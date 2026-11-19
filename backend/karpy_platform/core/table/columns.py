from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Callable

from karpy_platform.core.support.helpers import date_from_database, format_time


Formatter = Callable[[Any, Any], Any]


def get_row_value(row: Any, key: str, default: Any = None) -> Any:
    value = row
    for segment in key.split("."):
        if isinstance(value, dict):
            value = value.get(segment, default)
        else:
            value = getattr(value, segment, default)
        if value is default:
            return default
    return value


@dataclass
class Column:
    data: str
    name: str | None = None
    title_text: str | None = None
    type: str = "text"
    class_name: str = ""
    width_value: int | str | None = None
    orderable_value: bool = True
    searchable_value: bool = True
    visible_value: bool = True
    exportable_value: bool = True
    printable_value: bool = True
    responsive_priority_value: int | None = None
    align: str | None = None
    nowrap_value: bool = False
    copyable: bool = False
    empty_state: str = ""
    formatter: Formatter | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def make(cls, data: str, name: str = ""):
        return cls(data=data, name=name or data)

    def title(self, value: str):
        self.title_text = value
        return self

    def label(self, value: str):
        return self.title(value)

    def width(self, value: int | str):
        self.width_value = value
        return self

    def orderable(self, value: bool = True):
        self.orderable_value = value
        return self

    def searchable(self, value: bool = True):
        self.searchable_value = value
        return self

    def visible(self, value: bool = True):
        self.visible_value = value
        return self

    def hidden(self):
        return self.visible(False)

    def exportable(self, value: bool = True):
        self.exportable_value = value
        return self

    def printable(self, value: bool = True):
        self.printable_value = value
        return self

    def responsive_priority(self, value: int):
        self.responsive_priority_value = value
        return self

    def add_class(self, value: str):
        classes = set(filter(None, self.class_name.split()))
        classes.update(filter(None, value.split()))
        self.class_name = " ".join(sorted(classes))
        return self

    def remove_class(self, value: str):
        remove = set(value.split())
        self.class_name = " ".join(part for part in self.class_name.split() if part not in remove)
        return self

    def align_start(self):
        self.align = "start"
        return self

    def align_center(self):
        self.align = "center"
        return self

    def align_end(self):
        self.align = "end"
        return self

    def nowrap(self, value: bool = True):
        self.nowrap_value = value
        return self

    def column_visibility(self, value: bool = False):
        if value:
            return self.remove_class("no-column-visibility")
        return self.add_class("no-column-visibility")

    def with_empty_state(self, value: str = "-"):
        self.empty_state = value
        return self

    def format_using(self, formatter: Formatter):
        self.formatter = formatter
        return self

    def render(self, row: Any) -> Any:
        value = get_row_value(row, self.data)
        if (value is None or value == "") and self.empty_state:
            return self.empty_state
        if self.formatter:
            return self.formatter(value, row)
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, date):
            return value.isoformat()
        return value

    def to_dict(self) -> dict[str, Any]:
        return {
            "data": self.data,
            "name": self.name or self.data,
            "title": self.title_text or self.data.replace("_", " ").title(),
            "type": self.type,
            "className": self.class_name,
            "width": self.width_value,
            "orderable": self.orderable_value,
            "searchable": self.searchable_value,
            "visible": self.visible_value,
            "exportable": self.exportable_value,
            "printable": self.printable_value,
            "responsivePriority": self.responsive_priority_value,
            "align": self.align,
            "nowrap": self.nowrap_value,
            "copyable": self.copyable,
            "metadata": self.metadata,
        }


class CheckboxColumn(Column):
    @classmethod
    def make(cls, data: str = "id", name: str = "checkbox"):
        column = cls(data="checkbox", name=name, title_text="", type="checkbox")
        column.metadata["valueKey"] = data
        return column.orderable(False).searchable(False).width(24)


class IdColumn(Column):
    @classmethod
    def make(cls, data: str = "id", name: str = ""):
        return cls(data=data, name=name or data, title_text="ID").width(90).column_visibility()


class NameColumn(Column):
    @classmethod
    def make(cls, data: str = "name", name: str = ""):
        return cls(data=data, name=name or data, title_text="Name").align_start()


class EmailColumn(Column):
    @classmethod
    def make(cls, data: str = "email", name: str = ""):
        return cls(data=data, name=name or data, title_text="Email", type="email")


class PhoneColumn(Column):
    @classmethod
    def make(cls, data: str = "phone", name: str = ""):
        return cls(data=data, name=name or data, title_text="Phone", type="phone")


class DateColumn(Column):
    @classmethod
    def make(cls, data: str, name: str = ""):
        return cls(data=data, name=name or data, type="date").width(120).with_empty_state()

    def render(self, row: Any) -> Any:
        value = get_row_value(row, self.data)
        return date_from_database(value) if value else self.empty_state


class DateTimeColumn(Column):
    @classmethod
    def make(cls, data: str, name: str = ""):
        return cls(data=data, name=name or data, type="datetime").width(160).with_empty_state()

    def render(self, row: Any) -> Any:
        value = get_row_value(row, self.data)
        return format_time(value) if value else self.empty_state


class CreatedAtColumn(DateTimeColumn):
    @classmethod
    def make(cls, data: str = "created_at", name: str = ""):
        return cls(data=data, name=name or data, title_text="Created At", type="datetime").width(160).with_empty_state()


class UpdatedAtColumn(DateTimeColumn):
    @classmethod
    def make(cls, data: str = "updated_at", name: str = ""):
        return cls(data=data, name=name or data, title_text="Updated At", type="datetime").width(160).with_empty_state()


class YesNoColumn(Column):
    @classmethod
    def make(cls, data: str, name: str = ""):
        return cls(data=data, name=name or data, type="boolean").width(100).align_center()

    def render(self, row: Any) -> str:
        return "Yes" if bool(get_row_value(row, self.data)) else "No"


class StatusColumn(Column):
    @classmethod
    def make(cls, data: str = "status", name: str = ""):
        return cls(data=data, name=name or data, title_text="Status", type="status").width(120)


class ImageColumn(Column):
    @classmethod
    def make(cls, data: str = "image", name: str = ""):
        return cls(data=data, name=name or data, title_text="Image", type="image").width(80).orderable(False)


class RowActionsColumn(Column):
    @classmethod
    def make(cls, data: str = "rowActions", name: str = "rowActions"):
        return (
            cls(data=data, name=name, title_text="Operations", type="actions")
            .orderable(False)
            .searchable(False)
            .exportable(False)
            .printable(False)
            .responsive_priority(99)
            .align_center()
            .nowrap()
        )
