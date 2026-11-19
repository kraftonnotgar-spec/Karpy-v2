"""Sign-in for the mobile app. Contract: MOBILE_AUTH.md.

Same password, lockout, rate-limit, suspension and new-device code rules as the
browser sign-in in routes.py (the same functions run); the differences are only
transport: tokens and the code-challenge state travel in the JSON body, never in
cookies, and the "trusted device" is a server-signed token bound to the app's
device id hash, the password and the device epoch.

Extension points (``extensions.py``): ``auth.mobile.allow_user`` (who may use the app),
``auth.mobile.integrity`` (genuine-app checks) and ``auth.mobile.session_ended``.
"""
from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.database import get_db
from karpy_platform.core.acl.models import User, utcnow
from karpy_platform.core.acl.routes import user_payload

from . import extensions
from .account_state import account_status, account_status_body, account_status_code, account_status_message, account_status_reason
from .models import AuthSession, PushDevice
from .schemas import (
    MobileDevice,
    MobileLoginRequest,
    MobileLogoutRequest,
    MobileRefreshRequest,
    MobileResendLoginRequest,
    MobileVerifyLoginRequest,
    PushDeviceRemoveRequest,
    PushDeviceRequest,
)
from .security import MOBILE_CLIENT, current_user, is_mobile_bearer, issue_access_token, mobile_bearer_claims

router = APIRouter()

PLATFORM_LABELS = {"ios": "iOS", "android": "Android"}
MOBILE_AGENT_SUFFIX = " app"
STAFF_REFUSED = {
    "form": "Staff accounts sign in on the web.",
    "mobileAccess": "staff_not_allowed",
}


def _agent_prefix() -> str:
    return (settings.AUTH_MOBILE_APP_LABEL or settings.APP_NAME).strip() + " "


def device_label(device: MobileDevice) -> str:
    """What GET /user/sessions shows for this session, e.g. "Karpy iOS app · Amina's iPhone"."""
    label = f"{_agent_prefix()}{PLATFORM_LABELS[device.platform]}{MOBILE_AGENT_SUFFIX}"
    return f"{label} · {device.device_name}" if device.device_name else label


def is_mobile_session(session: AuthSession) -> bool:
    agent = session.user_agent or ""
    return any(f" {label}{MOBILE_AGENT_SUFFIX}" in agent for label in PLATFORM_LABELS.values())


def platform_of(agent: str | None) -> str:
    agent = agent or ""
    return next((key for key, label in PLATFORM_LABELS.items() if f" {label}{MOBILE_AGENT_SUFFIX}" in agent), "android")


async def _refused(user: User) -> bool:
    """True when this account may not use the app (staff by default, plus any plugin rule)."""
    from karpy_platform.core.acl.routes import admin_capable
    allowed = settings.AUTH_MOBILE_ALLOW_STAFF or not admin_capable(user)
    return not await extensions.filter_value("auth.mobile.allow_user", allowed, user)


def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


async def _genuine_app(db: AsyncSession, request: Request, purpose: str, platform: str, device: str, user_id: str | None = None) -> None:
    """Genuine-app checks registered by a plugin (``auth.mobile.integrity``); none by default."""
    await extensions.action("auth.mobile.integrity", db, request, purpose, platform, device, user_id)


def _closed_detail(user: User | None, state: str) -> dict:
    """Sign-in refusal for a deactivated or banned account: the web fields plus ``code`` and ``reason``."""
    return {"form": account_status_message(state), "accountStatus": state,
            "code": account_status_code(state), "reason": account_status_reason(user) or None}


async def _forget_push_device(db: AsyncSession, user_id: str, raw_device_id: str) -> None:
    """A closed account's app is wiped: drop this installation's push registration."""
    from .device_verification import mobile_device_hash
    try:
        async with db.begin_nested():
            await db.execute(delete(PushDevice).where(
                PushDevice.installation_hash == mobile_device_hash(raw_device_id), PushDevice.user_id == user_id))
    except Exception:  # noqa: BLE001 - never blocks the answer
        pass


async def _session_ended(db: AsyncSession, user_id: str, reason: str, session_id: str | None = None) -> None:
    await extensions.action("auth.mobile.session_ended", db, user_id, reason, session_id)


async def _closed_account(db: AsyncSession, data: MobileRefreshRequest, user: User | None, state: str) -> JSONResponse:
    if user is not None:
        await _forget_push_device(db, user.id, data.device_id)
        await _session_ended(db, user.id, "account_closed")
    await db.commit()
    return JSONResponse(account_status_body(user, state), status_code=status.HTTP_403_FORBIDDEN,
                        headers={"Cache-Control": "no-store"})


def _tokens(access: str, refresh: str) -> dict:
    return {
        "token_type": "Bearer",
        "access_token": access,
        "expires_in": settings.AUTH_ACCESS_TOKEN_MINUTES * 60,
        "refresh_token": refresh,
        "refresh_expires_in": settings.AUTH_REMEMBER_DAYS * 86400,
    }


