from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from karpy_platform.core.acl.routes import ensure_admin_user
from karpy_platform.core.base.responses import BaseHttpResponse
from karpy_platform.packages.slug.service import slug_service

router = APIRouter()


class SlugCreateRequest(BaseModel):
    value: str = Field(default="", max_length=255)
    slug_id: str | None = None
    model: str | None = None
    prefix: str | None = None


class PermalinkUpdateRequest(BaseModel):
    prefixes: dict[str, str] = Field(default_factory=dict)
    public_single_ending_url: str | None = None
    slug_turn_off_automatic_url_translation_into_latin: bool | None = None


@router.post("/ajax/slug/create")
async def create_slug(payload: SlugCreateRequest, db: AsyncSession = Depends(get_db)):
    await ensure_admin_user(db)
    return await slug_service.create_slug_string(db, payload.value, slug_id=payload.slug_id, model=payload.model, prefix=payload.prefix)


@router.get("/settings/permalink")
async def permalink_settings(db: AsyncSession = Depends(get_db)):
    await ensure_admin_user(db)
    return await slug_service.settings_payload(db)


@router.put("/settings/permalink")
async def update_permalink_settings(payload: PermalinkUpdateRequest, db: AsyncSession = Depends(get_db)):
    await ensure_admin_user(db)
    from karpy_platform.core.setting.store import setting_store

    for model_type, prefix in payload.prefixes.items():
        await slug_service.update_prefix(db, model_type, prefix)
    values: dict[str, Any] = {}
    if payload.public_single_ending_url is not None:
        values[slug_service.setting_key("public_single_ending_url")] = payload.public_single_ending_url.strip().lstrip(".")
    if payload.slug_turn_off_automatic_url_translation_into_latin is not None:
        values[slug_service.setting_key("slug_turn_off_automatic_url_translation_into_latin")] = "1" if payload.slug_turn_off_automatic_url_translation_into_latin else "0"
    if values:
        await setting_store.set(db, values)
        await setting_store.save(db)
    return BaseHttpResponse.make().set_data(await slug_service.settings_payload(db)).with_updated_success_message().to_dict()


@router.post("/settings/permalink/create-missing")
async def create_missing_slugs(db: AsyncSession = Depends(get_db)):
    await ensure_admin_user(db)
    created = await slug_service.create_missing(db)
    return BaseHttpResponse.make().set_data({"created": created}).set_message("Missing slugs created").to_dict()


@router.delete("/settings/permalink/truncate")
async def truncate_slugs(db: AsyncSession = Depends(get_db)):
    await ensure_admin_user(db)
    deleted = await slug_service.truncate(db)
    return BaseHttpResponse.make().set_data({"deleted": deleted}).set_message("Slugs truncated").to_dict()


@router.get("/slug/resolve/{path:path}")
async def resolve_slug(path: str, db: AsyncSession = Depends(get_db)):
    await ensure_admin_user(db)
    slug, key = await slug_service.find_reference(db, path)
    if not slug:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Slug not found")
    return {
        "key": key,
        "slug": {
            "id": slug.id,
            "key": slug.key,
            "prefix": slug.prefix,
            "referenceType": slug.reference_type,
            "referenceId": slug.reference_id,
        },
    }
