"""Service provider for the AstraCall SMS adapter."""

from __future__ import annotations

import logging

from fastapi import APIRouter

from .routes import router

logger = logging.getLogger("karpy.plugins.astracall_sms")


class AstracallSmsPlugin:
    """Registers the AstraCall provider into the payment SMS provider registry."""

    @staticmethod
    def activate() -> None:
        logger.info("AstraCall SMS activated")

    @staticmethod
    def deactivate() -> None:
        _unregister()

    @staticmethod
    def remove() -> None:
        _unregister()

    @staticmethod
    def boot() -> None:
        from .adapter import register

        register()  # selected with the setting payment.notifications.sms.provider = "astracall"
        logger.info("AstraCall SMS booted")

    @staticmethod
    def install() -> None:
        logger.info("AstraCall SMS install hook completed")

    @staticmethod
    def uninstall() -> None:
        _unregister()

    @staticmethod
    def get_model_modules() -> list[str]:
        return []

    @staticmethod
    def get_migration_modules() -> list[str]:
        return []

    @staticmethod
    def get_routes() -> APIRouter:
        return router

    @staticmethod
    def get_admin_menus() -> list[dict]:
        return [
            {
                "id": "astracall-sms",
                "name": "SMS provider",
                "icon": "message-circle",
                "url": "/admin/settings/sms",
                "priority": 81,
                "children": [],
            }
        ]


def _unregister() -> None:
    from .adapter import unregister

    unregister()
