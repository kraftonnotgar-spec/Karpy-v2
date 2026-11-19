from __future__ import annotations

import csv
import io
import json
import re
import zipfile
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from html import escape
from xml.etree import ElementTree as ET
from typing import Any

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from karpy_platform.core.base.dashboard_menu import DashboardMenuItem, dashboard_menu
from karpy_platform.packages.page.models import Page
from karpy_platform.packages.page.service import page_service

ExportHandler = Callable[[AsyncSession, dict[str, Any]], Awaitable[list[dict[str, Any]]]]
ImportHandler = Callable[[AsyncSession, list[dict[str, Any]], str | None], Awaitable[dict[str, Any]]]
ExamplesHandler = Callable[[AsyncSession], Awaitable[list[dict[str, Any]]]]
SchemaHandler = Callable[[AsyncSession], Awaitable[Any]]


class DataSyncImportValidationError(ValueError):
    """Raised when an uploaded import file is structurally invalid."""


@dataclass
class DataSyncColumn:
    key: str
    label: str
    rule: str = ""
    exportable: bool = True
    importable: bool = True
    required: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "rule": self.rule,
            "exportable": self.exportable,
            "importable": self.importable,
            "required": self.required,
        }


@dataclass
class DataSyncDataset:
    key: str
    title: str
    description: str = ""
    columns: list[DataSyncColumn] = field(default_factory=list)
    supports_import: bool = True
    supports_export: bool = True
    source: str = "core"
    icon: str = "package-import"
    export_description: str = ""
    import_description: str = ""
    default_chunk_size: int = 50
    export_handler: ExportHandler | None = field(default=None, repr=False, compare=False)
    import_handler: ImportHandler | None = field(default=None, repr=False, compare=False)
    examples_handler: ExamplesHandler | None = field(default=None, repr=False, compare=False)
    counters_handler: SchemaHandler | None = field(default=None, repr=False, compare=False)
    filters_handler: SchemaHandler | None = field(default=None, repr=False, compare=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "title": self.title,
            "description": self.description,
            "columns": [column.to_dict() for column in self.columns],
            "supportsImport": self.supports_import,
            "supportsExport": self.supports_export,
            "source": self.source,
            "icon": self.icon,
            "exportDescription": self.export_description or f"Export {self.title.lower()} to a CSV/Excel file.",
            "importDescription": self.import_description or f"Import {self.title.lower()} from a CSV/Excel file.",
            "defaultChunkSize": self.default_chunk_size,
        }

    @property
    def export_keys(self) -> list[str]:
        return [column.key for column in self.columns if column.exportable]

    @property
    def import_keys(self) -> list[str]:
        return [column.key for column in self.columns if column.importable]


