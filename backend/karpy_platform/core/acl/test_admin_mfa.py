"""Exercise MFA through the guarded HTTP API, including replay and lockout."""
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pyotp
from sqlalchemy import select

from karpy_platform.core.acl.test_admin_guard import AdminGuardTests, ORIGIN
from karpy_platform.core.acl.routes import ADMIN_SESSION_COOKIE, hash_password
from karpy_platform.core.acl.models import User, UserMeta, utcnow
from karpy_platform.plugins.auth.models import AuthSecurityEvent


class AdminMfaTests(AdminGuardTests):
    async def change(self, action, code="", password="root-password-long-enough"):
        return await self.http.post("/api/admin/profile/security/" + action,
            json={"currentPassword": password, "code": code}, headers={"origin": ORIGIN})

    async def password_only(self, login="root", password="root-password-long-enough"):
        return await self.http.post("/api/admin/auth/login", json={"login": login, "password": password},
                                    headers={"origin": ORIGIN})

    async def confirm(self, token, code):
        return await self.http.post("/api/admin/auth/login/setup", json={"token": token, "code": code},
                                    headers={"origin": ORIGIN})

    async def enroll(self):
        # Sign-in itself enrols the authenticator for an admin who has none.
        signed = await self.sign_in("root", "root-password-long-enough")
        self.assertEqual(signed.status_code, 200, signed.text)
        self.assertIn(ADMIN_SESSION_COOKIE, signed.cookies)
        codes = signed.json()["recovery_codes"]
        self.assertEqual(len(codes), 8)
        self.assertTrue(all(len(code) == 32 for code in codes))
        return self.totp_secrets["root"], codes

    async def unenrolled_session(self):
        """A signed-in admin who then switched the authenticator off in profile security."""
        _, codes = await self.enroll()
        self.assertEqual((await self.change("disable", codes[0])).status_code, 200)

    async def test_password_alone_never_issues_a_session_without_an_authenticator(self):
        for login, password in (("root", "root-password-long-enough"), ("editor", "editor-password-long")):
            first = await self.password_only(login, password)
            self.assertEqual(first.status_code, 200, first.text)
            body = first.json()
            self.assertTrue(body["mfa_setup_required"])
            self.assertTrue(body["qr"].startswith("data:image/png;base64,"))
            self.assertNotIn(ADMIN_SESSION_COOKIE, first.cookies)
            self.assertEqual(first.headers["cache-control"], "no-store")
            # A code sent with the password does not skip setup either.
            with_code = await self.http.post("/api/admin/auth/login", json={
                "login": login, "password": password, "code": pyotp.TOTP(body["secret"]).now()}, headers={"origin": ORIGIN})
            self.assertTrue(with_code.json()["mfa_setup_required"])
            self.assertNotIn(ADMIN_SESSION_COOKIE, with_code.cookies)
        self.assertEqual((await self.http.get("/api/admin/profile")).status_code, 401)
        self.assertEqual((await self.http.get("/api/admin/users")).status_code, 401)

    async def test_sign_in_setup_issues_session_once_and_then_requires_codes(self):
        first = (await self.password_only()).json()
        token, secret = first["setup_token"], first["secret"]
        async with self.factory() as db:
            stored = await db.scalar(select(UserMeta.value).where(UserMeta.key == "admin.mfa.v1"))
            self.assertNotIn(secret, stored)
            self.assertNotIn(token.rpartition(".")[2], stored)
        self.assertEqual((await self.confirm(token, "000000" if pyotp.TOTP(secret).now() != "000000" else "111111")).status_code, 422)
        self.assertEqual((await self.http.get("/api/admin/profile")).status_code, 401)
        signed = await self.confirm(token, pyotp.TOTP(secret).now())
        self.assertEqual(signed.status_code, 200, signed.text)
        self.assertIn(ADMIN_SESSION_COOKIE, signed.cookies)
        header = signed.headers["set-cookie"].lower()
        self.assertIn("httponly", header)
        self.assertIn("samesite=strict", header)
        codes = signed.json()["recovery_codes"]
        self.assertEqual((await self.http.get("/api/admin/users")).status_code, 200)
        self.assertTrue((await self.http.get("/api/admin/profile/security")).json()["enabled"])
        # Single use: the token cannot enrol again or mint another session.
        self.http.cookies.clear()
        self.assertEqual((await self.confirm(token, pyotp.TOTP(secret).now())).status_code, 422)
        again = await self.password_only()
        self.assertEqual(again.json(), {"mfa_required": True})
        self.assertNotIn(ADMIN_SESSION_COOKIE, again.cookies)
        recovered = await self.http.post("/api/admin/auth/login", json={
            "login": "root", "password": "root-password-long-enough", "code": codes[0]}, headers={"origin": ORIGIN})
        self.assertEqual(recovered.status_code, 200, recovered.text)
        async with self.factory() as db:
            events = (await db.scalars(select(AuthSecurityEvent.event))).all()
        self.assertIn("admin.authenticator.setup", events)
        self.assertIn("admin.authenticator.enable", events)

    async def test_setup_token_is_bound_to_the_attempt_user_password_and_time(self):
        older = (await self.password_only()).json()
        newer = (await self.password_only()).json()
        # Only the latest sign-in attempt's token and secret work.
        self.assertEqual((await self.confirm(older["setup_token"], pyotp.TOTP(older["secret"]).now())).status_code, 422)
        editor = (await self.password_only("editor", "editor-password-long")).json()
        forged = "editor." + newer["setup_token"].rpartition(".")[2]
        self.assertEqual((await self.confirm(forged, pyotp.TOTP(editor["secret"]).now())).status_code, 422)
        self.assertEqual((await self.confirm("garbage", "123456")).status_code, 422)
        later = time.time() + 601
        with patch("karpy_platform.core.acl.mfa.time.time", return_value=later):
            self.assertEqual((await self.confirm(newer["setup_token"], pyotp.TOTP(newer["secret"]).at(later))).status_code, 422)
        latest = (await self.password_only()).json()
        async with self.factory() as db:
            (await db.get(User, "root")).password = hash_password("changed-password-long-enough")
            await db.commit()
        self.assertEqual((await self.confirm(latest["setup_token"], pyotp.TOTP(latest["secret"]).now())).status_code, 422)
        self.assertNotIn(ADMIN_SESSION_COOKIE, self.http.cookies)

    async def test_wrong_setup_codes_end_the_attempt_and_count_toward_lockout(self):
        body = (await self.password_only()).json()
        good = pyotp.TOTP(body["secret"]).now()
        bad = "000000" if good != "000000" else "111111"
        for _ in range(5):
            self.assertEqual((await self.confirm(body["setup_token"], bad)).status_code, 422)
        # The attempt is spent, and the sign-in lockout now applies to the account from this IP.
        self.assertEqual((await self.confirm(body["setup_token"], good)).status_code, 429)
        self.assertEqual((await self.password_only()).status_code, 429)
        async with self.factory() as db:
            state = await db.scalar(select(UserMeta.value).where(UserMeta.key == "admin.mfa.v1"))
            self.assertNotIn("setup_token", state)
            failures = (await db.scalars(select(AuthSecurityEvent.identity).where(
                AuthSecurityEvent.event == "admin.login.failed"))).all()
        self.assertEqual(failures, ["admin:root"] * 5)

    async def test_google_never_issues_an_admin_session(self):
        from karpy_platform.plugins.social_login import routes as social
        self.app.include_router(social.router, prefix="/api/plugins/social_login")
        flow = SimpleNamespace(return_to=ORIGIN + "/admin", nonce="n")
        async with self.factory() as db:
            root = await db.get(User, "root")
        with patch.object(social, "consume_flow", AsyncMock(return_value=flow)), \
                patch.object(social, "google_configuration", AsyncMock(return_value=SimpleNamespace(configured=True))), \
                patch.object(social, "exchange_code", AsyncMock(return_value={"id_token": "x"})), \
                patch.object(social, "verify_google_identity", AsyncMock(return_value={})), \
                patch.object(social, "resolve_social_user", AsyncMock(return_value=root)):
            response = await self.http.get("/api/plugins/social_login/google/callback?state=s&code=c")
        self.assertEqual(response.status_code, 302)
        self.assertIn("social_login_error", response.headers["location"])
        self.assertNotIn(ADMIN_SESSION_COOKIE, response.cookies)
        self.assertEqual((await self.http.get("/api/admin/users")).status_code, 401)

    async def test_enrollment_encryption_login_no_session_until_mfa_and_replay(self):
        secret, codes = await self.enroll()
        async with self.factory() as db:
            value = await db.scalar(select(UserMeta.value).where(UserMeta.key == "admin.mfa.v1"))
            self.assertNotIn(secret, value)
            self.assertNotIn(codes[0], value)
        self.http.cookies.clear()
        first = await self.sign_in("root", "root-password-long-enough")
        self.assertTrue(first.json()["mfa_required"])
        self.assertNotIn(ADMIN_SESSION_COOKIE, first.cookies)
        self.assertEqual((await self.http.get("/api/admin/profile")).status_code, 401)
        async def login(code):
            return await self.http.post("/api/admin/auth/login", json={"login":"root", "password":"root-password-long-enough", "code":code}, headers={"origin":ORIGIN})
        # The code that confirmed enrolment cannot be replayed to sign in.
        self.assertEqual((await login(self.totp_codes["root"])).status_code, 422)
        later = time.time() + 60
        with patch("karpy_platform.core.acl.mfa.time.time", return_value=later):
            code = pyotp.TOTP(secret).at(later)
            signed = await login(code)
            self.assertEqual(signed.status_code, 200, signed.text)
            self.assertIn(ADMIN_SESSION_COOKIE, signed.cookies)
            self.assertEqual((await login(code)).status_code, 422)
        self.assertEqual((await login(codes[0])).status_code, 200)
        self.assertEqual((await login(codes[0])).status_code, 422)

    async def test_profile_requires_password_and_mfa_and_revokes_copied_session(self):
        _, codes = await self.enroll()
        async with self.factory() as db:
            user = await db.get(User, "root")
            user.email_verified_at = utcnow()
            await db.commit()
        copied = self.http.cookies.get(ADMIN_SESSION_COOKIE)
        path = "/api/admin/profile"
        headers = {"origin":ORIGIN}
        self.assertEqual((await self.http.post(path,json={"phone":"+255712345678"},headers=headers)).status_code,422)
        response = await self.http.post(path,json={"email":"new@example.com", "phone":"+255712345678", "newPassword":"new-long-password-for-root", "currentPassword":"root-password-long-enough", "code":codes[0]},headers=headers)
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual((await self.http.get(path)).json()["email"],"new@example.com")
        self.http.cookies.clear()
        self.http.cookies.set(ADMIN_SESSION_COOKIE,copied)
        self.assertEqual((await self.http.get(path)).status_code,401)
        async with self.factory() as db:
            self.assertIsNone((await db.get(User, "root")).email_verified_at)
            events = (await db.scalars(select(AuthSecurityEvent.event))).all()
            self.assertIn("admin.password.changed",events)
            self.assertIn("admin.profile.updated",events)

    async def test_setup_invalid_code_lockout_and_no_secret_in_history(self):
        await self.unenrolled_session()
        setup = await self.change("setup")
        for _ in range(5):
            self.assertEqual((await self.change("enable","not-a-code")).status_code,422)
        self.assertEqual((await self.change("enable",pyotp.TOTP(setup.json()["secret"]).now())).status_code,429)
        history = await self.http.get("/api/admin/profile/security")
        self.assertEqual(history.status_code,200)
        self.assertNotIn(setup.json()["secret"],history.text)
        self.assertNotIn(self.totp_secrets["root"],history.text)
        self.assertTrue(all(event["at"].endswith("+00:00") for event in history.json()["events"]))
        self.assertEqual(history.json()["enabled"],False)

    async def test_expired_setup_and_disable_require_reauthentication(self):
        await self.unenrolled_session()
        setup = await self.change("setup")
        later = time.time()+601
        with patch("karpy_platform.core.acl.mfa.time.time",return_value=later):
            self.assertEqual((await self.change("enable",pyotp.TOTP(setup.json()["secret"]).at(later))).status_code,422)
        # Signing in again after switching it off enrols a fresh authenticator.
        _, codes = await self.enroll()
        self.assertEqual((await self.change("disable")).status_code,422)
        self.assertEqual((await self.change("disable",codes[0])).status_code,200)
        self.assertFalse((await self.http.get("/api/admin/profile/security")).json()["enabled"])
