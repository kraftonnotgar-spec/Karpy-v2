from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class TableFilter:
    key: str
    title: str
    type: str = "text"
    operators: list[str] = field(default_factory=lambda: ["=", "!=", "like"])
    options: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def make(cls, key: str, title: str | None = None):
        return cls(key=key, title=title or key.replace("_", " ").title())

    def type_as(self, value: str):
        self.type = value
        return self

    def choices(self, values: list[dict[str, Any]]):
        self.options = values
        return self

    def allowed_operators(self, values: list[str]):
        self.operators = values
        return self

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "title": self.title,
            "type": self.type,
            "operators": self.operators,
            "options": self.options,
        }
