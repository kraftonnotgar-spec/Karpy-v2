from __future__ import annotations

import re
from html import escape
from typing import Any
from urllib.parse import urlparse

from sqlalchemy.ext.asyncio import AsyncSession

from karpy_platform.core.base.hooks import hooks
from karpy_platform.core.setting.registry import SettingField, SettingSection, setting_panel_registry
from karpy_platform.core.setting.store import setting_store
from karpy_platform.packages.optimize.constants import (
    OPTIMIZE_FILTER_HTML,
    OPTIMIZE_FILTER_SETTINGS,
    OPTIMIZE_SETTING_KEYS,
)


DEFAULT_OPTIMIZE_SETTINGS = {
    "optimize_page_speed_enable": "1",
    "optimize_collapse_white_space": "1",
    "optimize_elide_attributes": "1",
    "optimize_inline_css": "1",
    "optimize_insert_dns_prefetch": "1",
    "optimize_remove_comments": "1",
    "optimize_remove_quotes": "1",
    "optimize_defer_javascript": "0",
}

OPTIMIZE_FILTERS = [
    {
        "key": "optimize_collapse_white_space",
        "title": "Collapse white space",
        "description": "This filter reduces bytes transmitted in an HTML file by removing unnecessary whitespace.",
    },
    {
        "key": "optimize_elide_attributes",
        "title": "Elide attributes",
        "description": "This filter reduces the transfer size of HTML files by removing attributes from tags when the specified value is equal to the default value for that attribute. This can save a modest number of bytes, and may make the document more compressible by canonicalizing the affected tags.",
    },
    {
        "key": "optimize_inline_css",
        "title": "Inline CSS",
        "description": "This filter transforms the inline \"style\" attribute of tags into classes by moving the CSS to the header.",
    },
    {
        "key": "optimize_insert_dns_prefetch",
        "title": "Insert DNS prefetch",
        "description": "This filter injects tags in the HEAD to enable the browser to do DNS prefetching.",
    },
    {
        "key": "optimize_remove_comments",
        "title": "Remove comments",
        "description": "This filter eliminates HTML, JS and CSS comments. The filter reduces the transfer size of HTML files by removing the comments. Depending on the HTML file, this filter can significantly reduce the number of bytes transmitted on the network.",
    },
    {
        "key": "optimize_remove_quotes",
        "title": "Remove quotes",
        "description": "This filter eliminates unnecessary quotation marks from HTML attributes. While required by the various HTML specifications, browsers permit their omission when the value of an attribute is composed of a certain subset of characters (alphanumerics and some punctuation characters).",
    },
    {
        "key": "optimize_defer_javascript",
        "title": "Defer javascript",
        "description": "Defers the execution of javascript in the HTML. If necessary cancel deferring in some script, use data-pagespeed-no-defer as script attribute to cancel deferring.",
    },
]

SKIP_SUFFIXES = {
    ".xml",
    ".less",
    ".pdf",
    ".doc",
    ".txt",
    ".ico",
    ".rss",
    ".zip",
    ".mp3",
    ".rar",
    ".exe",
    ".wmv",
    ".avi",
    ".ppt",
    ".mpg",
    ".mpeg",
    ".tif",
    ".wav",
    ".mov",
    ".psd",
    ".ai",
    ".xls",
    ".mp4",
    ".m4a",
    ".swf",
    ".dat",
    ".dmg",
    ".iso",
    ".flv",
    ".m4v",
    ".torrent",
}


