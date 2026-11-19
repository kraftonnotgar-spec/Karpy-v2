"""Browser-bound login challenges. Passwords alone never trust a new device."""
from __future__ import annotations

import asyncio
import hashlib
import re
import secrets
from datetime import timedelta

import jwt
from app.config import settings
from fastapi import HTTPException
from sqlalchemy import func, select, update

from karpy_platform.core.acl.models import User, UserMeta, utcnow
from karpy_platform.core.setting.store import setting_store

from .models import AuthChallenge
from .security import challenge_hash

CHALLENGE_COOKIE = "app_login_challenge"
DEVICE_COOKIE = "app_trusted_device"
RESEND_COOKIE = "app_login_resend"
TTL = 300
# Bumped by "sign out other devices": every remembered device must verify again.
DEVICE_EPOCH_KEY = "auth.device_epoch"


def device_epoch(user):
    for item in user.meta or []:
        if item.key == DEVICE_EPOCH_KEY and item.value:
            return item.value
    return "0"


async def revoke_trusted_devices(db, user_id):
    """Invalidate every remembered device of this user (caller commits)."""
    item = await db.scalar(select(UserMeta).where(UserMeta.user_id == user_id, UserMeta.key == DEVICE_EPOCH_KEY))
    value = secrets.token_hex(8)
    if item:
        item.value = value
    else:
        db.add(UserMeta(user_id=user_id, key=DEVICE_EPOCH_KEY, value=value))


def browser_hash(request):
    # The same browser on the same device, ignoring version numbers: automatic browser updates
    # change them every few weeks and must not make a trusted device look new.
    agent = re.sub(r"\d+(?:[._]\d+)*", "", request.headers.get("user-agent", ""))
    return hashlib.sha256(agent.encode()).hexdigest()


def password_binding(user):
    return challenge_hash(user.id, user.password)


# Mobile app: the "browser" is a client-generated device id (random, 32+ chars). Only its
# hash is ever stored or signed; the challenge and resend tokens travel in the JSON body.
MOBILE_PREFIX = "m."
MOBILE_DEVICE_AUDIENCE = "app-trusted-mobile-device"
TRUSTED_DAYS = 30


def mobile_device_hash(device_id):
    return hashlib.sha256(("app-mobile-device:" + device_id).encode()).hexdigest()


def _binding(request, device):
    return device if device else browser_hash(request)


def _token_valid(token, device):
    return len(token) == 45 and (token[:2] == MOBILE_PREFIX if device else token[:2] in {"r.", "s."})


def recognized(request, user):
    try:
        claims = jwt.decode(request.cookies.get(DEVICE_COOKIE, ""), settings.JWT_SECRET,
                            algorithms=[settings.JWT_ALGORITHM], audience="app-trusted-device",
                            options={"require": ["exp", "iat", "sub", "binding", "browser"]})
        return (claims["sub"] == user.id and
                secrets.compare_digest(claims["binding"], password_binding(user)) and
                secrets.compare_digest(claims["browser"], browser_hash(request)) and
                secrets.compare_digest(str(claims.get("epoch", "0")), device_epoch(user)))
    except (jwt.InvalidTokenError, TypeError):
        return False


def mobile_recognized(token, user, device):
    """The mobile counterpart of the trusted-device cookie, with the same invalidation rules."""
    if not token or not device:
        return False
    try:
        claims = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM],
                            audience=MOBILE_DEVICE_AUDIENCE,
                            options={"require": ["exp", "iat", "sub", "binding", "device"]})
        return (claims["sub"] == user.id and
                secrets.compare_digest(claims["binding"], password_binding(user)) and
                secrets.compare_digest(claims["device"], device) and
                secrets.compare_digest(str(claims.get("epoch", "0")), device_epoch(user)))
    except (jwt.InvalidTokenError, TypeError):
        return False


def trust_mobile_device(user, device):
    now = utcnow()
    return jwt.encode({"sub": user.id, "aud": MOBILE_DEVICE_AUDIENCE, "iat": now,
                       "exp": now + timedelta(days=TRUSTED_DAYS), "binding": password_binding(user),
                       "device": device, "epoch": device_epoch(user)}, settings.JWT_SECRET,
                      algorithm=settings.JWT_ALGORITHM)


