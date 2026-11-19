"""Service provider for the Speed plugin."""

from __future__ import annotations

import importlib
import logging
from pathlib import Path

from fastapi import APIRouter

from .routes import router

logger = logging.getLogger("karpy.plugins.speed")
PLUGIN_PACKAGE = "karpy_platform.plugins.speed"
PLUGIN_PATH = Path(__file__).resolve().parent


class SpeedPlugin:
    """Plugin lifecycle hooks loaded by KARPy's PluginService."""

    @staticmethod
    def activate() -> None:
        logger.info("Speed plugin activated")

    @staticmethod
    def deactivate() -> None:
        logger.info("Speed plugin deactivated")

    @staticmethod
    def remove() -> None:
        logger.info("Speed plugin removed")

    @staticmethod
    def boot() -> None:
        """Register hooks, shortcodes, widgets, settings, and services here."""
        logger.info("Speed plugin booted")

    @staticmethod
    def install() -> None:
        """Run install tasks after activation. Keep table definitions in models/."""
        logger.info("Speed plugin install hook completed")

    @staticmethod
    def uninstall() -> None:
        """Run cleanup tasks when a plugin is permanently removed."""
        logger.info("Speed plugin uninstall hook completed")

    @staticmethod
    def get_model_modules() -> list[str]:
        """Return plugin model modules so SQLAlchemy can create plugin tables."""
        return _discover_modules("models")

    @staticmethod
    def get_migration_modules() -> list[str]:
        """Return migration modules for future Alembic/plugin migration execution."""
        return _discover_modules("database.migrations")

    @staticmethod
    def get_routes() -> APIRouter:
        return router

    @staticmethod
    def get_admin_menus() -> list[dict]:
        return [
            {
                "id": "speed",
                "name": "Speed",
                "icon": "rocket",
                "url": "/admin/plugins/speed",
                "priority": 120,
                "children": [
                    {
                        "id": "speed-dashboard",
                        "name": "Dashboard",
                        "url": "/admin/plugins/speed",
                        "priority": 10,
                    },
                    {
                        "id": "speed-rate-limits",
                        "name": "Rate Limits",
                        "url": "/admin/plugins/speed/rate-limits",
                        "priority": 20,
                    },
                    {
                        "id": "speed-blocked-traffic",
                        "name": "Blocked Traffic",
                        "url": "/admin/plugins/speed/blocked-traffic",
                        "priority": 30,
                    },
                    {
                        "id": "speed-security-monitor",
                        "name": "Security Monitor",
                        "url": "/admin/plugins/speed/security-monitor",
                        "priority": 40,
                    },
                ],
            }
        ]


def _discover_modules(folder: str) -> list[str]:
    path = PLUGIN_PATH.joinpath(*folder.split("."))
    if not path.exists():
        return []
    modules = []
    for file in sorted(path.glob("*.py")):
        if file.name.startswith("_"):
            continue
        module = f"{PLUGIN_PACKAGE}.{folder}.{file.stem}"
        importlib.import_module(module)
        modules.append(module)
    return modules
