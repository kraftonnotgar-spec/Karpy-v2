from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from karpy_platform.core.base.breadcrumbs import breadcrumb, page_title
from karpy_platform.core.base.dashboard_menu import dashboard_menu, register_core_admin_menu
from karpy_platform.core.base.models import AdminNotification
from karpy_platform.core.base.responses import BaseHttpResponse

router = APIRouter()
CONTACT_NOTIFICATION_ID = "contact-unread"


class NotificationCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=400)
    actionLabel: str | None = Field(default=None, max_length=120)
    actionUrl: str | None = Field(default=None, max_length=500)
    permission: str | None = Field(default=None, max_length=120)


def notification_payload(notification: AdminNotification) -> dict:
    return {
        "id": notification.id,
        "title": notification.title,
        "description": notification.description,
        "actionLabel": notification.action_label,
        "actionUrl": notification.action_url,
        "permission": notification.permission,
        "readAt": notification.read_at.isoformat() if notification.read_at else None,
        "createdAt": notification.created_at.isoformat() if notification.created_at else None,
    }


async def contact_notification_payload(db: AsyncSession) -> tuple[dict | None, int]:
    """Expose unread contact messages in the admin notification bell.

    Botble lets plugins contribute top-header notifications. KARPy keeps that
    same behavior by aggregating plugin state into the core notification feed.
    """
    try:
        from karpy_platform.plugins.contact.models.contact import Contact
    except Exception:
        return None, 0

    filters = [Contact.is_deleted.is_(False), Contact.status == "unread"]
    unread = await db.scalar(select(func.count()).select_from(Contact).where(*filters))
    unread_count = int(unread or 0)
    if unread_count <= 0:
        return None, 0

    latest = await db.scalar(select(Contact).where(*filters).order_by(Contact.created_at.desc()).limit(1))
    if not latest:
        return None, 0

    title = "New contact message" if unread_count == 1 else f"{unread_count} new contact messages"
    contact_line = "Open the latest contact submission and review it."
    if latest.name and latest.email:
        contact_line = f"{latest.name} sent a message from {latest.email}."

    return {
        "id": CONTACT_NOTIFICATION_ID,
        "title": title,
        "description": contact_line,
        "actionLabel": "View contact",
        "actionUrl": f"/admin/contacts/{latest.id}",
        "permission": "contacts.index",
        "readAt": None,
        "createdAt": latest.created_at.isoformat() if latest.created_at else None,
    }, unread_count


async def mark_contact_notifications_read(db: AsyncSession, *, all_items: bool) -> dict | None:
    try:
        from karpy_platform.plugins.contact.models.contact import Contact
    except Exception:
        return None

    filters = [Contact.is_deleted.is_(False), Contact.status == "unread"]
    if all_items:
        result = await db.execute(select(Contact).where(*filters))
        contacts = list(result.scalars().all())
    else:
        latest = await db.scalar(select(Contact).where(*filters).order_by(Contact.created_at.desc()).limit(1))
        contacts = [latest] if latest else []

    for contact in contacts:
        contact.status = "read"

    if contacts:
        await db.commit()

    now = datetime.utcnow().isoformat()
    return {
        "id": CONTACT_NOTIFICATION_ID,
        "title": "Contact notifications reviewed",
        "description": "Unread contact messages were marked as read.",
        "actionLabel": "View contacts",
        "actionUrl": "/admin/contacts",
        "permission": "contacts.index",
        "readAt": now,
        "createdAt": now,
    }


@router.get("/base/menu")
async def get_dashboard_menu(currentUrl: str = ""):
    register_core_admin_menu()
    return {"menus": dashboard_menu.get_all(current_url=currentUrl)}


@router.get("/base/breadcrumbs")
async def get_breadcrumbs():
    return {"title": page_title.get_title(), "breadcrumbs": breadcrumb.get_items()}


@router.get("/base/system")
async def get_base_system_info():
    from karpy_platform.core.manifest import read_core_json

    core = read_core_json()
    return {
        "appName": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "environment": settings.APP_ENV,
        "debug": settings.DEBUG,
        "adminPrefix": settings.ADMIN_DIR,
        "core": {
            "version": core.get("version"),
            "minimumPythonVersion": core.get("minimumPythonVersion"),
            "modules": core.get("modules", []),
        },
        "time": datetime.utcnow().isoformat(),
    } 


@router.get("/notifications")
async def list_admin_notifications(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(AdminNotification).order_by(AdminNotification.created_at.desc()))
    notifications = result.scalars().all()
    unread = int(await db.scalar(
        select(func.count()).select_from(AdminNotification).where(AdminNotification.read_at.is_(None))
    ) or 0)
    payloads = [notification_payload(item) for item in notifications]
    contact_payload, contact_unread = await contact_notification_payload(db)
    if contact_payload:
        payloads.insert(0, contact_payload)
    return {"notifications": payloads, "unread": unread + contact_unread}


@router.post("/notifications", status_code=status.HTTP_201_CREATED)
async def create_admin_notification(data: NotificationCreate, db: AsyncSession = Depends(get_db)):
    notification = AdminNotification(
        title=data.title,
        description=data.description,
        action_label=data.actionLabel,
        action_url=data.actionUrl,
        permission=data.permission,
    )
    db.add(notification)
    await db.commit()
    await db.refresh(notification)
    return BaseHttpResponse.make().set_data(notification_payload(notification)).with_created_success_message().to_dict()


@router.get("/notifications/count-unread")
async def count_unread_notifications(db: AsyncSession = Depends(get_db)):
    unread = int(await db.scalar(
        select(func.count()).select_from(AdminNotification).where(AdminNotification.read_at.is_(None))
    ) or 0)
    _, contact_unread = await contact_notification_payload(db)
    return {"unread": unread + contact_unread}


@router.put("/notifications/read-all")
async def read_all_notifications(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(AdminNotification).where(AdminNotification.read_at.is_(None)))
    for notification in result.scalars():
        notification.mark_as_read()
    await mark_contact_notifications_read(db, all_items=True)
    await db.commit()
    return BaseHttpResponse.make().with_updated_success_message().to_dict()


@router.put("/notifications/{notification_id}/read")
async def read_notification(notification_id: str, db: AsyncSession = Depends(get_db)):
    if notification_id == CONTACT_NOTIFICATION_ID:
        payload = await mark_contact_notifications_read(db, all_items=False)
        return BaseHttpResponse.make().set_data(payload or {}).with_updated_success_message().to_dict()

    notification = await db.get(AdminNotification, notification_id)
    if not notification:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Notification not found")
    notification.mark_as_read()
    await db.commit()
    await db.refresh(notification)
    return BaseHttpResponse.make().set_data(notification_payload(notification)).with_updated_success_message().to_dict()


@router.delete("/notifications/{notification_id}")
async def delete_notification(notification_id: str, db: AsyncSession = Depends(get_db)):
    notification = await db.get(AdminNotification, notification_id)
    if not notification:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Notification not found")
    await db.delete(notification)
    await db.commit()
    return BaseHttpResponse.make().with_deleted_success_message().to_dict()


@router.delete("/notifications")
async def delete_all_notifications(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(AdminNotification))
    for notification in result.scalars():
        await db.delete(notification)
    await db.commit()
    return BaseHttpResponse.make().with_deleted_success_message().to_dict()