class OptimizeService:
    """Python port of Botble's page-speed optimizer helper and middleware operations."""

    def __init__(self) -> None:
        self._booted = False
        self._runtime_enabled = True

    def boot(self) -> None:
        if self._booted:
            return
        setting_panel_registry.register_section(
            SettingSection(
                id="optimize",
                title="Optimize",
                description="Page speed switches for public HTML responses.",
                icon="gauge",
                route="/admin/settings/optimize",
                priority=140,
                permission="optimize.settings",
                group="settings.common",
                source="package:optimize",
                fields=[
                    SettingField("optimize_page_speed_enable", "Enable optimize page speed?", type="switch", default=DEFAULT_OPTIMIZE_SETTINGS["optimize_page_speed_enable"]),
                    *[
                        SettingField(item["key"], item["title"], type="switch", default=DEFAULT_OPTIMIZE_SETTINGS[item["key"]], description=item["description"])
                        for item in OPTIMIZE_FILTERS
                    ],
                ],
            )
        )
        self._booted = True

    def enable(self) -> "OptimizeService":
        self._runtime_enabled = True
        return self

    def disable(self) -> "OptimizeService":
        self._runtime_enabled = False
        return self

    async def settings(self, db: AsyncSession) -> dict[str, Any]:
        values = await setting_store.all(db, flat=True)
        settings = {key: values.get(key, default) for key, default in DEFAULT_OPTIMIZE_SETTINGS.items()}
        return await hooks.apply_filters_async(OPTIMIZE_FILTER_SETTINGS, settings)

    async def update_settings(self, db: AsyncSession, values: dict[str, Any]) -> dict[str, Any]:
        errors = self.validate_settings(values)
        if errors:
            raise ValueError(errors)

        clean_values = {
            key: self._on_off(values[key])
            for key in OPTIMIZE_SETTING_KEYS
            if key in values
        }
        await setting_store.set(db, clean_values)
        await setting_store.save(db)
        return await self.settings(db)

    def validate_settings(self, values: dict[str, Any]) -> dict[str, str]:
        allowed = {"1", "0", "true", "false", "yes", "no", "on", "off", ""}
        errors: dict[str, str] = {}
        for key in OPTIMIZE_SETTING_KEYS:
            if key not in values:
                continue
            value = values[key]
            if isinstance(value, bool) or (isinstance(value, int) and value in {0, 1}):
                continue
            if str(value).strip().lower() not in allowed:
                errors[key] = "Must be enabled or disabled."
        return errors

    async def status(self, db: AsyncSession) -> dict[str, Any]:
        settings = await self.settings(db)
        return {
            "enabled": self._truthy(settings.get("optimize_page_speed_enable")),
            "runtimeEnabled": self._runtime_enabled,
            "filters": [
                {**item, "enabled": self._truthy(settings.get(item["key"]))}
                for item in OPTIMIZE_FILTERS
            ],
            "skipPrefixes": ["/api", "/admin", "/media", "/docs", "/redoc", "/openapi.json", "/_debugbar"],
            "skipSuffixes": sorted(SKIP_SUFFIXES),
        }

    async def is_enabled(self, db: AsyncSession, path: str = "") -> bool:
        if not self._runtime_enabled or self.should_skip_path(path):
            return False
        settings = await self.settings(db)
        return self._truthy(settings.get("optimize_page_speed_enable"))

    async def optimize_html(self, html: str, db: AsyncSession | None = None, settings: dict[str, Any] | None = None) -> str:
        if settings is None:
            if db is None:
                settings = DEFAULT_OPTIMIZE_SETTINGS
            else:
                settings = await self.settings(db)

        if not self._truthy(settings.get("optimize_page_speed_enable")):
            return html

        result = html
        if self._truthy(settings.get("optimize_elide_attributes")):
            result = self.elide_attributes(result)
        if self._truthy(settings.get("optimize_inline_css")):
            result = self.inline_css(result)
        if self._truthy(settings.get("optimize_insert_dns_prefetch")):
            result = self.insert_dns_prefetch(result)
        if self._truthy(settings.get("optimize_collapse_white_space")):
            result = self.collapse_whitespace(result)
        if self._truthy(settings.get("optimize_remove_comments")):
            result = self.remove_comments(result)
        if self._truthy(settings.get("optimize_remove_quotes")):
            result = self.remove_quotes(result)
        if self._truthy(settings.get("optimize_defer_javascript")):
            result = self.defer_javascript(result)

        return await hooks.apply_filters_async(OPTIMIZE_FILTER_HTML, result, html, settings)

    def should_skip_path(self, path: str) -> bool:
        lower = (path or "").lower()
        if lower.startswith(("/api", "/admin", "/media", "/docs", "/redoc", "/openapi.json", "/_debugbar")):
            return True
        return any(lower.endswith(suffix) for suffix in SKIP_SUFFIXES)

    def collapse_whitespace(self, html: str) -> str:
        protected: list[str] = []
        result = html

        def hold(match: re.Match) -> str:
            protected.append(match.group(0))
            return f"@@KARPY_OPTIMIZE_PRE_{len(protected) - 1}@@"

        for tag in ("pre", "textarea", "script", "style"):
            result = re.sub(fr"<{tag}\b[^>]*>.*?</{tag}>", hold, result, flags=re.IGNORECASE | re.DOTALL)
        result = re.sub(r"\r|\n|\t", "", result)
        result = re.sub(r" +", " ", result)
        result = re.sub(r"> +<", "><", result)
        for index, block in enumerate(protected):
            result = result.replace(f"@@KARPY_OPTIMIZE_PRE_{index}@@", block)
        return result

    def remove_comments(self, html: str) -> str:
        return re.sub(r"<!--(?!\[if|\s*<!|\s*\])[\s\S]*?-->", "", html)

    def remove_quotes(self, html: str) -> str:
        result = re.sub(r"<(area|base|br|col|embed|hr|img|input|link|meta|param|source|track|wbr)([^>]*)/>", r"<\1\2>", html, flags=re.IGNORECASE)
        attributes = "src|width|height|name|charset|align|border|crossorigin|type"
        return re.sub(rf' ({attributes})="([^\s"\'=<>`]+)"', r" \1=\2", result, flags=re.IGNORECASE)

    def defer_javascript(self, html: str) -> str:
        def repl(match: re.Match) -> str:
            tag = match.group(0)
            lower = tag.lower()
            if " defer" in lower or "data-pagespeed-no-defer" in lower or "src=" not in lower:
                return tag
            return tag[:-1] + " defer>"

        return re.sub(r"<script\b[^>]*>", repl, html, flags=re.IGNORECASE)

    def elide_attributes(self, html: str) -> str:
        result = re.sub(r' method=("get"|get)', "", html, flags=re.IGNORECASE)
        result = re.sub(r" disabled=([^ >]+)", " disabled", result, flags=re.IGNORECASE)
        result = re.sub(r" selected=([^ >]+)", " selected", result, flags=re.IGNORECASE)
        return result

    def inline_css(self, html: str) -> str:
        styles: list[str] = []

        def replace_style(match: re.Match) -> str:
            class_name = f"page_speed_{len(styles) + 1}"
            styles.append(f".{class_name}{{{match.group(1)}}}")
            return f'class="{class_name}"'

        result = re.sub(r'style="([^"]+)"', replace_style, html)
        if not styles:
            return result
        result = self._merge_duplicate_class_attrs(result)
        block = "<style>" + " ".join(styles) + "</style>"
        if re.search(r"</head>", result, flags=re.IGNORECASE):
            return re.sub(r"</head>", block + "\n</head>", result, count=1, flags=re.IGNORECASE)
        return block + result

    def _merge_duplicate_class_attrs(self, html: str) -> str:
        def fix_tag(match: re.Match) -> str:
            tag = match.group(0)
            classes = re.findall(r'class="([^"]*)"', tag)
            if len(classes) < 2:
                return tag
            merged = " ".join(item for item in classes if item).strip()
            tag = re.sub(r'\sclass="[^"]*"', "", tag)
            return tag[:-1] + f' class="{merged}">'

        return re.sub(r"<[^>]+>", fix_tag, html)

    def insert_dns_prefetch(self, html: str) -> str:
        hosts = []
        for match in re.finditer(r"\bhttps?://[^\s()<>\"']+", html):
            host = urlparse(match.group(0)).hostname
            if host and host not in hosts:
                hosts.append(host)
        if not hosts:
            return html
        links = "\n".join(f'<link rel="dns-prefetch" href="//{escape(host)}">' for host in hosts)
        if re.search(r"<head>", html, flags=re.IGNORECASE):
            return re.sub(r"<head>", "<head>\n" + links, html, count=1, flags=re.IGNORECASE)
        return links + "\n" + html

    def _truthy(self, value: Any) -> bool:
        return str(value).strip().lower() in {"1", "true", "yes", "on"}

    def _on_off(self, value: Any) -> str:
        return "1" if self._truthy(value) else "0"


optimize_service = OptimizeService()


def boot_optimize_package() -> None:
    optimize_service.boot()
