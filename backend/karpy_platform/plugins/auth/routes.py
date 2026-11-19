from __future__ import annotations

import asyncio
import hashlib
import uuid
import secrets
from datetime import timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import desc, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.database import get_db
from karpy_platform.plugins.auth import extensions
from karpy_platform.core.acl.models import User, utcnow
from karpy_platform.core.acl.routes import hash_password, user_payload, verify_password
from karpy_platform.core.setting.mailer import MailDeliveryResult, mailer
from karpy_platform.core.setting.store import setting_store
from karpy_platform.plugins.auth.models import AuthChallenge, AuthSecurityEvent, AuthSession
from karpy_platform.plugins.auth.account_state import account_status, account_status_message
from karpy_platform.plugins.auth.schemas import (
    ForgotPasswordRequest,
    LoginRequest,
    RegisterRequest,
    ResendCodeRequest,
    ResetPasswordRequest,
    VerifyEmailRequest,
    VerifyLoginRequest,
)
from karpy_platform.plugins.auth.security import (
    MOBILE_CLIENT,
    REFRESH_COOKIE,
    challenge_hash,
    clear_auth_cookies,
    current_user,
    issue_access_token,
    set_auth_cookies,
    token_hash,
)

router = APIRouter()
VERIFICATION_TEMPLATE_KEY = "plugins.auth.email-verification"
PASSWORD_RESET_TEMPLATE_KEY = "plugins.auth.password-reset-code"


def _client_data(request: Request) -> tuple[str, str]:
    ip = request.client.host if request.client else "unknown"
    return ip[:64], request.headers.get("user-agent", "")[:500]


def _split_name(value: str) -> tuple[str, str]:
    parts = value.strip().split()
    return (parts[0], " ".join(parts[1:]) or "User")


async def _unique_username(db: AsyncSession, email: str) -> str:
    base = "".join(char for char in email.split("@", 1)[0].lower() if char.isalnum() or char in "-_")[:80] or "member"
    candidate, suffix = base, 1
    while await db.scalar(select(User.id).where(User.username == candidate)):
        suffix += 1
        candidate = f"{base}-{suffix}"
    return candidate


async def _event(db: AsyncSession, request: Request, identity: str, event: str, user_id: str | None = None) -> None:
    ip, agent = _client_data(request)
    db.add(AuthSecurityEvent(identity=identity[:160], event=event, user_id=user_id, ip_address=ip, user_agent=agent))
    # Per-IP attack detection (brute force, credential stuffing, code guessing, reset and sign-up floods).
    await extensions.security_event(event, ip, identity)


async def _login_failures(db: AsyncSession, identity: str, ip: str | None = None) -> int:
    since = utcnow() - timedelta(minutes=settings.AUTH_LOGIN_WINDOW_MINUTES)
    query = select(func.count()).select_from(AuthSecurityEvent).where(
        AuthSecurityEvent.identity == identity,
        AuthSecurityEvent.event == "login.failed",
        AuthSecurityEvent.created_at >= since,
    )
    if ip is not None:
        query = query.where(AuthSecurityEvent.ip_address == ip)
    return int(await db.scalar(query) or 0)


def _origin_allowed(request: Request) -> bool:
    from karpy_platform.core.acl.admin_guard import write_origin_allowed

    return write_origin_allowed(request)


async def _blocked(db: AsyncSession, identity: str) -> bool:
    since = utcnow() - timedelta(minutes=settings.AUTH_LOGIN_WINDOW_MINUTES)
    count = await db.scalar(
        select(func.count()).select_from(AuthSecurityEvent).where(
            AuthSecurityEvent.identity == identity,
            AuthSecurityEvent.event == "login.failed",
            AuthSecurityEvent.created_at >= since,
        )
    )
    return int(count or 0) >= settings.AUTH_MAX_LOGIN_ATTEMPTS


