"""API routes for the Location plugin."""

from __future__ import annotations

import asyncio
import io
from typing import Any, Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from karpy_platform.plugins.location.models.location import City, Country, State
from karpy_platform.plugins.location.services.locations import (
    LOCATION_DATA_SOURCE_URL,
    build_export_rows,
    count_model,
    example_rows,
    export_csv,
    import_rows,
    list_repo_countries,
    location_counts,
    parse_csv_bytes,
    parse_xlsx_bytes,
    rows_from_repo_country,
    serialize_city,
    serialize_country,
    serialize_state,
    slugify,
    validate_location_row,
)

router = APIRouter()


async def require_admin(request: Request, db: AsyncSession = Depends(get_db)):
    # A real admin session is required (this used to return the bootstrap admin for any caller).
    from karpy_platform.core.acl.admin_guard import require_admin_session

    return await require_admin_session(request, db)


class CountryPayload(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    slug: str | None = Field(default=None, max_length=120)
    code: str | None = Field(default=None, max_length=10)
    abbreviation: str | None = Field(default=None, max_length=10)
    nationality: str | None = Field(default=None, max_length=120)
    image: str | None = Field(default=None, max_length=500)
    order: int = Field(default=0, ge=0, le=127)
    status: str = "published"
    isDefault: bool = False


class StatePayload(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    slug: str | None = Field(default=None, max_length=120)
    abbreviation: str | None = Field(default=None, max_length=10)
    countryId: str = Field(min_length=1)
    order: int = Field(default=0, ge=0, le=127)
    status: str = "published"


class CityPayload(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    slug: str | None = Field(default=None, max_length=120)
    zipCode: str | None = Field(default=None, max_length=30)
    countryId: str = Field(min_length=1)
    stateId: str | None = None
    order: int = Field(default=0, ge=0, le=127)
    status: str = "published"


class AvailableImportPayload(BaseModel):
    countryCode: str | None = None
    countryCodes: list[str] = Field(default_factory=list)
    skipExistingRecords: bool = True


class ExportPayload(BaseModel):
    columns: list[str] = Field(default_factory=lambda: ["name", "slug", "import_type", "order", "abbreviation", "status", "country", "state", "nationality"])
    format: Literal["csv", "excel"] = "csv"
    locationType: Literal["all", "country", "state", "city"] = "all"
    status: str = "all"
    useChunkedExport: bool = True
    optimizeMemory: bool = True
    useStreaming: bool = False
    chunkSize: int = Field(default=300, ge=1, le=5000)


class BulkDeletePayload(BaseModel):
    ids: list[str] = Field(default_factory=list)


def _status_check(value: str) -> str:
    status = value.strip().lower()
    if status not in {"published", "draft", "pending", "disabled"}:
        raise HTTPException(status_code=422, detail={"status": "The status must be one of: published, draft, pending, disabled."})
    return status


async def _delete_country_tree(db: AsyncSession, country_id: str) -> tuple[int, int]:
    states_count = await count_model(db, State, [State.is_deleted.is_(False), State.country_id == country_id])
    cities_count = await count_model(db, City, [City.is_deleted.is_(False), City.country_id == country_id])
    await db.execute(update(State).where(State.country_id == country_id).values(is_deleted=True))
    await db.execute(update(City).where(City.country_id == country_id).values(is_deleted=True))
    return states_count, cities_count


async def _delete_state_tree(db: AsyncSession, state_id: str) -> int:
    cities_count = await count_model(db, City, [City.is_deleted.is_(False), City.state_id == state_id])
    await db.execute(update(City).where(City.state_id == state_id).values(is_deleted=True))
    return cities_count


async def _list_response(db: AsyncSession, model, serializer, statement, page: int, per_page: int) -> dict[str, Any]:
    total = await count_model(db, model, [model.is_deleted.is_(False)])
    rows = await db.execute(statement.offset((page - 1) * per_page).limit(per_page))
    return {"data": [serializer(row) for row in rows.scalars().all()], "meta": {"page": page, "perPage": per_page, "total": total}}


@router.get("/public/countries")
async def public_countries(db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    result = await db.execute(
        select(Country)
        .where(Country.is_deleted.is_(False), Country.status == "published")
        .order_by(Country.order.asc(), Country.name.asc())
    )
    return {"data": [serialize_country(country) for country in result.scalars().all()]}


@router.get("/public/states")
async def public_states(country_id: str = Query(alias="countryId"), db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    result = await db.execute(
        select(State)
        .options(selectinload(State.country))
        .where(State.is_deleted.is_(False), State.status == "published", State.country_id == country_id)
        .order_by(State.order.asc(), State.name.asc())
    )
    return {"data": [serialize_state(state) for state in result.scalars().all()]}


@router.get("/public/cities")
async def public_cities(
    country_id: str | None = Query(default=None, alias="countryId"),
    state_id: str | None = Query(default=None, alias="stateId"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    filters = [City.is_deleted.is_(False), City.status == "published"]
    if country_id:
        filters.append(City.country_id == country_id)
    if state_id:
        filters.append(City.state_id == state_id)
    result = await db.execute(
        select(City)
        .options(selectinload(City.country), selectinload(City.state))
        .where(*filters)
        .order_by(City.order.asc(), City.name.asc())
    )
    return {"data": [serialize_city(city) for city in result.scalars().all()]}


@router.get("/ajax/states-by-country")
async def states_by_country(country_id: str = Query(alias="country_id"), db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    return await public_states(country_id=country_id, db=db)


@router.get("/ajax/cities-by-state")
async def cities_by_state(
    state_id: str | None = Query(default=None, alias="state_id"),
    country_id: str | None = Query(default=None, alias="country_id"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return await public_cities(country_id=country_id, state_id=state_id, db=db)


@router.get("/", dependencies=[Depends(require_admin)])
async def index(db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    return {"plugin": "location", "name": "Location", "status": "ready", "counts": await location_counts(db)}


@router.get("/countries", dependencies=[Depends(require_admin)])
async def countries(
    q: str | None = None,
    status: str | None = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(15, ge=1, le=5000, alias="perPage"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    filters = [Country.is_deleted.is_(False)]
    if q:
        like = f"%{q.strip()}%"
        filters.append(or_(Country.name.ilike(like), Country.code.ilike(like), Country.nationality.ilike(like)))
    if status and status != "all":
        filters.append(Country.status == status)
    total = await count_model(db, Country, filters)
    rows = await db.execute(
        select(Country).where(*filters).order_by(Country.order.asc(), Country.name.asc()).offset((page - 1) * per_page).limit(per_page)
    )
    return {"data": [serialize_country(country) for country in rows.scalars().all()], "meta": {"page": page, "perPage": per_page, "total": total}}


@router.post("/countries", dependencies=[Depends(require_admin)])
async def create_country(payload: CountryPayload, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    country = Country(
        name=payload.name.strip(),
        slug=payload.slug or slugify(payload.name),
        code=payload.code.upper() if payload.code else None,
        abbreviation=payload.abbreviation,
        nationality=payload.nationality,
        image=payload.image,
        order=payload.order,
        status=_status_check(payload.status),
        is_default=payload.isDefault,
    )
    db.add(country)
    await db.commit()
    await db.refresh(country)
    return {"country": serialize_country(country)}


@router.get("/countries/{country_id}", dependencies=[Depends(require_admin)])
async def country_detail(country_id: str, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    country = await db.get(Country, country_id)
    if not country or country.is_deleted:
        raise HTTPException(status_code=404, detail="Country not found.")
    return {"country": serialize_country(country)}


@router.patch("/countries/{country_id}", dependencies=[Depends(require_admin)])
async def update_country(country_id: str, payload: CountryPayload, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    country = await db.get(Country, country_id)
    if not country or country.is_deleted:
        raise HTTPException(status_code=404, detail="Country not found.")
    country.name = payload.name.strip()
    country.slug = payload.slug or slugify(payload.name)
    country.code = payload.code.upper() if payload.code else None
    country.abbreviation = payload.abbreviation
    country.nationality = payload.nationality
    country.image = payload.image
    country.order = payload.order
    country.status = _status_check(payload.status)
    country.is_default = payload.isDefault
    await db.commit()
    await db.refresh(country)
    return {"country": serialize_country(country)}


@router.delete("/countries/{country_id}", dependencies=[Depends(require_admin)])
async def delete_country(country_id: str, db: AsyncSession = Depends(get_db)) -> dict[str, str]:
    country = await db.get(Country, country_id)
    if not country or country.is_deleted:
        raise HTTPException(status_code=404, detail="Country not found.")
    country.is_deleted = True
    states_count, cities_count = await _delete_country_tree(db, country_id)
    await db.commit()
    return {"message": f"Country deleted with {states_count} states and {cities_count} cities."}


@router.post("/countries/bulk-delete", dependencies=[Depends(require_admin)])
async def bulk_delete_countries(payload: BulkDeletePayload, db: AsyncSession = Depends(get_db)) -> dict[str, str]:
    ids = [item for item in dict.fromkeys(payload.ids) if item]
    if not ids:
        raise HTTPException(status_code=422, detail={"ids": "Please select at least one country."})
    deleted = states_count = cities_count = 0
    countries = (await db.execute(select(Country).where(Country.id.in_(ids), Country.is_deleted.is_(False)))).scalars().all()
    for country in countries:
        country.is_deleted = True
        child_states, child_cities = await _delete_country_tree(db, country.id)
        states_count += child_states
        cities_count += child_cities
        deleted += 1
    await db.commit()
    return {"message": f"{deleted} countries deleted with {states_count} states and {cities_count} cities."}


@router.get("/states", dependencies=[Depends(require_admin)])
async def states(
    q: str | None = None,
    country_id: str | None = Query(default=None, alias="countryId"),
    status: str | None = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(15, ge=1, le=5000, alias="perPage"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    filters = [State.is_deleted.is_(False), State.country.has(Country.is_deleted.is_(False))]
    if q:
        like = f"%{q.strip()}%"
        filters.append(or_(State.name.ilike(like), State.abbreviation.ilike(like)))
    if country_id:
        filters.append(State.country_id == country_id)
    if status and status != "all":
        filters.append(State.status == status)
    total = await count_model(db, State, filters)
    rows = await db.execute(
        select(State)
        .options(selectinload(State.country))
        .where(*filters)
        .order_by(State.order.asc(), State.name.asc())
        .offset((page - 1) * per_page)
        .limit(per_page)
    )
    return {"data": [serialize_state(state) for state in rows.scalars().all()], "meta": {"page": page, "perPage": per_page, "total": total}}


@router.post("/states", dependencies=[Depends(require_admin)])
async def create_state(payload: StatePayload, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    country = await db.get(Country, payload.countryId)
    if not country or country.is_deleted:
        raise HTTPException(status_code=422, detail={"countryId": "The selected country is invalid."})
    state = State(name=payload.name.strip(), slug=payload.slug or slugify(payload.name), abbreviation=payload.abbreviation, country_id=payload.countryId, order=payload.order, status=_status_check(payload.status))
    db.add(state)
    await db.commit()
    state = await db.scalar(select(State).options(selectinload(State.country)).where(State.id == state.id))
    return {"state": serialize_state(state)}


@router.get("/states/{state_id}", dependencies=[Depends(require_admin)])
async def state_detail(state_id: str, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    state = await db.scalar(select(State).options(selectinload(State.country)).where(State.id == state_id))
    if not state or state.is_deleted:
        raise HTTPException(status_code=404, detail="State not found.")
    return {"state": serialize_state(state)}


@router.patch("/states/{state_id}", dependencies=[Depends(require_admin)])
async def update_state(state_id: str, payload: StatePayload, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    state = await db.get(State, state_id)
    if not state or state.is_deleted:
        raise HTTPException(status_code=404, detail="State not found.")
    country = await db.get(Country, payload.countryId)
    if not country or country.is_deleted:
        raise HTTPException(status_code=422, detail={"countryId": "The selected country is invalid."})
    state.name = payload.name.strip()
    state.slug = payload.slug or slugify(payload.name)
    state.abbreviation = payload.abbreviation
    state.country_id = payload.countryId
    state.order = payload.order
    state.status = _status_check(payload.status)
    await db.commit()
    state = await db.scalar(select(State).options(selectinload(State.country)).where(State.id == state_id))
    return {"state": serialize_state(state)}


@router.delete("/states/{state_id}", dependencies=[Depends(require_admin)])
async def delete_state(state_id: str, db: AsyncSession = Depends(get_db)) -> dict[str, str]:
    state = await db.get(State, state_id)
    if not state or state.is_deleted:
        raise HTTPException(status_code=404, detail="State not found.")
    state.is_deleted = True
    cities_count = await _delete_state_tree(db, state_id)
    await db.commit()
    return {"message": f"State deleted with {cities_count} cities."}


@router.post("/states/bulk-delete", dependencies=[Depends(require_admin)])
async def bulk_delete_states(payload: BulkDeletePayload, db: AsyncSession = Depends(get_db)) -> dict[str, str]:
    ids = [item for item in dict.fromkeys(payload.ids) if item]
    if not ids:
        raise HTTPException(status_code=422, detail={"ids": "Please select at least one state."})
    deleted = cities_count = 0
    states = (await db.execute(select(State).where(State.id.in_(ids), State.is_deleted.is_(False)))).scalars().all()
    for state in states:
        state.is_deleted = True
        cities_count += await _delete_state_tree(db, state.id)
        deleted += 1
    await db.commit()
    return {"message": f"{deleted} states deleted with {cities_count} cities."}


@router.get("/cities", dependencies=[Depends(require_admin)])
async def cities(
    q: str | None = None,
    country_id: str | None = Query(default=None, alias="countryId"),
    state_id: str | None = Query(default=None, alias="stateId"),
    status: str | None = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(15, ge=1, le=5000, alias="perPage"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    filters = [
        City.is_deleted.is_(False),
        City.country.has(Country.is_deleted.is_(False)),
        or_(City.state_id.is_(None), City.state.has(State.is_deleted.is_(False))),
    ]
    if q:
        like = f"%{q.strip()}%"
        filters.append(or_(City.name.ilike(like), City.zip_code.ilike(like)))
    if country_id:
        filters.append(City.country_id == country_id)
    if state_id:
        filters.append(City.state_id == state_id)
    if status and status != "all":
        filters.append(City.status == status)
    total = await count_model(db, City, filters)
    rows = await db.execute(
        select(City)
        .options(selectinload(City.country), selectinload(City.state))
        .where(*filters)
        .order_by(City.order.asc(), City.name.asc())
        .offset((page - 1) * per_page)
        .limit(per_page)
    )
    return {"data": [serialize_city(city) for city in rows.scalars().all()], "meta": {"page": page, "perPage": per_page, "total": total}}


@router.post("/cities", dependencies=[Depends(require_admin)])
async def create_city(payload: CityPayload, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    country = await db.get(Country, payload.countryId)
    if not country or country.is_deleted:
        raise HTTPException(status_code=422, detail={"countryId": "The selected country is invalid."})
    if payload.stateId:
        state = await db.get(State, payload.stateId)
        if not state or state.is_deleted:
            raise HTTPException(status_code=422, detail={"stateId": "The selected state is invalid."})
        if state.country_id != payload.countryId:
            raise HTTPException(status_code=422, detail={"stateId": "The selected state does not belong to the selected country."})
    city = City(name=payload.name.strip(), slug=payload.slug or slugify(payload.name), zip_code=payload.zipCode, country_id=payload.countryId, state_id=payload.stateId, order=payload.order, status=_status_check(payload.status))
    db.add(city)
    await db.commit()
    city = await db.scalar(select(City).options(selectinload(City.country), selectinload(City.state)).where(City.id == city.id))
    return {"city": serialize_city(city)}


@router.get("/cities/{city_id}", dependencies=[Depends(require_admin)])
async def city_detail(city_id: str, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    city = await db.scalar(select(City).options(selectinload(City.country), selectinload(City.state)).where(City.id == city_id))
    if not city or city.is_deleted:
        raise HTTPException(status_code=404, detail="City not found.")
    return {"city": serialize_city(city)}


@router.patch("/cities/{city_id}", dependencies=[Depends(require_admin)])
async def update_city(city_id: str, payload: CityPayload, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    city = await db.get(City, city_id)
    if not city or city.is_deleted:
        raise HTTPException(status_code=404, detail="City not found.")
    country = await db.get(Country, payload.countryId)
    if not country or country.is_deleted:
        raise HTTPException(status_code=422, detail={"countryId": "The selected country is invalid."})
    if payload.stateId:
        state = await db.get(State, payload.stateId)
        if not state or state.is_deleted:
            raise HTTPException(status_code=422, detail={"stateId": "The selected state is invalid."})
        if state.country_id != payload.countryId:
            raise HTTPException(status_code=422, detail={"stateId": "The selected state does not belong to the selected country."})
    city.name = payload.name.strip()
    city.slug = payload.slug or slugify(payload.name)
    city.zip_code = payload.zipCode
    city.country_id = payload.countryId
    city.state_id = payload.stateId
    city.order = payload.order
    city.status = _status_check(payload.status)
    await db.commit()
    city = await db.scalar(select(City).options(selectinload(City.country), selectinload(City.state)).where(City.id == city_id))
    return {"city": serialize_city(city)}


@router.delete("/cities/{city_id}", dependencies=[Depends(require_admin)])
async def delete_city(city_id: str, db: AsyncSession = Depends(get_db)) -> dict[str, str]:
    city = await db.get(City, city_id)
    if not city or city.is_deleted:
        raise HTTPException(status_code=404, detail="City not found.")
    city.is_deleted = True
    await db.commit()
    return {"message": "City deleted."}


@router.post("/cities/bulk-delete", dependencies=[Depends(require_admin)])
async def bulk_delete_cities(payload: BulkDeletePayload, db: AsyncSession = Depends(get_db)) -> dict[str, str]:
    ids = [item for item in dict.fromkeys(payload.ids) if item]
    if not ids:
        raise HTTPException(status_code=422, detail={"ids": "Please select at least one city."})
    result = await db.execute(update(City).where(City.id.in_(ids), City.is_deleted.is_(False)).values(is_deleted=True))
    await db.commit()
    return {"message": f"{result.rowcount or 0} cities deleted."}


@router.get("/import/available", dependencies=[Depends(require_admin)])
async def import_available(db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    source_error: str | None = None
    try:
        imported = await db.execute(select(Country.code).where(Country.is_deleted.is_(False), Country.code.isnot(None)))
        imported_codes = {str(code).upper() for code in imported.scalars().all() if code}
    except Exception:
        imported_codes = set()
    try:
        countries = await asyncio.to_thread(list_repo_countries)
    except Exception as exc:
        countries = []
        source_error = f"Unable to load the location catalog right now: {exc}"
    return {
        "sourceUrl": LOCATION_DATA_SOURCE_URL,
        "countries": [{**country, "imported": str(country["code"]).upper() in imported_codes} for country in countries],
        "sourceError": source_error,
    }


@router.post("/import/available", dependencies=[Depends(require_admin)])
async def import_available_store(payload: AvailableImportPayload, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    codes = payload.countryCodes or ([payload.countryCode] if payload.countryCode else [])
    codes = [code for code in codes if code]
    if not codes:
        raise HTTPException(status_code=422, detail={"countryCode": "Please choose at least one country to import."})

    imported = skipped = 0
    errors: dict[str, str] = {}
    for code in codes:
        try:
            rows = await asyncio.to_thread(rows_from_repo_country, code)
            row_errors = {}
            for index, row in enumerate(rows, start=1):
                row_errors.update(validate_location_row(row, index))
            if row_errors:
                errors.update({f"{code}.{key}": value for key, value in row_errors.items()})
                continue
            result = await import_rows(db, rows, skip_existing=payload.skipExistingRecords)
            imported += result.imported
            skipped += result.skipped
        except Exception as exc:
            errors[code] = str(exc)

    if errors:
        raise HTTPException(status_code=422, detail=errors)
    return {"message": "Locations imported successfully.", "imported": imported, "skipped": skipped}


@router.post("/import/file", dependencies=[Depends(require_admin)])
async def import_file(
    file: UploadFile = File(...),
    chunk_size: int = Form(200, alias="chunkSize"),
    skip_existing_records: bool = Form(False, alias="skipExistingRecords"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    content = await file.read()
    name = (file.filename or "").lower()
    if name.endswith(".csv"):
        rows = parse_csv_bytes(content)
    elif name.endswith(".xlsx") or name.endswith(".xls"):
        rows = parse_xlsx_bytes(content)
    else:
        raise HTTPException(status_code=422, detail={"file": "The file must be a CSV, XLS, or XLSX file."})

    errors: dict[str, str] = {}
    for index, row in enumerate(rows, start=1):
        errors.update(validate_location_row(row, index))
    if errors:
        raise HTTPException(status_code=422, detail=errors)

    result = await import_rows(db, rows, skip_existing=skip_existing_records)
    return {"message": "Locations imported successfully.", "imported": result.imported, "skipped": result.skipped}


@router.get("/import/example", dependencies=[Depends(require_admin)])
async def import_example(format: Literal["csv", "excel"] = "csv") -> StreamingResponse:
    columns = ["name", "slug", "import_type", "order", "abbreviation", "status", "country", "state", "nationality"]
    if format == "excel":
        from openpyxl import Workbook

        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Locations"
        sheet.append(columns)
        for row in example_rows():
            sheet.append([row.get(column, "") for column in columns])
        stream = io.BytesIO()
        workbook.save(stream)
        stream.seek(0)
        return StreamingResponse(stream, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": "attachment; filename=location-import-example.xlsx"})

    csv_text = export_csv(example_rows(), columns)
    return StreamingResponse(io.BytesIO(csv_text.encode("utf-8-sig")), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=location-import-example.csv"})


@router.get("/export/options", dependencies=[Depends(require_admin)])
async def export_options(db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    return {"counts": await location_counts(db), "columns": ["name", "slug", "state", "country", "status", "order", "abbreviation", "import_type", "nationality"]}


@router.post("/export", dependencies=[Depends(require_admin)])
async def export_locations(payload: ExportPayload, db: AsyncSession = Depends(get_db)) -> StreamingResponse:
    columns = payload.columns or ["name", "slug", "import_type", "order", "abbreviation", "status", "country", "state", "nationality"]
    filters = {"country": [], "state": [], "city": []}
    if payload.status != "all":
        filters["country"].append(Country.status == payload.status)
        filters["state"].append(State.status == payload.status)
        filters["city"].append(City.status == payload.status)
    filters["country"].append(Country.is_deleted.is_(False))
    filters["state"].append(State.is_deleted.is_(False))
    filters["city"].append(City.is_deleted.is_(False))

    countries: list[Country] = []
    states: list[State] = []
    cities: list[City] = []
    if payload.locationType in {"all", "country"}:
        countries = (await db.execute(select(Country).where(*filters["country"]).order_by(Country.name.asc()))).scalars().all()
    if payload.locationType in {"all", "state"}:
        states = (await db.execute(select(State).options(selectinload(State.country)).where(*filters["state"]).order_by(State.name.asc()))).scalars().all()
    if payload.locationType in {"all", "city"}:
        cities = (await db.execute(select(City).options(selectinload(City.country), selectinload(City.state)).where(*filters["city"]).order_by(City.name.asc()))).scalars().all()
    rows = build_export_rows(countries, states, cities, columns)

    if payload.format == "excel":
        from openpyxl import Workbook

        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Locations"
        sheet.append(columns)
        for row in rows:
            sheet.append([row.get(column, "") for column in columns])
        stream = io.BytesIO()
        workbook.save(stream)
        stream.seek(0)
        return StreamingResponse(stream, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": "attachment; filename=locations.xlsx"})

    csv_text = export_csv(rows, columns)
    return StreamingResponse(io.BytesIO(csv_text.encode("utf-8-sig")), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=locations.csv"})
