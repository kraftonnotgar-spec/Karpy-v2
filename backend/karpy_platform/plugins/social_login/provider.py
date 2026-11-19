"""Service provider for the Social Login plugin."""

from __future__ import annotations

import importlib
import logging
from pathlib import Path

from fastapi import APIRouter

from .routes import router

logger = logging.getLogger("karpy.plugins.social_login")
PLUGIN_PACKAGE = "karpy_platform.plugins.social_login"
PLUGIN_PATH = Path(__file__).resolve().parent


class SocialLoginPlugin:
    """Plugin lifecycle hooks loaded by KARPy's PluginService."""

    @staticmethod
    def activate() -> None:
        logger.info("Social Login plugin activated")

    @staticmethod
    def deactivate() -> None:
        logger.info("Social Login plugin deactivated")

    @staticmethod
    def remove() -> None:
        logger.info("Social Login plugin removed")

    @staticmethod
    def boot() -> None:
        """Register the provider registry and OAuth services."""
        logger.info("Social Login plugin booted")

    @staticmethod
    def install() -> None:
        """Run install tasks after activation. Keep table definitions in models/."""
        logger.info("Social Login plugin install hook completed")

    @staticmethod
    def uninstall() -> None:
        """Run cleanup tasks when a plugin is permanently removed."""
        logger.info("Social Login plugin uninstall hook completed")

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
        # Social login is configured under Settings -> Others, like Botble.
        return []


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
