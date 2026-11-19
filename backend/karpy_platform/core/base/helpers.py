"""
KARPy CMS — Helpers (utility functions used across the platform).

Like Botble's helpers.php — scan folders, read JSON, file operations.
"""

import json
import os
import re
import html
from pathlib import Path
from typing import Any
from app.config import settings


def scan_folder(directory: str | Path) -> list[str]:
    """Scan a directory and return a list of subdirectory names.
    
    This is the Python equivalent of Botble's BaseHelper::scanFolder().
    Used by the Plugin Manager to discover installed plugins.
    """
    directory = Path(directory)
    if not directory.is_dir():
        return []

    return [
        entry.name
        for entry in directory.iterdir()
        if entry.is_dir() and not entry.name.startswith((".", "__"))
    ]


def clean(value: Any) -> str:
    """Strip HTML/script content from small labels and notices."""
    if value is None:
        return ""

    text = html.unescape(str(value))
    text = re.sub(r"<script\b[^<]*(?:(?!</script>)<[^<]*)*</script>", "", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    return text.strip()


def slugify(value: str, fallback: str = "item") -> str:
    """Create URL-safe slugs like Botble's HasSlug helper."""
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", clean(value).lower()).strip("-")
    return slug or fallback


def platform_path(*parts: str) -> Path:
    """Return a path inside karpy_platform."""
    return settings.PLATFORM_DIR.joinpath(*parts)


def core_path(module: str = "", sub_path: str = "") -> Path:
    """Return a path inside karpy_platform/core."""
    path = settings.PLATFORM_DIR / "core"
    if module:
        path = path / module
    if sub_path:
        path = path / sub_path
    return path


def package_path(package_name: str = "", sub_path: str = "") -> Path:
    """Return a path inside karpy_platform/packages."""
    path = settings.PLATFORM_DIR / "packages"
    if package_name:
        path = path / package_name
    if sub_path:
        path = path / sub_path
    return path


def get_admin_prefix() -> str:
    """Return the admin route prefix."""
    return settings.ADMIN_DIR.strip("/") or "admin"


def get_file_data(filepath: str | Path) -> dict[str, Any]:
    """Read and parse a JSON file (like plugin.json or theme.json).
    
    Returns empty dict if file doesn't exist or is invalid.
    """
    filepath = Path(filepath)
    if not filepath.exists() or not filepath.is_file():
        return {}

    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {}


def write_file_data(filepath: str | Path, data: dict) -> bool:
    """Write data to a JSON file."""
    filepath = Path(filepath)
    try:
        filepath.parent.mkdir(parents=True, exist_ok=True)
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return True
    except IOError:
        return False


def plugin_path(plugin_name: str = "", sub_path: str = "") -> Path:
    """Get the absolute path to a plugin directory.
    
    Examples:
        plugin_path()                     -> /platform/plugins/
        plugin_path("wedding")            -> /platform/plugins/wedding/
        plugin_path("wedding", "models")  -> /platform/plugins/wedding/models/
    """
    base = settings.PLUGINS_DIR
    if plugin_name:
        base = base / plugin_name
    if sub_path:
        base = base / sub_path
    return base


def theme_path(theme_name: str = "", sub_path: str = "") -> Path:
    """Get the absolute path to a theme directory."""
    base = settings.THEMES_DIR
    if theme_name:
        base = base / theme_name
    if sub_path:
        base = base / sub_path
    return base
