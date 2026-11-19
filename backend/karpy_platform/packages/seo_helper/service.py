from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from karpy_platform.core.base.hooks import hooks
from karpy_platform.core.base.meta_box import meta_box
from karpy_platform.core.setting.registry import SettingField, SettingSection, setting_panel_registry
from karpy_platform.core.setting.store import setting_store
from karpy_platform.packages.seo_helper.constants import (
    SEO_HELPER_FILTER_META,
    SEO_HELPER_FILTER_OPEN_GRAPH,
    SEO_HELPER_FILTER_RENDER,
    SEO_HELPER_FILTER_SUPPORTED_MODELS,
    SEO_HELPER_FILTER_TWITTER,
    SEO_META_KEY,
)
from karpy_platform.packages.seo_helper.entities import MetaCollection, SeoDescription, SeoOpenGraph, SeoTitle, SeoTwitter, clean_text


@dataclass
class SeoModule:
    model: type
    alias: str
    label: str

    @property
    def model_type(self) -> str:
        return f"{self.model.__module__}.{self.model.__name__}"


class SeoHelperService:
    """Botble-style SEO helper for meta tags, OG tags, Twitter cards, and SEO meta boxes."""

    webmaster_names = {
        "google": "google-site-verification",
        "bing": "msvalidate.01",
        "alexa": "alexaVerifyID",
        "pinterest": "p:domain_verify",
        "yandex": "yandex-verification",
    }

    def __init__(self) -> None:
        self._booted = False
        self._modules: dict[str, SeoModule] = {}
        self._aliases: dict[str, str] = {}

    def boot(self) -> None:
        if self._booted:
            return
        from karpy_platform.packages.page.models import Page

        self.register_module(Page, alias="page", label="Page")
        setting_panel_registry.register_section(
            SettingSection(
                id="seo",
                title="SEO",
                description="Default title, description, robots, Open Graph, Twitter, and webmaster verification.",
                icon="search-check",
                route="/admin/settings/seo",
                priority=25,
                group="settings.common",
                source="package:seo-helper",
                hidden=True,
                fields=[
                    SettingField("seo_title", "Default SEO title", default=settings.APP_NAME),
                    SettingField("seo_description", "Default SEO description", type="textarea", default=""),
                    SettingField("seo_og_image", "Default Open Graph image", type="mediaImage", default=""),
                    SettingField("seo_index", "Allow search engines to index site", type="switch", default="1"),
                    SettingField("seo_twitter_site", "Twitter site username", default=""),
                    SettingField("seo_twitter_card", "Twitter card type", type="select", default="summary", options=[
                        {"value": "summary", "label": "Summary"},
                        {"value": "summary_large_image", "label": "Summary large image"},
                    ]),
                    SettingField("seo_google_site_verification", "Google site verification", default=""),
                    SettingField("seo_bing_site_verification", "Bing site verification", default=""),
                    SettingField("seo_yandex_site_verification", "Yandex site verification", default=""),
                ],
            )
        )
        self._booted = True

    def register_module(self, model: type, *, alias: str | None = None, label: str | None = None) -> None:
        module = SeoModule(model=model, alias=alias or model.__name__.lower(), label=label or model.__name__)
        self._modules[module.model_type] = module
        self._aliases[module.alias] = module.model_type

    def remove_module(self, model_or_alias: str | type) -> None:
        model_type = self._model_type(model_or_alias)
        if not model_type:
            return
        module = self._modules.pop(model_type, None)
        if module:
            self._aliases.pop(module.alias, None)

    async def supported_modules(self) -> dict[str, dict[str, str]]:
        modules = {
            module.alias: {"alias": module.alias, "label": module.label, "modelType": module.model_type}
            for module in self._modules.values()
        }
        return await hooks.apply_filters_async(SEO_HELPER_FILTER_SUPPORTED_MODELS, modules)

    def is_supported(self, model_or_alias: Any) -> bool:
        return self._model_type(model_or_alias) in self._modules

    async def save_meta_data(
        self,
        db: AsyncSession,
        model: Any,
        seo_meta: dict[str, Any] | None,
    ) -> dict[str, Any]:
        if not self.is_supported(model):
            return {}

        normalized = self.normalize_meta(seo_meta)
        self._sync_model_columns(model, normalized)

        if normalized:
            await meta_box.save_meta_data(db, model.id, self._model_type(model), SEO_META_KEY, normalized)
        else:
            await meta_box.delete_meta_data(db, model.id, self._model_type(model), SEO_META_KEY)
        return normalized

    async def delete_meta_data(self, db: AsyncSession, model: Any) -> int:
        if not self.is_supported(model):
            return 0
        return await meta_box.delete_meta_data(db, model.id, self._model_type(model), SEO_META_KEY)

    async def get_meta_data(self, db: AsyncSession, model: Any) -> dict[str, Any]:
        if not self.is_supported(model) or not getattr(model, "id", None):
            return self.default_meta()
        stored = await meta_box.get_meta_data(db, model.id, self._model_type(model), SEO_META_KEY, single=True)
        meta = self.default_meta()
        if isinstance(stored, dict):
            meta.update(stored)
        meta.update({key: value for key, value in self._model_meta(model).items() if value})
        return meta

    def normalize_meta(self, meta: dict[str, Any] | None) -> dict[str, Any]:
        meta = meta or {}
        cleaned = {
            "seo_title": clean_text(meta.get("seo_title"), 70),
            "seo_description": clean_text(meta.get("seo_description"), 160),
            "seo_image": str(meta.get("seo_image") or meta.get("seo_meta_image") or "").strip(),
            "index": meta.get("index") if meta.get("index") in {"index", "noindex"} else "index",
        }
        return {key: value for key, value in cleaned.items() if value}

    def default_meta(self) -> dict[str, Any]:
        return {"seo_title": None, "seo_description": None, "seo_image": None, "index": "index"}

    def meta_box_schema(self, model: Any | None = None, meta: dict[str, Any] | None = None) -> dict[str, Any]:
        meta = {**self.default_meta(), **(meta or {})}
        return {
            "id": "seo_wrap",
            "title": "Search Engine Optimize",
            "supported": bool(model is None or self.is_supported(model)),
            "assets": {
                "styles": ["vendor/core/packages/seo-helper/css/seo-helper.css"],
                "scripts": ["vendor/core/packages/seo-helper/js/seo-helper.js"],
            },
            "fields": [
                {"key": "seo_meta.seo_title", "label": "SEO title", "type": "text", "maxLength": 70, "value": meta.get("seo_title")},
                {"key": "seo_meta.seo_description", "label": "SEO description", "type": "textarea", "maxLength": 160, "rows": 3, "value": meta.get("seo_description")},
                {"key": "seo_meta.seo_image", "label": "SEO image", "type": "mediaImage", "value": meta.get("seo_image")},
                {
                    "key": "seo_meta.index",
                    "label": "Index",
                    "type": "radio",
                    "value": meta.get("index", "index"),
                    "options": [{"value": "index", "label": "Index"}, {"value": "noindex", "label": "No index"}],
                },
            ],
        }

    async def render_for_model(self, db: AsyncSession, model: Any, url: str | None = None) -> dict[str, Any]:
        meta = await self.get_meta_data(db, model)
        title = meta.get("seo_title") or getattr(model, "name", None) or getattr(model, "title", None)
        description = meta.get("seo_description") or getattr(model, "description", None) or getattr(model, "content", None)
        image = meta.get("seo_image") or getattr(model, "image", None)
        return await self.render(db, title=title, description=description, image=image, url=url, robots_index=meta.get("index", "index") == "index")

    async def render(
        self,
        db: AsyncSession,
        *,
        title: str | None = None,
        description: str | None = None,
        image: str | None = None,
        url: str | None = None,
        robots_index: bool | None = None,
        og_type: str = "website",
    ) -> dict[str, Any]:
        site_title = str(await setting_store.get(db, "site_title", settings.APP_NAME) or settings.APP_NAME)
        default_title = str(await setting_store.get(db, "seo_title", site_title) or site_title)
        default_description = str(await setting_store.get(db, "seo_description", "") or "")
        default_image = str(await setting_store.get(db, "seo_og_image", "") or "")
        twitter_card = str(await setting_store.get(db, "seo_twitter_card", "summary") or "summary")
        twitter_site = str(await setting_store.get(db, "seo_twitter_site", "") or "")
        seo_index = await setting_store.get(db, "seo_index", "1")

        robots_index = robots_index if robots_index is not None else str(seo_index) in {"1", "true", "True", "index"}
        title_value = title or default_title
        description_value = description or default_description
        image_value = image or default_image
        url_value = url or settings.site_url

        title_entity = SeoTitle(default_title, site_name=site_title, separator="-", first=True)
        title_entity.set(title_value)
        description_entity = SeoDescription(description_value)
        misc = MetaCollection(ignored={"description"})
        misc.add("canonical", url_value)
        misc.add("robots", "index, follow" if robots_index else "noindex, nofollow")
        for key, webmaster_name in self.webmaster_names.items():
            value = await setting_store.get(db, f"seo_{key}_site_verification", "")
            if value:
                misc.add(webmaster_name, value)

        open_graph = SeoOpenGraph(site_name=site_title).set_type(og_type).set_title(title_value).set_description(description_value).set_url(url_value)
        if image_value:
            open_graph.set_image(image_value)
        twitter = SeoTwitter(twitter_card).set_title(title_value).set_description(description_value).set_site(twitter_site)
        if image_value:
            twitter.add_image(image_value)

        misc = await hooks.apply_filters_async(SEO_HELPER_FILTER_META, misc)
        open_graph = await hooks.apply_filters_async(SEO_HELPER_FILTER_OPEN_GRAPH, open_graph)
        twitter = await hooks.apply_filters_async(SEO_HELPER_FILTER_TWITTER, twitter)

        tags = "\n".join(filter(None, [title_entity.render(), description_entity.render(), misc.render(), open_graph.render(), twitter.render()]))
        tags = await hooks.apply_filters_async(SEO_HELPER_FILTER_RENDER, tags)
        return {
            "title": title_entity.get(),
            "titleOnly": title_entity.get_title_only(),
            "description": description_entity.get(),
            "image": image_value,
            "url": url_value,
            "robots": "index, follow" if robots_index else "noindex, nofollow",
            "openGraph": open_graph.to_dict(),
            "twitter": twitter.to_dict(),
            "html": tags,
        }

    def _sync_model_columns(self, model: Any, meta: dict[str, Any]) -> None:
        mapping = {"seo_title": "seo_title", "seo_description": "seo_description", "seo_image": "seo_image"}
        for meta_key, column in mapping.items():
            if hasattr(model, column):
                setattr(model, column, meta.get(meta_key))

    def _model_meta(self, model: Any) -> dict[str, Any]:
        return {
            "seo_title": getattr(model, "seo_title", None),
            "seo_description": getattr(model, "seo_description", None),
            "seo_image": getattr(model, "seo_image", None),
        }

    def _model_type(self, model_or_alias: Any) -> str | None:
        if isinstance(model_or_alias, str):
            return self._aliases.get(model_or_alias, model_or_alias)
        model = model_or_alias if isinstance(model_or_alias, type) else model_or_alias.__class__
        return f"{model.__module__}.{model.__name__}"


seo_helper = SeoHelperService()


def boot_seo_helper_package() -> None:
    seo_helper.boot()
