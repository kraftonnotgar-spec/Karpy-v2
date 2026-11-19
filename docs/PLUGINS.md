# Plugins and hooks

Everything a project adds to Karpy is a **plugin**, written the Botble way: a manifest, a provider
class with lifecycle methods, hooks, its own routes, models and migrations. Core files are never
edited for one product. The reference plugin is
[`backend/karpy_platform/plugins/hello_world/plugin.py`](../backend/karpy_platform/plugins/hello_world/plugin.py).

## 1. Anatomy

```
backend/karpy_platform/plugins/<name>/
├─ plugin.json          manifest: id, name, provider (module), version, required_plugins, minimum_core_version
├─ provider.py          provider class (or plugin.py, as in hello_world)
├─ routes.py            FastAPI router (mounted at /api/plugins/<name>/…)
├─ models/              SQLAlchemy models (on app.database.Base)
├─ schemas/             Pydantic request/response models (Botble FormRequests)
├─ services/            business logic
├─ database/migrations/ plugin migrations (platform-wide ones live in backend/app/migrations/versions/)
└─ tests/ or test_*.py  pytest
```

Scaffold: `python -m karpy_platform plugin:create Greetings` (Botble `cms:plugin:create`), then
`python -m karpy_platform plugin:activate greetings`. The active list is
`backend/karpy_platform/activated_plugins.json`; routes of active plugins are mounted at start-up.

### Provider contract

| Method | When | Botble equivalent |
|---|---|---|
| `activate()` / `deactivate()` / `remove()` | admin or CLI changes the plugin's state | `PluginServiceProvider` activate hooks |
| `boot()` | every start-up, for active plugins: register hooks, shortcodes, settings panels | `boot()` |
| `get_routes() -> APIRouter` | start-up; mounted at `/api/plugins/<folder>` | `routes/*.php` |
| `get_admin_sections() -> list[dict]` | each admin page load (web sidebar) | `DashboardMenu::registerItem` |
| `get_overview_widgets() -> list[dict]` | admin Overview page | dashboard widgets |
| `get_admin_menus() -> list[dict]` | legacy KARPy admin menu (`dashboard_menu`) | `DashboardMenu` |

## 2. Hooks (`core/base/hooks.py`)

Botble/WordPress-style, priority ordered (lower runs first), sync or async callbacks:

```python
from karpy_platform.core.base.hooks import hooks

hooks.add_filter("page_content", lambda html: html.replace("[year]", "2026"), priority=10)
html = hooks.apply_filters("page_content", html)                 # sync callers
html = await hooks.apply_filters_async("page_content", html)     # async callers

hooks.add_action("plugin_activated", on_activated)
hooks.do_action("plugin_activated", "greetings")
await hooks.do_action_async("order.paid", order_id)

hooks.remove_filter(...); hooks.remove_action(...); hooks.has_filter(...); hooks.has_action(...)
```

In-process hooks are not durable: for work that must happen even after a crash, write an outbox row
and publish an event (see [`SERVICES.md`](SERVICES.md)).

### Hooks the platform calls

| Hook | Kind | Arguments → result | Default |
|---|---|---|---|
| `auth.policy` | filter | `(AuthPolicy, db) → AuthPolicy` (registration open, terms, phone countries) | from `auth.*` settings / env |
| `auth.message` | filter | `(None, db, event, channel, language, variables, settings) → {"subject","html","text"}` | auth plugin email templates |
| `auth.email_layout` | filter | `(None, subject, text, settings) → {"subject","html","text"}` | simple HTML |
| `auth.sms_client` | filter | `(None, db) → client with async send_sms(phone, text, ref, otp=True)` | none (email only) |
| `auth.account_alert` / `auth.admin_alert` | filter | `(False, db, …) → bool handled` | not handled |
| `auth.mobile.allow_user` | filter | `(allowed, user) → bool` | staff refused unless `AUTH_MOBILE_ALLOW_STAFF` |
| `auth.security_event` | action | `(event, ip, identity)` — brute-force / attack detection | — |
| `auth.failed_sign_in` | action (sync) | `(request, area, identity, account_exists)` | — |
| `auth.before_session` | action | `(db, user, request_id)` | — |
| `auth.account_registered` | action | `(db, user_id)` inside the sign-up transaction | — |
| `auth.account_signal` | action | `(user_ids)` after commit | — |
| `auth.login_code.requested` / `.delivered` | action | delivery evidence (no codes) | — |
| `auth.mobile.integrity` | action | `(db, request, purpose, platform, installation, user_id)`; raise `HTTPException` to refuse | — |
| `auth.mobile.session_ended` | action | `(db, user_id, reason, session_id)` | — |
| `acl.admin_signed_in` | action | `(db, user_id, ip, user_agent)` | — |
| `acl.console_flags` | filter | `(list[str]) → list[str]` permission keys that admit staff to the admin | `[]` |
| `mail.branded_layout` | filter | `(None, subject, text, settings) → dict | None` for contact/test emails | legacy template |
| `admin.console.sections` / `admin.console.widgets` | filter | final lists before permission filtering | — |
| `plugin_activated` | action | `(plugin_name)` | — |

