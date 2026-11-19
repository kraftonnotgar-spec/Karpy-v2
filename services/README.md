# Karpy services

A **Karpy service** is a separately deployed process — written in any language — that
KARPy (the FastAPI backend in `backend/`) talks to over HTTP and RabbitMQ. A service
owns one well-bounded capability (and its own data); KARPy stays the system of record
for users, content, permissions and the admin UI.

Every service, whatever its language, implements the same small contract below. If a
service follows it, KARPy can call it, trust it, receive its events, health-check it
and trace through it without any per-language glue.

| Part | Where it is defined |
| --- | --- |
| HTTP API (OpenAPI 3.1) | `contracts/<service>.openapi.yaml` (start from [`contracts/example.openapi.yaml`](contracts/example.openapi.yaml)) |
| Request signing | [`contracts/signing.md`](contracts/signing.md) + [`contracts/signing-vectors.json`](contracts/signing-vectors.json) |
| Event envelope | [`contracts/event-envelope.schema.json`](contracts/event-envelope.schema.json) |
| Reference service (Go) | [`go-template/`](go-template/) |
| KARPy-side signing client (Python) | [`python-client/`](python-client/) |
| Local observability stack | [`observability/`](observability/) |

Architecture, when to build a service at all, and the new-service checklist are in
[`docs/SERVICES.md`](../docs/SERVICES.md).

---

## The contract

### (a) OpenAPI 3.1 contract

- One file per service: `services/contracts/<service>.openapi.yaml`, written **before**
  the code and reviewed like code. It is the source of truth for both sides.
- Business routes are versioned in the path: `/v1/...`. Ops routes (`/healthz`,
  `/readyz`) are unversioned and unauthenticated.
- Declare the four signing headers as security schemes (see the example) so readers and
  generators know every `/v1` call is signed.
- JSON only (`application/json`), `snake_case` fields, timestamps in RFC 3339 UTC, money
  as integer minor units plus a currency code, ids as strings.

### (b) Service-to-service authentication

**HMAC-SHA256 signed requests** — scheme `KARPY-HMAC-SHA256-V1`. Full definition and test
vectors: [`contracts/signing.md`](contracts/signing.md). Summary:

```
X-Karpy-Key-Id:    <key id>
X-Karpy-Timestamp: <unix seconds>
X-Karpy-Nonce:     <16-128 chars [A-Za-z0-9_-], random, single use>
X-Karpy-Signature: v1=<hex HMAC-SHA256(secret, canonical string)>
```

Canonical string (LF-joined, no trailing newline):

```
KARPY-HMAC-SHA256-V1
<key id>
<METHOD>
<path?query exactly as sent>
<timestamp>
<nonce>
<hex SHA-256 of the raw body>
```

Receiver rules: known key id; `|now - timestamp| <= 300 s`; constant-time compare;
reserve `(key id, nonce)` in a replay cache for `2 × skew` **after** the signature checks
(in memory for one replica, Redis `SET NX EX` for several); `401 unauthorized` for every
auth failure without saying which check failed; `409 request_replayed` on a reused nonce.

Key rotation uses key ids: a service accepts a *set*
(`KARPY_SERVICE_KEYS=keyid:secret,keyid2:secret2`), the caller signs with one active key
(`SERVICE_KEY_ID` / `SERVICE_SIGNING_SECRET` in the backend). Add new → switch caller →
remove old. Secrets ≥ 32 bytes (`openssl rand -hex 32`), one per caller→service pair.

**mTLS** is an optional extra on private networks (private CA, check the client cert
SAN). It does not replace HMAC: HMAC also gives replay protection and survives proxies.

The `X-Request-Id` and `traceparent` headers are not signed; anything with business
meaning (actor, amount, idempotency key) goes in the signed body.

### (c) Events over RabbitMQ

- **Exchange**: one durable **topic** exchange, `karpy.events` (backend setting
  `RABBITMQ_EXCHANGE`). Services publish to it; they do not create per-producer exchanges.
- **Routing key** = event `type` = `<domain>.<entity>.<event>`, lowercase, event in past
  tense: `content.post.published`, `member.account.created`, `example.echo.received`.
