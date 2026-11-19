"""Service provider for the Payment plugin."""

from __future__ import annotations

import importlib
import logging
from pathlib import Path

from fastapi import APIRouter

from .public_routes import router as public_router
from .routes import router as admin_router

logger = logging.getLogger("karpy.plugins.payment")
PLUGIN_PACKAGE = "karpy_platform.plugins.payment"
PLUGIN_PATH = Path(__file__).resolve().parent


class PaymentPlugin:
    """Plugin lifecycle hooks loaded by KARPy's PluginService."""

    @staticmethod
    def activate() -> None:
        logger.info("Payment plugin activated")

    @staticmethod
    def deactivate() -> None:
        logger.info("Payment plugin deactivated")

    @staticmethod
    def remove() -> None:
        logger.info("Payment plugin removed")

    @staticmethod
    def boot() -> None:
        """Boot only the provider-neutral transaction and method registry."""
        logger.info("Payment engine booted; waiting for active gateway plugins")

    @staticmethod
    def install() -> None:
        """Run install tasks after activation. Keep table definitions in models/."""
        logger.info("Payment plugin install hook completed")

    @staticmethod
    def uninstall() -> None:
        """Run cleanup tasks when a plugin is permanently removed."""
        logger.info("Payment plugin uninstall hook completed")

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
        router = APIRouter()
        router.include_router(public_router)
        router.include_router(admin_router)
        return router

    @staticmethod
    def get_admin_menus() -> list[dict]:
        return [
            {
                "id": "payments",
                "name": "Payments",
                "icon": "credit-card",
                "url": "/admin/payments/transactions",
                "priority": 62,
                "children": [
                    {
                        "id": "payment-transactions",
                        "name": "Transactions",
                        "icon": "list",
                        "url": "/admin/payments/transactions",
                        "priority": 10,
                    },
                    {
                        "id": "payment-logs",
                        "name": "Payment Logs",
                        "icon": "file-text",
                        "url": "/admin/payments/logs",
                        "priority": 20,
                    },
                    {
                        "id": "payment-methods",
                        "name": "Payment methods",
                        "icon": "settings",
                        "url": "/admin/payments/methods",
                        "priority": 30,
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
