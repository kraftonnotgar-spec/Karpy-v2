"""AstraCall adapter: HTTP contract (MockTransport), error handling, port conformance."""

from __future__ import annotations

import hashlib
import hmac
import json
import unittest

import httpx

from karpy_platform.core.security.secrets import encrypt_secret
from karpy_platform.plugins.payment.services.notifications.sms import (
    SmsProvider,
    resolve_sms_provider,
    sms_provider_registry,
)

from . import adapter
from .adapter import AstraCallSmsProvider

BASE_URL = "https://astracall.test/api/v1"
SECRET = "astracall-signing-secret"


class FakeAstraCall:
    """A MockTransport handler standing in for the AstraCall API."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.next: list[object] = []
        self.messages = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.next:
            response = self.next.pop(0)
            if isinstance(response, Exception):
                raise response
            return response
        path = request.url.path.removeprefix("/api/v1")
        if path == "/sms/send":
            self.messages += 1
            return httpx.Response(202, json={"success": True, "data": {"message_id": f"msg_{self.messages}", "status": "accepted"}})
        return httpx.Response(404, json={"success": False, "error": {"code": "not_found"}})


def error(status: int, code: str) -> httpx.Response:
    return httpx.Response(status, json={"success": False, "error": {"code": code, "message": "x"}})


def live_provider(api: FakeAstraCall, **overrides) -> AstraCallSmsProvider:
    params = {
        "api_key": "sk_live_example",
        "sender_id": "BRAND",
        "api_base_url": BASE_URL,
        "http_transport": httpx.MockTransport(api),
    }
    params.update(overrides)
    return AstraCallSmsProvider(**params)


class AdapterContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_conforms_to_the_sms_provider_port(self) -> None:
        self.assertTrue(issubclass(AstraCallSmsProvider, SmsProvider))
        self.assertEqual(AstraCallSmsProvider.name, "astracall")

    async def test_send_uses_bearer_key_idempotency_key_and_sender(self) -> None:
        api = FakeAstraCall()
        provider = live_provider(api)
        result = await provider.send("+255684104712", "Hi", reference="notify-sms-1")
        request = api.requests[0]
        self.assertEqual((request.method, request.url.path), ("POST", "/api/v1/sms/send"))
        self.assertEqual(request.headers["authorization"], "Bearer sk_live_example")
        self.assertEqual(request.headers["idempotency-key"], "notify-sms-1")
        self.assertEqual(
            json.loads(request.content),
            {"to": "+255684104712", "message": "Hi", "message_type": "transactional", "sender_id": "BRAND", "reference": "notify-sms-1"},
        )
        self.assertEqual(
            (result.status, result.sent, result.test, result.provider_message_id),
            ("accepted", True, False, "msg_1"),
        )

    async def test_send_generates_idempotency_key_without_reference(self) -> None:
        api = FakeAstraCall()
        result = await live_provider(api).send("+255684104712", "Hi")
        self.assertTrue(result.sent)
        self.assertTrue(api.requests[0].headers["idempotency-key"].startswith("notify-"))
        self.assertNotIn("reference", json.loads(api.requests[0].content))

    async def test_errors_return_non_sent_result_and_never_raise(self) -> None:
        cases = [
            (error(402, "insufficient_balance"), "insufficient_balance"),
            (error(422, "invalid_recipient"), "invalid_recipient"),
            (error(401, "unauthorized"), "unauthorized"),
            (httpx.ReadTimeout("slow"), "submission_unknown"),
        ]
        for response, expected_status in cases:
            api = FakeAstraCall()
            api.next = [response]
            with self.subTest(expected=expected_status):
                result = await live_provider(api).send("+255684104712", "Hi", reference="k")
                self.assertFalse(result.sent)
                self.assertEqual(result.status, expected_status)

    async def test_missing_api_key_is_skipped_safely(self) -> None:
        api = FakeAstraCall()
        provider = live_provider(api, api_key="")
        result = await provider.send("+255684104712", "Hi")
        self.assertFalse(result.sent)
        self.assertEqual(result.status, "credentials_missing")
        self.assertEqual(api.requests, [])

    async def test_test_key_marks_result_as_test(self) -> None:
        api = FakeAstraCall()
        result = await live_provider(api, api_key="sk_test_abc123def").send("+255684104712", "Hi")
        self.assertTrue(result.test)
        self.assertTrue(result.sent)

    async def test_verify_webhook_signature(self) -> None:
        provider = live_provider(FakeAstraCall(), webhook_secret=SECRET)
        body = b'{"event":"sms.delivered"}'
        good = hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
        self.assertTrue(provider.verify_webhook({"X-Webhook-Signature": good}, body))
        self.assertFalse(provider.verify_webhook({"X-Webhook-Signature": "deadbeef"}, body))
        self.assertFalse(provider.verify_webhook({}, body))


class ConfigureAndResolveTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        adapter.register()
        self.addCleanup(adapter.unregister)

    async def test_configure_decrypts_saved_credentials(self) -> None:
        values = {
            adapter.SETTING_API_KEY: encrypt_secret("sk_live_from_settings"),
            adapter.SETTING_SENDER_ID: "SAVED",
            adapter.SETTING_API_BASE_URL: "https://astracall.test/api/v1",
        }
        provider = AstraCallSmsProvider()
        self.assertTrue(provider.is_configured(values))
        provider.configure(values)
        self.assertEqual(provider.api_key, "sk_live_from_settings")
        self.assertEqual(provider.sender_id, "SAVED")
        self.assertFalse(provider.is_test)

    async def test_resolve_returns_astracall_when_selected_and_configured(self) -> None:
        values = {
            "payment.notifications.sms.provider": "astracall",
            adapter.SETTING_API_KEY: encrypt_secret("sk_live_selected"),
        }
        provider = await resolve_sms_provider(None, values)
        self.assertIs(provider, adapter.astracall)
        # resolve_sms_provider primed it from settings.
        self.assertEqual(provider.api_key, "sk_live_selected")

    async def test_resolve_falls_back_to_log_when_unconfigured(self) -> None:
        values = {"payment.notifications.sms.provider": "astracall"}  # no api key saved
        provider = await resolve_sms_provider(None, values)
        self.assertEqual(provider.name, "log")
        self.assertIs(provider, sms_provider_registry.get("log"))


if __name__ == "__main__":
    unittest.main()
