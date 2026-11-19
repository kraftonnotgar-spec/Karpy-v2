from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import secrets
import time
from typing import Any
from urllib.parse import urlencode, urlparse

import httpx
import jwt
from jwt import PyJWK
from jwt.exceptions import InvalidTokenError
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from karpy_platform.core.acl.models import Role, RoleUser, User, utcnow as acl_utcnow
from karpy_platform.core.acl.routes import hash_password
from karpy_platform.core.setting.store import setting_store
from karpy_platform.plugins.social_login.models.social_account import OAuthFlow, SocialAccount, utcnow as oauth_utcnow


GOOGLE_AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"
GOOGLE_ISSUERS = ("https://accounts.google.com", "accounts.google.com")
FLOW_LIFETIME = timedelta(minutes=10)


class SocialLoginError(RuntimeError):
    pass


@dataclass(frozen=True)
class GoogleConfiguration:
    globally_enabled: bool
    enabled: bool
    client_id: str
    client_secret: str
    allow_registration: bool
    style: str
    callback_url: str

    @property
    def configured(self) -> bool:
        return bool(self.globally_enabled and self.enabled and self.client_id and self.client_secret)


_jwks_cache: tuple[float, dict[str, Any]] | None = None


def _truthy(value: Any) -> bool:
    return value is True or str(value).strip().lower() in {"1", "true", "yes", "on"}


async def google_configuration(db: AsyncSession) -> GoogleConfiguration:
    values = await setting_store.all(db, flat=True)
    callback_url = f"{settings.APP_URL.rstrip('/')}/api/plugins/social_login/google/callback"
    style = str(values.get("social_login_style") or "basic")
    if style not in {"default", "basic", "minimal"}:
        style = "basic"
    return GoogleConfiguration(
        globally_enabled=_truthy(values.get("social_login_enable", False)),
        enabled=_truthy(values.get("social_login_google_enable", False)),
        client_id=str(values.get("social_login_google_client_id") or "").strip(),
        client_secret=str(values.get("social_login_google_client_secret") or "").strip(),
        allow_registration=_truthy(values.get("social_login_google_allow_registration", False)),
        style=style,
        callback_url=callback_url,
    )


def safe_return_to(value: str | None, request_origin: str) -> str:
    fallback = f"{request_origin.rstrip('/')}/admin"
    if not value:
        return fallback
    parsed = urlparse(value)
    origin = urlparse(request_origin)
    if parsed.scheme == origin.scheme and parsed.netloc == origin.netloc:
        return value
    if value.startswith("/") and not value.startswith("//"):
        return f"{request_origin.rstrip('/')}{value}"
    return fallback


def _state_hash(state: str) -> str:
    return hashlib.sha256(state.encode("utf-8")).hexdigest()


def _pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


async def create_google_flow(db: AsyncSession, config: GoogleConfiguration, return_to: str, *, provider: str = "google") -> str:
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    await db.execute(delete(OAuthFlow).where(OAuthFlow.expires_at < oauth_utcnow()))
    db.add(
        OAuthFlow(
            provider=provider,
            state_hash=_state_hash(state),
            nonce=nonce,
            code_verifier=verifier,
            return_to=return_to,
            expires_at=oauth_utcnow() + FLOW_LIFETIME,
        )
    )
    await db.commit()
    query = urlencode(
        {
            "client_id": config.client_id,
            "redirect_uri": config.callback_url,
            "response_type": "code",
            "scope": "openid email profile",
            "state": state,
            "nonce": nonce,
            "code_challenge": _pkce_challenge(verifier),
            "code_challenge_method": "S256",
            "prompt": "select_account",
        }
    )
    return f"{GOOGLE_AUTHORIZE_URL}?{query}"


async def consume_flow(db: AsyncSession, state: str, *, provider: str = "google") -> OAuthFlow:
    flow = await db.scalar(select(OAuthFlow).where(OAuthFlow.state_hash == _state_hash(state), OAuthFlow.provider == provider))
    now = datetime.now(timezone.utc)
    if not flow or flow.used_at is not None:
        raise SocialLoginError("This Google login request is invalid or has already been used.")
    expires_at = flow.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at <= now:
        raise SocialLoginError("This Google login request expired. Please try again.")
    consumed = await db.execute(update(OAuthFlow).where(OAuthFlow.id == flow.id, OAuthFlow.used_at.is_(None)).values(used_at=oauth_utcnow()))
    if consumed.rowcount != 1:
        raise SocialLoginError("This Google login request has already been used.")
    await db.commit()
    return flow


