"""AstraCall admin settings, mounted at ``/api/plugins/astracall_sms``.

Only the credential/settings surface is provided: entering the (encrypted) API key,
webhook secret, sender ID and base URL, and selecting AstraCall as the active SMS
provider. Delivery-receipt webhooks, balance and sender-ID sync are intentionally
out of scope here, as they would require message/sender tracking tables that are not
part of the neutral KARPy platform.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.config import settings as app_settings
from app.database import get_db
from karpy_platform.core.acl.routes import current_admin_user
from karpy_platform.core.security.secrets import decrypt_secret, encrypt_secret
from karpy_platform.core.setting.store import setting_store
from sqlalchemy.ext.asyncio import AsyncSession

from .adapter import (
    DEFAULT_API_BASE_URL,
    LIVE_KEY_PREFIX,
    PROVIDER_KEY,
    SETTING_API_BASE_URL,
    SETTING_API_KEY,
    SETTING_SENDER_ID,
    SETTING_WEBHOOK_SECRET,
)

# The setting that names the active SMS provider for payment notifications.
SETTING_PROVIDER = "payment.notifications.sms.provider"
DISABLED_PROVIDER = "log"  # the no-network stub: nothing leaves the platform

SENDER_PATTERN = re.compile(r"^[A-Za-z0-9 ._-]{3,11}$")


async def require_sms_admin(request: Request, db: AsyncSession = Depends(get_db)):
    """Super admin only; writes also require a same-origin (CSRF-safe) request."""
    user = await current_admin_user(request, db)
    if not user.super_user:
        raise HTTPException(status_code=403, detail="permission_denied")
    if request.method not in {"GET", "HEAD"}:
        allowed = set()
        for value in (
            app_settings.APP_URL,
            app_settings.USER_DASHBOARD_URL,
            app_settings.ADMIN_DASHBOARD_URL,
            *app_settings.user_dashboard_aliases,
        ):
            origin = urlsplit(value or "")
            schemes = {"https"} if app_settings.is_production else {"https", "http"}
            if origin.scheme in schemes and origin.netloc and not origin.username and not origin.password:
                allowed.add(f"{origin.scheme}://{origin.netloc}")
        if request.headers.get("origin", "") not in allowed or request.headers.get("sec-fetch-site") == "cross-site":
            raise HTTPException(status_code=403, detail="csrf_denied")
    return user


router = APIRouter(dependencies=[Depends(require_sms_admin)])


class SmsSettingsPayload(BaseModel):
    enabled: bool | None = None
    # Blank keeps the saved value; secrets are never echoed back.
    apiKey: str | None = Field(default=None, max_length=300)
    webhookSecret: str | None = Field(default=None, max_length=300)
    senderId: str | None = Field(default=None, max_length=11)
    apiBaseUrl: str | None = Field(default=None, max_length=300)


async def _values(db: AsyncSession) -> dict[str, Any]:
    return await setting_store.all(db, flat=True, force=True)


def _settings_view(values: dict[str, Any]) -> dict[str, Any]:
    key = decrypt_secret(str(values.get(SETTING_API_KEY) or "")).strip()
    selected = str(values.get(SETTING_PROVIDER) or DISABLED_PROVIDER).strip().lower()
    return {
        "provider": PROVIDER_KEY,
        "enabled": selected == PROVIDER_KEY,
        "activeProvider": selected,
        "apiKeySaved": bool(key),
        "keyMode": None if not key else ("live" if key.startswith(LIVE_KEY_PREFIX) else "test"),
        "webhookSecretSet": bool(decrypt_secret(str(values.get(SETTING_WEBHOOK_SECRET) or ""))),
        "senderId": str(values.get(SETTING_SENDER_ID) or ""),
        "apiBaseUrl": str(values.get(SETTING_API_BASE_URL) or "") or DEFAULT_API_BASE_URL,
        "channelEnabled": str(values.get("payment.notifications.channels.sms") or "").strip().lower()
        in {"1", "true", "yes", "on", "enabled"},
    }


@router.get("/v1/admin/settings")
async def get_sms_settings(db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    return _settings_view(await _values(db))


@router.put("/v1/admin/settings")
async def put_sms_settings(payload: SmsSettingsPayload, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    values = await _values(db)
    updates: dict[str, Any] = {}

    api_key = (payload.apiKey or "").strip()
    if api_key:
        if len(api_key) < 12 or not api_key.startswith("sk_") or any(char.isspace() for char in api_key):
            raise HTTPException(422, "api_key_invalid")
        updates[SETTING_API_KEY] = encrypt_secret(api_key)

    secret = (payload.webhookSecret or "").strip()
    if secret:
        if len(secret) < 8 or any(char.isspace() for char in secret):
            raise HTTPException(422, "webhook_secret_invalid")
        updates[SETTING_WEBHOOK_SECRET] = encrypt_secret(secret)

    if payload.senderId is not None:
        sender = payload.senderId.strip()
        if sender and not SENDER_PATTERN.match(sender):
            raise HTTPException(422, "sender_id_invalid")
        if sender != str(values.get(SETTING_SENDER_ID) or ""):
            updates[SETTING_SENDER_ID] = sender

    if payload.apiBaseUrl is not None:
        base = payload.apiBaseUrl.strip()
        if base and not base.startswith("https://"):
            raise HTTPException(422, "api_base_url_invalid")
        if base != str(values.get(SETTING_API_BASE_URL) or ""):
            updates[SETTING_API_BASE_URL] = base

    if payload.enabled is not None:
        wanted = PROVIDER_KEY if payload.enabled else DISABLED_PROVIDER
        if payload.enabled:
            effective_key = decrypt_secret(str(updates.get(SETTING_API_KEY) or values.get(SETTING_API_KEY) or "")).strip()
            if not effective_key:
                raise HTTPException(409, "api_key_missing")
        if str(values.get(SETTING_PROVIDER) or DISABLED_PROVIDER).strip().lower() != wanted:
            updates[SETTING_PROVIDER] = wanted

    if updates:
        await setting_store.set(db, updates, force=True)
        await setting_store.save(db)
        values = await _values(db)
    return _settings_view(values)
