"""Contact plugin serialization and rendering helpers."""

from __future__ import annotations

import html
from datetime import datetime
from typing import Any

from karpy_platform.plugins.contact.models.contact import Contact, ContactCustomField, ContactCustomFieldOption, ContactReply

CUSTOM_FIELD_TYPES = {"text", "number", "textarea", "dropdown", "checkbox", "radio", "date", "datetime", "time"}
CONTACT_STATUSES = {"read", "unread"}
FIELD_STATUSES = {"published", "draft", "pending", "disabled"}


def iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def serialize_option(option: ContactCustomFieldOption) -> dict[str, Any]:
    return {"id": option.id, "label": option.label or option.value, "value": option.value, "order": option.order}


def serialize_field(field: ContactCustomField) -> dict[str, Any]:
    return {
        "id": field.id,
        "type": field.type,
        "required": field.required,
        "name": field.name,
        "placeholder": field.placeholder or "",
        "order": field.order,
        "status": field.status,
        "options": [serialize_option(option) for option in sorted(field.options or [], key=lambda item: item.order)],
        "createdAt": iso(field.created_at),
        "updatedAt": iso(field.updated_at),
    }


def serialize_reply(reply: ContactReply) -> dict[str, Any]:
    return {"id": reply.id, "message": reply.message, "createdAt": iso(reply.created_at)}


def serialize_contact(contact: Contact, *, include_replies: bool = False) -> dict[str, Any]:
    payload = {
        "id": contact.id,
        "name": contact.name,
        "email": contact.email,
        "phone": contact.phone or "",
        "address": contact.address or "",
        "subject": contact.subject or "",
        "content": contact.content,
        "status": contact.status,
        "customFields": contact.custom_fields or {},
        "createdAt": iso(contact.created_at),
        "updatedAt": iso(contact.updated_at),
    }
    if include_replies:
        payload["replies"] = [serialize_reply(reply) for reply in contact.replies or []]
    return payload


def option_value(field: ContactCustomField, raw_value: Any) -> Any:
    if field.type == "checkbox":
        return "Yes" if raw_value in {True, "true", "1", "yes", "on", 1} else "No"
    if field.type in {"radio", "dropdown"}:
        for option in field.options or []:
            if str(option.value) == str(raw_value):
                return option.label or option.value
    return raw_value


def render_contact_form(fields: list[ContactCustomField], attributes: dict[str, Any] | None = None) -> str:
    attrs = attributes or {}
    display = _list_attribute(attrs.get("display_fields"), "phone,email,subject,address")
    mandatory = _list_attribute(attrs.get("mandatory_fields"), "email")
    title = str(attrs.get("information_box_title") or "Contact Us").strip()
    has_custom_fields = bool(fields)
    pieces = [
        _contact_form_assets(),
        '<section class="karpy-contact-block">',
        '<div class="karpy-contact-card">',
        '<div class="karpy-contact-head">',
        f'<div><p class="karpy-contact-eyebrow">Contact</p><h2>{html.escape(title)}</h2></div>',
        '<p>Send your message through the form below.</p>',
        "</div>",
        '<form class="karpy-contact-form" method="post" action="/api/plugins/contact/send" data-karpy-contact-form="true" novalidate>',
        f'<input type="hidden" name="display_fields" value="{html.escape(",".join(sorted(display)), quote=True)}">',
        f'<input type="hidden" name="required_fields" value="{html.escape(",".join(sorted(mandatory)), quote=True)}">',
        f'<input type="hidden" name="mandatory_fields" value="{html.escape(",".join(sorted(mandatory)), quote=True)}">',
        '<div class="karpy-contact-response" data-karpy-contact-response role="status" aria-live="polite"></div>',
        '<div class="karpy-contact-grid">',
        _input("name", "Name", "text", required=True),
    ]
    if "email" in display:
        pieces.append(_input("email", "Email", "email", required="email" in mandatory))
    if "phone" in display:
        pieces.append(_input("phone", "Phone", "tel", required="phone" in mandatory))
    if "address" in display:
        pieces.append(_input("address", "Address", "text", required="address" in mandatory))
    if "subject" in display:
        pieces.append(_input("subject", "Subject", "text", required="subject" in mandatory, span=True))
    pieces.append(_textarea("content", "Message", required=True))
    if has_custom_fields:
        pieces.append('<div class="karpy-contact-section-title"><span>Additional information</span></div>')
    for field in sorted(fields, key=lambda item: item.order):
        pieces.append(_custom_field(field))
    pieces.extend(
        [
            "</div>",
            '<div class="karpy-contact-actions"><button type="submit" class="karpy-contact-submit">Send message</button></div>',
            "</form>",
            "</div>",
            "</section>",
        ]
    )
    return "\n".join(pieces)


