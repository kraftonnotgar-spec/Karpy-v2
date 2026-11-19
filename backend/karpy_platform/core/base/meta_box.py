from __future__ import annotations

from collections import defaultdict
from typing import Any, Callable

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from karpy_platform.core.base.hooks import hooks
from karpy_platform.core.base.models import MetaBox


class MetaBoxManager:
    """Botble-style meta box registry and storage helper."""

    def __init__(self) -> None:
        self._boxes: dict[str | None, dict[str, dict[str, dict[str, dict]]]] = defaultdict(
            lambda: defaultdict(lambda: defaultdict(dict))
        )

    def add_meta_box(
        self,
        box_id: str,
        title: str,
        callback: Callable | str,
        reference: str | None = None,
        context: str = "advanced",
        priority: str = "default",
        args: dict | None = None,
    ) -> None:
        self._boxes[reference][context][priority][box_id] = {
            "id": box_id,
            "title": title,
            "callback": callback,
            "args": args or {},
        }

    def remove_meta_box(self, box_id: str, reference: str | None, context: str) -> None:
        for priority in ("high", "core", "default", "low"):
            self._boxes[reference][context][priority].pop(box_id, None)

    def get_meta_boxes(self, reference: str | None = None, context: str | None = None) -> dict:
        boxes = self._boxes.get(reference, {})
        if context:
            return boxes.get(context, {})
        return boxes

    async def save_meta_data(
        self,
        db: AsyncSession,
        reference_id: str,
        reference_type: str,
        key: str,
        value: Any,
    ) -> MetaBox:
        key = hooks.apply_filters("stored_meta_box_key", key, reference_type)
        result = await db.execute(
            select(MetaBox).where(
                MetaBox.meta_key == key,
                MetaBox.reference_id == reference_id,
                MetaBox.reference_type == reference_type,
            )
        )
        meta = result.scalar_one_or_none()
        if not meta:
            meta = MetaBox(meta_key=key, reference_id=reference_id, reference_type=reference_type)
            db.add(meta)
        meta.meta_value = value if isinstance(value, list) else [value]
        await db.commit()
        await db.refresh(meta)
        return meta

    async def get_meta_data(
        self,
        db: AsyncSession,
        reference_id: str,
        reference_type: str,
        key: str,
        single: bool = False,
    ) -> Any:
        key = hooks.apply_filters("stored_meta_box_key", key, reference_type)
        result = await db.execute(
            select(MetaBox).where(
                MetaBox.meta_key == key,
                MetaBox.reference_id == reference_id,
                MetaBox.reference_type == reference_type,
            )
        )
        meta = result.scalar_one_or_none()
        if not meta:
            return "" if single else []
        values = meta.meta_value or []
        return values[0] if single and values else values

    async def delete_meta_data(
        self,
        db: AsyncSession,
        reference_id: str,
        reference_type: str,
        key: str,
    ) -> int:
        key = hooks.apply_filters("stored_meta_box_key", key, reference_type)
        result = await db.execute(
            delete(MetaBox).where(
                MetaBox.meta_key == key,
                MetaBox.reference_id == reference_id,
                MetaBox.reference_type == reference_type,
            )
        )
        await db.commit()
        return result.rowcount or 0


meta_box = MetaBoxManager()
