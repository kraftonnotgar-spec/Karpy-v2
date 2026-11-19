# Go service template

Minimal, **stdlib-only** Karpy service implementing the contract in
[`../README.md`](../README.md): HMAC-signed requests, `/healthz`, `/readyz`, one example
endpoint (`POST /v1/echo`), the JSON error shape, `log/slog` JSON logs with trace ids,
graceful shutdown, and seams for RabbitMQ and OpenTelemetry. API contract:
[`../contracts/example.openapi.yaml`](../contracts/example.openapi.yaml).

```
cmd/server/main.go          wiring, graceful shutdown, --healthcheck/--readycheck probes
internal/config             env parsing (KARPY_SERVICE_KEYS, PORT, ...)
internal/auth               KARPY-HMAC-SHA256-V1 signer, verifier, middleware, replay cache
internal/httpapi            routes, request id, access log, error shape, health/readiness
internal/events             event envelope, UUIDv7, Publisher (no-op / in-memory), outbox notes
internal/telemetry          W3C traceparent propagation, trace ids in logs, OTel seam
```

## Run

```sh
export KARPY_SERVICE_KEYS="local-1:$(openssl rand -hex 32)"
go run ./cmd/server
curl -s localhost:8080/healthz
```

Docker (build context is this directory):

```sh
docker build -t karpy/example-service .
docker run --rm -p 8080:8080 -e KARPY_SERVICE_KEYS="local-1:<64 hex chars>" karpy/example-service
```

The image is distroless, runs as `nonroot`, and health-checks itself with
`/server --healthcheck` (use `--readycheck` for a readiness probe).

## Test

```sh
go vet ./...
go test ./...
```

`internal/auth` reads the shared conformance vectors from
`../contracts/signing-vectors.json` and covers: valid request, bad signature, tampered
body/query/method, stale and future timestamps, replayed nonce, unknown key, malformed
headers, oversized body, and key rotation.

## Environment

| Variable | Default | Notes |
| --- | --- | --- |
| `KARPY_SERVICE_KEYS` | **required** | `keyid:secret[,keyid:secret]`; secret ≥ 32 bytes. Several keys = rotation window. |
| `PORT` | `8080` | |
| `SERVICE_NAME` | `$OTEL_SERVICE_NAME` or `example-service` | Used in logs and as event `source`. |
| `APP_ENV` | `development` | Added to every log line. |
| `KARPY_SIGNATURE_MAX_SKEW_SECONDS` | `300` | Timestamp window; nonces are kept 2× this. |
| `MAX_BODY_BYTES` | `1048576` | Larger bodies → `413 payload_too_large`. |
| `LOG_LEVEL` | `info` | `debug` also logs health probes. |
| `SHUTDOWN_TIMEOUT_SECONDS` | `20` | Drain time; `/readyz` returns 503 while draining. |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | empty | Seam only — see `internal/telemetry`. |
| `RABBITMQ_URL` | empty | Seam only — empty uses the no-op publisher. |
| `RABBITMQ_EXCHANGE` | `karpy.events` | Topic exchange for events. |

## Call it from KARPy

```python
from karpy_service_client import ServiceClient   # services/python-client

client = ServiceClient(settings.EXAMPLE_SERVICE_URL, settings.SERVICE_KEY_ID,
                       settings.SERVICE_SIGNING_SECRET, timeout=settings.SERVICE_REQUEST_TIMEOUT_SECONDS)
client.post_json("/v1/echo", {"message": "hello"}, request_id=request_id, traceparent=traceparent)
# -> {"message": "hello", "key_id": "...", "request_id": "...", "received_at": "..."}
```

The backend's `SERVICE_KEY_ID:SERVICE_SIGNING_SECRET` pair must appear in this service's
`KARPY_SERVICE_KEYS`.

## Turning the template into a real service

1. Copy the directory, change the module path in `go.mod` and the imports.
2. Write `services/contracts/<service>.openapi.yaml` first; replace `/v1/echo`.
3. **Replay cache**: with more than one replica, implement `auth.ReplayCache` on Redis
   (`SET key 1 NX EX ttl`).
4. **Storage + outbox**: add Postgres (pgx), an `event_outbox` table and a relay
   goroutine; publish via `github.com/rabbitmq/amqp091-go` with confirms. Add the DB and
   broker to `Server.Checks` so `/readyz` reflects them.
5. **Telemetry**: add the OpenTelemetry SDK + OTLP exporter in `telemetry.Init` and wrap
   the handler with `otelhttp` (instructions in the package comment).
