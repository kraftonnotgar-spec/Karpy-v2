"""Shortcodes registered by the FAQ plugin."""

from __future__ import annotations

import asyncio
import threading
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.database import async_session
from karpy_platform.plugins.faq.models.faq import Faq, FaqCategory
from karpy_platform.plugins.faq.services.faq import render_faq_block


def faq_shortcode_config(attributes: dict[str, Any], content: str | None = None) -> dict[str, Any]:
    categories = _load_categories_sync()
    choices = [{"value": "", "label": "All categories"}] + [{"value": category.slug or category.id, "label": category.name} for category in categories]
    return {
        "title": "FAQs",
        "fields": [
            {"key": "title", "label": "Title", "type": "text", "default": "Frequently Asked Questions"},
            {"key": "subtitle", "label": "Subtitle", "type": "textarea", "default": ""},
            {"key": "category", "label": "Category", "type": "select", "default": "", "options": choices},
            {
                "key": "style",
                "label": "Style",
                "type": "select",
                "default": "accordion",
                "options": [{"value": "accordion", "label": "Accordion"}, {"value": "grid", "label": "Grid"}],
            },
            {"key": "limit", "label": "Limit", "type": "number", "default": "10"},
            {"key": "open_first", "label": "Open first question", "type": "switch", "default": "yes"},
        ],
        "attributes": attributes,
        "content": content,
    }


def render_faq_shortcode(shortcode, content: str | None = None) -> str:
    attrs = shortcode.to_array()
    return render_faq_block(_load_faqs_sync(attrs), attrs)


def _load_categories_sync() -> list[FaqCategory]:
    async def load() -> list[FaqCategory]:
        async with async_session() as session:
            result = await session.execute(
                select(FaqCategory)
                .where(FaqCategory.is_deleted.is_(False), FaqCategory.status == "published")
                .order_by(FaqCategory.order.asc(), FaqCategory.name.asc())
            )
            return list(result.scalars().all())

    return _run_sync(load)


def _load_faqs_sync(attributes: dict[str, Any]) -> list[Faq]:
    async def load() -> list[Faq]:
        async with async_session() as session:
            return await _query_faqs(session, attributes)

    return _run_sync(load)


async def _query_faqs(session, attributes: dict[str, Any]) -> list[Faq]:
    filters = [Faq.is_deleted.is_(False), Faq.status == "published", FaqCategory.is_deleted.is_(False), FaqCategory.status == "published"]
    category = str(attributes.get("category") or attributes.get("category_slug") or attributes.get("category_id") or "").strip()
    if category:
        filters.append((FaqCategory.slug == category) | (FaqCategory.id == category))
    try:
        limit = max(1, min(int(attributes.get("limit") or 10), 100))
    except (TypeError, ValueError):
        limit = 10
    result = await session.execute(
        select(Faq)
        .join(FaqCategory, Faq.category_id == FaqCategory.id)
        .options(selectinload(Faq.category))
        .where(*filters)
        .order_by(FaqCategory.order.asc(), Faq.order.asc(), Faq.created_at.desc())
        .limit(limit)
    )
    return list(result.scalars().unique().all())


def _run_sync(factory):
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(factory())
    if loop.is_running():
        return _run_in_worker(factory)
    return loop.run_until_complete(factory())


def _run_in_worker(factory):
    result: dict[str, Any] = {}

    def runner() -> None:
        try:
            result["value"] = asyncio.run(factory())
        except BaseException as exc:
            result["error"] = exc

    thread = threading.Thread(target=runner, name="karpy-faq-shortcode-loader", daemon=True)
    thread.start()
    thread.join()
    error = result.get("error")
    if isinstance(error, BaseException):
        raise error
    return result.get("value") or []