- **Queues** are owned by the *consumer* and named `<consumer>.<purpose>`, bound with
  patterns (`content.post.*`, `member.#`). Each queue gets:
  - `x-dead-letter-exchange: karpy.dlx` → `<queue>.dead` (parking lot, alerted on);
  - a delayed retry queue `<queue>.retry` (`x-message-ttl`, dead-lettering back to the
    main queue) for transient failures, with a max attempt count tracked in a header.
- **Envelope**: every message body is the JSON object in
  [`contracts/event-envelope.schema.json`](contracts/event-envelope.schema.json):

  ```json
  {
    "id": "01936d3e-7c4a-7b2e-9f10-2a4b6c8d0e1f",
    "type": "example.echo.received",
    "version": 1,
    "source": "example-service",
    "occurred_at": "2026-01-01T00:00:00Z",
    "correlation_id": "req-7f3a",
    "causation_id": "req-7f3a",
    "idempotency_key": "01936d3e-7c4a-7b2e-9f10-2a4b6c8d0e1f",
    "traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01",
    "data": {"message": "hello"}
  }
  ```

  AMQP properties: `message_id = id`, `content_type = application/json`,
  `delivery_mode = 2` (persistent), headers carry `traceparent` and `correlation_id`.
- **Producer: transactional outbox.** Never publish from inside a request handler. Insert
  the envelope into an `event_outbox` table **in the same DB transaction** as the state
  change; a relay claims pending rows (`FOR UPDATE SKIP LOCKED`), publishes with
  **publisher confirms** and `mandatory=true`, marks them published, and backs off
  exponentially on failure, marking rows dead after N attempts. (Table sketch in
  `go-template/internal/events/events.go`.)
- **Consumer: idempotent inbox.** Delivery is at-least-once. In the same transaction as
  the side effect, `INSERT INTO event_inbox(consumer, idempotency_key) ... ON CONFLICT DO
  NOTHING`; if nothing was inserted it is a duplicate → ack and skip. Ack only after
  commit. Use a bounded prefetch (e.g. 20). Unknown `type`/`version` → dead-letter, never
  crash-loop. Poison messages go to the retry queue, then `.dead`.
- **Versioning**: additive changes keep `version`; a breaking change publishes a new
  `version` (both side by side) until every consumer has moved.

### (d) Health and readiness

| Route | Meaning | Checks | Response |
| --- | --- | --- | --- |
| `GET /healthz` | Liveness — the process can serve HTTP | none (never touch dependencies) | `200 {"status":"alive",...}` |
| `GET /readyz` | Readiness — should receive traffic | each hard dependency (DB, broker, cache) with a short timeout; also fails while draining on shutdown | `200 {"status":"ready","checks":{...}}` or `503 {"status":"unavailable",...}` |

Both are unauthenticated and must not leak error details (log them instead). Containers
use `/healthz` for restarts and `/readyz` for routing. (KARPy itself exposes the same idea
as `/api/health` and `/api/ready`.)

### (e) Observability

- **OpenTelemetry** for traces, metrics and logs, exported over **OTLP** to
  `OTEL_EXPORTER_OTLP_ENDPOINT` (local: `http://otel-collector:4317` gRPC or `:4318`
  HTTP). `OTEL_SERVICE_NAME` names the service. No endpoint → telemetry is a no-op.
- **W3C trace context**: accept `traceparent`/`tracestate` on every inbound request, send
  them on every outbound call, copy `traceparent` into the event envelope and AMQP
  headers, and continue the trace when consuming.
- **Structured JSON logs** to stdout, one object per line, always including `service`,
  `environment`, `level`, `msg`, `request_id`, and `trace_id`/`span_id` when present. Never
  log secrets, signatures, full bodies or personal data.
- Minimum metrics: request count/duration by route and status class, outbox backlog and
  oldest age, consumer lag, retries and dead-letters.

### (f) Versioning and errors

- Path versioning (`/v1`). Within a version only additive changes; clients must ignore
  unknown response fields. A breaking change is `/v2`, run side by side.
- Every non-2xx response has exactly this shape:

  ```json
  {"error": {"code": "unauthorized", "message": "Invalid service authentication.", "request_id": "req-7f3a"}}
  ```

  `code` is stable snake_case for machines (`invalid_request`, `unauthorized`,
  `forbidden`, `not_found`, `conflict`, `request_replayed`, `payload_too_large`,
  `rate_limited`, `dependency_unavailable`, `internal_error`); `message` is safe to show;
  `request_id` echoes `X-Request-Id` (generated if absent, and returned as a header).
