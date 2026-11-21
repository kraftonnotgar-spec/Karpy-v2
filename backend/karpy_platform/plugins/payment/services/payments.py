"""Payment service helpers used by checkout/gateway plugins."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from karpy_platform.plugins.payment.models.payment import Payment, PaymentLog


def decimal_to_float(value: Any) -> float:
    if value is None:
        return 0.0
    if isinstance(value, Decimal):
        return float(value)
    return float(value)


def serialize_payment(payment: Payment, include_logs: bool = False) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": payment.id,
        "chargeId": payment.charge_id,
        "amount": decimal_to_float(payment.amount),
        "paymentFee": decimal_to_float(payment.payment_fee),
        "currency": payment.currency,
        "userId": payment.user_id,
        "paymentChannel": payment.payment_channel,
        "description": payment.description,
        "status": payment.status,
        "orderId": payment.order_id,
        "paymentType": payment.payment_type,
        "customerId": payment.customer_id,
        "customerType": payment.customer_type,
        "payerName": payment.payer_name,
        "payerEmail": payment.payer_email,
        "refundedAmount": decimal_to_float(payment.refunded_amount),
        "refundNote": payment.refund_note,
        "metadata": payment.payment_metadata or {},
        "viewedAt": payment.viewed_at.isoformat() if payment.viewed_at else None,
        "createdAt": payment.created_at.isoformat() if payment.created_at else None,
        "updatedAt": payment.updated_at.isoformat() if payment.updated_at else None,
    }
    if include_logs:
        payload["logs"] = [serialize_log(log) for log in sorted(payment.logs, key=lambda item: item.created_at or datetime.min, reverse=True)]
    return payload


def serialize_log(log: PaymentLog) -> dict[str, Any]:
    return {
        "id": log.id,
        "paymentMethod": log.payment_method,
        "request": log.request,
        "response": log.response,
        "ipAddress": log.ip_address,
        "paymentId": log.payment_id,
        "chargeId": log.charge_id,
        "event": log.event,
        "status": log.status,
        "viewedAt": log.viewed_at.isoformat() if log.viewed_at else None,
        "createdAt": log.created_at.isoformat() if log.created_at else None,
        "updatedAt": log.updated_at.isoformat() if log.updated_at else None,
    }


async def find_payment_for_log(db: AsyncSession, payment_id: str | None = None, charge_id: str | None = None) -> Payment | None:
    if payment_id:
        payment = await db.get(Payment, payment_id)
        if payment and not payment.is_deleted:
            return payment
    if charge_id:
        result = await db.execute(
            select(Payment).where(
                Payment.is_deleted.is_(False),
                or_(Payment.charge_id == charge_id, Payment.order_id == charge_id),
            )
        )
        return result.scalars().first()
    return None


async def create_payment(
    db: AsyncSession,
    *,
    charge_id: str | None,
    amount: Decimal | float | int | str,
    currency: str = "USD",
    payment_channel: str,
    status: str = "pending",
    payer_name: str | None = None,
    payer_email: str | None = None,
    description: str | None = None,
    order_id: str | None = None,
    payment_type: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> Payment:
    payment = Payment(
        charge_id=charge_id,
        amount=Decimal(str(amount or 0)),
        currency=currency,
        payment_channel=payment_channel,
        status=status,
        payer_name=payer_name,
        payer_email=payer_email,
        description=description,
        order_id=order_id,
        payment_type=payment_type,
        payment_metadata=metadata or {},
    )
    db.add(payment)
    # Flush so the new record has an id before the "order created" notification is built;
    # the in-app row is then committed atomically with the payment below.
    await db.flush()
    from karpy_platform.plugins.payment.services.notifications import (
        EVENT_ORDER_CREATED,
        dispatch_payment_event,
    )

    await dispatch_payment_event(db, EVENT_ORDER_CREATED, payment)
    await db.commit()
    await db.refresh(payment)
    return payment


async def log_payment_event(
    db: AsyncSession,
    *,
    payment_method: str,
    request: dict[str, Any] | list[Any] | str | None = None,
    response: dict[str, Any] | list[Any] | str | None = None,
    ip_address: str | None = None,
    payment_id: str | None = None,
    charge_id: str | None = None,
    event: str | None = None,
    status: str | None = None,
) -> PaymentLog:
    payment = await find_payment_for_log(db, payment_id=payment_id, charge_id=charge_id)
    log = PaymentLog(
        payment_method=payment_method,
        request=request,
        response=response,
        ip_address=ip_address,
        payment_id=payment.id if payment else payment_id,
        charge_id=charge_id or (payment.charge_id if payment else None),
        event=event,
        status=status,
    )
    db.add(log)
    await db.commit()
    await db.refresh(log)
    return log
