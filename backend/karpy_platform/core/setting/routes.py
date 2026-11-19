from __future__ import annotations

import asyncio
import re
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from karpy_platform.core.acl.routes import ensure_admin_user
from karpy_platform.core.base.responses import BaseHttpResponse
from karpy_platform.core.media.service import MediaValidationError, rv_media
from karpy_platform.core.media.settings import media_settings_payload, validate_media_settings
from karpy_platform.core.setting.api import (
    APISettingsError,
    api_settings_payload,
    save_generated_key,
    save_service_account,
    send_push_notification,
    validate_api_settings,
)
from karpy_platform.core.setting.cache import apply_runtime_cache_settings, cache_settings_payload, validate_cache_settings
from karpy_platform.core.setting.datatables import datatables_settings_payload, validate_datatables_settings
from karpy_platform.core.setting.email_recipients import get_admin_emails, normalize_admin_emails
from karpy_platform.core.setting.email_rules import validate_email_rule_settings
from karpy_platform.core.setting.email_templates import email_template_registry
from karpy_platform.core.setting.license import (
    LicenseActivationError,
    LicenseActivationPayload,
    activate_license as activate_envato_license,
    deactivate_license as deactivate_envato_license,
    license_status,
)
from karpy_platform.core.setting.mailer import MailDeliveryError, mailer
from karpy_platform.core.setting.phone import phone_settings_payload, validate_phone_settings
from karpy_platform.core.setting.registry import SettingField, setting_panel_registry
from karpy_platform.core.setting.store import GUARDED_SETTINGS, setting_store

router = APIRouter()


class SettingsUpdate(BaseModel):
    settings: dict[str, Any] = Field(default_factory=dict)
    force: bool = False


class SettingDelete(BaseModel):
    keys: list[str]
    force: bool = False


class EmailTestRequest(BaseModel):
    to: str
    subject: str = "KARPy test email"
    message: str = "This is a test email from KARPy CMS."
    template: str = "core.base.test"


class EmailTemplateStatusUpdate(BaseModel):
    statuses: dict[str, bool] = Field(default_factory=dict)


class EmailTemplateUpdate(BaseModel):
    subject: str | None = Field(default=None, max_length=300)
    body: str = Field(min_length=1, max_length=100000)


class LicenseActivationRequest(BaseModel):
    envatoUsername: str = Field(min_length=2, max_length=120)
    purchaseCode: str = Field(min_length=8, max_length=120)
    confirm: bool = False


