from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from karpy_platform.core.setting.store import setting_store


def normalize_admin_emails(value: Any) -> list[str]:
    if isinstance(value, str):
        candidates = [value]
    elif isinstance(value, list):
        candidates = value
    else:
        candidates = []

    emails: list[str] = []
    for candidate in candidates:
        email = str(candidate or "").strip()
        if email and email not in emails:
            emails.append(email)
    return emails


async def get_admin_emails(db: AsyncSession) -> list[str]:
    """Botble-style central recipient list for admin notifications."""
    values = await setting_store.all(db, flat=True)
    emails = normalize_admin_emails(values.get("admin_email"))
    if emails:
        return emails
    fallback = str(values.get("email_from_address") or "admin@company.com").strip()
    return [fallback] if fallback else []
