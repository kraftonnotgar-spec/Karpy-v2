# Karpy-v2

A clean, product-neutral platform to start every new project from:

- **`backend/`** — KARPy, Botble CMS ported to Python (FastAPI + SQLAlchemy): core, packages, plugins,
  themes, hooks, ACL, settings, media, numbered migrations, web + mobile authentication.
- **`web/`** — Next.js + shadcn front end with design tokens, i18n catalogs and an admin console that
  builds its menu and Overview from the plugins that are active.
- **`mobile/`** — Expo starter: sign-in, new-device codes, token refresh, PIN/biometric lock, offline
  cache, push registration, crash reporter, tab shell.
- **`services/`** — how services in Go, Python, Node, Mojo… plug in: OpenAPI contracts, signed requests,
  RabbitMQ events, health, OpenTelemetry; a ready Go service template.

Nothing here belongs to one product. Each project adds a thin product layer (brand, tokens, copy, seed
data, product plugins) and keeps this repository as `upstream` — see [`docs/NEW_PROJECT.md`](docs/NEW_PROJECT.md).

## Quick start

```bash
cp .env.example .env && docker compose up -d          # Postgres, Redis, RabbitMQ

cd backend && python3.12 -m venv .venv && .venv/bin/python -m pip install -r requirements-test.txt
cp .env.example .env && .venv/bin/python -m uvicorn app.main:app --port 9000

cd web && cp .env.example .env.local && npm install && npm run dev      # http://localhost:3000
cd mobile && cp .env.example .env && npm install && npx expo start
```

## Read next

| | |
|---|---|
| [`AGENTS.md`](AGENTS.md) | Repo map, commands, rules — for AI agents and people |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | How the parts fit |
| [`docs/PLUGINS.md`](docs/PLUGINS.md) | Plugin contract, hooks, admin menu sections and Overview widgets, example |
| [`docs/BOTBLE_MAPPING.md`](docs/BOTBLE_MAPPING.md) | Botble/Laravel → KARPy |
| [`docs/SERVICES.md`](docs/SERVICES.md) | Services in other languages |
| [`docs/MOBILE.md`](docs/MOBILE.md) | Mobile starter and its API |
| [`docs/NEW_PROJECT.md`](docs/NEW_PROJECT.md) | Start a project from Karpy-v2 |
| [`docs/INFRASTRUCTURE.md`](docs/INFRASTRUCTURE.md) | Optional monitoring module |
| [`docs/DECISIONS.md`](docs/DECISIONS.md), [`CHANGELOG.md`](CHANGELOG.md) | Decisions and releases |