async def _send_code(db: AsyncSession, user: User, code: str, template_key: str) -> MailDeliveryResult:
    values = await setting_store.all(db, flat=True, force=True)
    if settings.is_production and str(values.get("email_driver") or "log").lower() in {"log", "array"}:
        raise RuntimeError("A real email delivery provider is required for account verification.")
    event = {"plugins.auth.login-code": "login.otp", PASSWORD_RESET_TEMPLATE_KEY: "password_reset.otp"}.get(template_key, "verification.otp")
    message = await extensions.code_message(db, event, "email", "en", {
        "verification_code": code, "expires_minutes": str(5 if template_key == "plugins.auth.login-code" else settings.AUTH_OTP_TTL_MINUTES),
        "member_name": user.name if hasattr(user, "name") else "",
    }, settings_values=values)
    result = await asyncio.to_thread(mailer.send, values, to=user.email, subject=message["subject"], html=message["html"], text=message["text"])
    if settings.is_production and not result.sent:
        raise RuntimeError("A real email delivery provider is required for account verification.")
    return result


async def _new_challenge(db: AsyncSession, user: User, purpose: str) -> tuple[AuthChallenge, str]:
    active = await db.scalars(
        select(AuthChallenge).where(
            AuthChallenge.user_id == user.id,
            AuthChallenge.purpose == purpose,
            AuthChallenge.consumed_at.is_(None),
        )
    )
    now = utcnow()
    for item in active:
        item.consumed_at = now
    code = f"{secrets.randbelow(1_000_000):06d}"
    challenge = AuthChallenge(
        user_id=user.id,
        purpose=purpose,
        code_hash="pending",
        expires_at=now + timedelta(minutes=settings.AUTH_OTP_TTL_MINUTES),
    )
    db.add(challenge)
    await db.flush()
    challenge.code_hash = challenge_hash(challenge.id, code)
    return challenge, code


REFRESH_REUSE_GRACE_SECONDS = 10


def _new_refresh_token(session_id: str) -> str:
    """`<session id>.<secret>`: the id lets a replayed old token be traced to its session."""
    return f"{session_id}.{secrets.token_urlsafe(48)}"


def refresh_hash(raw: str, device: str | None = None) -> str:
    """Stored refresh hash; a mobile session's token only matches together with its device."""
    return token_hash(f"{raw}:{device}" if device else raw)


async def _create_session(
    db: AsyncSession, request: Request, user: User, remember: bool, *,
    device: str | None = None, user_agent: str | None = None,
) -> tuple[AuthSession, str, str]:
    """`device` (a mobile device hash) makes a mobile-app session: refresh bound to the
    device, access tokens carry client=mobile, lifetime is the remembered one."""
    await extensions.action("auth.before_session", db, user, getattr(request.state, "request_id", uuid.uuid4().hex))
    session_id = str(uuid.uuid4())
    raw_refresh = _new_refresh_token(session_id)
    ip, agent = _client_data(request)
    if user_agent is not None:
        agent = user_agent[:500]
    days = settings.AUTH_REMEMBER_DAYS if remember else settings.AUTH_REFRESH_DAYS
    session = AuthSession(
        id=session_id,
        user_id=user.id,
        refresh_token_hash=refresh_hash(raw_refresh, device),
        user_agent=agent,
        ip_address=ip,
        remember=remember,
        expires_at=utcnow() + timedelta(days=days),
    )
    db.add(session)
    await db.flush()
    return session, issue_access_token(user.id, session.id, MOBILE_CLIENT if device else None), raw_refresh


# Registration must never reveal whether an email or phone already belongs to an
# account. Every outcome returns this same response; the real situation is only
# ever told to the owner of the inbox.
REGISTER_RESPONSE = {
    "message": "Check your email to continue. If this address can be used for a new account, we've sent a verification code.",
    "requiresVerification": True,
}
REGISTER_NOTICE_LIMIT_PER_HOUR = 3


