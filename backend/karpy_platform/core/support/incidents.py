"""Safe operational evidence for the platform-admin security notice feed."""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import time
import traceback
import uuid

from fastapi import Request
from starlette.responses import JSONResponse

logger = logging.getLogger("karpy.incidents")
INCIDENT_HINTS = {
    "sms_receipt_unmatched": "SMS receipt has no unique recorded send. Provider retry requested; review SMS Delivery Activity.",
}


async def record_incident(request, status, error=None):
    from app.database import async_session
    from karpy_platform.core.base.models import AdminNotification

    reference = request.state.request_id
    route = getattr(request.scope.get("route"), "path", "/api/unmatched")
    route = route if isinstance(route, str) and re.fullmatch(r"[A-Za-z0-9_/{}/.:-]{1,180}", route) else "/api/unmatched"
    method = request.method if request.method in {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"} else "OTHER"
    kind = type(error).__name__ if error else "ServiceUnavailable"
    kind = kind if re.fullmatch(r"[A-Za-z0-9_]{1,80}", kind) else "InternalError"
    hint = INCIDENT_HINTS.get(getattr(request.state, "incident_code", None), "Check backend logs and Delivery Activity.")
    source = None
    if error and error.__traceback__:
        for frame in reversed(traceback.extract_tb(error.__traceback__)):
            path = frame.filename.replace("\\", "/")
            if "karpy_platform/" in path or "/app/" in path:
                source = path.split("karpy_platform/")[-1].split("/app/")[-1] + ":" + str(frame.lineno)
                break
    # Never serialize exception messages, request bodies, headers, queries or local variables.
    logger.error("platform_incident %s", json.dumps({"reference": reference, "method": method, "route": route, "status": status, "kind": kind, "source": source}))
    identity = str(uuid.uuid5(uuid.NAMESPACE_URL, hashlib.sha256(f"{method}:{route}:{status}:{kind}:{int(time.time()) // 300}".encode()).hexdigest()))
    try:
        async with asyncio.timeout(3), async_session() as db:
            if await db.get(AdminNotification, identity):
                return
            db.add(AdminNotification(id=identity, title="Platform request failed", permission="security.index",
                                     description=f"HTTP {status}; {kind}. Reference: {reference}. {method} {route}. {hint} Repeated failures are grouped for five minutes."[:400],
                                     action_label="Review platform security", action_url="/platform-admin/security-overview"))
            await db.commit()
    except Exception:
        # The log remains usable even when the database itself is unavailable.
        logger.warning("platform_incident_notice_unavailable reference=%s", reference)


class RuntimeIncidentMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not scope.get("path", "").startswith("/api/"):
            return await self.app(scope, receive, send)
        request = Request(scope)
        supplied = request.headers.get("x-request-id", "")
        request.state.request_id = supplied if re.fullmatch(r"[A-Za-z0-9_-]{1,64}", supplied) else uuid.uuid4().hex
        status = 200
        started = False

        async def tracked(message):
            nonlocal status, started
            if message["type"] == "http.response.start":
                status, started = message["status"], True
                headers = [(k, v) for k, v in message.get("headers", []) if k.lower() != b"x-request-id"]
                headers.append((b"x-request-id", request.state.request_id.encode()))
                if status >= 500:
                    headers = [(k, v) for k, v in headers if k.lower() != b"cache-control"]
                    headers.append((b"cache-control", b"no-store"))
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, tracked)
        except Exception as error:
            await record_incident(request, 500, error)
            if started:
                raise
            response = JSONResponse({"error": {"code": "unavailable", "message": "The request could not be completed.", "requestId": request.state.request_id}}, status_code=500,
                                    headers={"X-Request-ID": request.state.request_id, "Cache-Control": "no-store"})
            return await response(scope, receive, send)
        if status >= 500:
            await record_incident(request, status, getattr(request.state, "incident_error", None))
