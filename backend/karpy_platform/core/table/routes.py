from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from karpy_platform.core.acl.routes import ensure_admin_user
from karpy_platform.core.setting.datatables import datatables_settings_payload
from karpy_platform.core.setting.store import setting_store
from karpy_platform.core.table.builder import table_builder
from karpy_platform.core.table.tables import SettingsTable

router = APIRouter()


class TableDataRequest(BaseModel):
    draw: int = 1
    page: int = 1
    perPage: int = Field(default=10, ge=1)
    search: str | dict[str, Any] = ""
    orderBy: str | None = None
    orderDir: str = "desc"
    filters: list[dict[str, Any]] = Field(default_factory=list)
    start: int | None = None
    length: int | None = None
    order: list[dict[str, Any]] = Field(default_factory=list)
    columns: list[dict[str, Any]] = Field(default_factory=list)


class BulkActionRequest(BaseModel):
    action: str
    ids: list[Any] = Field(default_factory=list)


class BulkChangeRequest(BaseModel):
    ids: list[Any] = Field(default_factory=list)
    key: str
    value: Any = None


def register_core_tables() -> None:
    if not table_builder.has("settings"):
        table_builder.register("settings", SettingsTable)


@router.get("/tables")
async def list_tables(db: AsyncSession = Depends(get_db)):
    await ensure_admin_user(db)
    register_core_tables()
    return {"tables": table_builder.all()}


@router.get("/tables/{table_id}/schema")
async def table_schema(table_id: str, db: AsyncSession = Depends(get_db)):
    await ensure_admin_user(db)
    register_core_tables()
    try:
        payload = await table_builder.create(table_id).schema()
    except KeyError as exception:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exception)) from exception
    values = await setting_store.all(db, flat=True)
    payload["datatableSettings"] = datatables_settings_payload(values)
    return payload


@router.post("/tables/{table_id}/data")
async def table_data(table_id: str, payload: TableDataRequest, db: AsyncSession = Depends(get_db)):
    await ensure_admin_user(db)
    register_core_tables()
    try:
        table = table_builder.create(table_id)
    except KeyError as exception:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exception)) from exception
    result = await table.data(db, payload.model_dump())
    values = await setting_store.all(db, flat=True)
    result["datatableSettings"] = datatables_settings_payload(values)
    return result


@router.post("/tables/{table_id}/bulk-action")
async def dispatch_bulk_action(table_id: str, payload: BulkActionRequest, db: AsyncSession = Depends(get_db)):
    await ensure_admin_user(db)
    register_core_tables()
    try:
        table = table_builder.create(table_id)
    except KeyError as exception:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exception)) from exception
    return await table.dispatch_bulk_action(db, payload.action, payload.ids)


@router.post("/tables/{table_id}/bulk-change")
async def save_bulk_change(table_id: str, payload: BulkChangeRequest, db: AsyncSession = Depends(get_db)):
    await ensure_admin_user(db)
    register_core_tables()
    try:
        table = table_builder.create(table_id)
    except KeyError as exception:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exception)) from exception
    return await table.save_bulk_change(db, payload.ids, payload.key, payload.value)