class PushNotificationRequest(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    message: str = Field(min_length=1, max_length=500)
    target: str = "all"
    actionUrl: str = ""
    imageUrl: str = ""


@router.get("/")
async def get_all_settings(
    nested: bool = Query(default=False),
    forceReload: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
):
    """Back-compatible raw setting dictionary."""
    await ensure_admin_user(db)
    return await setting_store.all(db, flat=not nested, force=forceReload)


@router.post("/")
async def save_settings(payload: SettingsUpdate, db: AsyncSession = Depends(get_db)):
    """Back-compatible bulk save endpoint."""
    await ensure_admin_user(db)
    await _validate_settings(payload.settings)
    await setting_store.set(db, payload.settings, force=payload.force)
    await setting_store.save(db)
    values = await setting_store.all(db, flat=True, force=True)
    await apply_runtime_cache_settings(values)
    return {"status": "success", "message": "Settings saved successfully"}


@router.get("/panel")
async def get_settings_panel(db: AsyncSession = Depends(get_db)):
    await ensure_admin_user(db)
    values = await setting_store.all(db, flat=True)
    return {"panels": setting_panel_registry.panels(values), "guarded": sorted(GUARDED_SETTINGS)}


@router.get("/sections")
async def get_settings_sections(db: AsyncSession = Depends(get_db)):
    await ensure_admin_user(db)
    values = await setting_store.all(db, flat=True)
    return {"sections": [section.to_dict(values) for section in setting_panel_registry.sections()]}


@router.get("/values")
async def get_setting_values(
    keys: list[str] = Query(default_factory=list),
    prefix: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    await ensure_admin_user(db)
    values = await setting_store.all(db, flat=True)
    if keys:
        values = {key: values.get(key) for key in keys}
    if prefix:
        values = {key: value for key, value in values.items() if key.startswith(prefix)}
    return {"settings": values}


@router.post("/delete")
async def delete_settings(payload: SettingDelete, db: AsyncSession = Depends(get_db)):
    await ensure_admin_user(db)
    deleted = await setting_store.delete(db, payload.keys, force=payload.force)
    return BaseHttpResponse.make().set_data({"deleted": deleted}).with_deleted_success_message().to_dict()


@router.post("/cache/clear")
async def clear_setting_cache(db: AsyncSession = Depends(get_db)):
    await ensure_admin_user(db)
    setting_store.clear_cache()
    return BaseHttpResponse.make().set_message("Setting cache cleared successfully").to_dict()


def _html_to_text(markup: str) -> str:
    """Readable plain text from a simple legacy template body (block tags become line breaks)."""
    import html as html_module

    text = re.sub(r"(?is)<(script|style)\b.*?</\1>", "", str(markup or ""))
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(p|div|h[1-6]|tr|table|li)>", "\n\n", text)
    text = html_module.unescape(re.sub(r"<[^>]+>", "", text))
    lines = [" ".join(line.split()) for line in text.splitlines()]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def _branded_test_email(subject: str, markup: str, values: dict[str, Any]) -> tuple[str, str, str | None]:
    """Test emails use the branded layout a plugin registers (``mail.branded_layout`` filter:
    ``(None, subject, text, settings_values) -> {"subject", "html", "text"} | None``), else the legacy markup."""
    from karpy_platform.core.base.hooks import hooks
    if not hooks.has_filter("mail.branded_layout"):
        return subject, markup, None
    subject = " ".join(str(subject or "").split()) or "Test email"
    message = hooks.apply_filters("mail.branded_layout", None, subject, _html_to_text(markup) or "This is a test email.", values)
    if not message:
        return subject, markup, None
    return message["subject"], message["html"], message["text"]


@router.post("/email/test")
async def send_test_email(payload: EmailTestRequest, db: AsyncSession = Depends(get_db)):
    await ensure_admin_user(db)
    values = await setting_store.all(db, flat=True)
    if not _valid_email(payload.to):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid recipient email.")

    try:
        if payload.template:
            subject, html = mailer.render_template(payload.template, values, parts=False)
        else:
            subject, html = payload.subject, payload.message
        subject, html, text = _branded_test_email(subject, html, values)
        result = await asyncio.to_thread(mailer.send, values, to=payload.to, subject=subject, html=html, text=text)
    except (MailDeliveryError, ValueError) as exception:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exception)) from exception

    return BaseHttpResponse.make().set_message(result.message).set_data(result.__dict__).to_dict()


@router.get("/email/templates")
async def get_email_templates(db: AsyncSession = Depends(get_db)):
    await ensure_admin_user(db)
    values = await setting_store.all(db, flat=True)
    return email_template_registry.payload(values)


@router.put("/email/templates/status")
async def update_email_template_status(payload: EmailTemplateStatusUpdate, db: AsyncSession = Depends(get_db)):
    await ensure_admin_user(db)
    values: dict[str, str] = {}
    errors: dict[str, str] = {}
    for template_key, enabled in payload.statuses.items():
        found = email_template_registry.find(template_key)
        if not found:
            errors[template_key] = "Email template was not found."
            continue
        group, template = found
        if not template.can_off and not enabled:
            errors[template_key] = "This email template cannot be disabled."
            continue
        values[email_template_registry.status_key(group.type, group.module, template.key)] = "1" if enabled else "0"

    if errors:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, {"message": "Invalid email template status.", "errors": errors})

    if values:
        await setting_store.set(db, values)
        await setting_store.save(db)
    latest = await setting_store.all(db, flat=True, force=True)
    return BaseHttpResponse.make().set_data(email_template_registry.payload(latest)).with_updated_success_message().to_dict()


