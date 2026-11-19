# Botble CMS / Laravel → Karpy map

KARPy is the owner's port of **Botble CMS** (Laravel) to Python. If you have built Botble plugins, you
already know where everything is. Paths are relative to `backend/karpy_platform/` unless stated.

## 1. KARPy = Botble CMS in Python

KARPy is a port of **Botble CMS** (Laravel) to **FastAPI + SQLAlchemy (async)**, keeping Botble's structure:
**core** (`platform/core`) → **packages** (`platform/packages`) → **plugins** (`platform/plugins`) → **themes**
(`platform/themes`). The roots are declared in `backend/karpy_platform/core/core.json`
(`packagesRoot`, `pluginsRoot`, `themesRoot`). If you know Botble, you know where things are.

All paths below are relative to `backend/karpy_platform/` and were checked in this repository.

### 1.1 Core modules

| Botble (`platform/core/…`) | KARPy | Notes |
|---|---|---|
| `base` | `core/base/` | `BaseModel` + `SlugMixin`/`StatusMixin`/`SeoMixin` (`models.py`), hooks (`hooks.py`), meta boxes (`meta_box.py`), admin menu (`dashboard_menu.py`), breadcrumbs, responses |
| `acl` | `core/acl/` | `User`, `Role`, `RoleUser`, `Activation`, `UserMeta` (`models.py`); `User.has_permission("key")`; admin guard middleware and staff MFA (`admin_guard.py`, `mfa.py`) |
| `media` | `core/media/` | Media files/folders; storage drivers behind `StorageProvider` (`storage.py`: local, BunnyCDN, S3-compatible) |
| `setting` | `core/setting/` | Settings store with dot keys (`store.py` `SettingStore`), settings panels registry (`registry.py`), mailer (`mailer.py`), email templates registry (`email_templates.py`) |
| `dashboard` | `core/dashboard/` | Dashboard widgets; `console.py` = admin console registry (plugin menu sections + Overview widgets) |
| `support` | `core/support/` | Repositories (`repositories.py` `AsyncRepository`, `CacheRepositoryDecorator`), cache (`cache.py`), cron (`cron.py`), backups, incidents, middleware |
| `icon` | `core/icon/` | Icon manager and drivers |
| `chart` | `core/chart/` | Chart builder |
| `js-validation` | `core/js_validation/` | Validation rules shared with the front end |
| `table` | `core/table/` | Admin table builder: columns, filters, actions, bulk actions |
| `security` | `core/security/` | `encrypt_secret` / `decrypt_secret` (Fernet) for secrets stored in settings |
| (artisan commands) | `core/console/` | CLI commands and generators (1.5) |

### 1.2 Packages

| Botble (`platform/packages/…`) | KARPy (`packages/…`) |
|---|---|
| `page` | `page/` |
| `menu` | `menu/` |
| `slug` | `slug/` |
| `seo-helper` | `seo_helper/` |
| `sitemap` | `sitemap/` |
| `widget` | `widget/` |
| `theme` | `theme/` |
| `plugin-management` | `plugin_management/` (`service.py` `PluginService`: install list, `activate`, `deactivate`, `remove`, `boot_active_plugins`, `get_plugin_routers`) |
| `shortcode` | `shortcode/` (`engine.py` `shortcode_engine.register(...)`) — legacy/compatibility; prefer typed content blocks for website pages |
| `revision` | `revision/` (model change history) |
| `optimize` | `optimize/` (middleware) |
| `get-started` | `get_started/` |
| `installer` | `installer/` |
| `data-synchronize` | `data_synchronize/` |

Botble packages not listed here are **not ported yet**.

### 1.3 Plugins and themes

| Botble | KARPy | Notes |
|---|---|---|
| `platform/plugins/contact`, `faq`, `location`, `payment`, `social-login` | `plugins/contact/`, `faq/`, `location/`, `payment/`, `social_login/` | Folder names use `_` instead of `-` |
| — | `plugins/auth/` | Customer accounts: sign-up, sessions, device codes, phone identities, mobile bearer tokens |
| — | `plugins/manual_payment/`, `plugins/speed/` | Manual payment methods; Redis rate limiting |
| — | `plugins/hello_world/` | The sample plugin: read it first |
| `platform/themes/<theme>` | `themes/default/` (`theme.json`, `layouts/`, `views/`, `public/`) | Server-rendered themes are optional; the main front end is Next.js in `web/` |

