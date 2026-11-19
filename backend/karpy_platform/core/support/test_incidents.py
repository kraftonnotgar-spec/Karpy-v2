import unittest
from unittest.mock import patch

import httpx
from fastapi import FastAPI, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from karpy_platform.core.base.models import AdminNotification
from .incidents import RuntimeIncidentMiddleware


class RuntimeIncidentTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite://")
        async with self.engine.begin() as conn:
            await conn.run_sync(AdminNotification.__table__.create)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.patch = patch("app.database.async_session", self.sessions)
        self.patch.start()
        app = FastAPI()
        app.add_middleware(RuntimeIncidentMiddleware)

        @app.get("/api/example/{identity}")
        async def broken(identity: str):
            raise AttributeError("secret-otp-123456-password-private@example.test")

        @app.get("/api/unavailable")
        async def unavailable():
            raise HTTPException(503, "private-provider-message")

        @app.get("/api/invalid")
        async def invalid():
            raise HTTPException(422, "invalid_request")

        @app.post("/api/sms-receipt")
        async def sms_receipt(request: Request):
            request.state.incident_code = "sms_receipt_unmatched"
            raise HTTPException(503, "message_not_recorded")

        self.http = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")

    async def asyncTearDown(self):
        await self.http.aclose()
        self.patch.stop()
        await self.engine.dispose()

    async def test_unexpected_failures_create_deduplicated_safe_admin_notices(self):
        with self.assertLogs("karpy.incidents", "ERROR") as logs:
            for reference in ["support-one", "support-two"]:
                response = await self.http.get("/api/example/private-customer?code=123456", headers={"x-request-id": reference})
                self.assertEqual(response.status_code, 500)
                self.assertEqual(response.headers["x-request-id"], reference)
                self.assertNotIn("secret-otp", response.text)
        async with self.sessions() as db:
            notices = list(await db.scalars(select(AdminNotification)))
        self.assertEqual(len(notices), 1)
        self.assertIn("AttributeError", notices[0].description)
        self.assertIn("support-one", notices[0].description)
        self.assertEqual(notices[0].permission, "security.index")
        evidence = " ".join(logs.output) + notices[0].description
        for private in ["123456", "private@example.test", "private-customer", "secret-otp"]:
            self.assertNotIn(private, evidence)
        self.assertIn("/api/example/{identity}", evidence)
        self.assertIn("support-two", evidence)

    async def test_service_errors_record_notices_but_validation_errors_do_not(self):
        with self.assertLogs("karpy.incidents", "ERROR"):
            response = await self.http.get("/api/unavailable")
            self.assertEqual(response.status_code, 503)
            self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertEqual((await self.http.get("/api/invalid")).status_code, 422)
        async with self.sessions() as db:
            notices = list(await db.scalars(select(AdminNotification)))
        self.assertEqual(len(notices), 1)
        self.assertNotIn("private-provider-message", notices[0].description)

    async def test_database_outage_keeps_safe_log_and_does_not_replace_original_error(self):
        with patch("app.database.async_session", side_effect=RuntimeError("database-secret")), self.assertLogs("karpy.incidents", "ERROR") as logs:
            response = await self.http.get("/api/example/one")
        self.assertEqual(response.status_code, 500)
        self.assertNotIn("database-secret", " ".join(logs.output))

    async def test_sms_receipt_failure_has_safe_actionable_hint(self):
        with self.assertLogs("karpy.incidents", "ERROR"):
            response = await self.http.post("/api/sms-receipt")
        self.assertEqual(response.status_code, 503)
        async with self.sessions() as db:
            notices = list(await db.scalars(select(AdminNotification)))
        self.assertIn("SMS receipt has no unique recorded send", notices[0].description)
