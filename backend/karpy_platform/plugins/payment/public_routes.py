"""Authenticated customer checkout and unauthenticated signed gateway webhooks."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from karpy_platform.core.acl.models import User
from karpy_platform.plugins.auth.security import current_user
from karpy_platform.plugins.payment.models.payment import Payment
from karpy_platform.plugins.payment.services.checkout import configured_methods, create_plan_checkout
from karpy_platform.plugins.payment.services.methods import webhook_handlers
from karpy_platform.plugins.payment.services.payments import serialize_payment

router = APIRouter()


class CheckoutPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    planId: str = Field(min_length=1, max_length=36)
    method: str = Field(min_length=1, max_length=40)


@router.get("/checkout/methods")
async def checkout_methods(db: AsyncSession = Depends(get_db), user: User = Depends(current_user)) -> dict[str, Any]:
    methods = await configured_methods(db, public=True, user=user)
    return {"methods": methods, "enabled": bool(methods)}


@router.post("/checkout/plans")
async def checkout_plan(payload: CheckoutPayload, request: Request, db: AsyncSession = Depends(get_db), user: User = Depends(current_user)) -> dict[str, Any]:
    return await create_plan_checkout(db, request, user, payload.planId, payload.method)


@router.get("/checkout/payments/{payment_id}")
async def checkout_status(payment_id: str, db: AsyncSession = Depends(get_db), user: User = Depends(current_user)) -> dict[str, Any]:
    payment = await db.get(Payment, payment_id)
    if not payment or payment.is_deleted or payment.user_id != user.id:
        raise HTTPException(404, "Payment not found.")
    return {"payment": serialize_payment(payment)}


@router.post("/webhooks/{method_key}")
async def gateway_webhook(method_key: str, request: Request, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """Dispatch to the signed webhook handler registered by an active gateway."""
    handler = webhook_handlers.get(method_key)
    if not handler:
        raise HTTPException(404, "Payment gateway is not active.")
    return await handler(request, db)
