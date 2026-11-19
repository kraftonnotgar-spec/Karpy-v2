from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable


@dataclass
class DashboardMenuItem:
    id: str
    name: str
    url: str = ""
    icon: str | None = None
    priority: int = 99
    parent_id: str | None = None
    route: str = ""
    permissions: list[str] | bool = field(default_factory=list)
    active: bool = False

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "url": self.url,
            "icon": self.icon,
            "priority": self.priority,
            "parent_id": self.parent_id,
            "route": self.route,
            "permissions": self.permissions,
            "active": self.active,
            "children": [],
        }


class DashboardMenu:
    """Registry for Botble-style admin sidebar items."""

    def __init__(self) -> None:
        self._items: dict[str, dict[str, DashboardMenuItem]] = {"admin": {}}
        self._removed: dict[str, set[str]] = {"admin": set()}
        self._group = "admin"
        self._before: dict[str, list[Callable]] = {"admin": []}
        self._after: dict[str, list[Callable]] = {"admin": []}

    def for_group(self, group: str) -> "DashboardMenu":
        self._group = group
        self._items.setdefault(group, {})
        self._removed.setdefault(group, set())
        self._before.setdefault(group, [])
        self._after.setdefault(group, [])
        return self

    def default(self) -> "DashboardMenu":
        return self.for_group("admin")

    def register_item(self, item: DashboardMenuItem | dict) -> "DashboardMenu":
        if isinstance(item, dict):
            item = DashboardMenuItem(**{key: value for key, value in item.items() if key in DashboardMenuItem.__dataclass_fields__})
        if not item.id:
            raise ValueError("Dashboard menu item id is required")
        self._items[self._group][item.id] = item
        return self

    def remove_item(self, *ids: str) -> "DashboardMenu":
        self._removed[self._group].update(ids)
        return self

    def before_retrieving(self, callback: Callable) -> "DashboardMenu":
        self._before[self._group].append(callback)
        return self

    def after_retrieved(self, callback: Callable) -> "DashboardMenu":
        self._after[self._group].append(callback)
        return self

    def get_all(self, group: str = "admin", current_url: str = "") -> list[dict]:
        self.for_group(group)
        for callback in self._before[group]:
            callback(self)

        removed = self._removed[group]
        raw_items = [
            item.to_dict()
            for item in self._items[group].values()
            if item.id not in removed and item.parent_id not in removed
        ]
        by_parent: dict[str | None, list[dict]] = {}
        for item in raw_items:
            by_parent.setdefault(item["parent_id"], []).append(item)

        def build(parent_id: str | None = None) -> list[dict]:
            children = sorted(by_parent.get(parent_id, []), key=lambda value: value.get("priority", 99))
            for child in children:
                child["children"] = build(child["id"])
                child["active"] = bool(current_url and child["url"] and current_url.startswith(child["url"]))
                if any(grandchild.get("active") for grandchild in child["children"]):
                    child["active"] = True
            return children

        menu = build(None)
        for callback in self._after[group]:
            callback(self, menu)

        self.default()
        return menu

    def clear(self, group: str = "admin") -> None:
        self._items[group] = {}
        self._removed[group] = set()


dashboard_menu = DashboardMenu()


def register_core_admin_menu() -> None:
    dashboard_menu.default()

    for item in [
        DashboardMenuItem("dashboard", "Dashboard", "/admin", "layout-dashboard", 1),
        DashboardMenuItem("pages", "Pages", "/admin/pages", "file-text", 10),
        DashboardMenuItem("media", "Media", "/admin/media", "photo", 20),
        DashboardMenuItem("plugins", "Plugins", "/admin/plugins", "puzzle", 90),
        DashboardMenuItem("installed-plugins", "Installed Plugins", "/admin/plugins", parent_id="plugins", priority=10),
        DashboardMenuItem("add-plugin", "Add New Plugin", "/admin/plugins/add", parent_id="plugins", priority=20),
        DashboardMenuItem("appearance", "Appearance", "/admin/appearance", "palette", 91),
        DashboardMenuItem("themes", "Themes", "/admin/appearance/themes", parent_id="appearance", priority=10),
        DashboardMenuItem("menus", "Menus", "/admin/appearance/menus", parent_id="appearance", priority=20),
        DashboardMenuItem("widgets", "Widgets", "/admin/appearance/widgets", parent_id="appearance", priority=30),
        DashboardMenuItem("theme-options", "Theme Options", "/admin/appearance/theme-options", parent_id="appearance", priority=40),
        DashboardMenuItem("custom-css", "Custom CSS", "/admin/appearance/custom-css", parent_id="appearance", priority=50),
        DashboardMenuItem("custom-html", "Custom HTML", "/admin/appearance/custom-html", parent_id="appearance", priority=60),
        DashboardMenuItem("robots-txt", "Robots.txt Editor", "/admin/appearance/robots-txt", parent_id="appearance", priority=70),
        DashboardMenuItem("tools", "Tools", "/admin/tools/data-synchronize", "tools", 92, permissions=["core.tools"]),
        DashboardMenuItem("data-synchronize", "Export/Import Data", "/admin/tools/data-synchronize", parent_id="tools", priority=10),
        DashboardMenuItem("settings", "Settings", "/admin/settings", "settings", 99),
        DashboardMenuItem("system", "Platform Administration", "/admin/system", "users", 10000),
    ]:
        dashboard_menu.register_item(item)
