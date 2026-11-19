"""
KARPy CMS - Shortcode engine.

Python port of Botble's shortcode registry/compiler. It supports registered
blocks such as [gallery ids="1,2"] and turns them into rendered HTML or frontend
component placeholders.
"""

from __future__ import annotations

import html
import inspect
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from karpy_platform.core.base.hooks import hooks
from karpy_platform.packages.shortcode.constants import (
    SHORTCODE_ACTION_ADMIN_CONFIG_RENDERING,
    SHORTCODE_ACTION_RENDERED,
    SHORTCODE_FILTER_CONTENT_COMPILED,
    SHORTCODE_FILTER_GET_CALLBACK,
    SHORTCODE_REGISTER_CONTENT_IN_ADMIN,
)

logger = logging.getLogger("karpy.shortcode")


@dataclass
class ParsedShortcode:
    """Parsed shortcode value passed into callbacks."""

    name: str
    attributes: dict[str, Any] = field(default_factory=dict)
    content: str | None = None

    def get(self, key: str, default: Any = "") -> Any:
        return self.attributes.get(key, default)

    def attribute(self, key: str, fallback: Any = None) -> str:
        value = self.attributes.get(key, fallback)
        if value in {None, ""}:
            return ""
        return f'{key}="{html.escape(str(value), quote=True)}"'

    def to_array(self) -> dict[str, Any]:
        return dict(self.attributes)

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "attributes": self.to_array(), "content": self.content}

    def html_attributes(self) -> str:
        attributes = {"data-block-id": self.name}
        styles = []
        if background_color := self.get("background_color"):
            styles.append(f"--block-{self.name}-background-color: {background_color}; background-color: var(--block-{self.name}-background-color) !important;")
        if background_image := self.get("background_image"):
            styles.append(f"--block-{self.name}-background-image: url({background_image}); background-image: var(--block-{self.name}-background-image) !important; background-size: cover;")
        if text_color := self.get("text_color"):
            styles.append(f"--block-{self.name}-color: {text_color}; color: var(--block-{self.name}-color) !important;")
        if custom_css := self.get("custom_css"):
            styles.append(str(custom_css))
        if styles:
            attributes["style"] = " ".join(styles)
        return " ".join(f'{key}="{html.escape(str(value), quote=True)}"' for key, value in attributes.items())

    def __getattr__(self, key: str) -> Any:
        return self.attributes.get(key)

    def __setattr__(self, key: str, value: Any) -> None:
        if key in {"name", "attributes", "content"}:
            super().__setattr__(key, value)
        else:
            self.attributes[key] = value


@dataclass
class ShortcodeDefinition:
    key: str
    name: str | None
    description: str | None = ""
    callback: Callable | str | list[Any] | None = None
    preview_image: str = ""
    admin_config: str | dict[str, Any] | Callable | None = None
    admin_config_modifier: Callable | None = None
    category: str = "General"
    fields: list[dict[str, Any]] = field(default_factory=list)

    def public_payload(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "name": self.name,
            "description": self.description,
            "preview_image": self.preview_image,
            "previewImage": self.preview_image,
            "admin_config": self.admin_config if not callable(self.admin_config) else None,
            "adminConfig": self.admin_config if not callable(self.admin_config) else None,
            "category": self.category,
            "fields": self.fields,
        }


class ShortcodeField:
    """Helpers equivalent to Botble's ShortcodeField utility."""

    @staticmethod
    def parse_ids(value: str | None) -> list[str]:
        if not value:
            return []
        return [item.strip() for item in str(value).split(",") if item.strip()]

    def get_ids(self, field: str, shortcode: ParsedShortcode) -> list[str]:
        return self.parse_ids(shortcode.get(field))

    def get_tabs_data(self, fields: list[str], shortcode: ParsedShortcode, key: str | None = None) -> list[dict[str, Any]]:
        quantity_key = f"{key}_quantity" if key else "quantity"
        try:
            quantity = min(int(str(shortcode.get(quantity_key, 0)).split(",")[-1]), 20)
        except ValueError:
            quantity = 0
        rows = []
        for index in range(1, quantity + 1):
            row = {}
            for field_name in fields:
                attr = f"{key}_{field_name}_{index}" if key else f"{field_name}_{index}"
                row[field_name] = shortcode.get(attr)
            if any(value is not None for value in row.values()):
                rows.append(row)
        return rows

    def tabs_schema(self, fields: list[dict[str, Any]], *, max_items: int = 20, min_items: int = 1, key: str | None = None) -> dict[str, Any]:
        return {"type": "tabs", "fields": fields, "max": max_items, "min": min_items, "key": key}

    def lazy_loading_schema(self) -> dict[str, Any]:
        return {"key": "enable_lazy_loading", "label": "Lazy loading", "type": "switch", "default": "no"}


