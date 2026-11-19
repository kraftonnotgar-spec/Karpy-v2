"""Location import/export helpers."""

from __future__ import annotations

import csv
import io
import json
import os
import re
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from karpy_platform.plugins.location.models.location import City, Country, State

RAW_BASES = (
    "https://fastly.jsdelivr.net/gh/kraftonnotgar-spec/location@main",
    "https://cdn.jsdelivr.net/gh/kraftonnotgar-spec/location@main",
)
CATALOG_URL = "https://fastly.jsdelivr.net/gh/dr5hn/countries-states-cities-database@master/json/countries.json"
LOCATION_DATA_SOURCE_URL = "https://www.jsdelivr.com/package/gh/dr5hn/countries-states-cities-database"
LOCAL_DATA_PATH = os.getenv("KARPY_LOCATION_DATA_PATH")
STATUS_VALUES = {"published", "draft", "pending", "disabled"}
IMPORT_TYPES = {"country", "state", "city"}


@dataclass
class ImportResult:
    imported: int = 0
    skipped: int = 0


def slugify(value: str | None) -> str | None:
    if not value:
        return None
    text = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
    return text or None


def serialize_country(country: Country) -> dict[str, Any]:
    return {
        "id": country.id,
        "name": country.name,
        "slug": country.slug,
        "code": country.code,
        "abbreviation": country.abbreviation,
        "nationality": country.nationality,
        "image": country.image,
        "order": country.order,
        "status": country.status,
        "isDefault": country.is_default,
        "createdAt": country.created_at.isoformat() if country.created_at else None,
        "updatedAt": country.updated_at.isoformat() if country.updated_at else None,
    }


def serialize_state(state: State) -> dict[str, Any]:
    return {
        "id": state.id,
        "name": state.name,
        "slug": state.slug,
        "abbreviation": state.abbreviation,
        "countryId": state.country_id,
        "countryName": state.country.name if state.country else None,
        "order": state.order,
        "status": state.status,
        "createdAt": state.created_at.isoformat() if state.created_at else None,
        "updatedAt": state.updated_at.isoformat() if state.updated_at else None,
    }


def serialize_city(city: City) -> dict[str, Any]:
    return {
        "id": city.id,
        "name": city.name,
        "slug": city.slug,
        "zipCode": city.zip_code,
        "countryId": city.country_id,
        "countryName": city.country.name if city.country else None,
        "stateId": city.state_id,
        "stateName": city.state.name if city.state else None,
        "order": city.order,
        "status": city.status,
        "createdAt": city.created_at.isoformat() if city.created_at else None,
        "updatedAt": city.updated_at.isoformat() if city.updated_at else None,
    }


async def count_model(db: AsyncSession, model, filters: list[Any] | None = None) -> int:
    statement = select(func.count()).select_from(model)
    if filters:
        statement = statement.where(*filters)
    result = await db.execute(statement)
    return int(result.scalar() or 0)


async def location_counts(db: AsyncSession) -> dict[str, int]:
    country_filter = [Country.is_deleted.is_(False)]
    state_filter = [State.is_deleted.is_(False)]
    city_filter = [City.is_deleted.is_(False)]
    countries = await count_model(db, Country, country_filter)
    states = await count_model(db, State, state_filter)
    cities = await count_model(db, City, city_filter)
    return {
        "countries": countries,
        "states": states,
        "cities": cities,
        "locations": countries + states + cities,
    }


@lru_cache(maxsize=1)
def list_repo_countries() -> list[dict[str, Any]]:
    """Return the import catalog using one cacheable request instead of one request per country."""
    local_path = Path(LOCAL_DATA_PATH) if LOCAL_DATA_PATH else None
    if local_path and local_path.exists():
        codes = _repo_codes()
        countries: list[dict[str, Any]] = []
        for code in codes:
            data = _read_country_json(code)
            if data:
                countries.append(
                    {
                        "code": (data.get("code") or code).upper(),
                        "key": code.lower(),
                        "name": data.get("name") or code.upper(),
                        "nationality": data.get("nationality"),
                        "status": data.get("status") or "published",
                    }
                )
        return sorted(countries, key=lambda item: item["name"])

    payload = _read_remote_json(CATALOG_URL, timeout=20)
    if not isinstance(payload, list):
        raise ValueError("The location catalog returned an invalid response.")
    countries: list[dict[str, Any]] = []
    for data in payload:
        if not isinstance(data, dict):
            continue
        code = str(data.get("iso2") or "").strip().upper()
        name = str(data.get("name") or "").strip()
        if len(code) != 2 or not name:
            continue
        countries.append(
            {
                "code": code,
                "key": code.lower(),
                "name": name,
                "nationality": data.get("nationality"),
                "status": "published",
            }
        )
    return sorted(countries, key=lambda item: item["name"])