@router.post("/login")
async def mobile_login(data: MobileLoginRequest, request: Request, response: Response, db: AsyncSession = Depends(get_db)) -> dict:
    from .device_verification import mobile_device_hash, mobile_recognized, start
    from .routes import _create_session, _event, _password_sign_in

    email = str(data.email).strip().lower()
    device = mobile_device_hash(data.device_id)
    await _genuine_app(db, request, "sign_in", data.platform, device)
    try:
        user = await _password_sign_in(db, request, email, data.password,
                                       lambda item: mobile_recognized(data.device_token, item, device))
    except HTTPException as error:
        # The password was right and the account is closed: add the code and the admin's reason
        # so the app shows its "account closed" screen (same message as the web for the form).
        state = error.detail.get("accountStatus") if isinstance(error.detail, dict) else None
        if error.status_code == status.HTTP_403_FORBIDDEN and state in {"deactivated", "banned"}:
            closed = await db.scalar(select(User).options(selectinload(User.meta)).where(func.lower(User.email) == email))
            raise HTTPException(status.HTTP_403_FORBIDDEN, _closed_detail(closed, state)) from None
        raise
    if await _refused(user):
        await _event(db, request, email, "login.mobile_refused", user.id)
        await db.commit()
        raise HTTPException(status.HTTP_403_FORBIDDEN, STAFF_REFUSED)
    _no_store(response)
    if not mobile_recognized(data.device_token, user, device):
        # The challenge and resend tokens come back in the body; no cookie is set.
        return await start(db, request, Response(), user, True, device=device)
    session, access, refresh = await _create_session(db, request, user, True, device=device, user_agent=device_label(data))
    user.last_login = utcnow()
    await _event(db, request, email, "login.succeeded", user.id)
    await db.commit()
    return {"message": "Signed in successfully.", "user": user_payload(user), **_tokens(access, refresh)}


@router.post("/verify-login")
async def mobile_verify_login(data: MobileVerifyLoginRequest, request: Request, response: Response, db: AsyncSession = Depends(get_db)) -> dict:
    from .device_verification import TRUSTED_DAYS, consume, mobile_device_hash, trust_mobile_device
    from .routes import _client_data, _create_session, _event, _security_alert, _security_signal

    device = mobile_device_hash(data.device_id)
    await _genuine_app(db, request, "sign_in", data.platform, device)
    try:
        identity, _ = await consume(db, request, data.code, token=data.challenge_token, device=device)
    except HTTPException:
        await extensions.security_event("login.otp_failed", _client_data(request)[0])
        raise
    user = await db.scalar(select(User).options(selectinload(User.roles), selectinload(User.meta)).where(User.id == identity))
    if not user or not user.email_verified_at or account_status(user) != "active":
        await db.commit()
        if user and user.email_verified_at:
            raise HTTPException(403, _closed_detail(user, account_status(user)))
        raise HTTPException(403, {"form": "This account cannot sign in."})
    if await _refused(user):
        await db.commit()
        raise HTTPException(status.HTTP_403_FORBIDDEN, STAFF_REFUSED)
    session, access, refresh = await _create_session(db, request, user, True, device=device, user_agent=device_label(data))
    user.last_login = utcnow()
    # A new device signed in: plugins holding per-device keys can reset them.
    await _session_ended(db, user.id, "new_device")
    await _event(db, request, user.email, "login.otp_verified", user.id)
    alerted = await _security_alert(db, user.id, "sign_in.new_device", session.id)
    await db.commit()
    await _security_signal(alerted, user.id)
    _no_store(response)
    return {
        "user": user_payload(user),
        **_tokens(access, refresh),
        # Send back on the next /login from this device to skip the code for 30 days.
        "device_token": trust_mobile_device(user, device),
        "device_token_expires_in": TRUSTED_DAYS * 86400,
    }


@router.post("/resend-login")
async def mobile_resend_login(data: MobileResendLoginRequest, request: Request, response: Response, db: AsyncSession = Depends(get_db)) -> dict:
    from .device_verification import mobile_device_hash, resend

    result = await resend(db, request, Response(), token=data.resend_token, device=mobile_device_hash(data.device_id))
    _no_store(response)
    # The resend token stays valid (15 minutes from the first code); only the challenge rotates.
    return {**result, "resend_token": data.resend_token}


