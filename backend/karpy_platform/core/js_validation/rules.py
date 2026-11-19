from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


CLIENT_RULES = {
    "Accepted", "After", "Alpha", "AlphaDash", "AlphaNum", "Array", "Bail", "Before", "Between",
    "Boolean", "Confirmed", "Date", "Dimensions", "DateFormat", "Different", "Digits",
    "DigitsBetween", "Distinct", "Email", "File", "Filled", "Image", "In", "InArray", "Integer",
    "Ip", "Json", "Max", "Mimes", "Mimetypes", "Min", "NotIn", "Nullable", "Numeric", "Regex",
    "Required", "RequiredIf", "RequiredUnless", "RequiredWith", "RequiredWithAll", "RequiredWithout",
    "RequiredWithoutAll", "Same", "Size", "Sometimes", "String", "Timezone", "Url",
}
SERVER_RULES = {"ActiveUrl", "Exists", "Unique"}
FILE_RULES = {"File", "Image", "Mimes", "Mimetypes"}
DISABLE_RULE = "NoJsValidation"
REMOTE_RULE = "laravelValidationRemote"
JAVASCRIPT_RULE = "laravelValidation"
ASTERISK = "__asterisk__"


@dataclass(frozen=True)
class ParsedRule:
    name: str
    parameters: list[str]
    raw: str


def studly(value: str) -> str:
    return "".join(part.capitalize() for part in re.split(r"[_\-\s]+", value) if part)


def parse_rule(rule: str | Any) -> ParsedRule:
    if not isinstance(rule, str):
        return ParsedRule(studly(rule.__class__.__name__), [], str(rule))

    if ":" not in rule:
        return ParsedRule(studly(rule), [], rule)

    name, parameters = rule.split(":", 1)
    return ParsedRule(studly(name), _split_parameters(parameters), rule)


def explode_rules(rules: str | list[str] | tuple[str, ...]) -> list[str]:
    if isinstance(rules, str):
        return [part for part in rules.split("|") if part]
    return [str(rule) for rule in rules]


def attribute_html_name(attribute: str) -> str:
    attribute = attribute.replace(ASTERISK, "*")
    parts = attribute.split(".")
    if len(parts) == 1:
        return attribute
    return parts[0] + "".join(f"[{part}]" for part in parts[1:])


def parse_named_parameters(parameters: list[str]) -> dict[str, str | None]:
    parsed: dict[str, str | None] = {}
    for item in parameters:
        key, _, value = item.partition("=")
        parsed[key] = value or None
    return parsed


def is_remote_rule(rule: str) -> bool:
    return rule in SERVER_RULES or rule not in CLIENT_RULES


def is_disable_rule(rule: str) -> bool:
    return rule == DISABLE_RULE


def _split_parameters(parameters: str) -> list[str]:
    if parameters.startswith("/") and parameters.count("/") >= 2:
        return [parameters]
    return [part.strip() for part in parameters.split(",")]