Other Botble plugins (ecommerce, blog, etc.) are **not ported yet**.

### 1.4 How a plugin works (Botble → KARPy)

| Botble | KARPy |
|---|---|
| `plugin.json` | `plugins/<name>/plugin.json` (`id`, `name`, `namespace`, `provider`, `version`, `required_plugins`, `minimum_core_version`, optional `settings` panel). Several plugins also keep the original `botble.plugin.json` |
| Service provider (`register()` / `boot()`) | `provider.py` (or `plugin.py`) class with static `activate()`, `deactivate()`, `remove()`, `boot()`, `get_routes() -> APIRouter`, `get_admin_menus()` |
| `routes/web.php`, `routes/api.php` | `get_routes()` router, mounted at `/api/plugins/<folder>/…` by `app/main.py` |
| `add_filter` / `apply_filters` | `hooks.add_filter(name, callback, priority=10)`, `hooks.apply_filters(name, value, …)`, `apply_filters_async` |
| `add_action` / `do_action` | `hooks.add_action(name, callback, priority=10)`, `hooks.do_action(name, …)`, `do_action_async` (from `core/base/hooks.py`) |
| `remove_filter`, `has_filter` … | `remove_filter`, `remove_action`, `has_filter`, `has_action`, `get_registered_filters/actions` |
| Activated plugins list | `karpy_platform/activated_plugins.json` |
| `database/migrations` in the plugin | `plugins/<name>/database/migrations/` (folder exists in scaffolds); platform-wide numbered migrations in `backend/app/migrations/versions/` |
| `DashboardMenu::registerItem()` | `dashboard_menu.default().register_item(DashboardMenuItem(...))` (`core/base/dashboard_menu.py`) |
| Settings panel registration | `core/setting/registry.py` (`SettingPanelRegistry.register_panel`, `register_section`) |
| Admin UI (Blade, `resources/views`) | Next.js admin in `web/src/app/admin`, built from `get_admin_sections()` / `get_overview_widgets()` ([`PLUGINS.md`](PLUGINS.md)) |

Minimal plugin, the Botble way:

```python
# plugins/greetings/provider.py
from fastapi import APIRouter
from karpy_platform.core.base.hooks import hooks

class GreetingsPlugin:
    @staticmethod
    def activate(): ...
    @staticmethod
    def deactivate(): ...
    @staticmethod
    def remove(): ...

    @staticmethod
    def boot():
        hooks.add_filter("page_content", lambda html: html.replace("[hi]", "Hello"))

    @staticmethod
    def get_routes() -> APIRouter:
        router = APIRouter()
        @router.get("/")
        async def index():
            return {"ok": True}
        return router

    @staticmethod
    def get_admin_menus() -> list[dict]:
        return [{"id": "greetings", "name": "Greetings", "icon": "smile", "url": "/admin/greetings", "priority": 50}]
```

### 1.5 `php artisan cms:…` → `python -m karpy_platform …`

Commands that exist today (`core/console/commands.py`):

| Botble | KARPy |
|---|---|
| `php artisan cms:plugin:create <name>` | `python -m karpy_platform plugin:create <Name> [--id vendor/name] [--author] [--version] [--description] [--quick] [--force]` |
| `php artisan cms:plugin:activate <name>` | `python -m karpy_platform plugin:activate <name>` |
| `php artisan cms:plugin:deactivate <name>` | `python -m karpy_platform plugin:deactivate <name>` |
| `make:model` + `make:controller` + `make:request` for a plugin | `python -m karpy_platform crud:create <Resource> --plugin <folder> [--force]` (model, schema, route and table stubs) |
| `php artisan migrate` | `python -m app.migrations up` (also run at start-up) |
| `php artisan schedule:run` | `python -m karpy_platform.core.support.cron run` |