@router.post("/refresh")
async def mobile_refresh(data: MobileRefreshRequest, request: Request, response: Response, db: AsyncSession = Depends(get_db)) -> dict:
    from .device_verification import mobile_device_hash
    from .routes import REFRESH_REUSE_GRACE_SECONDS, _event, _new_refresh_token, refresh_hash

    raw = data.refresh_token
    device = mobile_device_hash(data.device_id)
    invalid = HTTPException(status.HTTP_401_UNAUTHORIZED, "This session is no longer valid.")
    session = await db.scalar(select(AuthSession).where(AuthSession.refresh_token_hash == refresh_hash(raw, device)))
    if not session and "." in raw:
        # A well-formed token whose session exists but whose secret (or device) does not
        # match was already rotated or stolen: end the session, as the browser refresh does.
        owner = await db.scalar(select(AuthSession).where(AuthSession.id == raw.split(".", 1)[0][:36]))
        if owner and not owner.revoked_at:
            concurrent = owner.last_used_at and owner.last_used_at > utcnow() - timedelta(seconds=REFRESH_REUSE_GRACE_SECONDS)
            if concurrent:
                # Two refreshes raced; the winner's tokens are valid, this one retries.
                raise invalid
            owner.revoked_at = utcnow()
            user_row = await db.get(User, owner.user_id)
            await _event(db, request, user_row.email if user_row else owner.user_id, "session.refresh_reuse", owner.user_id)
            await db.commit()
        raise invalid
    if not session:
        raise invalid
    user = await db.scalar(select(User).options(selectinload(User.roles), selectinload(User.meta)).where(User.id == session.user_id))
    state = account_status(user) if user else "deactivated"
    if session.revoked_at or session.expires_at <= utcnow():
        # Deactivating or banning ends every session at once; the app's own (current) refresh
        # token still learns why, so it can show the "account closed" screen instead of sign-in.
        if user and state != "active":
            return await _closed_account(db, data, user, state)
        raise invalid
    if not user or state != "active":
        session.revoked_at = utcnow()
        return await _closed_account(db, data, user, state)
    if await _refused(user):
        session.revoked_at = utcnow()
        await db.commit()
        raise HTTPException(status.HTTP_403_FORBIDDEN, STAFF_REFUSED)
    await _genuine_app(db, request, "session", platform_of(session.user_agent), device, user.id)
    new_refresh = _new_refresh_token(session.id)
    session.refresh_token_hash = refresh_hash(new_refresh, device)
    session.last_used_at = utcnow()
    access = issue_access_token(session.user_id, session.id, MOBILE_CLIENT)
    await db.commit()
    _no_store(response)
    return {"message": "Session refreshed.", **_tokens(access, new_refresh)}


@router.post("/logout")
async def mobile_logout(request: Request, response: Response, data: MobileLogoutRequest | None = None,
                        db: AsyncSession = Depends(get_db)) -> dict:
    """End this app session: by the bearer's session, else by refresh token + device id."""
    from .device_verification import mobile_device_hash
    from .routes import refresh_hash

    session = None
    claims = mobile_bearer_claims(request)
    if claims:
        session = await db.scalar(select(AuthSession).where(AuthSession.id == claims["sid"], AuthSession.user_id == claims["sub"]))
    if not session and data and data.refresh_token and data.device_id:
        session = await db.scalar(select(AuthSession).where(
            AuthSession.refresh_token_hash == refresh_hash(data.refresh_token, mobile_device_hash(data.device_id))))
    if session and not session.revoked_at:
        session.revoked_at = utcnow()
        await _session_ended(db, session.user_id, "signed_out", session.id)
        await db.commit()
    _no_store(response)
    return {"message": "Signed out successfully."}


@router.get("/me")
async def mobile_me(request: Request, response: Response, user: User = Depends(current_user)) -> dict:
    from .routes import me

    if not is_mobile_bearer(request):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Authentication is required.")
    if await _refused(user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, STAFF_REFUSED)
    _no_store(response)
    return await me(user)


def _require_mobile(request: Request) -> None:
    if not is_mobile_bearer(request):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Authentication is required.")


@router.post("/push-devices")
async def register_push_device(data: PushDeviceRequest, request: Request, response: Response,
                               user: User = Depends(current_user), db: AsyncSession = Depends(get_db)) -> dict:
    """Register (or move) this installation's push token. A push provider plugin sends to it."""
    from .device_verification import mobile_device_hash

    _require_mobile(request)
    installation = mobile_device_hash(data.device_id)
    row = await db.scalar(select(PushDevice).where(PushDevice.installation_hash == installation))
    if row is None:
        row = PushDevice(installation_hash=installation, user_id=user.id, platform=data.platform,
                         provider=data.provider, token=data.token)
        db.add(row)
    row.user_id, row.platform, row.provider, row.token = user.id, data.platform, data.provider, data.token
    row.app_version = data.app_version
    row.updated_at = utcnow()
    await db.commit()
    _no_store(response)
    return {"registered": True}


@router.delete("/push-devices")
async def remove_push_device(data: PushDeviceRemoveRequest, request: Request, response: Response,
                             user: User = Depends(current_user), db: AsyncSession = Depends(get_db)) -> dict:
    from .device_verification import mobile_device_hash

    _require_mobile(request)
    await db.execute(delete(PushDevice).where(PushDevice.installation_hash == mobile_device_hash(data.device_id),
                                              PushDevice.user_id == user.id))
    await db.commit()
    _no_store(response)
    return {"removed": True}