- Mutating endpoints that can be retried accept an `idempotency_key` **in the body** and
  return the original result for a repeat.

---

## Go (reference)

[`go-template/`](go-template/) is a stdlib-only service implementing all of the above:
config from env, signing middleware, `/healthz`, `/readyz`, `POST /v1/echo`, JSON errors,
`log/slog` JSON logs with trace ids, graceful shutdown, an event `Publisher` seam and
OTel seam. Copy the directory to start a new Go service.

## Python

A Python service is a small FastAPI app. Verify the signature from the **raw** body and
the raw request target, before parsing JSON. `verify_signature` in
[`python-client/karpy_service_client.py`](python-client/karpy_service_client.py) is
reusable on the receiving side:

```python
import os
from fastapi import Depends, FastAPI, HTTPException, Request
from redis.asyncio import Redis
from karpy_service_client import verify_signature  # or vendor the ~20 lines

KEYS = dict(item.split(":", 1) for item in os.environ["KARPY_SERVICE_KEYS"].split(","))
redis = Redis.from_url(os.environ["REDIS_URL"])
app = FastAPI()

async def signed(request: Request) -> str:
    body = await request.body()
    target = request.scope["raw_path"].decode()
    if request.scope["query_string"]:
        target += "?" + request.scope["query_string"].decode()
    key_id = verify_signature(KEYS, request.method, target, request.headers, body)
    if key_id is None:
        raise HTTPException(401, "unauthorized")       # map to the error shape in an exception handler
    nonce = request.headers["x-karpy-nonce"]
    if not await redis.set(f"karpy:nonce:{key_id}:{nonce}", 1, nx=True, ex=600):
        raise HTTPException(409, "request_replayed")
    return key_id

@app.get("/healthz")
async def healthz():
    return {"status": "alive"}

@app.post("/v1/echo")
async def echo(payload: dict, key_id: str = Depends(signed)):
    return {"message": payload["message"], "key_id": key_id}
```

Use `opentelemetry-instrumentation-fastapi` + the OTLP exporter for traces, `aio-pika`
(publisher confirms on) for RabbitMQ, and an outbox table in the service's own database.

## Node

```js
import crypto from "node:crypto";
import express from "express";

const KEYS = Object.fromEntries(process.env.KARPY_SERVICE_KEYS.split(",").map((kv) => {
  const i = kv.indexOf(":"); return [kv.slice(0, i), kv.slice(i + 1)];
}));
const seen = new Map(); // single replica only — use Redis SET NX EX in production

function verify(req, res, next) {
  const id = req.get("x-karpy-key-id"), ts = req.get("x-karpy-timestamp") ?? "";
  const nonce = req.get("x-karpy-nonce") ?? "", sig = req.get("x-karpy-signature") ?? "";
  const secret = KEYS[id];
  const fail = (s, code, message) => res.status(s).json({ error: { code, message, request_id: req.get("x-request-id") ?? "" } });
  if (!secret || !/^\d{1,12}$/.test(ts) || !/^[A-Za-z0-9_-]{16,128}$/.test(nonce) || !sig.startsWith("v1=")) return fail(401, "unauthorized", "Invalid service authentication.");
  if (Math.abs(Date.now() / 1000 - Number(ts)) > 300) return fail(401, "unauthorized", "Invalid service authentication.");
  const body = req.body instanceof Buffer ? req.body : Buffer.alloc(0);
  const canonical = ["KARPY-HMAC-SHA256-V1", id, req.method.toUpperCase(), req.originalUrl, ts, nonce,
    crypto.createHash("sha256").update(body).digest("hex")].join("\n");
  const expected = Buffer.from("v1=" + crypto.createHmac("sha256", secret).update(canonical).digest("hex"));
  const given = Buffer.from(sig);
  if (given.length !== expected.length || !crypto.timingSafeEqual(given, expected)) return fail(401, "unauthorized", "Invalid service authentication.");
  if (seen.has(id + "\0" + nonce)) return fail(409, "request_replayed", "Request was already processed.");
  seen.set(id + "\0" + nonce, Date.now() + 600_000);
  next();
}

const app = express();
app.get("/healthz", (_req, res) => res.json({ status: "alive" }));
// Raw body first, verify, then parse.
app.post("/v1/echo", express.raw({ type: "application/json", limit: "1mb" }), verify, (req, res) => {
  const { message } = JSON.parse(req.body.toString("utf8"));
  res.json({ message });
});
app.listen(Number(process.env.PORT ?? 8080));
```

