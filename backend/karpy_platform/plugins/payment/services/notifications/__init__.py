"""Admin notifications for payment lifecycle events.

Three events (payment received, payment failed, new order/checkout created) are
fanned out to three channels (in-app, email, SMS). Everything is provider-neutral
and driven by the setting store, so a project built on KARPy enables the channels
it wants without code changes.
"""

from __future__ import annotations

from .dispatcher import dispatch_payment_event
from .events import (
    EVENT_FAILED,
    EVENT_ORDER_CREATED,
    EVENT_RECEIVED,
    PAYMENT_EVENTS,
    build_context,
)

__all__ = [
    "dispatch_payment_event",
    "EVENT_RECEIVED",
    "EVENT_FAILED",
    "EVENT_ORDER_CREATED",
    "PAYMENT_EVENTS",
    "build_context",
]
