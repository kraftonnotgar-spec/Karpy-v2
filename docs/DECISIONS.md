# Decisions

Short records: context → decision → consequences. Newest last.

## D-001 · Karpy-v2 is the product-neutral starter (Nov 2026)
**Context.** The owner builds many products on KARPy (his Python port of Botble CMS). Earlier products
copied KARPy and carried each other's names and code.
**Decision.** Karpy-v2 holds only the neutral platform: backend core, packages and neutral plugins; a
neutral Next.js base; a neutral Expo starter; the polyglot services contract. Products start from it
([`NEW_PROJECT.md`](NEW_PROJECT.md)) and keep it as `upstream`.
**Consequences.** No product names in core (`tools/check_neutral.py`); brand from env/settings/tokens.

## D-002 · Product rules plug into auth through hooks (Nov 2026)
**Context.** The copied sign-in, sign-up, mobile and admin sign-in flows called one product's modules
(policy, notification center, SMS providers, alerts, attack detection, app integrity).
**Decision.** Replace each call with a neutral extension point in `plugins/auth/extensions.py`
(filters/actions on KARPy's hook system) with safe defaults: sign-up open by env/settings, codes by
email from the auth email templates, SMS only when a provider plugin registers `auth.sms_client`, no-op
alerts and integrity checks.
**Consequences.** Sign-in/registration work with no product installed; a product restores its rules by
registering hooks in its plugin `boot()`.

## D-003 · Plugins declare admin menu sections and Overview widgets (Nov 2026)
**Context.** The owner wants plugins to appear in the admin like the platform-admin console he already
uses: sections with badges and nested submenus, and an Overview built from widgets.
**Decision.** `core/dashboard/console.py` collects `get_admin_sections()` / `get_overview_widgets()`
from active plugins, validates them (Pydantic), filters by the admin's permissions and serves them at
`/api/admin/console/menu|widgets`. The web renders generic components; plugins ship data + metadata.
**Consequences.** Activating/deactivating a plugin changes the admin with no web change.

## D-004 · Fresh migration chain (Nov 2026)
**Decision.** `v0001` = baseline schema of all loaded models, `v0002` = phone identities. Product
schema migrations are not carried over. Every later change is a new numbered migration.

## D-005 · Services in other languages use signed HTTP + RabbitMQ events (Nov 2026)
**Decision.** OpenAPI contracts, HMAC-SHA256 signed requests (`KARPY-HMAC-SHA256-V1`), a versioned event
envelope with a transactional outbox and idempotent consumers, `/healthz` + `/readyz`, OpenTelemetry.
A stdlib-only Go template proves the contract ([`SERVICES.md`](SERVICES.md)).

## D-006 · Mobile push registration is part of auth (Nov 2026)
**Decision.** `auth_push_devices` stores one provider-neutral token per app installation
(`expo`/`fcm`/`apns`); sending belongs to a push provider plugin. A closed account's device is removed.