def set_cookie(response, name, value, age):
    response.set_cookie(name, value, max_age=age, httponly=True,
                        secure=settings.secure_cookies, samesite="lax", path="/")


def trust_device(response, request, user):
    now = utcnow()
    token = jwt.encode({"sub": user.id, "aud": "app-trusted-device", "iat": now,
                        "exp": now + timedelta(days=30), "binding": password_binding(user),
                        "browser": browser_hash(request), "epoch": device_epoch(user)}, settings.JWT_SECRET,
                       algorithm=settings.JWT_ALGORITHM)
    set_cookie(response, DEVICE_COOKIE, token, 30 * 86400)


def challenge_purpose(token):
    return "login:" + hashlib.sha256(token.encode()).hexdigest()[:32]


def proof(db_user, request, code, device=None):
    return code + password_binding(db_user) + _binding(request, device) + (db_user.phone or "") + db_user.email


async def start(db, request, response, user, remember, *, resending=False, device=None):
    """Send a sign-in code. `device` (a mobile_device_hash) switches to the mobile app:
    the challenge/resend tokens are returned in the body instead of cookies."""
    from . import extensions
    from .routes import _event, _new_challenge, _send_code
    from . import login_delivery

    # Serialize issuance/attempts for this identity, including concurrent requests.
    await db.execute(update(User).where(User.id == user.id).values(updated_at=User.updated_at))
    now = utcnow()
    recent = await db.scalar(select(func.count()).select_from(AuthChallenge).where(
        AuthChallenge.user_id == user.id, AuthChallenge.purpose.like("login:%"),
        AuthChallenge.created_at > now - timedelta(minutes=15)))
    latest = await db.scalar(select(AuthChallenge).where(
        AuthChallenge.user_id == user.id, AuthChallenge.purpose.like("login:%")
    ).order_by(AuthChallenge.created_at.desc()))
    if recent >= 5 or latest and latest.created_at > now - timedelta(seconds=60):
        raise HTTPException(429, {"form": "Please wait before requesting another sign-in code."}, headers={"Retry-After": "60"})
    # SMS goes too when an SMS provider plugin is registered and the phone is verified.
    sms = await extensions.sms_client(db) if extensions.phone_binding(user) else None
    sms_text = extensions.sms_code_text(await setting_store.all(db, flat=True, force=True), "login", "{code}") if sms else ""
    await db.execute(update(AuthChallenge).where(AuthChallenge.user_id == user.id,
        AuthChallenge.purpose.like("login:%"), AuthChallenge.consumed_at.is_(None)).values(consumed_at=now))
    # The remember choice is bound to an unpredictable, HttpOnly browser token.
    prefix = MOBILE_PREFIX if device else ("r." if remember else "s.")
    token = prefix + secrets.token_urlsafe(32)
    challenge, code = await _new_challenge(db, user, challenge_purpose(token))
    challenge.code_hash = challenge_hash(challenge.id, proof(user, request, code, device))
    challenge.expires_at = now + timedelta(seconds=TTL)
    await db.commit()
    activity = await login_delivery.begin(db, user, challenge, sms)

    try:
        if sms:
            # SMS has no database work. Only email uses this session; wait for
            # both deliveries before changing or invalidating the challenge.
            results = await asyncio.gather(
                sms.send_sms(user.phone, sms_text.replace("{code}", code), "login-" + challenge.id, otp=True),
                _send_code(db, user, code, "plugins.auth.login-code"),
                return_exceptions=True,
            )
            await login_delivery.finish(db, activity, {"sms": results[0], "email": results[1]})
            if any(isinstance(result, BaseException) for result in results):
                raise RuntimeError("Sign-in delivery failed")
            if results[0].test or results[0].status not in {"queued", "processing", "pending", "sent", "delivered", "accepted"}:
                raise RuntimeError("SMS was not accepted")
        else:
            results = await asyncio.gather(_send_code(db, user, code, "plugins.auth.login-code"), return_exceptions=True)
            await login_delivery.finish(db, activity, {"email": results[0]})
            if isinstance(results[0], BaseException):
                raise RuntimeError("Sign-in delivery failed")
    except Exception:  # noqa: BLE001 - Never issue a login proof after any delivery failure.
        challenge.consumed_at = utcnow()
        await _event(db, request, user.email, "login.delivery_failed", user.id)
        await db.commit()
        raise HTTPException(503, {"form": "We could not deliver your sign-in code. Please try again later."}) from None
    result = {"requiresOTP": True, "channels": ["email", "sms"] if sms else ["email"], "resend_after": 60}
    if device:
        result.update(challenge_token=token, challenge_expires_in=TTL)
    else:
        set_cookie(response, CHALLENGE_COOKIE, token, TTL)
    if not resending:
        await db.execute(update(AuthChallenge).where(AuthChallenge.user_id == user.id,
            AuthChallenge.purpose.like("resend:%"), AuthChallenge.consumed_at.is_(None)).values(consumed_at=utcnow()))
        retry_token = prefix + secrets.token_urlsafe(32)
        retry, _ = await _new_challenge(db, user, "resend:" + challenge_purpose(retry_token)[6:])
        retry.code_hash = challenge_hash(retry.id, password_binding(user) + _binding(request, device))
        retry.expires_at = utcnow() + timedelta(minutes=15)
        await db.commit()
        if device:
            result.update(resend_token=retry_token, resend_expires_in=900)
        else:
            set_cookie(response, RESEND_COOKIE, retry_token, 900)
    response.headers["Cache-Control"] = "no-store"
    return result