def _list_attribute(value: Any, default: str) -> set[str]:
    if isinstance(value, (list, tuple, set)):
        return {str(item).strip() for item in value if str(item).strip()}
    return {item.strip() for item in str(value or default).replace(" ", "").split(",") if item.strip()}


def _input(name: str, label: str, input_type: str, *, required: bool = False, span: bool = False) -> str:
    required_attr = " required" if required else ""
    class_name = "karpy-contact-field karpy-contact-span" if span else "karpy-contact-field"
    return (
        f'<label class="{class_name}" data-field-name="{html.escape(name, quote=True)}">'
        f'<span>{html.escape(label)}{_required_mark(required)}</span>'
        f'<input type="{input_type}" name="{name}" placeholder="{html.escape(label, quote=True)}"{required_attr}>'
        f'{_error_slot(name)}</label>'
    )


def _textarea(name: str, label: str, *, required: bool = False) -> str:
    required_attr = " required" if required else ""
    return (
        f'<label class="karpy-contact-field karpy-contact-span" data-field-name="{html.escape(name, quote=True)}">'
        f'<span>{html.escape(label)}{_required_mark(required)}</span>'
        f'<textarea name="{name}" placeholder="{html.escape(label, quote=True)}"{required_attr}></textarea>'
        f'{_error_slot(name)}</label>'
    )


def _custom_field(field: ContactCustomField) -> str:
    error_key = f"customFields.{field.id}"
    name = f"custom_fields[{html.escape(field.id, quote=True)}]"
    label = html.escape(field.name)
    label_text = f"{label}{_required_mark(field.required)}"
    required = " required" if field.required else ""
    placeholder = html.escape(field.placeholder or field.name, quote=True)
    if field.type == "textarea":
        return (
            f'<label class="karpy-contact-field karpy-contact-span" data-field-name="{html.escape(error_key, quote=True)}">'
            f"<span>{label_text}</span><textarea name=\"{name}\" placeholder=\"{placeholder}\"{required}></textarea>{_error_slot(error_key)}</label>"
        )
    if field.type == "dropdown":
        options = "".join(f'<option value="{html.escape(option.value, quote=True)}">{html.escape(option.label or option.value)}</option>' for option in field.options or [])
        return (
            f'<label class="karpy-contact-field" data-field-name="{html.escape(error_key, quote=True)}">'
            f"<span>{label_text}</span><select name=\"{name}\"{required}><option value=\"\">Select {label.lower()}</option>{options}</select>{_error_slot(error_key)}</label>"
        )
    if field.type in {"radio", "checkbox"}:
        input_type = "checkbox" if field.type == "checkbox" else "radio"
        options = field.options or []
        option_required = required if field.type == "radio" else ""
        if not options:
            return (
                f'<fieldset class="karpy-contact-field karpy-contact-span" data-field-name="{html.escape(error_key, quote=True)}">'
                f"<legend>{label_text}</legend><label class=\"karpy-contact-check\"><input type=\"{input_type}\" name=\"{name}\" value=\"1\"{required}> <span>{label}</span></label>{_error_slot(error_key)}</fieldset>"
            )
        inputs = "".join(
            f'<label class="karpy-contact-check"><input type="{input_type}" name="{name}" value="{html.escape(option.value, quote=True)}"{option_required}> <span>{html.escape(option.label or option.value)}</span></label>'
            for option in options
        )
        return f'<fieldset class="karpy-contact-field karpy-contact-span" data-field-name="{html.escape(error_key, quote=True)}"><legend>{label_text}</legend><div class="karpy-contact-options">{inputs}</div>{_error_slot(error_key)}</fieldset>'
    input_type = "number" if field.type == "number" else "datetime-local" if field.type == "datetime" else field.type if field.type in {"date", "time"} else "text"
    return (
        f'<label class="karpy-contact-field" data-field-name="{html.escape(error_key, quote=True)}">'
        f"<span>{label_text}</span><input type=\"{input_type}\" name=\"{name}\" placeholder=\"{placeholder}\"{required}>{_error_slot(error_key)}</label>"
    )


