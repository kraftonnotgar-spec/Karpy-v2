"""API routes for the Payment plugin."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.config import settings as app_settings
from karpy_platform.core.acl.routes import current_admin_user
from karpy_platform.core.setting.store import setting_store
from karpy_platform.plugins.payment.models.payment import Payment, PaymentLog
from karpy_platform.plugins.payment.services.methods import payment_methods, method_settings
from karpy_platform.plugins.payment.services.checkout import complete_payment
from karpy_platform.plugins.payment.services.configuration import merge_secure_settings, public_settings
from karpy_platform.plugins.payment.services.payments import (
    log_payment_event,
    serialize_log,
    serialize_payment,
)


async def require_admin(request: Request, db: AsyncSession = Depends(get_db)):
    # A real admin session is required (this used to return the bootstrap admin for any caller).
    from karpy_platform.core.acl.admin_guard import require_admin_session

    return await require_admin_session(request, db)


async def require_gateway_admin(request: Request, db: AsyncSession = Depends(get_db)):
    user = await current_admin_user(request, db)
    if not user.super_user:
        raise HTTPException(status_code=403, detail="permission_denied")
    if request.method not in {"GET", "HEAD"}:
        allowed = set()
        for value in (app_settings.APP_URL, app_settings.USER_DASHBOARD_URL, app_settings.ADMIN_DASHBOARD_URL, *app_settings.user_dashboard_aliases):
            origin = urlsplit(value)
            schemes = {"https"} if app_settings.is_production else {"https", "http"}
            if origin.scheme in schemes and origin.netloc and not origin.username and not origin.password:
                allowed.add(f"{origin.scheme}://{origin.netloc}")
        if request.headers.get("origin", "") not in allowed or request.headers.get("sec-fetch-site") == "cross-site":
            raise HTTPException(status_code=403, detail="csrf_denied")
    return user


router = APIRouter(dependencies=[Depends(require_admin)])

PAYMENT_STATUSES = {"pending", "completed", "canceled", "cancelled", "failed", "refunded", "processing"}


class PaymentCreatePayload(BaseModel):
    chargeId: str | None = None
    amount: Decimal = Decimal("0")
    currency: str = "USD"
    paymentChannel: str = Field(min_length=1)
    status: str = "pending"
    payerName: str | None = None
    payerEmail: str | None = None
    description: str | None = None
    orderId: str | None = None
    paymentType: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class PaymentUpdatePayload(BaseModel):
    status: str | None = None
    metadata: dict[str, Any] | None = None


class PaymentLogPayload(BaseModel):
    paymentMethod: str = Field(min_length=1)
    request: dict[str, Any] | list[Any] | str | None = None
    response: dict[str, Any] | list[Any] | str | None = None
    paymentId: str | None = None
    chargeId: str | None = None
    event: str | None = None
    status: str | None = None


class MethodSettingsPayload(BaseModel):
    defaultMethod: str | None = None


class MethodUpdatePayload(BaseModel):
    enabled: bool | None = None
    settings: dict[str, Any] = Field(default_factory=dict)


def _payment_filters(q: str | None = None, status: str | None = None):
    filters = [Payment.is_deleted.is_(False)]
    if q:
        like = f"%{q.strip()}%"
        filters.append(
            or_(
                Payment.charge_id.ilike(like),
                Payment.payer_name.ilike(like),
                Payment.payer_email.ilike(like),
                Payment.payment_channel.ilike(like),
            )
        )
    if status:
        filters.append(Payment.status == status)
    return filters


def _log_filters(q: str | None = None, method: str | None = None):
    filters = [PaymentLog.is_deleted.is_(False)]
    if q:
        like = f"%{q.strip()}%"
        filters.append(
            or_(
                PaymentLog.payment_method.ilike(like),
                PaymentLog.ip_address.ilike(like),
                PaymentLog.charge_id.ilike(like),
                PaymentLog.event.ilike(like),
                PaymentLog.status.ilike(like),
            )
        )
    if method:
        filters.append(PaymentLog.payment_method == method)
    return filters


async def _count(db: AsyncSession, model, filters: list[Any]) -> int:
    result = await db.execute(select(func.count()).select_from(model).where(*filters))
    return int(result.scalar() or 0)


@router.get("/")
async def index(db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    active_settings = await setting_store.all(db, flat=True)
    methods = []
    for method in payment_methods.all():
        item = method.to_dict(active_settings)
        item["settings"] = public_settings(method.key, item.get("settings"))
        methods.append(item)
    pending_filters = _payment_filters(status="pending")
    unread_filters = [Payment.is_deleted.is_(False), Payment.viewed_at.is_(None)]
    return {
        "plugin": "payment",
        "name": "Payment",
        "status": "ready",
        "counts": {
            "transactions": await _count(db, Payment, _payment_filters()),
            "pending": await _count(db, Payment, pending_filters),
            "unread": await _count(db, Payment, unread_filters),
            "logs": await _count(db, PaymentLog, _log_filters()),
            "methods": len(methods),
        },
        "methods": methods,
    }


@router.get("/transactions")
async def transactions(
    q: str | None = None,
    status: str | None = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(15, ge=1, le=100, alias="perPage"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    filters = _payment_filters(q=q, status=status if status and status != "all" else None)
    total = await _count(db, Payment, filters)
    result = await db.execute(
        select(Payment)
        .where(*filters)
        .order_by(Payment.created_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
    )
    return {
        "data": [serialize_payment(payment) for payment in result.scalars().all()],
        "meta": {"page": page, "perPage": per_page, "total": total},
    }


@router.post("/transactions")
async def create_transaction(payload: PaymentCreatePayload, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    status = payload.status.strip().lower()
    if status not in PAYMENT_STATUSES:
        raise HTTPException(status_code=422, detail={"status": "Unsupported payment status."})
    payment = Payment(
        charge_id=payload.chargeId,
        amount=payload.amount,
        currency=payload.currency.upper(),
        payment_channel=payload.paymentChannel.strip(),
        status=status,
        payer_name=payload.payerName,
        payer_email=payload.payerEmail,
        description=payload.description,
        order_id=payload.orderId,
        payment_type=payload.paymentType,
        payment_metadata=payload.metadata,
    )
    db.add(payment)
    await db.commit()
    await db.refresh(payment)
    return {"payment": serialize_payment(payment)}


@router.get("/transactions/{payment_id}")
async def transaction_detail(payment_id: str, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    payment = await db.get(Payment, payment_id)
    if not payment or payment.is_deleted:
        raise HTTPException(status_code=404, detail="Payment transaction not found.")
    if not payment.viewed_at:
        payment.viewed_at = datetime.utcnow()
        await db.commit()
        await db.refresh(payment)
    return {"payment": serialize_payment(payment, include_logs=True)}


@router.patch("/transactions/{payment_id}")
async def update_transaction(payment_id: str, payload: PaymentUpdatePayload, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    payment = await db.get(Payment, payment_id)
    if not payment or payment.is_deleted:
        raise HTTPException(status_code=404, detail="Payment transaction not found.")
    if payload.status is not None:
        status = payload.status.strip().lower()
        if status not in PAYMENT_STATUSES:
            raise HTTPException(status_code=422, detail={"status": "Unsupported payment status."})
        if status != payment.status:
            await complete_payment(db, payment, status)
    if payload.metadata is not None:
        payment.payment_metadata = payload.metadata
    await db.commit()
    await db.refresh(payment)
    return {"payment": serialize_payment(payment, include_logs=True)}


@router.delete("/transactions/{payment_id}")
async def delete_transaction(payment_id: str, db: AsyncSession = Depends(get_db)) -> dict[str, str]:
    payment = await db.get(Payment, payment_id)
    if not payment or payment.is_deleted:
        raise HTTPException(status_code=404, detail="Payment transaction not found.")
    payment.is_deleted = True
    await db.commit()
    return {"message": "Payment transaction deleted."}


@router.get("/logs")
async def logs(
    q: str | None = None,
    method: str | None = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(15, ge=1, le=100, alias="perPage"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    filters = _log_filters(q=q, method=method if method and method != "all" else None)
    total = await _count(db, PaymentLog, filters)
    result = await db.execute(
        select(PaymentLog)
        .where(*filters)
        .order_by(PaymentLog.created_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
    )
    return {
        "data": [serialize_log(log) for log in result.scalars().all()],
        "meta": {"page": page, "perPage": per_page, "total": total},
    }


@router.post("/logs")
async def create_log(payload: PaymentLogPayload, request: Request, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    log = await log_payment_event(
        db,
        payment_method=payload.paymentMethod.strip(),
        request=payload.request,
        response=payload.response,
        ip_address=request.client.host if request.client else None,
        payment_id=payload.paymentId,
        charge_id=payload.chargeId,
        event=payload.event,
        status=payload.status,
    )
    return {"log": serialize_log(log)}


@router.get("/logs/{log_id}")
async def log_detail(log_id: str, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    log = await db.get(PaymentLog, log_id)
    if not log or log.is_deleted:
        raise HTTPException(status_code=404, detail="Payment log not found.")
    if not log.viewed_at:
        log.viewed_at = datetime.utcnow()
        await db.commit()
        await db.refresh(log)
    return {"log": serialize_log(log)}


@router.delete("/logs/{log_id}")
async def delete_log(log_id: str, db: AsyncSession = Depends(get_db)) -> dict[str, str]:
    log = await db.get(PaymentLog, log_id)
    if not log or log.is_deleted:
        raise HTTPException(status_code=404, detail="Payment log not found.")
    log.is_deleted = True
    await db.commit()
    return {"message": "Payment log deleted."}


@router.get("/methods", dependencies=[Depends(require_gateway_admin)])
async def methods(db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    settings = await setting_store.all(db, flat=True, force=True)
    registered = []
    for method in payment_methods.all():
        item = method.to_dict(settings)
        item["settings"] = public_settings(method.key, item.get("settings"))
        item["webhookUrl"] = f"{app_settings.APP_URL.rstrip('/')}{method.webhook_path}" if method.webhook_path else ""
        registered.append(item)
    default_method = settings.get("payment.default_method") or (registered[0]["key"] if registered else "")
    return {
        "defaultMethod": default_method,
        "methods": registered,
        "emptyMessage": "No payment gateway has registered a method yet. Activate a gateway plugin and it will appear here.",
    }


@router.put("/methods/settings", dependencies=[Depends(require_gateway_admin)])
async def save_method_settings(payload: MethodSettingsPayload, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    registered_keys = payment_methods.keys()
    default_method = payload.defaultMethod or ""
    if default_method and default_method not in registered_keys:
        raise HTTPException(status_code=422, detail={"defaultMethod": "Select a registered payment method."})
    await setting_store.set(db, "payment.default_method", default_method)
    await setting_store.save(db)
    return await methods(db)


@router.patch("/methods/{method_key}", dependencies=[Depends(require_gateway_admin)])
async def update_method(method_key: str, payload: MethodUpdatePayload, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    method = payment_methods.get(method_key)
    if not method:
        raise HTTPException(status_code=404, detail="Payment method is not registered.")
    updates: dict[str, Any] = {}
    if payload.enabled is not None:
        updates[f"payment.methods.{method.key}.enabled"] = payload.enabled
    all_settings = await setting_store.all(db, flat=True, force=True)
    current = method_settings(all_settings, method.key)
    updates[f"payment.methods.{method.key}.settings"] = merge_secure_settings(method.key, current, payload.settings)
    await setting_store.set(db, updates)
    await setting_store.save(db)
    return await methods(db)
