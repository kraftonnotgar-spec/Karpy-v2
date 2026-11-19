from __future__ import annotations

import json
import os
import platform
import re
import shutil
import socket
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from karpy_platform.core.manifest import read_core_json


@dataclass(frozen=True)
class InfoRow:
    label: str
    value: Any
    status: str | None = None
    copyable: bool = False


class SystemInformationService:
    """Collects Python-native troubleshooting information for the admin panel."""

    excluded_size_dirs = {".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache", "test-results"}
    cache_ttl_seconds = 30

    async def payload(self, db: AsyncSession) -> dict[str, Any]:
        cached = getattr(self, "_cached_payload", None)
        if cached and time.monotonic() - cached["time"] < self.cache_ttl_seconds:
            return cached["payload"]

        database = await self.database_environment(db)
        packages = self.installed_packages()
        payload = {
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "app": {
                "name": settings.APP_NAME,
                "version": settings.APP_VERSION,
                "environment": settings.APP_ENV,
                "url": settings.APP_URL,
            },
            "packages": packages,
            "summary": {
                "packages": len(packages),
                "python": platform.python_version(),
                "framework": self.package_version("fastapi"),
                "database": database.get("driver") or database.get("dialect"),
            },
            "systemEnvironment": self.serialize_rows(self.system_environment()),
            "serverEnvironment": self.serialize_rows(self.server_environment()),
            "pythonEnvironment": self.serialize_rows(self.python_environment(packages)),
            "databaseEnvironment": self.serialize_rows(database["rows"]),
            "storageEnvironment": self.serialize_rows(self.storage_environment()),
        }
        self._cached_payload = {"time": time.monotonic(), "payload": payload}
        return payload

    def report_bytes(self, payload: dict[str, Any]) -> bytes:
        return json.dumps(payload, ensure_ascii=False, indent=2, default=str).encode("utf-8")

    def installed_packages(self) -> list[dict[str, Any]]:
        packages: list[dict[str, Any]] = []
        for distribution in metadata.distributions():
            name = distribution.metadata.get("Name") or distribution.name
            if not name:
                continue
            dependencies = [self.dependency_payload(requirement) for requirement in distribution.requires or []]
            packages.append(
                {
                    "name": name,
                    "version": distribution.version,
                    "dependencies": [dependency for dependency in dependencies if dependency],
                }
            )
        return sorted(packages, key=lambda item: item["name"].lower())

    def dependency_payload(self, requirement: str) -> dict[str, str] | None:
        clean = requirement.split(";", 1)[0].strip()
        if not clean:
            return None
        name = re.split(r"[\s<>=!~\[]+", clean, maxsplit=1)[0].strip()
        if not name:
            return None
        specifier = clean.removeprefix(name).strip()
        installed = self.package_version(name)
        return {
            "name": name,
            "version": installed or specifier or "*",
            "requirement": clean,
        }

    def system_environment(self) -> list[InfoRow]:
        core = read_core_json()
        return [
            InfoRow("CMS Version", settings.APP_VERSION),
            InfoRow("Core Version", core.get("version") or settings.APP_VERSION),
            InfoRow("Framework Version", self.package_version("fastapi") or "Unknown"),
            InfoRow("Timezone", datetime.now().astimezone().tzname() or "Local"),
            InfoRow("Server IP", self.server_ip(), copyable=True),
            InfoRow("App URL", settings.APP_URL, copyable=True),
            InfoRow("Public Site URL", settings.site_url, copyable=True),
            InfoRow("User Dashboard URL", settings.user_dashboard_url, copyable=True),
            InfoRow("Environment", settings.APP_ENV),
            InfoRow("Debug Mode", settings.DEBUG, status="success" if not settings.DEBUG else "warning"),
            InfoRow("Storage Dir Writable", self.is_writable(settings.STORAGE_DIR), status="success"),
            InfoRow("Cache Dir Writable", self.is_writable(settings.STORAGE_DIR / "framework" / "cache"), status="success"),
            InfoRow("App Size", self.human_size(self.app_size())),
        ]

    def server_environment(self) -> list[InfoRow]:
        disk = shutil.disk_usage(settings.BASE_DIR)
        memory = self.memory_summary()
        return [
            InfoRow("Python Version", platform.python_version(), status="success"),
            InfoRow("Uvicorn Version", self.package_version("uvicorn") or "Not installed"),
            InfoRow("Operating System", f"{platform.system()} {platform.release()}"),
            InfoRow("OS Version", platform.version()),
            InfoRow("Machine", platform.machine() or "Unknown"),
            InfoRow("Processor", platform.processor() or "Unknown"),
            InfoRow("CPU Count", os.cpu_count() or "Unknown"),
            InfoRow("Memory", memory),
            InfoRow("Disk Total", self.human_size(disk.total)),
            InfoRow("Disk Free", self.human_size(disk.free), status="success" if disk.free > 200 * 1024 * 1024 else "warning"),
        ]

    def python_environment(self, packages: list[dict[str, Any]]) -> list[InfoRow]:
        return [
            InfoRow("Executable", sys.executable, copyable=True),
            InfoRow("Prefix", sys.prefix, copyable=True),
            InfoRow("Virtual Environment", sys.prefix != sys.base_prefix, status="success" if sys.prefix != sys.base_prefix else "warning"),
            InfoRow("Pip Version", self.package_version("pip") or "Not installed"),
            InfoRow("Packages Installed", len(packages)),
            InfoRow("Import Path Entries", len(sys.path)),
            InfoRow("Default Encoding", sys.getdefaultencoding()),
            InfoRow("Filesystem Encoding", sys.getfilesystemencoding()),
        ]

    async def database_environment(self, db: AsyncSession) -> dict[str, Any]:
        parsed = make_url(settings.DATABASE_URL)
        dialect = parsed.get_backend_name()
        driver = parsed.get_driver_name()
        database_version = "Unknown"
        status = "warning"
        try:
            statement = text("select sqlite_version()") if dialect == "sqlite" else text("select version()")
            result = await db.execute(statement)
            database_version = str(result.scalar_one_or_none() or "Unknown")
            status = "success"
        except Exception as exception:
            database_version = f"Unavailable: {exception.__class__.__name__}"

        rows = [
            InfoRow("Dialect", dialect),
            InfoRow("Driver", driver or "default"),
            InfoRow("Database Version", database_version, status=status),
            InfoRow("Connection URL", parsed.render_as_string(hide_password=True), copyable=True),
        ]

        if dialect == "sqlite":
            sqlite_path = self.sqlite_path(parsed.database)
            rows.extend(
                [
                    InfoRow("Database File", str(sqlite_path), copyable=True),
                    InfoRow("Database File Size", self.human_size(sqlite_path.stat().st_size) if sqlite_path.exists() else "Missing", status="success" if sqlite_path.exists() else "warning"),
                    InfoRow("Database Writable", self.is_writable(sqlite_path.parent), status="success"),
                ]
            )
        else:
            rows.extend(
                [
                    InfoRow("Host", parsed.host or "Default"),
                    InfoRow("Port", parsed.port or "Default"),
                    InfoRow("Database Name", parsed.database or "Default"),
                ]
            )

        return {"dialect": dialect, "driver": driver, "rows": rows}

    def storage_environment(self) -> list[InfoRow]:
        storage_paths = [
            ("Base Directory", settings.BASE_DIR),
            ("Platform Directory", settings.PLATFORM_DIR),
            ("Plugins Directory", settings.PLUGINS_DIR),
            ("Themes Directory", settings.THEMES_DIR),
            ("Media Directory", settings.MEDIA_DIR),
            ("Storage Directory", settings.BASE_DIR / "storage"),
            ("Public Directory", settings.BASE_DIR / "public"),
            ("Logs Directory", settings.BASE_DIR / "storage" / "logs"),
            ("Backup Directory", settings.BASE_DIR / "storage" / "backups"),
        ]
        rows = []
        for label, path in storage_paths:
            exists = path.exists()
            rows.append(InfoRow(label, str(path), status="success" if exists and self.is_writable(path) else "warning", copyable=True))
        return rows

    def serialize_rows(self, rows: list[InfoRow]) -> list[dict[str, Any]]:
        return [
            {
                "label": row.label,
                "value": row.value,
                "status": row.status,
                "copyable": row.copyable,
            }
            for row in rows
        ]

    def package_version(self, name: str) -> str | None:
        try:
            return metadata.version(name)
        except metadata.PackageNotFoundError:
            return None

    def server_ip(self) -> str:
        try:
            return socket.gethostbyname(socket.gethostname())
        except OSError:
            return "127.0.0.1"

    def sqlite_path(self, database: str | None) -> Path:
        if not database:
            return settings.BASE_DIR / "karpy.db"
        path = Path(database)
        if not path.is_absolute():
            path = settings.BASE_DIR / path
        return path.resolve()

    def is_writable(self, path: Path) -> bool:
        target = path if path.suffix == "" else path.parent
        try:
            target.mkdir(parents=True, exist_ok=True)
            test_file = target / ".karpy-write-test"
            test_file.write_text("ok", encoding="utf-8")
            test_file.unlink(missing_ok=True)
            return True
        except OSError:
            return False

    def path_size(self, path: Path) -> int:
        if path.is_file():
            return path.stat().st_size
        if not path.exists():
            return 0
        total = 0
        for item in path.rglob("*"):
            if any(part in self.excluded_size_dirs for part in item.parts):
                continue
            if item.is_file():
                try:
                    total += item.stat().st_size
                except OSError:
                    continue
        return total

    def app_size(self) -> int:
        total = 0
        targets = [
            settings.BASE_DIR / "app",
            settings.PLATFORM_DIR,
            settings.BASE_DIR / "public",
            settings.BASE_DIR / "media",
            settings.BASE_DIR / "storage",
            settings.BASE_DIR / "requirements.txt",
            settings.BASE_DIR / ".env.example",
            settings.BASE_DIR / "admin-ui" / "src",
            settings.BASE_DIR / "admin-ui" / "package.json",
        ]
        for target in targets:
            total += self.path_size(target)
        return total

    def human_size(self, size: int) -> str:
        value = float(size)
        for unit in ("B", "KB", "MB", "GB", "TB"):
            if value < 1024 or unit == "TB":
                return f"{value:.2f} {unit}".replace(".00", "")
            value /= 1024
        return f"{size} B"

    def memory_summary(self) -> str:
        try:
            import psutil

            memory = psutil.virtual_memory()
            return f"{self.human_size(memory.total)} total / {self.human_size(memory.available)} available"
        except Exception:
            return "psutil not installed"


system_information_service = SystemInformationService()
