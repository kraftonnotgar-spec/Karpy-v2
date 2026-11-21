"""In-app admin notification records for payment lifecycle events.

Provider-neutral: a row describes a payment event (received, failed, or a new
order/checkout) in terms the admin feed can render, without any product-specific
shape. Delivery to email/SMS is handled by the notification dispatcher; this table
is only the in-app channel's durable store.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import DateTime, Index, JSON, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from karpy_platform.core.base.models import BaseModel


class PaymentNotification(BaseModel):
    """An admin-facing notification raised by a payment event."""

    __tablename__ = "payment_notifications"
    __table_args__ = (
        Index("idx_payment_notifications_read_created", "read_at", "created_at"),
        Index("idx_payment_notifications_event_created", "event", "created_at"),
    )

    # One of the event keys in services/notifications/events.py (received/failed/order_created).
    event: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    payment_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    reference: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(12), nullable=True)
    status: Mapped[str | None] = mapped_column(String(40), nullable=True)
    customer_label: Mapped[str | None] = mapped_column(String(190), nullable=True)
    data: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True, default=dict)
    read_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    def mark_as_read(self) -> None:
        if not self.read_at:
            self.read_at = datetime.utcnow()
