# Service request signing — `KARPY-HMAC-SHA256-V1`

Every call from KARPy (or any service) to a Karpy service is signed with a shared
secret using HMAC-SHA256. This file is the normative definition; the test vectors in
[`signing-vectors.json`](signing-vectors.json) are the conformance suite.

## Headers

| Header | Value | Signed |
| --- | --- | --- |
| `X-Karpy-Key-Id` | Identifier of the shared secret used (`[A-Za-z0-9._-]{1,64}`) | yes |
| `X-Karpy-Timestamp` | Unix time in **seconds**, decimal ASCII, no fraction (`1767225600`) | yes |
| `X-Karpy-Nonce` | Random, single use, `[A-Za-z0-9_-]{16,128}` (32 hex chars from a CSPRNG is fine) | yes |
| `X-Karpy-Signature` | `v1=<lowercase hex HMAC-SHA256>` | — |
| `X-Request-Id` | Correlation id for logs (optional, ≤ 128 chars). Not signed. | no |
| `traceparent` | W3C trace context (optional). Not signed. | no |

Anything the receiving service relies on for business meaning (amounts, actor,
idempotency key) must travel **in the body** (which is signed) — not in unsigned headers.

## Canonical string

Seven lines joined with a single `\n` (LF, 0x0A). No trailing newline.

```
KARPY-HMAC-SHA256-V1
<key id>
<HTTP method, uppercase>
<path and query exactly as sent on the wire>
<timestamp>
<nonce>
<lowercase hex SHA-256 of the raw request body bytes>
```

Rules:

- **Path and query** is the request target as it appears on the HTTP request line
  (origin-form): the percent-encoded path, then `?` and the raw query string if the
  query is non-empty. Do not decode, re-encode, normalise, or sort. If the query is
  empty, omit the `?`. The path never includes scheme, host or fragment.
- If a reverse proxy rewrites or strips a path prefix, the signer must sign the path
  **the service will see**, or the proxy must not rewrite it. Prefer no rewriting.
- **Body hash** is computed over the exact bytes sent. Empty body →
  `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`.
- **Signature** = `hex(HMAC-SHA256(key = secret as UTF-8 bytes, message = canonical string as UTF-8))`.

## Verification (receiver)

1. All four `X-Karpy-*` headers present and well-formed, else `401 unauthorized`.
2. Key id is known (the service holds a *set* of keys), else `401`.
3. `|now - timestamp| <= 300 s` (configurable skew window), else `401`.
4. Read the body (with a size limit), recompute, compare with a **constant-time**
   comparison (`hmac.Equal`, `hmac.compare_digest`, `crypto.timingSafeEqual`), else `401`.
5. Reserve `(key id, nonce)` in a replay cache with a TTL of at least `2 × skew`.
   If already present → `409 request_replayed`. Only reserve after the signature is valid,
   so unauthenticated callers cannot fill the cache.
6. Never say *which* check failed in the response (log it server-side instead).

The replay cache is in-memory in the templates. With more than one replica use a shared
store, e.g. Redis `SET karpy:nonce:<key id>:<nonce> 1 NX EX 600`.

## Key rotation

Services accept a set: `KARPY_SERVICE_KEYS=keyid:secret,keyid2:secret2`. The caller signs
with exactly one active key id. To rotate:

1. Add the new key to the service's set and deploy (both keys valid).
2. Switch the caller's active key id/secret and deploy.
3. Remove the old key from the service's set after the skew window has passed.

Secrets must be at least 32 bytes of high-entropy data (`openssl rand -hex 32`).
Use a different key per caller → service pair.

## Test vectors

Test-only secrets — never reuse them.

### Vector 1 — POST with query

| Field | Value |
| --- | --- |
| key id | `test-key-1` |
| secret | `karpy-test-secret-do-not-use-in-production-0001` |
| method | `POST` |
| path and query | `/v1/echo?lang=en` |
| timestamp | `1767225600` (2026-01-01T00:00:00Z) |
| nonce | `4f1c2a9e8b7d6c5f4e3d2c1b0a998877` |
| body | `{"message":"hello"}` (19 bytes, no trailing newline) |
| body SHA-256 | `9b2d43affbf49a367028df2e1414f84c0e099ac98c3d54a8a80157fd7771af25` |

Canonical string:

```
KARPY-HMAC-SHA256-V1
test-key-1
POST
/v1/echo?lang=en
1767225600
4f1c2a9e8b7d6c5f4e3d2c1b0a998877
9b2d43affbf49a367028df2e1414f84c0e099ac98c3d54a8a80157fd7771af25
```

Expected header:

```
X-Karpy-Signature: v1=52dab664eee3776e6b6a4cdf9985636a6f9b07eb68e8d54231baf005b978dec6
```

### Vector 2 — GET, empty body, escaped path, second key

| Field | Value |
| --- | --- |
| key id | `test-key-2` |
| secret | `karpy-test-secret-rotated-key-do-not-use-0002` |
| method | `GET` |
| path and query | `/v1/items/a%20b?page=2&sort=-created_at` |
| timestamp | `1767225600` |
| nonce | `nonce-get-0000000000000001` |
| body | empty |

```
X-Karpy-Signature: v1=f7ab55b6f1db7e78e2d9a61eb1040e62152a4d3f41c0a4ed44da38c0fe9c2850
```

### Checking an implementation

- Python: `python services/contracts/signing_vectors.py`
- Go template: `go test ./...` in `services/go-template` (reads `signing-vectors.json`)
- Python client: `pytest services/python-client`

## mTLS alternative

On a private network you may additionally (or, for internal-only services, instead)
require mutual TLS: the service trusts a private CA and checks the client
certificate's SAN. HMAC remains the default because it works through any proxy and is
trivial to implement in every language; mTLS is transport-level and does not protect
against replay of a captured request inside the network. When both are used, keep HMAC.
