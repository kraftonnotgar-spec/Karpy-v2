from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable
from urllib.parse import urljoin

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from karpy_platform.core.base.helpers import clean, slugify
from karpy_platform.core.base.hooks import hooks
from karpy_platform.core.setting.registry import SettingField, SettingSection, setting_panel_registry
from karpy_platform.core.setting.store import setting_store
from karpy_platform.packages.page.models import Page
from karpy_platform.packages.slug.constants import (
    CMS_SLUG_VARIABLES,
    FILTER_SLUG_EXISTED_STRING,
    FILTER_SLUG_PREFIX,
    FILTER_SLUG_STRING,
    SLUG_ACTION_PERMALINK_UPDATED,
    SLUG_ACTION_UPDATED,
)
from karpy_platform.packages.slug.models import Slug


@dataclass
class SlugModule:
    model: type
    name: str
    prefix: str = ""
    can_empty_prefix: bool = False
    generator_column: str = "name"
    preview: bool = True

    @property
    def model_type(self) -> str:
        return f"{self.model.__module__}.{self.model.__name__}"


class SlugCompiler:
    def variables(self) -> dict[str, dict[str, Any]]:
        now = datetime.utcnow()
        variables = {
            "%%year%%": {"label": "Current year", "value": now.year},
            "%%month%%": {"label": "Current month", "value": f"{now.month:02d}"},
            "%%day%%": {"label": "Current day", "value": f"{now.day:02d}"},
        }
        return hooks.apply_filters(CMS_SLUG_VARIABLES, variables)

    def compile(self, prefix: str | None, model: Any = None) -> str:
        if not prefix:
            return ""
        value = str(prefix).strip("/")
        for key, item in self.variables().items():
            value = value.replace(key, str(item.get("value", "")))
        return hooks.apply_filters("cms_slug_prefix", value, model)


