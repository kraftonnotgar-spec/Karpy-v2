"""Runtime rate limiter for the Speed plugin."""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import time
from collections import Counter, deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from app.config import settings


PLUGIN_FOLDER = "speed"
ACTIVE_PLUGINS_FILE = settings.PLATFORM_DIR / "activated_plugins.json"
CONFIG_DIR = settings.STORAGE_DIR / "plugins" / PLUGIN_FOLDER
CONFIG_FILE = CONFIG_DIR / "rate_limit.json"


DEFAULT_CONFIG: dict[str, Any] = {
    "enabled": True,
    "mode": "enforce",
    "storage": "auto",
    "identifier": "ip",
    "trustProxyHeaders": False,
    "hashClientKeys": True,
    "defaultRule": {
        "key": "global",
        "name": "Global traffic",
        "capacity": 240,
        "refillPerSecond": 4,
        "description": "Default token bucket for public and API traffic.",
    },
    "rules": [
        {
            "key": "admin",
            "name": "Admin API",
            "pattern": "/api/admin",
            "capacity": 600,
            "refillPerSecond": 10,
            "description": "Higher limit for authenticated admin operations.",
            "enabled": True,
        },
        {
            "key": "auth",
            "name": "Sensitive auth-style endpoints",
            "pattern": "/api/admin/auth",
            "methods": ["POST"],
            "capacity": 20,
            "refillPerSecond": 0.35,
            "description": "Protects login/password endpoints from brute force traffic.",
            "enabled": True,
        },
        {
            "key": "write",
            "name": "Write requests",
            "methods": ["POST", "PUT", "PATCH", "DELETE"],
            "pattern": "/api",
            "capacity": 120,
            "refillPerSecond": 2,
            "description": "Keeps write-heavy API traffic from overwhelming the database.",
            "enabled": True,
        },
    ],
    "exemptPaths": [
        "/api/health",
        "/api/plugins/speed/rate-limit",
        "/admin/assets",
        "/themes",
        "/media",
        "/favicon.ico",
        "/docs",
        "/openapi.json",
    ],
}


@dataclass
class RateDecision:
    allowed: bool
    rule: dict[str, Any]
    limit: int
    remaining: int
    retry_after: int
    storage: str
    client_key: str
    client_ip: str
    client_identity: str
    reason: str


@dataclass
class MemoryBucket:
    tokens: float
    updated_at: float


class InMemoryTokenBucketStore:
    def __init__(self) -> None:
        self._buckets: dict[str, MemoryBucket] = {}
        self._lock = asyncio.Lock()

    async def consume(self, key: str, capacity: int, refill_per_second: float) -> tuple[bool, int, int]:
        now = time.monotonic()
        refill_per_second = max(float(refill_per_second), 0.01)
        capacity = max(int(capacity), 1)

        async with self._lock:
            bucket = self._buckets.get(key)
            if not bucket:
                bucket = MemoryBucket(tokens=float(capacity), updated_at=now)

            elapsed = max(now - bucket.updated_at, 0)
            bucket.tokens = min(float(capacity), bucket.tokens + elapsed * refill_per_second)
            bucket.updated_at = now

            if bucket.tokens >= 1:
                bucket.tokens -= 1
                self._buckets[key] = bucket
                return True, int(bucket.tokens), 0

            retry_after = max(1, math.ceil((1 - bucket.tokens) / refill_per_second))
            self._buckets[key] = bucket
            return False, 0, retry_after

    def reset(self) -> None:
        self._buckets.clear()

    def size(self) -> int:
        return len(self._buckets)


