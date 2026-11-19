from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from karpy_platform.core.dashboard.models import DashboardWidget, DashboardWidgetSetting


@dataclass
class DashboardWidgetInstance:
    type: str = "widget"
    key: str = ""
    title: str = ""
    icon: str = ""
    color: str = ""
    route: str = ""
    body_class: str = ""
    is_equal_height: bool = True
    column: str | None = None
    permission: str | None = None
    stats_total: int | str | Callable[["DashboardWidgetInstance"], int | str] = 0
    has_load_callback: bool = False
    settings: dict[str, Any] = field(default_factory=dict)
    predefined_ranges: list[dict[str, Any]] = field(default_factory=list)
    priority: int = 999
    load_callback: Callable[["DashboardWidgetInstance", dict[str, Any]], Any] | None = None

    def set_type(self, value: str) -> "DashboardWidgetInstance":
        self.type = value
        return self

    def set_key(self, value: str) -> "DashboardWidgetInstance":
        self.key = value
        return self

    def set_title(self, value: str) -> "DashboardWidgetInstance":
        self.title = value
        return self

    def set_icon(self, value: str) -> "DashboardWidgetInstance":
        self.icon = value
        return self

    def set_color(self, value: str) -> "DashboardWidgetInstance":
        self.color = value
        return self

    def set_route(self, value: str) -> "DashboardWidgetInstance":
        self.route = value
        return self

    def set_body_class(self, value: str) -> "DashboardWidgetInstance":
        self.body_class = value
        return self

    def set_column(self, value: str | None) -> "DashboardWidgetInstance":
        self.column = value
        return self

    def set_permission(self, value: str | None) -> "DashboardWidgetInstance":
        self.permission = value
        return self

    def set_priority(self, value: int) -> "DashboardWidgetInstance":
        self.priority = value
        return self

    def set_stats_total(self, value: int | str | Callable[["DashboardWidgetInstance"], int | str]) -> "DashboardWidgetInstance":
        self.stats_total = value
        return self

    def set_has_load_callback(self, value: bool) -> "DashboardWidgetInstance":
        self.has_load_callback = value
        return self

    def set_load_callback(
        self,
        value: Callable[["DashboardWidgetInstance", dict[str, Any]], Any] | None,
    ) -> "DashboardWidgetInstance":
        self.load_callback = value
        self.has_load_callback = value is not None
        return self

    def set_settings(self, value: dict[str, Any]) -> "DashboardWidgetInstance":
        self.settings = value
        return self

    def set_predefined_ranges(self, value: list[dict[str, Any]]) -> "DashboardWidgetInstance":
        self.predefined_ranges = value
        return self

    def get_stats_total(self) -> int | str:
        return self.stats_total(self) if callable(self.stats_total) else self.stats_total

    def get_predefined_ranges(self) -> list[dict[str, Any]]:
        return self.predefined_ranges or predefined_ranges()

    def get_filter_range(self, filter_range_input: str | None) -> dict[str, Any]:
        ranges = self.get_predefined_ranges()
        if filter_range_input:
            for item in ranges:
                if item["key"] == filter_range_input:
                    return item
        return ranges[0]

    async def init(self, db: AsyncSession, user_id: str, widgets: list[dict]) -> list[dict]:
        widget, setting = await ensure_widget_setting(db, self.key, user_id)
        merged_settings = {**(setting.settings or {}), **self.settings}

        payload = {
            "id": widget.id,
            "name": widget.name,
            "type": self.type,
            "title": self.title,
            "icon": self.icon,
            "color": self.color,
            "route": self.route,
            "loadUrl": f"/api/admin/dashboard/widgets/{self.key}/load",
            "column": self.column,
            "bodyClass": self.body_class,
            "isEqualHeight": self.is_equal_height,
            "hasLoadCallback": self.has_load_callback,
            "settings": merged_settings,
            "predefinedRanges": self.get_predefined_ranges(),
            "status": setting.status,
            "order": setting.order,
            "priority": self.priority,
        }

        if self.type != "widget":
            payload["statsTotal"] = self.get_stats_total()

        widgets.append(payload)
        return widgets

    async def load(self, db: AsyncSession, user_id: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        _, setting = await ensure_widget_setting(db, self.key, user_id)
        params = params or {}
        selected_range = params.get("predefined_range") or (setting.settings or {}).get("predefined_range")

        if selected_range:
            setting.settings = {**(setting.settings or {}), "predefined_range": selected_range}
            await db.commit()

        if self.load_callback:
            data = self.load_callback(self, params)
            if hasattr(data, "__await__"):
                data = await data
            return {"widget": self.key, "data": data}

        return {
            "widget": self.key,
            "title": self.title,
            "settings": setting.settings or {},
            "predefinedRange": self.get_filter_range(selected_range),
            "empty": False,
        }

    async def save_settings(self, db: AsyncSession, user_id: str, settings: dict[str, Any]) -> bool:
        if not self.key:
            return False
        _, setting = await ensure_widget_setting(db, self.key, user_id)
        setting.settings = {**(setting.settings or {}), **settings}
        await db.commit()
        return True


class DashboardWidgetRegistry:
    def __init__(self) -> None:
        self._instances: dict[str, DashboardWidgetInstance] = {}

    def register(self, widget: DashboardWidgetInstance) -> DashboardWidgetInstance:
        if not widget.key:
            raise ValueError("Dashboard widget key is required")
        self._instances[widget.key] = widget
        return widget

    def remove(self, key: str) -> None:
        self._instances.pop(key, None)

    def all(self) -> list[DashboardWidgetInstance]:
        return list(self._instances.values())

    def get(self, key: str) -> DashboardWidgetInstance | None:
        return self._instances.get(key)

    def clear(self) -> None:
        self._instances.clear()


dashboard_widgets = DashboardWidgetRegistry()


async def ensure_widget_setting(db: AsyncSession, widget_name: str, user_id: str) -> tuple[DashboardWidget, DashboardWidgetSetting]:
    widget = await db.scalar(select(DashboardWidget).where(DashboardWidget.name == widget_name))
    if not widget:
        widget = DashboardWidget(name=widget_name)
        db.add(widget)
        await db.flush()

    setting = await db.scalar(
        select(DashboardWidgetSetting).where(
            DashboardWidgetSetting.widget_id == widget.id,
            DashboardWidgetSetting.user_id == user_id,
        )
    )
    if not setting:
        max_order = await db.scalar(select(func.max(DashboardWidgetSetting.order)))
        setting = DashboardWidgetSetting(
            widget_id=widget.id,
            user_id=user_id,
            order=(max_order or 0) + 1,
            status=True,
            settings={},
        )
        db.add(setting)
        await db.flush()

    return widget, setting


async def get_widgets_with_settings(db: AsyncSession, user_id: str) -> list[DashboardWidget]:
    result = await db.execute(
        select(DashboardWidget)
        .options(selectinload(DashboardWidget.settings.and_(DashboardWidgetSetting.user_id == user_id)))
        .order_by(DashboardWidget.name)
    )
    return result.scalars().unique().all()


def predefined_ranges() -> list[dict[str, str]]:
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    yesterday_start = today_start - timedelta(days=1)
    week_start = today_start - timedelta(days=today_start.weekday())
    month_start = today_start.replace(day=1)
    year_start = today_start.replace(month=1, day=1)
    ranges = [
        ("today", "Today", today_start, now),
        ("yesterday", "Yesterday", yesterday_start, today_start - timedelta(microseconds=1)),
        ("this_week", "This Week", week_start, now),
        ("last_7_days", "Last 7 Days", today_start - timedelta(days=7), now),
        ("this_month", "This Month", month_start, now),
        ("last_30_days", "Last 30 Days", today_start - timedelta(days=29), now),
        ("this_year", "This Year", year_start, now),
    ]
    return [
        {"key": key, "label": label, "startDate": start.isoformat(), "endDate": end.isoformat()}
        for key, label, start, end in ranges
    ]


def register_default_dashboard_widgets() -> None:
    return
