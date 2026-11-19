from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from karpy_platform.core.acl.models import RoleUser, User
from karpy_platform.core.acl.routes import ensure_admin_user
from karpy_platform.core.base.hooks import hooks
from karpy_platform.core.base.responses import BaseHttpResponse
from karpy_platform.core.dashboard.constants import (
    DASHBOARD_ACTION_REGISTER_SCRIPTS,
    DASHBOARD_FILTER_ADMIN_LIST,
    DASHBOARD_FILTER_ADMIN_NOTIFICATIONS,
    DASHBOARD_FILTER_TOP_BLOCKS,
)
from karpy_platform.core.dashboard.models import DashboardWidget, DashboardWidgetSetting
from karpy_platform.core.dashboard.widgets import (
    dashboard_widgets,
    ensure_widget_setting,
    get_widgets_with_settings,
    register_default_dashboard_widgets,
)
from karpy_platform.core.setting.tracking import website_tracking
from karpy_platform.packages.page.models import Page
from karpy_platform.packages.plugin_management.service import plugin_service
from karpy_platform.packages.theme.service import theme_service

router = APIRouter()


class WidgetOrderUpdate(BaseModel):
    items: list[str] = Field(default_factory=list)


class WidgetSettingUpdate(BaseModel):
    name: str
    settingName: str
    settingValue: str | int | float | bool | None


class HideWidgetsUpdate(BaseModel):
    widgets: dict[str, bool] = Field(default_factory=dict)


async def current_user_id(db: AsyncSession) -> str:
    user = await ensure_admin_user(db)
    return user.id


@router.get("/dashboard/summary")
async def get_dashboard_summary(db: AsyncSession = Depends(get_db)):
    await current_user_id(db)
    users = int(
        await db.scalar(
            select(func.count(func.distinct(User.id)))
            .select_from(User)
            .join(RoleUser, RoleUser.user_id == User.id, isouter=True)
            .where((User.super_user.is_(True)) | (RoleUser.id.isnot(None)))
        )
        or 0
    )
    pages = int(await db.scalar(select(func.count()).select_from(Page).where(Page.is_deleted == False)) or 0)
    themes = len(await theme_service.list_themes(db))
    plugins = int(plugin_service.stats().get("installed", 0))
    return {
        "counts": {
            "themes": themes,
            "users": users,
            "plugins": plugins,
            "pages": pages,
        }
    }


@router.get("/dashboard/analytics")
async def get_dashboard_analytics(range: str = Query(default="90d"), db: AsyncSession = Depends(get_db)):
    user = await ensure_admin_user(db)
    allowed_ranges = {"today", "7d", "30d", "90d", "all"}
    range_key = range if range in allowed_ranges else "90d"
    enabled = await website_tracking.first_party_enabled(db)
    dashboard_enabled = await website_tracking.dashboard_enabled(db)
    if not enabled or not dashboard_enabled:
        return {"enabled": enabled, "dashboardEnabled": dashboard_enabled, "permission": True, "range": range_key}
    if not user.has_permission("dashboard.analytics"):
        return {"enabled": enabled, "dashboardEnabled": dashboard_enabled, "permission": False, "range": range_key}
    payload = await website_tracking.analytics(db, range_key)
    payload["permission"] = True
    return payload


@router.get("/dashboard")
async def get_dashboard(db: AsyncSession = Depends(get_db)):
    user_id = await current_user_id(db)
    register_default_dashboard_widgets()

    await hooks.do_action_async(DASHBOARD_ACTION_REGISTER_SCRIPTS)

    widget_models = await get_widgets_with_settings(db, user_id)
    widget_data: list[dict] = []
    for instance in dashboard_widgets.all():
        widget_data = await instance.init(db, user_id, widget_data)

    widget_data = await hooks.apply_filters_async(DASHBOARD_FILTER_ADMIN_LIST, widget_data, widget_models, db)
    admin_notifications = await hooks.apply_filters_async(DASHBOARD_FILTER_ADMIN_NOTIFICATIONS, [], widget_data, db)
    top_blocks = await hooks.apply_filters_async(DASHBOARD_FILTER_TOP_BLOCKS, [], widget_data)

    available_ids = {item["id"] for item in widget_data if item.get("id")}
    persisted_widgets = [widget for widget in widget_models if widget.id in available_ids]

    stat_widgets = sorted(
        [item for item in widget_data if item.get("type") != "widget" and item.get("status", True)],
        key=lambda item: item.get("priority", 999),
    )
    user_widgets = sorted(
        [item for item in widget_data if item.get("type") == "widget" and item.get("status", True)],
        key=lambda item: item.get("order", 999),
    )
    hidden_widgets = sorted(
        [item for item in widget_data if item.get("type") == "widget" and not item.get("status", True)],
        key=lambda item: item.get("order", 999),
    )

    await db.commit()

    return {
        "title": "Dashboard",
        "widgets": [_widget_model_payload(widget) for widget in persisted_widgets],
        "statWidgets": stat_widgets,
        "userWidgets": user_widgets,
        "hiddenWidgets": hidden_widgets,
        "management": {
            "title": "Manage Widgets",
            "action": "/api/admin/dashboard/widgets/hides",
            "widgets": [_management_widget_payload(item) for item in widget_data if item.get("type") == "widget"],
        },
        "adminNotifications": admin_notifications,
        "topBlocks": top_blocks,
    }


