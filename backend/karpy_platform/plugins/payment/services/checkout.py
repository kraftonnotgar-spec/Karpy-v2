"""Provider-neutral payment helpers and optional plugin-owned fulfilment."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

import phonenumbers
from fastapi import HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from karpy_platform.core.acl.models import User
from karpy_platform.core.setting.phone import (
    available_phone_countries,
    normalize_country_codes,
)
from karpy_platform.core.setting.store import setting_store
from karpy_platform.plugins.payment.models.payment import Payment
from karpy_platform.plugins.payment.services.configuration import decrypted_settings
from karpy_platform.plugins.payment.services.fulfilment import fulfilment_extensions
from karpy_platform.plugins.payment.services.methods import payment_methods, method_settings

FINAL_STATUSES = {"completed", "failed", "canceled", "cancelled", "refunded"}
KNOWN_STATUSES = FINAL_STATUSES | {"pending", "processing"}
# Provider events may only move a payment forward. A late or out-of-order
# "failed"/"pending" must never undo a completed (and fulfilled) payment.
PROVIDER_TRANSITIONS: dict[str, set[str]] = {
    "pending": {"processing", "completed", "failed", "canceled", "cancelled"},
    "processing": {"completed", "failed", "canceled", "cancelled"},
    # Money that arrives after an expiry or cancellation is still recorded.
    "failed": {"completed"},
    "canceled": {"completed"},
    "cancelled": {"completed"},
    "completed": {"refunded"},
    "refunded": set(),
}


def provider_transition_allowed(current: str | None, next_status: str) -> bool:
    if next_status not in KNOWN_STATUSES:
        return False
    return next_status in PROVIDER_TRANSITIONS.get((current or "pending").lower(), set())


@dataclass(slots=True)
class CheckoutContext:
    payment: Payment
    # Compatibility context for optional product plugins; never an imported model.
    plan: Any
    user: User
    settings: dict[str, Any]
    request: Request


def _bool(value: Any) -> bool:
    return value in {True, "1", "true", "True", "yes", "on"}


async def configured_methods(
    db: AsyncSession, *, public: bool = False, user: User | None = None
) -> list[dict[str, Any]]:
    flat = await setting_store.all(db, flat=True, force=True)
    result: list[dict[str, Any]] = []
    for method in payment_methods.all():
        enabled = flat.get(f"payment.methods.{method.key}.enabled")
        if not _bool(enabled):
            continue
        values = method_settings(flat, method.key)
        decrypted = decrypted_settings(method.key, values)
        if any(not decrypted.get(key) for key in method.required_credentials):
            continue
        if user and not payment_country_allowed(values, user.phone):
            continue
        item = {
            "key": method.key,
            "name": str(
                values.get("methodName") or values.get("providerName") or method.name
            ),
            "description": str(values.get("description") or method.description),
            "type": method.checkout_type,
            "logo": str(values.get("methodLogo") or method.logo or ""),
        }
        if public and method.checkout_type == "manual":
            item["instructions"] = str(
                values.get("instructions")
                or "Contact support after submitting your payment reference."
            )
            item["accountLabel"] = str(values.get("accountLabel") or "Payment account")
            item["accountValue"] = str(values.get("accountValue") or "")
            item["network"] = str(values.get("network") or "")
        result.append(item)
    return result


async def create_plan_checkout(
    db: AsyncSession, request: Request, user: User, plan_id: str, method_key: str
) -> dict[str, Any]:
    """Compatibility route; product lookup/checkout belongs to its extension."""
    extension = fulfilment_extensions.get("plan")
    if extension is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            {
                "code": "capability_unavailable",
                "message": "Product checkout is not available.",
            },
        )
    return await extension.checkout(db, request, user, plan_id, method_key)


def calculate_fee(amount: Decimal, settings: dict[str, Any]) -> Decimal:
    try:
        raw = Decimal(str(settings.get("processingFee") or 0))
    except (InvalidOperation, ValueError):
        raw = Decimal(0)
    if raw <= 0:
        return Decimal(0)
    fee = (
        amount * raw / 100 if settings.get("processingFeeType") == "percentage" else raw
    )
    return fee.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def payment_country_allowed(settings: dict[str, Any], phone: str | None) -> bool:
    """Match gateway country restrictions against the member's verified phone country."""
    raw = settings.get("countries")
    if raw in (None, "", "ALL", "all"):
        return True
    allowed = set(normalize_country_codes(raw))
    if not allowed:
        return True
    value = str(phone or "").strip()
    if not value:
        return False
    try:
        parsed = phonenumbers.parse(value, None)
        region = str(phonenumbers.region_code_for_number(parsed) or "").upper()
        return bool(region and region in allowed)
    except phonenumbers.NumberParseException:
        compact = "+" + "".join(character for character in value if character.isdigit())
        matches = sorted(
            available_phone_countries(),
            key=lambda country: len(country.dial_code),
            reverse=True,
        )
        region = next(
            (
                country.iso2
                for country in matches
                if compact.startswith(country.dial_code)
            ),
            "",
        )
        return bool(region and region in allowed)


async def complete_payment(
    db: AsyncSession,
    payment: Payment,
    status_value: str,
    *,
    event_id: str | None = None,
    provider_payload: dict[str, Any] | None = None,
    actor_id: str | None = None,
) -> Payment:
    next_status = (
        status_value.lower().replace("expired", "failed").replace("voided", "canceled")
    )
    if payment.status == next_status and (
        not event_id
        or (payment.payment_metadata or {}).get("lastProviderEvent") == event_id
    ):
        return payment
    if event_id and not provider_transition_allowed(payment.status, next_status):
        # Signed but stale or out of order: record nothing, keep the current state.
        return payment
    payment.status = next_status
    metadata = dict(payment.payment_metadata or {})
    if event_id:
        metadata["lastProviderEvent"] = event_id
    if provider_payload:
        metadata["providerStatus"] = {
            key: value
            for key, value in provider_payload.items()
            if key not in {"data", "object"}
        }
    payment.payment_metadata = metadata
    extension = fulfilment_extensions.get(payment.payment_type)
    if extension and next_status in {"completed", "canceled", "cancelled", "refunded"}:
        try:
            await extension.transition(
                db, payment, next_status, actor_id or payment.user_id
            )
        except Exception:  # noqa: BLE001 - third-party callback failures must rollback and redact
            await db.rollback()
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                {
                    "code": "fulfilment_unavailable",
                    "message": "Product fulfilment could not be completed.",
                },
            ) from None
        metadata["fulfilment"] = {"status": "applied"}
    elif payment.payment_type == "plan":
        # Do not confuse confirmed payment with a product entitlement. Legacy
        # product payments remain visible for recovery, without inventing one.
        metadata["fulfilment"] = {
            "status": "unavailable",
            "code": "capability_unavailable",
        }
    payment.payment_metadata = metadata
    await db.commit()
    await db.refresh(payment)
    return payment
