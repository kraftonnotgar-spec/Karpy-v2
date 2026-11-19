from __future__ import annotations

import importlib
from pathlib import Path

from fastapi import APIRouter

from .routes import router

PLUGIN_PACKAGE = "karpy_platform.plugins.auth"
PLUGIN_PATH = Path(__file__).resolve().parent


class AuthPlugin:
    @staticmethod
    def activate() -> None: pass
    @staticmethod
    def deactivate() -> None: pass
    @staticmethod
    def remove() -> None: pass
    @staticmethod
    def boot() -> None: pass
    @staticmethod
    def install() -> None: pass
    @staticmethod
    def uninstall() -> None: pass

    @staticmethod
    def get_routes() -> APIRouter:
        return router

    @staticmethod
    def get_model_modules() -> list[str]:
        module = f"{PLUGIN_PACKAGE}.models.auth"
        importlib.import_module(module)
        return [module]

    @staticmethod
    def get_migration_modules() -> list[str]:
        return []

    @staticmethod
    def get_admin_menus() -> list[dict]:
        return []