async def _send_account_notice(db: AsyncSession, request: Request, email: str, kind: str, user_id: str | None = None) -> None:
    """Tell the inbox owner what happened, at most a few times an hour, never failing the request."""
    since = utcnow() - timedelta(hours=1)
    recent = await db.scalar(select(func.count()).select_from(AuthSecurityEvent).where(
        AuthSecurityEvent.identity == email,
        AuthSecurityEvent.event.in_(["register.existing_account", "register.not_created"]),
        AuthSecurityEvent.created_at >= since,
    ))
    await _event(db, request, email, f"register.{kind}", user_id)
    if int(recent or 0) >= REGISTER_NOTICE_LIMIT_PER_HOUR:
        return
    values = await setting_store.all(db, flat=True, force=True)
    name = extensions.app_name(values)
    if kind == "existing_account":
        subject = f"Someone tried to create a {name} account with your email"
        text = (f"Someone tried to create a new {name} account using this email address, "
                "but you already have an account.\n\n"
                "If it was you, sign in instead, or reset your password if you have forgotten it.\n"
                "If it wasn't you, you can ignore this email. Your account has not been changed.")
    else:
        subject = f"We couldn't create your {name} account"
        text = (f"We couldn't create a {name} account with the details you entered.\n\n"
                f"If you already have a {name} account, sign in or reset your password. "
                "Otherwise, sign up again with a different phone number, or contact support.")
    try:
        message = await extensions.email_layout(subject, text, values)
        await asyncio.to_thread(mailer.send, values, to=email, subject=message["subject"], html=message["html"], text=message["text"])
    except Exception:  # noqa: BLE001 - a notice failure must not reveal anything to the caller
        await _event(db, request, email, "register.notice_failed", user_id)


async def _admin_alert(db: AsyncSession, event: str, payload: dict, key: str) -> bool:
    """Queue an alert for admin notification recipients (delivered later by the worker); never raises."""
    try:
        return await extensions.admin_alert(db, event, payload, key)
    except Exception:  # noqa: BLE001 - an alert never changes the answer
        return False


async def _signup_attempt_alert(db: AsyncSession, user_id: str) -> bool:
    """In-app "Sign-up attempt with your email" for the account owner, throttled; never raises."""
    try:
        return await extensions.account_alert(db, user_id, "sign_up.attempt", "sign_up.attempt")
    except Exception:  # noqa: BLE001 - an alert never changes the answer
        return False


@router.post("/user/register", status_code=status.HTTP_201_CREATED)
async def register(data: RegisterRequest, request: Request, db: AsyncSession = Depends(get_db)) -> dict:
    from .phone_identity import PhoneIdentity, canonical_phone, reserve_phone
    auth_policy, _ = await extensions.policy(db)
    if not auth_policy.registration_open:
        # Paused by the platform admin: refuse before touching any account, the same for every email.
        # Admin alert recipients get one (hourly-bucketed) alert per address; it never changes the answer.
        if await _admin_alert(db, "signup.blocked", {"merchant_email": str(data.email), "reason": "sign-ups are paused"},
                              f"paused:{utcnow():%Y%m%d%H}:{hashlib.sha256(str(data.email).strip().lower().encode()).hexdigest()[:24]}"):
            await db.commit()
        raise HTTPException(status.HTTP_403_FORBIDDEN, "registration_closed")
    if auth_policy.require_terms and (not data.acceptTerms or data.policyVersion != auth_policy.version):
        raise HTTPException(422, {"form": "Accept the current Terms of Service and Privacy Policy."})
    email = str(data.email).strip().lower()
    if data.password != data.confirmPassword:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, {"confirmPassword": "The password confirmation does not match."})
    # Format checks only reveal the caller's own input, never other accounts.
    phone = canonical_phone(data.phone, auth_policy.phone_countries, data.country)
    response = {**REGISTER_RESPONSE, "email": email}
    # Hash on every path so existing and new emails take the same time.
    password_hash = hash_password(data.password)

    existing = await db.scalar(select(User).where(func.lower(User.email) == email))
    if existing:
        alerted = False
        if existing.email_verified_at:
            await _send_account_notice(db, request, email, "existing_account", existing.id)
            # In-app too (at most one an hour per account); the caller still sees the generic answer.
            alerted = await _signup_attempt_alert(db, existing.id)
        else:
            # Unfinished signup: give the inbox owner a fresh code (with the usual cooldown).
            latest = await db.scalar(select(AuthChallenge).where(AuthChallenge.user_id == existing.id).order_by(desc(AuthChallenge.created_at)))
            if not latest or latest.created_at <= utcnow() - timedelta(seconds=settings.AUTH_OTP_RESEND_SECONDS):
                _, code = await _new_challenge(db, existing, "verify-email")
                try:
                    await _send_code(db, existing, code, VERIFICATION_TEMPLATE_KEY)
                except Exception:  # noqa: BLE001 - same response either way
                    await _event(db, request, email, "register.delivery_failed", existing.id)
            await _event(db, request, email, "register.unverified_retry", existing.id)
        await db.commit()
        try:
            await _security_signal(alerted, existing.id)
        except Exception:  # noqa: BLE001 - a live badge refresh never changes the answer
            pass
        return response

    owned = await db.scalar(select(PhoneIdentity).where(PhoneIdentity.phone == phone, PhoneIdentity.user_id.is_not(None)))
    if owned:
        await _send_account_notice(db, request, email, "not_created")
        await db.commit()
        return response

    first_name, last_name = _split_name(data.name)
    user = User(
        first_name=first_name,
        last_name=last_name,
        username=await _unique_username(db, email),
        email=email,
        phone=phone,
        password=password_hash,
        permissions={},
        email_verified_at=None,
    )
    db.add(user)
    try:
        await db.flush()
        await reserve_phone(db, user, phone)
        # The new account's services come from the platform defaults at creation time.
        await extensions.action("auth.account_registered", db, user.id)
    except (IntegrityError, HTTPException):
        # Lost a race for this email or phone: answer exactly as for any other signup.
        await db.rollback()
        await _send_account_notice(db, request, email, "not_created")
        await db.commit()
        return response
    _, code = await _new_challenge(db, user, "verify-email")
    try:
        await _send_code(db, user, code, VERIFICATION_TEMPLATE_KEY)
    except Exception as exc:
        await db.rollback()
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, {"form": "We could not send the verification email. Please try again."}) from exc
    await _event(db, request, email, "register.created", user.id)
    await _admin_alert(db, "account.registered", {"merchant_id": user.id, "merchant": data.name, "merchant_email": email}, user.id)
    if data.acceptTerms:
        await _event(db, request, email, f"legal.accepted.v{auth_policy.version}", user.id)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        return response
    return response


