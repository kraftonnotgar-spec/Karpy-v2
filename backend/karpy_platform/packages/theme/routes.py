from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.config import settings
from karpy_platform.core.acl.routes import ensure_admin_user
from karpy_platform.core.base.responses import BaseHttpResponse
from karpy_platform.core.setting.store import setting_store
from karpy_platform.packages.theme.service import theme_service

admin_router = APIRouter()
options_router = APIRouter()
public_router = APIRouter()


class ThemeOptionsUpdate(BaseModel):
    values: dict[str, Any] = Field(default_factory=dict)
    theme: str | None = None


class CustomCssUpdate(BaseModel):
    custom_css: str = Field(default="", max_length=100000)


class CustomHtmlUpdate(BaseModel):
    header_html: str = Field(default="", max_length=100000)
    body_html: str = Field(default="", max_length=100000)
    footer_html: str = Field(default="", max_length=100000)


class RobotsUpdate(BaseModel):
    content: str = Field(default="", max_length=200000)


def robots_txt_path():
    public_dir = settings.BASE_DIR / "public"
    public_dir.mkdir(parents=True, exist_ok=True)
    return public_dir / "robots.txt"


@admin_router.get("")
async def list_themes(db: AsyncSession = Depends(get_db)):
    await ensure_admin_user(db)
    return {"themes": await theme_service.list_themes(db), "active": await theme_service.active_theme_name(db)}


@admin_router.get("/active")
async def active_theme(db: AsyncSession = Depends(get_db)):
    await ensure_admin_user(db)
    active = await theme_service.active_theme_name(db)
    info = theme_service.get_theme_info(active)
    return {"theme": info.to_dict(active=True, screenshot=theme_service.screenshot_url(active)) if info else {"folder": active, "active": True}}


@admin_router.post("/{theme}/activate")
async def activate_theme(theme: str, db: AsyncSession = Depends(get_db)):
    await ensure_admin_user(db)
    result = await theme_service.activate(db, theme)
    return BaseHttpResponse.make().set_error(result["error"]).set_message(result["message"]).set_data(result.get("data")).to_dict()


@admin_router.post("/publish-assets")
async def publish_assets(theme: str | None = Query(default=None), db: AsyncSession = Depends(get_db)):
    await ensure_admin_user(db)
    result = theme_service.publish_assets(theme)
    return BaseHttpResponse.make().set_error(result["error"]).set_message(result["message"]).set_data(result.get("data")).to_dict()


@admin_router.delete("/{theme}")
async def remove_theme(theme: str, db: AsyncSession = Depends(get_db)):
    await ensure_admin_user(db)
    result = await theme_service.remove(db, theme)
    return BaseHttpResponse.make().set_error(result["error"]).set_message(result["message"]).to_dict()


@admin_router.get("/{theme}/presets")
async def theme_presets(theme: str, db: AsyncSession = Depends(get_db)):
    await ensure_admin_user(db)
    return {"theme": theme, "presets": theme_service.presets(theme)}


@admin_router.get("/{theme}/screenshot")
async def theme_screenshot(theme: str, db: AsyncSession = Depends(get_db)):
    await ensure_admin_user(db)
    path = theme_service.screenshot_path(theme)
    if not path:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Theme screenshot not found")
    return FileResponse(path)


@options_router.get("")
async def get_theme_options(theme: str | None = Query(default=None), db: AsyncSession = Depends(get_db)):
    await ensure_admin_user(db)
    return await theme_service.options_payload(db, theme)


@options_router.put("")
async def update_theme_options(payload: ThemeOptionsUpdate, db: AsyncSession = Depends(get_db)):
    await ensure_admin_user(db)
    data = await theme_service.update_options(db, payload.values, payload.theme)
    return BaseHttpResponse.make().set_data(data).with_updated_success_message().to_dict()


@options_router.get("/custom-css")
async def get_custom_css(db: AsyncSession = Depends(get_db)):
    await ensure_admin_user(db)
    return {
        "customCss": await setting_store.get(db, "theme_custom_css", ""),
        "activeTheme": await theme_service.active_theme_name(db),
    }


@options_router.put("/custom-css")
async def update_custom_css(payload: CustomCssUpdate, db: AsyncSession = Depends(get_db)):
    await ensure_admin_user(db)
    await setting_store.force_set(db, "theme_custom_css", payload.custom_css)
    await setting_store.save(db)
    return BaseHttpResponse.make().set_data({"customCss": payload.custom_css}).with_updated_success_message().to_dict()


@options_router.get("/custom-html")
async def get_custom_html(db: AsyncSession = Depends(get_db)):
    await ensure_admin_user(db)
    return {
        "headerHtml": await setting_store.get(db, "theme_custom_html_header", ""),
        "bodyHtml": await setting_store.get(db, "theme_custom_html_body", ""),
        "footerHtml": await setting_store.get(db, "theme_custom_html_footer", ""),
        "activeTheme": await theme_service.active_theme_name(db),
    }


@options_router.put("/custom-html")
async def update_custom_html(payload: CustomHtmlUpdate, db: AsyncSession = Depends(get_db)):
    await ensure_admin_user(db)
    await setting_store.force_set(
        db,
        {
            "theme_custom_html_header": payload.header_html,
            "theme_custom_html_body": payload.body_html,
            "theme_custom_html_footer": payload.footer_html,
        },
    )
    await setting_store.save(db)
    return BaseHttpResponse.make().set_data(payload.model_dump()).with_updated_success_message().to_dict()


@options_router.get("/robots-txt")
async def get_robots_txt(db: AsyncSession = Depends(get_db)):
    await ensure_admin_user(db)
    path = robots_txt_path()
    default = "User-agent: *\nAllow: /\nSitemap: /sitemap.xml\n"
    content = path.read_text(encoding="utf-8") if path.exists() else default
    return {"content": content, "path": str(path), "writable": path.parent.exists()}


@options_router.put("/robots-txt")
async def update_robots_txt(payload: RobotsUpdate, db: AsyncSession = Depends(get_db)):
    await ensure_admin_user(db)
    path = robots_txt_path()
    path.write_text(payload.content, encoding="utf-8")
    return BaseHttpResponse.make().set_data({"content": payload.content, "path": str(path)}).with_updated_success_message().to_dict()


@options_router.get("/option/{key}")
async def get_theme_option(key: str, theme: str | None = Query(default=None), default: str = "", db: AsyncSession = Depends(get_db)):
    await ensure_admin_user(db)
    return {"key": key, "value": await theme_service.option(db, key, default, theme)}


@public_router.get("/site")
async def render_home(preview: bool = False, db: AsyncSession = Depends(get_db)):
    return await theme_service.render_public_path(db, "", preview=preview)


@public_router.get("/site/{path:path}")
async def render_path(path: str, preview: bool = False, db: AsyncSession = Depends(get_db)):
    return await theme_service.render_public_path(db, path, preview=preview)


@public_router.get("/robots.txt", include_in_schema=False)
async def public_robots_txt():
    path = robots_txt_path()
    if not path.exists():
        return PlainTextResponse("User-agent: *\nAllow: /\nSitemap: /sitemap.xml\n")
    return PlainTextResponse(path.read_text(encoding="utf-8"))
