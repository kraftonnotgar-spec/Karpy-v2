"""Fan a payment event out to every enabled notification channel.

Best-effort and non-blocking for the payment flow: this never raises and never
commits the caller's session. It reads channel/event enablement from the setting
store, so operators turn channels on and off without a deploy.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from karpy_platform.core.setting.store import setting_store

from . import channels
from .events import (
    PAYMENT_EVENTS,
    build_context,
    channel_enabled,
    event_enabled,
    notifications_enabled,
)

logger = logging.getLogger("karpy.plugins.payment.notifications")

_CHANNEL_DELIVERY = {
    "in_app": channels.deliver_in_app,
    "email": channels.deliver_email,
    "sms": channels.deliver_sms,
}


async def dispatch_payment_event(db: AsyncSession, event: str, payment: Any) -> dict[str, Any]:
    """Dispatch ``event`` for ``payment`` across the enabled channels.

    Returns a small summary (useful for tests/logging). Any failure is logged and
    swallowed; the caller's payment transaction is never affected.
    """
    summary: dict[str, Any] = {"event": event, "dispatched": False, "channels": {}}
    try:
        # Only act on real, persisted payments and known events. Unit tests that call
        # the payment services with lightweight stubs (no id) are intentionally skipped.
        if event not in PAYMENT_EVENTS or not getattr(payment, "id", None):
            return summary

        values = await setting_store.all(db, flat=True, force=True)
        if not notifications_enabled(values) or not event_enabled(values, event):
            return summary

        active = [name for name in _CHANNEL_DELIVERY if channel_enabled(values, name)]
        if not active:
            return summary

        context = build_context(event, payment)
        for name in active:
            try:
                summary["channels"][name] = await _CHANNEL_DELIVERY[name](db, event, context, values)
            except Exception:  # noqa: BLE001 - a channel failure never breaks the payment
                logger.exception("payment notification channel '%s' failed", name)
                summary["channels"][name] = None
        summary["dispatched"] = True
    except Exception:  # noqa: BLE001 - notifications must never break a payment
        logger.exception("payment notification dispatch failed for event '%s'", event)
    return summary
