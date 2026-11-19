from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


UrlResolver = str | Callable[[Any], str]


@dataclass
class TableAction:
    name: str
    label_text: str = ""
    url_value: UrlResolver | None = None
    icon_value: str | None = None
    color_value: str = "secondary"
    permissions: list[str] = field(default_factory=list)
    priority_value: int = 100
    confirmation_value: dict[str, Any] | None = None
    attributes: dict[str, Any] = field(default_factory=dict)
    type_value: str = "a"
    dropdown_item: bool = False

    @classmethod
    def make(cls, name: str):
        return cls(name=name)

    def label(self, value: str):
        self.label_text = value
        return self

    def url(self, value: UrlResolver):
        self.url_value = value
        return self

    def icon(self, value: str):
        self.icon_value = value
        return self

    def color(self, value: str):
        self.color_value = value
        return self

    def permission(self, value: str):
        self.permissions.append(value)
        return self

    def priority(self, value: int):
        self.priority_value = value
        return self

    def confirmation(self, title: str = "Are you sure?", message: str = ""):
        self.confirmation_value = {"title": title, "message": message}
        return self

    def add_attribute(self, key: str, value: Any):
        self.attributes[key] = value
        return self

    def type(self, value: str):
        self.type_value = value
        return self

    def display_as_dropdown_item(self, value: bool = True):
        self.dropdown_item = value
        return self

    def current_user_has_any_permissions(self) -> bool:
        return True

    def resolve_url(self, item: Any = None) -> str:
        if callable(self.url_value):
            if item is None:
                return ""
            return self.url_value(item)
        return self.url_value or ""

    def to_dict(self, item: Any = None) -> dict[str, Any]:
        return {
            "name": self.name,
            "label": self.label_text or self.name.replace("_", " ").title(),
            "url": self.resolve_url(item),
            "icon": self.icon_value,
            "color": self.color_value,
            "permissions": self.permissions,
            "priority": self.priority_value,
            "confirmation": self.confirmation_value,
            "attributes": self.attributes,
            "type": self.type_value,
            "dropdownItem": self.dropdown_item,
        }


class EditAction(TableAction):
    @classmethod
    def make(cls, name: str = "edit"):
        return cls(name=name, label_text="Edit", icon_value="edit", color_value="primary", priority_value=10)


class ViewAction(TableAction):
    @classmethod
    def make(cls, name: str = "view"):
        return cls(name=name, label_text="View", icon_value="eye", color_value="info", priority_value=5)


class DeleteAction(TableAction):
    @classmethod
    def make(cls, name: str = "delete"):
        return (
            cls(name=name, label_text="Delete", icon_value="trash", color_value="danger", priority_value=1000)
            .confirmation("Delete item?", "This action cannot be undone.")
        )


class HeaderAction(TableAction):
    pass


class CreateHeaderAction(HeaderAction):
    @classmethod
    def make(cls, name: str = "create"):
        return cls(name=name, label_text="Create", icon_value="plus", color_value="primary", priority_value=0)