def _required_mark(required: bool) -> str:
    return ' <strong class="karpy-contact-required">*</strong>' if required else ""


def _error_slot(key: str) -> str:
    return f'<small class="karpy-contact-field-error" data-field-error-for="{html.escape(key, quote=True)}"></small>'


def _contact_form_assets() -> str:
    return """
<script>
(function () {
    if (window.__karpyContactFormsBound) return;
    window.__karpyContactFormsBound = true;

    function errorMap(payload) {
        var detail = payload && payload.detail ? payload.detail : payload;
        return (detail && detail.errors) || detail || {};
    }

    function findByData(form, attr, value) {
        var items = form.querySelectorAll("[" + attr + "]");
        for (var index = 0; index < items.length; index += 1) {
            if (items[index].getAttribute(attr) === value) return items[index];
        }
        return null;
    }

    function clearState(form) {
        form.querySelectorAll(".karpy-contact-field.has-error").forEach(function (field) {
            field.classList.remove("has-error");
        });
        form.querySelectorAll("[data-field-error-for]").forEach(function (slot) {
            slot.textContent = "";
        });
        var response = form.querySelector("[data-karpy-contact-response]");
        if (response) {
            response.textContent = "";
            response.className = "karpy-contact-response";
        }
    }

    function messageText(value) {
        if (Array.isArray(value)) return value.join(" ");
        if (value && typeof value === "object") return Object.values(value).join(" ");
        return String(value || "This field is invalid.");
    }

    function showResponse(form, type, message) {
        var response = form.querySelector("[data-karpy-contact-response]");
        if (!response) return;
        response.textContent = message;
        response.className = "karpy-contact-response is-" + type;
    }

    document.addEventListener("submit", function (event) {
        var target = event.target;
        if (!target || !target.closest) return;
        var form = target.closest("[data-karpy-contact-form]");
        if (!form) return;
        event.preventDefault();
        clearState(form);

        var button = form.querySelector(".karpy-contact-submit");
        var previousText = button ? button.textContent : "";
        if (button) {
            button.disabled = true;
            button.textContent = "Sending...";
        }

        fetch(form.action, {
            method: "POST",
            body: new FormData(form),
            headers: { "X-Requested-With": "XMLHttpRequest" }
        }).then(function (response) {
            return response.json().catch(function () { return {}; }).then(function (payload) {
                if (!response.ok) throw payload;
                return payload;
            });
        }).then(function (payload) {
            showResponse(form, "success", payload.message || "Send message successfully!");
            form.reset();
        }).catch(function (payload) {
            var errors = errorMap(payload);
            if (!errors || typeof errors !== "object") {
                showResponse(form, "error", messageText(errors || "The message could not be sent."));
                return;
            }
            var hasFieldError = false;
            Object.keys(errors).forEach(function (key) {
                var slot = findByData(form, "data-field-error-for", key);
                var wrapper = findByData(form, "data-field-name", key);
                if (slot) {
                    slot.textContent = messageText(errors[key]);
                    hasFieldError = true;
                }
                if (wrapper) wrapper.classList.add("has-error");
            });
            showResponse(form, "error", hasFieldError ? "Please check the highlighted fields." : messageText(errors.message || errors.detail || "The message could not be sent."));
            var firstError = form.querySelector(".karpy-contact-field.has-error");
            if (firstError && firstError.scrollIntoView) firstError.scrollIntoView({ behavior: "smooth", block: "center" });
        }).finally(function () {
            if (button) {
                button.disabled = false;
                button.textContent = previousText;
            }
        });
    }, true);
}());
</script>
""".strip()
