from __future__ import annotations

from dataclasses import dataclass

from karpy_platform.core.base.helpers import clean


@dataclass
class BreadcrumbItem:
    label: str
    url: str = ""


class PageTitle:
    def __init__(self) -> None:
        self._title = "Dashboard"

    def set_title(self, title: str) -> "PageTitle":
        self._title = clean(title)
        return self

    def get_title(self) -> str:
        return self._title


class Breadcrumb:
    def __init__(self) -> None:
        self._items: dict[str, list[BreadcrumbItem]] = {"admin": []}
        self._group = "admin"

    def for_group(self, group: str) -> "Breadcrumb":
        self._group = group
        self._items.setdefault(group, [])
        return self

    def default(self) -> "Breadcrumb":
        return self.for_group("admin")

    def add(self, label: str, url: str = "") -> "Breadcrumb":
        self._items[self._group].append(BreadcrumbItem(clean(label), url))
        return self

    def prepend(self, label: str, url: str = "") -> "Breadcrumb":
        self._items[self._group].insert(0, BreadcrumbItem(clean(label), url))
        return self

    def get_items(self, group: str = "admin") -> list[dict]:
        self.for_group(group)
        return [item.__dict__ for item in self._items[group]]

    def clear(self, group: str = "admin") -> "Breadcrumb":
        self._items[group] = []
        return self


page_title = PageTitle()
breadcrumb = Breadcrumb()
