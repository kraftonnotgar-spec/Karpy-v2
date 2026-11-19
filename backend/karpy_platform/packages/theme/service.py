from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import HTTPException, status
from fastapi.responses import HTMLResponse
from jinja2 import ChoiceLoader, Environment, FileSystemLoader, TemplateNotFound, select_autoescape
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from karpy_platform.core.base.dashboard_menu import DashboardMenuItem, dashboard_menu
from karpy_platform.core.base.helpers import get_file_data, scan_folder, theme_path
from karpy_platform.core.base.hooks import hooks
from karpy_platform.core.setting.store import setting_store
from karpy_platform.packages.theme.assets import AssetManager
from karpy_platform.packages.theme.constants import (
    THEME_ACTION_ACTIVATED,
    THEME_ACTION_RENDERING_HOME,
    THEME_ACTION_RENDERING_SINGLE,
    THEME_FILTER_BODY_ATTRIBUTES,
    THEME_FILTER_FAVICON,
    THEME_FILTER_HTML_ATTRIBUTES,
    THEME_FILTER_LIST,
    THEME_FILTER_LOGO,
    THEME_FILTER_RENDERED_HTML,
    THEME_FILTER_SITE_TITLE,
    THEME_FILTER_TEMPLATE_CONTEXT,
    THEME_FRONT_BODY,
    THEME_FRONT_FOOTER,
    THEME_FRONT_HEADER,
)
from karpy_platform.packages.theme.options import theme_options
from karpy_platform.packages.theme.supports import format_date, render_social_sharing, social_links, social_sharing_buttons


@dataclass
class ThemeInfo:
    folder: str
    name: str
    version: str = "0.0.0"
    author: str = ""
    description: str = ""
    url: str = ""
    inherit: str | None = None
    required_plugins: list[str] = field(default_factory=list)
    presets: dict[str, Any] | list[Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self, active: bool = False, screenshot: str | None = None) -> dict[str, Any]:
        return {
            **self.raw,
            "folder": self.folder,
            "name": self.name,
            "version": self.version,
            "author": self.author,
            "description": self.description,
            "url": self.url,
            "inherit": self.inherit,
            "requiredPlugins": self.required_plugins,
            "presets": self.presets,
            "active": active,
            "screenshot": screenshot,
        }