class ShortcodeCompiler:
    def __init__(self) -> None:
        self._registered: dict[str, ShortcodeDefinition] = {}
        self._enabled = True
        self._strip = False
        self._edit_link: str | None = None
        self._ignored_caches: set[str] = set()
        self._ignored_lazy_loading: set[str] = set()
        self._loading_states: dict[str, str] = {}
        self._cache: dict[str, tuple[float, str]] = {}
        self.cache_enabled = False
        self.cache_ttl = 1800
        self.performance_log_threshold = 0.5

    def register(
        self,
        key: str,
        name: str | None,
        description: str | None = "",
        callback: Callable | str | list[Any] | None = None,
        preview_image: str = "",
        admin_config: str | dict[str, Any] | Callable | None = None,
        category: str = "General",
        fields: list[dict[str, Any]] | None = None,
    ) -> "ShortcodeCompiler":
        self._registered[key] = ShortcodeDefinition(
            key=key,
            name=name,
            description=description,
            callback=callback,
            preview_image=preview_image,
            admin_config=admin_config,
            category=category,
            fields=fields or [],
        )
        return self

    add = register

    def remove(self, key: str) -> None:
        self._registered.pop(key, None)

    def has(self, key: str) -> bool:
        return key in self._registered

    def has_shortcode(self, key: str) -> bool:
        return self.has(key)

    def has_shortcodes(self) -> bool:
        return bool(self._registered)

    def get_all(self) -> dict[str, dict[str, Any]]:
        return {key: definition.public_payload() for key, definition in sorted(self._registered.items())}

    def get_registered(self) -> dict[str, ShortcodeDefinition]:
        return dict(self._registered)

    def set_preview_image(self, key: str, preview_image: str) -> "ShortcodeCompiler":
        if key in self._registered:
            self._registered[key].preview_image = preview_image
        return self

    def set_admin_config(self, key: str, config: str | dict[str, Any] | Callable | None) -> None:
        if key in self._registered:
            self._registered[key].admin_config = config

    def modify_admin_config(self, key: str, callback: Callable) -> None:
        if key in self._registered:
            self._registered[key].admin_config_modifier = callback

    def enable(self) -> "ShortcodeCompiler":
        self._enabled = True
        return self

    def disable(self) -> "ShortcodeCompiler":
        self._enabled = False
        return self

    def set_edit_link(self, edit_link: str) -> None:
        self._edit_link = edit_link

    def get_edit_link(self) -> str | None:
        return self._edit_link

    def ignore_caches(self, shortcodes: list[str]) -> None:
        self._ignored_caches.update(shortcodes)

    def ignore_lazy_loading(self, shortcodes: list[str]) -> None:
        self._ignored_lazy_loading.update(shortcodes)

    def register_loading_state(self, shortcode_name: str, view: str) -> None:
        self._loading_states[shortcode_name] = view

    def fields(self) -> ShortcodeField:
        return ShortcodeField()

    def compile(self, content: str | None, force: bool = False) -> str:
        if not content:
            return ""
        if (not self._enabled or not self.has_shortcodes()) and not force:
            return content

        escaped: dict[str, str] = {}

        def protect_escaped(match: re.Match) -> str:
            if match.group(1) == "[" and match.group(6) == "]":
                token = f"@@KARPY_ESCAPED_SHORTCODE_{len(escaped)}@@"
                escaped[token] = match.group(0)[1:-1]
                return token
            return match.group(0)

        previous = None
        result = re.sub(self._get_regex(), protect_escaped, str(content), flags=re.DOTALL)
        passes = 0
        while previous != result and passes < 10:
            previous = result
            result = re.sub(self._get_regex(), self._render_match, result, flags=re.DOTALL)
            passes += 1
        for token, value in escaped.items():
            result = result.replace(token, value)
        return result

    def strip(self, content: str | None, except_shortcodes: list[str] | None = None) -> str:
        if not content or not self.has_shortcodes():
            return content or ""
        return re.sub(self._get_regex(except_shortcodes or []), self._strip_tag, content, flags=re.DOTALL)

    def generate_shortcode(
        self,
        name: str,
        attributes: dict[str, Any] | None = None,
        content: str | None = None,
        lazy: bool = False,
    ) -> str:
        attributes = dict(attributes or {})
        if lazy:
            attributes["enable_lazy_loading"] = "yes"
        attr_str = ""
        for key, value in attributes.items():
            value = str(value).replace("\r\n", "{{NEWLINE}}").replace("\n", "{{NEWLINE}}").replace("\r", "{{NEWLINE}}")
            attr_str += f' {key}="{html.escape(value, quote=True)}"'
        if content is None:
            content = ""
        return f"[{name}{attr_str}]{content}[/{name}]"

    def get_attributes(self, value: str) -> dict[str, Any]:
        match = re.search(self._get_regex(), html.unescape(value or ""), flags=re.DOTALL)
        if not match:
            return {}
        return self._parse_attributes(match.group(3) or "")

    def get_content(self, value: str) -> str | None:
        match = re.search(self._get_regex(), html.unescape(value or ""), flags=re.DOTALL)
        if not match:
            return None
        return match.group(5)

    def admin_config(self, key: str, code: str | None = None) -> dict[str, Any]:
        hooks.do_action(SHORTCODE_ACTION_ADMIN_CONFIG_RENDERING)
        definition = self._registered.get(key)
        if not definition:
            return {"key": key, "config": None, "attributes": {}, "content": None}

        attributes = self.get_attributes(code) if code else {}
        content = self.get_content(code) if code else None
        config = definition.admin_config
        if callable(config):
            config = self._call_admin_config(config, attributes, content)
        if definition.admin_config_modifier:
            config = definition.admin_config_modifier(config, attributes, content)
        if not config:
            config = {"code": self.generate_shortcode(key, attributes, content)}
        config = hooks.apply_filters(SHORTCODE_REGISTER_CONTENT_IN_ADMIN, config, key, attributes)
        return {"key": key, "config": config, "attributes": attributes, "content": content}

    def render_ui_block(self, name: str, attributes: dict[str, Any] | None = None) -> str | None:
        if name not in self._registered:
            return None
        code = self.generate_shortcode(name, attributes or {})
        cache_key = f"{name}:{repr(sorted((attributes or {}).items()))}"
        if self.cache_enabled and name not in self._ignored_caches:
            cached = self._cache.get(cache_key)
            if cached and cached[0] > time.time():
                return cached[1]
        rendered = self.compile(code, force=True)
        if self.cache_enabled and name not in self._ignored_caches and not self._contains_form_elements(rendered):
            self._cache[cache_key] = (time.time() + self.cache_ttl, rendered)
        return rendered

    def whitelist_shortcodes(self) -> list[str]:
        return hooks.apply_filters("core_whitelist_shortcodes", ["media", "youtube-video"])

    def _render_match(self, match: re.Match) -> str:
        if match.group(1) == "[" and match.group(6) == "]":
            return match.group(0)[1:-1]

        name = match.group(2)
        if name not in self._registered:
            return match.group(0)

        attributes = self._parse_attributes(match.group(3) or "")
        content = self.compile(match.group(5), force=True) if match.group(5) is not None else None
        shortcode = ParsedShortcode(name=name, attributes=attributes, content=content)

        if shortcode.get("enable_lazy_loading") == "yes" and name not in self._ignored_lazy_loading:
            return self._lazy_placeholder(shortcode)

        callback = hooks.apply_filters(SHORTCODE_FILTER_GET_CALLBACK, self._registered[name].callback, name)
        if not callback:
            return match.group(0)

        started = time.perf_counter()
        try:
            rendered = self._call_callback(callback, shortcode, content, name)
            rendered = hooks.apply_filters(SHORTCODE_FILTER_CONTENT_COMPILED, rendered, name, callback, self)
            hooks.do_action(SHORTCODE_ACTION_RENDERED, shortcode, rendered)
            elapsed = time.perf_counter() - started
            if elapsed > self.performance_log_threshold:
                logger.warning("Shortcode [%s] rendered slowly in %.3fs", name, elapsed)
            return "" if rendered is None else str(rendered)
        except Exception as exception:
            logger.exception("Shortcode [%s] failed", name)
            return f"<!-- Shortcode error [{html.escape(name)}]: {html.escape(str(exception))} -->"

    def _call_callback(self, callback: Callable | str | list[Any], shortcode: ParsedShortcode, content: str | None, name: str) -> Any:
        if isinstance(callback, str):
            raise TypeError(f"String callbacks are not importable yet: {callback}")
        if isinstance(callback, list) and len(callback) == 2:
            callback = getattr(callback[0], callback[1])
        if not callable(callback):
            return None
        parameters = inspect.signature(callback).parameters
        argc = len(parameters)
        if argc >= 4:
            return callback(shortcode, content, self, name)
        if argc == 3:
            return callback(shortcode, content, self)
        if argc == 2:
            return callback(shortcode, content)
        if argc == 1:
            return callback(shortcode)
        return callback()

    def _call_admin_config(self, callback: Callable, attributes: dict[str, Any], content: str | None) -> Any:
        argc = len(inspect.signature(callback).parameters)
        if argc >= 2:
            return callback(attributes, content)
        if argc == 1:
            return callback(attributes)
        return callback()

    def _parse_attributes(self, text: str) -> dict[str, Any]:
        text = html.unescape(text or "")
        text = re.sub(r"[\u00a0\u200b]+", " ", text)
        attributes: dict[str, Any] = {}
        pattern = (
            r'(\w+)\s*=\s*"([^"]*)"(?:\s|$)'
            r"|(\w+)\s*=\s*'([^']*)'(?:\s|$)"
            r"|(\w+)\s*=\s*([^\s'\"]+)(?:\s|$)"
            r'|"([^"]*)"(?:\s|$)'
            r"|(\S+)(?:\s|$)"
        )
        positional = 0
        for match in re.finditer(pattern, text.strip()):
            if match.group(1):
                attributes[match.group(1).lower()] = self._decode_attribute_value(match.group(2))
            elif match.group(3):
                attributes[match.group(3).lower()] = self._decode_attribute_value(match.group(4))
            elif match.group(5):
                attributes[match.group(5).lower()] = self._decode_attribute_value(match.group(6))
            elif match.group(7) is not None:
                attributes[str(positional)] = self._decode_attribute_value(match.group(7))
                positional += 1
            elif match.group(8) is not None:
                attributes[str(positional)] = self._decode_attribute_value(match.group(8))
                positional += 1
        return attributes

    def _decode_attribute_value(self, value: str) -> str:
        return value.replace("\\\"", "\"").replace("\\'", "'").replace("{{NEWLINE}}", "\n")

    def _get_regex(self, except_shortcodes: list[str] | None = None) -> str:
        except_shortcodes = except_shortcodes or []
        names = "|".join(re.escape(key) for key in self._registered.keys() if key not in except_shortcodes)
        if not names:
            return r"(?!)"
        return (
            r"\[(\[?)"
            r"(" + names + r")"
            r"(?![\w-])"
            r"([^\]\/]*(?:\/(?!\])[^\]\/]*)*?)"
            r"(?:(\/)\]|\](?:([^\[]*+(?:\[(?!\/\2\])[^\[]*+)*+)\[\/\2\])?)"
            r"(\]?)"
        )

    def _strip_tag(self, match: re.Match) -> str:
        if match.group(1) == "[" and match.group(6) == "]":
            return match.group(0)[1:-1]
        return (match.group(1) or "") + (match.group(6) or "")

    def _lazy_placeholder(self, shortcode: ParsedShortcode) -> str:
        attributes = {key: value for key, value in shortcode.to_array().items() if key != "enable_lazy_loading"}
        attrs = html.escape(repr(attributes), quote=True)
        loading = self._loading_states.get(shortcode.name, "Loading...")
        return f'<div class="shortcode-lazy-placeholder" data-shortcode="{html.escape(shortcode.name, quote=True)}" data-attributes="{attrs}">{html.escape(loading)}</div>'

    def _contains_form_elements(self, content: Any) -> bool:
        text = str(content or "")
        return any(pattern.lower() in text.lower() for pattern in ["<form", "csrf_token", "_token", "g-recaptcha", "FormBuilder", "renderForm()"])


shortcode_engine = ShortcodeCompiler()
