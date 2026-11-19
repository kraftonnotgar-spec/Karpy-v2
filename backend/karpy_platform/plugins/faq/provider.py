"""Service provider for the Faq plugin."""

from __future__ import annotations

import importlib
import logging
from pathlib import Path

from fastapi import APIRouter

from .routes import router

logger = logging.getLogger("karpy.plugins.faq")
PLUGIN_PACKAGE = "karpy_platform.plugins.faq"
PLUGIN_PATH = Path(__file__).resolve().parent


class FaqPlugin:
    """Plugin lifecycle hooks loaded by KARPy's PluginService."""

    @staticmethod
    def activate() -> None:
        logger.info("Faq plugin activated")

    @staticmethod
    def deactivate() -> None:
        logger.info("Faq plugin deactivated")

    @staticmethod
    def remove() -> None:
        logger.info("Faq plugin removed")

    @staticmethod
    def boot() -> None:
        """Register FAQ shortcodes and plugin services."""
        try:
            from karpy_platform.packages.shortcode.engine import shortcode_engine
            from karpy_platform.plugins.faq.shortcodes import faq_shortcode_config, render_faq_shortcode

            shortcode_engine.register(
                "faq",
                "FAQs",
                "Render published frequently asked questions from the FAQ plugin.",
                callback=render_faq_shortcode,
                admin_config=faq_shortcode_config,
                category="Content",
                fields=[
                    {"key": "title", "label": "Title", "type": "text", "default": "Frequently Asked Questions"},
                    {"key": "subtitle", "label": "Subtitle", "type": "textarea", "default": ""},
                    {"key": "category", "label": "Category", "type": "text", "default": ""},
                    {
                        "key": "style",
                        "label": "Style",
                        "type": "select",
                        "default": "accordion",
                        "options": [{"value": "accordion", "label": "Accordion"}, {"value": "grid", "label": "Grid"}],
                    },
                    {"key": "limit", "label": "Limit", "type": "number", "default": "10"},
                    {"key": "open_first", "label": "Open first question", "type": "switch", "default": "yes"},
                ],
            )
        except Exception as exc:
            logger.warning("Could not register FAQ shortcode: %s", exc)
        logger.info("Faq plugin booted")

    @staticmethod
    def install() -> None:
        """Run install tasks after activation. Keep table definitions in models/."""
        logger.info("Faq plugin install hook completed")

    @staticmethod
    def uninstall() -> None:
        """Run cleanup tasks when a plugin is permanently removed."""
        logger.info("Faq plugin uninstall hook completed")

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
                "id": "faq",
                "name": "FAQs",
                "icon": "circle-help",
                "url": "/admin/faqs",
                "priority": 59,
                "children": [
                    {
                        "id": "faq-list",
                        "name": "FAQs",
                        "icon": "list-check",
                        "url": "/admin/faqs",
                        "priority": 10,
                    },
                    {
                        "id": "faq-categories",
                        "name": "Categories",
                        "icon": "folder",
                        "url": "/admin/faqs/categories",
                        "priority": 20,
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
