"""API routes for the Contact plugin."""

from __future__ import annotations

import asyncio
import csv
import io
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from karpy_platform.core.setting.email_recipients import get_admin_emails
from karpy_platform.core.setting.email_templates import email_template_registry
from karpy_platform.core.setting.mailer import MailDeliveryError, mailer
from karpy_platform.core.setting.store import setting_store
from karpy_platform.plugins.contact.models.contact import Contact, ContactCustomField, ContactCustomFieldOption, ContactReply
from karpy_platform.plugins.contact.services.contact import (
    CONTACT_STATUSES,
    CUSTOM_FIELD_TYPES,
    FIELD_STATUSES,
    option_value,
    serialize_contact,
    serialize_field,
)

router = APIRouter()

CONTACT_ADMIN_REPLY_TEMPLATE = "plugins.contact.admin-reply"
CONTACT_REPLY_BAD_OVERRIDE_MARKERS = ("{{ booking_", "booking_first_name", "booking_inquiry")


class ContactUpdatePayload(BaseModel):
    status: str | None = None


class ContactReplyPayload(BaseModel):
    message: str = Field(min_length=1)
    sendEmail: bool = True


class CustomFieldOptionPayload(BaseModel):
    id: str | None = None
    label: str | None = None
    value: str = Field(min_length=1)
    order: int = 999


class CustomFieldPayload(BaseModel):
    type: str = "text"
    name: str = Field(min_length=1, max_length=190)
    placeholder: str | None = None
    required: bool = False
    order: int = 999
    status: str = "published"
    options: list[CustomFieldOptionPayload] = Field(default_factory=list)


async def require_admin(request: Request, db: AsyncSession = Depends(get_db)):
    # A real admin session is required (this used to return the bootstrap admin for any caller).
    from karpy_platform.core.acl.admin_guard import require_admin_session

    return await require_admin_session(request, db)


def _contact_filters(q: str | None = None, status: str | None = None) -> list[Any]:
    filters = [Contact.is_deleted.is_(False)]
    if q:
        like = f"%{q.strip()}%"
        filters.append(or_(Contact.name.ilike(like), Contact.email.ilike(like), Contact.phone.ilike(like), Contact.subject.ilike(like)))
    if status and status != "all":
        filters.append(Contact.status == status)
    return filters


def _field_filters(q: str | None = None, status: str | None = None) -> list[Any]:
    filters = [ContactCustomField.is_deleted.is_(False)]
    if q:
        like = f"%{q.strip()}%"
        filters.append(or_(ContactCustomField.name.ilike(like), ContactCustomField.placeholder.ilike(like), ContactCustomField.type.ilike(like)))
    if status and status != "all":
        filters.append(ContactCustomField.status == status)
    return filters


async def _count(db: AsyncSession, model, filters: list[Any]) -> int:
    result = await db.execute(select(func.count()).select_from(model).where(*filters))
    return int(result.scalar() or 0)


async def _published_fields(db: AsyncSession) -> list[ContactCustomField]:
    result = await db.execute(
        select(ContactCustomField)
        .options(selectinload(ContactCustomField.options))
        .where(ContactCustomField.is_deleted.is_(False), ContactCustomField.status == "published")
        .order_by(ContactCustomField.order.asc(), ContactCustomField.created_at.asc())
    )
    return list(result.scalars().unique().all())


@router.get("/")
async def index(db: AsyncSession = Depends(get_db), _: Any = Depends(require_admin)) -> dict[str, Any]:
    return {
        "plugin": "contact",
        "name": "Contact",
        "status": "ready",
        "counts": {
            "contacts": await _count(db, Contact, _contact_filters()),
            "unread": await _count(db, Contact, _contact_filters(status="unread")),
            "customFields": await _count(db, ContactCustomField, _field_filters()),
        },
    }


