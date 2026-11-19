from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from fastapi import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from starlette.requests import Request

from app.config import settings
from app.database import Base, load_models
from karpy_platform.core.acl.models import User, utcnow
from karpy_platform.core.acl.routes import hash_password, verify_password
from karpy_platform.plugins.auth.models import AuthChallenge, AuthSession
from karpy_platform.plugins.auth.routes import _new_challenge, resend, reset_password, verify_email
from karpy_platform.plugins.auth.schemas import ResendCodeRequest, ResetPasswordRequest, VerifyEmailRequest


def request_for_auth() -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "scheme": "https",
            "server": ("api.example.test", 443),
            "path": "/api/plugins/auth/user/test",
            "query_string": b"",
            "headers": [(b"user-agent", b"karpy-security-test")],
            "client": ("127.0.0.1", 12345),
        }
    )


class AuthenticationFlowTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        load_models()
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        self.settings_patch = patch.object(settings, "JWT_SECRET", "test-jwt-secret-that-is-at-least-32-bytes")
        self.settings_patch.start()

    async def asyncTearDown(self) -> None:
        self.settings_patch.stop()
        await self.engine.dispose()

    async def test_resend_only_delivers_for_registered_unverified_accounts(self) -> None:
        async with AsyncSession(self.engine, expire_on_commit=False) as session:
            verified = User(username="verified", email="verified@example.com", password="unused", permissions={}, email_verified_at=utcnow())
            pending = User(username="pending", email="pending@example.com", password="unused", permissions={})
            session.add_all([verified, pending])
            await session.commit()
            with patch("karpy_platform.plugins.auth.routes._send_code", new_callable=AsyncMock) as delivery:
                unknown_result = await resend(ResendCodeRequest(email="unknown@example.com"), request_for_auth(), session)
                verified_result = await resend(ResendCodeRequest(email=verified.email), request_for_auth(), session)
                delivery.assert_not_awaited()
                self.assertIsNone(await session.scalar(select(AuthChallenge)))
                pending_result = await resend(ResendCodeRequest(email="PENDING@example.com"), request_for_auth(), session)
                delivery.assert_awaited_once()
                challenge = await session.scalar(select(AuthChallenge))
                self.assertEqual(challenge.user_id, pending.id)
                self.assertEqual(challenge.purpose, "verify-email")
            self.assertEqual(unknown_result, verified_result)
            self.assertEqual(unknown_result, pending_result)
            self.assertNotIn("has been sent", unknown_result["message"])

    async def test_email_otp_is_single_use_and_creates_secure_session(self) -> None:
        async with AsyncSession(self.engine, expire_on_commit=False) as session:
            user = User(first_name="OTP", last_name="User", username="otp-user", email="otp@example.com", password="unused", permissions={})
            session.add(user)
            await session.flush()
            challenge, code = await _new_challenge(session, user, "verify-email")
            await session.commit()

            response = Response()
            result = await verify_email(
                VerifyEmailRequest(email=user.email, code=code),
                request_for_auth(),
                response,
                session,
            )
            await session.refresh(challenge)
            created_session = await session.scalar(select(AuthSession).where(AuthSession.user_id == user.id))

        self.assertEqual(result["user"]["email"], user.email)
        self.assertIsNotNone(challenge.consumed_at)
        self.assertIsNotNone(created_session)
        cookies = response.headers.getlist("set-cookie")
        self.assertTrue(any("HttpOnly" in value and "SameSite=lax" in value for value in cookies))

    async def test_password_reset_consumes_otp_revokes_sessions_and_changes_password(self) -> None:
        async with AsyncSession(self.engine, expire_on_commit=False) as session:
            user = User(
                first_name="Reset",
                last_name="User",
                username="reset-user",
                email="reset@example.com",
                password=hash_password("old-password"),
                email_verified_at=utcnow(),
                permissions={},
            )
            session.add(user)
            await session.flush()
            existing = AuthSession(
                user_id=user.id,
                refresh_token_hash="a" * 64,
                expires_at=utcnow(),
            )
            session.add(existing)
            challenge, code = await _new_challenge(session, user, "password-reset")
            await session.commit()

            response = Response()
            await reset_password(
                ResetPasswordRequest(
                    email=user.email,
                    code=code,
                    password="New-merchant-password9!",
                    confirmPassword="New-merchant-password9!",
                ),
                request_for_auth(),
                response,
                session,
            )
            await session.refresh(user)
            await session.refresh(existing)
            await session.refresh(challenge)

        self.assertTrue(verify_password("New-merchant-password9!", user.password))
        self.assertFalse(verify_password("old-password", user.password))
        self.assertIsNotNone(existing.revoked_at)
        self.assertIsNotNone(challenge.consumed_at)
        self.assertEqual(response.headers["cache-control"], "no-store")


if __name__ == "__main__":
    unittest.main()
