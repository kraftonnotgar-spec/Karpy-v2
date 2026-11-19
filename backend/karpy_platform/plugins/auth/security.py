from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, Request, status
import jwt
from jwt.exceptions import InvalidTokenError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.database import get_db
from karpy_platform.core.acl.models import User, utcnow
from karpy_platform.plugins.auth.models import AuthSession
from karpy_platform.plugins.auth.account_state import account_status, account_status_message

ACCESS_COOKIE = "karpy_user_access"
REFRESH_COOKIE = "karpy_user_refresh"


def token_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def challenge_hash(challenge_id: str, code: str) -> str:
    message = f"{challenge_id}:{code}".encode("utf-8")
    return hmac.new(settings.JWT_SECRET.encode("utf-8"), message, hashlib.sha256).hexdigest()


MOBILE_CLIENT = "mobile"
# Cookies that carry ambient credentials. A mobile bearer request carrying any of
# them is treated as a browser request (Origin/CSRF checks apply, bearer refused).
AMBIENT_AUTH_COOKIES = (ACCESS_COOKIE, REFRESH_COOKIE, "karpy_admin_session")


def issue_access_token(user_id: str, session_id: str, client: str | None = None) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "sid": session_id,
        "type": "access",
        "iat": now,
        "nbf": now,
        "exp": now + timedelta(minutes=settings.AUTH_ACCESS_TOKEN_MINUTES),
        "jti": secrets.token_urlsafe(16),
        "iss": settings.APP_URL.rstrip("/"),
    }
    if client:
        payload["client"] = client
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(value: str) -> dict:
    try:
        payload = jwt.decode(
            value,
            settings.JWT_SECRET,
            algorithms=[settings.JWT_ALGORITHM],
            issuer=settings.APP_URL.rstrip("/"),
        )
    except InvalidTokenError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Authentication is required.") from exc
    if payload.get("type") != "access" or not payload.get("sub") or not payload.get("sid"):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Authentication is required.")
    return payload


def set_auth_cookies(response, access_token: str, refresh_token: str, remember: bool) -> None:
    cookie_common = {
        "httponly": True,
        "secure": settings.secure_cookies,
        "samesite": settings.SESSION_SAME_SITE,
        "path": "/",
    }
    response.set_cookie(
        ACCESS_COOKIE,
        access_token,
        max_age=settings.AUTH_ACCESS_TOKEN_MINUTES * 60,
        **cookie_common,
    )
    refresh_age = (settings.AUTH_REMEMBER_DAYS if remember else settings.AUTH_REFRESH_DAYS) * 86400
    response.set_cookie(REFRESH_COOKIE, refresh_token, max_age=refresh_age, **cookie_common)


def clear_auth_cookies(response) -> None:
    response.delete_cookie(ACCESS_COOKIE, path="/")
    response.delete_cookie(REFRESH_COOKIE, path="/")


def _bearer(request: Request) -> str:
    authorization = request.headers.get("authorization", "")
    return authorization[7:].strip() if authorization.lower().startswith("bearer ") else ""


def has_ambient_auth_cookie(request: Request) -> bool:
    return any(request.cookies.get(name) for name in AMBIENT_AUTH_COOKIES)


def mobile_bearer_claims(request: Request) -> dict | None:
    """Claims of a valid mobile-app access token sent as Bearer with no auth cookies, else None.

    Signature, expiry and the `client` claim only; the session row is checked by
    authenticated_session_user. Developer API keys and web access tokens return None.
    """
    raw = _bearer(request)
    if not raw or has_ambient_auth_cookie(request):
        return None
    try:
        claims = decode_access_token(raw)
    except HTTPException:
        return None
    return claims if claims.get("client") == MOBILE_CLIENT else None


def cookie_or_mobile_bearer(request: Request) -> bool:
    """Transport gate for merchant dashboard APIs.

    Browser: the HttpOnly access cookie and no Authorization header (unchanged).
    Mobile app: a mobile access token as Bearer and no ambient auth cookies.
    Anything else (developer keys, web tokens as bearer, mixed credentials) is refused.
    """
    if request.headers.get("authorization"):
        return mobile_bearer_claims(request) is not None
    return bool(request.cookies.get(ACCESS_COOKIE))


def is_mobile_bearer(request: Request) -> bool:
    """True once authenticated_session_user accepted a mobile bearer with no ambient cookies.

    Such a request carries no ambient credentials, so Origin/CSRF checks do not apply.
    """
    return bool(getattr(request.state, "mobile_bearer", False))


async def authenticated_session_user(request: Request, db: AsyncSession = Depends(get_db)) -> User:
    """Validate session identity only; never grant account/financial eligibility.

    Status endpoints may report restrictions to the current session owner. All
    privileged callers must still enforce their own account policy.
    """
    bearer = _bearer(request)
    raw_token = bearer or request.cookies.get(ACCESS_COOKIE)
    if not raw_token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Authentication is required.")
    payload = decode_access_token(raw_token)
    session = await db.scalar(
        select(AuthSession).where(
            AuthSession.id == payload["sid"],
            AuthSession.user_id == payload["sub"],
            AuthSession.revoked_at.is_(None),
            AuthSession.expires_at > utcnow(),
        )
    )
    if not session:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "This session is no longer valid.")
    user = await db.scalar(
        select(User).options(selectinload(User.roles), selectinload(User.meta)).where(User.id == payload["sub"])
    )
    if not user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Authentication is required.")
    request.state.auth_session = session
    request.state.mobile_bearer = bool(
        bearer and payload.get("client") == MOBILE_CLIENT and not has_ambient_auth_cookie(request)
    )
    return user


async def current_user(request: Request, db: AsyncSession = Depends(get_db)) -> User:
    user = await authenticated_session_user(request, db)
    if not user.email_verified_at:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Authentication is required.")
    state = account_status(user)
    if state != "active":
        session = request.state.auth_session
        session.revoked_at = utcnow()
        await db.commit()
        if is_mobile_bearer(request):
            # The app refreshes on 401 and the refresh answers 403 with the account code and reason.
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "This session is no longer valid.")
        raise HTTPException(status.HTTP_403_FORBIDDEN, account_status_message(state))
    return user