@router.post("/user/verify-email")
async def verify_email(data: VerifyEmailRequest, request: Request, response: Response, db: AsyncSession = Depends(get_db)) -> dict:
    email = str(data.email).strip().lower()
    user = await db.scalar(
        select(User).options(selectinload(User.roles), selectinload(User.meta)).where(func.lower(User.email) == email)
    )
    # Unknown and already-verified emails answer exactly like a wrong code.
    if not user or user.email_verified_at:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, {"code": "The verification code is invalid or expired."})
    challenge = await db.scalar(
        select(AuthChallenge).where(
            AuthChallenge.user_id == user.id,
            AuthChallenge.purpose == "verify-email",
            AuthChallenge.consumed_at.is_(None),
        ).order_by(desc(AuthChallenge.created_at))
    )
    if not challenge or challenge.expires_at <= utcnow() or challenge.attempts >= settings.AUTH_OTP_MAX_ATTEMPTS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, {"code": "The verification code is invalid or expired."})
    challenge.attempts += 1
    if not secrets.compare_digest(challenge.code_hash, challenge_hash(challenge.id, data.code)):
        await _event(db, request, email, "otp.failed", user.id)
        await db.commit()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, {"code": "The verification code is invalid or expired."})
    challenge.consumed_at = utcnow()
    user.email_verified_at = utcnow()
    state = account_status(user)
    if state != "active":
        await db.commit()
        raise HTTPException(status.HTTP_403_FORBIDDEN, {"form": account_status_message(state), "accountStatus": state})
    session, access, refresh = await _create_session(db, request, user, False)
    await _event(db, request, email, "email.verified", user.id)
    await db.commit()
    set_auth_cookies(response, access, refresh, session.remember)
    response.headers["Cache-Control"] = "no-store"
    return {"message": "Email verified successfully.", "user": user_payload(user)}


@router.post("/user/resend-verification-code")
async def resend(data: ResendCodeRequest, request: Request, db: AsyncSession = Depends(get_db)) -> dict:
    email = str(data.email).strip().lower()
    user = await db.scalar(select(User).where(func.lower(User.email) == email))
    generic = {"message": "Request received. Only registered accounts awaiting email verification receive a code."}
    if not user or user.email_verified_at:
        return generic
    latest = await db.scalar(select(AuthChallenge).where(AuthChallenge.user_id == user.id).order_by(desc(AuthChallenge.created_at)))
    if latest and latest.created_at > utcnow() - timedelta(seconds=settings.AUTH_OTP_RESEND_SECONDS):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, {"form": "Please wait before requesting another code."})
    _, code = await _new_challenge(db, user, "verify-email")
    try:
        await _send_code(db, user, code, VERIFICATION_TEMPLATE_KEY)
    except Exception as exc:
        await db.rollback()
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, {"form": "We could not send the verification email. Please try again."}) from exc
    await _event(db, request, email, "otp.resent", user.id)
    await db.commit()
    return generic


