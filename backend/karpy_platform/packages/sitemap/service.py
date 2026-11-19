from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from html import escape
from typing import Any, Awaitable, Callable
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from karpy_platform.core.base.hooks import hooks
from karpy_platform.core.setting.registry import SettingField, SettingSection, setting_panel_registry
from karpy_platform.core.setting.store import setting_store
from karpy_platform.packages.page.constants import PAGE_ACTION_DELETED, PAGE_ACTION_SAVED
from karpy_platform.packages.page.models import Page
from karpy_platform.packages.sitemap.constants import (
    SITEMAP_ACTION_INDEXNOW_SUBMITTED,
    SITEMAP_ACTION_UPDATED,
    SITEMAP_FILTER_ITEMS,
    SITEMAP_FILTER_RENDER,
    SITEMAP_FILTER_SITEMAPS,
)

SitemapProvider = Callable[[AsyncSession], Awaitable[list["SitemapItem"]]]


@dataclass
class SitemapItem:
    loc: str
    lastmod: str | datetime | date | None = None
    priority: str | float | None = None
    freq: str | None = None
    images: list[dict[str, Any]] = field(default_factory=list)
    title: str | None = None
    translations: list[dict[str, Any]] = field(default_factory=list)
    videos: list[dict[str, Any]] = field(default_factory=list)
    googlenews: dict[str, Any] = field(default_factory=dict)
    alternates: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "loc": self.loc,
            "lastmod": self.lastmod,
            "priority": self.priority,
            "freq": self.freq,
            "images": self.images,
            "title": self.title,
            "translations": self.translations,
            "videos": self.videos,
            "googlenews": self.googlenews,
            "alternates": self.alternates,
        }


@dataclass
class SitemapIndexItem:
    loc: str
    lastmod: str | datetime | date | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"loc": self.loc, "lastmod": self.lastmod}


