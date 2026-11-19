from __future__ import annotations

import json

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from karpy_platform.core.acl.routes import ensure_admin_user
from karpy_platform.core.base.responses import BaseHttpResponse
from karpy_platform.core.support.backup import BackupCreateData, backup_service
from karpy_platform.core.support.cache import support_cache_manager
from karpy_platform.core.support.cache_management import cache_management_service
from karpy_platform.core.support.cron import cronjob_service
from karpy_platform.core.support.security import security_service
from karpy_platform.core.support.system_information import system_information_service
from karpy_platform.core.support.system_updater import system_updater_service

router = APIRouter()


class BackupCreateRequest(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    description: str | None = Field(default=None, max_length=400)
    databaseOnly: bool = False

    @field_validator("name", mode="before")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        if not isinstance(value, str) or len(value.strip()) < 2:
            raise ValueError("Name is required and must be at least 2 characters.")
        return value.strip()

    @field_validator("description", mode="before")
    @classmethod
    def normalize_description(cls, value: str | None) -> str | None:
        return value.strip() if isinstance(value, str) else value


@router.get("/support/cache")
async def cache_status(db: AsyncSession = Depends(get_db)):
    await ensure_admin_user(db)
    return cache_management_service.status()


@router.post("/support/cache/flush")
async def flush_cache(group: str | None = None, db: AsyncSession = Depends(get_db)):
    await ensure_admin_user(db)
    await support_cache_manager.flush(group)
    return BaseHttpResponse.make().set_message("Support cache flushed successfully").to_dict()


@router.post("/support/cache/actions/{action}")
async def run_cache_action(action: str, db: AsyncSession = Depends(get_db)):
    await ensure_admin_user(db)
    try:
        result = await cache_management_service.run(db, action)
    except ValueError as exception:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exception)) from exception
    return BaseHttpResponse.make().set_data(result).set_message(result["message"]).to_dict()


@router.get("/support/cronjob")
async def cronjob_status(db: AsyncSession = Depends(get_db)):
    await ensure_admin_user(db)
    return cronjob_service.status()


@router.post("/support/cronjob/run")
async def run_cronjob(db: AsyncSession = Depends(get_db)):
    await ensure_admin_user(db)
    result = cronjob_service.run_due_tasks()
    return BaseHttpResponse.make().set_data(result).set_message("Scheduler ran successfully").to_dict()


@router.get("/support/security")
async def security_status(db: AsyncSession = Depends(get_db)):
    await ensure_admin_user(db)
    return security_service.dashboard()


@router.get("/support/system-information")
async def system_information(db: AsyncSession = Depends(get_db)):
    await ensure_admin_user(db)
    return await system_information_service.payload(db)


@router.get("/support/system-information/report")
async def system_information_report(db: AsyncSession = Depends(get_db)):
    await ensure_admin_user(db)
    payload = await system_information_service.payload(db)
    return Response(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="karpy-system-report.json"'},
    )


@router.get("/support/system-updater")
async def system_updater_status(db: AsyncSession = Depends(get_db)):
    await ensure_admin_user(db)
    return system_updater_service.status()


@router.post("/support/system-updater/check")
async def system_updater_check(db: AsyncSession = Depends(get_db)):
    await ensure_admin_user(db)
    return system_updater_service.check()


@router.post("/support/system-updater/packages", status_code=status.HTTP_201_CREATED)
async def upload_system_update_package(file: UploadFile = File(...), db: AsyncSession = Depends(get_db)):
    await ensure_admin_user(db)
    try:
        package = system_updater_service.upload(file.filename or "karpy-update.zip", await file.read())
    except ValueError as exception:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exception)) from exception
    return BaseHttpResponse.make().set_data(package).set_message("Update package uploaded successfully").to_dict()


@router.post("/support/system-updater/actions/{action}")
async def run_system_updater_action(action: str, db: AsyncSession = Depends(get_db)):
    await ensure_admin_user(db)
    try:
        result = system_updater_service.run_action(action)
    except ValueError as exception:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exception)) from exception
    return BaseHttpResponse.make().set_data(result).set_message(result["message"]).to_dict()


@router.get("/support/backups")
async def list_backups(db: AsyncSession = Depends(get_db)):
    await ensure_admin_user(db)
    return {"backups": backup_service.list()}


@router.post("/support/backups", status_code=status.HTTP_201_CREATED)
async def create_backup(payload: BackupCreateRequest, db: AsyncSession = Depends(get_db)):
    await ensure_admin_user(db)
    backup = backup_service.create(BackupCreateData(payload.name, payload.description, payload.databaseOnly))
    return BaseHttpResponse.make().set_data(backup).set_message("Backup generated successfully").to_dict()


@router.get("/support/backups/{filename}/download")
async def download_backup(filename: str, db: AsyncSession = Depends(get_db)):
    await ensure_admin_user(db)
    try:
        path = backup_service.path_for(filename)
    except FileNotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Backup not found") from None
    except ValueError as exception:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exception)) from exception
    return FileResponse(path, media_type="application/zip", filename=path.name)


@router.post("/support/backups/{filename}/restore")
async def restore_backup(filename: str, db: AsyncSession = Depends(get_db)):
    await ensure_admin_user(db)
    try:
        restored = backup_service.restore(filename)
    except FileNotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Backup not found") from None
    except ValueError as exception:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exception)) from exception
    return BaseHttpResponse.make().set_data(restored).set_message("Backup restored successfully").to_dict()


@router.delete("/support/backups/{filename}")
async def delete_backup(filename: str, db: AsyncSession = Depends(get_db)):
    await ensure_admin_user(db)
    try:
        backup_service.delete(filename)
    except FileNotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Backup not found") from None
    except ValueError as exception:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exception)) from exception
    return BaseHttpResponse.make().set_message("Backup deleted successfully").to_dict()
