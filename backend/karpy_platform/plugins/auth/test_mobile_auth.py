"""Mobile-app sign-in: tokens in the body, device-bound OTP/trust, refresh rotation, staff refused."""
from __future__ import annotations

import secrets
import unittest
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from karpy_platform.core.acl.models import User, utcnow
from karpy_platform.core.acl.routes import hash_password

from .models import AuthChallenge, AuthSession
from .routes import router
from .security import ACCESS_COOKIE, decode_access_token, issue_access_token
from .test_flows import AuthenticationFlowTests

BASE = "/api/plugins/auth/mobile/v1"
PASSWORD = "merchant-password"


def device_id() -> str:
    return secrets.token_urlsafe(32)


class MobileAuthTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await AuthenticationFlowTests.asyncSetUp(self)
        from karpy_platform.core.setting.models import Setting
        async with AsyncSession(self.engine, expire_on_commit=False) as db:
            db.add(Setting(key="email_driver", value="smtp"))
            self.user = User(first_name="Real", last_name="Merchant", username="merchant", email="merchant@example.com",
                             password=hash_password(PASSWORD), permissions={}, email_verified_at=utcnow(),
                             phone="+255684104712", roles=[], meta=[])
            db.add(self.user)
            await db.commit()
            self.user_id = self.user.id
        self.app = FastAPI()
        self.app.include_router(router, prefix="/api/plugins/auth")

        async def database():
            async with AsyncSession(self.engine, expire_on_commit=False) as session:
                yield session

        self.app.dependency_overrides[get_db] = database
        self.http = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url="https://api.example.test",
                                      headers={"user-agent": "okhttp/4.12"})
        self.email = AsyncMock(return_value=SimpleNamespace(sent=True, driver="smtp"))
        self.mail_patch = patch("karpy_platform.plugins.auth.routes._send_code", self.email)
        self.mail_patch.start()
        self.device = device_id()

    async def asyncTearDown(self):
        self.mail_patch.stop()
        await self.http.aclose()
        await AuthenticationFlowTests.asyncTearDown(self)

    def code(self) -> str:
        return self.email.call_args.args[2]

    def assert_no_cookies(self, response):
        self.assertEqual(response.headers.get_list("set-cookie"), [])
        self.assertEqual(response.headers["cache-control"], "no-store")

    async def login(self, *, device=None, device_token=None, email="merchant@example.com", password=PASSWORD):
        body = {"email": email, "password": password, "device_id": device or self.device,
                "device_name": "Amina's iPhone", "platform": "ios"}
        if device_token:
            body["device_token"] = device_token
        return await self.http.post(f"{BASE}/login", json=body)

    async def verify(self, challenge, code, *, device=None):
        return await self.http.post(f"{BASE}/verify-login", json={
            "challenge_token": challenge, "code": code, "device_id": device or self.device,
            "device_name": "Amina's iPhone", "platform": "ios"})

    async def signed_in(self) -> dict:
        started = await self.login()
        self.assertEqual(started.status_code, 200, started.text)
        verified = await self.verify(started.json()["challenge_token"], self.code())
        self.assertEqual(verified.status_code, 200, verified.text)
        return verified.json()

    async def age_login_challenges(self):
        async with AsyncSession(self.engine) as db:
            for row in (await db.scalars(select(AuthChallenge).where(AuthChallenge.purpose.like("login:%")))).all():
                row.created_at = utcnow() - timedelta(seconds=61)
            await db.commit()

    async def test_new_device_needs_code_and_tokens_come_back_in_the_body(self):
        started = await self.login()
        self.assertEqual(started.status_code, 200, started.text)
        self.assert_no_cookies(started)
        body = started.json()
        self.assertTrue(body["requiresOTP"])
        self.assertEqual(body["channels"], ["email"])
        self.assertEqual(body["resend_after"], 60)
        self.assertEqual(body["challenge_expires_in"], 300)
        self.assertTrue(body["challenge_token"].startswith("m.") and body["resend_token"].startswith("m."))
        self.assertNotIn("access_token", body)
        async with AsyncSession(self.engine) as db:
            self.assertIsNone(await db.scalar(select(AuthSession)))
            # Only hashes of the tokens and of the device id are stored.
            stored = " ".join(row.purpose + row.code_hash for row in (await db.scalars(select(AuthChallenge))).all())
            self.assertNotIn(body["challenge_token"][2:], stored)
            self.assertNotIn(self.device, stored)

        # The code is bound to this device id: another device cannot use it.
        other = await self.verify(body["challenge_token"], self.code(), device=device_id())
        self.assertEqual(other.status_code, 422)
        verified = await self.verify(body["challenge_token"], self.code())
        self.assertEqual(verified.status_code, 200, verified.text)
        self.assert_no_cookies(verified)
        data = verified.json()
        self.assertEqual(data["user"]["email"], "merchant@example.com")
        self.assertEqual(data["token_type"], "Bearer")
        self.assertEqual(data["expires_in"], 15 * 60)
        self.assertEqual(data["refresh_expires_in"], 30 * 86400)
        self.assertEqual(decode_access_token(data["access_token"])["client"], "mobile")
        self.assertTrue(data["refresh_token"].startswith(decode_access_token(data["access_token"])["sid"] + "."))
        async with AsyncSession(self.engine) as db:
            session = await db.scalar(select(AuthSession))
            self.assertTrue(session.remember)
            self.assertEqual(session.user_agent, "Karpy iOS app · Amina's iPhone")
            self.assertGreater(session.expires_at, utcnow() + timedelta(days=29))
        # Single use.
        self.assertEqual((await self.verify(body["challenge_token"], self.code())).status_code, 422)

    async def test_wrong_codes_lock_the_challenge_after_five_attempts(self):
        started = (await self.login()).json()
        right = self.code()
        wrong = "000000" if right != "000000" else "111111"
        for _ in range(5):
            failed = await self.verify(started["challenge_token"], wrong)
            self.assertEqual(failed.status_code, 422)
            self.assertEqual(failed.json()["detail"], {"code": "The sign-in code is invalid or expired."})
        self.assertEqual((await self.verify(started["challenge_token"], right)).status_code, 422)

    async def test_web_and_mobile_challenge_tokens_do_not_cross(self):
        started = (await self.login()).json()
        # The browser verify reads a cookie with an r./s. prefix; a mobile token is refused there.
        self.http.cookies.set("app_login_challenge", started["challenge_token"])
        web = await self.http.post("/api/plugins/auth/user/verify-login", json={"code": self.code()})
        self.assertEqual(web.status_code, 422)
        self.http.cookies.clear()
        self.assertEqual((await self.verify(started["challenge_token"], self.code())).status_code, 200)

    async def test_resend_rotates_the_challenge_for_the_same_device_only(self):
        started = (await self.login()).json()
        old_code = self.code()
        early = await self.http.post(f"{BASE}/resend-login", json={"resend_token": started["resend_token"], "device_id": self.device})
        self.assertEqual(early.status_code, 429)
        await self.age_login_challenges()
        stranger = await self.http.post(f"{BASE}/resend-login", json={"resend_token": started["resend_token"], "device_id": device_id()})
        self.assertEqual(stranger.status_code, 422)
        self.assertEqual(stranger.json()["detail"], {"form": "Your sign-in attempt expired. Please sign in again."})
        resent = await self.http.post(f"{BASE}/resend-login", json={"resend_token": started["resend_token"], "device_id": self.device})
        self.assertEqual(resent.status_code, 200, resent.text)
        self.assert_no_cookies(resent)
        body = resent.json()
        self.assertEqual(body["resend_token"], started["resend_token"])
        self.assertNotEqual(body["challenge_token"], started["challenge_token"])
        self.assertEqual((await self.verify(started["challenge_token"], old_code)).status_code, 422)
        self.assertEqual((await self.verify(body["challenge_token"], self.code())).status_code, 200)

    async def test_trusted_device_token_skips_the_code_with_web_invalidation_rules(self):
        first = await self.signed_in()
        token = first["device_token"]
        self.assertEqual(first["device_token_expires_in"], 30 * 86400)
        again = await self.login(device_token=token)
        self.assertEqual(again.status_code, 200, again.text)
        self.assertIn("access_token", again.json())
        self.assertNotIn("requiresOTP", again.json())
        # The token is bound to the device id.
        await self.age_login_challenges()
        self.assertTrue((await self.login(device=device_id(), device_token=token)).json()["requiresOTP"])
        # "Sign out other devices" (device epoch) forgets it, like the browser trusted device.
        bearer = {"authorization": "Bearer " + again.json()["access_token"]}
        revoked = await self.http.post("/api/plugins/auth/user/sessions/revoke-others", headers=bearer)
        self.assertEqual(revoked.status_code, 200, revoked.text)
        await self.age_login_challenges()
        self.assertTrue((await self.login(device_token=token)).json()["requiresOTP"])
        # The session that revoked the others stays signed in.
        self.assertEqual((await self.http.get(f"{BASE}/me", headers=bearer)).status_code, 200)

    async def test_password_change_forgets_the_trusted_device(self):
        token = (await self.signed_in())["device_token"]
        async with AsyncSession(self.engine) as db:
            (await db.get(User, self.user_id)).password = hash_password("Another-password9!")
            await db.commit()
        await self.age_login_challenges()
        self.assertTrue((await self.login(device_token=token, password="Another-password9!")).json()["requiresOTP"])

    async def test_password_errors_and_lockout_match_the_web_login(self):
        web = await self.http.post("/api/plugins/auth/user/login", json={"email": "merchant@example.com", "password": "wrong"})
        mobile = await self.login(password="wrong")
        self.assertEqual((mobile.status_code, mobile.json()), (web.status_code, web.json()))
        self.assertEqual(mobile.json()["detail"], {"email": "These credentials do not match our records."})
        unknown = await self.login(email="nobody@example.com", password="wrong")
        self.assertEqual(unknown.json(), mobile.json())
        for _ in range(10):
            last = await self.login(password="wrong")
            if last.status_code == 429:
                break
        self.assertEqual(last.status_code, 429)
        self.assertEqual(last.json()["detail"], {"form": "Too many sign-in attempts. Please try again later."})

    async def test_suspended_and_unverified_accounts_get_the_web_errors(self):
        from karpy_platform.core.acl.models import UserMeta
        async with AsyncSession(self.engine) as db:
            db.add(UserMeta(user_id=self.user_id, key="auth.account_status", value="deactivated"))
            await db.commit()
        suspended = await self.login()
        self.assertEqual(suspended.status_code, 403)
        self.assertEqual(suspended.json()["detail"]["accountStatus"], "deactivated")
        async with AsyncSession(self.engine) as db:
            user = await db.get(User, self.user_id)
            user.email_verified_at = None
            await db.commit()
        self.assertTrue((await self.login()).json()["detail"]["requiresVerification"])

    async def test_banned_account_learns_at_once_with_code_and_reason(self):
        from karpy_platform.core.acl.models import UserMeta
        from .account_state import revoke_user_sessions
        from .device_verification import mobile_device_hash
        from .models import PushDevice
        tokens = await self.signed_in()
        async with AsyncSession(self.engine) as db:
            db.add(PushDevice(installation_hash=mobile_device_hash(self.device), user_id=self.user_id, platform="ios",
                              provider="apns", token="push-token"))
            db.add(UserMeta(user_id=self.user_id, key="auth.account_status", value="banned"))
            db.add(UserMeta(user_id=self.user_id, key="account.restriction_reason", value="Repeated  policy violations"))
            # What Platform Admin → Access does for deactivate and ban.
            self.assertEqual(await revoke_user_sessions(db, self.user_id), 1)
            await db.commit()
        bearer = {"authorization": "Bearer " + tokens["access_token"]}
        self.assertEqual((await self.http.get(f"{BASE}/me", headers=bearer)).status_code, 401)
        refused = await self.http.post(f"{BASE}/refresh", json={"refresh_token": tokens["refresh_token"], "device_id": self.device})
        self.assertEqual(refused.status_code, 403)
        self.assertEqual(refused.headers["cache-control"], "no-store")
        self.assertEqual(refused.json(), {
            "detail": "Your account has been banned. Contact support if you believe this is a mistake.",
            "code": "account_banned", "reason": "Repeated policy violations"})
        async with AsyncSession(self.engine) as db:
            self.assertIsNone(await db.scalar(select(PushDevice)))
        # A refresh token that is not this session's current one learns nothing.
        self.assertEqual((await self.http.post(f"{BASE}/refresh", json={"refresh_token": "x" * 40, "device_id": self.device})).status_code, 401)
        login = await self.login()
        self.assertEqual(login.status_code, 403)
        self.assertEqual(login.json()["detail"], {
            "form": "Your account has been banned. Contact support if you believe this is a mistake.",
            "accountStatus": "banned", "code": "account_banned", "reason": "Repeated policy violations"})
        wrong = await self.login(password="not-the-password")
        self.assertEqual(wrong.status_code, 422)
        self.assertNotIn("policy", wrong.text)

    async def test_deactivated_session_is_sent_to_refresh_and_stale_reasons_stay_hidden(self):
        from karpy_platform.core.acl.models import UserMeta
        tokens = await self.signed_in()
        async with AsyncSession(self.engine) as db:
            db.add(UserMeta(user_id=self.user_id, key="auth.account_status", value="deactivated"))
            # Left from an earlier restriction (not set by the access control): never shown.
            db.add(UserMeta(user_id=self.user_id, key="account.restriction", value="restricted"))
            db.add(UserMeta(user_id=self.user_id, key="account.restriction_reason", value="Old restriction note"))
            await db.commit()
        # The bearer gets 401 (not 403) so the app refreshes and learns the status there.
        me = await self.http.get(f"{BASE}/me", headers={"authorization": "Bearer " + tokens["access_token"]})
        self.assertEqual(me.status_code, 401)
        refused = await self.http.post(f"{BASE}/refresh", json={"refresh_token": tokens["refresh_token"], "device_id": self.device})
        self.assertEqual(refused.status_code, 403)
        self.assertEqual(refused.json()["code"], "account_deactivated")
        self.assertIsNone(refused.json()["reason"])
        self.assertNotIn("Old restriction", (await self.login()).text)

    async def test_platform_admin_and_staff_are_refused(self):
        async with AsyncSession(self.engine) as db:
            (await db.get(User, self.user_id)).super_user = True
            await db.commit()
        refused = await self.login()
        self.assertEqual(refused.status_code, 403)
        self.assertEqual(refused.json()["detail"]["mobileAccess"], "staff_not_allowed")
        self.assertIn("Staff accounts", refused.json()["detail"]["form"])
        self.email.assert_not_awaited()
        async with AsyncSession(self.engine) as db:
            self.assertIsNone(await db.scalar(select(AuthSession)))

    async def test_staff_promotion_ends_the_mobile_session_at_refresh(self):
        tokens = await self.signed_in()
        async with AsyncSession(self.engine) as db:
            (await db.get(User, self.user_id)).super_user = True
            await db.commit()
        refused = await self.http.post(f"{BASE}/refresh", json={"refresh_token": tokens["refresh_token"], "device_id": self.device})
        self.assertEqual(refused.status_code, 403)
        self.assertEqual(refused.json()["detail"]["mobileAccess"], "staff_not_allowed")

    async def test_refresh_rotates_and_replay_revokes_the_session(self):
        tokens = await self.signed_in()
        refreshed = await self.http.post(f"{BASE}/refresh", json={"refresh_token": tokens["refresh_token"], "device_id": self.device})
        self.assertEqual(refreshed.status_code, 200, refreshed.text)
        self.assert_no_cookies(refreshed)
        new = refreshed.json()
        self.assertNotEqual(new["refresh_token"], tokens["refresh_token"])
        self.assertEqual(decode_access_token(new["access_token"])["client"], "mobile")
        self.assertEqual(decode_access_token(new["access_token"])["sid"], decode_access_token(tokens["access_token"])["sid"])
        # Within the grace window a racing replay is refused but does not end the session.
        raced = await self.http.post(f"{BASE}/refresh", json={"refresh_token": tokens["refresh_token"], "device_id": self.device})
        self.assertEqual(raced.status_code, 401)
        async with AsyncSession(self.engine) as db:
            session = await db.scalar(select(AuthSession))
            self.assertIsNone(session.revoked_at)
            session.last_used_at = utcnow() - timedelta(seconds=30)
            await db.commit()
        replay = await self.http.post(f"{BASE}/refresh", json={"refresh_token": tokens["refresh_token"], "device_id": self.device})
        self.assertEqual(replay.status_code, 401)
        async with AsyncSession(self.engine) as db:
            self.assertIsNotNone((await db.scalar(select(AuthSession))).revoked_at)
        self.assertEqual((await self.http.post(f"{BASE}/refresh", json={"refresh_token": new["refresh_token"], "device_id": self.device})).status_code, 401)
        self.assertEqual((await self.http.get(f"{BASE}/me", headers={"authorization": "Bearer " + new["access_token"]})).status_code, 401)

    async def test_refresh_needs_the_same_device_and_is_not_a_web_refresh(self):
        tokens = await self.signed_in()
        async with AsyncSession(self.engine) as db:
            (await db.scalar(select(AuthSession))).last_used_at = utcnow() - timedelta(seconds=30)
            await db.commit()
        # The browser refresh never accepts a mobile refresh token (it is device-bound).
        self.http.cookies.set("karpy_user_refresh", tokens["refresh_token"])
        self.assertEqual((await self.http.post("/api/plugins/auth/user/refresh")).status_code, 401)
        self.http.cookies.clear()
        async with AsyncSession(self.engine) as db:
            self.assertIsNotNone((await db.scalar(select(AuthSession))).revoked_at)

    async def test_wrong_device_on_refresh_is_treated_as_theft(self):
        tokens = await self.signed_in()
        async with AsyncSession(self.engine) as db:
            (await db.scalar(select(AuthSession))).last_used_at = utcnow() - timedelta(seconds=30)
            await db.commit()
        stolen = await self.http.post(f"{BASE}/refresh", json={"refresh_token": tokens["refresh_token"], "device_id": device_id()})
        self.assertEqual(stolen.status_code, 401)
        self.assertEqual((await self.http.post(f"{BASE}/refresh", json={"refresh_token": tokens["refresh_token"], "device_id": self.device})).status_code, 401)

    async def test_logout_by_bearer_or_by_refresh_token(self):
        tokens = await self.signed_in()
        bearer = {"authorization": "Bearer " + tokens["access_token"]}
        out = await self.http.post(f"{BASE}/logout", json={"refresh_token": tokens["refresh_token"], "device_id": self.device}, headers=bearer)
        self.assertEqual(out.status_code, 200)
        self.assert_no_cookies(out)
        self.assertEqual((await self.http.get(f"{BASE}/me", headers=bearer)).status_code, 401)
        self.assertEqual((await self.http.post(f"{BASE}/refresh", json={"refresh_token": tokens["refresh_token"], "device_id": self.device})).status_code, 401)
        # Expired access token: the refresh token alone ends the session.
        await self.age_login_challenges()
        second = await self.signed_in()
        out = await self.http.post(f"{BASE}/logout", json={"refresh_token": second["refresh_token"], "device_id": self.device},
                                   headers={"authorization": "Bearer expired.or.garbage"})
        self.assertEqual(out.status_code, 200)
        async with AsyncSession(self.engine) as db:
            self.assertEqual([row.revoked_at is not None for row in (await db.scalars(select(AuthSession))).all()], [True, True])

    async def test_me_and_sessions_with_the_mobile_bearer(self):
        tokens = await self.signed_in()
        bearer = {"authorization": "Bearer " + tokens["access_token"]}
        me = await self.http.get(f"{BASE}/me", headers=bearer)
        self.assertEqual(me.status_code, 200, me.text)
        self.assertEqual(me.json()["user"]["email"], "merchant@example.com")
        self.assertEqual((await self.http.get("/api/plugins/auth/user/me", headers=bearer)).status_code, 200)
        sessions = (await self.http.get("/api/plugins/auth/user/sessions", headers=bearer)).json()["sessions"]
        self.assertEqual([(row["client"], row["userAgent"], row["current"]) for row in sessions],
                         [("mobile", "Karpy iOS app · Amina's iPhone", True)])
        # A browser access token is not a mobile session.
        async with AsyncSession(self.engine) as db:
            sid = (await db.scalar(select(AuthSession))).id
        web = issue_access_token(self.user_id, sid)
        self.assertEqual((await self.http.get(f"{BASE}/me", headers={"authorization": "Bearer " + web})).status_code, 401)
        # Mixed with an ambient cookie the bearer is not treated as a mobile request.
        self.http.cookies.set(ACCESS_COOKIE, web)
        self.assertEqual((await self.http.get(f"{BASE}/me", headers=bearer)).status_code, 401)

    async def test_web_cookie_login_is_unchanged(self):
        started = await self.http.post("/api/plugins/auth/user/login", json={"email": "merchant@example.com", "password": PASSWORD})
        self.assertEqual(started.status_code, 200)
        self.assertEqual(set(started.json()), {"requiresOTP", "channels", "resend_after"})
        names = {header.split("=", 1)[0] for header in started.headers.get_list("set-cookie")}
        self.assertEqual(names, {"app_login_challenge", "app_login_resend"})
        verified = await self.http.post("/api/plugins/auth/user/verify-login", json={"code": self.code()})
        self.assertEqual(verified.status_code, 200, verified.text)
        self.assertNotIn("access_token", verified.json())
        access = verified.cookies.get(ACCESS_COOKIE) or self.http.cookies.get(ACCESS_COOKIE)
        self.assertNotIn("client", decode_access_token(access))
        sessions = (await self.http.get("/api/plugins/auth/user/sessions")).json()["sessions"]
        self.assertEqual([row["client"] for row in sessions], ["web"])


