"""Pluggable SMS provider interface for payment notifications.

The payment plugin ships no vendor. A real provider (any SMS gateway) is dropped
in by another plugin that registers it through the ``payment.notifications.sms_provider``
filter (Botble-style hook) or the local ``sms_provider_registry``. Until then the
default :class:`LogSmsProvider` records messages without any network call, so the
feature is safe to enable in development and tests.
"""

from __future__ import annotations

import abc
import logging
from dataclasses import dataclass
from typing import Any

from karpy_platform.core.base.hooks import hooks

logger = logging.getLogger("karpy.plugins.payment.notifications.sms")

# Filter hook a vendor plugin uses to supply a provider instance:
#   hooks.add_filter(SMS_PROVIDER_FILTER, lambda provider, db, values: MyProvider(...))
SMS_PROVIDER_FILTER = "payment.notifications.sms_provider"

DEFAULT_SMS_PROVIDER = "log"


@dataclass(slots=True)
class SmsResult:
    """Outcome of one SMS send, shaped like the auth plugin's SMS client result."""

    provider: str
    to: str
    status: str = "logged"
    sent: bool = False
    test: bool = True


class SmsProvider(abc.ABC):
    """Abstract SMS sender. Implementations must not block the event loop for long."""

    #: Short machine name used to select the provider by config.
    name: str = "abstract"

    #: Credential keys (in the setting store) a real provider needs before it can send.
    required_credentials: tuple[str, ...] = ()

    @abc.abstractmethod
    async def send(self, to: str, message: str, *, reference: str | None = None) -> SmsResult:
        """Deliver ``message`` to ``to`` and return an :class:`SmsResult`."""
        raise NotImplementedError

    def is_configured(self, values: dict[str, Any]) -> bool:
        return all(values.get(key) for key in self.required_credentials)


class LogSmsProvider(SmsProvider):
    """Default no-network provider: records the message and reports it as simulated."""

    name = DEFAULT_SMS_PROVIDER

    async def send(self, to: str, message: str, *, reference: str | None = None) -> SmsResult:
        logger.info("payment notification SMS (stub) to %s ref=%s: %s", to, reference or "-", message)
        return SmsResult(provider=self.name, to=to, status="logged", sent=False, test=True)


class SmsProviderRegistry:
    """Local registry so a provider can be registered without the hook system too."""

    def __init__(self) -> None:
        self._providers: dict[str, SmsProvider] = {}

    def register(self, provider: SmsProvider) -> None:
        if not getattr(provider, "name", ""):
            raise ValueError("SMS provider requires a name")
        self._providers[provider.name] = provider

    def unregister(self, name: str) -> None:
        self._providers.pop(name, None)

    def get(self, name: str) -> SmsProvider | None:
        return self._providers.get(name)


sms_provider_registry = SmsProviderRegistry()
sms_provider_registry.register(LogSmsProvider())


async def resolve_sms_provider(db: Any, values: dict[str, Any]) -> SmsProvider:
    """Pick the configured provider, falling back to the safe no-network stub.

    Order: a provider supplied by the hook, then the one named in config if it is
    registered and has its credentials, otherwise the default log provider.
    """
    from karpy_platform.plugins.auth.extensions import filter_value

    supplied = await filter_value(SMS_PROVIDER_FILTER, None, db, values)
    if isinstance(supplied, SmsProvider):
        return supplied

    name = str(values.get("payment.notifications.sms.provider") or DEFAULT_SMS_PROVIDER).strip()
    provider = sms_provider_registry.get(name)
    if provider and provider.name != DEFAULT_SMS_PROVIDER and not provider.is_configured(values):
        logger.warning("SMS provider '%s' is missing credentials; using the log stub", name)
        provider = None
    return provider or sms_provider_registry.get(DEFAULT_SMS_PROVIDER) or LogSmsProvider()


def sms_recipients(values: dict[str, Any]) -> list[str]:
    raw = values.get("payment.notifications.sms.recipients") or ""
    if isinstance(raw, list):
        candidates = raw
    else:
        candidates = str(raw).split(",")
    recipients: list[str] = []
    for candidate in candidates:
        phone = str(candidate or "").strip()
        if phone and phone not in recipients:
            recipients.append(phone)
    return recipients