@router.post("/user/forgot-password")
async def forgot_password(
    data: ForgotPasswordRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    email = str(data.email).strip().lower()
    user = await db.scalar(select(User).options(selectinload(User.meta)).where(func.lower(User.email) == email))
    generic = {"message": "If this account can reset its password, a reset code has been sent."}
    if not user:
        await _event(db, request, email, "password_reset.unknown_email")
        await db.commit()
        return generic
    if not user.email_verified_at:
        await _event(db, request, email, "password_reset.unverified", user.id)
        await db.commit()
        return generic

    await db.execute(update(User).where(User.id == user.id).values(updated_at=User.updated_at))

    latest = await db.scalar(
        select(AuthChallenge).where(
            AuthChallenge.user_id == user.id,
            AuthChallenge.purpose == "password-reset",
        ).order_by(desc(AuthChallenge.created_at))
    )
    if latest and latest.created_at > utcnow() - timedelta(seconds=settings.AUTH_OTP_RESEND_SECONDS):
        return generic

    # Cap codes per account: each code allows a few guesses, so unlimited codes
    # would let an attacker grind through the 6-digit space over days.
    async def issued_since(delta: timedelta) -> int:
        return int(await db.scalar(select(func.count()).select_from(AuthChallenge).where(
            AuthChallenge.user_id == user.id,
            AuthChallenge.purpose == "password-reset",
            AuthChallenge.created_at > utcnow() - delta,
        )) or 0)

    if (await issued_since(timedelta(hours=1)) >= settings.AUTH_RESET_CODES_PER_HOUR
            or await issued_since(timedelta(days=1)) >= settings.AUTH_RESET_CODES_PER_DAY):
        await _event(db, request, email, "password_reset.throttled", user.id)
        await db.commit()
        return generic

    _, code = await _new_challenge(db, user, "password-reset")
    try:
        sms = await extensions.sms_client(db) if extensions.phone_binding(user) else None
        if sms is not None:
            text = extensions.sms_code_text(await setting_store.all(db, flat=True, force=True), "reset", code)
            result = await sms.send_sms(user.phone, text, "reset-" + secrets.token_hex(16), otp=True)
            if result.test or result.status not in {"queued", "processing", "pending", "sent", "delivered", "accepted"}:
                raise RuntimeError("SMS delivery unavailable")
        await _send_code(db, user, code, PASSWORD_RESET_TEMPLATE_KEY)
    except Exception:
        await db.rollback()
        await _event(db, request, email, "password_reset.delivery_failed", user.id)
        await db.commit()
        return generic
    await _event(db, request, email, "password_reset.requested", user.id)
    await db.commit()
    return generic


async def _security_alert(db, user_id, event, key) -> bool:
    """In-app account alert in the merchant notification center; never blocks sign-in or reset."""
    try:
        return await extensions.account_alert(db, user_id, event, str(key))
    except Exception:  # noqa: BLE001 - never blocks sign-in or reset
        return False


async def _security_signal(alerted: bool, user_id) -> None:
    if alerted:
        await extensions.action("auth.account_signal", [user_id])


@router.post("/user/reset-password")
async def reset_password(
    data: ResetPasswordRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> dict:
    email = str(data.email).strip().lower()
    errors: dict[str, str] = {}
    if data.password != data.confirmPassword:
        errors["confirmPassword"] = "The password confirmation does not match."
    if errors:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, errors)

    user = await db.scalar(select(User).where(func.lower(User.email) == email))
    challenge = None
    if user:
        await db.execute(update(User).where(User.id == user.id).values(updated_at=User.updated_at))
        await db.refresh(user)
        challenge = await db.scalar(
            select(AuthChallenge).where(
                AuthChallenge.user_id == user.id,
                AuthChallenge.purpose == "password-reset",
                AuthChallenge.consumed_at.is_(None),
            ).order_by(desc(AuthChallenge.created_at))
        )
    invalid = (
        not user
        or not challenge
        or challenge.expires_at <= utcnow()
        or challenge.attempts >= settings.AUTH_OTP_MAX_ATTEMPTS
    )
    if invalid:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, {"code": "The reset code is invalid or expired."})

    challenge.attempts += 1
    if not secrets.compare_digest(challenge.code_hash, challenge_hash(challenge.id, data.code)):
        await _event(db, request, email, "password_reset.failed", user.id)
        await db.commit()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, {"code": "The reset code is invalid or expired."})

    now = utcnow()
    challenge.consumed_at = now
    user.password = hash_password(data.password)
    active_sessions = await db.scalars(
        select(AuthSession).where(AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None))
    )
    for session in active_sessions:
        session.revoked_at = now
    await _event(db, request, email, "password_reset.completed", user.id)
    alerted = await _security_alert(db, user.id, "password.changed", challenge.id)
    await db.commit()
    await _security_signal(alerted, user.id)
    clear_auth_cookies(response)
    response.headers["Cache-Control"] = "no-store"
    return {"message": "Your password has been reset. You can now sign in."}