Full docstring: [`plugins/auth/extensions.py`](../backend/karpy_platform/plugins/auth/extensions.py).

## 3. Admin console: menu sections and Overview widgets

The web admin (`web/src/app/admin`) has no hardcoded plugin pages in its navigation. It asks the
backend which sections and widgets exist for the signed-in admin:

- `GET /api/admin/console/menu` → `{"sections": [...]}`
- `GET /api/admin/console/widgets` → `{"widgets": [...]}`

Only **active** plugins are asked (deactivate a plugin and it disappears), and every section, item and
widget with a `permission` is hidden from admins who lack it. Registry and schemas:
[`core/dashboard/console.py`](../backend/karpy_platform/core/dashboard/console.py).

### Menu section

```python
{
  "id": "shop",                     # [a-z0-9._-]
  "label": "shop.section",          # i18n key (web catalogs) …
  "label_default": "Shop",          # … and English fallback
  "icon": "store",                  # lucide icon name
  "priority": 100,                  # order in the sidebar
  "permission": None,               # optional, for the whole section
  "items": [
    {"id": "shop.orders", "label": "shop.menu.orders", "label_default": "Orders", "icon": "receipt",
     "route": "/admin/shop/orders", "permission": "shop.orders.view",
     "badge": {"endpoint": "/api/plugins/shop/admin/orders/pending-count", "tone": "attention"}},
    {"id": "shop.catalog", "label": "shop.menu.catalog", "label_default": "Catalog", "icon": "package",
     "permission": "shop.catalog.view",
     "children": [                  # nested slide-in submenu
       {"id": "shop.catalog.products", "label": "shop.menu.products", "label_default": "Products", "route": "/admin/shop/products"},
       {"id": "shop.catalog.categories", "label": "shop.menu.categories", "label_default": "Categories", "route": "/admin/shop/categories"}]}
  ]
}
```

The sidebar shows the **Workspace** (Overview + one entry per section). Opening a section slides in its
panel with **Back to Workspace**; an item with `children` slides in a nested submenu. A badge
`endpoint` answers `GET` with `{"count": <int>}` for the signed-in admin; the count shows when > 0.
Two plugins may add items to the same section id (items are merged).

### Overview widget

```python
{"id": "shop.revenue", "type": "kpi", "title": "shop.widgets.revenue", "title_default": "Revenue",
 "endpoint": "/api/plugins/shop/admin/stats/revenue", "size": "sm", "permission": "shop.reports.view",
 "order": 10, "options": {}}
```

`type` ∈ `kpi`, `area_chart`, `line_chart`, `bar_chart`, `list`, `todo`; `size` ∈ `sm`, `md`, `lg`, `full`.
The Overview page calls `GET <endpoint>?from=YYYY-MM-DD&to=YYYY-MM-DD` (its date-range filter) and
renders the core component for the type with its own loading, empty and error states. Data shapes:

| type | response |
|---|---|
| `kpi` | `{"value": 1234, "previous": 1100, "format": "number" \| "currency" \| "percent"}` |
| `area_chart`, `line_chart`, `bar_chart` | `{"series": [{"key": "orders", "label": "<i18n key>"}], "points": [{"x": "2026-11-01", "orders": 12}]}` |
| `list` | `{"items": [{"id", "title", "subtitle"?, "href"?, "meta"?}]}` |
| `todo` | `{"items": [{"id", "label", "count", "href"}]}` |