class ThemeRenderer:
    """Per-request renderer for layouts, views, regions, options, and assets."""

    def __init__(self, service: "ThemeService", theme: str, inherit: str | None = None) -> None:
        self.service = service
        self.theme = theme
        self.inherit = inherit
        self.layout = "default"
        self.regions: dict[str, Any] = {}
        self.arguments: dict[str, Any] = {}
        self.body_attributes: dict[str, Any] = {}
        self.html_attributes: dict[str, Any] = {"lang": "en"}
        self.asset = AssetManager(f"themes/{theme}")
        self.env = self._environment()

    def uses(self, theme: str) -> "ThemeRenderer":
        self.theme = theme
        self.env = self._environment()
        return self

    def set_layout(self, layout: str) -> "ThemeRenderer":
        if layout:
            self.layout = layout
        return self

    def set(self, region: str, value: Any) -> "ThemeRenderer":
        if region != "content":
            self.regions[region] = value
        return self

    def append(self, region: str, value: str) -> "ThemeRenderer":
        self.regions[region] = str(self.regions.get(region, "")) + value
        return self

    def prepend(self, region: str, value: str) -> "ThemeRenderer":
        self.regions[region] = value + str(self.regions.get(region, ""))
        return self

    def place(self, region: str, default: str = "") -> str:
        return str(self.regions.get(region, default))

    async def scope(self, db: AsyncSession, view: str, args: dict[str, Any] | None = None, default: str | None = None) -> "ThemeRenderer":
        self.arguments = args or {}
        self.asset.container().add_using_path("theme-style", "css/theme.css")
        view_name = self._view_name(view)
        try:
            content = await self._render(db, view_name, self.arguments)
        except TemplateNotFound:
            if default:
                content = await self._render_fallback(db, default, self.arguments)
            else:
                raise HTTPException(status.HTTP_404_NOT_FOUND, f"Theme view not found: {view}")
        self.regions["content"] = content
        return self

    async def render(self, db: AsyncSession, status_code: int = 200) -> HTMLResponse:
        self.asset.flush()
        options = await theme_options.all_values(db, self.theme)
        title = await self.service.site_title(db, self.theme)
        favicon = await self.service.favicon(db, self.theme)
        header_html = await hooks.apply_filters_async(THEME_FRONT_HEADER, await self.service.custom_header_html(db, self.theme), self, db)
        try:
            from karpy_platform.core.setting.tracking import website_tracking

            header_html += await website_tracking.tracking_code(db)
        except Exception:
            pass
        body_html = await hooks.apply_filters_async(THEME_FRONT_BODY, await self.service.custom_body_html(db, self.theme), self, db)
        footer_html = await hooks.apply_filters_async(THEME_FRONT_FOOTER, await self.service.custom_footer_html(db, self.theme), self, db)
        menu_locations: dict[str, Any] = {}
        try:
            from karpy_platform.packages.menu.service import menu_service

            for location in (await menu_service.locations()).keys():
                menu_locations[location] = await menu_service.render_location(db, location)
        except Exception:
            menu_locations = {}
        context = {
            **self.arguments,
            "theme": self,
            "theme_name": self.theme,
            "theme_options": options,
            "site_title": title,
            "favicon": favicon,
            "content": self.regions.get("content", ""),
            "regions": self.regions,
            "header_html": header_html,
            "body_html": body_html,
            "footer_html": footer_html,
            "assets": self.asset,
            "styles": self.asset.container().styles() + self.asset.container("header").styles(),
            "scripts": self.asset.container().scripts() + self.asset.container("footer").scripts(),
            "body_attributes": self._attributes(await hooks.apply_filters_async(THEME_FILTER_BODY_ATTRIBUTES, self.body_attributes, self, db)),
            "html_attributes": self._attributes(await hooks.apply_filters_async(THEME_FILTER_HTML_ATTRIBUTES, self.html_attributes, self, db)),
            "social_links": [item.to_dict() for item in social_links(options.get("social_links"))],
            "menu_locations": menu_locations,
            "format_date": format_date,
            "copyright": self.service.copyright(options.get("copyright")),
        }
        context = await hooks.apply_filters_async(THEME_FILTER_TEMPLATE_CONTEXT, context, self, db)
        html = await self._render(db, f"layouts/{self.layout}.html", context)
        html = await hooks.apply_filters_async(THEME_FILTER_RENDERED_HTML, html, self, db)
        return HTMLResponse(html, status_code=status_code, headers={"CMS-Version": settings.APP_VERSION})

    async def social_sharing(self, db: AsyncSession, url: str, title: str, thumbnail: str | None = None) -> str:
        options = await theme_options.all_values(db, self.theme)
        return render_social_sharing(social_sharing_buttons(options.get("social_sharing"), url, title, thumbnail))

    def content(self) -> str:
        return str(self.regions.get("content", ""))

    def add_body_attributes(self, values: dict[str, Any]) -> "ThemeRenderer":
        self.body_attributes.update(values)
        return self

    def add_html_attributes(self, values: dict[str, Any]) -> "ThemeRenderer":
        self.html_attributes.update(values)
        return self

    def asset_url(self, path: str) -> str:
        if path.startswith(("http://", "https://", "//", "/")):
            return path
        return f"/themes/{self.theme}/{path.lstrip('/')}"

    def _environment(self) -> Environment:
        paths = [theme_path(self.theme)]
        if self.inherit and self.inherit != self.theme:
            paths.append(theme_path(self.inherit))
        paths.append(self.service.package_path / "templates")
        return Environment(
            loader=ChoiceLoader([FileSystemLoader(str(path)) for path in paths if path.exists()]),
            autoescape=select_autoescape(["html", "xml"]),
            enable_async=True,
        )

    async def _render(self, db: AsyncSession, template: str, context: dict[str, Any]) -> str:
        template_obj = self.env.get_template(template)
        return await template_obj.render_async(**context)

    async def _render_fallback(self, db: AsyncSession, view: str, context: dict[str, Any]) -> str:
        fallback = "views/page.html" if view.endswith("themes.page") or view == "page" else self._view_name(view)
        return await self._render(db, fallback, context)

    def _view_name(self, view: str) -> str:
        view = view.replace("::", "/").replace(".", "/").strip("/")
        if not view.endswith(".html"):
            view = f"{view}.html"
        return view if view.startswith(("views/", "layouts/", "partials/")) else f"views/{view}"

    def _attributes(self, attributes: dict[str, Any]) -> str:
        output = []
        for key, value in attributes.items():
            if value is False or value is None:
                continue
            if value is True:
                output.append(str(key))
            else:
                output.append(f'{key}="{str(value)}"')
        return " ".join(output)


