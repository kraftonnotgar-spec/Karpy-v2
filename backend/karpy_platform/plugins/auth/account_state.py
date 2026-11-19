from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from karpy_platform.core.acl.models import User, UserMeta, utcnow

ACCOUNT_STATUS_KEY = "auth.account_status"
ACCOUNT_STATUSES = {"active", "deactivated", "banned"}


def account_status(user: User) -> str:
    for item in user.meta or []:
        if item.key == ACCOUNT_STATUS_KEY and item.value in ACCOUNT_STATUSES:
            return item.value
    return "active"


def account_status_message(value: str) -> str:
    if value == "banned":
        return "Your account has been banned. Contact support if you believe this is a mistake."
    return "Your account has been deactivated. Contact support to restore access."


def account_status_code(value: str) -> str:
    """Machine code for a closed account: ``account_banned`` or ``account_deactivated``."""
    return "account_banned" if value == "banned" else "account_deactivated"


def account_status_reason(user: User | None) -> str:
    """The reason Platform Admin gave in Access ("Shown to the merchant"), or "".

    Only for a closed account (deactivated or banned through the access control, which
    clears ``account.restriction``); a stale restriction reason is never shown.
    """
    if user is None or account_status(user) == "active":
        return ""
    values = {item.key: item.value for item in user.meta or []}
    if values.get("account.restriction"):
        return ""
    return " ".join(str(values.get("account.restriction_reason") or "").split())[:500]


def account_status_body(user: User | None, value: str) -> dict:
    """Mobile refusal for a closed account: the web message plus a code and the admin's reason."""
    return {"detail": account_status_message(value), "code": account_status_code(value),
            "reason": account_status_reason(user) or None}


async def revoke_user_sessions(db: AsyncSession, user_id: str) -> int:
    """End every web and app session of ``user_id`` now. The caller commits."""
    from .models import AuthSession
    result = await db.execute(update(AuthSession).where(
        AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None)).values(revoked_at=utcnow()))
    return int(result.rowcount or 0)


async def set_account_status(db: AsyncSession, user: User, value: str) -> str:
    if value not in ACCOUNT_STATUSES:
        raise ValueError("Invalid account status.")
    item = await db.scalar(
        select(UserMeta).where(UserMeta.user_id == user.id, UserMeta.key == ACCOUNT_STATUS_KEY)
    )
    if item:
        item.value = value
    else:
        item = UserMeta(user_id=user.id, key=ACCOUNT_STATUS_KEY, value=value)
        db.add(item)
    return value
