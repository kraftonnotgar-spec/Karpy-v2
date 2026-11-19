"""Optional product fulfilment, registered and owned by the supplying plugin.

Payment owns no product models. Plugins register at boot and unregister at
shutdown. Callbacks must be idempotent and must not commit the supplied session:
the payment status and fulfilment transition share the caller's transaction.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

Checkout = Callable[[Any, Any, Any, str, str], Awaitable[dict[str, Any]]]
Transition = Callable[[Any, Any, str, str | None], Awaitable[None]]


@dataclass(frozen=True)
class FulfilmentExtension:
    owner: str
    checkout: Checkout
    transition: Transition


class FulfilmentRegistry:
    def __init__(self) -> None:
        self._extensions: dict[str, FulfilmentExtension] = {}

    def register(self, payment_type: str, extension: FulfilmentExtension) -> None:
        if not payment_type or not extension.owner:
            raise ValueError("Fulfilment type and owner are required")
        if payment_type in self._extensions:
            raise ValueError("Fulfilment capability is already registered")
        if not callable(extension.checkout) or not callable(extension.transition):
            raise TypeError("Fulfilment callbacks are required")
        self._extensions[payment_type] = extension

    def get(self, payment_type: str) -> FulfilmentExtension | None:
        return self._extensions.get(payment_type)

    def unregister(self, payment_type: str, *, owner: str) -> None:
        extension = self.get(payment_type)
        if extension and extension.owner != owner:
            raise ValueError("Fulfilment capability belongs to another plugin")
        self._extensions.pop(payment_type, None)


fulfilment_extensions = FulfilmentRegistry()