@router.get("/email/templates/{template_key}")
async def get_email_template(template_key: str, db: AsyncSession = Depends(get_db)):
    await ensure_admin_user(db)
    found = email_template_registry.find(template_key)
    if not found:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Email template not found.")
    group, template = found
    values = await setting_store.all(db, flat=True)
    subject = values.get(email_template_registry.subject_key(group.type, group.module, template.key), template.subject)
    body = values.get(email_template_registry.body_key(group.type, group.module, template.key), template.body)
    invalid_partial_override = _is_base_partial(group.module, template.key) and _contains_partial_placeholder(str(body))
    if invalid_partial_override:
        body = template.body
    template_variables = {
        **template.variables,
        "site_title": "Site title",
        "site_url": "Site URL",
        "site_logo": "Email template logo",
        "site_email": "Email template contact address",
        "site_copyright": "Copyright text",
        "site_social_links": "Rendered social links",
    }
    if not _is_base_partial(group.module, template.key):
        template_variables.update({
            "header": "Email template header",
            "footer": "Email template footer",
        })
    return {
        "template": {
            "key": template_key,
            "type": group.type,
            "module": group.module,
            "name": template.key,
            "groupName": group.name,
            "title": template.title,
            "description": template.description,
            "subject": subject,
            "body": body,
            "defaultSubject": template.subject,
            "defaultBody": template.body,
            "variables": template_variables,
            "invalidOverride": invalid_partial_override,
        }
    }


@router.put("/email/templates/{template_key}")
async def update_email_template(template_key: str, payload: EmailTemplateUpdate, db: AsyncSession = Depends(get_db)):
    await ensure_admin_user(db)
    found = email_template_registry.find(template_key)
    if not found:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Email template not found.")
    group, template = found
    if _is_base_partial(group.module, template.key) and _contains_partial_placeholder(payload.body):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            {
                "message": "Invalid email template.",
                "errors": {
                    "body": "Header and footer partials cannot include {{ header }} or {{ footer }}. Put the full email body in a content template instead.",
                },
            },
        )
    values = {email_template_registry.body_key(group.type, group.module, template.key): payload.body}
    if template.subject or payload.subject is not None:
        values[email_template_registry.subject_key(group.type, group.module, template.key)] = payload.subject or ""
    await setting_store.set(db, values)
    await setting_store.save(db)
    return BaseHttpResponse.make().with_updated_success_message().to_dict()


@router.post("/email/templates/{template_key}/restore")
async def restore_email_template(template_key: str, db: AsyncSession = Depends(get_db)):
    await ensure_admin_user(db)
    found = email_template_registry.find(template_key)
    if not found:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Email template not found.")
    group, template = found
    keys = [email_template_registry.body_key(group.type, group.module, template.key)]
    if template.subject:
        keys.append(email_template_registry.subject_key(group.type, group.module, template.key))
    await setting_store.delete(db, keys, force=True)
    return BaseHttpResponse.make().set_message("Email template restored to default.").to_dict()


@router.get("/email/templates/{template_key}/preview")
async def preview_email_template(template_key: str, request: Request, db: AsyncSession = Depends(get_db)):
    await ensure_admin_user(db)
    values = await setting_store.all(db, flat=True)
    sample_values = {key: value for key, value in request.query_params.items() if not key.startswith("_")}
    sample_values.setdefault("reset_link", "#")
    try:
        subject, html = mailer.render_template(template_key, values, sample_values)
    except (MailDeliveryError, ValueError) as exception:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exception)) from exception
    return {"subject": subject, "html": html}


@router.get("/general/license")
async def get_general_license_status(db: AsyncSession = Depends(get_db)):
    await ensure_admin_user(db)
    return await license_status(db)


@router.post("/general/license/activate")
async def activate_general_license(payload: LicenseActivationRequest, db: AsyncSession = Depends(get_db)):
    await ensure_admin_user(db)
    try:
        status_payload = await activate_envato_license(
            db,
            LicenseActivationPayload(
                envato_username=payload.envatoUsername,
                purchase_code=payload.purchaseCode,
                confirm=payload.confirm,
            ),
        )
    except LicenseActivationError as exception:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exception)) from exception

    return BaseHttpResponse.make().set_message("Your license has been activated successfully.").set_data(status_payload).to_dict()


@router.post("/general/license/deactivate")
async def deactivate_general_license(db: AsyncSession = Depends(get_db)):
    await ensure_admin_user(db)
    status_payload = await deactivate_envato_license(db)
    return BaseHttpResponse.make().set_message("Deactivated license successfully!").set_data(status_payload).to_dict()


@router.get("/general/admin-emails")
async def get_general_admin_emails(db: AsyncSession = Depends(get_db)):
    await ensure_admin_user(db)
    return {"emails": await get_admin_emails(db)}