class RedisTokenBucketStore:
    SCRIPT = """
local current = redis.call('HMGET', KEYS[1], 'tokens', 'updated_at')
local capacity = tonumber(ARGV[1])
local refill = tonumber(ARGV[2])
local now = tonumber(ARGV[3])
local tokens = tonumber(current[1])
local updated_at = tonumber(current[2])
if tokens == nil then tokens = capacity end
if updated_at == nil then updated_at = now end
local elapsed = math.max(now - updated_at, 0)
tokens = math.min(capacity, tokens + (elapsed * refill))
local allowed = 0
local retry_after = 0
if tokens >= 1 then
  tokens = tokens - 1
  allowed = 1
else
  retry_after = math.max(1, math.ceil((1 - tokens) / refill))
end
redis.call('HMSET', KEYS[1], 'tokens', tokens, 'updated_at', now)
redis.call('EXPIRE', KEYS[1], math.max(60, math.ceil(capacity / refill * 2)))
return { allowed, math.floor(tokens), retry_after }
"""

    def __init__(self) -> None:
        self._client: Any | None = None
        self._retry_at = 0.0
        self._connect_lock = asyncio.Lock()

    async def client(self):
        if self._client:
            return self._client
        if time.monotonic() < self._retry_at:
            return None
        async with self._connect_lock:
            if self._client or time.monotonic() < self._retry_at:
                return self._client
            import redis.asyncio as redis
            from redis.asyncio.retry import Retry
            from redis.backoff import NoBackoff

            options = dict(decode_responses=True, socket_timeout=1, socket_connect_timeout=1,
                           retry=Retry(NoBackoff(), 0), max_connections=32)
            candidate = None
            try:
                candidate = (redis.from_url(settings.REDIS_URL, **options) if settings.REDIS_URL else
                             redis.Redis(host=settings.REDIS_HOST, port=settings.REDIS_PORT,
                                         password=settings.REDIS_PASSWORD, **options))
                await candidate.ping()
                self._client = candidate
            except Exception:
                self._retry_at = time.monotonic() + 5
                if candidate is not None:
                    try:
                        await candidate.aclose()
                    except Exception:
                        pass
        return self._client

    async def consume(self, key: str, capacity: int, refill_per_second: float) -> tuple[bool, int, int] | None:
        client = await self.client()
        if not client:
            return None
        try:
            result = await client.eval(self.SCRIPT, 1, f"karpy:speed:rate:{key}", capacity, refill_per_second, time.time())
            return bool(int(result[0])), int(result[1]), int(result[2])
        except Exception:
            if self._client is client:
                self._client = None
            self._retry_at = time.monotonic() + 5
            try:
                await client.aclose()
            except Exception:
                pass
            return None

    async def reset(self) -> None:
        client = await self.client()
        if not client:
            return
        keys = [key async for key in client.scan_iter("karpy:speed:rate:*")]
        if keys:
            await client.delete(*keys)


class RateLimitMetrics:
    def __init__(self) -> None:
        self.allowed = 0
        self.blocked = 0
        self.rules: Counter[str] = Counter()
        self.clients: Counter[str] = Counter()
        self.events: deque[dict[str, Any]] = deque(maxlen=80)
        self.started_at = time.time()

    def record(self, decision: RateDecision, request: Request) -> None:
        if decision.allowed:
            self.allowed += 1
            return
        self.blocked += 1
        rule_key = str(decision.rule.get("key") or "global")
        self.rules[rule_key] += 1
        self.clients[decision.client_identity] += 1
        self.events.appendleft(
            {
                "time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
                "path": request.url.path,
                "method": request.method,
                "rule": rule_key,
                "client": decision.client_key,
                "clientIp": decision.client_ip,
                "identity": decision.client_identity,
                "reason": decision.reason,
                "limit": decision.limit,
                "remaining": decision.remaining,
                "storage": decision.storage,
                "retryAfter": decision.retry_after,
                "userAgent": request.headers.get("user-agent", ""),
            }
        )

    def payload(self, store_size: int, storage: str) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "blocked": self.blocked,
            "total": self.allowed + self.blocked,
            "blockedRate": round(self.blocked / max(self.allowed + self.blocked, 1) * 100, 2),
            "startedAt": self.started_at,
            "storeSize": store_size,
            "storage": storage,
            "topRules": [{"key": key, "blocked": value} for key, value in self.rules.most_common(8)],
            "topClients": [{"client": key, "blocked": value} for key, value in self.clients.most_common(8)],
            "events": list(self.events),
        }

    def reset(self) -> None:
        self.__init__()


