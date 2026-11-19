from __future__ import annotations

import json
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import HTTPException, status
from fastapi.responses import JSONResponse
import jwt
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from app.config import settings as app_settings
from app.database import async_session
from karpy_platform.core.setting.store import setting_store


FIREBASE_SCOPE = "https://www.googleapis.com/auth/firebase.messaging"
FIREBASE_TOKEN_URL = "https://oauth2.googleapis.com/token"


class APISettingsError(Exception):
    pass


@dataclass
class NotificationResult:
    provider: str
    message_id: str | None = None
    target: str | None = None


def is_truthy(value: Any, default: bool = False) -> bool:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on", "enabled"}


def api_settings_payload(values: dict[str, Any]) -> dict[str, Any]:
    enabled = is_truthy(values.get("api_enabled"), default=True)
    api_key = str(values.get("api_key") or "").strip()
    push_enabled = is_truthy(values.get("api_push_enabled"), default=False)
    project_id = str(values.get("api_firebase_project_id") or "").strip()
    service_account_path = str(values.get("api_firebase_service_account_path") or "").strip()
    service_account_exists = bool(service_account_path and _service_account_file(service_account_path).exists())
    return {
        "enabled": enabled,
        "keyProtected": bool(api_key),
        "pushEnabled": push_enabled,
        "firebaseProjectId": project_id,
        "serviceAccountPath": service_account_path,
        "serviceAccountExists": service_account_exists,
        "siteUrl": app_settings.site_url,
        "docsUrl": "/docs",
        "publicExamples": {
            "pages": "/api/pages",
            "pageBySlug": "/api/pages/about-us",
        },
        "warnings": _api_warnings(enabled, api_key, push_enabled, project_id, service_account_exists),
    }


def validate_api_settings(values: dict[str, Any]) -> dict[str, str]:
    errors: dict[str, str] = {}
    api_key = str(values.get("api_key") or "").strip()
    if api_key and len(api_key) < 16:
        errors["api_key"] = "API key must be at least 16 characters."
    service_account_path = str(values.get("api_firebase_service_account_path") or "").strip()
    if service_account_path and not service_account_path.endswith(".json"):
        errors["api_firebase_service_account_path"] = "Service account file must be a JSON file."
    project_id = str(values.get("api_firebase_project_id") or "").strip()
    if project_id and not all(char.isalnum() or char in {"-", ":"} for char in project_id):
        errors["api_firebase_project_id"] = "Firebase project ID contains invalid characters."
    return errors


def generate_api_key() -> str:
    return f"karpy_{secrets.token_urlsafe(36)}"


async def save_generated_key(db: AsyncSession) -> str:
    api_key = generate_api_key()
    await setting_store.set(db, {"api_key": api_key})
    await setting_store.save(db)
    return api_key


async def save_service_account(db: AsyncSession, filename: str, content: bytes) -> dict[str, Any]:
    if not filename.lower().endswith(".json"):
        raise APISettingsError("Service account file must be a JSON file.")
    try:
        decoded = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exception:
        raise APISettingsError("Service account file contains invalid JSON.") from exception

    missing = [key for key in ["project_id", "client_email", "private_key"] if not decoded.get(key)]
    if missing:
        raise APISettingsError(f"Service account JSON is missing: {', '.join(missing)}.")

    destination = _service_account_file("firebase/service-account.json")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(json.dumps(decoded, indent=2).encode("utf-8"))
    settings_payload = {
        "api_firebase_service_account_path": "firebase/service-account.json",
        "api_firebase_project_id": decoded.get("project_id") or "",
    }
    await setting_store.set(db, settings_payload)
    await setting_store.save(db)
    return {
        "path": settings_payload["api_firebase_service_account_path"],
        "projectId": settings_payload["api_firebase_project_id"],
        "clientEmail": decoded.get("client_email"),
    }


