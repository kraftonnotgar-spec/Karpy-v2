"""
KARPy CMS — Application Entry Point.

This is the main FastAPI application that:
1. Boots the core engine (database, auth, settings)
2. Loads and boots all active plugins
3. Mounts plugin routes dynamically
4. Serves the admin API
"""

from contextlib import asynccontextmanager
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.responses import JSONResponse, ORJSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
from app.config import settings
from app.database import get_db, init_db
from app.http_security import RequestSizeLimitMiddleware
import logging
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import SQLAlchemyError

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("karpy")


def cors_origins() -> list[str]:
    return settings.cors_allowed_origin_list


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup & shutdown logic for KARPy CMS."""
    # ─── STARTUP ──────────────────────────────────────────────
    logger.info(f"🚀 Starting {settings.APP_NAME} v{settings.APP_VERSION}")

    # 1. Initialize database tables
    await init_db()
    logger.info("✅ Database initialized")

    logger.info(f"✅ {settings.APP_NAME} is ready at http://{settings.HOST}:{settings.PORT}")

    yield  # ← App runs here

    # ─── SHUTDOWN ─────────────────────────────────────────────
    logger.info(f"👋 Shutting down {settings.APP_NAME}")


# ─── Create the FastAPI app ───────────────────────────────────

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="KARPy — A blazing-fast Python CMS with a plugin architecture.",
    lifespan=lifespan,
    default_response_class=ORJSONResponse,
    # The interactive API pages are for local work only; production keeps them off.
    docs_url=None if settings.is_production else "/docs",
    redoc_url=None if settings.is_production else "/redoc",
    openapi_url=None if settings.is_production else "/openapi.json",
)

# CORS (allow the Next.js frontend to call the API)
configured_cors_origins = cors_origins()
app.add_middleware(
    CORSMiddleware,
    allow_origins=configured_cors_origins,
    allow_credentials="*" not in configured_cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.trusted_host_list)
app.add_middleware(RequestSizeLimitMiddleware, max_body_size=settings.MAX_REQUEST_SIZE_MB * 1024 * 1024)

settings.MEDIA_DIR.mkdir(parents=True, exist_ok=True)
from app.http_security import PublicMediaFiles
app.mount("/media", PublicMediaFiles(directory=settings.MEDIA_DIR), name="media")
theme_public_dir = settings.THEME_PUBLIC_DIR
theme_public_dir.mkdir(parents=True, exist_ok=True)
app.mount("/themes", StaticFiles(directory=theme_public_dir), name="themes")


# ─── Core API Routes ─────────────────────────────────────────

@app.get("/")
async def root():
    """Welcome endpoint for the browser."""
    return {
        "message": "Welcome to KARPy CMS Engine \U0001f680",
        "status": "Running",
        "health_check": "/api/health",
        "api_docs": "/docs"
    }

@app.get("/api/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "ok",
        "app": settings.APP_NAME,
        "version": settings.APP_VERSION,
    }


@app.get("/api/system/info")
async def system_info():
    """System information for the admin dashboard."""
    from karpy_platform.packages.plugin_management.service import plugin_service
    plugin_stats = plugin_service.stats()
    return {
        "app_name": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "app_url": settings.APP_URL.rstrip("/"),
        "site_url": settings.site_url,
        "user_dashboard_url": settings.user_dashboard_url,
        "installed_plugins": plugin_stats["installed"],
        "active_plugins": plugin_stats["active"],
    }


@app.get("/api/ready")
async def readiness_check():
    """Dependency and migration readiness without exposing database details."""
    from app.database import engine
    from app.migrations import MigrationDriftError, validate_migrations
    try:
        await validate_migrations(engine)
    except (MigrationDriftError, RuntimeError, SQLAlchemyError, OSError):
        return JSONResponse(status_code=503, content={"status": "unavailable", "checks": {"database": {"status": "unavailable", "code": "schema_drift"}}})
    checks = {"database": {"status": "ready"}, "migrations": {"status": "ready"}}
    if settings.CACHE_ENABLED:
        from karpy_platform.plugins.speed.rate_limiter import speed_rate_limiter
        try:
            client = await speed_rate_limiter.redis.client()
            if client is None:
                raise RuntimeError("Redis unavailable")
            await client.ping()
            checks["redis"] = {"status": "ready"}
        except Exception:
            checks["redis"] = {"status": "unavailable", "code": "dependency_unavailable"}
            return JSONResponse(status_code=503, content={"status": "unavailable", "checks": checks})
    return {"status": "ready", "checks": checks}


from karpy_platform.packages.get_started import boot_get_started_package
from karpy_platform.packages.get_started.routes import router as get_started_router
from karpy_platform.packages.data_synchronize import boot_data_synchronize_package
from karpy_platform.packages.data_synchronize.routes import router as data_synchronize_router
from karpy_platform.packages.installer import boot_installer_package
from karpy_platform.packages.installer.routes import router as installer_router
from karpy_platform.packages.menu import boot_menu_package
from karpy_platform.packages.menu.routes import router as menu_router
from karpy_platform.packages.optimize import boot_optimize_package
from karpy_platform.packages.optimize.middleware import OptimizeMiddleware
from karpy_platform.packages.optimize.routes import router as optimize_router
from karpy_platform.core.support.security import SecurityMiddleware
from karpy_platform.packages.page import boot_page_package
from karpy_platform.packages.page.routes import admin_router as page_admin_router
from karpy_platform.packages.page.routes import public_router as page_public_router
from karpy_platform.packages.plugin_management import boot_plugin_management_package
from karpy_platform.packages.plugin_management.routes import router as plugin_management_router
from karpy_platform.packages.revision import boot_revision_package
from karpy_platform.packages.revision.routes import router as revision_router
from karpy_platform.packages.seo_helper import boot_seo_helper_package
from karpy_platform.packages.seo_helper.routes import router as seo_helper_router
from karpy_platform.packages.shortcode import boot_shortcode_package
from karpy_platform.packages.shortcode.routes import admin_router as shortcode_admin_router
from karpy_platform.packages.shortcode.routes import public_router as shortcode_public_router
from karpy_platform.packages.sitemap import boot_sitemap_package
from karpy_platform.packages.sitemap.routes import admin_router as sitemap_admin_router
from karpy_platform.packages.sitemap.routes import public_router as sitemap_public_router
from karpy_platform.packages.slug import boot_slug_package
from karpy_platform.packages.slug.routes import router as slug_router
from karpy_platform.packages.theme import boot_theme_package
from karpy_platform.packages.theme.routes import admin_router as theme_admin_router
from karpy_platform.packages.theme.routes import options_router as theme_options_router
from karpy_platform.packages.theme.routes import public_router as theme_public_router
from karpy_platform.packages.widget import boot_widget_package
from karpy_platform.packages.widget.routes import router as widget_router
from karpy_platform.core.base.routes import router as base_router
from karpy_platform.core.chart.routes import router as chart_router
from karpy_platform.core.dashboard.routes import router as dashboard_router
from karpy_platform.core.icon.routes import router as icon_router
from karpy_platform.core.js_validation.routes import router as js_validation_router
from karpy_platform.core.media.routes import router as media_router
from karpy_platform.core.setting.api import APIAccessMiddleware
from karpy_platform.core.setting.routes import router as setting_router
from karpy_platform.core.support.routes import router as support_router
from karpy_platform.core.table.routes import router as table_router
from karpy_platform.core.acl.routes import router as acl_router
from karpy_platform.core.acl.admin_guard import AdminAuthMiddleware

try:
    from karpy_platform.plugins.speed.rate_limiter import SpeedRateLimitMiddleware
except Exception:
    SpeedRateLimitMiddleware = None

boot_get_started_package()
boot_data_synchronize_package()
boot_installer_package()
boot_menu_package()
boot_optimize_package()
boot_page_package()
boot_plugin_management_package()
boot_revision_package()
boot_seo_helper_package()
boot_shortcode_package()
boot_sitemap_package()
boot_slug_package()
boot_theme_package()
boot_widget_package()

# Innermost: every /api/admin request needs a valid admin session (rejections still get security headers).
app.add_middleware(AdminAuthMiddleware)
app.add_middleware(OptimizeMiddleware)
app.add_middleware(SecurityMiddleware)
app.add_middleware(APIAccessMiddleware)
if SpeedRateLimitMiddleware:
    app.add_middleware(SpeedRateLimitMiddleware)
from karpy_platform.core.support.incidents import RuntimeIncidentMiddleware
app.add_middleware(RuntimeIncidentMiddleware)
app.include_router(installer_router, prefix="/api/install", tags=["Installer"])
app.include_router(get_started_router, prefix="/api/admin/get-started", tags=["Get Started"])
app.include_router(data_synchronize_router, prefix="/api/admin/tools/data-synchronize", tags=["Data Synchronize"])
app.include_router(menu_router, prefix="/api/admin/appearance/menus", tags=["Menus"])
app.include_router(optimize_router, prefix="/api/admin/settings/optimize", tags=["Optimize"])
app.include_router(page_admin_router, prefix="/api/admin/pages", tags=["Pages"])
app.include_router(page_public_router, prefix="/api/pages", tags=["Public Pages"])
app.include_router(plugin_management_router, prefix="/api/admin/plugins", tags=["Plugin Management"])
app.include_router(revision_router, prefix="/api/admin/revisions", tags=["Revision"])
app.include_router(seo_helper_router, prefix="/api/admin/seo-helper", tags=["SEO Helper"])
app.include_router(shortcode_admin_router, prefix="/api/admin/shortcodes", tags=["Shortcodes"])
app.include_router(shortcode_public_router, prefix="/api", tags=["Public Shortcodes"])
app.include_router(sitemap_admin_router, prefix="/api/admin/settings/sitemap", tags=["Sitemap"])
app.include_router(sitemap_public_router, tags=["Public Sitemap"])
app.include_router(slug_router, prefix="/api/admin", tags=["Slug"])
app.include_router(theme_admin_router, prefix="/api/admin/appearance/themes", tags=["Themes"])
app.include_router(theme_options_router, prefix="/api/admin/appearance/theme-options", tags=["Theme Options"])
app.include_router(theme_public_router, tags=["Public Theme"])
app.include_router(widget_router, prefix="/api/admin/appearance/widgets", tags=["Widgets"])
app.include_router(base_router, prefix="/api/admin", tags=["Base"])
app.include_router(chart_router, prefix="/api/admin", tags=["Chart"])
app.include_router(dashboard_router, prefix="/api/admin", tags=["Dashboard"])
app.include_router(icon_router, prefix="/api/admin", tags=["Icon"])
app.include_router(js_validation_router, prefix="/api/admin", tags=["JS Validation"])
app.include_router(media_router, prefix="/api/admin", tags=["Media"])
app.include_router(setting_router, prefix="/api/admin/settings", tags=["Settings"])
app.include_router(support_router, prefix="/api/admin", tags=["Support"])
app.include_router(table_router, prefix="/api/admin", tags=["Table"])
app.include_router(acl_router, prefix="/api/admin", tags=["ACL"])

from karpy_platform.packages.plugin_management.service import plugin_service as active_plugin_service
active_plugin_service.boot_active_plugins()
for plugin_name, plugin_router in active_plugin_service.get_plugin_routers().items():
    app.include_router(plugin_router, prefix=f"/api/plugins/{plugin_name}", tags=[plugin_name])
    logger.info(f"  📦 Mounted plugin routes: /api/plugins/{plugin_name}")


@app.get("/api/admin/menus", tags=["Admin"])
async def get_admin_sidebar(db: AsyncSession = Depends(get_db)):
    """Get the admin sidebar menus (collected from all active plugins)."""
    from karpy_platform.packages.plugin_management.service import plugin_service
    from karpy_platform.core.base.dashboard_menu import dashboard_menu, register_core_admin_menu

    register_core_admin_menu()
    menus = dashboard_menu.get_all()

    # Add plugin menus
    plugin_menus = plugin_service.get_admin_menus()
    menus.extend(plugin_menus)

    await apply_dynamic_menu_badges(menus, db)

    # Sort by priority
    menus.sort(key=lambda m: m.get("priority", 50))

    return {"menus": menus}


async def apply_dynamic_menu_badges(menus: list[dict], db: AsyncSession) -> None:
    """Attach lightweight dynamic badges to menus without making menu loading fragile."""
    try:
        from sqlalchemy import func, select
        from karpy_platform.packages.plugin_management.service import get_active_plugins

        active_plugins = set(get_active_plugins())
        if "payment" in active_plugins:
            from karpy_platform.plugins.payment.models.payment import Payment

            result = await db.execute(
                select(func.count())
                .select_from(Payment)
                .where(Payment.is_deleted.is_(False), Payment.viewed_at.is_(None))
            )
            unread = int(result.scalar() or 0)
            if unread:
                set_menu_badge(menus, {"payments", "payment-transactions"}, unread)

        if "contact" in active_plugins:
            from karpy_platform.plugins.contact.models.contact import Contact

            result = await db.execute(
                select(func.count())
                .select_from(Contact)
                .where(Contact.is_deleted.is_(False), Contact.status == "unread")
            )
            unread_contacts = int(result.scalar() or 0)
            if unread_contacts:
                set_menu_badge(menus, {"contact", "contact-submissions"}, unread_contacts)

    except Exception as exc:
        logger.debug("Could not load dynamic plugin menu badges: %s", exc)


def set_menu_badge(menus: list[dict], ids: set[str], value: int | str) -> None:
    for menu in menus:
        if menu.get("id") in ids:
            menu["badge"] = value
        children = menu.get("children") or []
        if children:
            set_menu_badge(children, ids, value)


admin_dist_dir = settings.BASE_DIR / "admin-ui" / "dist"
if admin_dist_dir.exists():
    app.mount("/admin/assets", StaticFiles(directory=admin_dist_dir / "assets"), name="admin-assets")


@app.get("/admin", include_in_schema=False)
@app.get("/admin/{path:path}", include_in_schema=False)
async def admin_spa(path: str = ""):
    index_file = admin_dist_dir / "index.html"
    if not index_file.exists():
        raise HTTPException(404, "Admin UI has not been built yet. Run `npm run build` in admin-ui.")
    return FileResponse(index_file)


@app.get("/{path:path}", include_in_schema=False)
async def public_site(request: Request, path: str, preview: bool = False):
    from app.database import async_session
    from karpy_platform.packages.theme.service import theme_service
    from karpy_platform.core.setting.tracking import website_tracking

    if path.startswith(("api/", "admin/", "media/", "themes/")) or path in {"docs", "openapi.json", "favicon.ico"}:
        raise HTTPException(404, "Not found")

    async with async_session() as db:
        response = await theme_service.render_public_path(db, path, preview=preview)
        if not preview:
            await website_tracking.capture_request(db, request, path, status_code=response.status_code)
        return response

# ─── Run with: python -m app.main ─────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
    )
