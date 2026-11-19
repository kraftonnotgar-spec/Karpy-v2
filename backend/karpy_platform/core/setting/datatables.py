from __future__ import annotations

from typing import Any


def is_truthy(value: Any, default: bool = False) -> bool:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on", "enabled"}


def datatables_settings_payload(values: dict[str, Any]) -> dict[str, Any]:
    pagination_type = str(values.get("datatables_pagination_type") or "default").strip() or "default"
    if pagination_type not in {"default", "dropdown"}:
        pagination_type = "default"

    return {
        "paginationType": pagination_type,
        "showColumnVisibility": is_truthy(values.get("datatables_default_show_column_visibility"), default=False),
        "showExportButton": is_truthy(values.get("datatables_default_show_export_button"), default=False),
        "enableResponsive": is_truthy(values.get("datatables_default_enable_responsive"), default=True),
        "serverSide": True,
        "exportFormats": ["csv", "json"],
        "automationReady": True,
        "automationNote": "Tables expose predictable JSON schemas and export-friendly columns for API, Zapier, n8n, and WhatsApp automation flows.",
    }


def validate_datatables_settings(values: dict[str, Any]) -> dict[str, str]:
    errors: dict[str, str] = {}
    if "datatables_pagination_type" in values:
        pagination_type = str(values.get("datatables_pagination_type") or "default")
        if pagination_type not in {"default", "dropdown"}:
            errors["datatables_pagination_type"] = "Pagination type must be Default or Dropdown."
    for key in (
        "datatables_default_show_column_visibility",
        "datatables_default_show_export_button",
        "datatables_default_enable_responsive",
    ):
        if key not in values:
            continue
        value = values.get(key)
        if isinstance(value, bool):
            continue
        if str(value).lower() not in {"0", "1", "true", "false", "yes", "no", "on", "off", ""}:
            errors[key] = "Must be enabled or disabled."
    return errors