class SpeedRateLimiter:
    def __init__(self) -> None:
        self.memory = InMemoryTokenBucketStore()
        self.redis = RedisTokenBucketStore()
        self.metrics = RateLimitMetrics()
        self._config_cache: dict[str, Any] | None = None
        self._config_mtime = 0.0
        self._active_cache = False
        self._active_mtime = 0.0

    def ensure_config(self) -> None:
        if CONFIG_FILE.exists():
            return
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(json.dumps(DEFAULT_CONFIG, indent=2), encoding="utf-8")

    def is_plugin_active(self) -> bool:
        try:
            mtime = ACTIVE_PLUGINS_FILE.stat().st_mtime
        except OSError:
            self._active_cache = False
            return False
        if mtime == self._active_mtime:
            return self._active_cache
        self._active_mtime = mtime
        try:
            data = json.loads(ACTIVE_PLUGINS_FILE.read_text(encoding="utf-8"))
            plugins = set(data.get("plugins") or [])
            self._active_cache = PLUGIN_FOLDER in plugins
        except (OSError, json.JSONDecodeError):
            self._active_cache = False
        return self._active_cache

    def config(self) -> dict[str, Any]:
        self.ensure_config()
        mtime = CONFIG_FILE.stat().st_mtime
        if self._config_cache is not None and mtime == self._config_mtime:
            return self._config_cache
        try:
            loaded = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            loaded = {}
        self._config_cache = merge_config(DEFAULT_CONFIG, loaded)
        self._config_mtime = mtime
        return self._config_cache

    def save_config(self, values: dict[str, Any]) -> dict[str, Any]:
        config = validate_config(values)
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(json.dumps(config, indent=2), encoding="utf-8")
        self._config_cache = config
        self._config_mtime = CONFIG_FILE.stat().st_mtime
        return config

    async def decide(self, request: Request) -> RateDecision | None:
        if not self.is_plugin_active():
            return None
        config = self.config()
        if not config.get("enabled"):
            return None
        path = request.url.path
        if self.is_exempt(path, config):
            return None

        rule = match_rule(request, config)
        capacity = int(rule["capacity"])
        refill = float(rule["refillPerSecond"])
        client_info = client_identifier(request, config)
        raw_key = f"{rule['key']}:{client_info['bucket']}"
        bucket_key = hash_key(raw_key) if config.get("hashClientKeys") else raw_key

        storage = "memory"
        consumed = None
        if config.get("storage") in {"auto", "redis"} and settings.CACHE_ENABLED:
            consumed = await self.redis.consume(bucket_key, capacity, refill)
            if consumed:
                storage = "redis"

        # A Redis hiccup must never take the API down: fall back to this process's
        # own token bucket (the edge proxy still enforces its own limits). Only an
        # explicit "redis" storage setting keeps the old fail-closed behaviour.
        unavailable = consumed is None and settings.is_production and config.get("storage") == "redis"
        if unavailable:
            consumed = (False, 0, 5)
            storage = "unavailable"
        elif consumed is None:
            consumed = await self.memory.consume(bucket_key, capacity, refill)

        allowed, remaining, retry_after = consumed
        if config.get("mode") == "monitor" and not unavailable:
            allowed = True

        reason = "Allowed by token bucket."
        if unavailable:
            reason = "Distributed admission control is temporarily unavailable."
        elif not allowed:
            reason = f"Token bucket empty for {rule.get('name') or rule.get('key')}. Burst limit {capacity}, refill {refill:g}/sec."

        return RateDecision(
            allowed=allowed,
            rule=rule,
            limit=capacity,
            remaining=remaining,
            retry_after=retry_after,
            storage=storage,
            client_key=bucket_key[:18],
            client_ip=client_info["ip"],
            client_identity=client_info["identity"],
            reason=reason,
        )

    def is_exempt(self, path: str, config: dict[str, Any]) -> bool:
        return any(path == prefix or path.startswith(f"{prefix.rstrip('/')}/") for prefix in config.get("exemptPaths", []))

    async def reset(self) -> None:
        self.memory.reset()
        await self.redis.reset()
        self.metrics.reset()

    def status(self) -> dict[str, Any]:
        config = self.config()
        storage = "redis" if settings.CACHE_ENABLED else "memory"
        return {
            "active": self.is_plugin_active(),
            "config": config,
            "metrics": self.metrics.payload(self.memory.size(), storage),
            "recommendations": [
                "Use Redis in production so all app workers share the same token buckets.",
                "Keep write requests stricter than read requests to protect database cost.",
                "Put your reverse proxy IPs behind trusted headers before using X-Forwarded-For in production.",
            ],
        }


class SpeedRateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        decision = await speed_rate_limiter.decide(request)
        if decision is None:
            return await call_next(request)

        speed_rate_limiter.metrics.record(decision, request)
        if not decision.allowed:
            unavailable = decision.storage == "unavailable"
            return JSONResponse(
                status_code=503 if unavailable else 429,
                content={
                    "detail": "Admission control unavailable." if unavailable else "Too many requests.",
                    "message": "Please try again shortly." if unavailable else "Rate limit exceeded. Please retry after the bucket refills.",
                    "rule": decision.rule.get("key"),
                    "reason": decision.reason,
                    "retryAfter": decision.retry_after,
                },
                headers={
                    "Retry-After": str(decision.retry_after),
                    "X-RateLimit-Limit": str(decision.limit),
                    "X-RateLimit-Remaining": str(decision.remaining),
                    "X-KARPy-RateLimit-Storage": decision.storage,
                },
            )

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(decision.limit)
        response.headers["X-RateLimit-Remaining"] = str(decision.remaining)
        response.headers["X-KARPy-RateLimit-Storage"] = decision.storage
        return response


