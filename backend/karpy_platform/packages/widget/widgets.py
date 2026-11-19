from __future__ import annotations

import html
import re
import time
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from karpy_platform.core.base.helpers import clean
from karpy_platform.core.base.hooks import hooks
from karpy_platform.core.setting.store import setting_store
from karpy_platform.packages.widget.constants import WIDGET_FILTER_MENU_ADMIN_CONFIG, WIDGET_FILTER_RENDERED


def _contains_form_elements(content: str | None) -> bool:
    if not content:
        return False
    patterns = ["<form", "csrf_token", "_token", "g-recaptcha", "type=\"submit\"", "method=\"post\"", "method=\"POST\""]
    return any(pattern.lower() in content.lower() for pattern in patterns)


@dataclass
class WidgetField:
    name: str
    label: str
    type: str = "text"
    default: Any = None
    required: bool = False
    options: dict[str, Any] | list[Any] | None = None
    helper: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "label": self.label,
            "type": self.type,
            "default": self.default,
            "required": self.required,
            "options": self.options,
            "helper": self.helper,
        }


class AbstractWidget:
    """Base class for frontend widgets, close to Botble's AbstractWidget."""

    id: str = ""
    name: str = ""
    description: str = ""
    default_config: dict[str, Any] = {}
    ignored_caches: set[str] = set()

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = {**self.default_config, **(config or {})}

    @classmethod
    def widget_id(cls) -> str:
        return cls.id or f"{cls.__module__}.{cls.__name__}"

    @classmethod
    def admin_config(cls) -> list[WidgetField]:
        return []

    @classmethod
    def payload(cls) -> dict[str, Any]:
        return {
            "id": cls.widget_id(),
            "name": cls.name or cls.__name__,
            "description": cls.description,
            "defaults": cls.default_config,
            "fields": [field.to_dict() for field in cls.admin_config()],
        }

    async def data(self, db: AsyncSession, sidebar_id: str, position: int) -> dict[str, Any]:
        return {}

    async def render(self, db: AsyncSession, sidebar_id: str, position: int) -> str:
        html_output = await self.render_content(db, sidebar_id, position)
        return await hooks.apply_filters_async(WIDGET_FILTER_RENDERED, html_output, self, db)

    async def render_content(self, db: AsyncSession, sidebar_id: str, position: int) -> str:
        return ""

    @classmethod
    def ignore_caches(cls, widgets: list[str]) -> None:
        cls.ignored_caches.update(widgets)

    def should_ignore_cache(self) -> bool:
        return self.widget_id() in self.ignored_caches


class TextWidget(AbstractWidget):
    id = "text"
    name = "Text"
    description = "Arbitrary text or HTML."
    default_config = {"name": "", "content": ""}

    @classmethod
    def admin_config(cls) -> list[WidgetField]:
        return [
            WidgetField("name", "Name"),
            WidgetField("content", "Content", type="textarea"),
            WidgetField("enable_caching", "Enable caching", type="select", default="yes", options={"yes": "Yes", "no": "No"}),
        ]

    async def render_content(self, db: AsyncSession, sidebar_id: str, position: int) -> str:
        from karpy_platform.packages.shortcode.engine import shortcode_engine

        title = clean(self.config.get("name") or "")
        content = shortcode_engine.compile(str(self.config.get("content") or ""))
        if not title and not content:
            return ""
        title_html = f"<div class=\"panel-title\"><h3>{html.escape(title)}</h3></div>" if title else ""
        return f"<section class=\"widget widget-text\">{title_html}<div class=\"panel-content\">{content}</div></section>"