def _repo_codes() -> list[str]:
    local_path = Path(LOCAL_DATA_PATH) if LOCAL_DATA_PATH else Path(os.getenv("TEMP", "")) / "karpy-location-data"
    if local_path.exists():
        return sorted(path.name.lower() for path in local_path.iterdir() if path.is_dir() and len(path.name) == 2)
    return []


def _read_country_json(code: str) -> dict[str, Any] | None:
    try:
        return _read_json(f"{code.lower()}/country.json")
    except Exception:
        return None


def _read_json(path: str) -> Any:
    local_path = Path(LOCAL_DATA_PATH) if LOCAL_DATA_PATH else Path(os.getenv("TEMP", "")) / "karpy-location-data"
    if local_path.exists():
        with local_path.joinpath(path).open("r", encoding="utf-8") as stream:
            return json.load(stream)

    last_error: Exception | None = None
    for base_url in RAW_BASES:
        try:
            return _read_remote_json(f"{base_url}/{path}", timeout=12)
        except (OSError, TimeoutError, urllib.error.URLError, json.JSONDecodeError) as exc:
            last_error = exc
    raise RuntimeError(f"Location data is temporarily unavailable for {path}.") from last_error


def _read_remote_json(url: str, timeout: int) -> Any:
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "User-Agent": "KARPy-Location-Importer/1.0"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def rows_from_repo_country(code: str) -> list[dict[str, Any]]:
    key = code.strip().lower()
    paths = (f"{key}/country.json", f"{key}/states.json", f"{key}/cities.json")
    with ThreadPoolExecutor(max_workers=3, thread_name_prefix="location-import") as executor:
        country, states, cities = executor.map(_read_json, paths)
    country_name = country.get("name") or key.upper()
    rows = [
        {
            "name": country_name,
            "slug": slugify(country_name) or "",
            "import_type": "country",
            "order": min(max(int(country.get("order") or 0), 0), 127),
            "abbreviation": country.get("abbreviation") or "",
            "status": country.get("status") or "published",
            "country": "",
            "state": "",
            "nationality": country.get("nationality") or "",
            "code": country.get("code") or key.upper(),
            "is_default": bool(country.get("is_default")),
        }
    ]
    for index, state in enumerate(states or []):
        state_name = state.get("name") if isinstance(state, dict) else str(state)
        rows.append(
            {
                "name": state_name,
                "slug": slugify(state_name) or "",
                "import_type": "state",
                "order": min(max(int(state.get("order") or index if isinstance(state, dict) else index), 0), 127),
                "abbreviation": state.get("abbreviation") if isinstance(state, dict) else "",
                "status": (state.get("status") if isinstance(state, dict) else None) or "published",
                "country": country_name,
                "state": "",
                "nationality": "",
            }
        )
    for state_group in cities or []:
        state_name = state_group.get("name") if isinstance(state_group, dict) else ""
        for city_name in state_group.get("cities", []) if isinstance(state_group, dict) else []:
            rows.append(
                {
                    "name": str(city_name),
                    "slug": slugify(str(city_name)) or "",
                    "import_type": "city",
                    "order": 0,
                    "abbreviation": "",
                    "status": "published",
                    "country": country_name,
                    "state": state_name,
                    "nationality": "",
                }
            )
    return rows


def validate_location_row(row: dict[str, Any], index: int) -> dict[str, str]:
    prefix = f"rows.{index}"
    errors: dict[str, str] = {}
    name = str(row.get("name") or "").strip()
    import_type = str(row.get("import_type") or "").strip().lower()
    status = str(row.get("status") or "").strip().lower()
    order_value = row.get("order")

    if not name:
        errors[f"{prefix}.name"] = "The name field is required."
    elif len(name) > 120:
        errors[f"{prefix}.name"] = "The name may not be greater than 120 characters."

    slug = str(row.get("slug") or "").strip()
    if slug and len(slug) > 120:
        errors[f"{prefix}.slug"] = "The slug may not be greater than 120 characters."

    if import_type not in IMPORT_TYPES:
        errors[f"{prefix}.import_type"] = "The import type must be country, state, or city."

    if status not in STATUS_VALUES:
        errors[f"{prefix}.status"] = "The status must be one of: published, draft, pending, disabled."

    if import_type in {"state", "city"} and not str(row.get("country") or "").strip():
        errors[f"{prefix}.country"] = "The country field is required when import type is state or city."

    if import_type == "city" and not str(row.get("state") or "").strip():
        errors[f"{prefix}.state"] = "The state field is required when import type is city."

    abbreviation = str(row.get("abbreviation") or "").strip()
    if abbreviation and len(abbreviation) > 10:
        errors[f"{prefix}.abbreviation"] = "The abbreviation may not be greater than 10 characters."

    nationality = str(row.get("nationality") or "").strip()
    if nationality and len(nationality) > 120:
        errors[f"{prefix}.nationality"] = "The nationality may not be greater than 120 characters."

    if order_value not in (None, ""):
        try:
            order = int(order_value)
            if order < 0 or order > 127:
                errors[f"{prefix}.order"] = "The order must be between 0 and 127."
        except (TypeError, ValueError):
            errors[f"{prefix}.order"] = "The order must be an integer."

    return errors


