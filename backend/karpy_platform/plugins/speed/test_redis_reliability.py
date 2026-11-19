from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from starlette.requests import Request
from app.config import settings
from .rate_limiter import DEFAULT_CONFIG, RedisTokenBucketStore, SpeedRateLimiter, client_identifier


def request():
    return Request({"type": "http", "method": "POST", "path": "/api/payments", "headers": [(b"x-forwarded-for", b"attacker-controlled")], "client": ("127.0.0.1", 1234), "scheme": "https", "server": ("api.example.test", 443), "query_string": b""})


class RedisReliabilityTests(unittest.IsolatedAsyncioTestCase):
    async def test_connection_failure_recovers_after_bounded_cooldown(self):
        first = AsyncMock()
        first.ping.side_effect = TimeoutError("private redis connection detail")
        second = AsyncMock()
        store = RedisTokenBucketStore()
        with patch("redis.asyncio.Redis", side_effect=[first, second]) as factory, patch.object(settings, "REDIS_URL", None), patch("karpy_platform.plugins.speed.rate_limiter.time.monotonic", return_value=10):
            self.assertIsNone(await store.client())
            self.assertIsNone(await store.client())
            self.assertEqual(factory.call_count, 1)
            self.assertEqual(factory.call_args.kwargs["socket_timeout"], 1)
            first.aclose.assert_awaited_once()
        with patch("redis.asyncio.Redis", return_value=second), patch.object(settings, "REDIS_URL", None), patch("karpy_platform.plugins.speed.rate_limiter.time.monotonic", return_value=16):
            self.assertIs(await store.client(), second)

    async def test_failed_eval_closes_connection_without_replaying_increment(self):
        client = AsyncMock()
        client.eval.side_effect = ConnectionError("lost after send")
        store = RedisTokenBucketStore()
        store._client = client
        self.assertIsNone(await store.consume("key", 1, 1))
        client.eval.assert_awaited_once()
        client.aclose.assert_awaited_once()
        self.assertIsNone(store._client)

    async def test_failed_connection_cleanup_does_not_mask_unavailability(self):
        client = AsyncMock()
        client.eval.side_effect = TimeoutError("private connection detail")
        client.aclose.side_effect = ConnectionError("private cleanup detail")
        store = RedisTokenBucketStore()
        store._client = client
        self.assertIsNone(await store.consume("key", 1, 1))
        self.assertIsNone(store._client)
        client.eval.assert_awaited_once()

    async def test_production_distributed_admission_never_falls_back_to_memory(self):
        limiter = SpeedRateLimiter()
        config = {**DEFAULT_CONFIG, "mode": "enforce", "storage": "redis", "exemptPaths": []}
        with patch.object(limiter, "is_plugin_active", return_value=True), patch.object(limiter, "config", return_value=config), patch.object(settings, "APP_ENV", "production"), patch.object(settings, "CACHE_ENABLED", True), patch.object(limiter.redis, "consume", new=AsyncMock(return_value=None)), patch.object(limiter.memory, "consume", new=AsyncMock()) as memory:
            decision = await limiter.decide(request())
            self.assertFalse(decision.allowed)
            self.assertEqual(decision.storage, "unavailable")
            self.assertEqual(decision.retry_after, 5)
            memory.assert_not_awaited()

    async def test_production_auto_storage_falls_back_to_memory_instead_of_503(self):
        limiter = SpeedRateLimiter()
        config = {**DEFAULT_CONFIG, "mode": "enforce", "storage": "auto", "exemptPaths": []}
        with patch.object(limiter, "is_plugin_active", return_value=True), patch.object(limiter, "config", return_value=config), patch.object(settings, "APP_ENV", "production"), patch.object(settings, "CACHE_ENABLED", True), patch.object(limiter.redis, "consume", new=AsyncMock(return_value=None)):
            decision = await limiter.decide(request())
            self.assertTrue(decision.allowed)
            self.assertEqual(decision.storage, "memory")

    async def test_development_may_fall_back_but_proxy_headers_are_not_trusted_by_default(self):
        self.assertFalse(DEFAULT_CONFIG["trustProxyHeaders"])
        self.assertEqual(client_identifier(request(), DEFAULT_CONFIG)["ip"], "127.0.0.1")
        limiter = SpeedRateLimiter()
        with patch.object(limiter, "is_plugin_active", return_value=True), patch.object(limiter, "config", return_value={**DEFAULT_CONFIG, "exemptPaths": []}), patch.object(settings, "APP_ENV", "development"), patch.object(settings, "CACHE_ENABLED", False):
            decision = await limiter.decide(request())
            self.assertTrue(decision.allowed)
            self.assertEqual(decision.storage, "memory")