Plugins provide **data + metadata only**; the web renders every widget with core components and
design tokens, so a plugin never ships web code to appear on the Overview.

## 4. Complete example: `hello_world`

[`plugins/hello_world/plugin.py`](../backend/karpy_platform/plugins/hello_world/plugin.py) (abridged):

```python
PERMISSION = "hello_world.view"

class HelloWorldPlugin:
    @staticmethod
    def boot():
        hooks.add_action("plugin_activated", HelloWorldPlugin._on_any_plugin_activated)
        hooks.add_filter("acl.console_flags", HelloWorldPlugin._console_flags)   # grantable admin permission

    @staticmethod
    def get_routes() -> APIRouter:
        router = APIRouter()

        @router.get("/admin/pending-count")                 # badge source
        async def pending_count(_user=Depends(admin_only)):
            return {"count": 3}

        @router.get("/admin/stats/greetings")              # kpi widget data
        async def greetings_kpi(start: date | None = Query(None, alias="from"),
                                end: date | None = Query(None, alias="to"), _user=Depends(admin_only)):
            return {"value": 360, "previous": 300, "format": "number"}

        @router.get("/admin/stats/greetings-by-day")       # area chart data
        async def greetings_by_day(...):
            return {"series": [{"key": "greetings", "label": "hello_world.widgets.greetings"}],
                    "points": [{"x": "2026-11-01", "greetings": 12}, ...]}
        return router

    @staticmethod
    def get_admin_sections():
        return [{"id": "hello", "label": "hello_world.section", "label_default": "Hello World", "icon": "smile",
                 "items": [
                   {"id": "hello.inbox", "label": "hello_world.menu.inbox", "label_default": "Greetings inbox",
                    "icon": "inbox", "route": "/admin/hello/inbox", "permission": PERMISSION,
                    "badge": {"endpoint": "/api/plugins/hello_world/admin/pending-count", "tone": "attention"}},
                   {"id": "hello.library", "label": "hello_world.menu.library", "label_default": "Greeting library",
                    "icon": "library", "permission": PERMISSION, "children": [
                      {"id": "hello.library.templates", "label": "hello_world.menu.templates",
                       "label_default": "Templates", "route": "/admin/hello/templates", "permission": PERMISSION},
                      {"id": "hello.library.languages", "label": "hello_world.menu.languages",
                       "label_default": "Languages", "route": "/admin/hello/languages", "permission": PERMISSION}]}]}]

    @staticmethod
    def get_overview_widgets():
        return [
          {"id": "hello.greetings_total", "type": "kpi", "title": "hello_world.widgets.greetings_total",
           "title_default": "Greetings sent", "endpoint": "/api/plugins/hello_world/admin/stats/greetings",
           "size": "sm", "permission": PERMISSION, "order": 10},
          {"id": "hello.greetings_by_day", "type": "area_chart", "title": "hello_world.widgets.greetings_by_day",
           "title_default": "Greetings per day", "endpoint": "/api/plugins/hello_world/admin/stats/greetings-by-day",
           "size": "lg", "permission": PERMISSION, "order": 20},
        ]
```

Proof that it appears when active and disappears when deactivated:
[`core/dashboard/test_console.py`](../backend/karpy_platform/core/dashboard/test_console.py).

## 5. Checklist for a new plugin

1. `plugin:create`, fill `plugin.json` (`required_plugins` for dependencies).
2. Models + a numbered migration for every table/column; never edit an applied migration.
3. Pydantic schemas for input; routes check permissions server-side (`user.has_permission("key")`).
4. Permission keys declared and grantable (`acl.console_flags` filter for admin keys).
5. Settings through the settings store (`core/setting/store.py`), secrets encrypted
   (`core/security/secrets.py`) — never in code or seed files.
6. Admin: `get_admin_sections()` / `get_overview_widgets()`; add the i18n keys to
   `web/src/core/i18n/messages/*.json` (or the product's catalogs).
7. External providers behind a hook or port with a fake for tests.
8. Tests; `python tools/check_neutral.py` green.