@router.get("/phone-number/options")
async def get_phone_number_options(db: AsyncSession = Depends(get_db)):
    await ensure_admin_user(db)
    values = await setting_store.all(db, flat=True)
    return phone_settings_payload(values)


@router.get("/media/options")
async def get_media_options(db: AsyncSession = Depends(get_db)):
    await ensure_admin_user(db)
    values = await setting_store.all(db, flat=True)
    return media_settings_payload(values)


@router.post("/media/generate-thumbnails")
async def generate_media_thumbnails(db: AsyncSession = Depends(get_db)):
    await ensure_admin_user(db)
    try:
        result = await rv_media.regenerate_all_thumbnails(db)
    except MediaValidationError as exception:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exception)) from exception
    return BaseHttpResponse.make().set_data(result).set_message("Thumbnails generated successfully.").to_dict()


@router.get("/api/status")
async def get_api_settings_status(db: AsyncSession = Depends(get_db)):
    await ensure_admin_user(db)
    values = await setting_store.all(db, flat=True)
    return api_settings_payload(values)


@router.get("/cache/status")
async def get_cache_settings_status(db: AsyncSession = Depends(get_db)):
    await ensure_admin_user(db)
    values = await setting_store.all(db, flat=True)
    return cache_settings_payload(values)


@router.get("/datatables/status")
async def get_datatables_settings_status(db: AsyncSession = Depends(get_db)):
    await ensure_admin_user(db)
    values = await setting_store.all(db, flat=True)
    return datatables_settings_payload(values)


@router.post("/api/generate-key")
async def generate_random_api_key(db: AsyncSession = Depends(get_db)):
    await ensure_admin_user(db)
    api_key = await save_generated_key(db)
    values = await setting_store.all(db, flat=True, force=True)
    return (
        BaseHttpResponse.make()
        .set_data({"apiKey": api_key, "status": api_settings_payload(values)})
        .set_message("API key generated successfully.")
        .to_dict()
    )


@router.post("/api/firebase-service-account")
async def upload_firebase_service_account(file: UploadFile = File(...), db: AsyncSession = Depends(get_db)):
    await ensure_admin_user(db)
    content = await file.read()
    try:
        result = await save_service_account(db, file.filename or "service-account.json", content)
    except APISettingsError as exception:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exception)) from exception
    values = await setting_store.all(db, flat=True, force=True)
    return (
        BaseHttpResponse.make()
        .set_data({"file": result, "status": api_settings_payload(values)})
        .set_message("Firebase service account uploaded successfully.")
        .to_dict()
    )


@router.post("/api/send-notification")
async def send_api_push_notification(payload: PushNotificationRequest, db: AsyncSession = Depends(get_db)):
    await ensure_admin_user(db)
    try:
        result = await send_push_notification(db, payload.model_dump())
    except APISettingsError as exception:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exception)) from exception
    return (
        BaseHttpResponse.make()
        .set_data(result.__dict__)
        .set_message("Notification sent successfully.")
        .to_dict()
    )


@router.get("/{section_id}")
async def get_setting_section(section_id: str, db: AsyncSession = Depends(get_db)):
    await ensure_admin_user(db)
    section = setting_panel_registry.get_section(section_id)
    if not section:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Setting section not found.")
    values = await setting_store.all(db, flat=True)
    return section.to_dict(values)


@router.put("/{section_id}")
async def update_setting_section(section_id: str, payload: SettingsUpdate, db: AsyncSession = Depends(get_db)):
    await ensure_admin_user(db)
    section = setting_panel_registry.get_section(section_id)
    if not section:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Setting section not found.")

    allowed = set(section.field_keys())
    incoming = {key: value for key, value in payload.settings.items() if key in allowed}
    ignored = sorted(set(payload.settings) - allowed)

    await _validate_settings(incoming)
    await setting_store.set(db, incoming, force=payload.force)
    await setting_store.save(db)
    values = await setting_store.all(db, flat=True, force=True)
    if section_id == "cache":
        await _sync_cache_aliases(db, values)
        values = await setting_store.all(db, flat=True, force=True)
    await apply_runtime_cache_settings(values)

    return (
        BaseHttpResponse.make()
        .set_data({"section": section.to_dict(values), "ignored": ignored})
        .with_updated_success_message()
        .to_dict()
    )


