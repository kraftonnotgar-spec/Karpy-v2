from __future__ import annotations

from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from karpy_platform.core.base.dashboard_menu import DashboardMenuItem, dashboard_menu
from karpy_platform.core.base.hooks import hooks
from karpy_platform.packages.theme.constants import THEME_FILTER_TEMPLATE_CONTEXT
from karpy_platform.packages.widget.constants import (
    WIDGET_ACTION_DELETED,
    WIDGET_ACTION_RENDERING,
    WIDGET_ACTION_SAVED,
    WIDGET_ACTION_SETTINGS_RENDERING,
    WIDGET_FILTER_AVAILABLE,
    WIDGET_FILTER_GROUPS,
    WIDGET_FILTER_PAYLOAD,
)
from karpy_platform.packages.widget.models import Widget
from karpy_platform.packages.widget.widgets import (
    AbstractWidget,
    CoreSimpleMenuWidget,
    SiteCopyrightWidget,
    TextWidget,
    WidgetFactory,
    WidgetGroup,
)


class WidgetService:
    """Botble package/widget port: sidebars, registered widgets, persistence, rendering."""

    def __init__(self) -> None:
        self._booted = False
        self._groups: dict[str, WidgetGroup] = {}
        self.factory = WidgetFactory()

    def boot(self) -> None:
        if self._booted:
            return
        self.set_group(
            {
                "id": "primary_sidebar",
                "name": "Primary sidebar",
                "description": "Primary sidebar section",
            }
        )
        self.set_group(
            {
                "id": "top_sidebar",
                "name": "Top sidebar",
                "description": "Area for widgets on the top sidebar",
            }
        )
        self.set_group(
            {
                "id": "footer_sidebar",
                "name": "Footer sidebar",
                "description": "Area for footer widgets",
            }
        )
        self.register_widget(CoreSimpleMenuWidget)
        self.register_widget(TextWidget)
        self.register_widget(SiteCopyrightWidget)
        dashboard_menu.default().register_item(
            DashboardMenuItem(
                id="widgets",
                name="Widgets",
                url="/admin/appearance/widgets",
                icon="layout",
                priority=30,
                parent_id="appearance",
                permissions=["widgets.index"],
            )
        )
        hooks.add_filter(THEME_FILTER_TEMPLATE_CONTEXT, self._add_theme_context, priority=30)
        self._booted = True

    def set_group(self, args: dict[str, Any]) -> "WidgetService":
        group_id = args["id"]
        if group_id in self._groups:
            group = self._groups[group_id]
            group.name = args.get("name") or group.name
            group.description = args.get("description") or group.description
        else:
            self._groups[group_id] = WidgetGroup(group_id, args.get("name") or group_id, args.get("description") or "")
        return self

    def group(self, group_id: str) -> WidgetGroup:
        if group_id not in self._groups:
            self.set_group({"id": group_id, "name": group_id})
        return self._groups[group_id]

    def remove_group(self, group_id: str) -> "WidgetService":
        self._groups.pop(group_id, None)
        return self

    async def groups(self) -> list[dict[str, Any]]:
        return await hooks.apply_filters_async(WIDGET_FILTER_GROUPS, [group.to_dict() for group in self._groups.values()])

    def register_widget(self, widget_class: type[AbstractWidget]) -> None:
        self.factory.register_widget(widget_class)

    async def available_widgets(self) -> list[dict[str, Any]]:
        return await hooks.apply_filters_async(WIDGET_FILTER_AVAILABLE, self.factory.all())

    async def widgets_for_theme(self, db: AsyncSession, theme: str, sidebar_id: str | None = None) -> list[Widget]:
        statement = select(Widget).where(Widget.is_deleted == False, Widget.theme == theme).order_by(Widget.sidebar_id, Widget.position)
        if sidebar_id:
            statement = statement.where(Widget.sidebar_id == sidebar_id)
        result = await db.execute(statement)
        return list(result.scalars().unique().all())

    async def payload(self, db: AsyncSession, theme: str) -> dict[str, Any]:
        await hooks.do_action_async(WIDGET_ACTION_SETTINGS_RENDERING)
        groups = await self.groups()
        available = await self.available_widgets()
        assignments: dict[str, list[dict[str, Any]]] = {group["id"]: [] for group in groups}
        for widget in await self.widgets_for_theme(db, theme):
            assignments.setdefault(widget.sidebar_id, []).append(self.widget_payload(widget))
        for group in groups:
            group["count"] = len(assignments.get(group["id"], []))
        payload = {
            "theme": theme,
            "groups": groups,
            "available": available,
            "assignments": assignments,
            "cache": {
                "settingKey": "widget_cache_enabled",
                "ttlKey": "widget_cache_ttl",
            },
        }
        return await hooks.apply_filters_async(WIDGET_FILTER_PAYLOAD, payload, db, theme)

    def widget_payload(self, widget: Widget) -> dict[str, Any]:
        definition = self.factory.get(widget.widget_id)
        return {
            "id": widget.id,
            "widgetId": widget.widget_id,
            "sidebarId": widget.sidebar_id,
            "theme": widget.theme,
            "position": widget.position,
            "data": widget.data or {},
            "definition": definition.payload() if definition else None,
            "createdAt": widget.created_at.isoformat() if widget.created_at else None,
            "updatedAt": widget.updated_at.isoformat() if widget.updated_at else None,
        }

    async def save_sidebar(self, db: AsyncSession, theme: str, sidebar_id: str, items: list[dict[str, Any]]) -> list[Widget]:
        await db.execute(delete(Widget).where(Widget.theme == theme, Widget.sidebar_id == sidebar_id))
        saved: list[Widget] = []
        for index, item in enumerate(items):
            widget_id = item.get("widget_id") or item.get("widgetId") or item.get("id")
            if not widget_id or not self.factory.get(widget_id):
                continue
            widget = Widget(
                widget_id=widget_id,
                sidebar_id=sidebar_id,
                theme=theme,
                position=int(item.get("position", index) if item.get("position") is not None else index),
                data=item.get("data") or self._extract_data(item),
            )
            db.add(widget)
            saved.append(widget)
        await db.commit()
        for widget in saved:
            await db.refresh(widget)
        self.factory.clear_cache()
        await hooks.do_action_async(WIDGET_ACTION_SAVED, theme, sidebar_id, saved)
        return saved

    async def add_widget(
        self,
        db: AsyncSession,
        theme: str,
        sidebar_id: str,
        widget_id: str,
        data: dict[str, Any] | None = None,
    ) -> Widget:
        definition = self.factory.get(widget_id)
        if not definition:
            raise ValueError(f"Widget is not registered: {widget_id}")
        existing = await self.widgets_for_theme(db, theme, sidebar_id)
        widget = Widget(
            widget_id=widget_id,
            sidebar_id=sidebar_id,
            theme=theme,
            position=len(existing),
            data={**definition.default_config, **(data or {})},
        )
        db.add(widget)
        await db.commit()
        await db.refresh(widget)
        self.factory.clear_cache()
        await hooks.do_action_async(WIDGET_ACTION_SAVED, theme, sidebar_id, [widget])
        return widget

    async def update_widget(
        self,
        db: AsyncSession,
        theme: str,
        instance_id: str,
        data: dict[str, Any] | None = None,
        sidebar_id: str | None = None,
        position: int | None = None,
    ) -> Widget:
        result = await db.execute(select(Widget).where(Widget.id == instance_id, Widget.theme == theme, Widget.is_deleted == False))
        widget = result.scalar_one_or_none()
        if not widget:
            raise ValueError("Widget instance was not found")
        if sidebar_id:
            widget.sidebar_id = sidebar_id
        if position is not None:
            widget.position = position
        if data is not None:
            widget.data = data
        await db.commit()
        await db.refresh(widget)
        self.factory.clear_cache()
        await hooks.do_action_async(WIDGET_ACTION_SAVED, theme, widget.sidebar_id, [widget])
        return widget

    async def delete_widget_instance(self, db: AsyncSession, theme: str, instance_id: str) -> int:
        result = await db.execute(delete(Widget).where(Widget.id == instance_id, Widget.theme == theme))
        await db.commit()
        self.factory.clear_cache()
        await hooks.do_action_async(WIDGET_ACTION_DELETED, theme, "", instance_id, None)
        return result.rowcount or 0

    async def reorder_sidebar(self, db: AsyncSession, theme: str, sidebar_id: str, instance_ids: list[str]) -> list[Widget]:
        existing = await self.widgets_for_theme(db, theme, sidebar_id)
        by_id = {widget.id: widget for widget in existing}
        ordered: list[Widget] = []
        for position, instance_id in enumerate(instance_ids):
            widget = by_id.get(instance_id)
            if widget:
                widget.position = position
                ordered.append(widget)
        trailing = [widget for widget in existing if widget.id not in set(instance_ids)]
        for offset, widget in enumerate(trailing, start=len(ordered)):
            widget.position = offset
            ordered.append(widget)
        await db.commit()
        for widget in ordered:
            await db.refresh(widget)
        self.factory.clear_cache()
        await hooks.do_action_async(WIDGET_ACTION_SAVED, theme, sidebar_id, ordered)
        return ordered

    async def delete_widget(self, db: AsyncSession, theme: str, sidebar_id: str, widget_id: str, position: int | None = None) -> int:
        statement = delete(Widget).where(Widget.theme == theme, Widget.sidebar_id == sidebar_id, Widget.widget_id == widget_id)
        if position is not None:
            statement = statement.where(Widget.position == position)
        result = await db.execute(statement)
        await db.commit()
        self.factory.clear_cache()
        await hooks.do_action_async(WIDGET_ACTION_DELETED, theme, sidebar_id, widget_id, position)
        return result.rowcount or 0

    async def render_sidebar(self, db: AsyncSession, theme: str, sidebar_id: str) -> str:
        await hooks.do_action_async(WIDGET_ACTION_RENDERING, sidebar_id)
        widgets = await self.widgets_for_theme(db, theme, sidebar_id)
        output = []
        for widget in widgets:
            output.append(await self.factory.run(db, widget.widget_id, widget.data or {}, sidebar_id, widget.position, theme))
        return "".join(output)

    async def render_all_for_theme(self, db: AsyncSession, theme: str) -> dict[str, str]:
        rendered = {}
        for group in self._groups.values():
            rendered[group.id] = await self.render_sidebar(db, theme, group.id)
        return rendered

    def _extract_data(self, item: dict[str, Any]) -> dict[str, Any]:
        ignored = {"id", "widget_id", "widgetId", "sidebar_id", "sidebarId", "position", "data"}
        return {key: value for key, value in item.items() if key not in ignored}

    async def _add_theme_context(self, context: dict[str, Any], renderer: Any, db: AsyncSession) -> dict[str, Any]:
        widgets = await self.render_all_for_theme(db, renderer.theme)
        context["widgets"] = widgets
        context["widget_area"] = lambda sidebar_id: widgets.get(sidebar_id, "")
        return context


widget_service = WidgetService()


def boot_widget_package() -> None:
    widget_service.boot()