@router.get("/dashboard/widgets")
async def list_dashboard_widgets(db: AsyncSession = Depends(get_db)):
    user_id = await current_user_id(db)
    register_default_dashboard_widgets()
    widget_models = await get_widgets_with_settings(db, user_id)
    return {"widgets": [_widget_model_payload(widget) for widget in widget_models]}


@router.get("/dashboard/widgets/{widget_name}/load")
async def load_dashboard_widget(
    widget_name: str,
    predefined_range: str | None = None,
    changed_predefined_range: bool = False,
    db: AsyncSession = Depends(get_db),
):
    user_id = await current_user_id(db)
    register_default_dashboard_widgets()
    instance = dashboard_widgets.get(widget_name)
    if not instance:
        raise HTTPException(404, "Widget is not exists!")

    data = await instance.load(
        db,
        user_id,
        {
            "predefined_range": predefined_range,
            "changed_predefined_range": changed_predefined_range,
        },
    )
    return BaseHttpResponse.make().set_data(data).to_dict()


@router.post("/dashboard/widgets/setting-item")
async def edit_widget_setting_item(data: WidgetSettingUpdate, db: AsyncSession = Depends(get_db)):
    user_id = await current_user_id(db)
    widget = await db.scalar(select(DashboardWidget).where(DashboardWidget.name == data.name))
    if not widget:
        raise HTTPException(404, "Widget is not exists!")

    _, setting = await ensure_widget_setting(db, data.name, user_id)
    setting.settings = {**(setting.settings or {}), data.settingName: data.settingValue}
    await db.commit()
    return BaseHttpResponse.make().set_message("Save widget settings successfully!").to_dict()


@router.post("/dashboard/widgets/order")
async def update_widget_order(data: WidgetOrderUpdate, db: AsyncSession = Depends(get_db)):
    user_id = await current_user_id(db)
    for order, widget_name in enumerate(data.items):
        _, setting = await ensure_widget_setting(db, widget_name, user_id)
        setting.order = order
    await db.commit()
    return BaseHttpResponse.make().set_message("Update widget position successfully!").to_dict()


@router.get("/dashboard/widgets/hide")
async def hide_widget(name: str = Query(...), db: AsyncSession = Depends(get_db)):
    user_id = await current_user_id(db)
    widget = await db.scalar(select(DashboardWidget).where(DashboardWidget.name == name))
    if widget:
        _, setting = await ensure_widget_setting(db, name, user_id)
        max_order = await db.scalar(select(func.max(DashboardWidgetSetting.order)))
        setting.status = False
        setting.order = ((max_order or 0) if (max_order or 0) < 125 else 10) + 1
        await db.commit()

    return BaseHttpResponse.make().set_message("Update widget successfully!").to_dict()


@router.post("/dashboard/widgets/hides")
async def hide_widgets(data: HideWidgetsUpdate, db: AsyncSession = Depends(get_db)):
    user_id = await current_user_id(db)
    result = await db.execute(select(DashboardWidget))
    widgets = result.scalars().all()

    for widget in widgets:
        _, setting = await ensure_widget_setting(db, widget.name, user_id)
        if data.widgets.get(widget.name):
            setting.status = True
        else:
            max_order = await db.scalar(select(func.max(DashboardWidgetSetting.order)))
            setting.status = False
            setting.order = ((max_order or 0) if (max_order or 0) < 125 else 10) + 1

    await db.commit()
    return BaseHttpResponse.make().set_next_url("/admin").set_message("Update widget successfully!").to_dict()


def _widget_model_payload(widget: DashboardWidget) -> dict:
    setting = widget.settings[0] if widget.settings else None
    return {
        "id": widget.id,
        "name": widget.name,
        "setting": {
            "settings": setting.settings if setting else {},
            "order": setting.order if setting else 0,
            "status": setting.status if setting else True,
        },
    }


def _management_widget_payload(widget: dict) -> dict:
    return {
        "name": widget["name"],
        "title": widget["title"],
        "checked": widget.get("status", True),
        "order": widget.get("order", 0),
    }


# ---- Admin console registry (plugins' menu sections and Overview widgets) -------------

async def _console_permission_check(request, db: AsyncSession):
    from karpy_platform.core.acl.routes import current_admin_user

    user = await current_admin_user(request, db)
    return user.has_permission


@router.get("/console/menu")
async def console_menu(request: Request, db: AsyncSession = Depends(get_db)) -> dict:
    """Sidebar sections for the signed-in admin: active plugins only, items they may open."""
    from karpy_platform.core.dashboard.console import register_core_console, visible_sections

    register_core_console()
    return {"sections": visible_sections(await _console_permission_check(request, db))}


@router.get("/console/widgets")
async def console_widgets(request: Request, db: AsyncSession = Depends(get_db)) -> dict:
    """Overview widgets for the signed-in admin (metadata; each widget loads its own data)."""
    from karpy_platform.core.dashboard.console import register_core_console, visible_widgets

    register_core_console()
    return {"widgets": visible_widgets(await _console_permission_check(request, db))}
