"""Authentication gate for every /api/admin route.

Individual admin handlers historically trusted their callers. This middleware
makes the whole admin surface require a valid, unrevoked admin session from an
active, admin-capable account, and rejects cross-site writes. Routes still apply
their own finer permission checks (see acl.routes.require_acl).
"""
from __future__ import annotations

from urllib.parse import urlsplit

from fastapi import HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.config import settings
from app.database import async_session

ADMIN_PREFIX = "/api/admin"
# Signing in, checking status and signing out must work without a session.
PUBLIC_PATHS = frozenset({"/api/admin/auth/login", "/api/admin/auth/login/setup", "/api/admin/auth/status", "/api/admin/auth/logout"})
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def is_admin_path(path: str) -> bool:
    return path == ADMIN_PREFIX or path.startswith(ADMIN_PREFIX + "/")


def trusted_origins() -> set[str]:
    allowed: set[str] = set()
    for value in (settings.APP_URL, settings.USER_DASHBOARD_URL, settings.ADMIN_DASHBOARD_URL, *settings.user_dashboard_aliases):
        parsed = urlsplit(value or "")
        if (
            parsed.scheme in ({"https"} if settings.is_production else {"https", "http"})
            and parsed.netloc
            and not parsed.username
            and not parsed.password
        ):
            allowed.add(f"{parsed.scheme}://{parsed.netloc}")
    return allowed


def write_origin_allowed(request: Request) -> bool:
    """Browsers always send Origin on cross-origin writes; it must be ours."""
    if request.headers.get("sec-fetch-site") == "cross-site":
        return False
    origin = request.headers.get("origin")
    return origin is None or origin in trusted_origins()


def _deny(status_code: int, detail: str) -> JSONResponse:
    return JSONResponse({"detail": detail}, status_code=status_code, headers={"Cache-Control": "no-store"})


class AdminAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if not is_admin_path(path) or request.method == "OPTIONS":
            return await call_next(request)
        if request.method not in SAFE_METHODS and not write_origin_allowed(request):
            return _deny(403, "csrf_denied")
        if path in PUBLIC_PATHS:
            return await call_next(request)

        from karpy_platform.core.acl.routes import admin_capable, current_admin_user

        # Tests (and embedded apps) may supply their own session factory.
        factory = getattr(request.app.state, "admin_session_factory", None) or async_session
        try:
            async with factory() as db:
                user = await current_admin_user(request, db)
                capable = admin_capable(user)
        except HTTPException:
            return _deny(401, "Unauthenticated")
        except Exception:  # noqa: BLE001 - fail closed if identity cannot be checked
            return _deny(503, "admin_identity_unavailable")
        if not capable:
            return _deny(403, "permission_denied")
        return await call_next(request)


async def require_admin_session(request: Request, db) -> object:
    """Route dependency for admin routes mounted outside /api/admin (plugins)."""
    from karpy_platform.core.acl.routes import admin_capable, current_admin_user

    if request.method not in SAFE_METHODS and not write_origin_allowed(request):
        raise HTTPException(403, "csrf_denied")
    user = await current_admin_user(request, db)
    if not admin_capable(user):
        raise HTTPException(403, "permission_denied")
    return user
