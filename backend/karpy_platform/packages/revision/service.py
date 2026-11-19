from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from importlib import import_module
from typing import Any

from sqlalchemy import delete, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from karpy_platform.core.base.hooks import hooks
from karpy_platform.packages.revision.constants import (
    REVISION_ACTION_CREATED,
    REVISION_ACTION_DELETED,
    REVISION_ACTION_RESTORED,
    REVISION_ACTION_SAVED,
    REVISION_FILTER_FORMAT_VALUE,
    REVISION_FILTER_HISTORY,
    REVISION_FILTER_PAYLOAD,
    REVISION_FILTER_SUPPORTED_MODELS,
)
from karpy_platform.packages.revision.formatter import FieldFormatter
from karpy_platform.packages.revision.models import Revision


@dataclass
class RevisionModelConfig:
    model: type
    alias: str
    label: str
    keep: list[str] = field(default_factory=list)
    dont_keep: list[str] = field(default_factory=list)
    formatted_fields: dict[str, str] = field(default_factory=dict)
    formatted_field_names: dict[str, str] = field(default_factory=dict)
    history_limit: int = 20
    cleanup: bool = True
    creations_enabled: bool = False
    enabled: bool = True

    @property
    def model_type(self) -> str:
        return f"{self.model.__module__}.{self.model.__name__}"


