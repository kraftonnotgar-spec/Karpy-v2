"""
Hello World -- the sample KARPy plugin. Read it first (docs/PLUGINS.md walks through it).

It shows every extension point a plugin normally uses:
1. ``plugin.json`` manifest (id, provider, version, dependencies)
2. Lifecycle: ``activate()``, ``deactivate()``, ``remove()``, ``boot()``
3. Hooks (Botble ``add_action`` / ``add_filter``) and a shortcode, registered in ``boot()``
4. API routes: ``get_routes()`` -> mounted at ``/api/plugins/hello_world/...``
5. Admin console: ``get_admin_sections()`` (a sidebar section with a badge and a submenu)
   and ``get_overview_widgets()`` (a KPI tile and an area chart on the admin Overview)

Activate / deactivate: ``python -m karpy_platform plugin:activate hello_world`` (or the admin
Plugins page). When deactivated, its menu section and widgets disappear from the admin.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db

logger = logging.getLogger("karpy.plugins.hello_world")

PERMISSION = "hello_world.view"


async def admin_only(request: Request, db: AsyncSession = Depends(get_db)):
    """Widget and badge data are for signed-in admins with this plugin's permission."""
    from fastapi import HTTPException

    from karpy_platform.core.acl.routes import current_admin_user

    user = await current_admin_user(request, db)
    if not user.has_permission(PERMISSION):
        raise HTTPException(403, "forbidden")
    return user


def _days(start: date, end: date) -> list[date]:
    count = max(0, min((end - start).days, 366))
    return [start + timedelta(days=offset) for offset in range(count + 1)]


class HelloWorldPlugin:
    @staticmethod
    def activate():
        logger.info("Hello World plugin activated")

    @staticmethod
    def deactivate():
        logger.info("Hello World plugin deactivated")

    @staticmethod
    def remove():
        logger.info("Hello World plugin removed")

    @staticmethod
    def boot():
        """Called at start-up for active plugins: register hooks, shortcodes, settings panels."""
        from karpy_platform.core.base.hooks import hooks
        from karpy_platform.packages.shortcode.engine import shortcode_engine

        shortcode_engine.register(
            key="hello",
            name="Hello Greeting",
            description="Displays a greeting message. Usage: [hello name='World']",
            callback=HelloWorldPlugin._render_hello_shortcode,
        )
        hooks.add_action("plugin_activated", HelloWorldPlugin._on_any_plugin_activated)
        # Make this plugin's permission count as an admin console permission (acl.console_flags filter).
        hooks.add_filter("acl.console_flags", HelloWorldPlugin._console_flags)

    @staticmethod
    def _console_flags(flags: list[str]) -> list[str]:
        return [*flags, PERMISSION]

    @staticmethod
    def _render_hello_shortcode(shortcode, content):
        from html import escape

        name = escape(str(shortcode.get("name", "World")))
        return f'<div class="hello-widget"><h2>Hello, {name}!</h2></div>'

    @staticmethod
    def _on_any_plugin_activated(plugin_name, *args):
        logger.info("Hello World noticed that %r was activated", plugin_name)

    @staticmethod
    def get_routes() -> APIRouter:
        router = APIRouter()

        @router.get("/")
        async def hello_index():
            return {"message": "Hello from the Hello World plugin"}

        @router.get("/greet/{name}")
        async def hello_greet(name: str):
            return {"greeting": f"Hello, {name}!"}

        # Badge source: {"count": n}. A real plugin counts rows that need attention.
        @router.get("/admin/pending-count")
        async def pending_count(_user=Depends(admin_only)):
            return {"count": 3}

        # KPI widget data.
        @router.get("/admin/stats/greetings")
        async def greetings_kpi(
            start: date | None = Query(default=None, alias="from"),
            end: date | None = Query(default=None, alias="to"),
            _user=Depends(admin_only),
        ):
            end = end or date.today()
            days = len(_days(start or end - timedelta(days=29), end))
            return {"value": days * 12, "previous": days * 10, "format": "number"}

        # Area chart widget data.
        @router.get("/admin/stats/greetings-by-day")
        async def greetings_by_day(
            start: date | None = Query(default=None, alias="from"),
            end: date | None = Query(default=None, alias="to"),
            _user=Depends(admin_only),
        ):
            end = end or date.today()
            points = [{"x": day.isoformat(), "greetings": 8 + (day.toordinal() % 7) * 2}
                      for day in _days(start or end - timedelta(days=29), end)]
            return {"series": [{"key": "greetings", "label": "hello_world.widgets.greetings"}], "points": points}

        return router

    @staticmethod
    def get_admin_menus() -> list[dict]:
        """Legacy KARPy sidebar entry (Botble-style ``dashboard_menu``); the web admin uses sections."""
        return [{"id": "hello-world", "name": "Hello World", "icon": "smile", "url": "/admin/hello/inbox", "priority": 50}]

    @staticmethod
    def get_admin_sections() -> list[dict]:
        """A sidebar section in the web admin, opened as a slide-in panel."""
        return [{
            "id": "hello",
            "label": "hello_world.section",
            "label_default": "Hello World",
            "icon": "smile",
            "priority": 100,
            "items": [
                {
                    "id": "hello.inbox",
                    "label": "hello_world.menu.inbox",
                    "label_default": "Greetings inbox",
                    "icon": "inbox",
                    "route": "/admin/hello/inbox",
                    "permission": PERMISSION,
                    "badge": {"endpoint": "/api/plugins/hello_world/admin/pending-count", "tone": "attention"},
                    "priority": 10,
                },
                {
                    "id": "hello.library",
                    "label": "hello_world.menu.library",
                    "label_default": "Greeting library",
                    "icon": "library",
                    "permission": PERMISSION,
                    "priority": 20,
                    # Sub-items open as a nested slide-in submenu.
                    "children": [
                        {"id": "hello.library.templates", "label": "hello_world.menu.templates", "label_default": "Templates",
                         "route": "/admin/hello/templates", "permission": PERMISSION},
                        {"id": "hello.library.languages", "label": "hello_world.menu.languages", "label_default": "Languages",
                         "route": "/admin/hello/languages", "permission": PERMISSION},
                    ],
                },
            ],
        }]

    @staticmethod
    def get_overview_widgets() -> list[dict]:
        """Tiles on the admin Overview. Core renders them; this plugin only serves the data."""
        return [
            {
                "id": "hello.greetings_total",
                "type": "kpi",
                "title": "hello_world.widgets.greetings_total",
                "title_default": "Greetings sent",
                "endpoint": "/api/plugins/hello_world/admin/stats/greetings",
                "size": "sm",
                "permission": PERMISSION,
                "order": 10,
            },
            {
                "id": "hello.greetings_by_day",
                "type": "area_chart",
                "title": "hello_world.widgets.greetings_by_day",
                "title_default": "Greetings per day",
                "endpoint": "/api/plugins/hello_world/admin/stats/greetings-by-day",
                "size": "lg",
                "permission": PERMISSION,
                "order": 20,
            },
        ]
