"""Per-event, per-channel notification templates with sensible neutral defaults.

Short text is used for the in-app feed and SMS; a fuller subject/body is used for
email. Admins can override any string in the setting store under
``payment.notifications.templates.<event>.<field>`` without touching code.
"""

from __future__ import annotations

import html
from typing import Any

from .events import EVENT_FAILED, EVENT_ORDER_CREATED, EVENT_RECEIVED, NotificationContext


class _SafeDict(dict):
    def __missing__(self, key: str) -> str:  # keep unknown placeholders literal
        return "{" + key + "}"


# Each event ships a title (in-app heading), a short line (in-app body + SMS), an
# email subject, and an email body. Placeholders are the context variables.
DEFAULT_TEMPLATES: dict[str, dict[str, str]] = {
    EVENT_RECEIVED: {
        "title": "Payment received",
        "short": "Payment of {amount} received from {customer} (ref {reference}).",
        "subject": "Payment received: {amount}",
        "body": (
            "<p>A payment has been received.</p>"
            "<ul>"
            "<li><strong>Amount:</strong> {amount}</li>"
            "<li><strong>Reference:</strong> {reference}</li>"
            "<li><strong>Customer:</strong> {customer}</li>"
            "<li><strong>Status:</strong> {status}</li>"
            "<li><strong>Time:</strong> {timestamp}</li>"
            "</ul>"
        ),
    },
    EVENT_FAILED: {
        "title": "Payment failed",
        "short": "Payment of {amount} from {customer} failed (ref {reference}).",
        "subject": "Payment failed: {amount}",
        "body": (
            "<p>A payment attempt has failed.</p>"
            "<ul>"
            "<li><strong>Amount:</strong> {amount}</li>"
            "<li><strong>Reference:</strong> {reference}</li>"
            "<li><strong>Customer:</strong> {customer}</li>"
            "<li><strong>Status:</strong> {status}</li>"
            "<li><strong>Time:</strong> {timestamp}</li>"
            "</ul>"
        ),
    },
    EVENT_ORDER_CREATED: {
        "title": "New order",
        "short": "New order for {amount} from {customer} (ref {reference}).",
        "subject": "New order: {amount}",
        "body": (
            "<p>A new order/checkout has been created.</p>"
            "<ul>"
            "<li><strong>Amount:</strong> {amount}</li>"
            "<li><strong>Reference:</strong> {reference}</li>"
            "<li><strong>Customer:</strong> {customer}</li>"
            "<li><strong>Status:</strong> {status}</li>"
            "<li><strong>Time:</strong> {timestamp}</li>"
            "</ul>"
        ),
    },
}


def _template_field(event: str, field: str, values: dict[str, Any]) -> str:
    override = values.get(f"payment.notifications.templates.{event}.{field}")
    if override not in (None, ""):
        return str(override)
    return DEFAULT_TEMPLATES.get(event, {}).get(field, "")


def _render(template: str, variables: dict[str, Any]) -> str:
    try:
        return template.format_map(_SafeDict(variables))
    except (ValueError, IndexError):
        # A malformed override (e.g. stray braces) must never break delivery.
        return template


def render_title(event: str, context: NotificationContext, values: dict[str, Any]) -> str:
    return _render(_template_field(event, "title", values), context.variables)


def render_short(event: str, context: NotificationContext, values: dict[str, Any]) -> str:
    """Short line for the in-app feed and SMS."""
    return _render(_template_field(event, "short", values), context.variables)


def render_email(event: str, context: NotificationContext, values: dict[str, Any]) -> tuple[str, str, str]:
    """Return ``(subject, html_body, text_body)`` for the email channel."""
    subject = _render(_template_field(event, "subject", values), context.variables)
    body = _render(_template_field(event, "body", values), context.variables)
    text = render_short(event, context, values)
    if "<" not in body:
        body = f"<p>{html.escape(body)}</p>"
    return subject, body, text
