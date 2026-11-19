"""Extension points of the auth plugin (Botble-style hooks, ``core/base/hooks.py``).

The auth flows (web sign-in, mobile sign-in, registration, password reset, admin sign-in)
work on their own with safe defaults. Products and other plugins change behaviour by
registering hooks in their provider's ``boot()`` -- never by editing this plugin.

Filters (``hooks.add_filter(name, callback)``; callbacks may be sync or async):

``auth.policy``                (policy: AuthPolicy, db) -> AuthPolicy
    Sign-up open/closed, terms version, allowed phone countries.
``auth.message``               (message: dict | None, db, event, channel, language, variables, settings_values) -> dict
    Text of verification / sign-in / reset codes: ``{"subject", "html", "text"}``.
``auth.email_layout``          (message: dict | None, subject, text, settings_values) -> dict
    Wraps a plain notice (e.g. "someone tried to sign up with your email") in the brand layout.
``auth.sms_client``            (client | None, db) -> client | None
    An SMS sender with ``async send_sms(phone, text, reference, otp=True)`` returning an object
    with ``status`` and ``test``. Without one, codes go by email only.
``auth.account_alert``         (handled: bool, db, user_id, event, key) -> bool
    In-app security alert for the account owner (new device, sign-up attempt...).
``auth.admin_alert``           (handled: bool, db, event, payload, key) -> bool
    Alert for platform administrators (new account, blocked sign-up...).
``auth.mobile.allow_user``     (allowed: bool, user) -> bool
    Whether this account may use the mobile app (default: everyone but staff,
    unless ``AUTH_MOBILE_ALLOW_STAFF``).

Actions (``hooks.add_action(name, callback)``):

``auth.security_event``        (event, ip, identity) -- every sign-in/sign-up security event
                               (attack detection, metrics).
``auth.failed_sign_in``        (request, area, identity, account_exists) -- wrong password
                               (honeytokens, alerting). The password is never passed on.
``auth.before_session``        (db, user, request_id) -- right before a session is created
                               (prepare per-account data in other services).
``auth.account_registered``    (db, user_id) -- a new account row exists (default services,
                               welcome flows). Runs inside the sign-up transaction.
``auth.account_signal``        (user_ids) -- after commit, when an account alert was recorded
                               (live badge refresh).
``auth.login_code.requested``  (db, user, challenge_id, channels)
``auth.login_code.delivered``  (db, user_id, results) -- per-channel delivery results.
``auth.mobile.integrity``      (db, request, purpose, platform, installation, user_id) --
                               genuine-app checks (Play Integrity / App Attest); raise an
                               ``HTTPException`` to refuse.
``auth.mobile.session_ended``  (db, user_id, reason, session_id) -- mobile session signed
                               out, replaced on a new device or the account closed.
``acl.admin_signed_in``        (db, user, request) -- a staff member signed in to the admin.
"""
from __future__ import annotations

import html
import inspect
import logging
from typing import Any

from fastapi import HTTPException, Request
from pydantic import BaseModel, Field

from app.config import settings
from karpy_platform.core.base.hooks import hooks

log = logging.getLogger(__name__)


class AuthPolicy(BaseModel):
    """Sign-up rules. Defaults come from the settings store (``auth.*`` keys) and env."""

    version: int = Field(default=0, ge=0)
    registration_open: bool = True
    require_terms: bool = False
    terms_url: str = ""
    privacy_url: str = ""
    phone_required: bool = True
    # ISO 3166-1 alpha-2 codes; empty means every country is accepted.
    phone_countries: list[str] = Field(default_factory=list)


def _truthy(value: Any, default: bool) -> bool:
    if value is None or value == "":
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


async def _resolve(value: Any) -> Any:
    return await value if inspect.isawaitable(value) else value


async def filter_value(name: str, value: Any, *args: Any, **kwargs: Any) -> Any:
    """``apply_filters`` that also awaits async callbacks, one after the other."""
    for _priority, callback in list(hooks._filters.get(name, [])):  # noqa: SLF001 - same order as apply_filters
        value = await _resolve(callback(value, *args, **kwargs))
    return value


async def action(name: str, *args: Any, **kwargs: Any) -> None:
    """``do_action`` that awaits async callbacks. A failing listener is logged, never raised,
    except ``HTTPException`` (a listener may deliberately refuse the request)."""
    for _priority, callback in list(hooks._actions.get(name, [])):  # noqa: SLF001
        try:
            await _resolve(callback(*args, **kwargs))
        except HTTPException:
            raise
        except Exception:  # noqa: BLE001 - extensions must not break sign-in
            log.exception("auth hook %s failed", name)


# ---- policy -------------------------------------------------------------------------

async def policy(db) -> tuple[AuthPolicy, dict]:
    from karpy_platform.core.setting.store import setting_store

    values = await setting_store.all(db, flat=True, force=True)
    countries = [item.strip().upper() for item in str(values.get("auth.phone_countries") or settings.AUTH_PHONE_COUNTRIES or "").split(",") if item.strip()]
    value = AuthPolicy(
        version=int(values.get("auth.policy_version") or 0),
        registration_open=_truthy(values.get("auth.registration_open"), settings.AUTH_REGISTRATION_OPEN),
        require_terms=_truthy(values.get("auth.require_terms"), False),
        terms_url=str(values.get("auth.terms_url") or ""),
        privacy_url=str(values.get("auth.privacy_url") or ""),
        phone_required=_truthy(values.get("auth.phone_required"), settings.AUTH_PHONE_REQUIRED),
        phone_countries=countries,
    )
    return await filter_value("auth.policy", value, db), values


