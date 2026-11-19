from __future__ import annotations

import json
import os
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.config import settings


@dataclass(frozen=True)
class SecurityHeader:
    name: str
    value: str
    description: str


class SecurityService:
    """Runtime security configuration, headers, and suspicious request analysis."""

    suspicious_patterns = {
        "sql-injection": ("select%20", "union%20", "sleep(", "benchmark(", "' or ", "\" or ", "information_schema"),
        "xss": ("<script", "%3cscript", "javascript:", "onerror=", "onload="),
        "path-traversal": ("../", "..\\", "%2e%2e", "/etc/passwd", "win.ini"),
        "scanner": ("wp-admin", "wp-login", ".env", "phpmyadmin", "vendor/phpunit", "xmlrpc.php"),
    }

    def __init__(self, events_path: Path | None = None) -> None:
        self.events_path = events_path or settings.STORAGE_DIR / "security_events.jsonl"

    def dashboard(self) -> dict[str, Any]:
        settings_rows = self.security_settings()
        events = self.recent_events()
        severity_counts = Counter(event["severity"] for event in events)
        type_counts = Counter(event["type"] for event in events)
        failing = [row for row in settings_rows if not row["passed"]]
        return {
            "summary": {
                "configured": len(failing) == 0,
                "score": round(((len(settings_rows) - len(failing)) / max(len(settings_rows), 1)) * 100),
                "passed": len(settings_rows) - len(failing),
                "failed": len(failing),
                "events": len(events),
                "highRiskEvents": severity_counts.get("high", 0),
                "message": "All security settings are properly configured!" if not failing else f"{len(failing)} security {'setting needs' if len(failing) == 1 else 'settings need'} attention.",
            },
            "settings": settings_rows,
            "headers": [header.__dict__ for header in self.security_headers()],
            "events": events[:25],
            "analysis": {
                "bySeverity": dict(severity_counts),
                "byType": dict(type_counts),
                "topIps": Counter(event["ip"] for event in events).most_common(8),
            },
            "commands": self.monitor_commands(),
        }

    def security_settings(self) -> list[dict[str, Any]]:
        app_url_is_https = settings.APP_URL.lower().startswith("https://")
        production = settings.is_production
        secure_cookie_recommended = production or app_url_is_https
        cors_origins = [origin.strip() for origin in settings.CORS_ALLOWED_ORIGINS.split(",") if origin.strip()]
        rows = [
            self._row(
                "session_http_only",
                "HttpOnly Cookie Flag",
                "Prevents JavaScript from accessing session cookies.",
                settings.SESSION_HTTP_ONLY,
                True,
            ),
            self._row(
                "session_secure_cookie",
                "Secure Cookie Flag",
                "Ensures cookies are only sent over HTTPS connections.",
                settings.secure_cookies,
                secure_cookie_recommended,
                "Required when APP_ENV=production or APP_URL uses HTTPS.",
            ),
            self._row(
                "session_same_site",
                "SameSite Cookie Flag",
                "Restricts cross-site cookie usage to reduce CSRF risk.",
                settings.SESSION_SAME_SITE.lower(),
                "lax",
            ),
            self._row(
                "security_headers",
                "HTTP Security Headers",
                "Adds security headers to protect against common web vulnerabilities.",
                settings.ENABLE_HTTP_SECURITY_HEADERS,
                True,
            ),
            self._row(
                "cors_origins",
                "Restricted CORS Origins",
                "Limits browser API calls to trusted frontend origins.",
                ", ".join(cors_origins) or "*",
                "not *",
                "Set CORS_ALLOWED_ORIGINS to your admin/frontend domains in production.",
                passed="*" not in cors_origins and bool(cors_origins),
            ),
            self._row(
                "debug_mode",
                "Debug Mode",
                "Disables verbose debug output in production.",
                settings.DEBUG,
                False,
                "Keep DEBUG=false in production.",
                passed=not production or not settings.DEBUG,
            ),
            self._row(
                "secret_key",
                "Application Secret Key",
                "Uses a non-default secret for signing sessions and tokens.",
                "custom" if not self._uses_default_secret() else "default development secret",
                "custom",
                "Change SECRET_KEY and JWT_SECRET before production.",
                passed=not self._uses_default_secret(),
            ),
        ]
        return rows

    def security_headers(self) -> list[SecurityHeader]:
        headers = [
            SecurityHeader("X-Content-Type-Options", "nosniff", "Prevents browsers from guessing content types."),
            SecurityHeader("X-Frame-Options", "SAMEORIGIN", "Protects against clickjacking attacks."),
            SecurityHeader("X-XSS-Protection", "1; mode=block", "Enables legacy browser XSS protection."),
            SecurityHeader("Referrer-Policy", "strict-origin-when-cross-origin", "Controls how much referrer information is sent."),
            SecurityHeader("Permissions-Policy", "geolocation=(), microphone=(), camera=()", "Restricts sensitive browser capabilities by default."),
        ]
        if settings.APP_URL.lower().startswith("https://") or settings.APP_ENV.lower() == "production":
            headers.append(SecurityHeader("Strict-Transport-Security", "max-age=31536000; includeSubDomains", "Forces browsers to use HTTPS after first secure visit."))
        return headers

    def apply_headers(self, response) -> None:
        if not settings.ENABLE_HTTP_SECURITY_HEADERS:
            return
        for header in self.security_headers():
            response.headers.setdefault(header.name, header.value)

    def inspect_request(self, request: Request) -> None:
        attack_type = self.classify_request(str(request.url.path), str(request.url.query))
        if not attack_type:
            return
        self.record_event({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "type": attack_type,
            "severity": "high" if attack_type in {"sql-injection", "xss", "path-traversal"} else "medium",
            "ip": self.client_ip(request),
            "method": request.method,
            "path": request.url.path,
            "query": str(request.url.query)[:500],
            "userAgent": request.headers.get("user-agent", "")[:300],
        })

    def inspect_response(self, request: Request, response: Response) -> None:
        if response.status_code >= 500:
            self.record_event({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "type": "api-error",
                "severity": "high",
                "ip": self.client_ip(request),
                "method": request.method,
                "path": request.url.path,
                "query": str(request.url.query)[:500],
                "statusCode": response.status_code,
                "userAgent": request.headers.get("user-agent", "")[:300],
            })
            return
        if response.status_code in {401, 403, 429}:
            self.record_event({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "type": "blocked-request",
                "severity": "medium" if response.status_code != 403 else "high",
                "ip": self.client_ip(request),
                "method": request.method,
                "path": request.url.path,
                "query": str(request.url.query)[:500],
                "statusCode": response.status_code,
                "userAgent": request.headers.get("user-agent", "")[:300],
            })

    def inspect_exception(self, request: Request, exc: Exception) -> None:
        self.record_event({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "type": "api-error",
            "severity": "high",
            "ip": self.client_ip(request),
            "method": request.method,
            "path": request.url.path,
            "query": str(request.url.query)[:500],
            "errorClass": type(exc).__name__,
            "userAgent": request.headers.get("user-agent", "")[:300],
        })

    def classify_request(self, path: str, query: str = "") -> str | None:
        haystack = f"{path}?{query}".lower()
        for attack_type, patterns in self.suspicious_patterns.items():
            if any(pattern in haystack for pattern in patterns):
                return attack_type
        return None

    def record_event(self, event: dict[str, Any]) -> None:
        self.events_path.parent.mkdir(parents=True, exist_ok=True)
        with self.events_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=True) + "\n")

    def recent_events(self, limit: int = 200) -> list[dict[str, Any]]:
        try:
            lines = self.events_path.read_text(encoding="utf-8").splitlines()[-limit:]
        except OSError:
            return []
        events: list[dict[str, Any]] = []
        for line in reversed(lines):
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return events

    def monitor_commands(self) -> dict[str, str]:
        relative = self.events_path.relative_to(settings.BASE_DIR) if self.events_path.is_relative_to(settings.BASE_DIR) else self.events_path
        return {
            "windows": f"Get-Content -Path {relative} -Wait -Tail 50",
            "linux": f"tail -f {relative}",
            "powershell": f"Get-Content -Path {relative} -Wait -Tail 50",
        }

    def client_ip(self, request: Request) -> str:
        # Uvicorn normalizes this only for peers listed in FORWARDED_ALLOW_IPS.
        # Never trust a client-supplied forwarding header again at app level.
        return request.client.host if request.client else "unknown"

    def _row(
        self,
        key: str,
        name: str,
        description: str,
        current: Any,
        recommended: Any,
        note: str = "",
        passed: bool | None = None,
    ) -> dict[str, Any]:
        return {
            "key": key,
            "name": name,
            "description": description,
            "current": current,
            "recommended": recommended,
            "passed": current == recommended if passed is None else passed,
            "note": note,
        }

    def _uses_default_secret(self) -> bool:
        default_values = {"karpy-dev-secret-change-me-in-production", "karpy-jwt-secret-change-me", ""}
        return settings.SECRET_KEY in default_values or settings.JWT_SECRET in default_values


security_service = SecurityService()


class SecurityMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        security_service.inspect_request(request)
        try:
            response = await call_next(request)
        except Exception as exc:
            security_service.inspect_exception(request, exc)
            raise
        security_service.inspect_response(request, response)
        security_service.apply_headers(response)
        return response
