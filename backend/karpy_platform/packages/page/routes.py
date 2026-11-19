from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from karpy_platform.core.acl.routes import ensure_admin_user
from karpy_platform.core.base.responses import BaseHttpResponse
from karpy_platform.packages.page.service import page_service

admin_router = APIRouter()
public_router = APIRouter()


class PageCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    slug: str | None = Field(default=None, max_length=255)
    content: str | None = None
    description: str | None = Field(default=None, max_length=400)
    image: str | None = None
    template: str | None = "default"
    status: str = "published"
    is_featured: bool = False
    seo_title: str | None = None
    seo_description: str | None = None
    seo_image: str | None = None
    seo_meta: dict[str, Any] | None = None


class PageUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    slug: str | None = Field(default=None, max_length=255)
    content: str | None = None
    description: str | None = Field(default=None, max_length=400)
    image: str | None = None
    template: str | None = None
    status: str | None = None
    is_featured: bool | None = None
    seo_title: str | None = None
    seo_description: str | None = None
    seo_image: str | None = None
    seo_meta: dict[str, Any] | None = None


class BulkUpdate(BaseModel):
    ids: list[str] = Field(default_factory=list)
    values: dict[str, Any] = Field(default_factory=dict)


@admin_router.get("")
async def list_pages(
    status_filter: str | None = Query(default=None, alias="status"),
    search: str | None = None,
    template: str | None = None,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    await ensure_admin_user(db)
    pages = await page_service.list_pages(db, status=status_filter, search=search, template=template, limit=limit, offset=offset)
    total = await page_service.count_pages(db, status=status_filter)
    return {"pages": [page_service.page_payload(page) for page in pages], "total": total}


@admin_router.post("", status_code=status.HTTP_201_CREATED)
async def create_page(payload: PageCreate, db: AsyncSession = Depends(get_db)):
    user = await ensure_admin_user(db)
    page = await page_service.create_page(db, payload.model_dump(exclude_unset=True), user_id=user.id)
    return BaseHttpResponse.make().set_data(page_service.page_payload(page)).with_created_success_message().to_dict()


@admin_router.get("/table")
async def get_page_table(db: AsyncSession = Depends(get_db)):
    await ensure_admin_user(db)
    return await page_service.table_payload(db)


@admin_router.get("/templates")
async def get_page_templates(db: AsyncSession = Depends(get_db)):
    await ensure_admin_user(db)
    return {"templates": await page_service.templates.all()}


@admin_router.get("/menu-options")
async def get_page_menu_options(db: AsyncSession = Depends(get_db)):
    await ensure_admin_user(db)
    return {"items": await page_service.menu_options(db)}


@admin_router.post("/bulk")
async def bulk_update_pages(payload: BulkUpdate, db: AsyncSession = Depends(get_db)):
    user = await ensure_admin_user(db)
    updated = []
    for page_id in payload.ids:
        page = await page_service.get_page(db, page_id)
        if page:
            updated.append(page_service.page_payload(await page_service.update_page(db, page, payload.values, user_id=user.id)))
    return BaseHttpResponse.make().set_data({"updated": updated}).with_updated_success_message().to_dict()


@admin_router.get("/{page_id_or_slug}")
async def get_page(page_id_or_slug: str, db: AsyncSession = Depends(get_db)):
    await ensure_admin_user(db)
    page = await page_service.get_page(db, page_id_or_slug)
    if not page:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Page not found")
    data = page_service.page_payload(page, compiled_content=page.get_compiled_content())
    from karpy_platform.packages.seo_helper.service import seo_helper

    data["seoIndex"] = (await seo_helper.get_meta_data(db, page)).get("index", "index")
    return data


@admin_router.patch("/{page_id}")
async def update_page(page_id: str, payload: PageUpdate, db: AsyncSession = Depends(get_db)):
    user = await ensure_admin_user(db)
    page = await page_service.get_page(db, page_id)
    if not page:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Page not found")
    page = await page_service.update_page(db, page, payload.model_dump(exclude_unset=True), user_id=user.id)
    return BaseHttpResponse.make().set_data(page_service.page_payload(page)).with_updated_success_message().to_dict()


@admin_router.put("/{page_id}")
async def replace_page(page_id: str, payload: PageUpdate, db: AsyncSession = Depends(get_db)):
    return await update_page(page_id, payload, db)


@admin_router.delete("/{page_id}")
async def delete_page(page_id: str, db: AsyncSession = Depends(get_db)):
    user = await ensure_admin_user(db)
    page = await page_service.get_page(db, page_id)
    if not page:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Page not found")
    await page_service.delete_page(db, page, user_id=user.id)
    return BaseHttpResponse.make().with_deleted_success_message().to_dict()


@public_router.get("/home")
async def render_homepage(preview: bool = False, db: AsyncSession = Depends(get_db)):
    data = await page_service.public_page(db, preview=preview)
    if not data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Homepage not found")
    return data


@public_router.get("/{slug:path}")
async def render_page(slug: str, preview: bool = False, db: AsyncSession = Depends(get_db)):
    data = await page_service.public_page(db, slug=slug, preview=preview)
    if not data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Page not found")
    return data


# Backward-compatible import name used by older app/main.py versions.
router = admin_router