async def _password_sign_in(db: AsyncSession, request: Request, email: str, password: str, is_recognized) -> User:
    """Shared by the browser and mobile sign-in: lockouts, password, verification and status.

    `is_recognized(user)` says whether the caller presented this account's trusted device.
    Returns the user or raises the same errors for both clients.
    """
    from karpy_platform.core.acl.routes import _DUMMY_PASSWORD_HASH

    too_many = HTTPException(
        status.HTTP_429_TOO_MANY_REQUESTS,
        {"form": "Too many sign-in attempts. Please try again later."},
        headers={"Retry-After": str(settings.AUTH_LOGIN_WINDOW_MINUTES * 60)},
    )
    ip, _ = _client_data(request)
    # Lockout is per account *and* IP, so an attacker cannot lock the owner out.
    if await _login_failures(db, email, ip) >= settings.AUTH_MAX_LOGIN_ATTEMPTS:
        await extensions.security_event("login.failed", ip, email)
        raise too_many
    user = await db.scalar(
        select(User).options(selectinload(User.roles), selectinload(User.meta)).where(func.lower(User.email) == email)
    )
    if user:
        await db.execute(update(User).where(User.id == user.id).values(updated_at=User.updated_at))
        await db.refresh(user, attribute_names=["password", "phone", "meta", "email_verified_at"])
    # Distributed guessing across many IPs is capped per account; the owner's
    # remembered device still gets through.
    if (await _login_failures(db, email) >= settings.AUTH_MAX_LOGIN_ATTEMPTS_PER_ACCOUNT
            and not (user and is_recognized(user))):
        raise too_many
    # One hash check either way, so unknown emails answer as slowly as wrong passwords.
    password_ok = verify_password(password, user.password if user else _DUMMY_PASSWORD_HASH)
    if not user or not password_ok:
        # Honeytoken check: only on this failure path, in memory, never changes the answer.
        extensions.failed_sign_in(request, "account", email, password, account_exists=user is not None)
        await _event(db, request, email, "login.failed", user.id if user else None)
        await db.commit()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, {"email": "These credentials do not match our records."})
    if not user.email_verified_at:
        raise HTTPException(status.HTTP_403_FORBIDDEN, {"email": "Please verify your email before signing in.", "requiresVerification": True})
    state = account_status(user)
    if state != "active":
        raise HTTPException(status.HTTP_403_FORBIDDEN, {"form": account_status_message(state), "accountStatus": state})
    return user


@router.post("/user/login")
async def login(data: LoginRequest, request: Request, response: Response, db: AsyncSession = Depends(get_db)) -> dict:
    from .device_verification import recognized, start

    email = str(data.email).strip().lower()
    user = await _password_sign_in(db, request, email, data.password, lambda item: recognized(request, item))
    if not recognized(request, user):
        return await start(db, request, response, user, data.remember)
    session, access, refresh = await _create_session(db, request, user, data.remember)
    user.last_login = utcnow()
    await _event(db, request, email, "login.succeeded", user.id)
    await db.commit()
    set_auth_cookies(response, access, refresh, session.remember)
    response.headers["Cache-Control"] = "no-store"
    return {"message": "Signed in successfully.", "user": user_payload(user), "expiresIn": settings.AUTH_ACCESS_TOKEN_MINUTES * 60}


