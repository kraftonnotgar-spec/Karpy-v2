from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from karpy_platform.core.acl.routes import ensure_admin_user
from karpy_platform.core.base.responses import BaseHttpResponse
from karpy_platform.packages.revision.service import revision_service

router = APIRouter()


class RestoreRevisionRequest(BaseModel):
    to: str = Field(default="old", pattern="^(old|new)$")


@router.get("/supported")
async def supported_models(db: AsyncSession = Depends(get_db)):
    await ensure_admin_user(db)
    return {"models": await revision_service.supported_models()}


@router.get("/{model_alias}/{model_id}")
async def revision_history(
    model_alias: str,
    model_id: str,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    order: str = Query(default="desc", pattern="^(asc|desc)$"),
    db: AsyncSession = Depends(get_db),
):
    await ensure_admin_user(db)
    revisions = await revision_service.history(db, model_alias, model_id, limit=limit, offset=offset, order=order)
    return {
        "revisions": await revision_service.history_payload(revisions),
        "total": await revision_service.count_history(db, model_alias, model_id),
    }


@router.get("/{revision_id}")
async def get_revision(revision_id: str, db: AsyncSession = Depends(get_db)):
    await ensure_admin_user(db)
    revision = await revision_service.get_revision(db, revision_id)
    if not revision:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Revision not found")
    return await revision_service.payload(revision)


@router.delete("/{revision_id}")
async def delete_revision(revision_id: str, db: AsyncSession = Depends(get_db)):
    await ensure_admin_user(db)
    revision = await revision_service.get_revision(db, revision_id)
    if not revision:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Revision not found")
    await revision_service.delete_revision(db, revision)
    return BaseHttpResponse.make().with_deleted_success_message().to_dict()


@router.post("/{revision_id}/restore")
async def restore_revision(revision_id: str, payload: RestoreRevisionRequest, db: AsyncSession = Depends(get_db)):
    await ensure_admin_user(db)
    revision = await revision_service.get_revision(db, revision_id)
    if not revision:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Revision not found")
    model = await revision_service.restore_revision(db, revision, to=payload.to)
    if not model:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Revision cannot be restored")
    return BaseHttpResponse.make().set_data({"id": getattr(model, "id", None)}).with_updated_success_message().to_dict()
