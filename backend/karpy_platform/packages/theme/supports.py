from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from html import escape
from typing import Any
from urllib.parse import quote_plus

from karpy_platform.core.icon.manager import icon_manager


@dataclass
class SocialLink:
    name: str
    url: str
    icon: str = ""
    image: str = ""
    color: str = ""
    background_color: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "name": self.name,
            "url": self.url,
            "icon": self.icon,
            "image": self.image,
            "color": self.color,
            "backgroundColor": self.background_color,
        }


def normalize_repeater(value: Any) -> list[dict[str, Any]]:
    if not value:
        return []
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return []
    if not isinstance(value, list):
        return []
    rows = []
    for item in value:
        if isinstance(item, dict):
            rows.append(item)
        elif isinstance(item, list):
            rows.append({entry.get("key"): entry.get("value") for entry in item if isinstance(entry, dict)})
    return rows


def social_links(value: Any) -> list[SocialLink]:
    links = []
    for item in normalize_repeater(value):
        name = item.get("name") or item.get("label") or item.get("social-name") or ""
        url = item.get("url") or item.get("social-url") or ""
        if not name or not url:
            continue
        links.append(
            SocialLink(
                name=name,
                url=url,
                icon=item.get("icon") or item.get("social-icon") or "",
                image=item.get("image") or item.get("social-image") or "",
                color=item.get("color") or "",
                background_color=item.get("background_color") or item.get("background-color") or "",
            )
        )
    return links


def social_sharing_buttons(value: Any, url: str, title: str, thumbnail: str | None = None) -> list[dict[str, str]]:
    defaults = [
        {"social": "facebook", "icon": "facebook"},
        {"social": "x", "icon": "twitter"},
        {"social": "linkedin", "icon": "linkedin"},
        {"social": "email", "icon": "mail"},
    ]
    rows = normalize_repeater(value) or defaults
    encoded_url = quote_plus(url)
    encoded_title = quote_plus(title)
    buttons = []
    for item in rows:
        social = item.get("social")
        if not social:
            continue
        share_url = {
            "facebook": f"https://www.facebook.com/sharer.php?u={encoded_url}",
            "x": f"https://x.com/intent/tweet?url={encoded_url}&text={encoded_title}",
            "twitter": f"https://x.com/intent/tweet?url={encoded_url}&text={encoded_title}",
            "linkedin": f"https://www.linkedin.com/sharing/share-offsite/?url={encoded_url}",
            "pinterest": f"https://pinterest.com/pin/create/button/?url={encoded_url}&description={encoded_title}&media={quote_plus(thumbnail or '')}",
            "whatsapp": f"https://api.whatsapp.com/send?text={encoded_title}%20{encoded_url}",
            "telegram": f"https://t.me/share/url?url={encoded_url}&text={encoded_title}",
            "email": f"mailto:?subject={encoded_title}&body={encoded_url}",
        }.get(social, url)
        buttons.append(
            {
                "name": social.replace("-", " ").title(),
                "url": share_url,
                "icon": item.get("icon", ""),
                "image": item.get("icon_image", ""),
                "color": item.get("color", ""),
                "backgroundColor": item.get("background_color", ""),
            }
        )
    return buttons


def render_social_sharing(buttons: list[dict[str, str]]) -> str:
    if not buttons:
        return ""
    items = []
    for button in buttons:
        style = []
        if button.get("color"):
            style.append(f"color:{escape(button['color'], quote=True)}")
        if button.get("backgroundColor"):
            style.append(f"background-color:{escape(button['backgroundColor'], quote=True)}")
        label = escape(button["name"])
        icon_html = ""
        icon_name = button.get("icon", "")
        if icon_name:
            try:
                icon_html = icon_manager.component(icon_name, attributes={"aria-hidden": "true"})
            except Exception:
                icon_html = ""
        if not icon_html and button.get("image"):
            icon_html = f'<img src="{escape(button["image"], quote=True)}" alt="" aria-hidden="true">'
        items.append(
            f'<a class="karpy-share" href="{escape(button["url"], quote=True)}" target="_blank" rel="nofollow noopener" style="{";".join(style)}">{icon_html}<span>{label}</span></a>'
        )
    return '<nav class="karpy-social-sharing">' + "".join(items) + "</nav>"


def format_date(value: datetime | date | str | int | None, fmt: str = "M d, Y") -> str:
    if value is None:
        return ""
    if isinstance(value, (int, float)):
        value = datetime.fromtimestamp(value)
    if isinstance(value, str):
        return value
    mapping = {
        "M d, Y": "%b %d, %Y",
        "F j, Y": "%B %-d, %Y",
        "Y-m-d": "%Y-%m-%d",
        "d/m/Y": "%d/%m/%Y",
    }
    return value.strftime(mapping.get(fmt, "%b %d, %Y")).replace(" 0", " ")
