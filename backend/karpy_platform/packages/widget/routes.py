from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from karpy_platform.core.acl.routes import ensure_admin_user
from karpy_platform.core.base.responses import BaseHttpResponse
from karpy_platform.packages.theme.service import theme_service
from karpy_platform.packages.widget.service import widget_service

router = APIRouter()


class WidgetItemPayload(BaseModel):
    widget_id: str | None = None
    widgetId: str | None = None
    id: str | None = None
    position: int | None = None
    data: dict[str, Any] = Field(default_factory=dict)


class SidebarUpdatePayload(BaseModel):
    sidebar_id: str | None = None
    sidebarId: str | None = None
    theme: str | None = None
    items: list[dict[str, Any]] = Field(default_factory=list)


class WidgetCreatePayload(BaseModel):
    widget_id: str | None = None
    widgetId: str | None = None
    sidebar_id: str | None = None
    sidebarId: str | None = None
    theme: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)


class WidgetUpdatePayload(BaseModel):
    sidebar_id: str | None = None
    sidebarId: str | None = None
    theme: str | None = None
    position: int | None = None
    data: dict[str, Any] = Field(default_factory=dict)


class SidebarOrderPayload(BaseModel):
    theme: str | None = None
    sidebar_id: str | None = None
    sidebarId: str | None = None
    item_ids: list[str] = Field(default_factory=list)
    itemIds: list[str] = Field(default_factory=list)


@router.get("")
async def widgets_index(theme: str | None = Query(default=None), db: AsyncSession = Depends(get_db)):
    await ensure_admin_user(db)
    active_theme = theme or await theme_service.active_theme_name(db)
    return await widget_service.payload(db, active_theme)


@router.get("/groups")
async def widget_groups(db: AsyncSession = Depends(get_db)):
    await ensure_admin_user(db)
    return {"groups": await widget_service.groups()}


@router.get("/available")
async def available_widgets(db: AsyncSession = Depends(get_db)):
    await ensure_admin_user(db)
    return {"widgets": await widget_service.available_widgets()}


@router.put("/sidebar")
async def update_sidebar(payload: SidebarUpdatePayload, db: AsyncSession = Depends(get_db)):
    await ensure_admin_user(db)
    theme = payload.theme or await theme_service.active_theme_name(db)
    sidebar_id = payload.sidebar_id or payload.sidebarId or "primary_sidebar"
    saved = await widget_service.save_sidebar(db, theme, sidebar_id, payload.items)
    return BaseHttpResponse.make().set_data({"widgets": [widget_service.widget_payload(widget) for widget in saved]}).set_message("Widget saved successfully").to_dict()


@router.post("/sidebar")
async def save_sidebar(payload: SidebarUpdatePayload, db: AsyncSession = Depends(get_db)):
    return await update_sidebar(payload, db)


@router.post("/instances")
async def add_widget_instance(payload: WidgetCreatePayload, db: AsyncSession = Depends(get_db)):
    await ensure_admin_user(db)
    theme = payload.theme or await theme_service.active_theme_name(db)
    sidebar_id = payload.sidebar_id or payload.sidebarId or "primary_sidebar"
    widget_id = payload.widget_id or payload.widgetId
    if not widget_id:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Widget is required")
    try:
        widget = await widget_service.add_widget(db, theme, sidebar_id, widget_id, payload.data)
    except ValueError as exception:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exception)) from exception
    return BaseHttpResponse.make().set_data({"widget": widget_service.widget_payload(widget)}).set_message("Widget added successfully").to_dict()


@router.patch("/instances/{instance_id}")
async def update_widget_instance(instance_id: str, payload: WidgetUpdatePayload, db: AsyncSession = Depends(get_db)):
    await ensure_admin_user(db)
    theme = payload.theme or await theme_service.active_theme_name(db)
    try:
        widget = await widget_service.update_widget(
            db,
            theme,
            instance_id,
            payload.data,
            payload.sidebar_id or payload.sidebarId,
            payload.position,
        )
    except ValueError as exception:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exception)) from exception
    return BaseHttpResponse.make().set_data({"widget": widget_service.widget_payload(widget)}).set_message("Widget saved successfully").to_dict()


@router.delete("/instances/{instance_id}")
async def delete_widget_instance(instance_id: str, theme: str | None = Query(default=None), db: AsyncSession = Depends(get_db)):
    await ensure_admin_user(db)
    active_theme = theme or await theme_service.active_theme_name(db)
    deleted = await widget_service.delete_widget_instance(db, active_theme, instance_id)
    return BaseHttpResponse.make().set_data({"deleted": deleted}).set_message("Widget deleted successfully").to_dict()


@router.put("/sidebars/{sidebar_id}/order")
async def reorder_sidebar(sidebar_id: str, payload: SidebarOrderPayload, db: AsyncSession = Depends(get_db)):
    await ensure_admin_user(db)
    theme = payload.theme or await theme_service.active_theme_name(db)
    target_sidebar = payload.sidebar_id or payload.sidebarId or sidebar_id
    item_ids = payload.item_ids or payload.itemIds
    widgets = await widget_service.reorder_sidebar(db, theme, target_sidebar, item_ids)
    return BaseHttpResponse.make().set_data({"widgets": [widget_service.widget_payload(widget) for widget in widgets]}).set_message("Widget order saved successfully").to_dict()


@router.delete("/sidebar/{sidebar_id}/{widget_id}")
async def delete_widget(
    sidebar_id: str,
    widget_id: str,
    theme: str | None = Query(default=None),
    position: int | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    await ensure_admin_user(db)
    active_theme = theme or await theme_service.active_theme_name(db)
    deleted = await widget_service.delete_widget(db, active_theme, sidebar_id, widget_id, position)
    return BaseHttpResponse.make().set_data({"deleted": deleted}).set_message("Widget deleted successfully").to_dict()


@router.get("/render/{sidebar_id}")
async def render_sidebar(sidebar_id: str, theme: str | None = Query(default=None), db: AsyncSession = Depends(get_db)):
    active_theme = theme or await theme_service.active_theme_name(db)
    return {"sidebarId": sidebar_id, "html": await widget_service.render_sidebar(db, active_theme, sidebar_id)}