async def import_rows(db: AsyncSession, rows: Iterable[dict[str, Any]], skip_existing: bool = False) -> ImportResult:
    result = ImportResult()
    country_cache: dict[str, Country] = {}
    state_cache: dict[tuple[str, str], State] = {}

    for row in rows:
        import_type = str(row.get("import_type") or "state").strip().lower()
        if import_type == "country":
            country, created = await upsert_country(db, row, skip_existing=skip_existing)
            country_cache[country.name.lower()] = country
            result.imported += 1 if created else 0
            result.skipped += 0 if created else 1
        elif import_type == "state":
            country = await get_or_create_country(db, str(row.get("country") or ""), country_cache)
            state, created = await upsert_state(db, row, country.id, skip_existing=skip_existing)
            state_cache[(country.id, state.name.lower())] = state
            result.imported += 1 if created else 0
            result.skipped += 0 if created else 1
        elif import_type == "city":
            country = await get_or_create_country(db, str(row.get("country") or ""), country_cache)
            state = await get_or_create_state(db, str(row.get("state") or ""), country.id, state_cache)
            _, created = await upsert_city(db, row, country.id, state.id, skip_existing=skip_existing)
            result.imported += 1 if created else 0
            result.skipped += 0 if created else 1

    await db.commit()
    return result


async def get_or_create_country(db: AsyncSession, name: str, cache: dict[str, Country]) -> Country:
    key = name.strip().lower()
    if key in cache:
        return cache[key]
    found = await db.execute(select(Country).where(Country.name == name))
    country = found.scalars().first()
    if not country:
        country = Country(name=name, slug=slugify(name), nationality=_guess_nationality(name), status="published")
        db.add(country)
        await db.flush()
    elif country.is_deleted:
        country.is_deleted = False
        country.status = country.status or "published"
        await db.flush()
    cache[key] = country
    return country


async def get_or_create_state(db: AsyncSession, name: str, country_id: str, cache: dict[tuple[str, str], State]) -> State:
    key = (country_id, name.strip().lower())
    if key in cache:
        return cache[key]
    found = await db.execute(select(State).where(State.name == name, State.country_id == country_id))
    state = found.scalars().first()
    if not state:
        state = State(name=name, slug=slugify(name), country_id=country_id, status="published")
        db.add(state)
        await db.flush()
    elif state.is_deleted:
        state.is_deleted = False
        state.status = state.status or "published"
        await db.flush()
    cache[key] = state
    return state


async def upsert_country(db: AsyncSession, row: dict[str, Any], skip_existing: bool = False) -> tuple[Country, bool]:
    name = str(row.get("name") or "").strip()
    found = await db.execute(select(Country).where(Country.name == name))
    country = found.scalars().first()
    if country:
        was_deleted = country.is_deleted
        if skip_existing and not was_deleted:
            return country, False
        country.is_deleted = False
    else:
        country = Country(name=name)
        db.add(country)
    country.slug = str(row.get("slug") or "").strip() or slugify(name)
    country.code = str(row.get("code") or country.code or "").strip().upper() or None
    country.abbreviation = str(row.get("abbreviation") or "").strip() or None
    country.nationality = str(row.get("nationality") or "").strip() or country.nationality or _guess_nationality(name)
    country.order = int(row.get("order") or 0)
    country.status = str(row.get("status") or "published").strip().lower()
    country.is_default = bool(row.get("is_default", country.is_default))
    await db.flush()
    return country, True


async def upsert_state(db: AsyncSession, row: dict[str, Any], country_id: str, skip_existing: bool = False) -> tuple[State, bool]:
    name = str(row.get("name") or "").strip()
    found = await db.execute(select(State).where(State.name == name, State.country_id == country_id))
    state = found.scalars().first()
    if state:
        was_deleted = state.is_deleted
        if skip_existing and not was_deleted:
            return state, False
        state.is_deleted = False
    else:
        state = State(name=name, country_id=country_id)
        db.add(state)
    state.slug = str(row.get("slug") or "").strip() or slugify(name)
    state.abbreviation = str(row.get("abbreviation") or "").strip() or None
    state.order = int(row.get("order") or 0)
    state.status = str(row.get("status") or "published").strip().lower()
    await db.flush()
    return state, True