class ThemeService:
    """Botble package/theme port: discovery, activation, options, assets, and rendering."""

    def __init__(self) -> None:
        self._booted = False
        self._cache: dict[str, ThemeInfo] = {}
        self.package_path = Path(__file__).resolve().parent

    def boot(self) -> None:
        if self._booted:
            return
        theme_options.boot()
        settings.THEMES_DIR.mkdir(parents=True, exist_ok=True)
        self.public_themes_path.mkdir(parents=True, exist_ok=True)
        if self.exists("default"):
            self.publish_assets("default")
        dashboard_menu.default().register_item(
            DashboardMenuItem("themes", "Themes", "/admin/appearance/themes", "palette", 10, parent_id="appearance", permissions=["theme.index"])
        )
        dashboard_menu.default().register_item(
            DashboardMenuItem("theme-options", "Theme Options", "/admin/appearance/theme-options", "sliders", 15, parent_id="appearance", permissions=["theme.options"])
        )
        for item in [
            DashboardMenuItem("custom-css", "Custom CSS", "/admin/appearance/custom-css", "css", 50, parent_id="appearance", permissions=["theme.custom_css"]),
            DashboardMenuItem("custom-html", "Custom HTML", "/admin/appearance/custom-html", "html", 60, parent_id="appearance", permissions=["theme.custom_html"]),
            DashboardMenuItem("robots-txt", "Robots.txt Editor", "/admin/appearance/robots-txt", "file-text", 70, parent_id="appearance", permissions=["theme.robots"]),
        ]:
            dashboard_menu.default().register_item(item)
        self._booted = True

    @property
    def public_themes_path(self) -> Path:
        return settings.THEME_PUBLIC_DIR

    def installed_theme_names(self) -> list[str]:
        return scan_folder(settings.THEMES_DIR)

    def get_theme_info(self, theme: str) -> ThemeInfo | None:
        manifest = theme_path(theme, "theme.json")
        data = get_file_data(manifest)
        if not data:
            return None
        return ThemeInfo(
            folder=theme,
            name=data.get("name", theme.title()),
            version=data.get("version", "0.0.0"),
            author=data.get("author", ""),
            description=data.get("description", ""),
            url=data.get("url", ""),
            inherit=data.get("inherit"),
            required_plugins=data.get("required_plugins", data.get("requiredPlugins", [])) or [],
            presets=data.get("presets", {}),
            raw=data,
        )

    async def active_theme_name(self, db: AsyncSession) -> str:
        selected = await setting_store.get(db, "theme", "")
        if selected and self.exists(str(selected)):
            return str(selected)
        names = self.installed_theme_names()
        return names[0] if names else "default"

    async def list_themes(self, db: AsyncSession) -> list[dict[str, Any]]:
        active = await self.active_theme_name(db)
        themes = []
        for name in self.installed_theme_names():
            info = self.get_theme_info(name)
            if info:
                themes.append(info.to_dict(active=name == active, screenshot=self.screenshot_url(name)))
        return await hooks.apply_filters_async(THEME_FILTER_LIST, sorted(themes, key=lambda item: item["name"].lower()), db)

    def exists(self, theme: str | None) -> bool:
        return bool(theme and theme_path(theme).is_dir() and theme_path(theme, "theme.json").is_file())

    async def validate(self, theme: str) -> dict[str, Any]:
        if not theme_path(theme).is_dir():
            return {"error": True, "message": f"Theme '{theme}' does not exist"}
        if not theme_path(theme, "theme.json").is_file():
            return {"error": True, "message": "Missing theme.json file"}
        info = self.get_theme_info(theme)
        if info and info.inherit and not self.exists(info.inherit):
            return {"error": True, "message": f"Parent theme '{info.inherit}' was not found"}
        return {"error": False, "message": "Theme is valid"}

    async def activate(self, db: AsyncSession, theme: str) -> dict[str, Any]:
        validation = await self.validate(theme)
        if validation["error"]:
            return validation
        active = await self.active_theme_name(db)
        if active == theme and await setting_store.get(db, "theme", ""):
            return {"error": True, "message": f"Theme '{theme}' is already activated"}
        info = self.get_theme_info(theme)
        if info:
            from karpy_platform.packages.plugin_management.service import plugin_service

            for plugin_name in info.required_plugins:
                if plugin_name not in plugin_service.get_installed_plugins():
                    return {"error": True, "message": f"Required plugin is missing: {plugin_name}"}
                plugin_service.activate(plugin_name)
        published = self.publish_assets(theme)
        if published["error"]:
            return published
        await setting_store.force_set(db, "theme", theme)
        await setting_store.save(db)
        self.clear_cache()
        await hooks.do_action_async(THEME_ACTION_ACTIVATED, theme)
        return {"error": False, "message": f"Theme '{theme}' activated successfully"}

    def publish_assets(self, theme: str | None = None) -> dict[str, Any]:
        names = [theme] if theme else self.installed_theme_names()
        published = []
        for name in filter(None, names):
            source = theme_path(name, "public")
            target = self.public_themes_path / str(name)
            target.mkdir(parents=True, exist_ok=True)
            if source.exists():
                shutil.copytree(source, target, dirs_exist_ok=True)
            screenshot = theme_path(str(name), "screenshot.png")
            if screenshot.exists():
                shutil.copy2(screenshot, target / "screenshot.png")
            published.append(str(name))
        if not published:
            return {"error": True, "message": "No themes to publish assets"}
        self.clear_cache()
        return {"error": False, "message": f"Published assets for {', '.join(published)}", "data": {"themes": published}}

    async def remove(self, db: AsyncSession, theme: str) -> dict[str, Any]:
        active = await self.active_theme_name(db)
        if active == theme:
            return {"error": True, "message": "Cannot remove the active theme"}
        path = theme_path(theme).resolve()
        root = settings.THEMES_DIR.resolve()
        if root not in path.parents or not path.exists():
            return {"error": True, "message": "Theme path is invalid"}
        shutil.rmtree(path)
        public_path = (self.public_themes_path / theme).resolve()
        if self.public_themes_path.resolve() in public_path.parents and public_path.exists():
            shutil.rmtree(public_path)
        self.clear_cache()
        return {"error": False, "message": f"Theme '{theme}' removed successfully"}

    def get_renderer(self, theme: str, inherit: str | None = None) -> ThemeRenderer:
        return ThemeRenderer(self, theme, inherit)

    async def renderer_for_active_theme(self, db: AsyncSession) -> ThemeRenderer:
        theme = await self.active_theme_name(db)
        info = self.get_theme_info(theme)
        return self.get_renderer(theme, info.inherit if info else None)

    async def render_public_path(self, db: AsyncSession, path: str = "", preview: bool = False) -> HTMLResponse:
        from karpy_platform.packages.page.service import page_service

        renderer = await self.renderer_for_active_theme(db)
        if not path.strip("/"):
            await hooks.do_action_async(THEME_ACTION_RENDERING_HOME, renderer, db)
            page_data = await page_service.public_page(db, preview=preview)
        else:
            page_data = await page_service.public_page(db, slug=path.strip("/"), preview=preview)
        if page_data:
            await hooks.do_action_async(THEME_ACTION_RENDERING_SINGLE, page_data, renderer, db)
            renderer.add_body_attributes({"id": f"page-{page_data['page']['id']}"})
            await renderer.scope(db, page_data["view"], page_data, page_data.get("defaultView"))
            return await renderer.render(db)
        if not path.strip("/"):
            await renderer.scope(db, "index", {"seo": {"title": await self.site_title(db, renderer.theme)}})
            return await renderer.render(db)
        from fastapi.responses import RedirectResponse
        from karpy_platform.core.setting.store import setting_store

        if await setting_store.get(db, "redirect_404_to_homepage", "0") == "1":
            return RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Page not found")

    async def options_payload(self, db: AsyncSession, theme: str | None = None) -> dict[str, Any]:
        theme = theme or await self.active_theme_name(db)
        return await theme_options.payload(db, theme)

    async def update_options(self, db: AsyncSession, values: dict[str, Any], theme: str | None = None) -> dict[str, Any]:
        theme = theme or await self.active_theme_name(db)
        await theme_options.set_options(db, values, theme)
        return await self.options_payload(db, theme)

    async def option(self, db: AsyncSession, key: str, default: Any = "", theme: str | None = None) -> Any:
        active_theme = theme or await self.active_theme_name(db)
        await theme_options.prepare(active_theme)
        return await theme_options.get_option(db, key, default, active_theme)

    async def site_title(self, db: AsyncSession, theme: str | None = None) -> str:
        value = await self.option(db, "site_title", settings.APP_NAME, theme)
        return await hooks.apply_filters_async(THEME_FILTER_SITE_TITLE, value)

    async def logo(self, db: AsyncSession, theme: str | None = None) -> str:
        value = await self.option(db, "logo", "", theme)
        return await hooks.apply_filters_async(THEME_FILTER_LOGO, value)

    async def favicon(self, db: AsyncSession, theme: str | None = None) -> str:
        value = await self.option(db, "favicon", "", theme)
        return await hooks.apply_filters_async(THEME_FILTER_FAVICON, value)

    async def custom_body_html(self, db: AsyncSession, theme: str | None = None) -> str:
        option_html = str(await self.option(db, "custom_body_html", "", theme) or "")
        global_html = str(await setting_store.get(db, "theme_custom_html_body", "") or "")
        return option_html + global_html

    async def custom_footer_js(self, db: AsyncSession, theme: str | None = None) -> str:
        value = str(await self.option(db, "custom_footer_js", "", theme) or "")
        if value and "<script" not in value and "</script>" not in value:
            value = f"<script>{value}</script>"
        return value

    async def custom_header_html(self, db: AsyncSession, theme: str | None = None) -> str:
        css = str(await setting_store.get(db, "theme_custom_css", "") or "")
        header_html = str(await setting_store.get(db, "theme_custom_html_header", "") or "")
        option_js = str(await self.option(db, "custom_header_js", "", theme) or "")
        if option_js and "<script" not in option_js and "</script>" not in option_js:
            option_js = f"<script>{option_js}</script>"
        css_html = f"<style>{css}</style>" if css.strip() else ""
        return css_html + header_html + option_js

    async def custom_footer_html(self, db: AsyncSession, theme: str | None = None) -> str:
        footer_html = str(await setting_store.get(db, "theme_custom_html_footer", "") or "")
        return await self.custom_footer_js(db, theme) + footer_html

    def copyright(self, value: Any) -> str:
        year = str(datetime.now().year)
        return str(value or "").replace("%Y", year).replace("%y", year).replace(":year", year)

    def screenshot_url(self, theme: str) -> str | None:
        if theme_path(theme, "screenshot.png").exists() or (self.public_themes_path / theme / "screenshot.png").exists():
            return f"/api/admin/appearance/themes/{theme}/screenshot"
        return None

    def screenshot_path(self, theme: str) -> Path | None:
        for path in [theme_path(theme, "screenshot.png"), self.public_themes_path / theme / "screenshot.png"]:
            if path.exists():
                return path
        return None

    def presets(self, theme: str) -> dict[str, Any] | list[Any]:
        info = self.get_theme_info(theme)
        return info.presets if info else {}

    def clear_cache(self) -> None:
        self._cache.clear()


theme_service = ThemeService()


def boot_theme_package() -> None:
    theme_service.boot()
