"""AstraCall adapter for KARPy's payment-notification ``SmsProvider`` port.

This is a KARPy-native adaptation of the AstraCall provider. It conforms to the
port defined in ``payment.services.notifications.sms`` (``send(to, message, *,
reference=None) -> SmsResult`` plus ``configure``/``is_configured``), rather than a
richer bespoke port. Credentials come from the setting store, encrypted with the
platform's own ``enc:v1`` scheme:

- ``astracall.api_key``        encrypted API key (test keys never deliver to a phone)
- ``astracall.webhook_secret`` encrypted webhook signing secret (for a future webhook route)
- ``astracall.api_base_url``   optional, defaults to ``https://astracall.cc/api/v1``
- ``astracall.timeout_seconds``optional request timeout
- ``notify.sms.sender_id``     the sender ID shown on the message

Retries are the caller's responsibility: a transient failure returns a non-sent
``SmsResult`` (it is never raised), so the notification dispatcher stays best-effort.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import uuid
from typing import Any, Mapping

import httpx

from karpy_platform.plugins.payment.services.notifications.sms import SmsProvider, SmsResult

log = logging.getLogger("karpy.plugins.astracall_sms")

PROVIDER_KEY = "astracall"
DEFAULT_API_BASE_URL = "https://astracall.cc/api/v1"
LIVE_KEY_PREFIX = "sk_live_"
SIGNATURE_HEADER = "x-webhook-signature"

SETTING_API_KEY = "astracall.api_key"  # encrypted (enc:v1)
SETTING_WEBHOOK_SECRET = "astracall.webhook_secret"  # encrypted (enc:v1)
SETTING_API_BASE_URL = "astracall.api_base_url"
SETTING_TIMEOUT = "astracall.timeout_seconds"
SETTING_SENDER_ID = "notify.sms.sender_id"

# Tests inject an ``httpx.MockTransport`` here; production uses the default transport.
transport: httpx.AsyncBaseTransport | None = None


def _data(body: Any) -> dict[str, Any]:
    if isinstance(body, dict) and isinstance(body.get("data"), dict):
        return body["data"]
    return body if isinstance(body, dict) else {}


class AstraCallSmsProvider(SmsProvider):
    """AstraCall SMS sender conforming to the payment notification port."""

    name = PROVIDER_KEY
    required_credentials = (SETTING_API_KEY,)

    def __init__(
        self,
        *,
        api_key: str = "",
        webhook_secret: str = "",
        sender_id: str = "",
        api_base_url: str = DEFAULT_API_BASE_URL,
        timeout_seconds: float = 10.0,
        http_transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._api_key = api_key
        self._webhook_secret = webhook_secret
        self._sender_id = sender_id
        self._api_base_url = api_base_url or DEFAULT_API_BASE_URL
        self._timeout = timeout_seconds
        self._transport = http_transport

    # ---- configuration from the setting store -----------------------------------------

    def is_configured(self, values: dict[str, Any]) -> bool:
        from karpy_platform.core.security.secrets import decrypt_secret

        return bool(decrypt_secret(str(values.get(SETTING_API_KEY) or "")).strip())

    def configure(self, values: Mapping[str, Any]) -> None:
        """Load credentials saved by staff in the admin (encrypted) before a send."""
        from karpy_platform.core.security.secrets import decrypt_secret

        self._api_key = decrypt_secret(str(values.get(SETTING_API_KEY) or "")).strip()
        self._webhook_secret = decrypt_secret(str(values.get(SETTING_WEBHOOK_SECRET) or "")).strip()
        self._sender_id = str(values.get(SETTING_SENDER_ID) or "").strip()
        self._api_base_url = str(values.get(SETTING_API_BASE_URL) or "").strip() or DEFAULT_API_BASE_URL
        try:
            self._timeout = float(values.get(SETTING_TIMEOUT) or self._timeout)
        except (TypeError, ValueError):
            pass

    @property
    def api_key(self) -> str:
        return self._api_key

    @property
    def sender_id(self) -> str:
        return self._sender_id

    @property
    def is_test(self) -> bool:
        """Test keys never deliver to real phones."""
        return not self._api_key.startswith(LIVE_KEY_PREFIX)

    # ---- the port -----------------------------------------------------------------------

    async def send(self, to: str, message: str, *, reference: str | None = None) -> SmsResult:
        if not self._api_key:
            log.warning("AstraCall send skipped: no API key configured")
            return SmsResult(provider=self.name, to=to, status="credentials_missing", sent=False, test=self.is_test)

        body: dict[str, Any] = {"to": to, "message": message, "message_type": "transactional"}
        if self._sender_id:
            body["sender_id"] = self._sender_id
        if reference:
            body["reference"] = reference[:64]
        # A stable idempotency key lets the provider de-duplicate a retried request.
        idempotency_key = (reference or f"notify-{uuid.uuid4()}")[:64]
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Accept": "application/json",
            "Idempotency-Key": idempotency_key,
        }
        try:
            async with httpx.AsyncClient(
                base_url=self._api_base_url.rstrip("/"),
                timeout=self._timeout,
                transport=self._transport or transport,
                follow_redirects=False,
            ) as client:
                response = await client.request("POST", "/sms/send", json=body, headers=headers)
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            log.warning("AstraCall send failed (%s)", type(exc).__name__)
            return SmsResult(provider=self.name, to=to, status="submission_unknown", sent=False, test=self.is_test)

        try:
            payload = response.json()
        except ValueError:
            payload = {}
        if response.status_code < 300:
            data = _data(payload)
            message_id = str(data.get("message_id") or data.get("id") or "") or None
            # 202 means accepted (final delivery is confirmed out of band), not yet delivered.
            return SmsResult(
                provider=self.name,
                to=to,
                status="accepted",
                sent=True,
                test=self.is_test,
                provider_message_id=message_id,
            )
        error = payload.get("error") if isinstance(payload, dict) and isinstance(payload.get("error"), dict) else {}
        code = str(error.get("code") or ("unauthorized" if response.status_code == 401 else f"http_{response.status_code}"))
        log.warning("AstraCall send -> %s %s", response.status_code, code)
        return SmsResult(provider=self.name, to=to, status=code, sent=False, test=self.is_test)

    # ---- webhook signature (for a future delivery-receipt route) ----------------------

    def verify_webhook(self, headers: Mapping[str, str], raw_body: bytes) -> bool:
        """Constant-time hex HMAC-SHA256 of the raw body with the signing secret."""
        supplied = {str(k).lower(): str(v) for k, v in headers.items()}.get(SIGNATURE_HEADER, "").strip().lower()
        if not self._webhook_secret or not supplied:
            return False
        expected = hmac.new(self._webhook_secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(supplied, expected)


# Module-level singleton registered into the payment SMS provider registry.
astracall = AstraCallSmsProvider()


def register() -> None:
    """Register the AstraCall provider so ``payment.notifications.sms.provider=astracall`` selects it."""
    from karpy_platform.plugins.payment.services.notifications.sms import sms_provider_registry

    sms_provider_registry.register(astracall)


def unregister() -> None:
    from karpy_platform.plugins.payment.services.notifications.sms import sms_provider_registry

    sms_provider_registry.unregister(PROVIDER_KEY)
