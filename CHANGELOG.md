# Changelog

All notable changes to the Karpy-v2 platform. Versions follow semantic versioning; projects built on
Karpy merge tagged releases only (see `docs/NEW_PROJECT.md`).

## [Unreleased] — 0.1.0

### Added
- `backend/`: KARPy platform (core, packages, neutral plugins: auth with mobile auth, social_login,
  location, contact, faq, payment, manual_payment, speed, hello_world; default theme; neutral tools).
- Payment notifications: admin alerts for payment received, payment failed, and new order/checkout
  across three channels (in-app feed, email, SMS). In-app rows live in a new `payment_notifications`
  table with an admin API (list, unread count, mark read) under `/api/plugins/payment/notifications`;
  email uses the core mailer and admin recipient list; SMS goes through a pluggable provider port with
  a default no-network log stub (`payment.notifications.sms_provider` filter swaps in a real vendor).
  Per-channel and per-event enablement, recipients, and templates are configured in the setting store
  (`payment.notifications.*`); email/SMS stay off until configured. Migration `v0003_payment_notifications`.
- Auth extension points (`plugins/auth/extensions.py`): sign-up policy, code messages, email layout,
  SMS client, account/admin alerts, security events, mobile access, mobile integrity, session end.
- Mobile push device registration (`POST/DELETE /api/plugins/auth/mobile/v1/push-devices`).
- Admin console registry: plugins declare menu sections (badges, nested submenus) and Overview widgets
  (`/api/admin/console/menu`, `/api/admin/console/widgets`); `hello_world` shows both.
- `web/`: Next.js + shadcn base with neutral tokens, i18n catalogs and an admin console built from the registry.
- `mobile/`: Expo starter (auth, new-device code, refresh, app lock, offline cache, push, crash reporter, tabs).
- `services/`: polyglot contract (OpenAPI, HMAC signing with test vectors, event envelope, outbox),
  stdlib Go template, Python signing client, observability configs.
- `tools/check_neutral.py`, `docker-compose.yml` (Postgres, Redis, RabbitMQ, optional observability profile),
  agent guides (`AGENTS.md`, `CLAUDE.md`) and docs.

### Changed
- Fresh migration chain: `v0001` baseline, `v0002` phone identities, `v0003` payment notifications.
- Trusted hosts: `INTERNAL_API_ORIGIN` (the internal origin the web/app layer uses to reach the backend,
  e.g. a container service URL) is trusted automatically, so containerized server-side calls no longer
  need manual `INTERNAL_TRUSTED_HOSTS`. Still fail-closed — no wildcard is ever added.
- Neutral names: cookies `app_login_challenge`, `app_trusted_device`, `app_login_resend`; user meta
  `account.restriction`, `account.restriction_reason`, `account.country_code`, `account.identity.status`;
  `APP_NAME` default `Karpy`; MFA issuer `<APP_NAME> Admin`.

### Removed
- All product-specific code (product plugins, gateway plugins, external platform integrations, their
  migrations, tools and tests).