@router.post("/user/verify-login")
async def verify_login(data: VerifyLoginRequest, request: Request, response: Response, db: AsyncSession = Depends(get_db)) -> dict:
    from .device_verification import CHALLENGE_COOKIE, RESEND_COOKIE, consume, trust_device
    try:
        identity, remember = await consume(db, request, data.code)
    except HTTPException:
        await extensions.security_event("login.otp_failed", _client_data(request)[0])
        raise
    user = await db.scalar(select(User).options(selectinload(User.roles), selectinload(User.meta)).where(User.id == identity))
    if not user or not user.email_verified_at or account_status(user) != "active":
        await db.commit()
        raise HTTPException(403, {"form": "This account cannot sign in."})
    session, access, refresh = await _create_session(db, request, user, remember)
    user.last_login = utcnow()
    await _event(db, request, user.email, "login.otp_verified", user.id)
    # The email/SMS code is only asked on a device this account has not trusted yet.
    alerted = await _security_alert(db, user.id, "sign_in.new_device", session.id)
    await db.commit()
    await _security_signal(alerted, user.id)
    set_auth_cookies(response, access, refresh, remember)
    response.delete_cookie(CHALLENGE_COOKIE, path="/")
    response.delete_cookie(RESEND_COOKIE, path="/")
    # A device that passed the email code is trusted for 30 days, whether the sign-in came from
    # the password form or Google, so the code is not asked again each time a session expires.
    # "Remember me" only decides how long the session itself lasts.
    trust_device(response, request, user)
    response.headers["Cache-Control"] = "no-store"
    return {"user": user_payload(user)}


@router.post("/user/resend-login")
async def resend_login(request: Request, response: Response, db: AsyncSession = Depends(get_db)) -> dict:
    from .device_verification import resend
    return await resend(db, request, response)


@router.post("/user/refresh")
async def refresh(request: Request, response: Response, db: AsyncSession = Depends(get_db)) -> dict:
    raw = request.cookies.get(REFRESH_COOKIE)
    if not raw or len(raw) > 256:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Authentication is required.")
    invalid = HTTPException(status.HTTP_401_UNAUTHORIZED, "This session is no longer valid.")
    session = await db.scalar(select(AuthSession).where(AuthSession.refresh_token_hash == token_hash(raw)))
    if not session and "." in raw:
        # A well-formed token whose session exists but whose secret is stale was
        # already rotated: someone is replaying a stolen token. End the session.
        owner = await db.scalar(select(AuthSession).where(AuthSession.id == raw.split(".", 1)[0][:36]))
        if owner and not owner.revoked_at:
            concurrent = owner.last_used_at and owner.last_used_at > utcnow() - timedelta(seconds=REFRESH_REUSE_GRACE_SECONDS)
            if concurrent:
                # Another tab just rotated this token. Keep the browser's fresh
                # cookies (shared across tabs) and let this request retry.
                raise invalid
            owner.revoked_at = utcnow()
            user_row = await db.get(User, owner.user_id)
            await _event(db, request, user_row.email if user_row else owner.user_id, "session.refresh_reuse", owner.user_id)
            await db.commit()
        clear_auth_cookies(response)
        raise invalid
    if not session or session.revoked_at or session.expires_at <= utcnow():
        clear_auth_cookies(response)
        raise invalid
    user = await db.scalar(select(User).options(selectinload(User.meta)).where(User.id == session.user_id))
    state = account_status(user) if user else "deactivated"
    if not user or state != "active":
        session.revoked_at = utcnow()
        await db.commit()
        clear_auth_cookies(response)
        raise HTTPException(status.HTTP_403_FORBIDDEN, account_status_message(state))
    new_refresh = _new_refresh_token(session.id)
    session.refresh_token_hash = token_hash(new_refresh)
    session.last_used_at = utcnow()
    access = issue_access_token(session.user_id, session.id)
    await db.commit()
    set_auth_cookies(response, access, new_refresh, session.remember)
    response.headers["Cache-Control"] = "no-store"
    return {"message": "Session refreshed.", "expiresIn": settings.AUTH_ACCESS_TOKEN_MINUTES * 60}


