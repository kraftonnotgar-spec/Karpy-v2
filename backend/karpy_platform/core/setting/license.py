from __future__ import annotations

import json
import os
import asyncio
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from karpy_platform.core.setting.store import setting_store


ENVATO_AUTHOR_SALE_URL = "https://api.envato.com/v3/market/author/sale"


class LicenseActivationError(RuntimeError):
    pass


@dataclass
class LicenseActivationPayload:
    envato_username: str
    purchase_code: str
    confirm: bool


def _envato_token() -> str:
    return (
        os.getenv("ENVATO_API_TOKEN")
        or os.getenv("ENVATO_PERSONAL_TOKEN")
        or settings.ENVATO_API_TOKEN
        or settings.ENVATO_PERSONAL_TOKEN
        or ""
    ).strip()


def _mask_code(code: str) -> str:
    if not code:
        return ""
    if len(code) <= 10:
        return "*" * len(code)
    return f"{code[:4]}...{code[-4:]}"


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _buyer_from_sale(data: dict[str, Any]) -> str:
    buyer = data.get("buyer") or data.get("buyer_username") or data.get("username") or ""
    if isinstance(buyer, dict):
        buyer = buyer.get("username") or buyer.get("name") or ""
    return str(buyer).strip()


def _item_from_sale(data: dict[str, Any]) -> dict[str, Any]:
    item = data.get("item") if isinstance(data.get("item"), dict) else {}
    return {
        "id": str(item.get("id") or data.get("item_id") or ""),
        "name": str(item.get("name") or data.get("item_name") or ""),
    }


async def license_status(db: AsyncSession) -> dict[str, Any]:
    values = await setting_store.all(db, flat=True)
    purchase_code = str(values.get("license_purchase_code") or "")
    activated = bool(values.get("licensed_to")) and values.get("license_status") == "active"
    return {
        "activated": activated,
        "status": "active" if activated else "invalid",
        "licensedTo": values.get("licensed_to") or "",
        "activatedAt": values.get("license_activated_at") or "",
        "checkedAt": values.get("license_checked_at") or "",
        "source": values.get("license_source") or "envato",
        "envatoUsername": values.get("license_envato_username") or "",
        "purchaseCodeMasked": _mask_code(purchase_code),
        "itemId": values.get("license_envato_item_id") or "",
        "itemName": values.get("license_envato_item_name") or "",
        "envatoConfigured": bool(_envato_token()),
    }


async def activate_license(db: AsyncSession, payload: LicenseActivationPayload) -> dict[str, Any]:
    username = payload.envato_username.strip().strip("/")
    purchase_code = payload.purchase_code.strip()

    if username.startswith(("http://", "https://")):
        username = username.rsplit("/", 1)[-1]
        raise LicenseActivationError(f'Envato username must not be a URL. Please try with username "{username}".')
    if not payload.confirm:
        raise LicenseActivationError("Please confirm the Envato license terms before activating.")

    token = _envato_token()
    if not token:
        raise LicenseActivationError("Envato API token is not configured on the server. Set ENVATO_API_TOKEN in .env.")

    sale = await _lookup_envato_sale(token, purchase_code)
    buyer = _buyer_from_sale(sale)
    if buyer and buyer.lower() != username.lower():
        raise LicenseActivationError("Purchase code does not belong to that Envato username.")

    item = _item_from_sale(sale)
    expected_item_id = str(settings.ENVATO_ITEM_ID or "").strip()
    if expected_item_id and item["id"] and item["id"] != expected_item_id:
        raise LicenseActivationError("Purchase code is valid, but it is not for this KARPy CMS item.")

    now = _utc_now()
    await setting_store.force_set(
        db,
        {
            "licensed_to": buyer or username,
            "license_envato_username": username,
            "license_purchase_code": purchase_code,
            "license_status": "active",
            "license_source": "envato",
            "license_activated_at": now,
            "license_checked_at": now,
            "license_envato_item_id": item["id"],
            "license_envato_item_name": item["name"],
        },
    )
    await setting_store.save(db)
    return await license_status(db)


async def deactivate_license(db: AsyncSession) -> dict[str, Any]:
    await setting_store.force_set(
        db,
        {
            "licensed_to": "",
            "license_envato_username": "",
            "license_purchase_code": "",
            "license_status": "",
            "license_source": "envato",
            "license_activated_at": "",
            "license_checked_at": _utc_now(),
            "license_envato_item_id": "",
            "license_envato_item_name": "",
        },
    )
    await setting_store.save(db)
    return await license_status(db)


async def _lookup_envato_sale(token: str, purchase_code: str) -> dict[str, Any]:
    return await asyncio.to_thread(_lookup_envato_sale_sync, token, purchase_code)


def _lookup_envato_sale_sync(token: str, purchase_code: str) -> dict[str, Any]:
    query = urllib.parse.urlencode({"code": purchase_code})
    request = urllib.request.Request(
        f"{ENVATO_AUTHOR_SALE_URL}?{query}",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "User-Agent": "KARPy CMS license verification",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=12) as response:
            payload = response.read().decode("utf-8")
    except urllib.error.HTTPError as exception:
        detail = exception.read().decode("utf-8", errors="ignore")
        if exception.code == 404:
            raise LicenseActivationError("Purchase code was not found in your Envato author sales.") from exception
        raise LicenseActivationError(f"Envato license check failed with HTTP {exception.code}: {detail or exception.reason}") from exception
    except urllib.error.URLError as exception:
        raise LicenseActivationError(f"Could not connect to Envato: {exception.reason}") from exception

    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exception:
        raise LicenseActivationError("Envato returned an invalid response.") from exception
    if not isinstance(data, dict) or not data:
        raise LicenseActivationError("Envato returned no sale data for this purchase code.")
    return data
