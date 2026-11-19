from __future__ import annotations

import json
import unittest
from unittest.mock import AsyncMock, patch

from app.config import settings
from app.main import readiness_check
from karpy_platform.plugins.speed.rate_limiter import speed_rate_limiter


class ReadinessTests(unittest.IsolatedAsyncioTestCase):
    async def test_disabled_cache_does_not_claim_or_probe_redis(self):
        with patch("app.migrations.validate_migrations", new=AsyncMock()), patch.object(settings, "CACHE_ENABLED", False), patch.object(speed_rate_limiter.redis, "client", new=AsyncMock()) as connect:
            result = await readiness_check()
        self.assertEqual(result["status"], "ready")
        self.assertNotIn("redis", result["checks"])
        connect.assert_not_awaited()

    async def test_required_redis_failure_returns_safe_unavailable(self):
        with patch("app.migrations.validate_migrations", new=AsyncMock()), patch.object(settings, "CACHE_ENABLED", True), patch.object(speed_rate_limiter.redis, "client", new=AsyncMock(side_effect=ConnectionError("redis://private-user:private-password@internal:6379"))):
            response = await readiness_check()
        self.assertEqual(response.status_code, 503)
        self.assertEqual(json.loads(response.body)["checks"]["redis"], {"status": "unavailable", "code": "dependency_unavailable"})
        self.assertNotIn(b"private-password", response.body)

    async def test_required_redis_is_pinged_before_ready(self):
        client = AsyncMock()
        with patch("app.migrations.validate_migrations", new=AsyncMock()), patch.object(settings, "CACHE_ENABLED", True), patch.object(speed_rate_limiter.redis, "client", new=AsyncMock(return_value=client)):
            result = await readiness_check()
        self.assertEqual(result["checks"]["redis"]["status"], "ready")
        client.ping.assert_awaited_once()

    async def test_schema_failure_never_reports_healthy_dependencies(self):
        with patch("app.migrations.validate_migrations", new=AsyncMock(side_effect=RuntimeError("private schema detail"))), patch.object(speed_rate_limiter.redis, "client", new=AsyncMock()) as connect:
            response = await readiness_check()
        self.assertEqual(response.status_code, 503)
        self.assertEqual(json.loads(response.body)["checks"]["database"]["code"], "schema_drift")
        self.assertNotIn(b"private schema detail", response.body)
        connect.assert_not_awaited()
