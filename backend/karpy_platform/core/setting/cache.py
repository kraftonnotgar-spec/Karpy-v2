from __future__ import annotations

from typing import Any

from karpy_platform.core.support.cache_management import cache_management_service


def is_truthy(value: Any, default: bool = False) -> bool:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on", "enabled"}


def int_setting(values: dict[str, Any], key: str, default: int) -> int:
    try:
        return int(values.get(key) or default)
    except (TypeError, ValueError):
        return default


def cache_settings_payload(values: dict[str, Any]) -> dict[str, Any]:
    threshold_mb = int_setting(values, "cache_size_warning_threshold_mb", 50)
    status = cache_management_service.status()
    size_bytes = cache_management_service.cache_size()
    return {
        "settings": {
            "cacheAdminMenu": is_truthy(values.get("cache_admin_menu_enabled"), default=True),
            "cacheFrontMenu": is_truthy(values.get("cache_front_menu_enabled"), default=True),
            "cacheUserAvatar": is_truthy(values.get("cache_user_avatar_enabled"), default=True),
            "cacheShortcodes": is_truthy(values.get("shortcode_cache_enabled"), default=True),
            "cacheWidgets": is_truthy(values.get("widget_cache_enabled"), default=True),
            "cacheInstalledPlugins": is_truthy(values.get("cache_installed_plugins_enabled"), default=True),
            "cacheSitemap": is_truthy(values.get("sitemap_use_cache"), default=True),
        },
        "currentSizeBytes": size_bytes,
        "currentSize": cache_management_service.human_size(size_bytes),
        "warningThresholdMb": threshold_mb,
        "warningExceeded": size_bytes > threshold_mb * 1024 * 1024,
        "trackedGroups": status["summary"]["trackedGroups"],
        "trackedKeys": status["summary"]["trackedKeys"],
        "aliveKeys": status["summary"]["aliveKeys"],
        "secureDefaults": {
            "hashedKeys": True,
            "dynamicContentBypass": True,
            "formsBypassCache": True,
            "personalDataTtlSeconds": int_setting(values, "cache_personal_data_ttl", 300),
        },
    }


def validate_cache_settings(values: dict[str, Any]) -> dict[str, str]:
    errors: dict[str, str] = {}
    ranges = {
        "cache_default_ttl": (60, 86400, "Default cache TTL must be between 60 seconds and 1 day."),
        "cache_personal_data_ttl": (60, 3600, "Personal data cache TTL must be between 60 seconds and 1 hour."),
        "shortcode_cache_ttl": (60, 86400, "Shortcode cache duration must be between 60 seconds and 1 day."),
        "widget_cache_ttl": (60, 86400, "Widget cache duration must be between 60 seconds and 1 day."),
        "cache_sitemap_timeout_minutes": (1, 1440, "Sitemap cache timeout must be between 1 minute and 1 day."),
        "cache_size_warning_threshold_mb": (1, 10240, "Cache size warning threshold must be between 1 MB and 10240 MB."),
    }
    for key, (minimum, maximum, message) in ranges.items():
        if key not in values:
            continue
        try:
            number = int(values.get(key) or 0)
        except (TypeError, ValueError):
            errors[key] = "Must be a whole number."
            continue
        if number < minimum or number > maximum:
            errors[key] = message

    prefix = str(values.get("cache_key_prefix") or "").strip()
    if "cache_key_prefix" in values and prefix:
        if len(prefix) > 40:
            errors["cache_key_prefix"] = "Cache key prefix must not be longer than 40 characters."
        elif not all(char.isalnum() or char in {"_", "-", ":"} for char in prefix):
            errors["cache_key_prefix"] = "Cache key prefix may only contain letters, numbers, dashes, underscores, and colons."
    return errors


async def apply_runtime_cache_settings(values: dict[str, Any]) -> None:
    """Apply settings to in-memory engines that do not read from the database per render."""
    try:
        from karpy_platform.packages.shortcode.engine import shortcode_engine

        shortcode_engine.cache_enabled = is_truthy(values.get("shortcode_cache_enabled"), default=True)
        shortcode_engine.cache_ttl = int_setting(values, "shortcode_cache_ttl", 1800)
        shortcode_engine.performance_log_threshold = float(values.get("shortcode_performance_log_threshold") or 0.5)
    except Exception:
        pass
    try:
        from karpy_platform.packages.plugin_management.service import plugin_service

        plugin_service.cache_installed_plugins_enabled = is_truthy(values.get("cache_installed_plugins_enabled"), default=True)
        if not plugin_service.cache_installed_plugins_enabled:
            plugin_service.clear_installed_plugins_cache()
    except Exception:
        pass
