from __future__ import annotations

import secrets
from typing import Any

from karpy_platform.core.base.hooks import hooks
from karpy_platform.core.js_validation.parser import ValidationRuleParser
from karpy_platform.core.js_validation.validator import JavascriptValidator


DEFAULT_OPTIONS = {
    "view": "core/js-validation::bootstrap",
    "form_selector": "form",
    "focus_on_error": False,
    "duration_animate": 1000,
    "disable_remote_validation": False,
    "remote_validation_field": "_js_validation",
    "escape": False,
    "ignore": "",
}


class JsValidatorFactory:
    def __init__(self, options: dict[str, Any] | None = None) -> None:
        self.options = {**DEFAULT_OPTIONS, **(options or {})}

    def make(
        self,
        rules: dict[str, str | list[str]],
        messages: dict[str, str] | None = None,
        custom_attributes: dict[str, str] | None = None,
        selector: str | None = None,
    ) -> JavascriptValidator:
        parser = ValidationRuleParser(
            rules=rules,
            messages=messages or {},
            custom_attributes=custom_attributes or {},
            remote_token=self.get_session_token(),
            escape=bool(self.options.get("escape", False)),
        )
        return JavascriptValidator(
            parser=parser,
            selector_value=selector or self.options["form_selector"],
            view=self.options["view"],
            remote_enabled=not bool(self.options["disable_remote_validation"]),
            ignore_value=self.options.get("ignore"),
        )

    def form_request(self, form_request: Any, selector: str | None = None) -> JavascriptValidator:
        request = form_request() if isinstance(form_request, type) else form_request
        rules = request.rules() if hasattr(request, "rules") else getattr(request, "rules", {})
        messages = request.messages() if hasattr(request, "messages") else getattr(request, "messages", {})
        attributes = request.attributes() if hasattr(request, "attributes") else getattr(request, "attributes", {})

        rules = hooks.apply_filters("core_request_rules", rules, request)
        messages = hooks.apply_filters("core_request_messages", messages, request)
        attributes = hooks.apply_filters("core_request_attributes", attributes, request)

        return self.make(rules, messages, attributes, selector)

    def get_session_token(self) -> str:
        return secrets.token_urlsafe(32)


js_validator = JsValidatorFactory()