async def _validate_settings(values: dict[str, Any]) -> None:
    fields = setting_panel_registry.fields()
    errors: dict[str, str] = {}

    for key, value in values.items():
        field = fields.get(key)
        if not field:
            continue
        error = _validate_field(field, value)
        if error:
            errors[key] = error

    for key, value in values.items():
        field = fields.get(key)
        if not field:
            continue
        required_if = (field.rules or {}).get("required_if")
        if not isinstance(required_if, dict):
            continue
        dependency = str(required_if.get("field") or "")
        expected = required_if.get("equals", True)
        if dependency and _setting_values_match(values.get(dependency), expected) and _setting_value_is_empty(value):
            errors[key] = str(required_if.get("message") or "This setting is required.")

    errors.update(validate_email_rule_settings(values))
    errors.update(validate_phone_settings(values))
    errors.update(validate_media_settings(values))
    errors.update(validate_api_settings(values))
    errors.update(validate_cache_settings(values))
    errors.update(validate_datatables_settings(values))

    driver = str(values.get("email_driver") or "").lower()
    if driver:
        required_by_driver = {
            "smtp": ["email_host", "email_port"],
            "mailgun": ["email_mail_gun_domain", "email_mail_gun_secret", "email_mail_gun_endpoint"],
            "ses": ["email_ses_key", "email_ses_secret", "email_ses_region"],
            "postmark": ["email_postmark_token"],
            "resend": ["email_resend_key"],
            "log": ["email_log_channel"],
            "sendmail": ["email_sendmail_path"],
        }
        for key in required_by_driver.get(driver, []):
            if key in values and (values.get(key) is None or str(values.get(key)).strip() == ""):
                errors[key] = "This setting is required for the selected mailer."

    if errors:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, {"message": "Invalid settings.", "errors": errors})


def _setting_value_is_empty(value: Any) -> bool:
    return value is None or value == "" or value == []


def _setting_values_match(actual: Any, expected: Any) -> bool:
    if isinstance(expected, bool):
        normalized = actual if isinstance(actual, bool) else str(actual).strip().lower() in {"1", "true", "yes", "on"}
        return normalized is expected
    return str(actual) == str(expected)


async def _sync_cache_aliases(db: AsyncSession, values: dict[str, Any]) -> None:
    updates: dict[str, Any] = {}
    if "cache_sitemap_timeout_minutes" in values:
        try:
            updates["sitemap_cache_duration"] = str(int(values.get("cache_sitemap_timeout_minutes") or 60) * 60)
        except (TypeError, ValueError):
            pass
    if updates:
        await setting_store.set(db, updates, force=True)
        await setting_store.save(db)


def _validate_field(field: SettingField, value: Any) -> str | None:
    if field.required and (value is None or value == "" or value == []):
        return "This setting is required."
    if value is None or value == "":
        return None
    if field.key == "admin_email":
        emails = normalize_admin_emails(value)
        max_items = int(field.rules.get("max_items", 4))
        if len(emails) > max_items:
            return f"You can add maximum {max_items} emails."
        if any(not _valid_email(email) for email in emails):
            return "Every admin email must be a valid email address."
    if field.type == "email" and not _valid_email(str(value)):
        return "Invalid email address."
    if field.type == "number":
        try:
            float(value)
        except (TypeError, ValueError):
            return "Must be a number."
    if field.type == "select" and field.options:
        allowed = {str(option["value"]) for option in field.options}
        if str(value) not in allowed:
            return "Invalid option."
    rules = field.rules or {}
    if "max_length" in rules and len(str(value)) > int(rules["max_length"]):
        return f"Must be at most {rules['max_length']} characters."
    if "min" in rules:
        try:
            if float(value) < float(rules["min"]):
                return f"Must be at least {rules['min']}."
        except (TypeError, ValueError):
            return "Must be a number."
    if "max" in rules:
        try:
            if float(value) > float(rules["max"]):
                return f"Must be at most {rules['max']}."
        except (TypeError, ValueError):
            return "Must be a number."
    return None


def _valid_email(value: str) -> bool:
    return bool(re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", value))


def _is_base_partial(module: str, template: str) -> bool:
    return module == "base" and template in {"header", "footer"}


def _contains_partial_placeholder(body: str) -> bool:
    lowered = body.lower()
    return "{{ header }}" in lowered or "{{header}}" in lowered or "{{ footer }}" in lowered or "{{footer}}" in lowered
