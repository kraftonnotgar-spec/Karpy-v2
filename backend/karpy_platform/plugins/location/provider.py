"""Service provider for the Location plugin."""

from __future__ import annotations

import importlib
import logging
from pathlib import Path

from fastapi import APIRouter

from .routes import router

logger = logging.getLogger("karpy.plugins.location")
PLUGIN_PACKAGE = "karpy_platform.plugins.location"
PLUGIN_PATH = Path(__file__).resolve().parent


class LocationPlugin:
    """Plugin lifecycle hooks loaded by KARPy's PluginService."""

    @staticmethod
    def activate() -> None:
        logger.info("Location plugin activated")

    @staticmethod
    def deactivate() -> None:
        logger.info("Location plugin deactivated")

    @staticmethod
    def remove() -> None:
        logger.info("Location plugin removed")

    @staticmethod
    def boot() -> None:
        logger.info("Location plugin booted")

    @staticmethod
    def install() -> None:
        logger.info("Location plugin install hook completed")

    @staticmethod
    def uninstall() -> None:
        logger.info("Location plugin uninstall hook completed")

    @staticmethod
    def get_model_modules() -> list[str]:
        return _discover_modules("models")

    @staticmethod
    def get_migration_modules() -> list[str]:
        return _discover_modules("database.migrations")

    @staticmethod
    def get_routes() -> APIRouter:
        return router

    @staticmethod
    def get_admin_menus() -> list[dict]:
        return [
            {
                "id": "locations",
                "name": "Locations",
                "icon": "globe-2",
                "url": "/admin/locations/countries",
                "priority": 57,
                "children": [
                    {
                        "id": "location-countries",
                        "name": "Countries",
                        "icon": "flag",
                        "url": "/admin/locations/countries",
                        "priority": 10,
                    },
                    {
                        "id": "location-states",
                        "name": "States",
                        "icon": "map",
                        "url": "/admin/locations/states",
                        "priority": 20,
                    },
                    {
                        "id": "location-cities",
                        "name": "Cities",
                        "icon": "map-pin",
                        "url": "/admin/locations/cities",
                        "priority": 30,
                    },
                    {
                        "id": "location-importer",
                        "name": "Location Importer",
                        "icon": "box",
                        "url": "/admin/locations/import",
                        "priority": 40,
                    },
                    {
                        "id": "location-exporter",
                        "name": "Location Exporter",
                        "icon": "box",
                        "url": "/admin/locations/export",
                        "priority": 50,
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

