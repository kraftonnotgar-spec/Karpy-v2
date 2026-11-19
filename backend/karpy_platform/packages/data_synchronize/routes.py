from __future__ import annotations

import json

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from karpy_platform.core.acl.routes import ensure_admin_user
from karpy_platform.core.base.responses import BaseHttpResponse
from karpy_platform.packages.data_synchronize.service import DataSyncImportValidationError, data_synchronize_service

router = APIRouter()


@router.get("")
async def index(db: AsyncSession = Depends(get_db)):
    await ensure_admin_user(db)
    datasets = data_synchronize_service.datasets()
    return {
        "datasets": datasets,
        "exports": [dataset for dataset in datasets if dataset["supportsExport"]],
        "imports": [dataset for dataset in datasets if dataset["supportsImport"]],
    }


@router.get("/export/{dataset_key}")
async def export_dataset(
    dataset_key: str,
    format: str = "csv",
    columns: list[str] = Query(default=[]),
    limit: int | None = Query(default=None, ge=1, le=10000),
    status: str | None = None,
    template: str | None = None,
    start_date: str | None = Query(default=None, alias="startDate"),
    end_date: str | None = Query(default=None, alias="endDate"),
    db: AsyncSession = Depends(get_db),
):
    await ensure_admin_user(db)
    dataset = data_synchronize_service.get_dataset(dataset_key)
    if not dataset or not dataset.supports_export:
        raise HTTPException(404, "Export dataset not found")
    selected_columns = [column for column in columns if column in dataset.export_keys] or dataset.export_keys
    rows = await data_synchronize_service.export_dataset(
        db,
        dataset_key,
        columns=selected_columns,
        limit=limit,
        status=status,
        template=template,
        start_date=start_date,
        end_date=end_date,
    )
    if format == "json":
        content = json.dumps({"dataset": dataset.to_dict(), "data": rows}, ensure_ascii=False, indent=2)
        return Response(content, media_type="application/json", headers={"Content-Disposition": f'attachment; filename="{dataset_key}.json"'})
    if format in {"xlsx", "excel"}:
        content = data_synchronize_service.to_xlsx(dataset, rows, selected_columns)
        return Response(
            content,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{dataset_key}.xlsx"'},
        )
    content = data_synchronize_service.to_csv(dataset, rows, selected_columns)
    return Response(content, media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="{dataset_key}.csv"'})


@router.get("/export/{dataset_key}/schema")
async def export_schema(dataset_key: str, db: AsyncSession = Depends(get_db)):
    await ensure_admin_user(db)
    dataset = data_synchronize_service.get_dataset(dataset_key)
    if not dataset or not dataset.supports_export:
        raise HTTPException(404, "Export dataset not found")
    return await data_synchronize_service.export_schema(db, dataset_key)


@router.get("/import/{dataset_key}/schema")
async def import_schema(dataset_key: str, db: AsyncSession = Depends(get_db)):
    await ensure_admin_user(db)
    dataset = data_synchronize_service.get_dataset(dataset_key)
    if not dataset or not dataset.supports_import:
        raise HTTPException(404, "Import dataset not found")
    return await data_synchronize_service.import_schema(db, dataset_key)


@router.get("/import/{dataset_key}/example")
async def import_example(dataset_key: str, format: str = "csv", db: AsyncSession = Depends(get_db)):
    await ensure_admin_user(db)
    dataset = data_synchronize_service.get_dataset(dataset_key)
    if not dataset or not dataset.supports_import:
        raise HTTPException(404, "Import dataset not found")
    rows = await data_synchronize_service.examples(db, dataset_key)
    if format in {"xlsx", "excel"}:
        content = data_synchronize_service.to_xlsx(dataset, rows, dataset.import_keys)
        return Response(
            content,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{dataset_key}-example.xlsx"'},
        )
    content = data_synchronize_service.to_csv(dataset, rows, dataset.import_keys)
    return Response(content, media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="{dataset_key}-example.csv"'})


@router.post("/import/{dataset_key}")
async def import_dataset(
    dataset_key: str,
    file: UploadFile = File(...),
    chunk_size: int = Form(default=50, alias="chunkSize"),
    db: AsyncSession = Depends(get_db),
):
    user = await ensure_admin_user(db)
    dataset = data_synchronize_service.get_dataset(dataset_key)
    if not dataset or not dataset.supports_import:
        raise HTTPException(404, "Import dataset not found")
    if chunk_size < 1 or chunk_size > 1000:
        raise HTTPException(422, {"fieldErrors": {"chunkSize": "Chunk size must be between 1 and 1000."}})
    content = await file.read()
    try:
        rows = data_synchronize_service.parse_import_file(content, file.filename or "", dataset)
    except DataSyncImportValidationError as exception:
        raise HTTPException(422, str(exception)) from exception
    except Exception as exception:
        raise HTTPException(422, "The import file could not be processed. Please check the file and try again.") from exception
    result = await data_synchronize_service.import_dataset(db, dataset_key, rows, user_id=user.id)
    return BaseHttpResponse.make().set_data(result).with_updated_success_message().to_dict()
