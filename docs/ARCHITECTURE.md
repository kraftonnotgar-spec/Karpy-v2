# Architecture

```
            ┌──────────────┐   ┌──────────────┐
 browsers → │  web/        │   │  mobile/     │ ← phones (Expo, iOS/Android)
            │  Next.js     │   │  bearer JWT  │
            └──────┬───────┘   └──────┬───────┘
     /api (rewrite, cookies)          │ /api/plugins/auth/mobile/v1 (+ bearer on other APIs)
                   ▼                  ▼
            ┌─────────────────────────────────┐
            │ backend/  KARPy (FastAPI)       │──── PostgreSQL (SQLite for quick local runs)
            │ core → packages → plugins       │──── Redis (cache, rate limits)
            │ hooks, ACL, settings, media     │
            └───────┬───────────────┬─────────┘
   signed HTTP (HMAC)│               │ events (outbox → RabbitMQ topic exchange)
                    ▼               ▼
            ┌──────────────────────────────┐
            │ services/  Go, Python, Node, │  each: OpenAPI contract, /healthz /readyz,
            │ Mojo…  (own DB if needed)    │  OTel traces, idempotent consumers
            └──────────────────────────────┘
```

## Layers

1. **Core** (`backend/karpy_platform/core`) — Botble `platform/core`: ACL (users, roles, permissions,
   admin MFA), base (models, hooks, responses, menus), dashboard (widgets, **admin console registry**),
   media (storage providers), settings (store, encryption, mailer, email templates), support (cache,
   cron, incidents, middleware), table builder, icons, charts.
2. **Packages** (`packages/`) — reusable CMS features: pages, menus, slugs, SEO, sitemap, revisions,
   themes, widgets, shortcodes (legacy), plugin management, installer, data import/export.
3. **Plugins** (`plugins/`) — features, each removable: `auth` (accounts, sessions, new-device codes,
   phone identities, mobile tokens, push devices), `social_login`, `location`, `contact`, `faq`,
   `payment` (gateway registry) + `manual_payment`, `speed` (Redis rate limits), `hello_world` (example).
4. **Product layer** — per project, outside core: brand config, tokens, catalogs, seed data and product
   plugins ([`NEW_PROJECT.md`](NEW_PROJECT.md)).

**Dependency rule:** product code may import core; core never imports product code. Core talks to
products through hooks, settings, registries and seed data.

## Backend boot (`backend/app/main.py`)

Typed env (`app/config.py`, pydantic-settings; production refuses weak secrets, SQLite and `*` CORS) →
migrations (`app/migrations`, numbered, checksummed) → middleware (security headers, trusted hosts,
CORS, request size, admin guard for `/api/admin`, rate limits) → core/package routers under
`/api/admin/...` and public routers → active plugins booted and mounted at `/api/plugins/<name>`.
Health: `/api/health` (liveness), `/api/ready` (database + migrations).

## Auth model

- **Web accounts:** HttpOnly cookie access + refresh tokens, rotation with reuse detection, trusted
  devices (signed cookie), new-device email (and optional SMS) codes, sessions list and revoke.
- **Admin:** separate signed session cookie, staff MFA (TOTP), admin guard on `/api/admin`.
- **Mobile:** same rules, tokens in JSON bodies, device-bound (see `plugins/auth/MOBILE_AUTH.md`).
- **Services:** HMAC-signed requests (`services/contracts/signing.md`).
- Product rules (who may sign up, extra alerts, SMS, integrity checks) plug in through
  `plugins/auth/extensions.py`.

## Web (`web/`)

Next.js App Router. `src/components/ui` = shadcn (unmodified). `src/core` = neutral composites,
config (zod), i18n catalogs, admin console (sidebar from `/api/admin/console/menu`, Overview from
`/api/admin/console/widgets`). `src/products/<p>` = brand tokens (`theme.css`), product manifest and
copy. `/api` is rewritten to the backend so cookies stay first-party.

## Mobile (`mobile/`)

Expo Router app: auth flow, app lock (PIN + biometrics), secure storage, light/dark tokens, TanStack
Query cache persisted for offline, network banner, push registration, crash reporter, tab shell.
See [`MOBILE.md`](MOBILE.md).

## Services (`services/`)

Other languages plug in over HTTP with signed requests and over RabbitMQ with a versioned event
envelope and a transactional outbox. See [`SERVICES.md`](SERVICES.md).

## Data and migrations

SQLAlchemy 2 async models on `app.database.Base`; string UUID ids. `v0001` creates the baseline schema
for every loaded model (fresh chain for Karpy-v2); `v0002` adds phone identities. Every later change is
a new `vNNNN_*.py` with `up`, `down`, `validate`; the runner records checksums and refuses edited files.

## Observability (optional)

Off by default. `docker compose --profile observability up -d` starts an OpenTelemetry collector,
Jaeger and Prometheus; the backend reads `OTEL_EXPORTER_OTLP_ENDPOINT` when instrumentation is added.
See [`INFRASTRUCTURE.md`](INFRASTRUCTURE.md).
