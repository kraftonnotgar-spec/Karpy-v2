"""Lifecycle provider for configurable manual payments."""

import logging

from .gateway import register_gateway, unregister_gateway

logger = logging.getLogger("karpy.plugins.manual_payment")


class ManualPaymentPlugin:
    @staticmethod
    def activate() -> None:
        logger.info("Manual payment gateway activated")

    @staticmethod
    def boot() -> None:
        register_gateway()

    @staticmethod
    def deactivate() -> None:
        unregister_gateway()

    @staticmethod
    def remove() -> None:
        unregister_gateway()

    @staticmethod
    def uninstall() -> None:
        unregister_gateway()