`req.originalUrl` is the path and query as received (Express does not decode it). Check
your implementation against `contracts/signing-vectors.json`. For telemetry use
`@opentelemetry/sdk-node` with `@opentelemetry/auto-instrumentations-node`; for RabbitMQ
`amqplib` with a `ConfirmChannel`.

## Mojo

Mojo (Modular) is a compiled, Python-superset-style language aimed at high-performance
compute. Be aware of its current state before choosing it for a service:

- It is pre-1.0; the language and standard library still change between releases. Pin
  the version (it is distributed through Modular's package channels / `pixi`, and as the
  `mojo` / `modular` Python packages) and expect to update code on upgrades.
- The standard library has **no production HTTP server, TLS, AMQP or OpenTelemetry**.
  Community HTTP libraries exist but are young — treat them as experimental.
- Mojo has first-class **Python interop**: Mojo code can import and call Python modules,
  and (a newer, still-evolving feature) Python can import Mojo code compiled as a Python
  extension module.

So the recommended shapes are:

1. **Python host + Mojo kernel (recommended).** Build a normal Python service (FastAPI,
   as above) that owns HTTP, HMAC, health, events and telemetry, and import the hot path
   written in Mojo as an extension module. The service contract is unchanged; Mojo is an
   implementation detail.
2. **Separate Mojo process behind the same contract.** Run a Mojo binary as a worker
   (e.g. reading jobs from stdin/a local socket, or consuming from a queue via a thin
   Python/Go sidecar), with the sidecar implementing `/healthz`, `/readyz`, HMAC and the
   envelope. Only expose a Mojo HTTP server directly once a mature HTTP library exists,
   and then it must pass the same signing vectors.

Illustrative sketch — **pseudocode, check the current Mojo docs for exact names**
(the Python-extension API in particular has changed across releases):

```mojo
# kernel.mojo  -- PSEUDOCODE: compiled into a Python extension module
from python import PythonObject
# from python.bindings import PythonModuleBuilder   # name/shape per current Mojo docs

fn score(values: PythonObject) raises -> PythonObject:
    var total: Float64 = 0
    for v in values:
        total += Float64(v)
    return total

# @export
# fn PyInit_kernel() -> PythonObject:   # module init hook exposing `score` to Python
#     ...
```

```python
# service.py -- real Python; the Mojo module is imported like any extension
import kernel            # built from kernel.mojo
@app.post("/v1/score")
async def score(payload: dict, key_id: str = Depends(signed)):
    return {"score": float(kernel.score(payload["values"]))}
```

## The KARPy side

[`python-client/karpy_service_client.py`](python-client/karpy_service_client.py) is a
standalone, httpx-only signing client (`ServiceClient`, `AsyncServiceClient`,
`KarpyHmacAuth` for any httpx client, `sign_headers`, `verify_signature`) with tests
against the shared vectors (`pytest services/python-client`). It is intentionally
self-contained so the backend team can move it into
`backend/karpy_platform/integrations/services/` and wire it to the backend settings:

| Backend setting | Used for |
| --- | --- |
| `SERVICE_KEY_ID`, `SERVICE_SIGNING_SECRET` | Active signing key for outbound service calls |
| `SERVICE_REQUEST_TIMEOUT_SECONDS` | Default per-call timeout |
| `RABBITMQ_URL`, `RABBITMQ_EXCHANGE` (`karpy.events`) | Event publishing (outbox relay) and consumers |
| `OTEL_EXPORTER_OTLP_ENDPOINT`, `OTEL_SERVICE_NAME` | Telemetry export |

Each service's base URL should be its own setting (e.g. `EXAMPLE_SERVICE_URL`), passed to
`ServiceClient(base_url, key_id, secret, timeout=...)`.
