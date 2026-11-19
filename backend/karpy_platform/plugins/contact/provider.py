"""Service provider for the Contact plugin."""

from __future__ import annotations

import importlib
import logging
from pathlib import Path

from fastapi import APIRouter

from .routes import router

logger = logging.getLogger("karpy.plugins.contact")
PLUGIN_PACKAGE = "karpy_platform.plugins.contact"
PLUGIN_PATH = Path(__file__).resolve().parent


class ContactPlugin:
    """Plugin lifecycle hooks loaded by KARPy's PluginService."""

    @staticmethod
    def activate() -> None:
        logger.info("Contact plugin activated")

    @staticmethod
    def deactivate() -> None:
        logger.info("Contact plugin deactivated")

    @staticmethod
    def remove() -> None:
        logger.info("Contact plugin removed")

    @staticmethod
    def boot() -> None:
        """Register contact shortcodes and plugin services."""
        try:
            from karpy_platform.packages.shortcode.engine import shortcode_engine
            from karpy_platform.plugins.contact.shortcodes import render_contact_shortcode, contact_shortcode_config

            shortcode_engine.register(
                "contact-form",
                "Contact form",
                "Render the public contact form with Botble-style custom fields.",
                callback=render_contact_shortcode,
                admin_config=contact_shortcode_config,
                category="Forms",
                fields=[
                    {
                        "key": "display_fields",
                        "label": "Display fields",
                        "type": "checklist",
                        "default": ["phone", "email", "subject", "address"],
                        "description": "Choose optional contact fields shown beside the always-required Name and Message fields.",
                        "options": [
                            {"value": "phone", "label": "Phone"},
                            {"value": "email", "label": "Email"},
                            {"value": "subject", "label": "Subject"},
                            {"value": "address", "label": "Address"},
                        ],
                    },
                    {
                        "key": "mandatory_fields",
                        "label": "Mandatory fields",
                        "type": "checklist",
                        "default": ["email"],
                        "description": "If left blank, these fields will be validated by default configuration. Name and Message are always mandatory.",
                        "options": [
                            {"value": "phone", "label": "Phone"},
                            {"value": "email", "label": "Email"},
                            {"value": "subject", "label": "Subject"},
                            {"value": "address", "label": "Address"},
                        ],
                    },
                    {"key": "show_information_box", "label": "Show information box", "type": "switch", "default": "yes"},
                    {"key": "information_box_title", "label": "Information box title", "type": "text", "default": "Contact Us"},
                    {"key": "show_social_links", "label": "Show social links", "type": "switch", "default": "yes"},
                ],
            )
        except Exception as exc:
            logger.warning("Could not register contact shortcode: %s", exc)
        logger.info("Contact plugin booted")

    @staticmethod
    def install() -> None:
        """Run install tasks after activation. Keep table definitions in models/."""
        logger.info("Contact plugin install hook completed")

    @staticmethod
    def uninstall() -> None:
        """Run cleanup tasks when a plugin is permanently removed."""
        logger.info("Contact plugin uninstall hook completed")

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
                "id": "contact",
                "name": "Contact",
                "icon": "mail",
                "url": "/admin/contacts",
                "priority": 58,
                "children": [
                    {
                        "id": "contact-submissions",
                        "name": "Contacts",
                        "icon": "box",
                        "url": "/admin/contacts",
                        "priority": 10,
                    },
                    {
                        "id": "contact-custom-fields",
                        "name": "Custom Fields",
                        "icon": "box-plus",
                        "url": "/admin/contacts/custom-fields",
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
