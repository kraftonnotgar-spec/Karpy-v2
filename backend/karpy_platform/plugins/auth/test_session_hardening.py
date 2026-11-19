"""Login lockout by account+IP, refresh-token reuse detection and reset-code caps."""
from __future__ import annotations

import unittest
from datetime import timedelta
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from starlette.requests import Request

from app.config import settings
from app.database import Base, load_models
from karpy_platform.core.acl.models import User, utcnow
from karpy_platform.core.acl.routes import hash_password
from karpy_platform.plugins.auth.models import AuthChallenge, AuthSession
from karpy_platform.plugins.auth.routes import _create_session, forgot_password, login, refresh
from karpy_platform.plugins.auth.schemas import ForgotPasswordRequest, LoginRequest
from karpy_platform.plugins.auth.security import REFRESH_COOKIE


def request_from(ip: str, cookie: str = "") -> Request:
    headers = [(b"user-agent", b"karpy-security-test")]
    if cookie:
        headers.append((b"cookie", cookie.encode()))
    return Request({
        "type": "http", "method": "POST", "scheme": "https", "server": ("api.example.test", 443),
        "path": "/api/plugins/auth/user/test", "query_string": b"", "headers": headers, "client": (ip, 12345),
    })


class SessionHardeningTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        load_models()
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        self.patches = [
            patch.object(settings, "JWT_SECRET", "test-jwt-secret-that-is-at-least-32-bytes"),
            patch.object(settings, "AUTH_OTP_RESEND_SECONDS", 0),
        ]
        for item in self.patches:
            item.start()
        async with AsyncSession(self.engine, expire_on_commit=False) as db:
            self.user = User(username="owner", email="owner@example.com", permissions={},
                             password=hash_password("correct-horse-battery"), email_verified_at=utcnow())
            db.add(self.user)
            await db.commit()

    async def asyncTearDown(self) -> None:
        for item in self.patches:
            item.stop()
        await self.engine.dispose()

    async def attempt(self, db, ip: str, password: str):
        return await login(LoginRequest(email="owner@example.com", password=password, remember=False),
                           request_from(ip), Response(), db)

    async def test_an_attacker_ip_cannot_lock_the_owner_out(self) -> None:
        async with AsyncSession(self.engine, expire_on_commit=False) as db:
            for _ in range(settings.AUTH_MAX_LOGIN_ATTEMPTS):
                with self.assertRaises(HTTPException) as failed:
                    await self.attempt(db, "203.0.113.9", "wrong-password")
                self.assertEqual(failed.exception.status_code, 422)
            with self.assertRaises(HTTPException) as blocked:
                await self.attempt(db, "203.0.113.9", "correct-horse-battery")
            self.assertEqual(blocked.exception.status_code, 429)
            # The owner, from their own address, still gets the device OTP step.
            with patch("karpy_platform.plugins.auth.device_verification.start",
                       new=AsyncMock(return_value={"requiresOTP": True, "channels": ["email"]})):
                result = await self.attempt(db, "198.51.100.4", "correct-horse-battery")
            self.assertTrue(result["requiresOTP"])

    async def test_distributed_guessing_is_capped_per_account(self) -> None:
        with patch.object(settings, "AUTH_MAX_LOGIN_ATTEMPTS_PER_ACCOUNT", 3):
            async with AsyncSession(self.engine, expire_on_commit=False) as db:
                for index in range(3):
                    with self.assertRaises(HTTPException):
                        await self.attempt(db, f"203.0.113.{index + 1}", "wrong-password")
                with self.assertRaises(HTTPException) as blocked:
                    await self.attempt(db, "198.51.100.4", "correct-horse-battery")
                self.assertEqual(blocked.exception.status_code, 429)

    async def test_replaying_a_rotated_refresh_token_ends_the_session(self) -> None:
        async with AsyncSession(self.engine, expire_on_commit=False) as db:
            session, _, first = await _create_session(db, request_from("198.51.100.4"), self.user, False)
            await db.commit()
            self.assertTrue(first.startswith(session.id + "."))
            response = Response()
            await refresh(request_from("198.51.100.4", f"{REFRESH_COOKIE}={first}"), response, db)
            # Past the concurrency grace window, the old token is a stolen-token signal.
            session.last_used_at = utcnow() - timedelta(minutes=1)
            await db.commit()
            with self.assertRaises(HTTPException) as replayed:
                await refresh(request_from("203.0.113.9", f"{REFRESH_COOKIE}={first}"), Response(), db)
            self.assertEqual(replayed.exception.status_code, 401)
            await db.refresh(session)
            self.assertIsNotNone(session.revoked_at)

    async def test_concurrent_refresh_inside_the_grace_window_does_not_revoke(self) -> None:
        async with AsyncSession(self.engine, expire_on_commit=False) as db:
            session, _, first = await _create_session(db, request_from("198.51.100.4"), self.user, False)
            await db.commit()
            await refresh(request_from("198.51.100.4", f"{REFRESH_COOKIE}={first}"), Response(), db)
            with self.assertRaises(HTTPException):
                await refresh(request_from("198.51.100.4", f"{REFRESH_COOKIE}={first}"), Response(), db)
            await db.refresh(session)
            self.assertIsNone(session.revoked_at)

    async def test_reset_codes_are_capped_per_account(self) -> None:
        async with AsyncSession(self.engine, expire_on_commit=False) as db:
            with patch("karpy_platform.plugins.auth.routes._send_code", new_callable=AsyncMock), \
                 patch("karpy_platform.plugins.auth.extensions.phone_binding", return_value=False):
                results = [
                    await forgot_password(ForgotPasswordRequest(email="owner@example.com"), request_from("198.51.100.4"), db)
                    for _ in range(settings.AUTH_RESET_CODES_PER_HOUR + 2)
                ]
            issued = await db.scalar(select(func.count()).select_from(AuthChallenge).where(
                AuthChallenge.purpose == "password-reset"))
            self.assertEqual(issued, settings.AUTH_RESET_CODES_PER_HOUR)
            # Every response is the same generic message: no throttling signal leaks.
            self.assertEqual(len({str(item) for item in results}), 1)
            self.assertEqual(await db.scalar(select(func.count()).select_from(AuthSession)), 0)


if __name__ == "__main__":
    unittest.main()