async def resend(db, request, response, *, token=None, device=None):
    from sqlalchemy.orm import selectinload
    from .account_state import account_status

    if token is None:
        token = "" if device else request.cookies.get(RESEND_COOKIE, "")
    invalid = HTTPException(422, {"form": "Your sign-in attempt expired. Please sign in again."})
    if not _token_valid(token, device):
        raise invalid
    retry = await db.scalar(select(AuthChallenge).where(
        AuthChallenge.purpose == "resend:" + challenge_purpose(token)[6:]))
    if not retry:
        raise invalid
    await db.execute(update(User).where(User.id == retry.user_id).values(updated_at=User.updated_at))
    await db.refresh(retry)
    user = await db.scalar(select(User).options(selectinload(User.meta)).where(User.id == retry.user_id).execution_options(populate_existing=True))
    if (retry.consumed_at or retry.expires_at <= utcnow() or not user or not user.email_verified_at
            or account_status(user) != "active" or not secrets.compare_digest(
                retry.code_hash, challenge_hash(retry.id, password_binding(user) + _binding(request, device)))):
        raise invalid
    return await start(db, request, response, user, bool(device) or token.startswith("r."), resending=True, device=device)


async def consume(db, request, code, *, token=None, device=None):
    if token is None:
        token = "" if device else request.cookies.get(CHALLENGE_COOKIE, "")
    if not _token_valid(token, device):
        raise HTTPException(422, {"code": "The sign-in code is invalid or expired."})
    purpose = challenge_purpose(token)
    identity = await db.scalar(select(AuthChallenge.user_id).where(AuthChallenge.purpose == purpose))
    if identity:
        await db.execute(update(User).where(User.id == identity).values(updated_at=User.updated_at))
    challenge = await db.scalar(select(AuthChallenge).where(AuthChallenge.purpose == purpose).execution_options(populate_existing=True))
    if not challenge or challenge.consumed_at or challenge.expires_at <= utcnow() or challenge.attempts >= 5:
        raise HTTPException(422, {"code": "The sign-in code is invalid or expired."})
    challenge.attempts += 1
    user = await db.get(User, identity, populate_existing=True)
    if not user or not secrets.compare_digest(challenge.code_hash, challenge_hash(challenge.id, proof(user, request, code, device))):
        await db.commit()
        raise HTTPException(422, {"code": "The sign-in code is invalid or expired."})
    challenge.consumed_at = utcnow()
    await db.execute(update(AuthChallenge).where(AuthChallenge.user_id == identity,
        AuthChallenge.purpose.like("resend:%"), AuthChallenge.consumed_at.is_(None)).values(consumed_at=utcnow()))
    return identity, bool(device) or token.startswith("r.")