@router.post("/user/logout")
async def logout(request: Request, response: Response, db: AsyncSession = Depends(get_db)) -> dict:
    from .security import ACCESS_COOKIE, decode_access_token

    if not _origin_allowed(request):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "csrf_denied")
    session = None
    raw = request.cookies.get(REFRESH_COOKIE)
    if raw:
        session = await db.scalar(select(AuthSession).where(AuthSession.refresh_token_hash == token_hash(raw)))
    if not session and request.cookies.get(ACCESS_COOKIE):
        # No refresh cookie: still end the server-side session the access token names.
        try:
            claims = decode_access_token(request.cookies[ACCESS_COOKIE])
            session = await db.scalar(select(AuthSession).where(
                AuthSession.id == claims["sid"], AuthSession.user_id == claims["sub"]))
        except HTTPException:
            session = None
    if session and not session.revoked_at:
        session.revoked_at = utcnow()
        await db.commit()
    clear_auth_cookies(response)
    response.headers["Cache-Control"] = "no-store"
    return {"message": "Signed out successfully."}


@router.get("/user/me")
async def me(user: User = Depends(current_user)) -> dict:
    from .account_timezone import account_country, account_timezone
    # Display-only: the account's timezone follows its country (None when unknown).
    return {"user": {**user_payload(user), "timezone": account_timezone(user), "country": account_country(user)}}


@router.get("/user/trusted-device")
async def trusted_device(request: Request, user: User = Depends(current_user)) -> dict:
    from .device_verification import recognized
    return {"remembered": recognized(request, user)}


@router.post("/user/forget-device")
async def forget_device(request: Request, response: Response, user: User = Depends(current_user)) -> dict:
    from .device_verification import DEVICE_COOKIE
    extensions.csrf(request)
    response.delete_cookie(DEVICE_COOKIE, path="/")
    response.headers["Cache-Control"] = "no-store"
    return {"ok": True}


def session_client(item: AuthSession) -> str:
    from .mobile_routes import is_mobile_session
    return "mobile" if is_mobile_session(item) else "web"


@router.get("/user/sessions")
async def sessions(request: Request, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)) -> dict:
    # Active sessions only, newest first, with the caller's own session marked.
    current = request.state.auth_session.id
    rows = await db.scalars(select(AuthSession).where(
        AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None), AuthSession.expires_at > utcnow(),
    ).order_by(desc(AuthSession.last_used_at)).limit(50))
    return {"sessions": [{"id": item.id, "userAgent": item.user_agent, "client": session_client(item), "ipAddress": item.ip_address, "lastUsedAt": item.last_used_at.isoformat(), "createdAt": item.created_at.isoformat(), "expiresAt": item.expires_at.isoformat(), "revoked": False, "current": item.id == current} for item in rows]}


@router.delete("/user/sessions/{session_id}")
async def revoke_session(session_id: str, request: Request, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)) -> dict:
    if not _origin_allowed(request):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "csrf_denied")
    session = await db.scalar(select(AuthSession).where(AuthSession.id == session_id, AuthSession.user_id == user.id))
    if not session:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Session not found.")
    session.revoked_at = utcnow()
    await _event(db, request, user.email, "session.revoked", user.id)
    await db.commit()
    return {"message": "Session revoked."}


@router.post("/user/sessions/revoke-others")
async def revoke_other_sessions(request: Request, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)) -> dict:
    """Sign out every other device and forget all remembered devices.

    Use after a lost phone or suspected compromise; this browser stays signed in.
    """
    from .device_verification import revoke_trusted_devices

    if not _origin_allowed(request):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "csrf_denied")
    current = request.state.auth_session
    others = await db.scalars(select(AuthSession).where(
        AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None), AuthSession.id != current.id))
    now = utcnow()
    count = 0
    for session in others:
        session.revoked_at = now
        count += 1
    await revoke_trusted_devices(db, user.id)
    await _event(db, request, user.email, "session.revoked_others", user.id)
    await db.commit()
    return {"ok": True, "revoked": count}


from .mobile_routes import router as _mobile_router  # noqa: E402 - uses the helpers above

router.include_router(_mobile_router, prefix="/mobile/v1")
