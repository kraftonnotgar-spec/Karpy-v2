"""Payment notification dispatch, channel rendering, and the in-app admin API."""

from __future__ import annotations

import unittest
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.database import Base, load_models
from karpy_platform.core.setting.models import Setting
from karpy_platform.core.setting.store import setting_store
from karpy_platform.plugins.payment.models.notification import PaymentNotification
from karpy_platform.plugins.payment.models.payment import Payment
from karpy_platform.plugins.payment.routes import (
    list_notifications,
    mark_all_notifications_read,
    mark_notification_read,
    notifications_unread_count,
)
from karpy_platform.plugins.payment.services.notifications import (
    EVENT_FAILED,
    EVENT_ORDER_CREATED,
    EVENT_RECEIVED,
    dispatch_payment_event,
)
from karpy_platform.plugins.payment.services.notifications.sms import LogSmsProvider
from karpy_platform.plugins.payment.services.payments import create_payment

ALL_CHANNELS = {
    "payment.notifications.enabled": "1",
    "payment.notifications.channels.in_app": "1",
    "payment.notifications.channels.email": "1",
    "payment.notifications.channels.sms": "1",
    "admin_email": "ops@example.test",
    "payment.notifications.sms.recipients": "+10000000000",
    "email_driver": "array",
}


class PaymentNotificationTests(unittest.IsolatedAsyncioTestCase):
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

    async def _seed_settings(self, session: AsyncSession, values: dict[str, str]) -> None:
        for key, value in values.items():
            session.add(Setting(key=key, value=value))
        await session.commit()
        setting_store.clear_cache()

    async def _make_payment(self, session: AsyncSession, **overrides) -> Payment:
        payment = Payment(
            charge_id=overrides.get("charge_id", "CHG-1"),
            amount=overrides.get("amount", Decimal("150.00")),
            currency=overrides.get("currency", "USD"),
            payment_channel="card",
            status=overrides.get("status", "pending"),
            payer_name=overrides.get("payer_name", "Ada Customer"),
        )
        session.add(payment)
        await session.commit()
        await session.refresh(payment)
        return payment

    async def test_each_event_dispatches_to_every_enabled_channel(self) -> None:
        async with self.session() as session:
            await self._seed_settings(session, ALL_CHANNELS)
            for event in (EVENT_RECEIVED, EVENT_FAILED, EVENT_ORDER_CREATED):
                with self.subTest(event=event):
                    payment = await self._make_payment(session)
                    with patch(
                        "karpy_platform.plugins.payment.services.notifications.channels.mailer"
                    ) as mail, patch.object(LogSmsProvider, "send", new=AsyncMock()) as sms:
                        mail.send = MagicMock()
                        summary = await dispatch_payment_event(session, event, payment)
                        await session.commit()

                    self.assertTrue(summary["dispatched"])
                    self.assertEqual(set(summary["channels"]), {"in_app", "email", "sms"})
                    # Email reached the configured admin recipient.
                    mail.send.assert_called_once()
                    self.assertEqual(mail.send.call_args.kwargs["to"], "ops@example.test")
                    # SMS stub provider was invoked for the configured recipient.
                    sms.assert_awaited_once()
                    # In-app row persisted on the same transaction.
                    rows = (
                        await session.execute(
                            select(PaymentNotification).where(PaymentNotification.event == event)
                        )
                    ).scalars().all()
                    self.assertEqual(len(rows), 1)

    async def test_channels_render_event_content(self) -> None:
        async with self.session() as session:
            await self._seed_settings(session, ALL_CHANNELS)
            payment = await self._make_payment(session)
            captured: dict[str, object] = {}

            def capture(values, **kwargs):
                captured.update(kwargs)
                return MagicMock(sent=False)

            with patch(
                "karpy_platform.plugins.payment.services.notifications.channels.mailer"
            ) as mail, patch.object(LogSmsProvider, "send", new=AsyncMock()) as sms:
                mail.send = MagicMock(side_effect=capture)
                await dispatch_payment_event(session, EVENT_RECEIVED, payment)
                await session.commit()

            # Short text (in-app + SMS) names amount, customer and reference.
            sms_message = sms.await_args.args[1]
            self.assertIn("150.00 USD", sms_message)
            self.assertIn("Ada Customer", sms_message)
            # Email subject and HTML body are the fuller rendering.
            self.assertIn("Payment received", captured["subject"])
            self.assertIn("<li>", captured["html"])
            self.assertIn("150.00 USD", captured["html"])

            row = (await session.execute(select(PaymentNotification))).scalars().one()
            self.assertEqual(row.title, "Payment received")
            self.assertIn("Ada Customer", row.body)
            self.assertEqual(row.currency, "USD")
            self.assertIsNone(row.read_at)

    async def test_disabled_channels_are_skipped(self) -> None:
        async with self.session() as session:
            await self._seed_settings(
                session,
                {
                    "payment.notifications.enabled": "1",
                    "payment.notifications.channels.in_app": "1",
                    "payment.notifications.channels.email": "0",
                    "payment.notifications.channels.sms": "0",
                    "admin_email": "ops@example.test",
                },
            )
            payment = await self._make_payment(session)
            with patch(
                "karpy_platform.plugins.payment.services.notifications.channels.mailer"
            ) as mail, patch.object(LogSmsProvider, "send", new=AsyncMock()) as sms:
                mail.send = MagicMock()
                summary = await dispatch_payment_event(session, EVENT_RECEIVED, payment)
                await session.commit()

            self.assertEqual(set(summary["channels"]), {"in_app"})
            mail.send.assert_not_called()
            sms.assert_not_awaited()
            count = await session.scalar(select(func.count()).select_from(PaymentNotification))
            self.assertEqual(int(count or 0), 1)

    async def test_master_switch_off_suppresses_everything(self) -> None:
        async with self.session() as session:
            await self._seed_settings(
                session, {**ALL_CHANNELS, "payment.notifications.enabled": "0"}
            )
            payment = await self._make_payment(session)
            with patch(
                "karpy_platform.plugins.payment.services.notifications.channels.mailer"
            ) as mail:
                mail.send = MagicMock()
                summary = await dispatch_payment_event(session, EVENT_RECEIVED, payment)
                await session.commit()

            self.assertFalse(summary["dispatched"])
            mail.send.assert_not_called()
            count = await session.scalar(select(func.count()).select_from(PaymentNotification))
            self.assertEqual(int(count or 0), 0)

    async def test_order_created_fires_from_create_payment(self) -> None:
        async with self.session() as session:
            await self._seed_settings(
                session,
                {
                    "payment.notifications.enabled": "1",
                    "payment.notifications.channels.in_app": "1",
                    "payment.notifications.channels.email": "0",
                    "payment.notifications.channels.sms": "0",
                },
            )
            payment = await create_payment(
                session,
                charge_id="CHG-ORDER",
                amount=Decimal("42.00"),
                currency="EUR",
                payment_channel="card",
            )
            self.assertIsNotNone(payment.id)
            rows = (
                await session.execute(
                    select(PaymentNotification).where(
                        PaymentNotification.event == EVENT_ORDER_CREATED
                    )
                )
            ).scalars().all()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].payment_id, payment.id)
            self.assertEqual(rows[0].reference, "CHG-ORDER")

    async def test_in_app_list_unread_and_mark_read_api(self) -> None:
        async with self.session() as session:
            await self._seed_settings(
                session,
                {
                    "payment.notifications.enabled": "1",
                    "payment.notifications.channels.in_app": "1",
                    "payment.notifications.channels.email": "0",
                    "payment.notifications.channels.sms": "0",
                },
            )
            payment = await self._make_payment(session)
            await dispatch_payment_event(session, EVENT_RECEIVED, payment)
            await dispatch_payment_event(session, EVENT_FAILED, payment)
            await session.commit()

            listing = await list_notifications(unread_only=False, page=1, per_page=15, db=session)
            self.assertEqual(listing["meta"]["total"], 2)
            self.assertEqual(listing["unread"], 2)

            counts = await notifications_unread_count(db=session)
            self.assertEqual(counts["unread"], 2)

            target = listing["data"][0]["id"]
            marked = await mark_notification_read(target, db=session)
            self.assertIsNotNone(marked["notification"]["readAt"])
            self.assertEqual(marked["unread"], 1)

            unread_only = await list_notifications(unread_only=True, page=1, per_page=15, db=session)
            self.assertEqual(unread_only["meta"]["total"], 1)

            cleared = await mark_all_notifications_read(db=session)
            self.assertEqual(cleared["unread"], 0)


if __name__ == "__main__":
    unittest.main()