if __name__ == "__main__":
    unittest.main()


class MobilePushAndHookTests(unittest.IsolatedAsyncioTestCase):
    """Push registration and the neutral extension points (no product plugin installed)."""

    asyncSetUp = MobileAuthTests.asyncSetUp
    asyncTearDown = MobileAuthTests.asyncTearDown
    code = MobileAuthTests.code
    login = MobileAuthTests.login
    verify = MobileAuthTests.verify
    signed_in = MobileAuthTests.signed_in
    age_login_challenges = MobileAuthTests.age_login_challenges

    async def test_push_device_register_move_and_remove(self):
        from .models import PushDevice
        tokens = await self.signed_in()
        bearer = {"authorization": "Bearer " + tokens["access_token"]}
        body = {"device_id": self.device, "platform": "ios", "provider": "expo", "token": "ExponentPushToken[abc12345]"}
        self.assertEqual((await self.http.post(f"{BASE}/push-devices", json=body)).status_code, 401)
        saved = await self.http.post(f"{BASE}/push-devices", json=body, headers=bearer)
        self.assertEqual(saved.json(), {"registered": True})
        again = await self.http.post(f"{BASE}/push-devices", json={**body, "token": "ExponentPushToken[new67890]"}, headers=bearer)
        self.assertEqual(again.status_code, 200)
        async with AsyncSession(self.engine) as db:
            rows = (await db.scalars(select(PushDevice))).all()
            self.assertEqual([row.token for row in rows], ["ExponentPushToken[new67890]"])
        removed = await self.http.request("DELETE", f"{BASE}/push-devices", json={"device_id": self.device}, headers=bearer)
        self.assertEqual(removed.json(), {"removed": True})
        async with AsyncSession(self.engine) as db:
            self.assertIsNone(await db.scalar(select(PushDevice)))

    async def test_plugins_can_refuse_mobile_access_and_hear_session_end(self):
        from karpy_platform.core.base.hooks import hooks
        ended = []
        refuse = lambda allowed, user: False  # noqa: E731
        listener = lambda db, user_id, reason, session_id=None: ended.append(reason)  # noqa: E731
        tokens = await self.signed_in()
        hooks.add_action("auth.mobile.session_ended", listener)
        self.addCleanup(hooks.remove_action, "auth.mobile.session_ended", listener)
        await self.http.post(f"{BASE}/logout", headers={"authorization": "Bearer " + tokens["access_token"]})
        self.assertEqual(ended, ["signed_out"])
        hooks.add_filter("auth.mobile.allow_user", refuse)
        self.addCleanup(hooks.remove_filter, "auth.mobile.allow_user", refuse)
        await self.age_login_challenges()
        refused = await self.login()
        self.assertEqual(refused.status_code, 403)
        self.assertEqual(refused.json()["detail"]["mobileAccess"], "staff_not_allowed")
