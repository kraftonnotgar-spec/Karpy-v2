"""Shortcodes registered by the Contact plugin."""

from __future__ import annotations

import asyncio
import threading
from typing import Any

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import settings
from app.database import async_session
from karpy_platform.plugins.contact.models.contact import ContactCustomField
from karpy_platform.plugins.contact.routes import _published_fields
from karpy_platform.plugins.contact.services.contact import render_contact_form


def contact_shortcode_config(attributes: dict[str, Any], content: str | None = None) -> dict[str, Any]:
    return {
        "title": "Contact form",
        "fields": [
            {
                "key": "display_fields",
                "label": "Display fields",
                "type": "checklist",
                "choices": {"phone": "Phone", "email": "Email", "subject": "Subject", "address": "Address"},
                "default": ["phone", "email", "subject", "address"],
                "description": "Choose optional contact fields shown beside the always-required Name and Message fields.",
            },
            {
                "key": "mandatory_fields",
                "label": "Mandatory fields",
                "type": "checklist",
                "choices": {"phone": "Phone", "email": "Email", "subject": "Subject", "address": "Address"},
                "default": ["email"],
                "description": "If left blank, these fields will be validated by default configuration. Name and Message are always mandatory.",
            },
            {"key": "image", "label": "Image", "type": "media"},
            {"key": "show_information_box", "label": "Show information box", "type": "switch", "default": "yes"},
            {"key": "information_box_title", "label": "Information box title", "type": "text", "default": "Contact Us"},
            {"key": "show_social_links", "label": "Show social links", "type": "switch", "default": "yes"},
        ],
        "attributes": attributes,
        "content": content,
    }


def render_contact_shortcode(shortcode, content: str | None = None) -> str:
    fields = _load_fields_sync()
    return render_contact_form(fields, shortcode.to_array())


def _load_fields_sync() -> list[ContactCustomField]:
    async def load() -> list[ContactCustomField]:
        async with async_session() as session:
            return await _published_fields(session)

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(load())

    if loop.is_running():
        return _load_fields_in_worker()
    return loop.run_until_complete(load())


def _load_fields_in_worker() -> list[ContactCustomField]:
    """Load contact custom fields while shortcode rendering runs inside an event loop."""
    result: dict[str, list[ContactCustomField] | BaseException] = {}

    async def load() -> list[ContactCustomField]:
        engine = create_async_engine(settings.DATABASE_URL, echo=False, future=True)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with session_factory() as session:
                fields = await _published_fields(session)
                for field in fields:
                    field.options = list(field.options or [])
                return fields
        finally:
            await engine.dispose()

    def runner() -> None:
        try:
            result["fields"] = asyncio.run(load())
        except BaseException as exc:
            result["error"] = exc

    thread = threading.Thread(target=runner, name="karpy-contact-shortcode-fields", daemon=True)
    thread.start()
    thread.join()
    error = result.get("error")
    if isinstance(error, BaseException):
        raise error
    return list(result.get("fields") or [])