async def registration_open(db) -> bool:
    value, _ = await policy(db)
    return value.registration_open


# ---- messages -----------------------------------------------------------------------

TEMPLATE_FOR_EVENT = {
    "verification.otp": "plugins.auth.email-verification",
    "login.otp": "plugins.auth.login-code",
    "password_reset.otp": "plugins.auth.password-reset-code",
}


async def code_message(db, event: str, channel: str, language: str, variables: dict, *, settings_values: dict) -> dict:
    """Subject/html/text for a one-time code. Default: the auth plugin's email templates."""
    message = await filter_value("auth.message", None, db, event, channel, language, variables, settings_values)
    if message:
        return message
    from karpy_platform.core.setting.email_templates import email_template_registry
    from karpy_platform.core.setting.mailer import mailer

    code = variables.get("verification_code", "")
    minutes = variables.get("expires_minutes", "")
    template_key = TEMPLATE_FOR_EVENT.get(event, TEMPLATE_FOR_EVENT["verification.otp"])
    template_vars = {"verification_code": code, "expires_in_minutes": minutes,
                     "member_name": variables.get("member_name", "")}
    if not email_template_registry.find(template_key):
        _register_auth_templates()
    name = app_name(settings_values)
    text = f"Your {name} code is {code}. It expires in {minutes} minutes. Never share it."
    try:
        subject, body = mailer.render_template(template_key, settings_values, template_vars)
    except Exception:  # noqa: BLE001 - a template problem must not stop sign-in codes
        log.exception("auth email template %s could not be rendered; using plain text", template_key)
        subject, body = f"Your {name} code", f"<p>{html.escape(text)}</p>"
    return {"subject": subject, "html": body, "text": text}


def _register_auth_templates() -> None:
    """Email templates come from this plugin's manifest (normally registered at boot)."""
    import json
    from pathlib import Path

    from karpy_platform.core.setting.email_templates import email_template_registry

    manifest = json.loads((Path(__file__).with_name("plugin.json")).read_text(encoding="utf-8"))
    email_template_registry.register_from_manifest("auth", manifest)


def sms_code_text(settings_values: dict, purpose: str, code: str) -> str:
    name = settings_values.get("site_title") or settings.APP_NAME
    if purpose == "reset":
        return f"Your {name} password reset code is {code}. Do not share it."
    return f"Your {name} sign-in code is {code}. Valid for 5 minutes. Do not share it."


async def email_layout(subject: str, text: str, settings_values: dict) -> dict:
    message = await filter_value("auth.email_layout", None, subject, text, settings_values)
    if message:
        return message
    paragraphs = "".join(f"<p>{html.escape(part).replace(chr(10), '<br>')}</p>" for part in text.split("\n\n"))
    return {"subject": subject, "html": f"<!doctype html><html><body>{paragraphs}</body></html>", "text": text}


def app_name(settings_values: dict | None = None) -> str:
    return str((settings_values or {}).get("site_title") or settings.APP_NAME)


# ---- SMS ----------------------------------------------------------------------------

def phone_binding(user) -> bool:
    """True when the account's current phone number was verified (``auth.phone.*`` meta)."""
    entries = [item for item in getattr(user, "meta", None) or [] if item.key.startswith("auth.phone.")]
    values = {item.key: item.value for item in entries}
    if len(values) != len(entries):
        return False
    if values.get("auth.phone.verified_number") != (user.phone or ""):
        return False
    return bool(values.get("auth.phone.verified_at"))


async def sms_client(db):
    """The SMS sender registered by an SMS provider plugin, or ``None``."""
    return await filter_value("auth.sms_client", None, db)


async def live_sms_client(db):
    client = await sms_client(db)
    if client is None:
        raise HTTPException(503, "phone_delivery_unavailable")
    return client


# ---- alerts and events --------------------------------------------------------------

async def account_alert(db, user_id: str, event: str, key: str) -> bool:
    return bool(await filter_value("auth.account_alert", False, db, user_id, event, key))


async def admin_alert(db, event: str, payload: dict, key: str) -> bool:
    return bool(await filter_value("auth.admin_alert", False, db, event, payload, key))


async def security_event(event: str, ip: str | None, identity: str | None = None) -> None:
    await action("auth.security_event", event, ip, identity)


def failed_sign_in(request: Request, area: str, identity: str, password: str, *, account_exists: bool) -> None:
    """Synchronous on purpose (called on the failure path); listeners must be sync."""
    del password  # never handed to extensions
    for _priority, callback in list(hooks._actions.get("auth.failed_sign_in", [])):  # noqa: SLF001
        try:
            callback(request, area, identity, account_exists)
        except Exception:  # noqa: BLE001
            log.exception("auth.failed_sign_in listener failed")


# ---- CSRF for cookie-authenticated writes ----------------------------------------------

def csrf(request: Request) -> None:
    """Refuse cookie-authenticated writes from origins other than the configured dashboards.
    Mobile bearer requests carry no ambient credentials, so there is nothing to forge."""
    from .security import is_mobile_bearer

    if is_mobile_bearer(request):
        return
    origin = request.headers.get("origin", "")
    allowed = {value.rstrip("/") for value in (settings.APP_URL, settings.USER_DASHBOARD_URL, settings.ADMIN_DASHBOARD_URL, settings.PUBLIC_SITE_URL) if value}
    if not origin or origin.rstrip("/") not in allowed:
        raise HTTPException(403, "csrf_origin_not_allowed")
