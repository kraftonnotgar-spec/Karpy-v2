from __future__ import annotations

import hashlib
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlparse

from fastapi import Request
from sqlalchemy import distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from karpy_platform.core.setting.models import WebsiteVisit
from karpy_platform.core.setting.store import setting_store


TRACKING_METHOD_FIRST_PARTY = "karpy"


class WebsiteTrackingService:
    """First-party analytics and script rendering for website tracking."""

    async def enabled(self, db: AsyncSession) -> bool:
        method = str(await setting_store.get(db, "tracking_method", "none") or "none")
        return method != "none"

    async def first_party_enabled(self, db: AsyncSession) -> bool:
        method = str(await setting_store.get(db, "tracking_method", "none") or "none")
        return method in {TRACKING_METHOD_FIRST_PARTY, "google_analytics", "google_tag_manager", "custom"}

    async def dashboard_enabled(self, db: AsyncSession) -> bool:
        value = await setting_store.get(db, "tracking_dashboard_enabled", "1")
        return _truthy(value)

    async def capture_request(self, db: AsyncSession, request: Request, path: str, status_code: int = 200) -> None:
        if status_code >= 400 or not await self.first_party_enabled(db):
            return

        normalized_path = "/" + path.strip("/") if path.strip("/") else "/"
        user_agent = (request.headers.get("user-agent") or "")[:500]
        client_ip = self._client_ip(request)
        referrer = self._external_referrer(request)
        ip_hash = self._hash(client_ip)
        visitor_key = self._hash(f"{client_ip}|{user_agent}")

        db.add(
            WebsiteVisit(
                visitor_key=visitor_key,
                path=normalized_path[:500],
                referrer=referrer[:500] if referrer else None,
                device=self._device(user_agent),
                browser=self._browser(user_agent),
                country=self._header_value(request, "cf-ipcountry", "x-vercel-ip-country", "x-country-code"),
                city=self._header_value(request, "cf-ipcity", "x-vercel-ip-city", "x-city"),
                ip_hash=ip_hash,
                user_agent=user_agent or None,
            )
        )
        await db.commit()

    async def tracking_code(self, db: AsyncSession) -> str:
        method = str(await setting_store.get(db, "tracking_method", "none") or "none")
        if method == "google_analytics":
            measurement_id = str(await setting_store.get(db, "google_analytics_measurement_id", "") or "").strip()
            if not measurement_id:
                return ""
            return (
                f'<script async src="https://www.googletagmanager.com/gtag/js?id={measurement_id}"></script>'
                "<script>"
                "window.dataLayer=window.dataLayer||[];"
                "function gtag(){dataLayer.push(arguments);}"
                "gtag('js',new Date());"
                f"gtag('config','{measurement_id}');"
                "</script>"
            )
        if method == "google_tag_manager":
            container_id = str(await setting_store.get(db, "google_tag_manager_id", "") or "").strip()
            if not container_id:
                return ""
            return (
                "<script>(function(w,d,s,l,i){w[l]=w[l]||[];w[l].push({'gtm.start':"
                "new Date().getTime(),event:'gtm.js'});var f=d.getElementsByTagName(s)[0],"
                "j=d.createElement(s),dl=l!='dataLayer'?'&l='+l:'';j.async=true;j.src="
                f"'https://www.googletagmanager.com/gtm.js?id='+i+dl;f.parentNode.insertBefore(j,f);"
                f"}})(window,document,'script','dataLayer','{container_id}');</script>"
            )
        if method == "custom":
            return str(await setting_store.get(db, "custom_tracking_code", "") or "")
        return ""

    async def analytics(self, db: AsyncSession, range_key: str = "90d") -> dict[str, Any]:
        start = self._range_start(range_key)
        where = [WebsiteVisit.created_at >= start] if start else []
        enabled = await self.first_party_enabled(db)
        dashboard_enabled = await self.dashboard_enabled(db)

        total_views = int(await db.scalar(select(func.count()).select_from(WebsiteVisit).where(*where)) or 0)
        unique_visitors = int(await db.scalar(select(func.count(distinct(WebsiteVisit.visitor_key))).where(*where)) or 0)

        return {
            "enabled": enabled,
            "dashboardEnabled": dashboard_enabled,
            "range": range_key,
            "summary": {
                "views": total_views,
                "visitors": unique_visitors,
                "topPath": await self._top_label(db, WebsiteVisit.path, where),
                "topReferrer": await self._top_label(db, WebsiteVisit.referrer, where, "Direct"),
            },
            "viewsOverTime": await self._views_over_time(db, start),
            "topReferrers": await self._top_counts(db, WebsiteVisit.referrer, where, "Direct", limit=6),
            "devices": await self._top_counts(db, WebsiteVisit.device, where, "unknown", limit=5),
            "countries": await self._top_counts(db, WebsiteVisit.country, where, "Unknown", limit=6),
            "cities": await self._top_counts(db, WebsiteVisit.city, where, "Unknown", limit=6),
            "browsers": await self._top_counts(db, WebsiteVisit.browser, where, "Unknown", limit=6),
            "pages": await self._top_counts(db, WebsiteVisit.path, where, "/", limit=6),
        }

    def _range_start(self, range_key: str) -> datetime | None:
        now = datetime.utcnow()
        if range_key == "today":
            return now.replace(hour=0, minute=0, second=0, microsecond=0)
        if range_key == "7d":
            return now - timedelta(days=6)
        if range_key == "30d":
            return now - timedelta(days=29)
        if range_key == "90d":
            return now - timedelta(days=89)
        return None

    async def _views_over_time(self, db: AsyncSession, start: datetime | None) -> list[dict[str, Any]]:
        if start:
            days = max(1, min(90, (datetime.utcnow().date() - start.date()).days + 1))
            buckets = {(datetime.utcnow().date() - timedelta(days=offset)).isoformat(): 0 for offset in range(days)}
        else:
            first = await db.scalar(select(func.min(WebsiteVisit.created_at)))
            if not first:
                return []
            days = min(180, (datetime.utcnow().date() - first.date()).days + 1)
            buckets = {(datetime.utcnow().date() - timedelta(days=offset)).isoformat(): 0 for offset in range(days)}

        where = [WebsiteVisit.created_at >= start] if start else []
        result = await db.execute(select(WebsiteVisit.created_at).where(*where))
        for created_at in result.scalars().all():
            key = created_at.date().isoformat()
            if key in buckets:
                buckets[key] += 1
        return [{"date": key, "views": buckets[key]} for key in sorted(buckets)]

    async def _top_label(self, db: AsyncSession, column: Any, where: list[Any], fallback: str = "") -> str:
        items = await self._top_counts(db, column, where, fallback, limit=1)
        return str(items[0]["label"]) if items else fallback

    async def _top_counts(self, db: AsyncSession, column: Any, where: list[Any], fallback: str, limit: int = 6) -> list[dict[str, Any]]:
        result = await db.execute(
            select(column, func.count().label("total"))
            .where(*where)
            .group_by(column)
            .order_by(func.count().desc())
            .limit(limit)
        )
        rows = []
        for label, total in result.all():
            rows.append({"label": label or fallback, "value": int(total or 0)})
        return rows

    def _client_ip(self, request: Request) -> str:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
        real_ip = request.headers.get("x-real-ip")
        if real_ip:
            return real_ip.strip()
        return request.client.host if request.client else "0.0.0.0"

    def _external_referrer(self, request: Request) -> str | None:
        value = request.headers.get("referer") or request.headers.get("referrer")
        if not value:
            return None
        parsed = urlparse(value)
        host = parsed.netloc or value
        own_host = urlparse(settings.site_url).netloc
        if own_host and host == own_host:
            return None
        return host

    def _header_value(self, request: Request, *names: str) -> str | None:
        for name in names:
            value = request.headers.get(name)
            if value:
                return value[:120]
        return None

    def _hash(self, value: str) -> str:
        return hashlib.sha256(f"{settings.SECRET_KEY}|{value}".encode("utf-8")).hexdigest()

    def _device(self, user_agent: str) -> str:
        text = user_agent.lower()
        if "ipad" in text or "tablet" in text:
            return "tablet"
        if "mobile" in text or "iphone" in text or "android" in text:
            return "mobile"
        return "desktop"

    def _browser(self, user_agent: str) -> str:
        text = user_agent.lower()
        if "edg/" in text:
            return "Edge"
        if "chrome/" in text and "chromium" not in text:
            return "Chrome"
        if "firefox/" in text:
            return "Firefox"
        if "safari/" in text and "chrome/" not in text:
            return "Safari"
        if "opr/" in text or "opera" in text:
            return "Opera"
        return "Unknown"


def _truthy(value: Any) -> bool:
    return value is True or str(value).strip().lower() in {"1", "true", "yes", "on"}


website_tracking = WebsiteTrackingService()
