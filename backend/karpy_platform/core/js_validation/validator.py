from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from karpy_platform.core.js_validation.parser import ValidationRuleParser


@dataclass
class JavascriptValidator:
    parser: ValidationRuleParser
    selector_value: str = "form"
    view: str = "core/js-validation::bootstrap"
    remote_enabled: bool = True
    ignore_value: str | None = ""

    def selector(self, selector: str | None) -> "JavascriptValidator":
        if selector:
            self.selector_value = selector
        return self

    def ignore(self, ignore: str | None) -> "JavascriptValidator":
        self.ignore_value = ignore
        return self

    def remote(self, enabled: bool = True) -> "JavascriptValidator":
        self.remote_enabled = enabled
        return self

    def sometimes(self, attribute: str, rules: str | list[str]) -> "JavascriptValidator":
        self.parser.add_conditional_rules(attribute, rules)
        return self

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "rules": self.parser.parse(include_remote=self.remote_enabled),
            "messages": {},
            "selector": self.selector_value,
        }
        if self.ignore_value is not None:
            data["ignore"] = self.ignore_value
        return data

    def render(self, selector: str | None = None) -> str:
        self.selector(selector)
        payload = json.dumps(self.to_dict(), separators=(",", ":"))
        return (
            "<script>\n"
            "(function(){\n"
            f"  window.KARPyJsValidation = window.KARPyJsValidation || [];\n"
            f"  window.KARPyJsValidation.push({payload});\n"
            "})();\n"
            "</script>"
        )
