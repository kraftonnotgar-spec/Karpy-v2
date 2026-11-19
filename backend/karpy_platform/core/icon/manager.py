from __future__ import annotations

import html
from typing import Any

from karpy_platform.core.icon.drivers import IconDriver, SvgDriver


DEFAULT_ICON_CONFIG = {
    "className": "icon",
    "attributes": {},
}


class IconManager:
    def __init__(self) -> None:
        self.config = DEFAULT_ICON_CONFIG.copy()
        self._drivers: dict[str, IconDriver] = {}
        self.default_driver = "svg"

    def driver(self, name: str | None = None) -> IconDriver:
        name = name or self.default_driver
        if name not in self._drivers:
            if name != "svg":
                raise ValueError(f"Icon driver [{name}] is not supported.")
            self._drivers[name] = SvgDriver().set_config(self.config)
        return self._drivers[name]

    def all(self) -> dict[str, dict[str, str]]:
        return self.driver().all()

    def search(self, query: str = "", limit: int = 50, offset: int = 0) -> list[dict[str, str]]:
        driver = self.driver()
        if not isinstance(driver, SvgDriver):
            return list(driver.all().values())[offset : offset + limit]
        return driver.search(query=query, limit=limit, offset=offset)

    def count(self, query: str = "") -> int:
        driver = self.driver()
        if not isinstance(driver, SvgDriver):
            return len(driver.all())
        return driver.count(query=query)

    def has(self, name: str) -> bool:
        return self.driver().has(name)

    def render(self, name: str, attributes: dict[str, Any] | None = None) -> str:
        return self.driver().render(name, attributes or {})

    def component(self, name: str, size: str | None = None, attributes: dict[str, Any] | None = None) -> str:
        attributes = dict(attributes or {})
        classes = [attributes.pop("class", "")]

        if size:
            classes.insert(0, f"icon-{size}")

        if name.startswith("ti ti-") or self.has(name):
            full_name = SvgDriver.normalize_full_name(name)
            classes.append(f"svg-icon-{full_name.replace(' ', '-')}")
            return self.render(full_name, {**attributes, "class": " ".join(filter(None, classes))})

        classes.insert(0, name)
        class_attr = html.escape(" ".join(filter(None, classes)), quote=True)
        other_attrs = _attributes_to_html(attributes)
        return f'<i class="{class_attr}" {other_attrs}></i>'.replace(" ></i>", "></i>")

    def set_icon_path(self, path: str) -> "IconManager":
        self.driver().set_icon_path(path)
        return self


icon_manager = IconManager()


def _attributes_to_html(attributes: dict[str, Any]) -> str:
    output = []
    for key, value in attributes.items():
        if value is None or value is False:
            continue
        if value is True:
            output.append(str(key))
            continue
        output.append(f'{key}="{html.escape(str(value), quote=True)}"')
    return " ".join(output)
