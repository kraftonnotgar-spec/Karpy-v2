from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

from karpy_platform.core.base.helpers import get_file_data as base_get_file_data
from karpy_platform.core.base.helpers import scan_folder as base_scan_folder
from karpy_platform.core.base.helpers import write_file_data as base_write_file_data


def format_time(timestamp: datetime | date | str | None, fmt: str = "%d %b %Y %H:%M") -> str:
    if timestamp is None:
        return ""
    if isinstance(timestamp, str):
        try:
            timestamp = datetime.fromisoformat(timestamp)
        except ValueError:
            return timestamp
    return timestamp.strftime(fmt)


def date_from_database(value: datetime | date | str | None, fmt: str = "%Y-%m-%d") -> str:
    return format_time(value, fmt)


def human_file_size(bytes_value: float | int, precision: int = 2) -> str:
    size = float(bytes_value or 0)
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size < 1024 or unit == "TB":
            if unit == "B":
                return f"{int(size)} {unit}"
            return f"{size:.{precision}f} {unit}"
        size /= 1024
    return "0 B"


def get_file_data(path: str | Path, to_array: bool = True) -> dict[str, Any] | str | None:
    path = Path(path)
    if to_array:
        return base_get_file_data(path)
    if not path.exists() or not path.is_file():
        return None
    return path.read_text(encoding="utf-8")


def json_encode_prettify(data: dict | list) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False)


def save_file_data(path: str | Path, data: dict | list | str | None, json_data: bool = True) -> bool:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if json_data:
        if not isinstance(data, dict):
            data = {"data": data}
        return base_write_file_data(path, data)
    path.write_text("" if data is None else str(data), encoding="utf-8")
    return True


def scan_folder(path: str | Path, ignore_files: list[str] | None = None) -> list[str]:
    ignore = set(ignore_files or [])
    return [item for item in base_scan_folder(path) if item not in ignore]
