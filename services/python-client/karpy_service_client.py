"""Sign outbound KARPy -> service calls with KARPY-HMAC-SHA256-V1.

Standalone (only depends on httpx) so it can later move into
``backend/karpy_platform/integrations/services/``. The scheme is defined in
``services/contracts/signing.md``; conformance vectors are in
``services/contracts/signing-vectors.json``.

Backend settings it maps to (``backend/app/config.py``)::

    SERVICE_KEY_ID                   -> key_id
    SERVICE_SIGNING_SECRET           -> secret
    SERVICE_REQUEST_TIMEOUT_SECONDS  -> timeout

Usage::

    client = ServiceClient("http://example-service:8080", key_id, secret)
    data = client.post_json("/v1/echo", {"message": "hi"}, request_id=req_id)

    async with AsyncServiceClient(base_url, key_id, secret) as c:
        data = await c.post_json("/v1/echo", {"message": "hi"})
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import time
from collections.abc import Generator
from typing import Any

import httpx

SCHEME = "KARPY-HMAC-SHA256-V1"
HEADER_KEY_ID = "X-Karpy-Key-Id"
HEADER_TIMESTAMP = "X-Karpy-Timestamp"
HEADER_NONCE = "X-Karpy-Nonce"
HEADER_SIGNATURE = "X-Karpy-Signature"
HEADER_REQUEST_ID = "X-Request-Id"
MIN_SECRET_BYTES = 32

_KEY_ID = re.compile(r"[A-Za-z0-9._-]{1,64}")
_NONCE = re.compile(r"[A-Za-z0-9_-]{16,128}")


def canonical_string(key_id: str, method: str, path_and_query: str, timestamp: str, nonce: str, body: bytes) -> str:
    return "\n".join((SCHEME, key_id, method.upper(), path_and_query, timestamp, nonce, hashlib.sha256(body).hexdigest()))


def signature(secret: str | bytes, canonical: str) -> str:
    key = secret.encode() if isinstance(secret, str) else secret
    return "v1=" + hmac.new(key, canonical.encode(), hashlib.sha256).hexdigest()


def sign_headers(
    key_id: str,
    secret: str | bytes,
    method: str,
    path_and_query: str,
    body: bytes,
    *,
    timestamp: int | None = None,
    nonce: str | None = None,
) -> dict[str, str]:
    """Return the four X-Karpy-* headers for one request."""
    ts = str(int(time.time()) if timestamp is None else timestamp)
    nonce = nonce or secrets.token_hex(16)
    if not _NONCE.fullmatch(nonce):
        raise ValueError("nonce must be 16-128 chars of [A-Za-z0-9_-]")
    canonical = canonical_string(key_id, method, path_and_query, ts, nonce, body)
    return {
        HEADER_KEY_ID: key_id,
        HEADER_TIMESTAMP: ts,
        HEADER_NONCE: nonce,
        HEADER_SIGNATURE: signature(secret, canonical),
    }


def verify_signature(
    keys: dict[str, str | bytes],
    method: str,
    path_and_query: str,
    headers: Any,
    body: bytes,
    *,
    max_skew_seconds: int = 300,
    now: float | None = None,
) -> str | None:
    """Stateless check for Python services. Returns the key id, or None.

    The caller must still reserve (key id, nonce) in a replay cache (Redis
    ``SET ... NX EX``) after this returns a key id, and answer 409 on replay.
    """
    key_id = headers.get(HEADER_KEY_ID, "")
    ts = headers.get(HEADER_TIMESTAMP, "")
    nonce = headers.get(HEADER_NONCE, "")
    sig = headers.get(HEADER_SIGNATURE, "")
    secret = keys.get(key_id)
    if secret is None or not re.fullmatch(r"[0-9]{1,12}", ts) or not _NONCE.fullmatch(nonce) or not sig.startswith("v1="):
        return None
    if abs((time.time() if now is None else now) - int(ts)) > max_skew_seconds:
        return None
    expected = signature(secret, canonical_string(key_id, method, path_and_query, ts, nonce, body))
    return key_id if hmac.compare_digest(expected, sig) else None


class KarpyHmacAuth(httpx.Auth):
    """httpx auth flow: signs the final request (method, raw path+query, body)."""

    requires_request_body = True

    def __init__(self, key_id: str, secret: str | bytes) -> None:
        raw = secret.encode() if isinstance(secret, str) else secret
        if not _KEY_ID.fullmatch(key_id or "") or len(raw) < MIN_SECRET_BYTES:
            raise ValueError("service key id must match [A-Za-z0-9._-]{1,64} and the secret must be >= 32 bytes")
        self._key_id = key_id
        self._secret = raw

    def __repr__(self) -> str:  # never print the secret
        return f"KarpyHmacAuth(key_id={self._key_id!r})"

    def auth_flow(self, request: httpx.Request) -> Generator[httpx.Request, httpx.Response, None]:
        # raw_path is the origin-form target exactly as httpx sends it (path + "?" + query).
        target = request.url.raw_path.decode("ascii")
        request.headers.update(sign_headers(self._key_id, self._secret, request.method, target, request.content))
        yield request


class ServiceError(RuntimeError):
    """A service answered with the standard {"error": {...}} shape (or failed)."""

    def __init__(self, status_code: int, code: str, message: str, request_id: str = "") -> None:
        super().__init__(f"{status_code} {code}: {message}")
        self.status_code = status_code
        self.code = code
        self.message = message
        self.request_id = request_id


def _raise_for_error(response: httpx.Response) -> None:
    if response.is_success:
        return
    try:
        err = response.json().get("error", {})
    except (ValueError, AttributeError):
        err = {}
    if not isinstance(err, dict):
        err = {}
    raise ServiceError(
        response.status_code,
        str(err.get("code") or "upstream_error"),
        str(err.get("message") or "Service request failed."),
        str(err.get("request_id") or response.headers.get(HEADER_REQUEST_ID, "")),
    )


def _encode(payload: Any) -> bytes:
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode()


def _headers(request_id: str | None, traceparent: str | None) -> dict[str, str]:
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if request_id:
        headers[HEADER_REQUEST_ID] = request_id
    if traceparent:
        headers["traceparent"] = traceparent
    return headers


class ServiceClient:
    """Synchronous signed client for one service base URL."""

    def __init__(self, base_url: str, key_id: str, secret: str, *, timeout: float = 10.0,
                 transport: httpx.BaseTransport | None = None) -> None:
        self._client = httpx.Client(base_url=base_url.rstrip("/"), auth=KarpyHmacAuth(key_id, secret),
                                    timeout=timeout, transport=transport, follow_redirects=False)

    def request_json(self, method: str, path: str, payload: Any = None, *, params: dict[str, str] | None = None,
                     request_id: str | None = None, traceparent: str | None = None) -> Any:
        content = b"" if payload is None else _encode(payload)
        response = self._client.request(method, path, content=content, params=params,
                                        headers=_headers(request_id, traceparent))
        _raise_for_error(response)
        return response.json() if response.content else None

    def post_json(self, path: str, payload: Any, **kw: Any) -> Any:
        return self.request_json("POST", path, payload, **kw)

    def get_json(self, path: str, **kw: Any) -> Any:
        return self.request_json("GET", path, None, **kw)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> ServiceClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


class AsyncServiceClient:
    """Async variant for FastAPI handlers. Reuse one instance per service (connection pool)."""

    def __init__(self, base_url: str, key_id: str, secret: str, *, timeout: float = 10.0,
                 transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._client = httpx.AsyncClient(base_url=base_url.rstrip("/"), auth=KarpyHmacAuth(key_id, secret),
                                         timeout=timeout, transport=transport, follow_redirects=False)

    async def request_json(self, method: str, path: str, payload: Any = None, *, params: dict[str, str] | None = None,
                           request_id: str | None = None, traceparent: str | None = None) -> Any:
        content = b"" if payload is None else _encode(payload)
        response = await self._client.request(method, path, content=content, params=params,
                                              headers=_headers(request_id, traceparent))
        _raise_for_error(response)
        return response.json() if response.content else None

    async def post_json(self, path: str, payload: Any, **kw: Any) -> Any:
        return await self.request_json("POST", path, payload, **kw)

    async def get_json(self, path: str, **kw: Any) -> Any:
        return await self.request_json("GET", path, None, **kw)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> AsyncServiceClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()
