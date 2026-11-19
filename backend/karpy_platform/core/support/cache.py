from __future__ import annotations

import asyncio
import hashlib
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.config import settings
from karpy_platform.core.base.helpers import get_file_data, write_file_data


@dataclass
class CacheEntry:
    value: Any
    expires_at: float | None = None

    def expired(self) -> bool:
        return self.expires_at is not None and self.expires_at <= time.time()


class SupportCache:
    """Small Botble-style grouped cache with tracked keys."""

    def __init__(self, group: str, cache_time: int = 600, stored_keys: Path | None = None) -> None:
        self.group = group
        self.cache_time = cache_time
        self.stored_keys = stored_keys or settings.STORAGE_DIR / "support_cache_keys.json"
        self._data: dict[str, CacheEntry] = {}
        self._lock = asyncio.Lock()

    def generate_cache_key(self, key: str) -> str:
        group_hash = hashlib.sha256(self.group.encode("utf-8")).hexdigest()[:24]
        key_hash = hashlib.sha256(str(key).encode("utf-8")).hexdigest()
        return f"{group_hash}@{key_hash}"

    async def get(self, key: str, default: Any = None) -> Any:
        generated_key = self.generate_cache_key(key)
        entry = self._data.get(generated_key)
        if not entry:
            return default
        if entry.expired():
            await self.forget(key)
            return default
        return entry.value

    async def put(self, key: str, value: Any, ttl: int | None = None) -> bool:
        generated_key = self.generate_cache_key(key)
        if ttl is None:
            ttl = self.cache_time
        expires_at = None if ttl == -1 else time.time() + ttl
        async with self._lock:
            self._data[generated_key] = CacheEntry(value=value, expires_at=expires_at)
            self._store_cache_key(generated_key)
        return True

    async def forever(self, key: str, value: Any) -> bool:
        return await self.put(key, value, ttl=-1)

    async def remember(
        self,
        key: str,
        ttl: int | None,
        callback: Callable[[], Any] | Callable[[], Awaitable[Any]],
    ) -> Any:
        if await self.has(key):
            return await self.get(key)
        value = callback()
        if asyncio.iscoroutine(value):
            value = await value
        await self.put(key, value, ttl)
        return value

    async def remember_forever(self, key: str, callback: Callable[[], Any] | Callable[[], Awaitable[Any]]) -> Any:
        return await self.remember(key, -1, callback)

    async def has(self, key: str) -> bool:
        generated_key = self.generate_cache_key(key)
        entry = self._data.get(generated_key)
        if not entry:
            return False
        if entry.expired():
            await self.forget(key)
            return False
        return True

    async def forget(self, key: str) -> bool:
        generated_key = key if "@" in key else self.generate_cache_key(key)
        self._data.pop(generated_key, None)
        keys = self._read_stored_keys()
        group_keys = keys.get(self.group, [])
        if generated_key in group_keys:
            group_keys.remove(generated_key)
        if group_keys:
            keys[self.group] = group_keys
        else:
            keys.pop(self.group, None)
        self._write_stored_keys(keys)
        return True

    async def flush(self) -> bool:
        keys = self._read_stored_keys()
        for key in keys.get(self.group, []):
            self._data.pop(key, None)
        keys.pop(self.group, None)
        self._write_stored_keys(keys)
        return True

    def stats(self) -> dict[str, Any]:
        keys = self._read_stored_keys().get(self.group, [])
        alive = [key for key in keys if key in self._data and not self._data[key].expired()]
        return {"group": self.group, "trackedKeys": len(keys), "aliveKeys": len(alive)}

    def _store_cache_key(self, key: str) -> None:
        keys = self._read_stored_keys()
        group_keys = keys.setdefault(self.group, [])
        if key not in group_keys:
            group_keys.append(key)
        self._write_stored_keys(keys)

    def _read_stored_keys(self) -> dict[str, list[str]]:
        data = get_file_data(self.stored_keys)
        return data if isinstance(data, dict) else {}

    def _write_stored_keys(self, keys: dict[str, list[str]]) -> None:
        self.stored_keys.parent.mkdir(parents=True, exist_ok=True)
        if keys:
            write_file_data(self.stored_keys, keys)
        elif self.stored_keys.exists():
            self.stored_keys.unlink()


class CacheManager:
    def __init__(self) -> None:
        self._groups: dict[str, SupportCache] = {}

    def make(self, group: str) -> SupportCache:
        if group not in self._groups:
            self._groups[group] = SupportCache(group)
        return self._groups[group]

    def groups(self) -> list[dict[str, Any]]:
        return [cache.stats() for cache in sorted(self._groups.values(), key=lambda item: item.group)]

    async def flush(self, group: str | None = None) -> bool:
        if group:
            return await self.make(group).flush()
        for cache in self._groups.values():
            await cache.flush()
        return True


support_cache_manager = CacheManager()
