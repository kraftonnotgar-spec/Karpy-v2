from __future__ import annotations

from karpy_platform.core.base.hooks import hooks
from karpy_platform.core.dashboard.constants import DASHBOARD_FILTER_ADMIN_NOTIFICATIONS
from karpy_platform.core.setting.registry import SettingField, SettingSection, setting_panel_registry
from karpy_platform.packages.shortcode.engine import shortcode_engine


class ShortcodeService:
    def __init__(self) -> None:
        self._booted = False

    def boot(self) -> None:
        if self._booted:
            return
        shortcode_engine.enable()
        setting_panel_registry.register_section(
            SettingSection(
                id="shortcode",
                title="Shortcode",
                description="Editor block rendering, lazy loading, and shortcode cache controls.",
                icon="brackets",
                route="/admin/settings/shortcode",
                priority=45,
                group="settings.others",
                source="package:shortcode",
                hidden=True,
                fields=[
                    SettingField("shortcode_cache_enabled", "Enable shortcode cache", type="switch", default="0"),
                    SettingField("shortcode_cache_ttl", "Shortcode cache TTL", type="number", default="1800"),
                    SettingField("shortcode_performance_log_threshold", "Slow shortcode threshold", type="number", default="0.5"),
                ],
            )
        )
        hooks.add_filter(DASHBOARD_FILTER_ADMIN_NOTIFICATIONS, self._cache_notification, priority=5)
        self._booted = True

    def _cache_notification(self, notifications: list[dict], widget_data=None, db=None) -> list[dict]:
        notifications.append(
            {
                "id": "shortcode-cache-suggestion",
                "type": "info",
                "title": "Shortcode cache",
                "message": "Enable shortcode cache after the frontend blocks are stable.",
                "action": {"label": "Shortcode settings", "url": "/admin/settings/shortcode"},
            }
        )
        return notifications


shortcode_service = ShortcodeService()


def boot_shortcode_package() -> None:
    shortcode_service.boot()