class CoreSimpleMenuWidget(AbstractWidget):
    id = "core-simple-menu"
    name = "Simple menu"
    description = "Add a simple menu to a widget area."
    default_config = {"name": "", "items": []}

    @classmethod
    def admin_config(cls) -> list[WidgetField]:
        fields = [
            WidgetField("name", "Name"),
            WidgetField(
                "items",
                "Items",
                type="repeater",
                default=[],
                options=[
                    WidgetField("label", "Label", required=True).to_dict(),
                    WidgetField("url", "URL", required=True).to_dict(),
                    WidgetField("attributes", "Attributes").to_dict(),
                    WidgetField("is_open_new_tab", "Open in new tab?", type="switch").to_dict(),
                ],
            ),
            WidgetField("enable_caching", "Enable caching", type="select", default="yes", options={"yes": "Yes", "no": "No"}),
        ]
        return hooks.apply_filters(WIDGET_FILTER_MENU_ADMIN_CONFIG, fields, cls)

    async def render_content(self, db: AsyncSession, sidebar_id: str, position: int) -> str:
        title = clean(self.config.get("name") or "")
        items = self.config.get("items") or []
        if isinstance(items, str):
            items = []
        rows = []
        for item in items:
            item = self._normalize_item(item)
            label = clean(item.get("label") or "")
            url = item.get("url") or "#"
            if not label:
                continue
            attributes = clean(item.get("attributes") or "")
            target = " target=\"_blank\" rel=\"noopener\"" if item.get("is_open_new_tab") else ""
            rows.append(f"<li><a href=\"{html.escape(str(url), quote=True)}\" {attributes}{target}>{html.escape(label)}</a></li>")
        if not rows and not title:
            return ""
        title_html = f"<h3>{html.escape(title)}</h3>" if title else ""
        return f"<section class=\"widget widget-simple-menu\">{title_html}<ul>{''.join(rows)}</ul></section>"

    def _normalize_item(self, item: Any) -> dict[str, Any]:
        if isinstance(item, dict):
            return item
        if isinstance(item, list):
            return {row.get("key"): row.get("value") for row in item if isinstance(row, dict)}
        return {}


class SiteCopyrightWidget(AbstractWidget):
    id = "site-copyright"
    name = "Site copyright"
    description = "Copyright text from theme options."
    default_config = {"name": ""}

    @classmethod
    def admin_config(cls) -> list[WidgetField]:
        return [
            WidgetField("name", "Name"),
            WidgetField("description", "Helper", type="html", default="Change the copyright text in Theme Options."),
        ]

    async def render_content(self, db: AsyncSession, sidebar_id: str, position: int) -> str:
        from karpy_platform.packages.theme.service import theme_service

        active_theme = await theme_service.active_theme_name(db)
        copyright_text = theme_service.copyright(await theme_service.option(db, "copyright", "", active_theme))
        if not copyright_text:
            return ""
        return f"<section class=\"widget widget-copyright\">{html.escape(copyright_text)}</section>"


@dataclass
class WidgetGroup:
    id: str
    name: str
    description: str = ""
    separator: str = ""
    widgets: dict[int, list[dict[str, Any]]] = field(default_factory=dict)

    def position(self, position: int) -> "WidgetGroupPosition":
        return WidgetGroupPosition(self, position)

    def add_widget(self, widget_id: str, data: dict[str, Any] | None = None, position: int = 100) -> None:
        self.widgets.setdefault(position, []).append({"widget_id": widget_id, "data": data or {}, "position": position})

    def clear_widgets(self) -> None:
        self.widgets.clear()

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "description": self.description, "count": self.count()}

    def count(self) -> int:
        return sum(len(items) for items in self.widgets.values())


class WidgetGroupPosition:
    def __init__(self, group: WidgetGroup, position: int) -> None:
        self.group = group
        self._position = position

    def add_widget(self, widget_id: str, data: dict[str, Any] | None = None) -> None:
        self.group.add_widget(widget_id, data, self._position)


class WidgetFactory:
    def __init__(self) -> None:
        self._widgets: dict[str, type[AbstractWidget]] = {}
        self._cache: dict[str, tuple[float, str]] = {}

    def register_widget(self, widget_class: type[AbstractWidget]) -> None:
        self._widgets[widget_class.widget_id()] = widget_class

    def get(self, widget_id: str) -> type[AbstractWidget] | None:
        return self._widgets.get(widget_id)

    def all(self) -> list[dict[str, Any]]:
        return [widget.payload() for widget in self._widgets.values()]

    async def run(self, db: AsyncSession, widget_id: str, config: dict[str, Any] | None, sidebar_id: str, position: int, theme: str) -> str:
        widget_class = self.get(widget_id)
        if not widget_class:
            return ""
        widget = widget_class(config or {})
        cache_enabled = str(await setting_store.get(db, "widget_cache_enabled", "0")).lower() in {"1", "true", "yes", "on"}
        cache_ttl = int(await setting_store.get(db, "widget_cache_ttl", "1800") or 1800)
        cache_key = f"{theme}:{sidebar_id}:{position}:{widget_id}:{hash(str(config))}"
        if cache_enabled and not widget.should_ignore_cache() and str(widget.config.get("enable_caching", "yes")) != "no":
            cached = self._cache.get(cache_key)
            if cached and cached[0] > time.time():
                return cached[1]
        rendered = await widget.render(db, sidebar_id, position)
        if cache_enabled and rendered and not _contains_form_elements(rendered):
            self._cache[cache_key] = (time.time() + cache_ttl, rendered)
        return rendered

    def clear_cache(self) -> None:
        self._cache.clear()
