from __future__ import annotations

from dataclasses import dataclass, field
from html import escape
from pathlib import Path
from typing import Any, Callable


@dataclass
class AssetItem:
    name: str
    source: str
    dependencies: list[str] = field(default_factory=list)
    attributes: dict[str, Any] = field(default_factory=dict)


class AssetContainer:
    """Botble-style CSS/JS container with dependency ordering."""

    def __init__(self, name: str, base_path: str = "") -> None:
        self.name = name
        self.base_path = base_path.strip("/")
        self.assets: dict[str, dict[str, AssetItem]] = {"style": {}, "script": {}}
        self._use_path = False

    def add(
        self,
        name: str,
        source: str | list[str],
        dependencies: list[str] | None = None,
        attributes: dict[str, Any] | None = None,
        version: str | None = None,
    ) -> "AssetContainer":
        if isinstance(source, list):
            for item in source:
                self.add(f"{name}-{abs(hash(item))}", item, dependencies, attributes, version)
            return self
        extension = Path(source.split("?", 1)[0]).suffix.lower()
        if version:
            source = f"{source}?v={version}"
        return self.style(name, source, dependencies, attributes) if extension == ".css" else self.script(name, source, dependencies, attributes)

    def add_using_path(
        self,
        name: str,
        source: str | list[str],
        dependencies: list[str] | None = None,
        attributes: dict[str, Any] | None = None,
        version: str | None = None,
    ) -> "AssetContainer":
        self._use_path = True
        return self.add(name, source, dependencies, attributes, version)

    def style(
        self,
        name: str,
        source: str,
        dependencies: list[str] | None = None,
        attributes: dict[str, Any] | None = None,
    ) -> "AssetContainer":
        attributes = {"media": "all", **(attributes or {})}
        self._register("style", name, self._source(source), dependencies or [], attributes)
        return self

    def script(
        self,
        name: str,
        source: str,
        dependencies: list[str] | None = None,
        attributes: dict[str, Any] | None = None,
    ) -> "AssetContainer":
        self._register("script", name, self._source(source), dependencies or [], attributes or {})
        return self

    def write_script(
        self,
        name: str,
        source: str,
        dependencies: list[str] | None = None,
        attributes: dict[str, Any] | None = None,
    ) -> "AssetContainer":
        html = f"<script{self._attributes(attributes or {})}>{source}</script>"
        self._register("script", name, html, dependencies or [], {})
        return self

    def write_style(self, name: str, source: str, dependencies: list[str] | None = None) -> "AssetContainer":
        self._register("style", name, f"<style>{source}</style>", dependencies or [], {})
        return self

    def write_content(self, name: str, source: str, dependencies: list[str] | None = None) -> "AssetContainer":
        self._register("script", name, source, dependencies or [], {})
        return self

    def remove(self, *names: str) -> "AssetContainer":
        for name in names:
            self.assets["style"].pop(name, None)
            self.assets["script"].pop(name, None)
        return self

    def styles(self) -> str:
        return self._group("style")

    def scripts(self) -> str:
        return self._group("script")

    def get_assets(self, group: str) -> list[str]:
        return [self._asset_url(group, name) for name in self._arranged(self.assets.get(group, {}))]

    def all(self) -> dict[str, dict[str, dict[str, Any]]]:
        return {
            group: {name: item.__dict__ for name, item in assets.items()}
            for group, assets in self.assets.items()
        }

    def _register(
        self,
        group: str,
        name: str,
        source: str,
        dependencies: list[str],
        attributes: dict[str, Any],
    ) -> None:
        self.assets.setdefault(group, {})[name] = AssetItem(name, source, dependencies, attributes)

    def _source(self, source: str) -> str:
        if self._use_path and not source.startswith(("http://", "https://", "//", "/")):
            source = f"/{self.base_path}/{source.lstrip('/')}" if self.base_path else f"/{source.lstrip('/')}"
        self._use_path = False
        return source

    def _group(self, group: str) -> str:
        return "".join(self._asset(group, name) for name in self._arranged(self.assets.get(group, {})))

    def _asset(self, group: str, name: str) -> str:
        item = self.assets[group][name]
        if "<" in item.source:
            return item.source + "\n"
        source = self._asset_url(group, name)
        if group == "style":
            attributes = {"rel": "stylesheet", "type": "text/css", "href": source, **item.attributes}
            return f"<link{self._attributes(attributes)}>\n"
        attributes = {"src": source, **item.attributes}
        return f"<script{self._attributes(attributes)}></script>\n"

    def _asset_url(self, group: str, name: str) -> str:
        source = self.assets[group][name].source
        if source.startswith(("http://", "https://", "//", "/")) or "<" in source:
            return source
        return f"/{source.lstrip('/')}"

    def _arranged(self, assets: dict[str, AssetItem]) -> list[str]:
        pending = dict(assets)
        ordered: list[str] = []
        while pending:
            progressed = False
            for name, item in list(pending.items()):
                dependencies = [dep for dep in item.dependencies if dep in assets and dep != name]
                if all(dep in ordered for dep in dependencies):
                    ordered.append(name)
                    pending.pop(name)
                    progressed = True
            if not progressed:
                ordered.extend(pending)
                break
        return ordered

    def _attributes(self, attributes: dict[str, Any]) -> str:
        output = []
        for key, value in attributes.items():
            if value is False or value is None:
                continue
            if value is True:
                output.append(str(key))
            else:
                output.append(f'{key}="{escape(str(value), quote=True)}"')
        return (" " + " ".join(output)) if output else ""


class AssetManager:
    """Per-render asset manager similar to Botble's Theme::asset()."""

    def __init__(self, base_path: str = "") -> None:
        self.base_path = base_path.strip("/")
        self._containers: dict[str, AssetContainer] = {}
        self._cooks: dict[str, Callable[["AssetManager"], None]] = {}
        self._serves: set[str] = set()

    def container(self, name: str = "default") -> AssetContainer:
        if name not in self._containers:
            self._containers[name] = AssetContainer(name, self.base_path)
        return self._containers[name]

    def add_path(self, base_path: str) -> None:
        self.base_path = base_path.strip("/")
        for container in self._containers.values():
            container.base_path = self.base_path

    def cook(self, name: str, callback: Callable[["AssetManager"], None]) -> None:
        self._cooks[name] = callback

    def serve(self, name: str) -> "AssetManager":
        self._serves.add(name)
        return self

    def flush(self) -> None:
        for name in list(self._serves):
            callback = self._cooks.get(name)
            if callback:
                callback(self)

    def all(self) -> dict[str, Any]:
        return {name: container.all() for name, container in self._containers.items()}
