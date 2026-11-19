from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from karpy_platform.core.acl.routes import ensure_admin_user
from karpy_platform.core.base.responses import BaseHttpResponse
from karpy_platform.packages.optimize.constants import OPTIMIZE_SETTING_KEYS
from karpy_platform.packages.optimize.service import optimize_service

router = APIRouter()


class OptimizeSettingsUpdate(BaseModel):
    settings: dict[str, Any] = Field(default_factory=dict)


class OptimizePreviewRequest(BaseModel):
    html: str
    settings: dict[str, Any] | None = None


@router.get("")
async def get_optimize_settings(db: AsyncSession = Depends(get_db)):
    await ensure_admin_user(db)
    return {
        "settings": await optimize_service.settings(db),
        "fields": OPTIMIZE_SETTING_KEYS,
        "previewAction": "/api/admin/settings/optimize/preview",
    }


@router.put("")
async def update_optimize_settings(payload: OptimizeSettingsUpdate, db: AsyncSession = Depends(get_db)):
    await ensure_admin_user(db)
    try:
        settings = await optimize_service.update_settings(db, payload.settings)
    except ValueError as exception:
        errors = exception.args[0] if exception.args and isinstance(exception.args[0], dict) else {}
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, {"message": "Invalid settings.", "errors": errors}) from exception
    return BaseHttpResponse.make().set_data({"settings": settings}).with_updated_success_message().to_dict()


@router.get("/status")
async def get_optimize_status(db: AsyncSession = Depends(get_db)):
    await ensure_admin_user(db)
    return await optimize_service.status(db)


@router.post("/preview")
async def preview_optimization(payload: OptimizePreviewRequest, db: AsyncSession = Depends(get_db)):
    await ensure_admin_user(db)
    settings = payload.settings or await optimize_service.settings(db)
    optimized = await optimize_service.optimize_html(payload.html, settings=settings)
    return {
        "html": optimized,
        "beforeBytes": len(payload.html.encode("utf-8")),
        "afterBytes": len(optimized.encode("utf-8")),
    }
