"""Event keys, config readers, and context building for payment notifications."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

# Neutral event keys. These are not provider or product specific.
EVENT_RECEIVED = "received"
EVENT_FAILED = "failed"
EVENT_ORDER_CREATED = "order_created"

PAYMENT_EVENTS = (EVENT_RECEIVED, EVENT_FAILED, EVENT_ORDER_CREATED)

EVENT_LABELS = {
    EVENT_RECEIVED: "Payment received",
    EVENT_FAILED: "Payment failed",
    EVENT_ORDER_CREATED: "New order",
}

CHANNELS = ("in_app", "email", "sms")

# Default channel/event enablement. In-app is on; email and SMS stay off until an
# operator configures delivery (SMTP, an SMS provider and recipients), so a fresh
# install never attempts network delivery it was not set up for.
_DEFAULT_CHANNEL_ENABLED = {"in_app": True, "email": False, "sms": False}
_DEFAULT_EVENT_ENABLED = {event: True for event in PAYMENT_EVENTS}


def _truthy(value: Any, default: bool) -> bool:
    if value is None or value == "":
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on", "enabled"}


def notifications_enabled(values: dict[str, Any]) -> bool:
    return _truthy(values.get("payment.notifications.enabled"), True)


def channel_enabled(values: dict[str, Any], channel: str) -> bool:
    return _truthy(
        values.get(f"payment.notifications.channels.{channel}"),
        _DEFAULT_CHANNEL_ENABLED.get(channel, False),
    )


def event_enabled(values: dict[str, Any], event: str) -> bool:
    return _truthy(
        values.get(f"payment.notifications.events.{event}"),
        _DEFAULT_EVENT_ENABLED.get(event, True),
    )


def enabled_channels(values: dict[str, Any]) -> list[str]:
    return [channel for channel in CHANNELS if channel_enabled(values, channel)]


@dataclass(slots=True)
class NotificationContext:
    """Rendered-ready variables for one payment event, used by every channel."""

    event: str
    event_label: str
    payment_id: str | None
    reference: str | None
    amount: Decimal | None
    amount_display: str
    currency: str | None
    status: str | None
    customer_label: str
    occurred_at: datetime
    occurred_at_display: str
    variables: dict[str, Any] = field(default_factory=dict)


def _amount_display(amount: Decimal | None, currency: str | None) -> str:
    if amount is None:
        return ""
    formatted = f"{amount:,.2f}" if isinstance(amount, Decimal) else str(amount)
    return f"{formatted} {currency}".strip() if currency else formatted


def _customer_label(payment: Any) -> str:
    for attribute in ("payer_name", "payer_email"):
        value = getattr(payment, attribute, None)
        if value:
            return str(value)
    user_id = getattr(payment, "user_id", None)
    if user_id:
        return f"account {user_id}"
    return "a customer"


def build_context(event: str, payment: Any) -> NotificationContext:
    """Turn a payment record into neutral template variables for an event."""
    amount = getattr(payment, "amount", None)
    if amount is not None and not isinstance(amount, Decimal):
        try:
            amount = Decimal(str(amount))
        except (ArithmeticError, ValueError, TypeError):
            amount = None
    currency = getattr(payment, "currency", None)
    reference = (
        getattr(payment, "charge_id", None)
        or getattr(payment, "order_id", None)
        or getattr(payment, "id", None)
    )
    status = getattr(payment, "status", None)
    occurred_at = datetime.now(timezone.utc)
    amount_display = _amount_display(amount, currency)
    customer_label = _customer_label(payment)
    occurred_display = occurred_at.strftime("%Y-%m-%d %H:%M UTC")
    variables = {
        "event": event,
        "event_label": EVENT_LABELS.get(event, event),
        "amount": amount_display,
        "currency": currency or "",
        "reference": reference or "",
        "customer": customer_label,
        "status": status or "",
        "timestamp": occurred_display,
    }
    return NotificationContext(
        event=event,
        event_label=EVENT_LABELS.get(event, event),
        payment_id=getattr(payment, "id", None),
        reference=reference,
        amount=amount,
        amount_display=amount_display,
        currency=currency,
        status=status,
        customer_label=customer_label,
        occurred_at=occurred_at,
        occurred_at_display=occurred_display,
        variables=variables,
    )
