from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from karpy_platform.core.js_validation.messages import build_message
from karpy_platform.core.js_validation.rules import (
    JAVASCRIPT_RULE,
    REMOTE_RULE,
    attribute_html_name,
    explode_rules,
    is_disable_rule,
    is_remote_rule,
    parse_named_parameters,
    parse_rule,
)


@dataclass
class ValidationRuleParser:
    rules: dict[str, str | list[str]]
    messages: dict[str, str] = field(default_factory=dict)
    custom_attributes: dict[str, str] = field(default_factory=dict)
    remote_token: str | None = None
    escape: bool = False
    conditional: dict[str, list[str]] = field(default_factory=dict)

    def add_conditional_rules(self, attribute: str, rules: str | list[str]) -> None:
        current = self.conditional.setdefault(attribute, [])
        current.extend(explode_rules(rules))

    def parse(self, include_remote: bool = True) -> dict[str, dict[str, list[list[Any]]]]:
        js_rules: dict[str, dict[str, list[list[Any]]]] = {}

        for attribute, raw_rules in self.rules.items():
            rules = explode_rules(raw_rules)
            if any(is_disable_rule(parse_rule(rule).name) for rule in rules):
                continue

            for raw_rule in rules:
                parsed = parse_rule(raw_rule)
                if is_disable_rule(parsed.name):
                    continue

                js_attribute, js_rule, parameters = self.get_rule(attribute, parsed.name, parsed.parameters, raw_rule)
                if js_rule == REMOTE_RULE and not include_remote:
                    continue

                message = build_message(
                    attribute,
                    parsed.name,
                    parsed.parameters,
                    self.messages,
                    self.custom_attributes,
                    escape=self.escape,
                )
                js_rules.setdefault(js_attribute, {}).setdefault(js_rule, []).append(
                    [parsed.name, parameters, message, self.is_implicit(parsed.name)]
                )

        return js_rules

    def get_rule(self, attribute: str, rule: str, parameters: list[str], raw_rule: str) -> tuple[str, str, Any]:
        force_remote = raw_rule in self.conditional.get(attribute, [])
        if force_remote or is_remote_rule(rule):
            return attribute_html_name(attribute), REMOTE_RULE, [attribute_html_name(attribute), self.remote_token, force_remote]

        attribute, parameters = self.client_rule(attribute, rule, parameters)
        return attribute_html_name(attribute), JAVASCRIPT_RULE, parameters

    def client_rule(self, attribute: str, rule: str, parameters: list[str]) -> tuple[str, Any]:
        if rule == "Confirmed":
            return f"{attribute}_confirmation", [attribute_html_name(attribute)]
        if rule in {"Before", "After"}:
            return attribute, [parameters[0]] if parameters else []
        if rule in {"Different", "Same"} and parameters:
            return attribute, [attribute_html_name(parameters[0])]
        if rule in {"RequiredWith", "RequiredWithAll", "RequiredWithout", "RequiredWithoutAll"}:
            return attribute, [attribute_html_name(item) for item in parameters]
        if rule in {"RequiredIf", "RequiredUnless", "InArray"} and parameters:
            return attribute, [attribute_html_name(parameters[0]), *parameters[1:]]
        if rule == "Dimensions":
            return attribute, parse_named_parameters(parameters)
        if rule == "Distinct":
            return attribute, [attribute_html_name(attribute), *parameters]
        return attribute, parameters

    @staticmethod
    def is_implicit(rule: str) -> bool:
        return rule in {
            "Accepted",
            "Filled",
            "Required",
            "RequiredIf",
            "RequiredUnless",
            "RequiredWith",
            "RequiredWithAll",
            "RequiredWithout",
            "RequiredWithoutAll",
        }
