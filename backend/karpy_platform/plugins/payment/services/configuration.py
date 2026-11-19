"""Shared secure configuration support for independently packaged gateways."""

from __future__ import annotations

from typing import Any

from karpy_platform.core.security.secrets import decrypt_secret, encrypt_secret

from .methods import payment_methods, method_settings


async def read_method_settings(db, key: str) -> dict[str, Any]:
    from sqlalchemy import select, or_
    from karpy_platform.core.setting.models import Setting
    from karpy_platform.core.setting.store import decode_setting_value
    prefix = f"payment.methods.{key}.settings"
    rows = await db.scalars(select(Setting).where(or_(Setting.key == prefix, Setting.key.startswith(prefix + ".", autoescape=True))))
    return method_settings({row.key: decode_setting_value(row.value) for row in rows}, key)


def secret_keys(method_key: str) -> set[str]:
    method = payment_methods.get(method_key)
    return {field.key for field in (method.fields if method else []) if field.secret}


def public_settings(method_key: str, settings: dict[str, Any] | None) -> dict[str, Any]:
    values = dict(settings or {})
    configured: dict[str, bool] = {}
    for key in secret_keys(method_key):
        configured[key] = bool(decrypt_secret(str(values.get(key) or "")))
        values.pop(key, None)
    values["configuredSecrets"] = configured
    return values


def merge_secure_settings(
    method_key: str, current: dict[str, Any] | None, incoming: dict[str, Any]
) -> dict[str, Any]:
    values = dict(current or {})
    incoming = dict(incoming)
    incoming.pop("configuredSecrets", None)
    for key in secret_keys(method_key):
        supplied = str(incoming.pop(key, "") or "").strip()
        if supplied:
            values[key] = encrypt_secret(supplied)
    values.update(incoming)
    return values


def decrypted_settings(
    method_key: str, settings: dict[str, Any] | None
) -> dict[str, Any]:
    values = dict(settings or {})
    for key in secret_keys(method_key):
        values[key] = decrypt_secret(str(values.get(key) or ""))
    return values
