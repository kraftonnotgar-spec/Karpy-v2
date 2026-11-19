import asyncio
import re
import unittest
from datetime import timedelta
from http.cookies import SimpleCookie
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from karpy_platform.core.acl.models import User, UserMeta, utcnow

from . import device_verification as device
from .models import AuthChallenge, AuthSession
from .routes import login, verify_login, resend_login
from .schemas import LoginRequest, VerifyLoginRequest
from .test_flows import AuthenticationFlowTests, request_for_auth


def request_with(response=None, *, agent=None):
    request = request_for_auth()
    if response:
        cookies = SimpleCookie()
        for header in response.headers.getlist("set-cookie"):
            cookies.load(header)
        request.scope["headers"].append((b"cookie", "; ".join(f"{k}={v.value}" for k, v in cookies.items()).encode()))
    if agent:
        request.scope["headers"] = [(key, value) for key, value in request.scope["headers"] if key != b"user-agent"] + [(b"user-agent", agent.encode())]
    return request


class DeviceVerificationTests(AuthenticationFlowTests):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        from karpy_platform.core.base.hooks import hooks
        from karpy_platform.core.setting.models import Setting
        # Delivery evidence goes to plugins through the auth.login_code.delivered action.
        self.delivered = []
        self._listener = lambda db, user_id, statuses: self.delivered.append((user_id, dict(statuses)))
        hooks.add_action("auth.login_code.delivered", self._listener)
        self.addCleanup(hooks.remove_action, "auth.login_code.delivered", self._listener)
        async with AsyncSession(self.engine) as db:
            db.add(Setting(key="email_driver", value="smtp"))
            await db.commit()

    async def user(self, db, *, verified_phone=False):
        from karpy_platform.core.acl.routes import hash_password
        user = User(first_name="Real", last_name="Merchant", username="merchant", email="merchant@example.com",
                    password=hash_password("merchant-password"), permissions={}, email_verified_at=utcnow(),
                    phone="+255684104712", roles=[], meta=[])
        db.add(user)
        await db.flush()
        if verified_phone:
            user.meta.extend([UserMeta(key="auth.phone.verified_number", value=user.phone),
                              UserMeta(key="auth.phone.verified_at", value=utcnow().isoformat())])
        await db.commit()
        return user

    async def start(self, db, user, *, remember=True):
        response = Response()
        email = AsyncMock(return_value=SimpleNamespace(sent=True, driver="smtp"))
        with patch("karpy_platform.plugins.auth.routes._send_code", email):
            result = await login(LoginRequest(email=user.email, password="merchant-password", remember=remember), request_with(), response, db)
        return result, response, email.call_args.args[2]

    async def test_password_never_issues_session_before_otp_and_code_is_single_use(self):
        async with AsyncSession(self.engine, expire_on_commit=False) as db:
            user = await self.user(db)
            result, response, code = await self.start(db, user)
            self.assertTrue(result["requiresOTP"])
            self.assertEqual(result["channels"], ["email"])
            self.assertIsNone(await db.scalar(select(AuthSession)))
            self.assertNotIn("karpy_user_access", str(response.headers))
            request = request_with(response)
            verified = Response()
            await verify_login(VerifyLoginRequest(code=code), request, verified, db)
            self.assertIsNotNone(await db.scalar(select(AuthSession)))
            self.assertIn("karpy_user_access", str(verified.headers))
            self.assertTrue(device.recognized(request_with(verified), user))
            self.assertFalse(device.recognized(request_with(verified, agent="other-browser"), user))
            with self.assertRaises(HTTPException):
                await verify_login(VerifyLoginRequest(code=code), request, Response(), db)
            user.password = "changed-password-hash"
            self.assertFalse(device.recognized(request_with(verified), user))

    async def age_login(self, db):
        for row in (await db.scalars(select(AuthChallenge).where(AuthChallenge.purpose.like("login:%")))).all():
            row.created_at = utcnow() - timedelta(seconds=61)
        await db.commit()

    async def test_resend_rotates_code_and_keeps_remember_and_single_use(self):
        async with AsyncSession(self.engine, expire_on_commit=False) as db:
            user = await self.user(db)
            _, response, old = await self.start(db, user)
            request = request_with(response)
            with self.assertRaises(HTTPException) as limited:
                await resend_login(request, Response(), db)
            self.assertEqual(limited.exception.status_code, 429)
            await self.age_login(db)
            next_response = Response()
            email = AsyncMock(return_value=SimpleNamespace(sent=True, driver="smtp"))
            with patch("karpy_platform.plugins.auth.routes._send_code", email):
                result = await resend_login(request, next_response, db)
            self.assertEqual(result["resend_after"], 60)
            with self.assertRaises(HTTPException):
                await device.consume(db, request, old)
            merged = request_with(next_response)
            identity, remember = await device.consume(db, merged, email.call_args.args[2])
            self.assertEqual(identity, user.id)
            self.assertTrue(remember)
            await db.commit()
            with self.assertRaises(HTTPException):
                await resend_login(request, Response(), db)

    async def test_resend_rejects_missing_cookie_other_browser_password_change_and_expiry(self):
        async with AsyncSession(self.engine, expire_on_commit=False) as db:
            user = await self.user(db)
            _, response, _ = await self.start(db, user)
            await self.age_login(db)
            for request in [request_with(), request_with(response, agent="different-browser")]:
                with self.assertRaises(HTTPException):
                    await resend_login(request, Response(), db)
            original = user.password
            user.password = "changed"
            await db.commit()
            with self.assertRaises(HTTPException):
                await resend_login(request_with(response), Response(), db)
            user.password = original
            retry = await db.scalar(select(AuthChallenge).where(AuthChallenge.purpose.like("resend:%")))
            self.assertLessEqual(len(retry.purpose), 40)
            retry.expires_at = utcnow() - timedelta(seconds=1)
            await db.commit()
            with self.assertRaises(HTTPException):
                await resend_login(request_with(response), Response(), db)

    async def test_resend_can_retry_delivery_failure_after_cooldown(self):
        async with AsyncSession(self.engine, expire_on_commit=False) as db:
            user = await self.user(db)
            _, response, _ = await self.start(db, user)
            await self.age_login(db)
            with patch("karpy_platform.plugins.auth.routes._send_code", AsyncMock(side_effect=RuntimeError("unavailable"))):
                with self.assertRaises(HTTPException) as failed:
                    await resend_login(request_with(response), Response(), db)
            self.assertEqual(failed.exception.status_code, 503)
            await self.age_login(db)
            with patch("karpy_platform.plugins.auth.routes._send_code", AsyncMock(return_value=SimpleNamespace(sent=True, driver="smtp"))):
                result = await resend_login(request_with(response), Response(), db)
            self.assertTrue(result["requiresOTP"])

    async def test_cookie_binding_attempt_limit_and_password_change_invalidate_challenge(self):
        async with AsyncSession(self.engine, expire_on_commit=False) as db:
            user = await self.user(db)
            _, response, code = await self.start(db, user)
            with self.assertRaises(HTTPException):
                await device.consume(db, request_with(), code)
            with self.assertRaises(HTTPException):
                await device.consume(db, request_with(response, agent="other-browser"), code)
            user.password = "reset-password"
            await db.commit()
            with self.assertRaises(HTTPException):
                await device.consume(db, request_with(response), code)
            challenge = await db.scalar(select(AuthChallenge))
            challenge.attempts = 5
            await db.commit()
            with self.assertRaises(HTTPException):
                await device.consume(db, request_with(response), code)
            self.assertIsNone(await db.scalar(select(AuthSession)))

    async def test_verified_phone_requires_both_channels_and_outage_fails_closed(self):
        async with AsyncSession(self.engine, expire_on_commit=False) as db:
            user = await self.user(db, verified_phone=True)
            sms = SimpleNamespace(send_sms=AsyncMock(return_value=SimpleNamespace(test=False, status="processing")))
            with patch("karpy_platform.plugins.auth.extensions.sms_client", AsyncMock(return_value=sms)):
                result, _, code = await self.start(db, user)
            self.assertEqual(result["channels"], ["email", "sms"])
            self.assertIn(code, sms.send_sms.call_args.args[1])
            self.assertEqual(sms.send_sms.call_args.kwargs, {"otp": True})
            self.assertIsNone(await db.scalar(select(AuthSession)))

    async def test_delivery_failure_and_sandbox_sms_never_issue_challenge_cookie(self):
        for verified_phone in [False, True]:
            async with AsyncSession(self.engine, expire_on_commit=False) as db:
                user = await self.user(db, verified_phone=verified_phone)
                response = Response()
                sms = SimpleNamespace(send_sms=AsyncMock(return_value=SimpleNamespace(test=True, status="accepted")))
                with patch("karpy_platform.plugins.auth.extensions.sms_client", AsyncMock(return_value=sms)), patch("karpy_platform.plugins.auth.routes._send_code", AsyncMock(side_effect=RuntimeError("email down"))), self.assertRaises(HTTPException) as raised:
                    await device.start(db, request_with(), response, user, False)
                self.assertEqual(raised.exception.status_code, 503)
                self.assertNotIn("set-cookie", response.headers)
                self.assertIsNotNone((await db.scalar(select(AuthChallenge))).consumed_at)
                await db.delete(user)
                await db.execute(AuthChallenge.__table__.delete())
                await db.commit()

    async def test_issuance_cooldown_and_trust_after_code_without_checkbox(self):
        async with AsyncSession(self.engine, expire_on_commit=False) as db:
            user = await self.user(db)
            _, response, code = await self.start(db, user, remember=False)
            with self.assertRaises(HTTPException) as raised:
                await self.start(db, user)
            self.assertEqual(raised.exception.status_code, 429)
            verified = Response()
            await verify_login(VerifyLoginRequest(code=code), request_with(response), verified, db)
            # A passed code trusts the device for 30 days even without "Remember me" (e.g. Google sign-in).
            self.assertTrue(device.recognized(request_with(verified), user))

    async def test_expired_challenge_cannot_issue_a_session(self):
        async with AsyncSession(self.engine, expire_on_commit=False) as db:
            user = await self.user(db)
            _, response, code = await self.start(db, user)
            challenge = await db.scalar(select(AuthChallenge))
            challenge.expires_at = utcnow() - timedelta(seconds=1)
            await db.commit()
            with self.assertRaises(HTTPException):
                await verify_login(VerifyLoginRequest(code=code), request_with(response), Response(), db)
            self.assertIsNone(await db.scalar(select(AuthSession)))

    async def test_same_code_starts_on_both_channels_without_waiting_for_other_delivery(self):
        async with AsyncSession(self.engine, expire_on_commit=False) as db:
            user = await self.user(db, verified_phone=True)
            sms_started, email_started = asyncio.Event(), asyncio.Event()
            codes = {}

            async def sms_delivery(phone, message, reference, *, otp):
                self.assertEqual(phone, user.phone)
                self.assertTrue(otp)
                codes["sms"] = re.search(r"\b[0-9]{6}\b", message).group()
                sms_started.set()
                await asyncio.wait_for(email_started.wait(), 2)
                return SimpleNamespace(test=False, status="accepted")

            async def email_delivery(session, recipient, code, template):
                self.assertIs(session, db)
                self.assertEqual(recipient.email, user.email)
                self.assertEqual(template, "plugins.auth.login-code")
                codes["email"] = code
                email_started.set()
                await asyncio.wait_for(sms_started.wait(), 2)
                return SimpleNamespace(sent=True, driver="smtp")

            sms = SimpleNamespace(send_sms=AsyncMock(side_effect=sms_delivery))
            response = Response()
            with patch("karpy_platform.plugins.auth.extensions.sms_client", AsyncMock(return_value=sms)), patch("karpy_platform.plugins.auth.routes._send_code", AsyncMock(side_effect=email_delivery)):
                result = await device.start(db, request_with(), response, user, False)
            self.assertEqual(result["channels"], ["email", "sms"])
            self.assertEqual(codes["sms"], codes["email"])
            self.assertEqual(len((await db.scalars(select(AuthChallenge).where(AuthChallenge.purpose.like("login:%")))).all()), 1)
            self.assertEqual(self.delivered, [(user.id, {"email": "provider_accepted", "sms": "provider_accepted"})])
            self.assertNotIn(codes["email"], repr(self.delivered))
            await verify_login(VerifyLoginRequest(code=codes["sms"]), request_with(response), Response(), db)
            with self.assertRaises(HTTPException):
                await verify_login(VerifyLoginRequest(code=codes["email"]), request_with(response), Response(), db)

    async def test_each_delivery_failure_still_attempts_both_and_invalidates_shared_code(self):
        for failed_channel in ["sms", "email"]:
            with self.subTest(channel=failed_channel):
                async with AsyncSession(self.engine, expire_on_commit=False) as db:
                    user = await self.user(db, verified_phone=True)
                    sms = SimpleNamespace(send_sms=AsyncMock(
                        side_effect=RuntimeError("SMS unavailable") if failed_channel == "sms" else None,
                        return_value=SimpleNamespace(test=False, status="accepted"),
                    ))
                    email = AsyncMock(side_effect=RuntimeError("Email unavailable") if failed_channel == "email" else None)
                    response = Response()
                    with patch("karpy_platform.plugins.auth.extensions.sms_client", AsyncMock(return_value=sms)), patch("karpy_platform.plugins.auth.routes._send_code", email), self.assertRaises(HTTPException) as raised:
                        await device.start(db, request_with(), response, user, False)
                    self.assertEqual(raised.exception.status_code, 503)
                    sms.send_sms.assert_awaited_once()
                    email.assert_awaited_once()
                    self.assertNotIn("set-cookie", response.headers)
                    self.assertIsNotNone((await db.scalar(select(AuthChallenge))).consumed_at)
                    self.assertIsNone(await db.scalar(select(AuthSession)))
                    self.assertEqual(self.delivered[-1][1][failed_channel], "submission_unknown")
                    await db.delete(user)
                    await db.execute(AuthChallenge.__table__.delete())
                    await db.commit()

    async def test_unverified_or_changed_phone_receives_email_only(self):
        async with AsyncSession(self.engine, expire_on_commit=False) as db:
            user = await self.user(db, verified_phone=True)
            user.phone = "+255712345678"
            await db.commit()
            with patch("karpy_platform.plugins.auth.extensions.sms_client", AsyncMock()) as sms_factory:
                result, _, _ = await self.start(db, user)
            sms_factory.assert_not_awaited()
            self.assertEqual(result["channels"], ["email"])

    async def test_real_email_submission_is_logged_without_code_or_message_body(self):
        from karpy_platform.core.setting.store import setting_store
        async with AsyncSession(self.engine, expire_on_commit=False) as db:
            user = await self.user(db)
            with patch.object(setting_store, "all", wraps=setting_store.all) as settings_reads, patch("karpy_platform.plugins.auth.routes.mailer.send", return_value=SimpleNamespace(sent=True, driver="smtp")) as send:
                result = await device.start(db, request_with(), Response(), user, False)
            self.assertEqual(result["channels"], ["email"])
            send.assert_called_once()
            self.assertEqual(settings_reads.await_count, 1)  # One shared email/design snapshot.
            self.assertEqual(send.call_args.kwargs["to"], user.email)
            code = re.search(r"\b[0-9]{6}\b", send.call_args.kwargs["text"]).group()
            self.assertEqual(self.delivered, [(user.id, {"email": "provider_accepted"})])
            self.assertNotIn(code, repr(self.delivered))

    async def test_email_send_failure_is_logged_without_provider_error_details(self):
        async with AsyncSession(self.engine, expire_on_commit=False) as db:
            user = await self.user(db)
            response = Response()
            with patch("karpy_platform.plugins.auth.routes.mailer.send", side_effect=RuntimeError("private SMTP diagnostics")), self.assertRaises(HTTPException) as raised:
                await device.start(db, request_with(), response, user, False)
            self.assertEqual(raised.exception.status_code, 503)
            self.assertEqual(self.delivered, [(user.id, {"email": "submission_unknown"})])
            self.assertNotIn("private SMTP", repr(self.delivered))
            self.assertNotIn("set-cookie", response.headers)


class BrowserHashTests(unittest.TestCase):
    def test_browser_updates_keep_the_device_trusted(self):
        from types import SimpleNamespace
        old = SimpleNamespace(headers={"user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/130.0.6723.92 Safari/537.36"})
        new = SimpleNamespace(headers={"user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/131.0.6778.70 Safari/537.36"})
        other = SimpleNamespace(headers={"user-agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 18_1 like Mac OS X) Safari/604.1"})
        self.assertEqual(device.browser_hash(old), device.browser_hash(new))
        self.assertNotEqual(device.browser_hash(old), device.browser_hash(other))
