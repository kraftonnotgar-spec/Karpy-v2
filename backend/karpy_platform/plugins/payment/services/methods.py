"""Payment method registry.

Gateway plugins register themselves here at boot time. The payment settings
screen reads this registry, so the UI only shows real installed methods.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable
from copy import deepcopy
from karpy_platform.core.setting.store import dot_set


def method_settings(settings: dict[str, Any], key: str) -> dict[str, Any]:
    prefix = f"payment.methods.{key}.settings"
    stored = settings.get(prefix)
    values = deepcopy(stored) if isinstance(stored, dict) else {}
    # SettingStore saves dictionary leaves as dotted rows. Leaves override legacy JSON.
    for name, value in settings.items():
        if name.startswith(prefix + "."):
            dot_set(values, name[len(prefix) + 1:], value)
    return values


@dataclass(slots=True)
class PaymentMethodField:
    key: str
    label: str
    type: str = "text"
    placeholder: str = ""
    help: str = ""
    required: bool = False
    secret: bool = False
    options: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "type": self.type,
            "placeholder": self.placeholder,
            "help": self.help,
            "required": self.required,
            "secret": self.secret,
            "options": self.options,
        }


@dataclass(slots=True)
class PaymentMethod:
    key: str
    name: str
    description: str = ""
    logo: str = ""
    fields: list[PaymentMethodField] = field(default_factory=list)
    priority: int = 100
    enabled_by_default: bool = False
    source: str = "payment"
    setup_instructions: list[str] = field(default_factory=list)
    webhook_path: str = ""
    checkout_type: str = "online"
    required_credentials: list[str] = field(default_factory=list)

    def to_dict(self, settings: dict[str, Any] | None = None) -> dict[str, Any]:
        settings = settings or {}
        enabled_key = f"payment.methods.{self.key}.enabled"
        raw_enabled = settings.get(enabled_key)
        enabled = self.enabled_by_default if raw_enabled in {None, ""} else raw_enabled in {True, "1", 1, "true", "True"}
        values = method_settings(settings, self.key)
        return {
            "key": self.key,
            "name": self.name,
            "description": self.description,
            "logo": str(values.get("methodLogo") or self.logo),
            "fields": [field.to_dict() for field in self.fields],
            "priority": self.priority,
            "enabled": enabled,
            "source": self.source,
            "setupInstructions": self.setup_instructions,
            "webhookPath": self.webhook_path,
            "checkoutType": self.checkout_type,
            "settings": values,
        }


class PaymentMethodRegistry:
    """Runtime registry used by payment gateway plugins."""

    def __init__(self) -> None:
        self._methods: dict[str, PaymentMethod] = {}

    def register(
        self,
        key: str,
        *,
        name: str,
        description: str = "",
        logo: str = "",
        fields: list[PaymentMethodField | dict[str, Any]] | None = None,
        priority: int = 100,
        enabled_by_default: bool = False,
        source: str = "payment",
        setup_instructions: list[str] | None = None,
        webhook_path: str = "",
        checkout_type: str = "online",
        required_credentials: list[str] | None = None,
    ) -> PaymentMethod:
        normalized_key = key.strip().lower().replace(" ", "_")
        parsed_fields = [
            field if isinstance(field, PaymentMethodField) else PaymentMethodField(**field)
            for field in (fields or [])
        ]
        method = PaymentMethod(
            key=normalized_key,
            name=name,
            description=description,
            logo=logo,
            fields=parsed_fields,
            priority=priority,
            enabled_by_default=enabled_by_default,
            source=source,
            setup_instructions=list(setup_instructions or []),
            webhook_path=webhook_path,
            checkout_type=checkout_type,
            required_credentials=list(required_credentials or []),
        )
        self._methods[normalized_key] = method
        return method

    def unregister(self, key: str) -> None:
        self._methods.pop(key.strip().lower().replace(" ", "_"), None)

    def get(self, key: str) -> PaymentMethod | None:
        return self._methods.get(key.strip().lower().replace(" ", "_"))

    def all(self) -> list[PaymentMethod]:
        return sorted(self._methods.values(), key=lambda method: (method.priority, method.name.lower()))

    def keys(self) -> list[str]:
        return [method.key for method in self.all()]

    def clear(self) -> None:
        self._methods.clear()


payment_methods = PaymentMethodRegistry()


CheckoutHandler = Callable[[Any], Awaitable[dict[str, Any]]]


class CheckoutHandlerRegistry:
    """Provider-neutral checkout callbacks supplied by gateway plugins."""

    def __init__(self) -> None:
        self._handlers: dict[str, CheckoutHandler] = {}

    def register(self, key: str, handler: CheckoutHandler) -> None:
        self._handlers[key.strip().lower().replace(" ", "_")] = handler

    def unregister(self, key: str) -> None:
        self._handlers.pop(key.strip().lower().replace(" ", "_"), None)

    def get(self, key: str) -> CheckoutHandler | None:
        return self._handlers.get(key.strip().lower().replace(" ", "_"))

    def clear(self) -> None:
        self._handlers.clear()


checkout_handlers = CheckoutHandlerRegistry()


WebhookHandler = Callable[[Any, Any], Awaitable[dict[str, Any]]]


class WebhookHandlerRegistry:
    """Signed webhook callbacks supplied by active gateway plugins."""

    def __init__(self) -> None:
        self._handlers: dict[str, WebhookHandler] = {}

    def register(self, key: str, handler: WebhookHandler) -> None:
        self._handlers[key.strip().lower().replace(" ", "_")] = handler

    def unregister(self, key: str) -> None:
        self._handlers.pop(key.strip().lower().replace(" ", "_"), None)

    def get(self, key: str) -> WebhookHandler | None:
        return self._handlers.get(key.strip().lower().replace(" ", "_"))

    def clear(self) -> None:
        self._handlers.clear()


webhook_handlers = WebhookHandlerRegistry()
