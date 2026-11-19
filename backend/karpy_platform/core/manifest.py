from __future__ import annotations

import json
from pathlib import Path
from typing import Any


CORE_DIR = Path(__file__).resolve().parent
CORE_JSON = CORE_DIR / "core.json"
CORE_COMPOSER_JSON = CORE_DIR / "composer.json"


def read_core_json() -> dict[str, Any]:
    return _read_json(CORE_JSON)


def read_composer_json() -> dict[str, Any]:
    return _read_json(CORE_COMPOSER_JSON)


def core_modules() -> list[str]:
    return list(read_core_json().get("modules", []))


def core_providers() -> list[str]:
    return list(read_composer_json().get("providers", []))


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
