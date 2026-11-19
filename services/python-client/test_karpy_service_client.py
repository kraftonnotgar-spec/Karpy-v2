from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest

import karpy_service_client as ksc

VECTORS = json.loads((Path(__file__).resolve().parents[1] / "contracts" / "signing-vectors.json").read_text("utf-8"))["vectors"]
V1 = VECTORS[0]


@pytest.mark.parametrize("v", VECTORS, ids=[v["name"] for v in VECTORS])
def test_vectors(v):
    body = v["body"].encode()
    assert ksc.canonical_string(v["key_id"], v["method"], v["path_and_query"], v["timestamp"], v["nonce"], body) == v["canonical_string"]
    headers = ksc.sign_headers(v["key_id"], v["secret"], v["method"], v["path_and_query"], body,
                               timestamp=int(v["timestamp"]), nonce=v["nonce"])
    assert headers[ksc.HEADER_SIGNATURE] == v["signature_header"]
    assert ksc.verify_signature({v["key_id"]: v["secret"]}, v["method"], v["path_and_query"], headers, body,
                                now=int(v["timestamp"])) == v["key_id"]


def test_verify_rejects_tamper_skew_and_unknown_key():
    body = V1["body"].encode()
    headers = ksc.sign_headers(V1["key_id"], V1["secret"], "POST", V1["path_and_query"], body,
                               timestamp=int(V1["timestamp"]), nonce=V1["nonce"])
    keys = {V1["key_id"]: V1["secret"]}
    now = int(V1["timestamp"])
    assert ksc.verify_signature(keys, "POST", V1["path_and_query"], headers, b'{"message":"HELLO"}', now=now) is None
    assert ksc.verify_signature(keys, "POST", "/v1/echo?lang=fr", headers, body, now=now) is None
    assert ksc.verify_signature(keys, "POST", V1["path_and_query"], headers, body, now=now + 301) is None
    assert ksc.verify_signature({"other": V1["secret"]}, "POST", V1["path_and_query"], headers, body, now=now) is None


def _echo_handler(seen: list[httpx.Request]):
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        key = ksc.verify_signature({V1["key_id"]: V1["secret"]}, request.method,
                                   request.url.raw_path.decode(), request.headers, request.content)
        if key is None:
            return httpx.Response(401, json={"error": {"code": "unauthorized", "message": "Invalid service authentication.",
                                                       "request_id": request.headers.get("x-request-id", "")}})
        return httpx.Response(200, json={"message": json.loads(request.content)["message"], "key_id": key})
    return handler


def test_client_signs_wire_request_including_query():
    seen: list[httpx.Request] = []
    with ksc.ServiceClient("http://svc.test", V1["key_id"], V1["secret"],
                           transport=httpx.MockTransport(_echo_handler(seen))) as client:
        out = client.post_json("/v1/echo", {"message": "hello"}, params={"lang": "en"}, request_id="req-1",
                               traceparent="00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01")
    assert out == {"message": "hello", "key_id": V1["key_id"]}
    sent = seen[0]
    assert sent.content == V1["body"].encode()  # compact JSON, identical bytes to the vector body
    assert sent.url.raw_path == b"/v1/echo?lang=en"
    assert sent.headers["x-request-id"] == "req-1" and sent.headers["traceparent"].startswith("00-")
    assert sent.headers[ksc.HEADER_SIGNATURE].startswith("v1=")
    assert len(sent.headers[ksc.HEADER_NONCE]) == 32


def test_client_raises_structured_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(409, json={"error": {"code": "request_replayed", "message": "Request was already processed.",
                                                   "request_id": "req-9"}})
    with ksc.ServiceClient("http://svc.test", V1["key_id"], V1["secret"], transport=httpx.MockTransport(handler)) as c:
        with pytest.raises(ksc.ServiceError) as exc:
            c.get_json("/v1/anything")
    assert (exc.value.status_code, exc.value.code, exc.value.request_id) == (409, "request_replayed", "req-9")


def test_async_client():
    seen: list[httpx.Request] = []

    async def run():
        async with ksc.AsyncServiceClient("http://svc.test", V1["key_id"], V1["secret"],
                                          transport=httpx.MockTransport(_echo_handler(seen))) as c:
            return await c.post_json("/v1/echo", {"message": "hi"})

    assert asyncio.run(run())["message"] == "hi"


def test_rejects_weak_credentials():
    with pytest.raises(ValueError):
        ksc.KarpyHmacAuth("k", "short")
    with pytest.raises(ValueError):
        ksc.KarpyHmacAuth("bad id", "x" * 32)
    assert "x" * 32 not in repr(ksc.KarpyHmacAuth("k", "x" * 32))