def merge_config(defaults: dict[str, Any], loaded: dict[str, Any]) -> dict[str, Any]:
    merged = json.loads(json.dumps(defaults))
    for key, value in loaded.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key].update(value)
        else:
            merged[key] = value
    return validate_config(merged)


def validate_config(values: dict[str, Any]) -> dict[str, Any]:
    config = merge_shallow(DEFAULT_CONFIG, values)
    config["enabled"] = bool(config.get("enabled"))
    config["trustProxyHeaders"] = bool(config.get("trustProxyHeaders"))
    config["hashClientKeys"] = bool(config.get("hashClientKeys"))
    config["mode"] = str(config.get("mode") or "enforce")
    if config["mode"] not in {"enforce", "monitor"}:
        config["mode"] = "enforce"
    config["storage"] = str(config.get("storage") or "auto")
    if config["storage"] not in {"auto", "memory", "redis"}:
        config["storage"] = "auto"
    config["identifier"] = str(config.get("identifier") or "ip")
    if config["identifier"] not in {"ip", "ip_user_agent"}:
        config["identifier"] = "ip"
    config["exemptPaths"] = [clean_prefix(item) for item in config.get("exemptPaths", []) if clean_prefix(item)]
    config["defaultRule"] = validate_rule(config.get("defaultRule") or {}, DEFAULT_CONFIG["defaultRule"])
    config["rules"] = [validate_rule(rule, None) for rule in config.get("rules", []) if isinstance(rule, dict)]
    return config


def merge_shallow(defaults: dict[str, Any], values: dict[str, Any]) -> dict[str, Any]:
    output = json.loads(json.dumps(defaults))
    for key, value in values.items():
        output[key] = value
    return output


def validate_rule(rule: dict[str, Any], fallback: dict[str, Any] | None) -> dict[str, Any]:
    source = {**(fallback or {}), **rule}
    key = str(source.get("key") or source.get("name") or "rule").strip().lower().replace(" ", "_")[:80]
    capacity = max(1, min(int(source.get("capacity") or 60), 100000))
    refill = max(0.01, min(float(source.get("refillPerSecond") or source.get("refill_per_second") or 1), 10000))
    methods = source.get("methods") or ["*"]
    if not isinstance(methods, list):
        methods = ["*"]
    return {
        "key": key,
        "name": str(source.get("name") or key.title())[:120],
        "pattern": clean_prefix(source.get("pattern") or "*"),
        "methods": [str(method).upper() for method in methods],
        "capacity": capacity,
        "refillPerSecond": refill,
        "description": str(source.get("description") or "")[:240],
        "enabled": bool(source.get("enabled", True)),
    }


def clean_prefix(value: Any) -> str:
    text = str(value or "").strip()
    if text == "*":
        return text
    return "/" + text.strip("/") if text else ""


def match_rule(request: Request, config: dict[str, Any]) -> dict[str, Any]:
    path = request.url.path
    method = request.method.upper()
    candidates = []
    for rule in config.get("rules", []):
        if not rule.get("enabled", True):
            continue
        methods = rule.get("methods") or ["*"]
        if "*" not in methods and method not in methods:
            continue
        pattern = rule.get("pattern") or "*"
        if pattern == "*" or path == pattern or path.startswith(f"{pattern.rstrip('/')}/"):
            candidates.append(rule)
    if not candidates:
        return config["defaultRule"]
    return sorted(candidates, key=lambda item: len(item.get("pattern") or ""), reverse=True)[0]


def client_identifier(request: Request, config: dict[str, Any]) -> dict[str, str]:
    ip = request.client.host if request.client else "unknown"
    if config.get("trustProxyHeaders"):
        forwarded = request.headers.get("x-forwarded-for") or request.headers.get("x-real-ip")
        if forwarded:
            ip = forwarded.split(",")[0].strip()
    header_identity = (
        request.headers.get("x-user-email")
        or request.headers.get("x-user-id")
        or request.headers.get("x-admin-email")
    )
    identity = str(header_identity or ip)[:180]
    if config.get("identifier") == "ip_user_agent":
        bucket = f"{ip}:{request.headers.get('user-agent', '')[:160]}"
    else:
        bucket = ip
    return {"bucket": bucket, "ip": ip, "identity": identity}


def hash_key(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


speed_rate_limiter = SpeedRateLimiter()