class RevisionService:
    """Python port of Botble's revision package and RevisionableTrait."""

    def __init__(self) -> None:
        self._booted = False
        self._models: dict[str, RevisionModelConfig] = {}
        self._aliases: dict[str, str] = {}

    def boot(self) -> None:
        if self._booted:
            return
        from karpy_platform.packages.page.models import Page

        self.register_model(
            Page,
            alias="page",
            label="Page",
            keep=[
                "name",
                "slug",
                "image",
                "template",
                "description",
                "status",
                "user_id",
                "is_featured",
                "seo_title",
                "seo_description",
                "seo_image",
                "is_deleted",
            ],
            dont_keep=["content"],
            formatted_fields={"status": "status", "is_featured": "bool", "is_deleted": "bool"},
            formatted_field_names={
                "seo_title": "SEO title",
                "seo_description": "SEO description",
                "seo_image": "SEO image",
                "is_featured": "Featured",
                "is_deleted": "Deleted",
                "user_id": "Author",
            },
            history_limit=20,
            cleanup=True,
        )
        self._booted = True

    def register_model(
        self,
        model: type,
        *,
        alias: str | None = None,
        label: str | None = None,
        keep: list[str] | None = None,
        dont_keep: list[str] | None = None,
        formatted_fields: dict[str, str] | None = None,
        formatted_field_names: dict[str, str] | None = None,
        history_limit: int = 20,
        cleanup: bool = True,
        creations_enabled: bool = False,
        enabled: bool = True,
    ) -> None:
        config = RevisionModelConfig(
            model=model,
            alias=alias or model.__name__.lower(),
            label=label or model.__name__,
            keep=keep or [],
            dont_keep=dont_keep or [],
            formatted_fields=formatted_fields or {},
            formatted_field_names=formatted_field_names or {},
            history_limit=history_limit,
            cleanup=cleanup,
            creations_enabled=creations_enabled,
            enabled=enabled,
        )
        self._models[config.model_type] = config
        self._aliases[config.alias] = config.model_type

    async def supported_models(self) -> dict[str, dict[str, Any]]:
        models = {
            config.alias: {
                "alias": config.alias,
                "label": config.label,
                "modelType": config.model_type,
                "historyLimit": config.history_limit,
                "cleanup": config.cleanup,
                "creationsEnabled": config.creations_enabled,
                "enabled": config.enabled,
            }
            for config in self._models.values()
        }
        return await hooks.apply_filters_async(REVISION_FILTER_SUPPORTED_MODELS, models)

    def get_config(self, model_or_alias: Any) -> RevisionModelConfig | None:
        if isinstance(model_or_alias, str):
            model_type = self._aliases.get(model_or_alias, model_or_alias)
            return self._models.get(model_type)
        model_type = self.model_type(model_or_alias)
        return self._models.get(model_type)

    def model_type(self, model_or_class: Any) -> str:
        model = model_or_class if isinstance(model_or_class, type) else model_or_class.__class__
        return f"{model.__module__}.{model.__name__}"

    def snapshot(self, model: Any, config: RevisionModelConfig | None = None) -> dict[str, Any]:
        config = config or self.get_config(model)
        if not config:
            return {}

        data = {}
        for column in model.__table__.columns:
            key = column.name
            if key in {"id", "created_at", "updated_at"}:
                continue
            if config.keep and key not in config.keep:
                continue
            if key in config.dont_keep:
                continue
            data[key] = getattr(model, key)
        return data

    async def record_created(self, db: AsyncSession, model: Any, *, user_id: str | None = None) -> list[Revision]:
        config = self.get_config(model)
        if not config or not config.enabled or not config.creations_enabled:
            return []

        revisions = [
            Revision(
                revisionable_type=config.model_type,
                revisionable_id=model.id,
                user_id=user_id,
                key="created_at",
                old_value=None,
                new_value=self._serialize(getattr(model, "created_at", None)),
            )
        ]
        db.add_all(revisions)
        await hooks.do_action_async(REVISION_ACTION_CREATED, model, revisions)
        return revisions

    async def record_update(
        self,
        db: AsyncSession,
        model: Any,
        before: dict[str, Any],
        *,
        user_id: str | None = None,
    ) -> list[Revision]:
        config = self.get_config(model)
        if not config or not config.enabled:
            return []

        after = self.snapshot(model, config)
        revisions = []
        for key, old_value in before.items():
            if key not in after or old_value == after[key]:
                continue
            revisions.append(
                Revision(
                    revisionable_type=config.model_type,
                    revisionable_id=model.id,
                    user_id=user_id,
                    key=key,
                    old_value=self._serialize(old_value),
                    new_value=self._serialize(after[key]),
                )
            )

        if not revisions:
            return []

        if config.cleanup:
            await self._cleanup(db, config, model.id, incoming=len(revisions))

        db.add_all(revisions)
        await hooks.do_action_async(REVISION_ACTION_SAVED, model, revisions)
        return revisions

    async def record_deleted(self, db: AsyncSession, model: Any, before: dict[str, Any], *, user_id: str | None = None) -> list[Revision]:
        revisions = await self.record_update(db, model, before, user_id=user_id)
        if revisions:
            await hooks.do_action_async(REVISION_ACTION_DELETED, model, revisions)
        return revisions

    async def history(
        self,
        db: AsyncSession,
        model_or_alias: str,
        model_id: str,
        *,
        limit: int = 100,
        offset: int = 0,
        order: str = "desc",
    ) -> list[Revision]:
        config = self.get_config(model_or_alias)
        revisionable_type = config.model_type if config else model_or_alias
        statement = (
            select(Revision)
            .where(Revision.revisionable_type == revisionable_type, Revision.revisionable_id == model_id)
            .order_by(desc(Revision.created_at) if order == "desc" else Revision.created_at)
            .offset(offset)
            .limit(limit)
        )
        result = await db.execute(statement)
        revisions = list(result.scalars().unique().all())
        return await hooks.apply_filters_async(REVISION_FILTER_HISTORY, revisions, revisionable_type, model_id)

    async def class_history(self, db: AsyncSession, model_or_alias: str, *, limit: int = 100, order: str = "desc") -> list[Revision]:
        config = self.get_config(model_or_alias)
        revisionable_type = config.model_type if config else model_or_alias
        statement = select(Revision).where(Revision.revisionable_type == revisionable_type)
        statement = statement.order_by(desc(Revision.created_at) if order == "desc" else Revision.created_at).limit(limit)
        result = await db.execute(statement)
        return list(result.scalars().unique().all())

    async def count_history(self, db: AsyncSession, model_or_alias: str, model_id: str) -> int:
        config = self.get_config(model_or_alias)
        revisionable_type = config.model_type if config else model_or_alias
        return int(
            await db.scalar(
                select(func.count())
                .select_from(Revision)
                .where(Revision.revisionable_type == revisionable_type, Revision.revisionable_id == model_id)
            )
            or 0
        )

    async def get_revision(self, db: AsyncSession, revision_id: str) -> Revision | None:
        return await db.get(Revision, revision_id)

    async def delete_revision(self, db: AsyncSession, revision: Revision) -> None:
        await db.delete(revision)
        await db.commit()

    async def restore_revision(self, db: AsyncSession, revision: Revision, *, to: str = "old") -> Any | None:
        model = await self.history_of(db, revision)
        if not model or not hasattr(model, revision.key):
            return None
        raw_value = revision.old_value if to == "old" else revision.new_value
        setattr(model, revision.key, self._cast_restore_value(model, revision.key, raw_value))
        await db.commit()
        await db.refresh(model)
        await hooks.do_action_async(REVISION_ACTION_RESTORED, revision, model)
        return model

    async def history_of(self, db: AsyncSession, revision: Revision) -> Any | None:
        config = self.get_config(revision.revisionable_type)
        model_class = config.model if config else self._import_model(revision.revisionable_type)
        if not model_class:
            return None
        return await db.get(model_class, revision.revisionable_id)

    async def payload(self, revision: Revision) -> dict[str, Any]:
        config = self.get_config(revision.revisionable_type)
        field_name = self.field_name(revision.key, config)
        old_value = await self.format_value(revision.key, revision.old_value, config)
        new_value = await self.format_value(revision.key, revision.new_value, config)
        data = {
            "id": revision.id,
            "revisionableType": revision.revisionable_type,
            "revisionableAlias": config.alias if config else revision.revisionable_type,
            "revisionableId": revision.revisionable_id,
            "userId": revision.user_id,
            "author": revision.user.name if revision.user else "N/A",
            "key": revision.key,
            "field": field_name,
            "oldValue": old_value,
            "newValue": new_value,
            "createdAt": revision.created_at.isoformat() if revision.created_at else None,
            "updatedAt": revision.updated_at.isoformat() if revision.updated_at else None,
        }
        return await hooks.apply_filters_async(REVISION_FILTER_PAYLOAD, data, revision)

    async def history_payload(self, revisions: list[Revision]) -> list[dict[str, Any]]:
        return [await self.payload(revision) for revision in revisions]

    def form_tab_payload(self, model: Any) -> dict[str, Any]:
        config = self.get_config(model)
        return {
            "id": "revisions",
            "label": "Revision",
            "supported": bool(config and config.enabled and getattr(model, "id", None)),
            "historyUrl": f"/api/admin/revisions/{config.alias}/{model.id}" if config else "",
            "assets": {
                "styles": ["vendor/core/packages/revision/css/revision.css"],
                "scripts": ["vendor/core/packages/revision/js/html-diff.js", "vendor/core/packages/revision/js/revision.js"],
            },
            "columns": ["author", "field", "oldValue", "newValue", "createdAt"],
        }

    def field_name(self, key: str, config: RevisionModelConfig | None = None) -> str:
        if config and key in config.formatted_field_names:
            return config.formatted_field_names[key]
        if key.endswith("_id"):
            key = key[:-3]
        return key.replace("_", " ").title()

    async def format_value(self, key: str, value: Any, config: RevisionModelConfig | None = None) -> str | None:
        formatted = FieldFormatter.format(key, value, config.formatted_fields if config else {})
        return await hooks.apply_filters_async(REVISION_FILTER_FORMAT_VALUE, formatted, key, value, config)

    async def _cleanup(self, db: AsyncSession, config: RevisionModelConfig, model_id: str, *, incoming: int) -> None:
        total = int(
            await db.scalar(
                select(func.count())
                .select_from(Revision)
                .where(Revision.revisionable_type == config.model_type, Revision.revisionable_id == model_id)
            )
            or 0
        )
        overflow = total + incoming - config.history_limit
        if overflow <= 0:
            return

        result = await db.execute(
            select(Revision.id)
            .where(Revision.revisionable_type == config.model_type, Revision.revisionable_id == model_id)
            .order_by(Revision.created_at)
            .limit(overflow)
        )
        ids = [row[0] for row in result.fetchall()]
        if ids:
            await db.execute(delete(Revision).where(Revision.id.in_(ids)))

    def _serialize(self, value: Any) -> str | None:
        return FieldFormatter.stringify(value) if value is not None else None

    def _cast_restore_value(self, model: Any, key: str, value: str | None) -> Any:
        if value is None:
            return None

        column = model.__table__.columns.get(key)
        if column is None:
            return value

        try:
            python_type = column.type.python_type
        except NotImplementedError:
            return value

        if python_type is bool:
            return str(value).lower() in {"1", "true", "yes", "published"}
        if python_type is datetime:
            return datetime.fromisoformat(value)
        try:
            return python_type(value)
        except (TypeError, ValueError):
            return value

    def _import_model(self, model_type: str) -> type | None:
        try:
            module_name, class_name = model_type.rsplit(".", 1)
            return getattr(import_module(module_name), class_name)
        except Exception:
            return None


revision_service = RevisionService()


def boot_revision_package() -> None:
    revision_service.boot()
