from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from karpy_platform.core.acl.routes import ensure_admin_user
from karpy_platform.core.base.responses import BaseHttpResponse
from karpy_platform.packages.shortcode.engine import shortcode_engine

admin_router = APIRouter()
public_router = APIRouter()


class ShortcodeConfigRequest(BaseModel):
    key: str | None = None
    code: str | None = None


class RenderBlockRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    attributes: dict[str, Any] = Field(default_factory=dict)


class CompileRequest(BaseModel):
    content: str = ""
    force: bool = False


class GenerateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    attributes: dict[str, Any] = Field(default_factory=dict)
    content: str | None = None
    lazy: bool = False


@admin_router.get("")
async def list_shortcodes(db: AsyncSession = Depends(get_db)):
    await ensure_admin_user(db)
    return {"shortcodes": shortcode_engine.get_all()}


@admin_router.post("/compile")
async def compile_content(payload: CompileRequest, db: AsyncSession = Depends(get_db)):
    await ensure_admin_user(db)
    return {"html": shortcode_engine.compile(payload.content, force=payload.force)}


@admin_router.post("/generate")
async def generate_shortcode(payload: GenerateRequest, db: AsyncSession = Depends(get_db)):
    await ensure_admin_user(db)
    return {"shortcode": shortcode_engine.generate_shortcode(payload.name, payload.attributes, payload.content, payload.lazy)}


@admin_router.post("/ajax-get-admin-config/{key}")
async def ajax_get_admin_config(key: str, payload: ShortcodeConfigRequest | None = None, db: AsyncSession = Depends(get_db)):
    await ensure_admin_user(db)
    data = shortcode_engine.admin_config(key, payload.code if payload else None)
    return BaseHttpResponse.make().set_data(data).to_dict()


@admin_router.post("/ajax-get-admin-config")
async def ajax_get_admin_config_from_payload(payload: ShortcodeConfigRequest, db: AsyncSession = Depends(get_db)):
    await ensure_admin_user(db)
    key = payload.key
    if not key:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Shortcode key is required")
    data = shortcode_engine.admin_config(key, payload.code)
    return BaseHttpResponse.make().set_data(data).to_dict()


@admin_router.get("/{key}")
async def get_shortcode(key: str, db: AsyncSession = Depends(get_db)):
    await ensure_admin_user(db)
    shortcodes = shortcode_engine.get_all()
    if key not in shortcodes:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Shortcode not found")
    return shortcodes[key]


@public_router.post("/ajax/render-ui-blocks")
async def render_ui_block(payload: RenderBlockRequest):
    html = shortcode_engine.render_ui_block(payload.name, payload.attributes)
    return BaseHttpResponse.make().set_data(html).to_dict()
