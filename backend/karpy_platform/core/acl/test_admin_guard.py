"""Admin API authentication, session revocation, escalation and installer lock."""
from __future__ import annotations

import unittest
from unittest.mock import patch

import httpx
import pyotp
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.database import Base, get_db, load_models
from karpy_platform.core.acl.admin_guard import AdminAuthMiddleware
from karpy_platform.core.acl.models import User, UserMeta
from karpy_platform.core.acl.routes import (
    ADMIN_SESSION_COOKIE,
    ADMIN_SESSION_EPOCH_KEY,
    hash_password,
    make_session_token,
    password_fingerprint,
    router,
)
from karpy_platform.packages.installer.routes import router as installer_router
from karpy_platform.plugins.auth.models import AuthSecurityEvent

ORIGIN = "https://admin.test"


class AdminGuardTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.patches = [
            patch.object(settings, "ADMIN_DASHBOARD_URL", ORIGIN),
            patch.object(settings, "SECRET_KEY", "admin-guard-test-secret-key-32-bytes!!"),
        ]
        for item in self.patches:
            item.start()
        load_models()
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(self.engine, class_=AsyncSession, expire_on_commit=False)
        self.app = FastAPI()
        self.app.state.admin_session_factory = factory
        self.app.add_middleware(AdminAuthMiddleware)
        self.app.include_router(router, prefix="/api/admin")
        self.app.include_router(installer_router, prefix="/api/install")

        async def database():
            async with factory() as session:
                yield session

        self.app.dependency_overrides[get_db] = database
        self.http = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url=ORIGIN)
        async with factory() as db:
            db.add_all([
                User(id="root", username="root", email="root@admin.test", super_user=True,
                     manage_supers=True, password=hash_password("root-password-long-enough")),
                User(id="editor", username="editor", email="editor@admin.test",
                     permissions={"users.index": True, "users.edit": True},
                     password=hash_password("editor-password-long")),
                User(id="merchant", username="merchant", email="merchant@shop.test", permissions={},
                     password=hash_password("merchant-password-long")),
            ])
            await db.commit()
        self.factory = factory
        self.totp_secrets: dict[str, str] = {}
        self.totp_codes: dict[str, str] = {}

    async def asyncTearDown(self):
        await self.http.aclose()
        await self.engine.dispose()
        for item in self.patches:
            item.stop()

    async def sign_in(self, login: str, password: str) -> httpx.Response:
        """Password sign-in; an admin without an authenticator enrols one first (sign-in setup step)."""
        response = await self.http.post("/api/admin/auth/login", json={"login": login, "password": password},
                                        headers={"origin": ORIGIN})
        if response.status_code == 200 and response.json().get("mfa_setup_required"):
            self.assertNotIn(ADMIN_SESSION_COOKIE, response.cookies)
            body = response.json()
            self.totp_secrets[login] = body["secret"]
            self.totp_codes[login] = pyotp.TOTP(body["secret"]).now()
            response = await self.http.post("/api/admin/auth/login/setup", json={
                "token": body["setup_token"], "code": self.totp_codes[login]}, headers={"origin": ORIGIN})
        return response

    async def test_admin_api_rejects_requests_without_a_session(self):
        for method, path in [("GET", "/api/admin/users"), ("PATCH", "/api/admin/users/merchant"),
                             ("DELETE", "/api/admin/users/merchant"), ("GET", "/api/admin/roles")]:
            response = await self.http.request(method, path, json={"superUser": True}, headers={"origin": ORIGIN})
            self.assertEqual(response.status_code, 401, (method, path))
        async with self.factory() as db:
            merchant = await db.get(User, "merchant")
            self.assertFalse(merchant.super_user)

    async def test_forged_or_unsigned_tokens_are_rejected(self):
        self.http.cookies.set(ADMIN_SESSION_COOKIE, "root:1:" + "0" * 64)
        self.assertEqual((await self.http.get("/api/admin/users")).status_code, 401)

    async def test_merchants_cannot_sign_in_to_admin_and_failures_are_recorded(self):
        response = await self.sign_in("merchant@shop.test", "merchant-password-long")
        self.assertEqual(response.status_code, 422)
        self.assertNotIn(ADMIN_SESSION_COOKIE, response.cookies)
        async with self.factory() as db:
            events = (await db.scalars(select(AuthSecurityEvent.event))).all()
        self.assertIn("admin.login.failed", events)

    async def test_admin_login_locks_after_repeated_failures_from_one_ip(self):
        for _ in range(5):
            self.assertEqual((await self.sign_in("root", "wrong-password")).status_code, 422)
        self.assertEqual((await self.sign_in("root", "root-password-long-enough")).status_code, 429)

    async def test_session_cookie_is_strict_and_logout_revokes_server_side(self):
        response = await self.sign_in("root", "root-password-long-enough")
        self.assertEqual(response.status_code, 200, response.text)
        header = response.headers["set-cookie"].lower()
        self.assertIn("httponly", header)
        self.assertIn("samesite=strict", header)
        token = response.cookies[ADMIN_SESSION_COOKIE]
        self.assertEqual((await self.http.get("/api/admin/users")).status_code, 200)
        self.assertEqual((await self.http.post("/api/admin/auth/logout", headers={"origin": ORIGIN})).status_code, 200)
        # A copied cookie no longer works after logout.
        self.http.cookies.set(ADMIN_SESSION_COOKIE, token)
        self.assertEqual((await self.http.get("/api/admin/users")).status_code, 401)

    async def test_password_change_ends_existing_sessions(self):
        self.http.cookies.set(ADMIN_SESSION_COOKIE, make_session_token(
            "root", "0", password_fingerprint(hash_password("unrelated"))))
        self.assertEqual((await self.http.get("/api/admin/users")).status_code, 401)

    async def test_cross_site_writes_are_refused(self):
        await self.sign_in("root", "root-password-long-enough")
        response = await self.http.patch("/api/admin/users/merchant", json={"firstName": "Changed"},
                                          headers={"origin": "https://evil.test"})
        self.assertEqual(response.status_code, 403)

    async def test_limited_admin_cannot_grant_super_or_extra_permissions(self):
        self.assertEqual((await self.sign_in("editor", "editor-password-long")).status_code, 200)
        headers = {"origin": ORIGIN}
        self.assertEqual((await self.http.patch("/api/admin/users/editor", json={"superUser": True}, headers=headers)).status_code, 403)
        self.assertEqual((await self.http.patch("/api/admin/users/merchant", json={"permissions": ["users.destroy"]}, headers=headers)).status_code, 403)
        self.assertEqual((await self.http.patch("/api/admin/users/root", json={"firstName": "Hijack"}, headers=headers)).status_code, 403)
        self.assertEqual((await self.http.delete("/api/admin/users/merchant", headers=headers)).status_code, 403)
        ok = await self.http.patch("/api/admin/users/merchant", json={"permissions": ["users.index"]}, headers=headers)
        self.assertEqual(ok.status_code, 200, ok.text)

    async def test_bumping_the_epoch_revokes_every_session(self):
        await self.sign_in("root", "root-password-long-enough")
        async with self.factory() as db:
            # Sign-in setup already rotated the epoch once, so update that row when present.
            epoch = await db.scalar(select(UserMeta).where(
                UserMeta.user_id == "root", UserMeta.key == ADMIN_SESSION_EPOCH_KEY))
            if epoch:
                epoch.value = "rotated"
            else:
                db.add(UserMeta(user_id="root", key=ADMIN_SESSION_EPOCH_KEY, value="rotated"))
            await db.commit()
        self.assertEqual((await self.http.get("/api/admin/users")).status_code, 401)

    async def test_installer_cannot_wipe_users_once_installed(self):
        response = await self.http.post("/api/install/account", json={
            "first_name": "Evil", "last_name": "Admin", "username": "evil", "email": "evil@evil.test",
            "password": "evil-password", "password_confirmation": "evil-password",
        })
        self.assertEqual(response.status_code, 403)
        self.assertEqual((await self.http.post("/api/install/environment", json={})).status_code, 403)
        async with self.factory() as db:
            self.assertEqual(len((await db.scalars(select(User.id))).all()), 3)


if __name__ == "__main__":
    unittest.main()