class SlugService:
    """Botble-style slug helper/service for permalink records and URLs."""

    def __init__(self) -> None:
        self._booted = False
        self._modules: dict[str, SlugModule] = {}
        self._aliases: dict[str, str] = {}
        self.compiler = SlugCompiler()

    def boot(self) -> None:
        if self._booted:
            return
        self.register_module(Page, "Pages", alias="page", prefix="", can_empty_prefix=True, generator_column="name")
        setting_panel_registry.register_section(
            SettingSection(
                id="permalink",
                title="Permalink",
                description="Slug prefixes, URL endings, and public permalink behavior.",
                icon="link",
                route="/admin/settings/permalink",
                priority=90,
                permission="settings.options",
                group="settings.common",
                source="package:slug",
                hidden=True,
                fields=[
                    SettingField("public_single_ending_url", "Public single ending URL", default="", description="Example: html makes URLs end with .html"),
                    SettingField("slug_turn_off_automatic_url_translation_into_latin", "Turn off automatic URL translation into Latin", type="switch", default="0"),
                ],
            )
        )
        self._booted = True

    def register_module(
        self,
        model: type,
        name: str | Callable[[], str] | None = None,
        *,
        alias: str | None = None,
        prefix: str = "",
        can_empty_prefix: bool = False,
        generator_column: str = "name",
        preview: bool = True,
    ) -> None:
        display_name = name() if callable(name) else (name or model.__name__)
        module = SlugModule(model=model, name=display_name, prefix=prefix, can_empty_prefix=can_empty_prefix, generator_column=generator_column, preview=preview)
        self._modules[module.model_type] = module
        self._aliases[alias or model.__name__.lower()] = module.model_type

    def remove_module(self, model_or_alias: str | type) -> None:
        model_type = self.model_type(model_or_alias)
        module = self._modules.pop(model_type, None)
        if module:
            for alias, alias_model in list(self._aliases.items()):
                if alias_model == model_type:
                    self._aliases.pop(alias, None)

    def supported_models(self) -> dict[str, dict[str, Any]]:
        return {
            model_type: {
                "modelType": model_type,
                "name": module.name,
                "prefix": module.prefix,
                "canEmptyPrefix": module.can_empty_prefix,
                "generatorColumn": module.generator_column,
                "preview": module.preview,
            }
            for model_type, module in self._modules.items()
        }

    def is_supported_model(self, model_or_alias: Any) -> bool:
        return self.model_type(model_or_alias) in self._modules

    def model_type(self, model_or_alias: Any) -> str:
        if isinstance(model_or_alias, str):
            return self._aliases.get(model_or_alias, model_or_alias)
        model = model_or_alias if isinstance(model_or_alias, type) else model_or_alias.__class__
        return f"{model.__module__}.{model.__name__}"

    def module(self, model_or_alias: Any) -> SlugModule | None:
        return self._modules.get(self.model_type(model_or_alias))

    async def prefix(self, db: AsyncSession, model_or_alias: Any, default: str = "", translate: bool = True) -> str:
        model_type = self.model_type(model_or_alias)
        module = self._modules.get(model_type)
        key = self.permalink_setting_key(model_type)
        value = await setting_store.get(db, key, None)
        if value is None:
            value = module.prefix if module else default
        value = str(value or "").strip("/")
        return self.compiler.compile(value, model_or_alias) if translate else value

    def permalink_setting_key(self, model_type: str) -> str:
        return self.setting_key("permalink-" + slugify(model_type.replace(".", "_"), "model"))

    def setting_key(self, key: str) -> str:
        return hooks.apply_filters("slug_helper_get_permalink_setting_key", key)

    async def public_single_ending_url(self, db: AsyncSession) -> str:
        value = await setting_store.get(db, self.setting_key("public_single_ending_url"), "")
        value = str(value or "").strip().lstrip(".")
        return f".{value}" if value else ""

    async def turn_off_automatic_url_translation_into_latin(self, db: AsyncSession) -> bool:
        value = await setting_store.get(db, self.setting_key("slug_turn_off_automatic_url_translation_into_latin"), "0")
        return str(value).lower() in {"1", "true", "yes", "on"}

    async def create_slug_string(
        self,
        db: AsyncSession,
        value: str | None,
        *,
        slug_id: str | None = None,
        model: Any = None,
        prefix: str | None = None,
    ) -> str:
        if await self.turn_off_automatic_url_translation_into_latin(db):
            base_slug = clean(value or "").strip().replace("/", "-")
            base_slug = base_slug or str(int(datetime.utcnow().timestamp()))
        else:
            base_slug = slugify(value or str(int(datetime.utcnow().timestamp())), fallback="item")

        model_prefix = prefix
        if model_prefix is None and model is not None:
            model_prefix = await self.prefix(db, model, translate=False)
        model_prefix = (model_prefix or "").strip("/")

        candidate = base_slug
        index = 1
        while await self.exists(db, candidate, model_prefix, ignore_id=slug_id):
            candidate = hooks.apply_filters(FILTER_SLUG_EXISTED_STRING, f"{base_slug}-{index}", base_slug, index, model)
            index += 1

        return hooks.apply_filters(FILTER_SLUG_STRING, candidate, model)

    async def exists(self, db: AsyncSession, key: str, prefix: str = "", ignore_id: str | None = None) -> bool:
        statement = select(Slug).where(Slug.key == key, Slug.prefix == (prefix or ""))
        if ignore_id:
            statement = statement.where(Slug.id != ignore_id)
        return bool(await db.scalar(statement))

    async def save_for_model(self, db: AsyncSession, model: Any, value: str | None = None) -> Slug:
        model_type = self.model_type(model)
        module = self._modules.get(model_type)
        if not module:
            raise ValueError(f"Model {model_type} is not registered for slugs")

        result = await db.execute(select(Slug).where(Slug.reference_type == model_type, Slug.reference_id == model.id))
        slug = result.scalar_one_or_none()
        prefix = await self.prefix(db, model_type, translate=False)
        source = value or getattr(model, module.generator_column, None) or getattr(model, "name", None) or model.id
        key = await self.create_slug_string(db, source, slug_id=slug.id if slug else None, model=model_type, prefix=prefix)
        if not slug:
            slug = Slug(reference_type=model_type, reference_id=model.id)
            db.add(slug)
        slug.key = key
        slug.prefix = prefix
        if hasattr(model, "slug"):
            model.slug = key
        await hooks.do_action_async(SLUG_ACTION_UPDATED, model, slug)
        return slug

    async def get_slug(
        self,
        db: AsyncSession,
        key: str | None,
        *,
        prefix: str | None = None,
        model: Any = None,
        reference_id: str | None = None,
    ) -> Slug | None:
        if key is not None:
            ending = await self.public_single_ending_url(db)
            if ending and key.endswith(ending):
                key = key[: -len(ending)]
        statement = select(Slug)
        if key is not None:
            statement = statement.where(Slug.key == key)
        if prefix is not None:
            statement = statement.where(Slug.prefix == prefix.strip("/"))
        if model is not None:
            statement = statement.where(Slug.reference_type == self.model_type(model))
        if reference_id is not None:
            statement = statement.where(Slug.reference_id == reference_id)
        return await db.scalar(statement)

    async def find_reference(self, db: AsyncSession, path: str, model: Any = None) -> tuple[Slug | None, str]:
        path = path.strip("/")
        ending = await self.public_single_ending_url(db)
        if ending and path.endswith(ending):
            path = path[: -len(ending)]
        prefixes = sorted(await self.all_prefixes(db), key=len, reverse=True)
        prefix = ""
        key = path
        for candidate in prefixes:
            candidate = candidate.strip("/")
            if candidate and (path == candidate or path.startswith(candidate + "/")):
                prefix = candidate
                key = path[len(candidate) :].strip("/")
                break
        slug = await self.get_slug(db, key, prefix=prefix, model=model)
        return slug, key

    async def url_for_model(self, db: AsyncSession, model: Any) -> str:
        slug = await self.get_slug(db, None, model=model, reference_id=model.id)
        site_url = settings.site_url + "/"
        if not slug:
            prefix = await self.prefix(db, model, translate=True)
            key = getattr(model, "slug", None) or model.id
            path = "/".join(segment.strip("/") for segment in [hooks.apply_filters(FILTER_SLUG_PREFIX, prefix), key] if segment)
            return urljoin(site_url, path) + await self.public_single_ending_url(db)
        path = "/".join(segment.strip("/") for segment in [hooks.apply_filters(FILTER_SLUG_PREFIX, slug.prefix), slug.key] if segment)
        return urljoin(site_url, path) + await self.public_single_ending_url(db)

    async def delete_for_model(self, db: AsyncSession, model: Any) -> int:
        result = await db.execute(delete(Slug).where(Slug.reference_type == self.model_type(model), Slug.reference_id == model.id))
        return result.rowcount or 0

    async def create_missing(self, db: AsyncSession) -> int:
        created = 0
        for module in self._modules.values():
            result = await db.execute(select(module.model))
            for model in result.scalars().unique().all():
                if hasattr(model, "is_deleted") and model.is_deleted:
                    continue
                if not await self.get_slug(db, None, model=module.model, reference_id=model.id):
                    await self.save_for_model(db, model, getattr(model, "slug", None))
                    created += 1
        await db.commit()
        return created

    async def truncate(self, db: AsyncSession) -> int:
        result = await db.execute(delete(Slug))
        await db.commit()
        return result.rowcount or 0

    async def update_prefix(self, db: AsyncSession, model_or_alias: Any, prefix: str) -> None:
        model_type = self.model_type(model_or_alias)
        prefix = prefix.strip("/")
        await setting_store.set(db, self.permalink_setting_key(model_type), prefix)
        await setting_store.save(db)
        await db.execute(update(Slug).where(Slug.reference_type == model_type).values(prefix=prefix))
        await db.commit()
        await hooks.do_action_async(SLUG_ACTION_PERMALINK_UPDATED, model_type, prefix)

    async def all_prefixes(self, db: AsyncSession) -> list[str]:
        prefixes = []
        for model_type, module in self._modules.items():
            prefixes.append(await self.prefix(db, model_type, translate=False))
            prefixes.append(module.prefix)
        return list(dict.fromkeys(filter(None, prefixes)))

    async def settings_payload(self, db: AsyncSession) -> dict[str, Any]:
        modules = []
        for model_type, module in self._modules.items():
            key = self.permalink_setting_key(model_type)
            prefix = await self.prefix(db, model_type, translate=False)
            modules.append(
                {
                    "modelType": model_type,
                    "name": module.name,
                    "settingKey": key,
                    "prefix": prefix,
                    "canEmptyPrefix": module.can_empty_prefix,
                    "helperText": self.helper_text(prefix, "your-url-here"),
                }
            )
        return {
            "modules": modules,
            "publicSingleEndingUrl": await self.public_single_ending_url(db),
            "turnOffAutomaticUrlTranslationIntoLatin": await self.turn_off_automatic_url_translation_into_latin(db),
            "variables": self.compiler.variables(),
        }

    def helper_text(self, prefix: str, postfix: str = "", separation: str = "/") -> str:
        path = (prefix.strip("/") + separation + postfix.strip("/")).strip("/") if prefix else postfix.strip("/")
        return urljoin(settings.site_url + "/", path)


slug_service = SlugService()


def boot_slug_package() -> None:
    slug_service.boot()
