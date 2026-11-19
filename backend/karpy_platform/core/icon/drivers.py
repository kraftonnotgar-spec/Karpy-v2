from __future__ import annotations

import html
import re
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from app.config import settings
from karpy_platform.core.icon.exceptions import SvgNotFoundError


class IconDriver(ABC):
    def __init__(self) -> None:
        self.config: dict[str, Any] = {}
        self.icon_path: Path | None = None

    def set_config(self, config: dict[str, Any]) -> "IconDriver":
        self.config = config
        return self

    def get_config(self) -> dict[str, Any]:
        return self.config

    def set_icon_path(self, path: str | Path) -> "IconDriver":
        self.icon_path = Path(path)
        return self

    @abstractmethod
    def all(self) -> dict[str, dict[str, str]]:
        raise NotImplementedError

    @abstractmethod
    def render(self, name: str, attributes: dict[str, Any] | None = None) -> str:
        raise NotImplementedError

    @abstractmethod
    def has(self, name: str) -> bool:
        raise NotImplementedError

    def parse_attributes_to_html(self, attributes: dict[str, Any] | None = None) -> str:
        formatted = self.format_attributes(attributes or {})
        output = []
        for key, value in formatted.items():
            if value is None or value is False:
                continue
            if value is True:
                output.append(str(key))
                continue
            output.append(f'{key}="{html.escape(str(value), quote=True)}"')
        return " ".join(output)

    def format_attributes(self, attributes: dict[str, Any]) -> dict[str, Any]:
        default_attributes = self.config.get("attributes", {})
        attributes = {**default_attributes, **attributes}
        attributes["class"] = self.merge_class_name_attribute(str(attributes.get("class", "")))
        return attributes

    def merge_class_name_attribute(self, class_name: str = "") -> str:
        return " ".join(part for part in [self.config.get("className", ""), class_name] if part).strip()


class SvgDriver(IconDriver):
    def __init__(self) -> None:
        super().__init__()
        self.icons: dict[str, dict[str, str]] | None = None
        self.cached_contents: dict[str, str] = {}
        self.search_paths = [
            settings.PLATFORM_DIR / "core" / "icon" / "resources" / "svg",
            settings.BASE_DIR / "botble cms" / "platform" / "core" / "icon" / "resources" / "svg",
        ]
        self.set_icon_path(self.search_paths[0])

    def all(self) -> dict[str, dict[str, str]]:
        if self.icons is None:
            self.icons = self.discover_icons()
        return self.icons

    def render(self, name: str, attributes: dict[str, Any] | None = None) -> str:
        normalized_name = self.normalize_full_name(name)
        if not self.has(normalized_name):
            if settings.DEBUG:
                raise SvgNotFoundError.missing(name)
            return ""

        contents = self.get_contents(normalized_name)
        contents = re.sub(r"^\s*<\?xml.+?\?>", "", contents, flags=re.DOTALL).strip()
        contents = re.sub(r"<!--.*?-->", "", contents, flags=re.DOTALL).strip()
        attributes_html = self.parse_attributes_to_html(attributes)
        return re.sub(r"<svg\b", f"<svg {attributes_html}".rstrip(), contents, count=1)

    def has(self, name: str) -> bool:
        return self.discover_icon(name)

    def search(self, query: str = "", limit: int = 50, offset: int = 0) -> list[dict[str, str]]:
        icons = list(self.all().values())
        if query:
            query = query.lower()
            icons = [icon for icon in icons if query in icon["name"].lower() or query in icon["basename"].lower()]
        icons.sort(key=lambda icon: icon["basename"])
        return icons[offset : offset + limit]

    def count(self, query: str = "") -> int:
        if not query:
            return len(self.all())
        query = query.lower()
        return sum(1 for icon in self.all().values() if query in icon["name"].lower() or query in icon["basename"].lower())

    def get_contents(self, name: str) -> str:
        normalized_name = self.normalize_full_name(name)
        if normalized_name not in self.cached_contents:
            icon = self.all()[normalized_name]
            self.cached_contents[normalized_name] = Path(icon["path"]).read_text(encoding="utf-8")
        return self.cached_contents[normalized_name]

    def discover_icons(self) -> dict[str, dict[str, str]]:
        icons: dict[str, dict[str, str]] = {}
        for path in self.search_paths:
            if not path.is_dir():
                continue
            for file in path.glob("*.svg"):
                basename = file.stem
                name = f"ti ti-{basename}"
                icons[name] = {"name": name, "basename": basename, "path": str(file)}
        return icons

    def discover_icon(self, name: str) -> bool:
        normalized_name = self.normalize_full_name(name)
        icons = self.all()
        if normalized_name in icons:
            return True

        basename = self.normalize_basename(normalized_name)
        for path in self.search_paths:
            file = path / f"{basename}.svg"
            if file.exists():
                icons[normalized_name] = {"name": normalized_name, "basename": basename, "path": str(file)}
                return True
        return False

    @staticmethod
    def normalize_full_name(name: str) -> str:
        name = name.strip()
        return name if name.startswith("ti ti-") else f"ti ti-{name}"

    @staticmethod
    def normalize_basename(name: str) -> str:
        return name.replace("ti ti-", "", 1).strip()
