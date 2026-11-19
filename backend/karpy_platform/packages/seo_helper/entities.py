from __future__ import annotations

import html
import re
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any


def clean_text(value: Any, max_length: int | None = None) -> str:
    text = re.sub(r"\[[^\]]+\]", "", str(value or ""))
    text = re.sub(r"<[^>]+>", "", text)
    text = " ".join(html.unescape(text).split())
    if max_length and len(text) > max_length:
        return text[: max_length - 1].rstrip() + "..."
    return text


@dataclass
class MetaTag:
    name: str
    content: str
    name_property: str = "name"
    prefix: str = ""

    link_names = {
        "alternate",
        "archives",
        "author",
        "canonical",
        "first",
        "help",
        "icon",
        "index",
        "last",
        "license",
        "next",
        "nofollow",
        "noreferrer",
        "pingback",
        "prefetch",
        "prev",
        "publisher",
    }

    def is_valid(self) -> bool:
        return bool(str(self.content or "").strip())

    @property
    def key(self) -> str:
        return self.name

    def render(self) -> str:
        if not self.is_valid():
            return ""
        name = html.escape(str(self.name), quote=True)
        content = html.escape(str(self.content), quote=True)
        if self.name in self.link_names:
            return f'<link rel="{name}" href="{content}">'
        name_property = html.escape(self.name_property, quote=True)
        prefixed = html.escape(f"{self.prefix}{self.name}", quote=True)
        return f'<meta {name_property}="{prefixed}" content="{content}">'


class MetaCollection:
    def __init__(self, prefix: str = "", name_property: str = "name", ignored: set[str] | None = None) -> None:
        self.prefix = prefix
        self.name_property = name_property
        self.ignored = ignored or set()
        self.items: OrderedDict[str, MetaTag] = OrderedDict()

    def add(self, name: str, content: Any) -> "MetaCollection":
        if name in self.ignored:
            return self
        tag = MetaTag(str(name).strip().replace(" ", "-"), str(content or "").strip(), self.name_property, self.prefix)
        if tag.is_valid():
            self.items[tag.key] = tag
        return self

    def add_many(self, values: dict[str, Any]) -> "MetaCollection":
        for name, content in values.items():
            self.add(name, content)
        return self

    def remove(self, names: str | list[str]) -> "MetaCollection":
        for name in ([names] if isinstance(names, str) else names):
            self.items.pop(str(name).strip().lower(), None)
        return self

    def has(self, name: str) -> bool:
        return name in self.items

    def get(self, name: str) -> str | None:
        tag = self.items.get(name)
        return tag.content if tag else None

    def render(self) -> str:
        return "\n".join(filter(None, [tag.render() for tag in self.items.values()]))

    def to_dict(self) -> dict[str, str]:
        return {key: tag.content for key, tag in self.items.items()}


class SeoTitle:
    def __init__(self, title: str | None = "", site_name: str = "", separator: str = "-", first: bool = True, max_length: int = 120) -> None:
        self.title = title or ""
        self.site_name = site_name or ""
        self.separator = separator or "-"
        self.first = first
        self.max_length = max_length

    def set(self, title: str | None, site_name: str | None = None, separator: str | None = None) -> "SeoTitle":
        if title is not None:
            self.title = clean_text(title)
        if site_name is not None:
            self.site_name = clean_text(site_name)
        if separator is not None:
            self.separator = separator.strip() or "-"
        return self

    def get_title_only(self) -> str:
        return self.title

    def get(self) -> str:
        parts = []
        if self.first:
            parts = [self.title, self.site_name]
        else:
            parts = [self.site_name, self.title]
        parts = [part for part in parts if part]
        return clean_text(f" {self.separator} ".join(dict.fromkeys(parts)), self.max_length)

    def render(self) -> str:
        return f"<title>{html.escape(self.get())}</title>" if self.get() else ""


class SeoDescription:
    def __init__(self, content: str | None = "", max_length: int = 386) -> None:
        self.content = clean_text(content)
        self.max_length = max_length

    def set(self, content: str | None) -> "SeoDescription":
        if content:
            self.content = clean_text(content)
        return self

    def get(self) -> str:
        return clean_text(self.content, self.max_length)

    def render(self) -> str:
        description = self.get()
        return MetaTag("description", description).render() if description else ""


class SeoOpenGraph:
    def __init__(self, site_name: str = "", prefix: str = "og:") -> None:
        self.meta = MetaCollection(prefix=prefix, name_property="property")
        if site_name:
            self.set_site_name(site_name)
        self.set_type("website")

    def add_property(self, name: str, content: Any) -> "SeoOpenGraph":
        self.meta.add(name, content)
        return self

    def add_properties(self, values: dict[str, Any]) -> "SeoOpenGraph":
        self.meta.add_many(values)
        return self

    def set_type(self, value: str) -> "SeoOpenGraph":
        return self.add_property("type", value)

    def set_title(self, value: str | None) -> "SeoOpenGraph":
        return self.add_property("title", clean_text(value, 120))

    def set_description(self, value: str | None) -> "SeoOpenGraph":
        return self.add_property("description", clean_text(value, 250))

    def set_url(self, value: str | None) -> "SeoOpenGraph":
        return self.add_property("url", value)

    def set_site_name(self, value: str | None) -> "SeoOpenGraph":
        return self.add_property("site_name", value)

    def set_image(self, value: str | None) -> "SeoOpenGraph":
        return self.add_property("image", value)

    def has_image(self) -> bool:
        return self.meta.has("image")

    def render(self) -> str:
        return self.meta.render()

    def to_dict(self) -> dict[str, str]:
        return self.meta.to_dict()


class SeoTwitter:
    supported_types = {"app", "gallery", "photo", "player", "product", "summary", "summary_large_image"}

    def __init__(self, card: str = "summary") -> None:
        self.meta = MetaCollection(prefix="twitter:")
        self.images: list[str] = []
        self.set_type(card)

    def set_type(self, value: str) -> "SeoTwitter":
        value = (value or "summary").strip().lower()
        if value not in self.supported_types:
            value = "summary"
        return self.add_meta("card", value)

    def set_site(self, value: str | None) -> "SeoTwitter":
        if value:
            value = value if value.startswith("@") else f"@{value}"
        return self.add_meta("site", value)

    def set_title(self, value: str | None) -> "SeoTwitter":
        return self.add_meta("title", clean_text(value, 120))

    def set_description(self, value: str | None) -> "SeoTwitter":
        return self.add_meta("description", clean_text(value, 250))

    def add_image(self, value: str | None) -> "SeoTwitter":
        if value and len(self.images) < 4:
            self.images.append(value)
        return self

    def add_meta(self, name: str, content: Any) -> "SeoTwitter":
        self.meta.add(name, content)
        return self

    def add_metas(self, values: dict[str, Any]) -> "SeoTwitter":
        self.meta.add_many(values)
        return self

    def render(self) -> str:
        if len(self.images) == 1:
            self.meta.add("image", self.images[0])
        elif len(self.images) > 1:
            for index, image in enumerate(self.images):
                self.meta.add(f"image{index}", image)
        return self.meta.render()

    def to_dict(self) -> dict[str, str]:
        return self.meta.to_dict()
