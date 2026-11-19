from __future__ import annotations

import json
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from karpy_platform.core.setting.models import Setting


GUARDED_SETTINGS = {
    "activated_plugins",
    "theme",
    "licensed_to",
    "license_activated_at",
    "license_checked_at",
    "license_envato_item_id",
    "license_envato_item_name",
    "license_envato_username",
    "license_purchase_code",
    "license_source",
    "license_status",
    "media_random_hash",
    "admin_appearance_custom_css",
    "admin_appearance_custom_header_js",
    "admin_appearance_custom_body_js",
    "admin_appearance_custom_footer_js",
}


def encode_setting_value(value: Any) -> str:
    if isinstance(value, str):
        return value
    if value is None:
        return ""
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def decode_setting_value(value: str | None) -> Any:
    if value is None:
        return None
    text = str(value)
    stripped = text.strip()
    if not stripped:
        return ""
    if stripped in {"0", "1"}:
        return stripped
    if stripped[0:1] in {"{", "["}:
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            return text
    return text


def dot_get(data: dict[str, Any], key: str, default: Any = None) -> Any:
    if key in data:
        return data[key]
    value: Any = data
    for segment in key.split("."):
        if not isinstance(value, dict) or segment not in value:
            return default
        value = value[segment]
    return value


def dot_set(data: dict[str, Any], key: str, value: Any) -> None:
    if key in data and "." in key:
        data[key] = value
        return
    target = data
    segments = key.split(".")
    for segment in segments[:-1]:
        child = target.setdefault(segment, {})
        if not isinstance(child, dict):
            # Opaque settings may also have dotted audit keys. Keep both values.
            data[key] = value
            return
        target = child
    previous = target.get(segments[-1])
    if isinstance(previous, dict) and not isinstance(value, dict):
        data.update(flatten(previous, key))
    target[segments[-1]] = value


def dot_forget(data: dict[str, Any], key: str) -> None:
    if key in data:
        data.pop(key)
        return
    target = data
    segments = key.split(".")
    for segment in segments[:-1]:
        if not isinstance(target, dict) or segment not in target:
            return
        target = target[segment]
    if isinstance(target, dict):
        target.pop(segments[-1], None)


def flatten(data: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in data.items():
        dotted = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            result.update(flatten(value, dotted))
        else:
            result[dotted] = value
    return result


class SettingStore:
    """Botble-style cached database setting store."""

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._loaded = False
        self._unsaved = False

    async def load(self, db: AsyncSession, force: bool = False) -> None:
        if self._loaded and not force:
            return
        result = await db.execute(select(Setting))
        nested: dict[str, Any] = {}
        for row in result.scalars().all():
            dot_set(nested, row.key, decode_setting_value(row.value))
        self._data = nested
        self._loaded = True

    async def all(self, db: AsyncSession, flat: bool = True, force: bool = False) -> dict[str, Any]:
        await self.load(db, force=force)
        return flatten(self._data) if flat else self._data

    async def get(self, db: AsyncSession, key: str, default: Any = None) -> Any:
        await self.load(db)
        return dot_get(self._data, key, default)

    async def has(self, db: AsyncSession, key: str) -> bool:
        sentinel = object()
        return await self.get(db, key, sentinel) is not sentinel

    async def set(self, db: AsyncSession, key: str | dict[str, Any], value: Any = None, force: bool = False) -> "SettingStore":
        await self.load(db)
        values = key if isinstance(key, dict) else {key: value}
        for setting_key, setting_value in values.items():
            if not force and setting_key in GUARDED_SETTINGS:
                continue
            dot_set(self._data, setting_key, setting_value)
        self._unsaved = True
        return self

    async def force_set(self, db: AsyncSession, key: str | dict[str, Any], value: Any = None) -> "SettingStore":
        return await self.set(db, key, value, force=True)

    async def forget(self, db: AsyncSession, key: str, force: bool = False) -> "SettingStore":
        await self.load(db)
        if not force and key in GUARDED_SETTINGS:
            return self
        dot_forget(self._data, key)
        self._unsaved = True
        return self

    async def save(self, db: AsyncSession) -> bool:
        if not self._unsaved:
            return False

        for key, value in flatten(self._data).items():
            encoded = encode_setting_value(value)
            setting = await db.get(Setting, key)
            if setting:
                setting.value = encoded
            else:
                db.add(Setting(key=key, value=encoded))

        await db.commit()
        self._unsaved = False
        return True

    async def delete(self, db: AsyncSession, keys: list[str] | str, force: bool = False) -> int:
        if isinstance(keys, str):
            keys = [keys]
        if not force:
            keys = [key for key in keys if key not in GUARDED_SETTINGS]
        if not keys:
            return 0
        result = await db.execute(delete(Setting).where(Setting.key.in_(keys)))
        for key in keys:
            dot_forget(self._data, key)
        await db.commit()
        return result.rowcount or 0

    def clear_cache(self) -> None:
        self._loaded = False
        self._data = {}
        self._unsaved = False


setting_store = SettingStore()
