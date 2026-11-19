# backend — KARPy (Botble CMS in Python)

FastAPI + SQLAlchemy 2 (async) platform with Botble's structure. Map for Botble/Laravel developers:
[`../docs/BOTBLE_MAPPING.md`](../docs/BOTBLE_MAPPING.md). Plugins and hooks: [`../docs/PLUGINS.md`](../docs/PLUGINS.md).

```
app/                    boot (main.py), typed env (config.py), database, HTTP security, migrations/
karpy_platform/
  core/                 acl, base (hooks, models), dashboard (+ console.py: admin console registry), media,
                        setting, support, table, icon, chart, js_validation, security, console (CLI generators)
  packages/             page, menu, slug, seo_helper, sitemap, revision, theme, widget, shortcode,
                        plugin_management, installer, get_started, optimize, data_synchronize
  plugins/              auth, social_login, location, contact, faq, payment, manual_payment, speed, hello_world
  themes/default/       server-rendered theme (optional)
  activated_plugins.json
tools/                  release_migration_acceptance.py, karpy-windows-connector, karpy-terminal-pool
```

## Run

Python **3.12** (pinned wheels are not available for 3.14).

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements-test.txt     # Windows: .venv\Scripts\python
cp .env.example .env                                         # set SECRET_KEY, JWT_SECRET, ADMIN_BOOTSTRAP_PASSWORD
.venv/bin/python -m app.migrations up                        # also runs at start-up
.venv/bin/python -m uvicorn app.main:app --port 9000
```

Without `DATABASE_URL` a local SQLite file (`karpy.db`, git-ignored) is used. Health: `/api/health`,
readiness: `/api/ready`, OpenAPI docs: `/docs` (development only).

## Test

```bash
.venv/bin/python -m pytest -q                 # whole suite (~6 minutes)
.venv/bin/python -m pytest -q karpy_platform/plugins/auth
```

## CLI (Botble artisan → KARPy)

```bash
python -m karpy_platform plugin:create Greetings      # scaffold (manifest, provider, routes, admin section stub)
python -m karpy_platform plugin:activate greetings
python -m karpy_platform plugin:deactivate greetings
python -m karpy_platform crud:create Item --plugin greetings
python -m app.migrations up                           # php artisan migrate
python -m karpy_platform.core.support.cron run        # php artisan schedule:run
```

## Key places

- Env reference: `app/config.py` (every variable typed with a default; production rejects weak values).
- Auth flows: `plugins/auth/routes.py` (web), `mobile_routes.py` ([`MOBILE_AUTH.md`](karpy_platform/plugins/auth/MOBILE_AUTH.md)),
  `device_verification.py` (new-device codes), extension points `extensions.py`.
- Admin sign-in, roles, permissions, staff MFA: `core/acl/`.
- Admin console registry (plugins' menu sections and Overview widgets): `core/dashboard/console.py`,
  endpoints `GET /api/admin/console/menu` and `/api/admin/console/widgets`.
- Migrations: `app/migrations/versions/` (`v0001` baseline, `v0002` phone identities).

## Docker

`Dockerfile` (Python 3.12 slim, non-root, health check). Build from this folder:
`docker build -t karpy-backend .`
