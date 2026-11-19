from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from sqlalchemy import delete, update
from sqlalchemy.ext.asyncio import AsyncSession

from karpy_platform.core.base.responses import BaseHttpResponse


@dataclass
class TableBulkChange:
    name_value: str = ""
    title_value: str = ""
    type_value: str = "text"
    validate_value: str | list[str] | None = None
    required_value: bool = False
    options: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def make(cls, data: dict[str, Any] | None = None):
        instance = cls()
        for key, value in (data or {}).items():
            setattr(instance, key, value)
        return instance

    def name(self, value: str):
        self.name_value = value
        return self

    def title(self, value: str):
        self.title_value = value
        return self

    def type(self, value: str):
        self.type_value = value
        return self

    def validate(self, value: str | list[str]):
        self.validate_value = value
        return self

    def required(self, value: bool = True):
        self.required_value = value
        return self

    def choices(self, values: list[dict[str, Any]]):
        self.options = values
        return self

    def get_name(self) -> str:
        return self.name_value

    def to_dict(self) -> dict[str, Any]:
        validate = self.validate_value
        if isinstance(validate, list):
            validate = "|".join(validate)
        if self.required_value:
            validate = "required" if not validate else f"required|{validate}"
        return {
            "name": self.name_value,
            "title": self.title_value or self.name_value.replace("_", " ").title(),
            "type": self.type_value,
            "validate": validate,
            "options": self.options,
        }


class TextBulkChange(TableBulkChange):
    @classmethod
    def make(cls, data: dict[str, Any] | None = None):
        return super().make(data).type("text").validate(["required", "string", "max:255"])


class NumberBulkChange(TableBulkChange):
    @classmethod
    def make(cls, data: dict[str, Any] | None = None):
        return super().make(data).type("number").validate(["required", "numeric"])


class DateBulkChange(TableBulkChange):
    @classmethod
    def make(cls, data: dict[str, Any] | None = None):
        return super().make(data).type("date").validate(["required", "date"])


class SelectBulkChange(TableBulkChange):
    @classmethod
    def make(cls, data: dict[str, Any] | None = None):
        return super().make(data).type("select").validate(["required"])


@dataclass
class TableBulkAction:
    name: str
    label_text: str = ""
    priority_value: int = 100
    permissions: list[str] = field(default_factory=list)
    confirmation_value: dict[str, Any] | None = None
    before_dispatch: Callable[[Any, list[Any]], None] | None = None
    after_dispatch: Callable[[Any, list[Any]], None] | None = None

    @classmethod
    def make(cls, name: str):
        return cls(name=name)

    def label(self, value: str):
        self.label_text = value
        return self

    def priority(self, value: int):
        self.priority_value = value
        return self

    def permission(self, value: str):
        self.permissions.append(value)
        return self

    def confirmation(self, title: str = "Are you sure?", message: str = ""):
        self.confirmation_value = {"title": title, "message": message}
        return self

    def current_user_has_any_permissions(self) -> bool:
        return True

    async def dispatch(self, db: AsyncSession, model: type, ids: list[Any]) -> BaseHttpResponse:
        raise NotImplementedError

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "label": self.label_text or self.name.replace("_", " ").title(),
            "priority": self.priority_value,
            "permissions": self.permissions,
            "confirmation": self.confirmation_value,
        }


class DeleteBulkAction(TableBulkAction):
    @classmethod
    def make(cls, name: str = "delete"):
        return cls(name=name, label_text="Delete", priority_value=1000).confirmation(
            "Delete selected items?",
            "This action cannot be undone.",
        )

    async def dispatch(self, db: AsyncSession, model: type, ids: list[Any]) -> BaseHttpResponse:
        if not ids:
            return BaseHttpResponse.make().set_error().set_message("No items selected.")
        primary_key = list(model.__table__.primary_key.columns)[0]
        result = await db.execute(delete(model).where(primary_key.in_(ids)))
        await db.commit()
        return BaseHttpResponse.make().set_data({"deleted": result.rowcount or 0}).with_deleted_success_message()


class UpdateBulkAction(TableBulkAction):
    def __init__(self, name: str = "update", values: dict[str, Any] | None = None):
        super().__init__(name=name, label_text="Update", priority_value=50)
        self.values = values or {}

    async def dispatch(self, db: AsyncSession, model: type, ids: list[Any]) -> BaseHttpResponse:
        primary_key = list(model.__table__.primary_key.columns)[0]
        result = await db.execute(update(model).where(primary_key.in_(ids)).values(**self.values))
        await db.commit()
        return BaseHttpResponse.make().set_data({"updated": result.rowcount or 0}).with_updated_success_message()
