"""API routes for the Speed plugin."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from karpy_platform.core.acl.models import utcnow
from karpy_platform.core.acl.routes import ensure_admin_user
from karpy_platform.core.support.security import security_service
from karpy_platform.plugins.auth.models import AuthSecurityEvent, AuthSession
from .rate_limiter import speed_rate_limiter, validate_config

router = APIRouter()


@router.get("/")
async def index() -> dict:
    return {
        "plugin": "speed",
        "name": "Speed",
        "status": "ready",
        "features": ["rate-limiter", "token-bucket", "redis-ready", "traffic-dashboard"],
    }


@router.get("/rate-limit")
async def rate_limit_status() -> dict[str, Any]:
    return speed_rate_limiter.status()


@router.put("/rate-limit")
async def update_rate_limit(payload: dict[str, Any]) -> dict[str, Any]:
    config = validate_config(payload.get("config") if "config" in payload else payload)
    saved = speed_rate_limiter.save_config(config)
    return {"message": "Rate limit settings saved.", "config": saved, "metrics": speed_rate_limiter.status()["metrics"]}


@router.post("/rate-limit/reset")
async def reset_rate_limit() -> dict[str, Any]:
    await speed_rate_limiter.reset()
    return {"message": "Rate limit counters reset.", **speed_rate_limiter.status()}


@router.post("/rate-limit/test")
async def test_rate_limit(payload: dict[str, Any]) -> dict[str, Any]:
    config = speed_rate_limiter.config()
    rule = payload.get("rule") or config.get("defaultRule") or {}
    checked = validate_config({**config, "defaultRule": {**config.get("defaultRule", {}), **rule}})
    return {"message": "Rule accepted.", "rule": checked["defaultRule"]}


@router.get("/security-monitor")
async def security_monitor(db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    await ensure_admin_user(db)
    security = security_service.dashboard()
    rate_status = speed_rate_limiter.status()
    auth_payload = await _safe_auth_security_payload(db)

    security_events = security.get("events") or []
    blocked_security_events = [
        event for event in security_events
        if event.get("type") in {"blocked-request", "scanner", "sql-injection", "xss", "path-traversal"}
    ]
    api_error_events = [event for event in security_events if event.get("type") == "api-error"]
    rate_metrics = rate_status.get("metrics") or {}

    return {
        "summary": {
            "suspiciousEvents": int(security.get("summary", {}).get("events") or 0),
            "highRiskEvents": int(security.get("summary", {}).get("highRiskEvents") or 0),
            "blockedRequests": int(rate_metrics.get("blocked") or 0) + len(blocked_security_events),
            "loginFailures": auth_payload["loginFailures24h"],
            "activeSessions": auth_payload["activeSessions"],
            "apiErrors": len(api_error_events),
        },
        "security": security,
        "rateLimit": rate_status,
        "auth": auth_payload,
    }


async def _auth_security_payload(db: AsyncSession) -> dict[str, Any]:
    now = utcnow()
    since = now - timedelta(hours=24)

    active_sessions = await db.scalar(
        select(func.count(AuthSession.id)).where(
            AuthSession.revoked_at.is_(None),
            AuthSession.expires_at > now,
        )
    )
    login_failures = await db.scalar(
        select(func.count(AuthSecurityEvent.id)).where(
            AuthSecurityEvent.event.in_(["login.failed", "otp.failed", "password_reset.failed"]),
            AuthSecurityEvent.created_at >= since,
        )
    )
    events_result = await db.execute(
        select(AuthSecurityEvent)
        .order_by(AuthSecurityEvent.created_at.desc())
        .limit(50)
    )
    events = events_result.scalars().all()

    return {
        "activeSessions": int(active_sessions or 0),
        "loginFailures24h": int(login_failures or 0),
        "events": [
            {
                "id": event.id,
                "userId": event.user_id,
                "identity": event.identity,
                "event": event.event,
                "ipAddress": event.ip_address,
                "userAgent": event.user_agent,
                "details": event.details,
                "createdAt": event.created_at.isoformat() if event.created_at else None,
            }
            for event in events
        ],
    }


async def _safe_auth_security_payload(db: AsyncSession) -> dict[str, Any]:
    try:
        return await _auth_security_payload(db)
    except Exception:
        return {
            "activeSessions": 0,
            "loginFailures24h": 0,
            "events": [],
            "warning": "Authentication event store is unavailable.",
        }