**Not ported yet:** seeders (`db:seed`), queue workers, `cache:clear` as a CLI command (cache tools are in the admin API), theme and package generators.

---

## 2. Laravel → FastAPI concepts (short map)

| Laravel | Here | Difference to remember |
|---|---|---|
| Routes + controllers | FastAPI `APIRouter` per plugin (`get_routes()`); route functions are the controllers | Handlers are `async def`; return dicts/Pydantic models, JSON by default |
| Form Requests / validation | Pydantic models (`schemas.py` / `schemas/` in plugins) | Validation runs before your function; errors are `422` unless mapped |
| Eloquent models / relations | SQLAlchemy 2 models on `app.database.Base` / `core/base/models.py` `BaseModel`; `relationship()` | Async session: `await db.execute(select(User).where(...))`; no lazy loading by accident — use `selectinload` |
| Repositories | `core/support/repositories.py` `AsyncRepository` | |
| Migrations | Numbered files `backend/app/migrations/versions/vNNNN_*.py` with `async def up(connection)` | Never edit an applied file; checksums are checked at boot |
| Seeders / factories | **Not ported yet** — planned: product seed files + seed command; test fixtures in `tests/fixtures/` | |
| Service container / providers | Plugin provider classes + plain imports; FastAPI `Depends()` for per-request things | No global container; dependencies are function parameters |
| Middleware | Starlette middleware (`app.add_middleware(...)` in `app/main.py`, e.g. `AdminAuthMiddleware`, `SpeedRateLimitMiddleware`) or route dependencies | Prefer a dependency for per-route rules |
| Auth guards / Sanctum / session | `plugins/auth/security.py`: HttpOnly cookie sessions, `current_user` dependency, `mobile_bearer_claims` for mobile bearer tokens | `user: User = Depends(current_user)` |
| Policies / gates | ACL permission keys: `user.has_permission("key")`; staff routes behind `AdminAuthMiddleware` | Declare keys in the plugin; check on the server |
| `config()` / `.env` | `app/config.py` (`pydantic-settings` `Settings`, env) + settings store (`core/setting/store.py`) for admin-editable values | Typed; invalid env fails at start |
| Cache / Redis | `core/support/cache.py`; Redis rate limits in `plugins/speed/rate_limiter.py` | Response/session caching in Redis is planned |
| Queues / jobs / Horizon | **Not ported yet** — RabbitMQ outbox + workers: contract in [`SERVICES.md`](SERVICES.md) | |
| Events / listeners | `hooks.do_action` / `add_action` (in-process); durable events via an outbox — planned | In-process hooks are lost on crash; use the outbox for anything that must happen |
| Notifications / Mail | `core/setting/mailer.py` + `email_templates.py`; SMS via the `auth.sms_client` hook; push devices in `plugins/auth` (sending by a provider plugin) | |
| Storage | `core/media/` (`StorageProvider`, local VPS) | |
| Scheduler / cron | `core/support/cron.py` (`python -m karpy_platform.core.support.cron run`) | Scheduled workers on RabbitMQ planned |
| Artisan | `python -m karpy_platform …` (1.5) | |
| Blade / Livewire / Inertia | Next.js in `web/` calling the API (`/api` proxied) | The backend is API-first |
| Telescope / logging | Python `logging`, incidents (`core/support/incidents.py`), model revisions (`packages/revision`); audit log planned | |
| PHPUnit / Pest | `pytest` (`backend/pytest.ini`), many tests use `unittest.IsolatedAsyncioTestCase` | |

Tiny example — a validated, authenticated, permission-checked endpoint:

```python
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from karpy_platform.plugins.auth.security import current_user

router = APIRouter()

class RenameIn(BaseModel):          # FormRequest
    name: str

@router.post("/items/{item_id}/rename")
async def rename(item_id: str, data: RenameIn,
                 user=Depends(current_user),              # auth guard
                 db: AsyncSession = Depends(get_db)):     # injected session
    if not user.has_permission("items.edit"):              # gate
        raise HTTPException(403, "forbidden")
    ...
```
