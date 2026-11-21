"""AstraCall admin settings: write-only encrypted secrets, enable switch, validation."""

from __future__ import annotations

import unittest

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.database import Base, load_models
from karpy_platform.core.setting.models import Setting
from karpy_platform.core.setting.store import setting_store

from .routes import SmsSettingsPayload, get_sms_settings, put_sms_settings


class SmsSettingsAdminTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        load_models()
        setting_store.clear_cache()
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    async def asyncTearDown(self) -> None:
        setting_store.clear_cache()
        await self.engine.dispose()

    def session(self) -> AsyncSession:
        return AsyncSession(self.engine, expire_on_commit=False)

    async def _stored(self, session: AsyncSession, key: str):
        row = await session.get(Setting, key)
        return row.value if row else None

    async def test_secrets_are_write_only_and_encrypted(self) -> None:
        async with self.session() as session:
            view = await put_sms_settings(
                SmsSettingsPayload(apiKey="sk_live_saved_key_123", webhookSecret="whsec_abcdefgh", senderId="BRAND"),
                db=session,
            )
            self.assertTrue(view["apiKeySaved"])
            self.assertEqual(view["keyMode"], "live")
            self.assertEqual(view["senderId"], "BRAND")
            self.assertTrue(view["webhookSecretSet"])
            # Secrets are never echoed back.
            self.assertNotIn("sk_live_saved_key_123", str(view))
            self.assertNotIn("whsec_abcdefgh", str(view))
            stored = await self._stored(session, "astracall.api_key")
            self.assertTrue(stored.startswith("enc:v1:"))

            # A blank key keeps the saved one.
            setting_store.clear_cache()
            await put_sms_settings(SmsSettingsPayload(apiKey="", senderId="BRAND"), db=session)
            self.assertEqual(await self._stored(session, "astracall.api_key"), stored)

    async def test_rejects_bad_values(self) -> None:
        async with self.session() as session:
            with self.assertRaises(HTTPException) as bad_key:
                await put_sms_settings(SmsSettingsPayload(apiKey="nope"), db=session)
            self.assertEqual(bad_key.exception.status_code, 422)
            with self.assertRaises(HTTPException) as bad_sender:
                await put_sms_settings(SmsSettingsPayload(senderId="bad!*"), db=session)
            self.assertEqual(bad_sender.exception.status_code, 422)

    async def test_enable_switch_sets_the_active_provider(self) -> None:
        async with self.session() as session:
            # Cannot enable without a saved key.
            with self.assertRaises(HTTPException) as missing:
                await put_sms_settings(SmsSettingsPayload(enabled=True), db=session)
            self.assertEqual(missing.exception.status_code, 409)

            setting_store.clear_cache()
            await put_sms_settings(SmsSettingsPayload(apiKey="sk_live_saved_key_123"), db=session)
            setting_store.clear_cache()
            enabled = await put_sms_settings(SmsSettingsPayload(enabled=True), db=session)
            self.assertTrue(enabled["enabled"])
            self.assertEqual(await self._stored(session, "payment.notifications.sms.provider"), "astracall")

            setting_store.clear_cache()
            disabled = await put_sms_settings(SmsSettingsPayload(enabled=False), db=session)
            self.assertFalse(disabled["enabled"])
            self.assertEqual(await self._stored(session, "payment.notifications.sms.provider"), "log")

    async def test_get_reflects_saved_state(self) -> None:
        async with self.session() as session:
            empty = await get_sms_settings(db=session)
            self.assertFalse(empty["apiKeySaved"])
            self.assertEqual(empty["activeProvider"], "log")
            setting_store.clear_cache()
            await put_sms_settings(SmsSettingsPayload(apiKey="sk_test_key_123456", senderId="BRAND"), db=session)
            setting_store.clear_cache()
            view = await get_sms_settings(db=session)
            self.assertTrue(view["apiKeySaved"])
            self.assertEqual(view["keyMode"], "test")


if __name__ == "__main__":
    unittest.main()
