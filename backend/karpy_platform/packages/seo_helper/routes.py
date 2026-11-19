from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from karpy_platform.core.acl.routes import ensure_admin_user
from karpy_platform.core.base.responses import BaseHttpResponse
from karpy_platform.packages.page.service import page_service
from karpy_platform.packages.seo_helper.service import seo_helper

router = APIRouter()


class SeoRenderRequest(BaseModel):
    title: str | None = None
    description: str | None = None
    image: str | None = None
    url: str | None = None
    robots_index: bool | None = None
    og_type: str = "website"


class SeoMetaRequest(BaseModel):
    seo_title: str | None = Field(default=None, max_length=70)
    seo_description: str | None = Field(default=None, max_length=160)
    seo_image: str | None = None
    index: str = Field(default="index", pattern="^(index|noindex)$")


@router.get("/supported")
async def supported_modules(db: AsyncSession = Depends(get_db)):
    await ensure_admin_user(db)
    return {"modules": await seo_helper.supported_modules()}


@router.get("/meta-box/{model_alias}/{model_id}")
async def get_meta_box(model_alias: str, model_id: str, db: AsyncSession = Depends(get_db)):
    await ensure_admin_user(db)
    model = await _resolve_model(db, model_alias, model_id)
    meta = await seo_helper.get_meta_data(db, model)
    return {"meta": meta, "metaBox": seo_helper.meta_box_schema(model, meta)}


@router.put("/meta-box/{model_alias}/{model_id}")
async def save_meta_box(model_alias: str, model_id: str, payload: SeoMetaRequest, db: AsyncSession = Depends(get_db)):
    await ensure_admin_user(db)
    model = await _resolve_model(db, model_alias, model_id)
    meta = await seo_helper.save_meta_data(db, model, payload.model_dump())
    await db.commit()
    return BaseHttpResponse.make().set_data({"meta": meta, "metaBox": seo_helper.meta_box_schema(model, meta)}).with_updated_success_message().to_dict()


@router.delete("/meta-box/{model_alias}/{model_id}")
async def delete_meta_box(model_alias: str, model_id: str, db: AsyncSession = Depends(get_db)):
    await ensure_admin_user(db)
    model = await _resolve_model(db, model_alias, model_id)
    await seo_helper.delete_meta_data(db, model)
    return BaseHttpResponse.make().with_deleted_success_message().to_dict()


@router.post("/render")
async def render_seo(payload: SeoRenderRequest, db: AsyncSession = Depends(get_db)):
    await ensure_admin_user(db)
    return await seo_helper.render(db, **payload.model_dump())


@router.get("/preview/{model_alias}/{model_id}")
async def preview_model_seo(model_alias: str, model_id: str, url: str | None = Query(default=None), db: AsyncSession = Depends(get_db)):
    await ensure_admin_user(db)
    model = await _resolve_model(db, model_alias, model_id)
    return await seo_helper.render_for_model(db, model, url=url)


async def _resolve_model(db: AsyncSession, model_alias: str, model_id: str) -> Any:
    if model_alias == "page":
        model = await page_service.get_page(db, model_id)
        if model:
            return model
    raise HTTPException(status.HTTP_404_NOT_FOUND, "SEO model not found")
