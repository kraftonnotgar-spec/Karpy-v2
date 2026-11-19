"""Payment models for the KARPy payment plugin.

The shape follows Botble's payment plugin: transactions live in ``payments`` and
gateway request/response traces live in ``payment_logs``.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, JSON, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from karpy_platform.core.base.models import BaseModel


class Payment(BaseModel):
    """A payment transaction recorded by a checkout or gateway plugin."""

    __tablename__ = "payments"
    __table_args__ = (
        Index("idx_payments_status_created", "status", "created_at"),
        Index("idx_payments_channel_created", "payment_channel", "created_at"),
        Index("idx_payments_charge_order", "charge_id", "order_id"),
    )

    charge_id: Mapped[str | None] = mapped_column(String(120), index=True, nullable=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0, nullable=False)
    payment_fee: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0, nullable=False)
    currency: Mapped[str] = mapped_column(String(12), default="USD", nullable=False)
    user_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    payment_channel: Mapped[str] = mapped_column(String(80), default="manual", nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="pending", nullable=False, index=True)
    order_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    payment_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    customer_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    customer_type: Mapped[str | None] = mapped_column(String(120), nullable=True)
    payer_name: Mapped[str | None] = mapped_column(String(190), nullable=True)
    payer_email: Mapped[str | None] = mapped_column(String(190), nullable=True)
    refunded_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0, nullable=False)
    refund_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    payment_metadata: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSON, nullable=True, default=dict)
    viewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    logs: Mapped[list["PaymentLog"]] = relationship(
        "PaymentLog",
        back_populates="payment",
        lazy="selectin",
    )


class PaymentLog(BaseModel):
    """A gateway/API request and response trace for a payment method."""

    __tablename__ = "payment_logs"
    __table_args__ = (
        Index("idx_payment_logs_method_created", "payment_method", "created_at"),
        Index("idx_payment_logs_charge_created", "charge_id", "created_at"),
    )

    payment_method: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    request: Mapped[dict[str, Any] | list[Any] | str | None] = mapped_column(JSON, nullable=True)
    response: Mapped[dict[str, Any] | list[Any] | str | None] = mapped_column(JSON, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(80), nullable=True)
    payment_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("payments.id"), nullable=True, index=True)
    charge_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    event: Mapped[str | None] = mapped_column(String(120), nullable=True)
    status: Mapped[str | None] = mapped_column(String(60), nullable=True)
    viewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    payment: Mapped[Payment | None] = relationship("Payment", back_populates="logs", lazy="selectin")