async def send_push_notification(db: AsyncSession, payload: dict[str, Any]) -> NotificationResult:
    values = await setting_store.all(db, flat=True)
    if not is_truthy(values.get("api_push_enabled"), default=False):
        raise APISettingsError("Push notifications are disabled.")

    title = str(payload.get("title") or "").strip()
    message = str(payload.get("message") or "").strip()
    if not title:
        raise APISettingsError("Notification title is required.")
    if not message:
        raise APISettingsError("Notification message is required.")

    project_id = str(values.get("api_firebase_project_id") or "").strip()
    service_account_path = str(values.get("api_firebase_service_account_path") or "").strip()
    if not project_id or not service_account_path:
        raise APISettingsError("Firebase project ID and service account file are required.")

    service_account = _load_service_account(service_account_path)
    target = str(payload.get("target") or "all")
    data: dict[str, str] = {}
    if payload.get("actionUrl"):
        data["action_url"] = str(payload["actionUrl"])
    if payload.get("imageUrl"):
        data["image_url"] = str(payload["imageUrl"])

    message_payload: dict[str, Any] = {
        "notification": {"title": title, "body": message},
        "data": data,
    }
    tokens = _device_tokens(values)
    if target == "tokens" and tokens:
        message_payload["token"] = tokens[0]
    else:
        message_payload["topic"] = "all"

    access_token = _firebase_access_token(service_account)
    request_payload = json.dumps({"message": message_payload}).encode("utf-8")
    request = urllib.request.Request(
        f"https://fcm.googleapis.com/v1/projects/{project_id}/messages:send",
        data=request_payload,
        method="POST",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            result = json.loads(response.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exception:
        body = exception.read().decode("utf-8", errors="replace")
        raise APISettingsError(_google_error_message(body) or f"Firebase returned HTTP {exception.code}.") from exception
    except urllib.error.URLError as exception:
        raise APISettingsError(f"Could not connect to Firebase: {exception.reason}") from exception

    return NotificationResult(provider="firebase", message_id=result.get("name"), target=target)


class APIAccessMiddleware(BaseHTTPMiddleware):
    """Apply CMS API enable/key settings to public API routes."""

    async def dispatch(self, request: Request, call_next):
        if not self._should_check(request.url.path):
            return await call_next(request)
        try:
            async with async_session() as db:
                values = await setting_store.all(db, flat=True)
        except Exception:
            return await call_next(request)

        if not is_truthy(values.get("api_enabled"), default=True):
            return JSONResponse({"detail": "Public API access is disabled."}, status_code=status.HTTP_403_FORBIDDEN)

        api_key = str(values.get("api_key") or "").strip()
        if api_key:
            provided = request.headers.get("X-API-KEY") or request.query_params.get("api_key")
            if provided != api_key:
                return JSONResponse({"detail": "A valid X-API-KEY header is required."}, status_code=status.HTTP_401_UNAUTHORIZED)

        return await call_next(request)

    @staticmethod
    def _should_check(path: str) -> bool:
        if not path.startswith("/api"):
            return False
        exempt_prefixes = (
            "/api/admin",
            "/api/install",
            "/api/health",
            "/api/system",
        )
        return not path.startswith(exempt_prefixes)


def _api_warnings(enabled: bool, api_key: str, push_enabled: bool, project_id: str, service_account_exists: bool) -> list[str]:
    warnings: list[str] = []
    if not enabled:
        warnings.append("API is disabled. Public API endpoints will be inaccessible.")
    if enabled and not api_key:
        warnings.append("API key protection is disabled. Endpoints are publicly accessible.")
    if push_enabled and (not project_id or not service_account_exists):
        warnings.append("FCM project ID or service account is not configured. Push notifications will not work.")
    return warnings


def _service_account_file(path: str) -> Path:
    clean_path = Path(path.replace("\\", "/"))
    if clean_path.is_absolute():
        return clean_path
    return app_settings.STORAGE_DIR / "app" / clean_path


def _load_service_account(path: str) -> dict[str, Any]:
    service_account_path = _service_account_file(path)
    if not service_account_path.exists():
        raise APISettingsError("Firebase service account file was not found.")
    try:
        return json.loads(service_account_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exception:
        raise APISettingsError("Firebase service account file contains invalid JSON.") from exception


def _firebase_access_token(service_account: dict[str, Any]) -> str:
    now = int(time.time())
    assertion = jwt.encode(
        {
            "iss": service_account["client_email"],
            "scope": FIREBASE_SCOPE,
            "aud": FIREBASE_TOKEN_URL,
            "iat": now,
            "exp": now + 3600,
        },
        service_account["private_key"],
        algorithm="RS256",
    )
    request_body = urllib.parse.urlencode({
        "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
        "assertion": assertion,
    }).encode("utf-8")
    request = urllib.request.Request(
        FIREBASE_TOKEN_URL,
        data=request_body,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            result = json.loads(response.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exception:
        body = exception.read().decode("utf-8", errors="replace")
        raise APISettingsError(_google_error_message(body) or "Could not authenticate the Firebase service account.") from exception
    return str(result.get("access_token") or "")


def _device_tokens(values: dict[str, Any]) -> list[str]:
    raw = str(values.get("api_push_device_tokens") or "")
    return [item.strip() for item in raw.replace("\n", ",").split(",") if item.strip()]


def _google_error_message(body: str) -> str:
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return body[:500]
    error = payload.get("error")
    if isinstance(error, dict):
        return str(error.get("message") or error.get("status") or payload)
    return str(error or payload)
