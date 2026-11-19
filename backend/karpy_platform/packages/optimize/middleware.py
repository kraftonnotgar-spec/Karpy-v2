from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.database import async_session
from karpy_platform.packages.optimize.service import optimize_service


class OptimizeMiddleware(BaseHTTPMiddleware):
    """Apply Botble-style page-speed transforms to public HTML responses."""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        content_type = response.headers.get("content-type", "")

        if "text/html" not in content_type.lower():
            return response

        async with async_session() as db:
            if not await optimize_service.is_enabled(db, request.url.path):
                return response
            body = b"".join([chunk async for chunk in response.body_iterator])
            try:
                html = body.decode(response.charset or "utf-8")
            except UnicodeDecodeError:
                return Response(
                    content=body,
                    status_code=response.status_code,
                    headers=dict(response.headers),
                    media_type=response.media_type,
                )
            optimized = await optimize_service.optimize_html(html, db=db)

        headers = dict(response.headers)
        headers.pop("content-length", None)
        return Response(
            content=optimized,
            status_code=response.status_code,
            headers=headers,
            media_type=response.media_type,
        )
