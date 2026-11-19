# Karpy-v2 — guide for AI agents and developers

Karpy-v2 is a **product-neutral starter platform**. Every new project (a directory, a shop, a booking
app…) starts from it and adds only a thin product layer. The backend is **KARPy: Botble CMS ported to
Python** (FastAPI + SQLAlchemy async), with Botble's structure: core → packages → plugins → themes.
If you know Botble/Laravel, read [`docs/BOTBLE_MAPPING.md`](docs/BOTBLE_MAPPING.md) first.

## Repository map

| Folder | What | Start here |
|---|---|---|
| `backend/` | KARPy API (FastAPI, SQLAlchemy 2 async, numbered migrations, plugin system, ACL, media, settings) | [`backend/README.md`](backend/README.md) |
| `backend/karpy_platform/core/` | Kernel (Botble `platform/core`): acl, base (hooks, models), dashboard (admin console registry), media, setting, support, table… | |
| `backend/karpy_platform/packages/` | Botble packages: page, menu, slug, seo_helper, sitemap, revision, theme, widget, plugin_management… | |
| `backend/karpy_platform/plugins/` | Neutral plugins: auth (web + mobile), social_login, location, contact, faq, payment, manual_payment, speed, hello_world (the example) | [`docs/PLUGINS.md`](docs/PLUGINS.md) |
| `web/` | Next.js + shadcn front end: public site, account dashboard, admin console built from the plugin registry | [`web/README.md`](web/README.md) |
| `mobile/` | Expo starter: sign-in, new-device code, refresh, PIN/biometric lock, offline cache, push, tabs | [`mobile/README.md`](mobile/README.md), [`docs/MOBILE.md`](docs/MOBILE.md) |
| `services/` | Services in other languages (Go template, contracts, signing, events) | [`services/README.md`](services/README.md), [`docs/SERVICES.md`](docs/SERVICES.md) |
| `tools/` | `check_neutral` (no product names / raw colours in core) | [`tools/README.md`](tools/README.md) |
| `docs/` | Architecture, plugins, Botble mapping, services, mobile, new project, infrastructure, decisions | [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) |

## Commands

```bash
docker compose up -d                                  # Postgres, Redis, RabbitMQ (127.0.0.1 only)

# backend (Python 3.12)
cd backend
python3.12 -m venv .venv && .venv/bin/python -m pip install -r requirements-test.txt   # Windows: .venv\Scripts\python
cp .env.example .env
.venv/bin/python -m app.migrations up                 # also runs at start-up
.venv/bin/python -m uvicorn app.main:app --port 9000  # /api/health, /api/ready, /docs (dev)
.venv/bin/python -m pytest -q                         # full suite (~6 min)
.venv/bin/python -m karpy_platform plugin:create Greetings   # scaffold a plugin (Botble cms:plugin:create)
.venv/bin/python -m karpy_platform plugin:activate hello_world

# web (Node 20+)
cd web && npm install && npm run dev                  # http://localhost:3000, /api proxied to API_ORIGIN
npm run typecheck && npm run lint && npm run build

# mobile (Expo)
cd mobile && npm install && npx expo start
npx tsc --noEmit && npm run lint && npm test

# Go service template
cd services/go-template && go vet ./... && go test ./...

# neutrality check (run before every commit)
python tools/check_neutral.py
```

## Rules (all parts)

1. **No hardcoding.** Brand name, texts, lists, numbers that are business decisions, URLs, providers
   and feature flags come from settings, env (`backend/app/config.py`, typed and validated at boot),
   seed data or message catalogs — never literals in code. Magic numbers become named config fields.
2. **Product-neutral core.** No product names in `backend/app`, `backend/karpy_platform`, `web/src`
   (outside `web/src/products/`), `mobile/src`, `services/`. `tools/check_neutral.py` enforces it.
   Product code lives in a product layer (`web/src/products/<p>/`, product plugins); core never imports it.
3. **Plugins the Botble way.** New features are plugins: `plugin.json` manifest + provider class with
   `activate/deactivate/remove/boot/get_routes` (+ `get_admin_sections`, `get_overview_widgets` for the
   admin). Extend other code with hooks (`hooks.add_filter` / `hooks.add_action`), settings or registry
   entries — never by editing core files for one product. See [`docs/PLUGINS.md`](docs/PLUGINS.md).
4. **Design tokens only.** Web: shadcn components in `web/src/components/ui` stay unmodified; colours
   and fonts only through CSS variables whose values live in `web/src/products/<p>/theme.css`.
   Mobile: colours only from `mobile/src/theme`. No raw hex in components.
5. **UI text from catalogs.** Web `web/src/core/i18n/messages/*.json` (+ product overrides); mobile
   `mobile/src/i18n`. Backend errors return stable codes/messages.
6. **Migrations for every data change.** New numbered file in `backend/app/migrations/versions/`
   (`vNNNN_name.py`, `up`/`down`/`validate`); never edit an applied migration (checksums are checked at boot).
7. **Every external service behind a port/hook** with a fake for tests (see `plugins/auth/extensions.py`
   for the pattern).
8. **Secrets never in git**: only `.env.example` files are tracked. No keys, tokens, databases, media,
   `node_modules`, server addresses or personal data in commits.
9. **Tests**: add or update tests with every change; backend `pytest`, web typecheck/lint/build,
   mobile tsc/lint/tests, Go `go test`.
10. **Commits**: plain, descriptive messages. **No AI attribution lines** (no `Co-Authored-By` for AI
    tools, no "generated with" footers).

## Where things are wired

- Auth extension points (sign-up policy, messages, SMS, alerts, mobile access, integrity): `backend/karpy_platform/plugins/auth/extensions.py`.
- Admin menu sections + Overview widgets from plugins: `backend/karpy_platform/core/dashboard/console.py`, served at `GET /api/admin/console/menu` and `/api/admin/console/widgets`; rendered by `web/src/core/admin/`.
- Mobile auth contract: `backend/karpy_platform/plugins/auth/MOBILE_AUTH.md`.
- Service-to-service signing: `services/contracts/signing.md`.
