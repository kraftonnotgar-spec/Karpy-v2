from __future__ import annotations

import importlib.util
import os
import platform
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from karpy_platform.core.base.hooks import hooks
from karpy_platform.core.setting.registry import SettingField, SettingSection, setting_panel_registry
from karpy_platform.core.setting.store import setting_store
from karpy_platform.packages.installer.constants import (
    INSTALLED_SESSION_NAME,
    INSTALLING_SESSION_NAME,
    INSTALLER_FILTER_REQUIREMENTS,
    INSTALLER_FILTER_STEPS,
    INSTALLER_PACKAGE_ID,
    INSTALLER_SETTING_COMPLETED,
    INSTALLER_SETTING_LICENSE_SKIPPED,
)


@dataclass
class InstallerStep:
    key: str
    label: str
    route: str
    priority: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "route": self.route,
            "priority": self.priority,
        }


class InstallerService:
    """API-first port of Botble's installer package."""

    minimum_python = (3, 11)
    required_modules = [
        "fastapi",
        "pydantic",
        "pydantic_settings",
        "sqlalchemy",
        "uvicorn",
    ]
    writable_paths = [
        "storage",
        "media",
        "karpy_platform",
        "karpy_platform/plugins",
        "karpy_platform/themes",
    ]

    def __init__(self) -> None:
        self._booted = False

    def boot(self) -> None:
        if self._booted:
            return
        setting_panel_registry.register_section(
            SettingSection(
                id="installer",
                title="Installer",
                description="First-run installation state, license reminder, and environment setup metadata.",
                icon="wrench",
                route="/install",
                priority=99997,
                group="settings.others",
                source="package:installer",
                hidden=True,
                fields=[
                    SettingField(INSTALLER_SETTING_COMPLETED, "Installation completed", type="switch", default="0"),
                    SettingField("installer.license_buyer", "License buyer", secret=True),
                    SettingField("installer.purchase_code", "Purchase code", type="password", secret=True),
                    SettingField(INSTALLER_SETTING_LICENSE_SKIPPED, "License skipped", type="switch", default="0"),
                ],
            )
        )
        self._booted = True

    async def status(self, db: AsyncSession) -> dict[str, Any]:
        installed = await self.is_installed(db)
        installing = self.installing_file.exists()
        return {
            "id": INSTALLER_PACKAGE_ID,
            "installed": installed,
            "installing": installing and not installed,
            "installedAt": self._read_text(self.installed_file),
            "installingAt": self._read_text(self.installing_file),
            "steps": await self.steps(),
            "requirements": await self.requirements(),
        }

    async def is_installed(self, db: AsyncSession) -> bool:
        setting_value = await setting_store.get(db, INSTALLER_SETTING_COMPLETED, "0")
        if str(setting_value) == "1" or self.installed_file.exists():
            return True

        try:
            from karpy_platform.core.acl.models import User

            user_count = await db.scalar(select(func.count()).select_from(User))
            return bool(user_count)
        except Exception:
            return False

    async def steps(self) -> list[dict[str, Any]]:
        steps = {
            "welcome": InstallerStep("welcome", "Welcome", "/install/welcome", 10),
            "requirements": InstallerStep("requirements", "Requirements", "/install/requirements", 20),
            "environment": InstallerStep("environment", "Environment", "/install/environment", 30),
            "account": InstallerStep("account", "Create Account", "/install/account", 50),
            "license": InstallerStep("license", "License", "/install/license", 60),
            "final": InstallerStep("final", "Final", "/install/final", 70),
        }
        filtered = await hooks.apply_filters_async(INSTALLER_FILTER_STEPS, steps)
        return [
            item.to_dict()
            for item in sorted(filtered.values(), key=lambda step: (step.priority, step.label))
        ]

    async def requirements(self) -> dict[str, Any]:
        python_supported = sys.version_info >= self.minimum_python
        modules = {
            module: importlib.util.find_spec(module) is not None
            for module in self._required_modules()
        }
        permissions = {
            relative: self._is_writable(settings.BASE_DIR / relative)
            for relative in self.writable_paths
        }
        requirements = {
            "python": {
                "full": platform.python_version(),
                "current": ".".join(map(str, sys.version_info[:3])),
                "minimum": ".".join(map(str, self.minimum_python)),
                "supported": python_supported,
            },
            "modules": modules,
            "permissions": permissions,
            "database": {
                "urlConfigured": bool(settings.DATABASE_URL),
                "driver": settings.DATABASE_URL.split(":", 1)[0] if settings.DATABASE_URL else "",
            },
        }
        errors = (
            not python_supported
            or not all(modules.values())
            or not all(permissions.values())
            or not bool(settings.DATABASE_URL)
        )
        payload = {"errors": errors, "requirements": requirements}
        return await hooks.apply_filters_async(INSTALLER_FILTER_REQUIREMENTS, payload)

    async def save_environment(self, db: AsyncSession, values: dict[str, Any]) -> dict[str, Any]:
        env_values = {
            "APP_NAME": values.get("app_name"),
            "APP_URL": values.get("app_url"),
            "APP_ENV": values.get("app_env"),
            "DEBUG": values.get("debug"),
            "DATABASE_URL": values.get("database_url"),
            "ADMIN_DIR": values.get("admin_dir"),
        }
        written = self.write_env({key: value for key, value in env_values.items() if value is not None})
        await setting_store.set(
            db,
            {
                "installer.environment_saved": "1",
                "installer.app_name": values.get("app_name", settings.APP_NAME),
                "installer.app_url": values.get("app_url", settings.APP_URL),
                "installer.database_driver": self._database_driver(str(values.get("database_url", settings.DATABASE_URL))),
            },
        )
        await setting_store.save(db)
        self.mark_installing()
        return {
            "written": written,
            "envPath": str(self.env_file),
            "restartRequired": True,
            "message": "Environment saved. Restart the app to use changed runtime values.",
        }

    async def save_license(self, db: AsyncSession, buyer: str | None, purchase_code: str | None, skipped: bool = False) -> None:
        await setting_store.force_set(
            db,
            {
                "installer.license_buyer": buyer or "",
                "installer.purchase_code": purchase_code or "",
                "installer.license_skipped": "1" if skipped else "0",
            },
        )
        await setting_store.save(db)

    async def finish(self, db: AsyncSession) -> dict[str, Any]:
        if self.installing_file.exists():
            self.installing_file.unlink()
        self._write_marker(self.installed_file)
        await setting_store.set(db, INSTALLER_SETTING_COMPLETED, "1")
        await setting_store.save(db)
        return {
            "installed": True,
            "installedAt": self._read_text(self.installed_file),
        }

    def mark_installing(self) -> None:
        self._write_marker(self.installing_file)

    def write_env(self, values: dict[str, Any]) -> bool:
        self.env_file.parent.mkdir(parents=True, exist_ok=True)
        existing = self._parse_env(self.env_file.read_text(encoding="utf-8") if self.env_file.exists() else "")
        for key, value in values.items():
            existing[key] = self._format_env_value(value)
        content = "\n".join(f"{key}={value}" for key, value in existing.items()) + "\n"
        self.env_file.write_text(content, encoding="utf-8")
        return True

    @property
    def storage_dir(self) -> Path:
        path = settings.BASE_DIR / "storage"
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def installed_file(self) -> Path:
        return self.storage_dir / INSTALLED_SESSION_NAME

    @property
    def installing_file(self) -> Path:
        return self.storage_dir / INSTALLING_SESSION_NAME

    @property
    def env_file(self) -> Path:
        return settings.BASE_DIR / ".env"

    def _write_marker(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(datetime.now(timezone.utc).isoformat(), encoding="utf-8")

    def _read_text(self, path: Path) -> str | None:
        if not path.exists():
            return None
        return path.read_text(encoding="utf-8").strip()

    def _is_writable(self, path: Path) -> bool:
        path.mkdir(parents=True, exist_ok=True)
        return os.access(path, os.W_OK)

    def _parse_env(self, content: str) -> dict[str, str]:
        parsed: dict[str, str] = {}
        for line in content.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            parsed[key.strip()] = value.strip()
        return parsed

    def _format_env_value(self, value: Any) -> str:
        if isinstance(value, bool):
            return "true" if value else "false"
        text = str(value).replace('"', "")
        if any(char.isspace() for char in text):
            return f'"{text}"'
        return text

    def _database_driver(self, database_url: str) -> str:
        return database_url.split(":", 1)[0] if database_url else ""

    def _required_modules(self) -> list[str]:
        modules = list(self.required_modules)
        database_url = settings.DATABASE_URL or ""
        if database_url.startswith("postgresql"):
            modules.append("asyncpg")
        elif database_url.startswith("sqlite"):
            modules.append("aiosqlite")
        return modules


installer_service = InstallerService()


def boot_installer_package() -> None:
    installer_service.boot()
