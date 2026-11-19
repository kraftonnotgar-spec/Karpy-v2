from __future__ import annotations

import html
from typing import Any


DEFAULT_MESSAGES = {
    "Accepted": "The :attribute must be accepted.",
    "After": "The :attribute must be a date after :date.",
    "Alpha": "The :attribute may only contain letters.",
    "AlphaDash": "The :attribute may only contain letters, numbers, dashes and underscores.",
    "AlphaNum": "The :attribute may only contain letters and numbers.",
    "Before": "The :attribute must be a date before :date.",
    "Between": "The :attribute must be between :min and :max.",
    "Boolean": "The :attribute field must be true or false.",
    "Confirmed": "The :attribute confirmation does not match.",
    "Date": "The :attribute is not a valid date.",
    "Different": "The :attribute and :other must be different.",
    "Digits": "The :attribute must be :digits digits.",
    "DigitsBetween": "The :attribute must be between :min and :max digits.",
    "Email": "The :attribute must be a valid email address.",
    "Image": "The :attribute must be an image.",
    "In": "The selected :attribute is invalid.",
    "Integer": "The :attribute must be an integer.",
    "Max": "The :attribute may not be greater than :max.",
    "Mimes": "The :attribute must be a file of type: :values.",
    "Min": "The :attribute must be at least :min.",
    "Numeric": "The :attribute must be a number.",
    "Regex": "The :attribute format is invalid.",
    "Required": "The :attribute field is required.",
    "RequiredIf": "The :attribute field is required when :other is :value.",
    "RequiredWith": "The :attribute field is required when :values is present.",
    "Same": "The :attribute and :other must match.",
    "Size": "The :attribute must be :size.",
    "String": "The :attribute must be a string.",
    "Url": "The :attribute format is invalid.",
}


def build_message(
    attribute: str,
    rule: str,
    parameters: list[str],
    messages: dict[str, str] | None = None,
    attributes: dict[str, str] | None = None,
    escape: bool = False,
) -> str:
    messages = messages or {}
    attributes = attributes or {}
    key = f"{attribute}.{rule.lower()}"
    template = messages.get(key) or messages.get(rule) or messages.get(rule.lower()) or DEFAULT_MESSAGES.get(rule)
    template = template or f"The :attribute field failed {rule} validation."
    label = attributes.get(attribute, attribute.replace("_", " "))
    replacements: dict[str, Any] = {
        ":attribute": label,
        ":date": parameters[0] if parameters else "",
        ":digits": parameters[0] if parameters else "",
        ":min": parameters[0] if parameters else "",
        ":max": parameters[1] if len(parameters) > 1 else "",
        ":other": parameters[0] if parameters else "",
        ":value": parameters[1] if len(parameters) > 1 else "",
        ":values": ", ".join(parameters),
        ":size": parameters[0] if parameters else "",
    }
    message = template
    for placeholder, value in replacements.items():
        message = message.replace(placeholder, str(value))
    return html.escape(message) if escape else message
