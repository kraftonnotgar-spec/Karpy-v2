from __future__ import annotations

from datetime import date, datetime
from typing import Any


class FieldFormatter:
    """Formats revision values using Botble-like per-field format rules."""

    @classmethod
    def format(cls, key: str, value: Any, formats: dict[str, str] | None = None) -> str | None:
        if value is None:
            return None

        rule = (formats or {}).get(key)
        if not rule:
            return cls.stringify(value)

        method, _, argument = rule.partition(":")
        formatter = getattr(cls, method, None)
        if not formatter:
            return cls.stringify(value)
        return formatter(value, argument)

    @staticmethod
    def stringify(value: Any) -> str:
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, date):
            return value.isoformat()
        if isinstance(value, bool):
            return "1" if value else "0"
        return str(value)

    @staticmethod
    def bool(value: Any, _: str = "") -> str:
        return "Yes" if str(value).lower() in {"1", "true", "yes", "published"} else "No"

    @staticmethod
    def status(value: Any, _: str = "") -> str:
        return str(value).replace("_", " ").title()

    @staticmethod
    def datetime(value: Any, fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
        if isinstance(value, datetime):
            return value.strftime(fmt or "%Y-%m-%d %H:%M:%S")
        return str(value)
