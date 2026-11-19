from __future__ import annotations

from typing import Any

from sqlalchemy import desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from karpy_platform.core.base.dashboard_menu import DashboardMenuItem, dashboard_menu
from karpy_platform.core.base.helpers import clean
from karpy_platform.core.base.hooks import hooks
from karpy_platform.core.dashboard.constants import DASHBOARD_FILTER_ADMIN_LIST
from karpy_platform.core.setting.registry import SettingField, SettingSection, setting_panel_registry
from karpy_platform.core.setting.store import setting_store
from karpy_platform.packages.page.constants import (
    PAGE_ACTION_DELETED,
    PAGE_ACTION_SAVED,
    PAGE_FILTER_FRONT_PAGE_CONTENT,
    PAGE_FILTER_PUBLIC_SINGLE_DATA,
    PAGE_FILTER_TEMPLATES,
)
from karpy_platform.packages.page.models import Page


class PageTemplateRegistry:
    def __init__(self) -> None:
        self._templates: dict[str, str] = {"default": "Default template"}

    def register(self, templates: dict[str, str]) -> None:
        self._templates.update(templates)

    async def all(self) -> dict[str, str]:
        return await hooks.apply_filters_async(PAGE_FILTER_TEMPLATES, dict(self._templates))


class PageService:
    """Botble packages/page engine for admin CRUD and public page resolution."""

    def __init__(self) -> None:
        self._booted = False
        self.templates = PageTemplateRegistry()

    def boot(self) -> None:
        if self._booted:
            return
        dashboard_menu.default().register_item(
            DashboardMenuItem(
                id="pages",
                name="Pages",
                url="/admin/pages",
                icon="file-text",
                priority=10,
                permissions=["pages.index"],
            )
        )
        setting_panel_registry.register_section(
            SettingSection(
                id="pages",
                title="Pages",
                description="Homepage and page-rendering defaults.",
                icon="file-text",
                route="/admin/settings/pages",
                priority=20,
                group="settings.common",
                source="package:page",
                hidden=True,
                fields=[
                    SettingField("homepage_id", "Homepage", type="text", default=""),
                    SettingField("page_public_single_ending_url", "Public page ending URL", default=""),
                ],
            )
        )
        hooks.add_filter(DASHBOARD_FILTER_ADMIN_LIST, self._add_page_stats_widget, priority=15)
        self._booted = True

    async def list_pages(
        self,
        db: AsyncSession,
        *,
        status: str | None = None,
        search: str | None = None,
        template: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Page]:
        statement = select(Page).where(Page.is_deleted == False)
        if status:
            statement = statement.where(Page.status == status)
        if template:
            statement = statement.where(Page.template == template)
        if search:
            term = f"%{search.strip()}%"
            statement = statement.where(or_(Page.name.ilike(term), Page.description.ilike(term), Page.slug.ilike(term)))
        statement = statement.order_by(desc(Page.created_at)).offset(offset).limit(limit)
        result = await db.execute(statement)
        return list(result.scalars().unique().all())

    async def count_pages(self, db: AsyncSession, status: str | None = None) -> int:
        statement = select(func.count()).select_from(Page).where(Page.is_deleted == False)
        if status:
            statement = statement.where(Page.status == status)
        return int(await db.scalar(statement) or 0)

    async def get_page(self, db: AsyncSession, page_id_or_slug: str) -> Page | None:
        from karpy_platform.packages.slug.service import slug_service

        result = await db.execute(select(Page).where(Page.is_deleted == False).where(Page.id == page_id_or_slug))
        page = result.scalars().unique().one_or_none()
        if page:
            return page

        slug, key = await slug_service.find_reference(db, page_id_or_slug, Page)
        if slug:
            page = await db.get(Page, slug.reference_id)
            if page and not page.is_deleted:
                return page

        result = await db.execute(select(Page).where(Page.is_deleted == False).where(Page.slug == key))
        return result.scalars().unique().one_or_none()

    async def create_page(self, db: AsyncSession, values: dict[str, Any], user_id: str | None = None) -> Page:
        from karpy_platform.packages.seo_helper.service import seo_helper
        from karpy_platform.packages.slug.service import slug_service

        slug_value = values.get("slug")
        seo_meta = self._extract_seo_meta(values)
        page = Page()
        await self._fill_page(db, page, values, user_id=user_id)
        db.add(page)
        await db.flush()
        await slug_service.save_for_model(db, page, slug_value or page.name)
        await db.commit()
        await db.refresh(page)
        if seo_meta:
            await seo_helper.save_meta_data(db, page, seo_meta)
            await db.refresh(page)
        await hooks.do_action_async(PAGE_ACTION_SAVED, page, "created")
        return page

    async def update_page(self, db: AsyncSession, page: Page, values: dict[str, Any], user_id: str | None = None) -> Page:
        from karpy_platform.packages.revision.service import revision_service
        from karpy_platform.packages.seo_helper.service import seo_helper
        from karpy_platform.packages.slug.service import slug_service

        slug_value = values.get("slug") if "slug" in values else None
        seo_meta = self._extract_seo_meta(values)
        before = revision_service.snapshot(page)
        await self._fill_page(db, page, values, ignore_id=page.id)
        if slug_value is not None or not page.slug:
            await slug_service.save_for_model(db, page, slug_value or page.name)
        if seo_meta:
            normalized = seo_helper.normalize_meta(seo_meta)
            for meta_key, column in {"seo_title": "seo_title", "seo_description": "seo_description", "seo_image": "seo_image"}.items():
                if meta_key in normalized:
                    setattr(page, column, normalized.get(meta_key))
        await revision_service.record_update(db, page, before, user_id=user_id)
        if seo_meta:
            await seo_helper.save_meta_data(db, page, seo_meta)
        await db.commit()
        await db.refresh(page)
        await hooks.do_action_async(PAGE_ACTION_SAVED, page, "updated")
        return page

    async def delete_page(self, db: AsyncSession, page: Page, user_id: str | None = None) -> None:
        from karpy_platform.packages.revision.service import revision_service
        from karpy_platform.packages.seo_helper.service import seo_helper
        from karpy_platform.packages.slug.service import slug_service

        before = revision_service.snapshot(page)
        page.is_deleted = True
        await revision_service.record_deleted(db, page, before, user_id=user_id)
        await seo_helper.delete_meta_data(db, page)
        await slug_service.delete_for_model(db, page)
        await db.commit()
        await hooks.do_action_async(PAGE_ACTION_DELETED, page)

    async def public_page(self, db: AsyncSession, slug: str | None = None, preview: bool = False) -> dict[str, Any] | None:
        page = None
        if slug in {None, "", "/"}:
            homepage_id = await setting_store.get(db, "homepage_id", "")
            if homepage_id:
                page = await self.get_page(db, str(homepage_id))
        if not page and slug:
            page = await self.get_page(db, slug.strip("/"))
        if not page:
            return None
        if page.status != "published" and not preview:
            return None

        content = page.get_compiled_content()
        content = await hooks.apply_filters_async(PAGE_FILTER_FRONT_PAGE_CONTENT, content, page)
        data = {
            "view": "page",
            "defaultView": "packages/page::themes.page",
            "page": self.page_payload(page, compiled_content=content),
            "seo": await self.seo_payload(db, page),
            "slug": page.slug,
            "template": page.template or "default",
        }
        return await hooks.apply_filters_async(PAGE_FILTER_PUBLIC_SINGLE_DATA, data, page)

    async def menu_options(self, db: AsyncSession) -> list[dict[str, Any]]:
        from karpy_platform.packages.slug.service import slug_service

        pages = await self.list_pages(db, status="published", limit=500)
        return [
            {
                "title": page.name,
                "referenceType": "page",
                "referenceId": page.id,
                "url": await slug_service.url_for_model(db, page),
            }
            for page in pages
        ]

    async def table_payload(self, db: AsyncSession) -> dict[str, Any]:
        templates = await self.templates.all()
        return {
            "id": "pages",
            "title": "Pages",
            "createAction": "/admin/pages/create",
            "columns": [
                {"key": "id", "title": "ID", "type": "text"},
                {"key": "name", "title": "Name", "type": "link"},
                {"key": "template", "title": "Template", "type": "text", "choices": templates},
                {"key": "createdAt", "title": "Created", "type": "datetime"},
                {"key": "status", "title": "Status", "type": "status"},
            ],
            "bulkChanges": [
                {"key": "name", "title": "Name", "type": "text"},
                {"key": "template", "title": "Template", "type": "select", "choices": templates},
                {"key": "status", "title": "Status", "type": "select", "choices": ["published", "draft", "pending"]},
                {"key": "created_at", "title": "Created At", "type": "date"},
            ],
        }

    def page_payload(self, page: Page, compiled_content: str | None = None) -> dict[str, Any]:
        from karpy_platform.packages.revision.service import revision_service

        return {
            "id": page.id,
            "name": page.name,
            "slug": page.slug,
            "url": self.page_url(page),
            "content": page.content,
            "compiledContent": compiled_content,
            "description": page.description,
            "image": page.image,
            "template": page.template or "default",
            "isFeatured": bool(page.is_featured),
            "status": page.status,
            "userId": page.user_id,
            "seoTitle": page.seo_title,
            "seoDescription": page.seo_description,
            "seoImage": page.seo_image,
            "createdAt": page.created_at.isoformat() if page.created_at else None,
            "updatedAt": page.updated_at.isoformat() if page.updated_at else None,
            "revisionTab": revision_service.form_tab_payload(page),
        }

    async def seo_payload(self, db: AsyncSession, page: Page) -> dict[str, Any]:
        from karpy_platform.packages.seo_helper.service import seo_helper
        from karpy_platform.packages.slug.service import slug_service

        url = await slug_service.url_for_model(db, page)
        data = await seo_helper.render_for_model(db, page, url=url)
        data["schema"] = {
            "@context": "https://schema.org",
            "@type": "WebPage",
            "name": page.name,
            "url": url,
        }
        return data

    def page_url(self, page: Page) -> str:
        ending = ""  # later slug/theme package can filter or replace this
        return "/" + (page.slug or page.id).strip("/") + ending

    async def _fill_page(
        self,
        db: AsyncSession,
        page: Page,
        values: dict[str, Any],
        *,
        ignore_id: str | None = None,
        user_id: str | None = None,
    ) -> None:
        if "name" in values and values["name"] is not None:
            page.name = clean(values["name"])
        if not page.name:
            raise ValueError("Page name is required")
        if "slug" in values and values["slug"]:
            page.slug = clean(values["slug"]).strip().strip("/")
        elif not page.slug:
            page.slug = clean(page.name).strip().strip("/")
        for key in (
            "content",
            "description",
            "image",
            "template",
            "status",
            "seo_title",
            "seo_description",
            "seo_image",
        ):
            if key in values:
                setattr(page, key, values[key])
        if "is_featured" in values:
            page.is_featured = bool(values["is_featured"])
        if user_id and not page.user_id:
            page.user_id = user_id
        if not page.status:
            page.status = "published"
        if not page.template:
            page.template = "default"

    def _extract_seo_meta(self, values: dict[str, Any]) -> dict[str, Any]:
        seo_meta = values.pop("seo_meta", None) or {}
        for key in ("seo_title", "seo_description", "seo_image"):
            if key in values:
                seo_meta[key] = values[key]
        return seo_meta

    async def _add_page_stats_widget(
        self,
        widgets: list[dict[str, Any]],
        widget_models: Any = None,
        db: AsyncSession | None = None,
    ) -> list[dict[str, Any]]:
        total = await self.count_pages(db, status="published") if db else "Pages"
        widgets.append(
            {
                "id": "widget_total_pages",
                "name": "widget_total_pages",
                "type": "stats",
                "title": "Pages",
                "icon": "files",
                "color": "yellow",
                "route": "/admin/pages",
                "column": "col-12 col-md-6 col-lg-3",
                "statsTotal": total,
                "priority": 15,
                "status": True,
                "order": 15,
                "settings": {},
                "predefinedRanges": [],
            }
        )
        return widgets


page_service = PageService()


def boot_page_package() -> None:
    page_service.boot()