class DataSynchronizeService:
    """Botble-style export/import registry for admin tools."""

    def __init__(self) -> None:
        self._booted = False
        self._datasets: dict[str, DataSyncDataset] = {}

    def boot(self) -> None:
        if self._booted:
            return
        dashboard_menu.default().register_item(
            DashboardMenuItem("data-synchronize", "Export/Import Data", "/admin/tools/data-synchronize", "package-import", 10, parent_id="tools", permissions=["tools.data-synchronize"])
        )
        self.register_dataset(
            DataSyncDataset(
                key="pages",
                title="Pages",
                description="Pages content with slug, URL, template, media image, and publication status.",
                columns=[
                    DataSyncColumn("name", "Name", "The Name field accepts a string value of up to 120 characters or may be left blank.", required=True),
                    DataSyncColumn("slug", "Slug", "The Slug field accepts a string value of up to 250 characters or may be left blank."),
                    DataSyncColumn("description", "Description", "The Description field accepts a string value of up to 400 characters or may be left blank."),
                    DataSyncColumn("content", "Content", "The Content field accepts a string value of up to 300,000 characters or may be left blank."),
                    DataSyncColumn("image", "Image", "The Image field accepts a string value or may be left blank."),
                    DataSyncColumn("template", "Template", "The Template field accepts a string value of up to 60 characters or may be left blank."),
                    DataSyncColumn("url", "URL", "The URL field is generated from the public slug and is exported for reference.", importable=False),
                    DataSyncColumn("status", "Status", "Status must be one of the following values: published, draft, pending."),
                ],
                export_description="Export pages to CSV/Excel file.",
                import_description="Import pages from a CSV/Excel file.",
                source="package:page",
            )
        )
        self._booted = True

    def register_dataset(self, dataset: DataSyncDataset) -> None:
        self._datasets[dataset.key] = dataset

    def datasets(self) -> list[dict[str, Any]]:
        return [dataset.to_dict() for dataset in sorted(self._datasets.values(), key=lambda item: item.title)]

    def get_dataset(self, key: str) -> DataSyncDataset | None:
        return self._datasets.get(key)

    async def export_schema(self, db: AsyncSession, key: str) -> dict[str, Any]:
        dataset = self._datasets.get(key)
        if not dataset:
            raise KeyError(key)
        return {
            "dataset": dataset.to_dict(),
            "counters": await self._counters(db, key),
            "filters": await self._filters(db, key),
            "columns": [column.to_dict() for column in dataset.columns if column.exportable],
        }

    async def import_schema(self, db: AsyncSession, key: str) -> dict[str, Any]:
        dataset = self._datasets.get(key)
        if not dataset:
            raise KeyError(key)
        examples = await self.examples(db, key)
        return {
            "dataset": dataset.to_dict(),
            "columns": [column.to_dict() for column in dataset.columns if column.importable],
            "rules": [
                {"column": column.label, "key": column.key, "rules": column.rule}
                for column in dataset.columns
                if column.importable and column.rule
            ],
            "examples": examples,
            "allowedExtensions": ["csv", "xlsx", "xls"],
            "defaultChunkSize": dataset.default_chunk_size,
        }

    async def export_dataset(
        self,
        db: AsyncSession,
        key: str,
        *,
        columns: list[str] | None = None,
        limit: int | None = None,
        status: str | None = None,
        template: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> list[dict[str, Any]]:
        dataset = self._datasets.get(key)
        if dataset and dataset.export_handler:
            return await dataset.export_handler(
                db,
                {
                    "columns": columns,
                    "limit": limit,
                    "status": status,
                    "template": template,
                    "start_date": start_date,
                    "end_date": end_date,
                },
            )
        if key != "pages":
            raise KeyError(key)
        statement = self._page_query(status=status, template=template, start_date=start_date, end_date=end_date).order_by(Page.created_at.asc())
        if limit:
            statement = statement.limit(limit)
        result = await db.execute(statement)
        rows = [self._page_row(page) for page in result.scalars().unique().all()]
        export_columns = columns or self._datasets[key].export_keys
        return [{column: row.get(column) for column in export_columns} for row in rows]

    async def import_dataset(self, db: AsyncSession, key: str, rows: list[dict[str, Any]], user_id: str | None = None) -> dict[str, Any]:
        dataset = self._datasets.get(key)
        if dataset and dataset.import_handler:
            return await dataset.import_handler(db, rows, user_id)
        if key != "pages":
            raise KeyError(key)
        created = 0
        updated = 0
        skipped = 0
        errors: list[dict[str, Any]] = []
        for index, row in enumerate(rows, start=1):
            try:
                payload = self._page_payload(row)
                row_errors = self._validate_page_payload(payload, index)
                if row_errors:
                    skipped += 1
                    errors.extend(row_errors)
                    continue
                page = None
                row_slug = str(row.get("slug") or "").strip()
                if row_slug:
                    page = await page_service.get_page(db, row_slug)
                if page:
                    await page_service.update_page(db, page, payload, user_id=user_id)
                    updated += 1
                else:
                    await page_service.create_page(db, payload, user_id=user_id)
                    created += 1
            except Exception as exception:
                skipped += 1
                errors.append({"row": index, "message": str(exception)})
        return {"created": created, "updated": updated, "skipped": skipped, "errors": errors}

    async def examples(self, db: AsyncSession, key: str) -> list[dict[str, Any]]:
        dataset = self._datasets.get(key)
        if dataset and dataset.examples_handler:
            return await dataset.examples_handler(db)
        if key != "pages":
            raise KeyError(key)
        pages = await page_service.list_pages(db, limit=3)
        if pages:
            return [
                {
                    "name": page.name,
                    "slug": page.slug,
                    "description": self._limit(page.description, 120),
                    "content": self._limit(page.content, 120),
                    "image": page.image or "",
                    "template": page.template or "default",
                    "status": page.status or "published",
                }
                for page in pages
            ]
        return [
            {
                "name": "Homepage",
                "slug": "homepage",
                "description": "Main landing page for the website.",
                "content": "<h2>Welcome</h2><p>Build your first page content here.</p>",
                "image": "",
                "template": "default",
                "status": "published",
            },
            {
                "name": "About Us",
                "slug": "about-us",
                "description": "Short introduction about your company.",
                "content": "<p>Tell visitors who you are and what you do.</p>",
                "image": "",
                "template": "default",
                "status": "published",
            },
            {
                "name": "Contact",
                "slug": "contact",
                "description": "Contact page description.",
                "content": "<p>Share your address, phone number, and contact form.</p>",
                "image": "",
                "template": "default",
                "status": "published",
            },
        ]

    def to_csv(self, dataset: DataSyncDataset, rows: list[dict[str, Any]], columns: list[str] | None = None) -> str:
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=columns or dataset.export_keys, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
        return output.getvalue()

    def to_xlsx(self, dataset: DataSyncDataset, rows: list[dict[str, Any]], columns: list[str] | None = None) -> bytes:
        keys = columns or dataset.export_keys
        sheet_rows = [keys] + [[row.get(key, "") for key in keys] for row in rows]
        sheet_data = []
        for row_index, row in enumerate(sheet_rows, start=1):
            cells = []
            for column_index, value in enumerate(row, start=1):
                ref = f"{self._excel_column(column_index)}{row_index}"
                cells.append(f'<c r="{ref}" t="inlineStr"><is><t>{escape("" if value is None else str(value))}</t></is></c>')
            sheet_data.append(f'<row r="{row_index}">{"".join(cells)}</row>')
        sheet_xml = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            f'<sheetData>{"".join(sheet_data)}</sheetData></worksheet>'
        )
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("[Content_Types].xml", self._xlsx_content_types())
            archive.writestr("_rels/.rels", self._xlsx_rels())
            archive.writestr("xl/workbook.xml", self._xlsx_workbook())
            archive.writestr("xl/_rels/workbook.xml.rels", self._xlsx_workbook_rels())
            archive.writestr("xl/worksheets/sheet1.xml", sheet_xml)
        return output.getvalue()

    def parse_rows(self, content: bytes, filename: str) -> list[dict[str, Any]]:
        return self.parse_import_file(content, filename)

    def parse_import_file(self, content: bytes, filename: str, dataset: DataSyncDataset | None = None) -> list[dict[str, Any]]:
        lower = filename.lower().strip()
        extension = lower.rsplit(".", 1)[-1] if "." in lower else ""
        allowed = {"csv", "xlsx", "xls"}
        if extension not in allowed:
            raise DataSyncImportValidationError("The import file must be a CSV or Excel file (.csv, .xlsx, .xls).")
        if not content:
            raise DataSyncImportValidationError("The import file is empty.")
        if len(content) > 20 * 1024 * 1024:
            raise DataSyncImportValidationError("The import file is too large. Please split it into smaller files.")
        if extension == "xlsx":
            rows = self._parse_xlsx_safe(content)
        elif extension == "xls" and content[:2] == b"PK":
            rows = self._parse_xlsx_safe(content)
        elif extension == "xls":
            if content[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
                raise DataSyncImportValidationError("Legacy .xls binary files are not supported yet. Please save the file as .xlsx or CSV and upload again.")
            rows = self._parse_csv_safe(content)
        else:
            rows = self._parse_csv_safe(content)
        self._validate_import_rows(rows, dataset)
        return rows

    def _parse_rows_legacy(self, content: bytes, filename: str) -> list[dict[str, Any]]:
        lower = filename.lower()
        if lower.endswith(".xlsx"):
            return self._parse_xlsx(content)
        text = content.decode("utf-8-sig")
        if lower.endswith(".json"):
            parsed = json.loads(text or "[]")
            if isinstance(parsed, dict):
                parsed = parsed.get("data") or parsed.get("rows") or []
            if not isinstance(parsed, list):
                raise ValueError("JSON import must be an array of rows.")
            return [dict(row) for row in parsed if isinstance(row, dict)]
        reader = csv.DictReader(io.StringIO(text))
        return [dict(row) for row in reader]

    def _parse_csv_safe(self, content: bytes) -> list[dict[str, Any]]:
        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError as exception:
            raise DataSyncImportValidationError("The CSV file must be encoded as UTF-8.") from exception
        if not text.strip():
            raise DataSyncImportValidationError("The import file is empty.")
        try:
            sample = text[:4096]
            delimiter = csv.Sniffer().sniff(sample, delimiters=",;\t").delimiter if any(mark in sample for mark in [",", ";", "\t"]) else ","
        except csv.Error:
            delimiter = ","
        try:
            reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
            headers = [str(header or "").strip() for header in (reader.fieldnames or [])]
            self._validate_headers(headers)
            rows = [{str(key or "").strip().lower(): value for key, value in row.items() if key is not None} for row in reader]
        except csv.Error as exception:
            raise DataSyncImportValidationError("The CSV file could not be read. Please check the delimiter and header row.") from exception
        return [row for row in rows if any(str(value or "").strip() for value in row.values())]

    def _parse_xlsx_safe(self, content: bytes) -> list[dict[str, Any]]:
        try:
            return self._parse_xlsx(content)
        except zipfile.BadZipFile as exception:
            raise DataSyncImportValidationError("The Excel file is not a valid .xlsx workbook.") from exception
        except KeyError as exception:
            raise DataSyncImportValidationError("The Excel file is missing the first worksheet.") from exception
        except ET.ParseError as exception:
            raise DataSyncImportValidationError("The Excel worksheet XML is damaged and cannot be imported.") from exception
        except Exception as exception:
            raise DataSyncImportValidationError("The Excel file could not be read. Please save it again as .xlsx or CSV.") from exception

    def _validate_headers(self, headers: list[str]) -> None:
        normalized = [header.strip().lower() for header in headers if header and header.strip()]
        if not normalized:
            raise DataSyncImportValidationError("The import file must include a header row.")
        duplicates = sorted({header for header in normalized if normalized.count(header) > 1})
        if duplicates:
            raise DataSyncImportValidationError(f"The import file has duplicated column(s): {', '.join(duplicates)}.")

    def _validate_import_rows(self, rows: list[dict[str, Any]], dataset: DataSyncDataset | None) -> None:
        if not rows:
            raise DataSyncImportValidationError("The import file does not contain any data rows.")
        if not dataset:
            return
        allowed = set(dataset.import_keys)
        required = {column.key for column in dataset.columns if column.importable and column.required}
        headers = {key.strip().lower() for key in rows[0].keys() if key and key.strip()}
        known_headers = headers & allowed
        if not known_headers:
            raise DataSyncImportValidationError(f"The import file columns do not match {dataset.title}. Please download the example file and use its headers.")
        missing_required = sorted(required - headers)
        if missing_required:
            labels = {column.key: column.label for column in dataset.columns}
            readable = ", ".join(labels.get(key, key) for key in missing_required)
            raise DataSyncImportValidationError(f"The import file is missing required column(s): {readable}.")

    async def _counters(self, db: AsyncSession, key: str) -> list[dict[str, Any]]:
        dataset = self._datasets.get(key)
        if dataset and dataset.counters_handler:
            return await dataset.counters_handler(db)
        if key != "pages":
            return []
        total = await db.scalar(select(func.count()).select_from(Page).where(Page.is_deleted == False))
        return [{"label": "Total Pages", "value": int(total or 0)}]

    async def _filters(self, db: AsyncSession, key: str) -> dict[str, Any]:
        dataset = self._datasets.get(key)
        if dataset and dataset.filters_handler:
            return await dataset.filters_handler(db)
        if key != "pages":
            return {}
        templates = await page_service.templates.all()
        return {
            "statuses": ["published", "draft", "pending"],
            "templates": [{"value": value, "label": label} for value, label in templates.items()],
        }

    def _page_row(self, page: Page) -> dict[str, Any]:
        return {
            "name": page.name,
            "slug": page.slug,
            "description": page.description,
            "content": page.content,
            "image": page.image,
            "template": page.template or "default",
            "url": page_service.page_url(page),
            "status": page.status,
        }

    def _page_payload(self, row: dict[str, Any]) -> dict[str, Any]:
        name = str(row.get("name") or row.get("Name") or "").strip()
        slug = str(row.get("slug") or row.get("Slug") or "").strip()
        status = str(row.get("status") or row.get("Status") or "published").strip().lower() or "published"
        return {
            "name": name,
            "slug": slug or self._slugify(name) or None,
            "status": status,
            "template": str(row.get("template") or row.get("Template") or "default").strip() or "default",
            "description": row.get("description") or row.get("Description") or None,
            "content": row.get("content") or row.get("Content") or "",
            "image": row.get("image") or row.get("Image") or None,
        }

    def _validate_page_payload(self, payload: dict[str, Any], row: int) -> list[dict[str, Any]]:
        errors: list[dict[str, Any]] = []
        if not payload["name"]:
            errors.append({"row": row, "column": "name", "message": "The Name field is required."})
        limits = {"name": 120, "slug": 250, "description": 400, "content": 300000, "template": 60}
        for key, maximum in limits.items():
            value = payload.get(key)
            if value is not None and len(str(value)) > maximum:
                errors.append({"row": row, "column": key, "message": f"The {key.replace('_', ' ').title()} field may not be greater than {maximum} characters."})
        if payload.get("status") not in {"published", "draft", "pending"}:
            errors.append({"row": row, "column": "status", "message": "Status must be one of: published, draft, pending."})
        return errors

    def _page_query(self, *, status: str | None, template: str | None, start_date: str | None, end_date: str | None):
        filters = [Page.is_deleted == False]
        if status:
            filters.append(Page.status == status)
        if template:
            filters.append(Page.template == template)
        if start_date:
            filters.append(func.date(Page.created_at) >= start_date)
        if end_date:
            filters.append(func.date(Page.created_at) <= end_date)
        return select(Page).where(and_(*filters))

    def _date(self, value: datetime | None) -> str | None:
        return value.isoformat() if value else None

    def _slugify(self, value: str) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
        return slug or value.strip().lower().replace(" ", "-")

    def _limit(self, value: str | None, length: int) -> str:
        if not value:
            return ""
        return value if len(value) <= length else f"{value[: length - 3]}..."

    def _excel_column(self, index: int) -> str:
        value = ""
        while index:
            index, remainder = divmod(index - 1, 26)
            value = chr(65 + remainder) + value
        return value

    def _xlsx_content_types(self) -> str:
        return (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            "</Types>"
        )

    def _xlsx_rels(self) -> str:
        return (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
            "</Relationships>"
        )

    def _xlsx_workbook(self) -> str:
        return (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<sheets><sheet name="Data" sheetId="1" r:id="rId1"/></sheets></workbook>'
        )

    def _xlsx_workbook_rels(self) -> str:
        return (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
            "</Relationships>"
        )

    def _parse_xlsx(self, content: bytes) -> list[dict[str, Any]]:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            shared_strings = self._xlsx_shared_strings(archive)
            sheet = ET.fromstring(archive.read("xl/worksheets/sheet1.xml"))
        ns = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
        rows: list[list[str]] = []
        for row in sheet.findall(".//x:sheetData/x:row", ns):
            values: list[str] = []
            for cell in row.findall("x:c", ns):
                cell_type = cell.attrib.get("t")
                if cell_type == "inlineStr":
                    values.append("".join(text.text or "" for text in cell.findall(".//x:t", ns)))
                elif cell_type == "s":
                    raw = cell.findtext("x:v", default="", namespaces=ns)
                    values.append(shared_strings[int(raw)] if raw.isdigit() and int(raw) < len(shared_strings) else "")
                else:
                    values.append(cell.findtext("x:v", default="", namespaces=ns))
            rows.append(values)
        if not rows:
            return []
        headers = [str(header).strip() for header in rows[0]]
        self._validate_headers(headers)
        return [dict(zip(headers, row)) for row in rows[1:] if any(str(value).strip() for value in row)]

    def _xlsx_shared_strings(self, archive: zipfile.ZipFile) -> list[str]:
        try:
            raw = archive.read("xl/sharedStrings.xml")
        except KeyError:
            return []
        root = ET.fromstring(raw)
        ns = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
        return ["".join(text.text or "" for text in item.findall(".//x:t", ns)) for item in root.findall("x:si", ns)]


data_synchronize_service = DataSynchronizeService()


def boot_data_synchronize_package() -> None:
    data_synchronize_service.boot()