async def upsert_city(db: AsyncSession, row: dict[str, Any], country_id: str, state_id: str | None, skip_existing: bool = False) -> tuple[City, bool]:
    name = str(row.get("name") or "").strip()
    found = await db.execute(
        select(City).where(City.name == name, City.country_id == country_id, City.state_id == state_id)
    )
    city = found.scalars().first()
    if city:
        was_deleted = city.is_deleted
        if skip_existing and not was_deleted:
            return city, False
        city.is_deleted = False
    else:
        city = City(name=name, country_id=country_id, state_id=state_id)
        db.add(city)
    city.slug = str(row.get("slug") or "").strip() or slugify(name)
    city.zip_code = str(row.get("zip_code") or row.get("zipCode") or "").strip() or None
    city.order = int(row.get("order") or 0)
    city.status = str(row.get("status") or "published").strip().lower()
    await db.flush()
    return city, True


def parse_csv_bytes(content: bytes) -> list[dict[str, Any]]:
    text = content.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    return [normalize_import_row(row) for row in reader]


def parse_xlsx_bytes(content: bytes) -> list[dict[str, Any]]:
    from openpyxl import load_workbook

    workbook = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    sheet = workbook.active
    rows = list(sheet.iter_rows(values_only=True))
    if not rows:
        return []
    headers = [str(cell or "").strip().lower().replace(" ", "_") for cell in rows[0]]
    payload: list[dict[str, Any]] = []
    for row in rows[1:]:
        payload.append(normalize_import_row(dict(zip(headers, row))))
    return payload


def normalize_import_row(row: dict[str, Any]) -> dict[str, Any]:
    aliases = {
        "type": "import_type",
        "location_type": "import_type",
        "zip": "zip_code",
        "zip_code": "zip_code",
    }
    clean: dict[str, Any] = {}
    for key, value in row.items():
        normalized = aliases.get(str(key).strip().lower().replace(" ", "_"), str(key).strip().lower().replace(" ", "_"))
        clean[normalized] = value if value is not None else ""
    clean.setdefault("status", "published")
    return clean


def build_export_rows(countries: list[Country], states: list[State], cities: list[City], columns: list[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for country in countries:
        item = {
            "name": country.name,
            "slug": country.slug or "",
            "import_type": "country",
            "order": country.order,
            "abbreviation": country.abbreviation or country.code or "",
            "status": country.status,
            "country": "",
            "state": "",
            "nationality": country.nationality or "",
        }
        rows.append({column: item.get(column, "") for column in columns})
    for state in states:
        item = {
            "name": state.name,
            "slug": state.slug or "",
            "import_type": "state",
            "order": state.order,
            "abbreviation": state.abbreviation or "",
            "status": state.status,
            "country": state.country.name if state.country else "",
            "state": "",
            "nationality": "",
        }
        rows.append({column: item.get(column, "") for column in columns})
    for city in cities:
        item = {
            "name": city.name,
            "slug": city.slug or "",
            "import_type": "city",
            "order": city.order,
            "abbreviation": "",
            "status": city.status,
            "country": city.country.name if city.country else "",
            "state": city.state.name if city.state else "",
            "nationality": "",
        }
        rows.append({column: item.get(column, "") for column in columns})
    return rows


def export_csv(rows: list[dict[str, Any]], columns: list[str]) -> str:
    stream = io.StringIO()
    writer = csv.DictWriter(stream, fieldnames=columns)
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue()


def example_rows() -> list[dict[str, Any]]:
    return [
        {"name": "United States of America", "slug": "", "import_type": "country", "order": 0, "abbreviation": "", "status": "published", "country": "", "state": "", "nationality": "Americans"},
        {"name": "Texas", "slug": "", "import_type": "state", "order": 0, "abbreviation": "TX", "status": "published", "country": "United States of America", "state": "", "nationality": ""},
        {"name": "Washington", "slug": "", "import_type": "state", "order": 0, "abbreviation": "WA", "status": "published", "country": "United States of America", "state": "", "nationality": ""},
        {"name": "Houston", "slug": "houston", "import_type": "city", "order": 0, "abbreviation": "", "status": "published", "country": "United States of America", "state": "Texas", "nationality": ""},
        {"name": "San Antonio", "slug": "san-antonio", "import_type": "city", "order": 0, "abbreviation": "", "status": "published", "country": "United States of America", "state": "Texas", "nationality": ""},
    ]


def _guess_nationality(name: str) -> str:
    parts = [part for part in name.split(" ") if part]
    if len(parts) > 2:
        return "".join(part[0] for part in parts[:2]).upper()
    return name[:2].upper()