class SitemapService:
    """Botble-style sitemap manager with providers, rendering, cache, and IndexNow support."""

    indexnow_endpoints = {
        "bing": "https://api.indexnow.org/indexnow",
        "yandex": "https://yandex.com/indexnow",
        "seznam": "https://search.seznam.cz/indexnow",
        "naver": "https://searchadvisor.naver.com/indexnow",
    }

    def __init__(self) -> None:
        self._booted = False
        self._providers: dict[str, SitemapProvider] = {}
        self._cache: dict[str, tuple[float, str, str]] = {}

    def boot(self) -> None:
        if self._booted:
            return
        self.register_provider("pages", self._page_items)
        setting_panel_registry.register_section(
            SettingSection(
                id="sitemap",
                title="Sitemap",
                description="XML sitemap generation, paging, cache, and IndexNow submission.",
                icon="sitemap",
                route="/admin/settings/sitemap",
                priority=1000,
                permission="sitemap.settings",
                group="settings.common",
                source="package:sitemap",
                hidden=True,
                fields=[
                    SettingField("sitemap_enabled", "Enable sitemap", type="switch", default="1"),
                    SettingField("sitemap_items_per_page", "Sitemap items per page", type="number", default="1000"),
                    SettingField("sitemap_use_cache", "Use sitemap cache", type="switch", default="1"),
                    SettingField("cache_sitemap_timeout_minutes", "Cache duration", type="number", default="60"),
                    SettingField("sitemap_escaping", "Escape XML values", type="switch", default="1"),
                    SettingField("sitemap_use_styles", "Use XML styles", type="switch", default="1"),
                    SettingField("sitemap_use_gzip", "Use gzip when storing files", type="switch", default="0"),
                    SettingField("indexnow_enabled", "Enable IndexNow", type="switch", default="0"),
                    SettingField("indexnow_api_key", "IndexNow API key", default=""),
                ],
            )
        )
        hooks.add_action(PAGE_ACTION_SAVED, self._content_updated, priority=50)
        hooks.add_action(PAGE_ACTION_DELETED, self._content_updated, priority=50)
        self._booted = True

    def register_provider(self, key: str, provider: SitemapProvider) -> None:
        self._providers[key] = provider

    def remove_provider(self, key: str) -> None:
        self._providers.pop(key, None)

    async def items(self, db: AsyncSession) -> list[SitemapItem]:
        collected: list[SitemapItem] = []
        for provider in self._providers.values():
            collected.extend(await provider(db))
        collected = await hooks.apply_filters_async(SITEMAP_FILTER_ITEMS, collected, db)
        return self._dedupe_items(collected)

    async def sitemaps(self, db: AsyncSession) -> list[SitemapIndexItem]:
        site_url = await self.site_url(db)
        items = await self.items(db)
        per_page = await self.items_per_page(db)
        if len(items) <= per_page:
            sitemaps = [SitemapIndexItem(loc=urljoin(site_url + "/", "sitemap.xml"), lastmod=self._lastmod(items))]
        else:
            chunks = [items[index : index + per_page] for index in range(0, len(items), per_page)]
            sitemaps = [
                SitemapIndexItem(loc=urljoin(site_url + "/", f"sitemap-{index + 1}.xml"), lastmod=self._lastmod(chunk))
                for index, chunk in enumerate(chunks)
            ]
        return await hooks.apply_filters_async(SITEMAP_FILTER_SITEMAPS, sitemaps, db)

    async def generate(self, db: AsyncSession, format: str = "xml", page: int | None = None) -> tuple[str, str]:
        if not await self.enabled(db):
            return "Sitemap is disabled", "text/plain; charset=utf-8"

        cache_key = f"{format}:{page or 0}"
        cached = await self._get_cache(db, cache_key)
        if cached:
            return cached

        if format == "sitemapindex":
            content = self.render_sitemap_index(await self.sitemaps(db))
            media_type = "text/xml; charset=utf-8"
        else:
            items = await self.items(db)
            per_page = await self.items_per_page(db)
            if page:
                start = (page - 1) * per_page
                items = items[start : start + per_page]
            if format == "txt":
                content = self.render_txt(items)
                media_type = "text/plain; charset=utf-8"
            elif format == "html":
                content = self.render_html(items, await self.site_url(db))
                media_type = "text/html; charset=utf-8"
            else:
                content = self.render_xml(items)
                media_type = "text/xml; charset=utf-8"

        content = await hooks.apply_filters_async(SITEMAP_FILTER_RENDER, content, format, db)
        await self._set_cache(db, cache_key, content, media_type)
        return content, media_type

    def render_xml(self, items: list[SitemapItem]) -> str:
        lines = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" xmlns:xhtml="http://www.w3.org/1999/xhtml" xmlns:image="http://www.google.com/schemas/sitemap-image/1.1" xmlns:video="http://www.google.com/schemas/sitemap-video/1.1">',
        ]
        for item in items[:50000]:
            data = item.to_dict()
            lines.append("  <url>")
            lines.append(f"    <loc>{self._xml(data['loc'])}</loc>")
            for translation in data["translations"]:
                lines.append(f'    <xhtml:link hreflang="{self._xml(translation.get("language", ""))}" href="{self._xml(translation.get("url", ""))}" rel="alternate" />')
            for alternate in data["alternates"]:
                lines.append(f'    <xhtml:link href="{self._xml(alternate.get("url", ""))}" rel="alternate" media="{self._xml(alternate.get("media", ""))}" />')
            if data["priority"] is not None:
                lines.append(f"    <priority>{self._xml(str(data['priority']))}</priority>")
            if data["lastmod"] is not None:
                lines.append(f"    <lastmod>{self._format_lastmod(data['lastmod'])}</lastmod>")
            if data["freq"]:
                lines.append(f"    <changefreq>{self._xml(data['freq'])}</changefreq>")
            for image in data["images"]:
                if not image.get("url"):
                    continue
                lines.append("    <image:image>")
                lines.append(f"      <image:loc>{self._xml(image['url'])}</image:loc>")
                for tag in ("title", "caption", "geo_location", "license"):
                    if image.get(tag):
                        lines.append(f"      <image:{tag}>{self._xml(image[tag])}</image:{tag}>")
                lines.append("    </image:image>")
            for video in data["videos"]:
                lines.append("    <video:video>")
                for tag in ("thumbnail_loc", "title", "description", "content_loc", "duration", "expiration_date", "rating", "view_count", "publication_date", "family_friendly", "requires_subscription", "live"):
                    if video.get(tag):
                        lines.append(f"      <video:{tag}>{self._xml(str(video[tag]))}</video:{tag}>")
                lines.append("    </video:video>")
            lines.append("  </url>")
        lines.append("</urlset>")
        return "\n".join(lines)

    def render_sitemap_index(self, sitemaps: list[SitemapIndexItem]) -> str:
        lines = ['<?xml version="1.0" encoding="UTF-8"?>', '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
        for item in sitemaps:
            lines.append("  <sitemap>")
            lines.append(f"    <loc>{self._xml(item.loc)}</loc>")
            if item.lastmod:
                lines.append(f"    <lastmod>{self._format_lastmod(item.lastmod)}</lastmod>")
            lines.append("  </sitemap>")
        lines.append("</sitemapindex>")
        return "\n".join(lines)

    def render_txt(self, items: list[SitemapItem]) -> str:
        return "\n".join(item.loc for item in items) + "\n"

    def render_html(self, items: list[SitemapItem], site_url: str) -> str:
        rows = "\n".join(
            f'<li><a href="{escape(item.loc, quote=True)}">{escape(item.title or item.loc)}</a> <small>{escape(self._format_lastmod(item.lastmod)) if item.lastmod else ""}</small></li>'
            for item in items
        )
        return f"<!DOCTYPE html><html><head><title>Sitemap for {escape(site_url)}</title></head><body><h1><a href=\"{escape(site_url, quote=True)}\">Sitemap for {escape(site_url)}</a></h1><ul>{rows}</ul></body></html>"

    async def settings_payload(self, db: AsyncSession) -> dict[str, Any]:
        api_key = await setting_store.get(db, "indexnow_api_key", "")
        return {
            "enabled": await self.enabled(db),
            "itemsPerPage": await self.items_per_page(db),
            "cacheEnabled": await self._bool_setting(db, "sitemap_use_cache", False),
            "cacheDuration": await self.cache_duration_seconds(db),
            "sitemapUrl": urljoin((await self.site_url(db)) + "/", "sitemap.xml"),
            "sitemapIndexUrl": urljoin((await self.site_url(db)) + "/", "sitemap-index.xml"),
            "indexNow": {
                "enabled": await self._bool_setting(db, "indexnow_enabled", False),
                "apiKey": api_key,
                "keyFileName": self.indexnow_key_file_name(api_key),
                "keyFileExists": self.indexnow_key_file_exists(api_key),
                "keyFileValid": self.indexnow_key_file_valid(api_key),
                "endpoints": self.indexnow_endpoints,
            },
            "providers": sorted(self._providers),
        }

    async def generate_indexnow_key(self, db: AsyncSession) -> dict[str, Any]:
        api_key = str(uuid.uuid4())
        await setting_store.force_set(db, "indexnow_api_key", api_key)
        await setting_store.save(db)
        created = self.create_indexnow_key_file(api_key)
        return {
            "success": created,
            "api_key": api_key,
            "key_file_name": self.indexnow_key_file_name(api_key),
            "key_file_url": urljoin((await self.site_url(db)) + "/", self.indexnow_key_file_name(api_key)),
            "key_file_exists": self.indexnow_key_file_exists(api_key),
            "key_file_valid": self.indexnow_key_file_valid(api_key),
        }

    def create_indexnow_key_file(self, api_key: str) -> bool:
        if not api_key:
            return False
        path = settings.BASE_DIR / self.indexnow_key_file_name(api_key)
        path.write_text(api_key, encoding="utf-8")
        return True

    def indexnow_key_file_name(self, api_key: str | None) -> str:
        return f"{api_key or 'missing'}.txt"

    def indexnow_key_file_exists(self, api_key: str | None) -> bool:
        return bool(api_key and (settings.BASE_DIR / self.indexnow_key_file_name(api_key)).exists())

    def indexnow_key_file_valid(self, api_key: str | None) -> bool:
        if not self.indexnow_key_file_exists(api_key):
            return False
        return (settings.BASE_DIR / self.indexnow_key_file_name(api_key)).read_text(encoding="utf-8").strip() == api_key

    async def submit_indexnow(self, db: AsyncSession, urls: list[str] | None = None) -> dict[str, Any]:
        if not await self._bool_setting(db, "indexnow_enabled", False):
            return {"status": "disabled", "message": "IndexNow is disabled"}
        api_key = await setting_store.get(db, "indexnow_api_key", "")
        if not api_key:
            return {"status": "error", "message": "IndexNow API key is not configured"}

        urls = urls or [urljoin((await self.site_url(db)) + "/", "sitemap.xml")]
        host = urlparse(urls[0]).hostname or urlparse(await self.site_url(db)).hostname
        payload = json.dumps({"host": host, "key": api_key, "urlList": urls}).encode("utf-8")
        results = {}
        for engine, endpoint in self.indexnow_endpoints.items():
            try:
                request = Request(endpoint, data=payload, headers={"Content-Type": "application/json; charset=utf-8"}, method="POST")
                with urlopen(request, timeout=30) as response:
                    results[engine] = {"status": "success", "status_code": response.status, "urls_count": len(urls)}
            except Exception as exception:
                results[engine] = {"status": "error", "message": str(exception)}
        await hooks.do_action_async(SITEMAP_ACTION_INDEXNOW_SUBMITTED, results, urls)
        return results

    async def enabled(self, db: AsyncSession) -> bool:
        return await self._bool_setting(db, "sitemap_enabled", True)

    async def items_per_page(self, db: AsyncSession) -> int:
        value = int(await setting_store.get(db, "sitemap_items_per_page", "1000") or 1000)
        return min(max(value, 10), 100000)

    async def site_url(self, db: AsyncSession) -> str:
        site_url = await setting_store.get(db, "site_url", None)
        return str(site_url or settings.site_url).rstrip("/")

    async def _page_items(self, db: AsyncSession) -> list[SitemapItem]:
        from sqlalchemy import select
        from karpy_platform.packages.slug.service import slug_service

        result = await db.execute(
            select(Page)
            .where(Page.is_deleted == False, Page.status == "published")
            .order_by(Page.updated_at.desc())
        )
        pages = result.scalars().unique().all()
        site_url = await self.site_url(db)
        items = []
        for page in pages:
            loc = await slug_service.url_for_model(db, page)
            if not loc.startswith(("http://", "https://")):
                loc = urljoin(site_url + "/", loc.strip("/"))
            items.append(
                SitemapItem(
                    loc=loc,
                    lastmod=page.updated_at,
                    priority="0.8",
                    freq="weekly",
                    images=[{"url": urljoin(site_url + "/", page.image.lstrip("/")), "title": page.name}] if page.image else [],
                    title=page.name,
                )
            )
        return items

    async def _content_updated(self, *args, **kwargs) -> None:
        self.clear_cache()
        await hooks.do_action_async(SITEMAP_ACTION_UPDATED)

    def clear_cache(self) -> None:
        self._cache.clear()

    async def _get_cache(self, db: AsyncSession, key: str) -> tuple[str, str] | None:
        if not await self._bool_setting(db, "sitemap_use_cache", False):
            return None
        cached = self._cache.get(key)
        if not cached:
            return None
        expires_at, content, media_type = cached
        if expires_at < datetime.now(timezone.utc).timestamp():
            self._cache.pop(key, None)
            return None
        return content, media_type

    async def _set_cache(self, db: AsyncSession, key: str, content: str, media_type: str) -> None:
        if not await self._bool_setting(db, "sitemap_use_cache", False):
            return
        duration = await self.cache_duration_seconds(db)
        self._cache[key] = (datetime.now(timezone.utc).timestamp() + duration, content, media_type)

    async def _bool_setting(self, db: AsyncSession, key: str, default: bool) -> bool:
        value = await setting_store.get(db, key, "1" if default else "0")
        return str(value).lower() in {"1", "true", "yes", "on"}

    async def cache_duration_seconds(self, db: AsyncSession) -> int:
        minutes = await setting_store.get(db, "cache_sitemap_timeout_minutes", None)
        if minutes not in (None, ""):
            try:
                return max(60, int(minutes) * 60)
            except (TypeError, ValueError):
                return 3600
        try:
            return int(await setting_store.get(db, "sitemap_cache_duration", "3600") or 3600)
        except (TypeError, ValueError):
            return 3600

    def _dedupe_items(self, items: list[SitemapItem]) -> list[SitemapItem]:
        seen = set()
        output = []
        for item in items:
            if item.loc in seen:
                continue
            seen.add(item.loc)
            output.append(item)
        return output

    def _lastmod(self, items: list[SitemapItem]) -> str | None:
        values = [self._format_lastmod(item.lastmod) for item in items if item.lastmod]
        return max(values) if values else None

    def _format_lastmod(self, value: str | datetime | date | None) -> str:
        if value is None:
            return ""
        if isinstance(value, datetime):
            if value.tzinfo is None:
                value = value.replace(tzinfo=timezone.utc)
            return value.isoformat()
        if isinstance(value, date):
            return datetime(value.year, value.month, value.day, tzinfo=timezone.utc).isoformat()
        return str(value)

    def _xml(self, value: Any) -> str:
        return escape(str(value or ""), quote=True)


sitemap_service = SitemapService()


def boot_sitemap_package() -> None:
    sitemap_service.boot()
