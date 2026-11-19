from __future__ import annotations

import json
import secrets
from html import escape
from typing import Any

from karpy_platform.core.chart.types import ChartTypes


class RawJs(str):
    """String marker for callback values that should render as JavaScript."""


class BaseChart:
    """Python port of Botble's Morris chart base class."""

    chart_type: ChartTypes = ChartTypes.LINE
    js_function_fields = {"hoverCallback", "formatter", "dateFormat", "xLabelFormat", "yLabelFormat"}

    def __init__(self, chart_type: ChartTypes | str | None = None) -> None:
        self.options: dict[str, Any] = {}
        self.use_inline_js = False
        self.element = f"{chart_type or self.chart_type}_{secrets.token_hex(6)}"
        if chart_type:
            self.chart_type = ChartTypes(chart_type)

    def set_element_id(self, element_id: str) -> "BaseChart":
        self.element = element_id
        return self

    def get_element_id(self) -> str:
        return self.element

    def set_use_inline_js(self, use_inline_js: bool) -> "BaseChart":
        self.use_inline_js = use_inline_js
        return self

    def is_use_inline_js(self) -> bool:
        return self.use_inline_js

    def set_option(self, key: str, value: Any) -> "BaseChart":
        self.options[key] = value
        return self

    def data(self, value: list[dict[str, Any]]) -> "BaseChart":
        return self.set_option("data", value)

    def labels(self, value: list[str]) -> "BaseChart":
        return self.set_option("labels", value)

    def xkey(self, value: str | list[str]) -> "BaseChart":
        return self.set_option("xkey", value)

    def ykeys(self, value: list[str]) -> "BaseChart":
        return self.set_option("ykeys", value)

    def to_array(self) -> dict[str, Any]:
        payload = {"element": self.element, **self.default_options(), **self.options}
        return {key: value for key, value in payload.items() if value not in (None, "", [], {})}

    def to_json(self) -> str:
        return _json_with_raw_js(self.to_array())

    def render_chart(self) -> str:
        element = escape(self.element, quote=True)
        return (
            f'<div id="{element}" style="width: 100%; display: block; min-height: 300px;"></div>\n'
            "<script>\n"
            "document.addEventListener('DOMContentLoaded', function () {\n"
            f"  Morris.{self.chart_type.value}({self.to_json()});\n"
            "});\n"
            "</script>"
        )

    def default_options(self) -> dict[str, Any]:
        return {}

    def __getattr__(self, name: str):
        def setter(value: Any) -> "BaseChart":
            if name in self.js_function_fields and isinstance(value, str) and value.strip().startswith("function"):
                value = RawJs(value)
            return self.set_option(name, value)

        return setter


def _json_with_raw_js(value: Any) -> str:
    raw_values: list[str] = []

    def normalize(item: Any) -> Any:
        if isinstance(item, RawJs):
            token = f"__RAW_JS_{len(raw_values)}__"
            raw_values.append(str(item))
            return token
        if isinstance(item, dict):
            return {key: normalize(val) for key, val in item.items()}
        if isinstance(item, list):
            return [normalize(val) for val in item]
        return item

    encoded = json.dumps(normalize(value), separators=(",", ":"))
    for index, raw in enumerate(raw_values):
        encoded = encoded.replace(f'"__RAW_JS_{index}__"', raw)
    return encoded
