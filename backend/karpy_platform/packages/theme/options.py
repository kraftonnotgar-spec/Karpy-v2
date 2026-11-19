from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from karpy_platform.core.base.helpers import clean, get_file_data, slugify, theme_path
from karpy_platform.core.base.hooks import hooks
from karpy_platform.core.setting.store import setting_store
from karpy_platform.packages.theme.constants import THEME_ACTION_OPTIONS_RENDERING, THEME_ACTION_OPTIONS_UPDATED, THEME_FILTER_OPTIONS


@dataclass
class ThemeOptionField:
    id: str
    label: str
    type: str = "text"
    section_id: str = "general"
    default: Any = ""
    priority: int = 99
    helper: str = ""
    attributes: dict[str, Any] = field(default_factory=dict)
    choices: list[str] | dict[str, Any] | None = None
    clean_tags: bool = True

    def to_dict(self, value: Any = None) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "type": self.type,
            "sectionId": self.section_id,
            "default": self.default,
            "value": self.default if value is None else value,
            "priority": self.priority,
            "helper": self.helper,
            "attributes": self.attributes,
            "choices": self.choices,
            "cleanTags": self.clean_tags,
        }


@dataclass
class ThemeOptionSection:
    id: str
    title: str
    description: str = ""
    icon: str = "settings"
    priority: int = 99
    hidden: bool = False

    def to_dict(self, fields: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "icon": self.icon,
            "priority": self.priority,
            "hidden": self.hidden,
            "fields": fields or [],
        }


