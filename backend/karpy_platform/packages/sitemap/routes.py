from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from karpy_platform.core.acl.routes import ensure_admin_user
from karpy_platform.core.base.responses import BaseHttpResponse
from karpy_platform.packages.sitemap.service import sitemap_service

admin_router = APIRouter()
public_router = APIRouter()


class IndexNowSubmitRequest(BaseModel):
    urls: list[str] = Field(default_factory=list)


@public_router.get("/sitemap.xml")
async def sitemap_xml(page: int | None = Query(default=None, ge=1), db: AsyncSession = Depends(get_db)):
    content, media_type = await sitemap_service.generate(db, "xml", page=page)
    return Response(content=content, media_type=media_type)


@public_router.get("/sitemap-index.xml")
async def sitemap_index(db: AsyncSession = Depends(get_db)):
    content, media_type = await sitemap_service.generate(db, "sitemapindex")
    return Response(content=content, media_type=media_type)


@public_router.get("/sitemap-{page}.xml")
async def sitemap_xml_page(page: int, db: AsyncSession = Depends(get_db)):
    content, media_type = await sitemap_service.generate(db, "xml", page=page)
    return Response(content=content, media_type=media_type)


@public_router.get("/sitemap.txt")
async def sitemap_txt(db: AsyncSession = Depends(get_db)):
    content, media_type = await sitemap_service.generate(db, "txt")
    return Response(content=content, media_type=media_type)


@public_router.get("/sitemap.html")
async def sitemap_html(db: AsyncSession = Depends(get_db)):
    content, media_type = await sitemap_service.generate(db, "html")
    return Response(content=content, media_type=media_type)


@admin_router.get("")
async def sitemap_settings(db: AsyncSession = Depends(get_db)):
    await ensure_admin_user(db)
    return await sitemap_service.settings_payload(db)


@admin_router.post("/clear-cache")
async def clear_cache(db: AsyncSession = Depends(get_db)):
    await ensure_admin_user(db)
    sitemap_service.clear_cache()
    return BaseHttpResponse.make().set_message("Sitemap cache cleared").to_dict()


@admin_router.post("/generate-key")
async def generate_indexnow_key(db: AsyncSession = Depends(get_db)):
    await ensure_admin_user(db)
    return await sitemap_service.generate_indexnow_key(db)


@admin_router.post("/create-key-file")
async def create_indexnow_key_file(db: AsyncSession = Depends(get_db)):
    await ensure_admin_user(db)
    payload = await sitemap_service.settings_payload(db)
    api_key = payload["indexNow"]["apiKey"]
    if not api_key:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No IndexNow API key configured")
    created = sitemap_service.create_indexnow_key_file(api_key)
    return {"success": created, **(await sitemap_service.settings_payload(db))["indexNow"]}


@admin_router.post("/indexnow/submit")
async def submit_indexnow(payload: IndexNowSubmitRequest, db: AsyncSession = Depends(get_db)):
    await ensure_admin_user(db)
    return await sitemap_service.submit_indexnow(db, payload.urls or None)


@admin_router.get("/preview")
async def preview_sitemap(format: str = Query(default="xml", pattern="^(xml|txt|html|sitemapindex)$"), db: AsyncSession = Depends(get_db)):
    await ensure_admin_user(db)
    content, media_type = await sitemap_service.generate(db, format)
    return {"format": format, "mediaType": media_type, "content": content}