async def exchange_code(config: GoogleConfiguration, flow: OAuthFlow, code: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": config.client_id,
                "client_secret": config.client_secret,
                "redirect_uri": config.callback_url,
                "grant_type": "authorization_code",
                "code_verifier": flow.code_verifier,
            },
        )
    if response.status_code >= 400:
        raise SocialLoginError("Google could not complete the authorization request. Check the client credentials and callback URL.")
    payload = response.json()
    if not payload.get("id_token"):
        raise SocialLoginError("Google did not return a verified identity token.")
    return payload


async def _google_jwks() -> dict[str, Any]:
    global _jwks_cache
    if _jwks_cache and _jwks_cache[0] > time.time():
        return _jwks_cache[1]
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(GOOGLE_JWKS_URL)
        response.raise_for_status()
    keys = response.json()
    _jwks_cache = (time.time() + 3600, keys)
    return keys


async def verify_google_identity(id_token: str, config: GoogleConfiguration, nonce: str) -> dict[str, Any]:
    try:
        header = jwt.get_unverified_header(id_token)
        keys = await _google_jwks()
        key = next((item for item in keys.get("keys", []) if item.get("kid") == header.get("kid")), None)
        if not key:
            raise SocialLoginError("Google's signing key could not be found.")
        claims = jwt.decode(
            id_token,
            PyJWK.from_dict(key).key,
            algorithms=["RS256"],
            audience=config.client_id,
            options={"verify_at_hash": False},
        )
    except SocialLoginError:
        raise
    except (InvalidTokenError, ValueError, StopIteration) as exc:
        raise SocialLoginError("Google returned an invalid identity token.") from exc
    if claims.get("iss") not in GOOGLE_ISSUERS:
        raise SocialLoginError("Google returned an identity token from an invalid issuer.")
    if not secrets.compare_digest(str(claims.get("nonce") or ""), nonce):
        raise SocialLoginError("Google login nonce validation failed.")
    if not _truthy(claims.get("email_verified")):
        raise SocialLoginError("Google has not verified this email address.")
    if not claims.get("sub") or not claims.get("email"):
        raise SocialLoginError("Google did not provide the required account identity.")
    return claims


async def _unique_username(db: AsyncSession, email: str) -> str:
    base = "".join(char if char.isalnum() else "-" for char in email.split("@", 1)[0].lower()).strip("-") or "user"
    candidate = base[:100]
    suffix = 1
    while await db.scalar(select(User.id).where(func.lower(User.username) == candidate.lower())):
        suffix += 1
        candidate = f"{base[:90]}-{suffix}"
    return candidate


async def _registration_open(db: AsyncSession) -> bool:
    """The platform-wide "New account registration" switch overrides every Google sign-up option."""
    from karpy_platform.plugins.auth.extensions import registration_open

    return await registration_open(db)


async def resolve_social_user(db: AsyncSession, claims: dict[str, Any], allow_registration: bool) -> User:
    provider_id = str(claims["sub"])
    email = str(claims["email"]).strip().lower()
    social = await db.scalar(select(SocialAccount).where(SocialAccount.provider == "google", SocialAccount.provider_user_id == provider_id))
    if social:
        user = await db.get(User, social.user_id)
        if not user:
            raise SocialLoginError("The linked KARPy account no longer exists.")
    else:
        user = await db.scalar(select(User).where(func.lower(User.email) == email))
        if not user:
            if not allow_registration or not await _registration_open(db):
                raise SocialLoginError("No KARPy account uses this Google email. Ask an administrator to create or link the account.")
            names = str(claims.get("name") or email).strip().split(maxsplit=1)
            user = User(
                first_name=str(claims.get("given_name") or names[0] or "Google")[:120],
                last_name=str(claims.get("family_name") or (names[1] if len(names) > 1 else "User"))[:120],
                username=await _unique_username(db, email),
                email=email,
                password=hash_password(secrets.token_urlsafe(36)),
                avatar=str(claims.get("picture") or "")[:500] or None,
                email_verified_at=acl_utcnow(),
                super_user=False,
                manage_supers=False,
                permissions={},
            )
            db.add(user)
            await db.flush()
            # The new account's services come from the platform defaults at creation time.
            from karpy_platform.plugins.auth.extensions import action
            await action("auth.account_registered", db, user.id)
            default_role = await db.scalar(select(Role).where(Role.is_default.is_(True)).order_by(Role.created_at.asc()))
            if default_role:
                db.add(RoleUser(user_id=user.id, role_id=default_role.id))
        social = SocialAccount(user_id=user.id, provider="google", provider_user_id=provider_id, email=email)
        db.add(social)

    social.email = email
    social.name = str(claims.get("name") or "")[:255] or None
    social.avatar = str(claims.get("picture") or "")[:1000] or None
    social.last_login_at = oauth_utcnow()
    user.last_login = acl_utcnow()
    if not user.email_verified_at:
        user.email_verified_at = acl_utcnow()
    await db.commit()
    return user
