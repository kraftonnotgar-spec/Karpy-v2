"""Admin console registry: menu sections and Overview widgets declared by plugins.

The web admin (``web/src/app/admin``) builds its sidebar and its Overview page from this
registry at runtime, so a plugin appears in the admin by declaring metadata -- no web code
changes. Deactivated plugins disappear automatically because only active plugins are asked.

A plugin provider (``provider.py`` / ``plugin.py``) may implement either or both:

    @staticmethod
    def get_admin_sections() -> list[dict]:   # -> MenuSection
        ...

    @staticmethod
    def get_overview_widgets() -> list[dict]:  # -> OverviewWidget
        ...

Core items are registered with ``console_registry.register_section`` / ``register_widget``
(same shapes). Other code can change the final lists with the filters
``admin.console.sections`` and ``admin.console.widgets`` (``core/base/hooks.py``).

Labels are i18n keys (``label``) plus an English fallback (``label_default``); the web looks the
key up in its message catalogs and falls back to the default text.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Literal

from pydantic import BaseModel, Field, ValidationError, model_validator

from karpy_platform.core.base.hooks import hooks

log = logging.getLogger(__name__)

WidgetType = Literal["kpi", "area_chart", "line_chart", "bar_chart", "list", "todo"]
WidgetSize = Literal["sm", "md", "lg", "full"]


class Badge(BaseModel):
    """A count shown next to a menu item, e.g. pending items.

    ``endpoint`` is an API path (starting with ``/api/``) answering ``{"count": <int>}``
    for the signed-in admin. ``tone`` picks the badge style (design token, not a colour).
    """

    endpoint: str = Field(pattern=r"^/api/[A-Za-z0-9_\-/.{}?=&]+$")
    tone: Literal["default", "attention", "danger"] = "default"


class MenuItem(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9_.\-]*$")
    label: str
    label_default: str = ""
    icon: str | None = None  # lucide icon name, e.g. "inbox"
    route: str = ""  # web route, e.g. "/admin/contacts"
    permission: str | None = None
    badge: Badge | None = None
    priority: int = 50
    children: list["MenuItem"] = Field(default_factory=list)  # nested slide-in submenu

    @model_validator(mode="after")
    def _needs_target(self) -> "MenuItem":
        if not self.route and not self.children:
            raise ValueError(f"menu item {self.id!r} needs a route or children")
        return self


class MenuSection(BaseModel):
    """A group in the admin sidebar, e.g. "Content" or "Shop". Opens as a slide-in panel."""

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9_.\-]*$")
    label: str
    label_default: str = ""
    icon: str | None = None
    priority: int = 50
    permission: str | None = None
    items: list[MenuItem] = Field(default_factory=list)


class OverviewWidget(BaseModel):
    """A tile on the admin Overview page. The plugin provides data; core renders it.

    ``endpoint`` answers ``GET <endpoint>?from=YYYY-MM-DD&to=YYYY-MM-DD`` with the data shape of
    ``type`` (see docs/PLUGINS.md): ``kpi`` -> ``{"value", "previous"?, "format"?}``;
    ``area_chart``/``line_chart``/``bar_chart`` -> ``{"series": [{"key","label"}], "points": [{"x", <key>: n}]}``;
    ``list`` -> ``{"items": [{"id","title","subtitle"?,"href"?,"meta"?}]}``;
    ``todo`` -> ``{"items": [{"id","label","count","href"}]}``.
    """

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9_.\-]*$")
    type: WidgetType
    title: str
    title_default: str = ""
    endpoint: str = Field(pattern=r"^/api/[A-Za-z0-9_\-/.{}]+$")
    size: WidgetSize = "sm"
    permission: str | None = None
    order: int = 50
    options: dict[str, Any] = Field(default_factory=dict)


MenuItem.model_rebuild()


class ConsoleRegistry:
    def __init__(self) -> None:
        self._sections: dict[str, tuple[str, MenuSection]] = {}
        self._widgets: dict[str, tuple[str, OverviewWidget]] = {}

    def register_section(self, section: MenuSection | dict, *, source: str = "core") -> None:
        value = section if isinstance(section, MenuSection) else MenuSection(**section)
        self._sections[value.id] = (source, value)

    def register_widget(self, widget: OverviewWidget | dict, *, source: str = "core") -> None:
        value = widget if isinstance(widget, OverviewWidget) else OverviewWidget(**widget)
        self._widgets[value.id] = (source, value)

    def clear(self) -> None:
        self._sections.clear()
        self._widgets.clear()

    # -- collection ------------------------------------------------------------------

    @staticmethod
    def _from_plugins(method: str, model: type[BaseModel]) -> list[tuple[str, BaseModel]]:
        from karpy_platform.packages.plugin_management.service import get_active_plugins, plugin_service

        found: list[tuple[str, BaseModel]] = []
        for name in get_active_plugins():
            info = plugin_service.get_plugin_info(name)
            plugin_class = plugin_service._get_loaded_plugin(name, info)  # noqa: SLF001 - same as get_admin_menus
            getter: Callable | None = getattr(plugin_class, method, None) if plugin_class else None
            if not getter:
                continue
            try:
                for raw in getter() or []:
                    found.append((name, raw if isinstance(raw, model) else model(**raw)))
            except (ValidationError, TypeError, ValueError) as error:
                log.warning("Plugin %s returned an invalid %s entry: %s", name, method, error)
            except Exception:  # noqa: BLE001 - one broken plugin never breaks the admin
                log.exception("Plugin %s failed in %s", name, method)
        return found

    def sections(self) -> list[tuple[str, MenuSection]]:
        merged: dict[str, tuple[str, MenuSection]] = dict(self._sections)
        for source, section in self._from_plugins("get_admin_sections", MenuSection):
            if section.id in merged:
                # Two plugins may add items to the same section (e.g. both add to "content").
                owner, existing = merged[section.id]
                items = {item.id: item for item in existing.items}
                items.update({item.id: item for item in section.items})
                merged[section.id] = (owner, existing.model_copy(update={"items": list(items.values())}))
            else:
                merged[section.id] = (source, section)
        values = sorted(merged.values(), key=lambda pair: (pair[1].priority, pair[1].id))
        return hooks.apply_filters("admin.console.sections", values)

    def widgets(self) -> list[tuple[str, OverviewWidget]]:
        merged = dict(self._widgets)
        for source, widget in self._from_plugins("get_overview_widgets", OverviewWidget):
            merged[widget.id] = (source, widget)
        values = sorted(merged.values(), key=lambda pair: (pair[1].order, pair[1].id))
        return hooks.apply_filters("admin.console.widgets", values)


console_registry = ConsoleRegistry()


# -- permission filtering (per signed-in admin) ---------------------------------------

def _allowed(permission: str | None, can: Callable[[str], bool]) -> bool:
    return not permission or can(permission)


def _visible_items(items: list[MenuItem], can: Callable[[str], bool]) -> list[dict]:
    out = []
    for item in sorted(items, key=lambda value: (value.priority, value.id)):
        if not _allowed(item.permission, can):
            continue
        children = _visible_items(item.children, can)
        if item.children and not children and not item.route:
            continue  # a submenu whose every child is hidden disappears too
        data = item.model_dump(exclude={"children"})
        data["children"] = children
        out.append(data)
    return out


def visible_sections(can: Callable[[str], bool]) -> list[dict]:
    result = []
    for source, section in console_registry.sections():
        if not _allowed(section.permission, can):
            continue
        items = _visible_items(section.items, can)
        if not items:
            continue
        data = section.model_dump(exclude={"items"})
        data.update(plugin=source, items=items)
        result.append(data)
    return result


def visible_widgets(can: Callable[[str], bool]) -> list[dict]:
    return [
        {**widget.model_dump(), "plugin": source}
        for source, widget in console_registry.widgets()
        if _allowed(widget.permission, can)
    ]


def register_core_console() -> None:
    """The platform's own section. Plugins add theirs through their providers."""
    console_registry.register_section({
        "id": "platform",
        "label": "admin.sections.platform",
        "label_default": "Platform",
        "icon": "layout-grid",
        "priority": 900,
        "items": [
            {"id": "platform.pages", "label": "admin.menu.pages", "label_default": "Pages", "icon": "file-text", "route": "/admin/pages", "permission": "pages.index", "priority": 10},
            {"id": "platform.media", "label": "admin.menu.media", "label_default": "Media", "icon": "image", "route": "/admin/media", "permission": "media.index", "priority": 20},
            {"id": "platform.plugins", "label": "admin.menu.plugins", "label_default": "Plugins", "icon": "puzzle", "route": "/admin/plugins", "permission": "plugins.index", "priority": 30},
            {"id": "platform.users", "label": "admin.menu.users", "label_default": "Users & roles", "icon": "users", "route": "/admin/users", "permission": "users.index", "priority": 40},
            {"id": "platform.settings", "label": "admin.menu.settings", "label_default": "Settings", "icon": "settings", "route": "/admin/settings", "permission": "settings.index", "priority": 90},
        ],
    })