class ThemeOptionRegistry:
    """Botble-like theme option sections and per-theme setting storage."""

    def __init__(self) -> None:
        self.opt_name = "theme"
        self._sections: dict[str, ThemeOptionSection] = {}
        self._fields: dict[str, ThemeOptionField] = {}
        self._booted = False

    def boot(self) -> None:
        if self._booted:
            return
        self.set_section(ThemeOptionSection("general", "General", "Site identity and common frontend behavior.", "home", 10))
        self.set_section(ThemeOptionSection("page", "Page", "Default page rendering and public metadata.", "book-open", 20))
        self.set_section(ThemeOptionSection("breadcrumb", "Breadcrumb", "Breadcrumb visibility and separator.", "signpost", 30))
        self.set_section(ThemeOptionSection("logo", "Logo", "Logo, favicon, and brand media.", "image", 40))
        self.set_section(ThemeOptionSection("typography", "Typography", "Frontend font families and base type settings.", "type", 50))
        self.set_section(ThemeOptionSection("social-links", "Social Links", "Links displayed in your theme header or footer.", "share-2", 60))
        self.set_section(ThemeOptionSection("toast-notification", "Toast Notification", "Frontend toast notification behavior.", "bell", 70))
        self.set_section(ThemeOptionSection("social-sharing", "Social Sharing", "Social share button configuration.", "network", 80))
        self.set_section(ThemeOptionSection("custom-code", "Custom Code", "Header, body, and footer integrations.", "code", 90))
        for field in [
            ThemeOptionField("site_title", "Site title", section_id="general", default="KARPy", priority=10, attributes={"placeholder": "Site title"}),
            ThemeOptionField("show_site_name", "Show site name", type="select", section_id="general", default="0", choices={"0": "No", "1": "Yes"}, priority=20),
            ThemeOptionField("site_title_separator", "Site title separator", type="select", section_id="general", default="-", choices={"-": "- (dash)", "|": "| (pipe)"}, priority=30),
            ThemeOptionField("seo_title", "SEO title", section_id="general", priority=40, attributes={"placeholder": "SEO title"}),
            ThemeOptionField("seo_description", "SEO description", type="textarea", section_id="general", priority=50),
            ThemeOptionField("seo_index", "SEO index", type="radio", section_id="general", default="1", choices={"1": "Index", "0": "No Index"}, priority=60, helper="Choose whether search engines may show public pages in search results."),
            ThemeOptionField("seo_og_image", "Default Open Graph image", type="mediaImage", section_id="general", priority=70, helper="Recommended size: 1200x630px."),
            ThemeOptionField("term_and_privacy_policy_url", "Term and privacy policy URL", section_id="general", priority=80, attributes={"placeholder": "https://example.com/term-and-privacy-policy"}),
            ThemeOptionField("copyright", "Copyright", type="textarea", section_id="general", default="Copyright :year KARPy.", priority=90),
            ThemeOptionField("default_page_template", "Default page template", type="select", section_id="page", default="default", choices={"default": "Default template", "full-width": "Full width", "no-sidebar": "No sidebar"}, priority=10),
            ThemeOptionField("page_banner_image", "Default banner image (1920x170px)", type="mediaImage", section_id="page", priority=20),
            ThemeOptionField("theme_breadcrumb_enabled", "Enable breadcrumb?", type="radio", section_id="breadcrumb", default="1", choices={"1": "Yes", "0": "No"}, priority=10),
            ThemeOptionField("breadcrumb_separator", "Breadcrumb separator", section_id="breadcrumb", default="/", priority=20),
            ThemeOptionField("favicon", "Favicon", type="mediaImage", section_id="logo", priority=10),
            ThemeOptionField("favicon_type", "Favicon type", type="select", section_id="logo", default="image/x-icon", choices={"image/x-icon": "ICO", "image/png": "PNG", "image/svg+xml": "SVG", "image/gif": "GIF", "image/jpeg": "JPEG", "image/webp": "WebP"}, priority=20),
            ThemeOptionField("logo", "Logo", type="mediaImage", section_id="logo", priority=30),
            ThemeOptionField("logo_height", "Logo height", type="number", section_id="logo", default="48", priority=40),
            ThemeOptionField("primary_font", "Primary font", section_id="typography", default="Inter", priority=10),
            ThemeOptionField("body_font_size", "Body font size", type="number", section_id="typography", default="16", priority=20),
            ThemeOptionField("primary_color", "Primary color", type="color", section_id="typography", default="#206bc4", priority=30),
            ThemeOptionField("social_links", "Social links", type="repeater", section_id="social-links", default=[], priority=10, attributes={"fields": ["label", "url", "icon"]}),
            ThemeOptionField("toast_notification_enabled", "Enable toast notification?", type="select", section_id="toast-notification", default="1", choices={"1": "Yes", "0": "No"}, priority=10),
            ThemeOptionField("social_sharing", "Social sharing buttons", type="repeater", section_id="social-sharing", default=self.default_social_sharing(), priority=10, attributes={"fields": ["social", "icon", "background_color", "color"]}),
            ThemeOptionField("custom_header_js", "Header JavaScript", type="code", section_id="custom-code", clean_tags=False),
            ThemeOptionField("custom_body_html", "Body HTML", type="code", section_id="custom-code", clean_tags=False),
            ThemeOptionField("custom_footer_js", "Footer JavaScript", type="code", section_id="custom-code", clean_tags=False),
        ]:
            self.set_field(field)
        self._booted = True

    def set_section(self, section: ThemeOptionSection | dict[str, Any]) -> "ThemeOptionRegistry":
        if isinstance(section, dict):
            section = self._normalize_section(section)
        self._sections[section.id] = section
        return self

    def set_field(self, field: ThemeOptionField | dict[str, Any]) -> "ThemeOptionRegistry":
        if isinstance(field, dict):
            field = self._normalize_field(field)
        if not field.id:
            field.id = slugify(field.label, fallback="field")
        self._fields[field.id] = field
        return self

    def remove_section(self, section_id: str, fields: bool = False) -> "ThemeOptionRegistry":
        self._sections.pop(section_id, None)
        if fields:
            for key, field in list(self._fields.items()):
                if field.section_id == section_id:
                    self._fields.pop(key, None)
        return self

    def remove_field(self, field_id: str) -> "ThemeOptionRegistry":
        self._fields.pop(field_id, None)
        return self

    def option_key(self, key: str, theme: str, locale: str | None = None) -> str:
        suffix = f"-{locale.strip('-')}" if locale else ""
        return f"{self.opt_name}-{theme}{suffix}-{key}"

    async def get_option(self, db: AsyncSession, key: str, default: Any = "", theme: str = "default") -> Any:
        field = self._fields.get(key)
        default = field.default if default == "" and field and field.default not in ("", None) else default
        value = await setting_store.get(db, self.option_key(key, theme), None)
        if value is None:
            value = await setting_store.get(db, f"theme_options.{key}", default)
        if isinstance(default, (dict, list)) and isinstance(value, str):
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return default
        return default if value is None else value

    async def has_option(self, db: AsyncSession, key: str, theme: str = "default") -> bool:
        return await setting_store.has(db, self.option_key(key, theme))

    async def set_option(self, db: AsyncSession, key: str, value: Any, theme: str = "default") -> None:
        field = self._fields.get(key)
        if field and field.clean_tags:
            if isinstance(value, str):
                value = clean(value)
            elif isinstance(value, list):
                value = [clean(item) if isinstance(item, str) else item for item in value]
        if isinstance(value, (dict, list)):
            value = json.dumps(value, ensure_ascii=False)
        await setting_store.set(db, self.option_key(key, theme), value)

    async def set_options(self, db: AsyncSession, values: dict[str, Any], theme: str = "default") -> None:
        await self.prepare(theme)
        for key, value in values.items():
            await self.set_option(db, key, value, theme)
        await setting_store.save(db)
        await hooks.do_action_async(THEME_ACTION_OPTIONS_UPDATED, theme, values)

    async def payload(self, db: AsyncSession, theme: str = "default") -> dict[str, Any]:
        await self.prepare(theme)
        sections = []
        for section in sorted(self._sections.values(), key=lambda item: item.priority):
            fields = [
                field.to_dict(await self.get_option(db, field.id, field.default, theme))
                for field in sorted(self._fields.values(), key=lambda item: item.priority)
                if field.section_id == section.id
            ]
            sections.append(section.to_dict(fields))
        payload = {
            "theme": theme,
            "sections": sections,
            "values": {
                field.id: await self.get_option(db, field.id, field.default, theme)
                for field in self._fields.values()
            },
        }
        return await hooks.apply_filters_async(THEME_FILTER_OPTIONS, payload, db, theme)

    async def all_values(self, db: AsyncSession, theme: str = "default") -> dict[str, Any]:
        await self.prepare(theme)
        return {
            field.id: await self.get_option(db, field.id, field.default, theme)
            for field in self._fields.values()
        }

    async def prepare(self, theme: str = "default") -> None:
        self.boot()
        self.load_theme_manifest_options(theme)
        await hooks.do_action_async(THEME_ACTION_OPTIONS_RENDERING, self, theme)

    def load_theme_manifest_options(self, theme: str = "default") -> None:
        data = get_file_data(theme_path(theme, "theme.json"))
        options = data.get("theme_options") or data.get("themeOptions") or {}
        sections = options.get("sections", []) if isinstance(options, dict) else []
        fields = options.get("fields", []) if isinstance(options, dict) else []
        for section in sections:
            if isinstance(section, dict):
                self.set_section(section)
        for field_data in fields:
            if isinstance(field_data, dict):
                self.set_field(field_data)

    def default_social_sharing(self) -> list[dict[str, str]]:
        return [
            {"social": "facebook", "icon": "ti ti-brand-facebook"},
            {"social": "x", "icon": "ti ti-brand-x"},
            {"social": "linkedin", "icon": "ti ti-brand-linkedin"},
            {"social": "email", "icon": "ti ti-mail"},
        ]

    def _normalize_section(self, data: dict[str, Any]) -> ThemeOptionSection:
        section_id = str(data.get("id") or slugify(str(data.get("title") or "section"), fallback="section"))
        section = ThemeOptionSection(
            id=section_id,
            title=str(data.get("title") or data.get("name") or section_id),
            description=str(data.get("description") or data.get("desc") or ""),
            icon=str(data.get("icon") or "settings"),
            priority=int(data.get("priority") or 99),
            hidden=bool(data.get("hidden", False)),
        )
        for field_data in data.get("fields") or []:
            if isinstance(field_data, dict):
                field_data = {**field_data, "section_id": section.id}
                self.set_field(field_data)
        return section

    def _normalize_field(self, data: dict[str, Any]) -> ThemeOptionField:
        attributes = data.get("attributes") if isinstance(data.get("attributes"), dict) else {}
        option_attributes = attributes.get("options") if isinstance(attributes.get("options"), dict) else {}
        field_type = str(data.get("type") or "text")
        type_map = {
            "customSelect": "select",
            "customRadio": "radio",
            "customColor": "color",
            "googleFonts": "text",
            "helper": "html",
            "onOff": "switch",
        }
        choices = data.get("choices") or data.get("options") or attributes.get("list") or attributes.get("values")
        default = data.get("default", attributes.get("value", data.get("default_value", "")))
        return ThemeOptionField(
            id=str(data.get("id") or attributes.get("name") or ""),
            label=str(data.get("label") if data.get("label") is not False else ""),
            type=type_map.get(field_type, field_type),
            section_id=str(data.get("section_id") or data.get("sectionId") or "general"),
            default=default,
            priority=int(data.get("priority") or 99),
            helper=str(data.get("helper") or attributes.get("helper") or attributes.get("content") or ""),
            attributes={**option_attributes, **{key: value for key, value in attributes.items() if key not in {"options", "list", "values", "value"}}},
            choices=choices,
            clean_tags=bool(data.get("clean_tags", data.get("cleanTags", True))),
        )


theme_options = ThemeOptionRegistry()
