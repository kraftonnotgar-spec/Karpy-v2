"""FAQ plugin serializers, validation helpers, and shortcode rendering."""

from __future__ import annotations

import html
import re
from datetime import datetime
from typing import Any

from karpy_platform.plugins.faq.models.faq import Faq, FaqCategory

FAQ_STATUSES = {"published", "draft", "pending", "disabled"}


def iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def slugify(value: str) -> str:
    text = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
    return text or "faq"


def normalize_status(value: str | None) -> str:
    status = str(value or "published").strip().lower()
    if status not in FAQ_STATUSES:
        raise ValueError("Unsupported status.")
    return status


def serialize_category(category: FaqCategory, *, include_count: bool = False) -> dict[str, Any]:
    payload = {
        "id": category.id,
        "name": category.name,
        "slug": category.slug or "",
        "description": category.description or "",
        "parentId": category.parent_id or "",
        "parentName": category.parent.name if category.parent else "",
        "order": category.order,
        "status": category.status,
        "createdAt": iso(category.created_at),
        "updatedAt": iso(category.updated_at),
    }
    if include_count:
        payload["faqCount"] = len([faq for faq in category.faqs or [] if not faq.is_deleted])
        payload["childrenCount"] = len([child for child in category.children or [] if not child.is_deleted])
    return payload


def serialize_faq(faq: Faq) -> dict[str, Any]:
    return {
        "id": faq.id,
        "categoryId": faq.category_id,
        "categoryName": faq.category.name if faq.category else "",
        "question": faq.question,
        "answer": faq.answer,
        "order": faq.order,
        "status": faq.status,
        "createdAt": iso(faq.created_at),
        "updatedAt": iso(faq.updated_at),
    }


def render_faq_block(faqs: list[Faq], attributes: dict[str, Any] | None = None) -> str:
    attrs = attributes or {}
    title = str(attrs.get("title") or "Frequently Asked Questions").strip()
    subtitle = str(attrs.get("subtitle") or "").strip()
    style = str(attrs.get("style") or "accordion").strip().lower()
    open_first = str(attrs.get("open_first") or "yes").lower() in {"1", "true", "yes", "on"}
    class_name = "karpy-faq-block is-grid" if style == "grid" else "karpy-faq-block"
    pieces = [
        '<section class="' + class_name + '" data-karpy-faq-block="true">',
        '<div class="karpy-faq-head">',
        f"<h2>{html.escape(title)}</h2>",
    ]
    if subtitle:
        pieces.append(f"<p>{html.escape(subtitle)}</p>")
    pieces.append("</div>")
    if not faqs:
        pieces.append('<div class="karpy-faq-empty">No FAQs are available yet.</div>')
    else:
        pieces.append('<div class="karpy-faq-items">')
        for index, faq in enumerate(faqs):
            open_attr = " open" if open_first and index == 0 and style != "grid" else ""
            answer = faq.answer or ""
            if style == "grid":
                pieces.append(
                    '<article class="karpy-faq-card">'
                    f"<h3>{html.escape(faq.question)}</h3>"
                    f'<div class="karpy-faq-answer">{answer}</div>'
                    "</article>"
                )
            else:
                pieces.append(
                    f'<details class="karpy-faq-item"{open_attr}>'
                    f"<summary>{html.escape(faq.question)}</summary>"
                    f'<div class="karpy-faq-answer">{answer}</div>'
                    "</details>"
                )
        pieces.append("</div>")
    pieces.append("</section>")
    return "\n".join(pieces)