@router.get("/contacts")
async def contacts(
    q: str | None = None,
    status: str | None = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(15, ge=1, le=100, alias="perPage"),
    db: AsyncSession = Depends(get_db),
    _: Any = Depends(require_admin),
) -> dict[str, Any]:
    filters = _contact_filters(q=q, status=status)
    total = await _count(db, Contact, filters)
    result = await db.execute(
        select(Contact)
        .where(*filters)
        .order_by(Contact.created_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
    )
    return {"data": [serialize_contact(contact) for contact in result.scalars().all()], "meta": {"page": page, "perPage": per_page, "total": total}}


@router.get("/contacts/export")
async def export_contacts(
    q: str | None = None,
    status: str | None = None,
    db: AsyncSession = Depends(get_db),
    _: Any = Depends(require_admin),
) -> StreamingResponse:
    result = await db.execute(select(Contact).where(*_contact_filters(q=q, status=status)).order_by(Contact.created_at.desc()))
    stream = io.StringIO()
    writer = csv.writer(stream)
    writer.writerow(["Name", "Email", "Phone", "Subject", "Status", "Created At", "Content"])
    for contact in result.scalars().all():
        writer.writerow([contact.name, contact.email, contact.phone or "", contact.subject or "", contact.status, contact.created_at.isoformat(), contact.content])
    stream.seek(0)
    return StreamingResponse(iter([stream.getvalue()]), media_type="text/csv", headers={"Content-Disposition": 'attachment; filename="contacts.csv"'})


@router.get("/contacts/{contact_id}")
async def contact_detail(contact_id: str, db: AsyncSession = Depends(get_db), _: Any = Depends(require_admin)) -> dict[str, Any]:
    result = await db.execute(select(Contact).options(selectinload(Contact.replies)).where(Contact.id == contact_id, Contact.is_deleted.is_(False)))
    contact = result.scalars().first()
    if not contact:
        raise HTTPException(status_code=404, detail="Contact was not found.")
    if contact.status == "unread":
        contact.status = "read"
        await db.commit()
        await db.refresh(contact)
    return {"contact": serialize_contact(contact, include_replies=True)}


@router.patch("/contacts/{contact_id}")
async def update_contact(contact_id: str, payload: ContactUpdatePayload, db: AsyncSession = Depends(get_db), _: Any = Depends(require_admin)) -> dict[str, Any]:
    contact = await db.get(Contact, contact_id)
    if not contact or contact.is_deleted:
        raise HTTPException(status_code=404, detail="Contact was not found.")
    if payload.status:
        status = payload.status.lower().strip()
        if status not in CONTACT_STATUSES:
            raise HTTPException(status_code=422, detail={"status": "Unsupported contact status."})
        contact.status = status
    await db.commit()
    await db.refresh(contact)
    return {"contact": serialize_contact(contact, include_replies=True)}


@router.delete("/contacts/{contact_id}")
async def delete_contact(contact_id: str, db: AsyncSession = Depends(get_db), _: Any = Depends(require_admin)) -> dict[str, str]:
    contact = await db.get(Contact, contact_id)
    if not contact or contact.is_deleted:
        raise HTTPException(status_code=404, detail="Contact was not found.")
    contact.is_deleted = True
    await db.commit()
    return {"message": "Contact deleted."}


@router.post("/contacts/{contact_id}/reply")
async def reply_contact(contact_id: str, payload: ContactReplyPayload, db: AsyncSession = Depends(get_db), _: Any = Depends(require_admin)) -> dict[str, Any]:
    contact = await db.get(Contact, contact_id)
    if not contact or contact.is_deleted:
        raise HTTPException(status_code=404, detail="Contact was not found.")
    reply = ContactReply(contact_id=contact.id, message=payload.message.strip())
    contact.status = "read"
    db.add(reply)
    await db.commit()
    await db.refresh(reply)
    if payload.sendEmail:
        await _send_contact_email(db, CONTACT_ADMIN_REPLY_TEMPLATE, contact.email, contact, {"admin_reply_message": reply.message})
    return {"reply": {"id": reply.id, "message": reply.message, "createdAt": reply.created_at.isoformat()}}


@router.get("/custom-fields")
async def custom_fields(
    q: str | None = None,
    status: str | None = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(25, ge=1, le=100, alias="perPage"),
    db: AsyncSession = Depends(get_db),
    _: Any = Depends(require_admin),
) -> dict[str, Any]:
    filters = _field_filters(q=q, status=status)
    total = await _count(db, ContactCustomField, filters)
    result = await db.execute(
        select(ContactCustomField)
        .options(selectinload(ContactCustomField.options))
        .where(*filters)
        .order_by(ContactCustomField.order.asc(), ContactCustomField.created_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
    )
    return {"data": [serialize_field(field) for field in result.scalars().unique().all()], "meta": {"page": page, "perPage": per_page, "total": total}, "types": sorted(CUSTOM_FIELD_TYPES)}


@router.post("/custom-fields")
async def create_custom_field(payload: CustomFieldPayload, db: AsyncSession = Depends(get_db), _: Any = Depends(require_admin)) -> dict[str, Any]:
    field = _build_field(ContactCustomField(), payload)
    db.add(field)
    await db.flush()
    _replace_options(db, field, payload.options)
    await db.commit()
    await db.refresh(field)
    result = await db.execute(select(ContactCustomField).options(selectinload(ContactCustomField.options)).where(ContactCustomField.id == field.id))
    return {"field": serialize_field(result.scalars().first())}


@router.get("/custom-fields/{field_id}")
async def custom_field_detail(field_id: str, db: AsyncSession = Depends(get_db), _: Any = Depends(require_admin)) -> dict[str, Any]:
    result = await db.execute(select(ContactCustomField).options(selectinload(ContactCustomField.options)).where(ContactCustomField.id == field_id, ContactCustomField.is_deleted.is_(False)))
    field = result.scalars().first()
    if not field:
        raise HTTPException(status_code=404, detail="Custom field was not found.")
    return {"field": serialize_field(field), "types": sorted(CUSTOM_FIELD_TYPES)}


@router.put("/custom-fields/{field_id}")
async def update_custom_field(field_id: str, payload: CustomFieldPayload, db: AsyncSession = Depends(get_db), _: Any = Depends(require_admin)) -> dict[str, Any]:
    result = await db.execute(select(ContactCustomField).options(selectinload(ContactCustomField.options)).where(ContactCustomField.id == field_id, ContactCustomField.is_deleted.is_(False)))
    field = result.scalars().first()
    if not field:
        raise HTTPException(status_code=404, detail="Custom field was not found.")
    _build_field(field, payload)
    for option in list(field.options or []):
        await db.delete(option)
    await db.flush()
    _replace_options(db, field, payload.options)
    await db.commit()
    result = await db.execute(select(ContactCustomField).options(selectinload(ContactCustomField.options)).where(ContactCustomField.id == field.id))
    return {"field": serialize_field(result.scalars().first())}


@router.delete("/custom-fields/{field_id}")
async def delete_custom_field(field_id: str, db: AsyncSession = Depends(get_db), _: Any = Depends(require_admin)) -> dict[str, str]:
    field = await db.get(ContactCustomField, field_id)
    if not field or field.is_deleted:
        raise HTTPException(status_code=404, detail="Custom field was not found.")
    field.is_deleted = True
    await db.commit()
    return {"message": "Custom field deleted."}


@router.get("/form")
async def contact_form_fields(db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    fields = await _published_fields(db)
    return {"fields": [serialize_field(field) for field in fields]}


@router.post("/send")
async def send_contact(request: Request, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    data = await _request_data(request)
    contact = await _store_contact(db, data)
    email_errors = []
    for recipient in await get_admin_emails(db):
        try:
            await _send_contact_email(db, "plugins.contact.notice", recipient, contact)
        except MailDeliveryError as exc:
            email_errors.append(str(exc))
    try:
        await _send_contact_email(db, "plugins.contact.sender-confirmation", contact.email, contact)
    except MailDeliveryError:
        pass
    return {"message": "Send message successfully!", "contact": serialize_contact(contact), "emailErrors": email_errors}


def _build_field(field: ContactCustomField, payload: CustomFieldPayload) -> ContactCustomField:
    field_type = payload.type.lower().strip()
    status = payload.status.lower().strip()
    if field_type not in CUSTOM_FIELD_TYPES:
        raise HTTPException(status_code=422, detail={"errors": {"type": "Unsupported custom field type."}})
    if status not in FIELD_STATUSES:
        raise HTTPException(status_code=422, detail={"errors": {"status": "Unsupported custom field status."}})
    if field_type in {"dropdown", "radio"} and not payload.options:
        raise HTTPException(status_code=422, detail={"errors": {"options": "This field type needs at least one option."}})
    field.type = field_type
    field.name = payload.name.strip()
    field.placeholder = (payload.placeholder or "").strip() or None
    field.required = payload.required
    field.order = payload.order
    field.status = status
    return field


def _replace_options(db: AsyncSession, field: ContactCustomField, options: list[CustomFieldOptionPayload]) -> None:
    rows: list[ContactCustomFieldOption] = []
    for index, option in enumerate(options):
        rows.append(
            ContactCustomFieldOption(
                custom_field_id=field.id,
                label=(option.label or option.value).strip(),
                value=option.value.strip(),
                order=option.order if option.order != 999 else index + 1,
            )
        )
    if rows:
        db.add_all(rows)


async def _request_data(request: Request) -> dict[str, Any]:
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        return dict(await request.json())
    form = await request.form()
    data: dict[str, Any] = {}
    custom_fields: dict[str, Any] = {}
    for key, value in form.multi_items():
        if key.startswith("custom_fields[") and key.endswith("]"):
            custom_fields[key[14:-1]] = value
        else:
            data[key] = value
    if custom_fields:
        data["customFields"] = custom_fields
    return data


async def _store_contact(db: AsyncSession, data: dict[str, Any]) -> Contact:
    errors = {}
    name = str(data.get("name") or "").strip()
    email = str(data.get("email") or "").strip()
    content = str(data.get("content") or data.get("message") or "").strip()
    display_fields = _list_attribute(data.get("display_fields"), "phone,email,address,subject")
    mandatory_fields = _list_attribute(data.get("required_fields") or data.get("mandatory_fields"), "email")
    always_required = {"name", "content"}
    if not name:
        errors["name"] = "The name field is required."
    if not content:
        errors["content"] = "The message field is required."
    if "email" in display_fields and ("email" in mandatory_fields or "email" in always_required):
        if not email or "@" not in email:
            errors["email"] = "A valid email address is required."
    elif email and "@" not in email:
        errors["email"] = "A valid email address is required."
    for field_name, label in {"phone": "phone", "address": "address", "subject": "subject"}.items():
        if field_name in display_fields and field_name in mandatory_fields and not str(data.get(field_name) or "").strip():
            errors[field_name] = f"The {label} field is required."
    fields = await _published_fields(db)
    raw_custom = data.get("customFields") or data.get("custom_fields") or {}
    custom_values: dict[str, Any] = {}
    for field in fields:
        raw_value = raw_custom.get(field.id) if isinstance(raw_custom, dict) else None
        if field.required and raw_value in {None, ""}:
            errors[f"customFields.{field.id}"] = f"The {field.name} field is required."
            continue
        if raw_value not in {None, ""}:
            custom_values[field.name] = option_value(field, raw_value)
    if errors:
        raise HTTPException(status_code=422, detail={"errors": errors})
    contact = Contact(
        name=name,
        email=email,
        phone=str(data.get("phone") or "").strip() or None,
        address=str(data.get("address") or "").strip() or None,
        subject=str(data.get("subject") or "").strip() or None,
        content=content,
        custom_fields=custom_values,
    )
    db.add(contact)
    await db.commit()
    await db.refresh(contact)
    return contact


def _list_attribute(value: Any, default: str) -> set[str]:
    if isinstance(value, (list, tuple, set)):
        return {str(item).strip() for item in value if str(item).strip()}
    return {item.strip() for item in str(value or default).replace(" ", "").split(",") if item.strip()}


async def _send_contact_email(db: AsyncSession, template_key: str, recipient: str, contact: Contact, extra: dict[str, Any] | None = None) -> None:
    values = await setting_store.all(db, flat=True)
    if template_key == CONTACT_ADMIN_REPLY_TEMPLATE:
        values = await _heal_contact_reply_template_override(db, values)
    variables = {
        "contact_name": contact.name,
        "contact_subject": contact.subject or "",
        "contact_email": contact.email,
        "contact_phone": contact.phone or "",
        "contact_address": contact.address or "",
        "contact_content": contact.content,
        "contact_custom_fields": _custom_fields_html(contact.custom_fields or {}),
        **(extra or {}),
    }
    subject, html = mailer.render_template(template_key, values, variables)
    text = None
    branded = _branded_contact_email(template_key, subject, contact, extra or {}, values)
    if branded:
        subject, html, text = branded["subject"], branded["html"], branded["text"]
    await asyncio.to_thread(mailer.send, values, to=recipient, subject=subject, html=html, text=text)


def _branded_contact_email(template_key: str, subject: str, contact: Contact, extra: dict[str, Any], values: dict[str, Any]) -> dict | None:
    """A plugin's branded email layout (``mail.branded_layout`` filter) for contact emails;
    None keeps the legacy template.

    render_template above still decides whether the template is switched on and supplies the
    (admin-editable) subject; the body wording is the default template's, as plain text.
    """
    from karpy_platform.core.base.hooks import hooks
    if not hooks.has_filter("mail.branded_layout"):
        return None
    subject = " ".join(str(subject).split())
    if template_key == "plugins.contact.notice":
        lines = [f"{label}: {value}" for label, value in (("Name", contact.name), ("Email", contact.email), ("Phone", contact.phone), ("Subject", contact.subject)) if value]
        fields = [f"{key}: {value}" for key, value in (contact.custom_fields or {}).items() if str(value or "").strip()]
        text = "\n\n".join(part for part in ("\n".join(lines), contact.content, "\n".join(fields)) if part)
    elif template_key == "plugins.contact.sender-confirmation":
        text = f"Thank you, {contact.name}.\n\nWe received your message and will respond soon.\n\nYour message:\n{contact.content}"
    elif template_key == CONTACT_ADMIN_REPLY_TEMPLATE:
        original = "\n".join(part for part in ((f"Subject: {contact.subject}" if contact.subject else ""), contact.content) if part)
        text = (f"Dear {contact.name},\n\nThank you for contacting us. We reviewed your message and here is our response:\n\n"
                f"{extra.get('admin_reply_message') or ''}\n\nYour original message:\n{original}\n\n"
                "If you have any additional questions, please reply to this email or contact us again.")
    else:
        return None
    return hooks.apply_filters("mail.branded_layout", None, subject, text.replace("\r\n", "\n").replace("\r", "\n"), values)


async def _heal_contact_reply_template_override(db: AsyncSession, values: dict[str, Any]) -> dict[str, Any]:
    """Keep contact replies from accidentally using a template saved for another plugin."""

    found = email_template_registry.find(CONTACT_ADMIN_REPLY_TEMPLATE)
    if not found:
        return values

    group, template = found
    subject_key = email_template_registry.subject_key(group.type, group.module, template.key)
    body_key = email_template_registry.body_key(group.type, group.module, template.key)
    bad_keys = [
        key
        for key in (subject_key, body_key)
        if _looks_like_wrong_contact_reply_override(values.get(key))
    ]
    if not bad_keys:
        return values

    await setting_store.delete(db, bad_keys)
    fresh = await setting_store.all(db, flat=True, force=True)
    return fresh


def _looks_like_wrong_contact_reply_override(value: Any) -> bool:
    text = str(value or "").lower()
    return any(marker in text for marker in CONTACT_REPLY_BAD_OVERRIDE_MARKERS)


def _custom_fields_html(values: dict[str, Any]) -> str:
    if not values:
        return ""
    return "<br>".join(f"<strong>{key}:</strong> {value}" for key, value in values.items())
