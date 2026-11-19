from __future__ import annotations

import json
import re
import shutil
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote

from app.config import settings


@dataclass
class BackupCreateData:
    name: str
    description: str | None = None
    database_only: bool = False


class BackupService:
    """Small Botble-style backup manager for database and local uploads."""

    def __init__(self, backup_dir: Path | None = None) -> None:
        self.backup_dir = backup_dir or settings.STORAGE_DIR / "backups"

    def list(self) -> list[dict]:
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        backups = [self.payload(path) for path in self.backup_dir.glob("*.zip")]
        return sorted(backups, key=lambda item: item["createdAt"], reverse=True)

    def create(self, data: BackupCreateData) -> dict:
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        created_at = datetime.now(timezone.utc)
        stem = f"{created_at.strftime('%Y%m%d%H%M%S')}-{self._slug(data.name)}"
        path = self.backup_dir / f"{stem}.zip"
        database_path = self.sqlite_database_path()
        manifest = {
            "name": data.name.strip(),
            "description": data.description or "",
            "databaseOnly": data.database_only,
            "createdAt": created_at.isoformat(),
            "database": str(database_path.relative_to(settings.BASE_DIR)) if database_path and database_path.exists() else None,
            "media": None if data.database_only else str(settings.MEDIA_DIR.relative_to(settings.BASE_DIR)),
            "version": 1,
        }

        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("manifest.json", json.dumps(manifest, indent=2))
            if database_path and database_path.exists():
                archive.write(database_path, "database/karpy.db")
            if not data.database_only and settings.MEDIA_DIR.exists():
                for file_path in settings.MEDIA_DIR.rglob("*"):
                    if file_path.is_file():
                        archive.write(file_path, Path("media") / file_path.relative_to(settings.MEDIA_DIR))

        return self.payload(path)

    def payload(self, path: Path) -> dict:
        manifest = self.manifest(path)
        created_at = manifest.get("createdAt") or datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()
        return {
            "id": path.name,
            "name": manifest.get("name") or path.stem,
            "description": manifest.get("description") or "",
            "size": path.stat().st_size,
            "humanSize": self.human_size(path.stat().st_size),
            "createdAt": created_at,
            "databaseOnly": bool(manifest.get("databaseOnly")),
            "filename": path.name,
        }

    def manifest(self, path: Path) -> dict:
        try:
            with zipfile.ZipFile(path) as archive:
                with archive.open("manifest.json") as manifest_file:
                    return json.loads(manifest_file.read().decode("utf-8"))
        except (KeyError, json.JSONDecodeError, zipfile.BadZipFile, OSError):
            return {}

    def delete(self, filename: str) -> None:
        path = self.path_for(filename)
        if path.exists():
            path.unlink()

    def restore(self, filename: str) -> dict:
        path = self.path_for(filename)
        restored = {"database": False, "media": False}
        database_path = self.sqlite_database_path()
        with zipfile.ZipFile(path) as archive:
            if database_path and "database/karpy.db" in archive.namelist():
                database_path.parent.mkdir(parents=True, exist_ok=True)
                with archive.open("database/karpy.db") as source, database_path.open("wb") as target:
                    shutil.copyfileobj(source, target)
                restored["database"] = True
            media_members = [member for member in archive.namelist() if member.startswith("media/") and not member.endswith("/")]
            if media_members:
                settings.MEDIA_DIR.mkdir(parents=True, exist_ok=True)
                for member in media_members:
                    target = self._safe_extract_target(settings.MEDIA_DIR, member.removeprefix("media/"))
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(member) as source, target.open("wb") as output:
                        shutil.copyfileobj(source, output)
                restored["media"] = True
        return restored

    def path_for(self, filename: str) -> Path:
        safe_name = Path(unquote(filename)).name
        if not safe_name.endswith(".zip"):
            safe_name = f"{safe_name}.zip"
        path = (self.backup_dir / safe_name).resolve()
        root = self.backup_dir.resolve()
        if root not in path.parents and path != root:
            raise ValueError("Invalid backup path.")
        if not path.exists():
            raise FileNotFoundError("Backup not found.")
        return path

    def sqlite_database_path(self) -> Path | None:
        database_url = settings.DATABASE_URL
        if not database_url.startswith("sqlite"):
            return None
        raw_path = database_url.split(":///", 1)[-1]
        path = Path(raw_path)
        if not path.is_absolute():
            path = settings.BASE_DIR / raw_path
        return path.resolve()

    def human_size(self, size: int) -> str:
        value = float(size)
        for unit in ("B", "KB", "MB", "GB"):
            if value < 1024 or unit == "GB":
                return f"{value:.2f} {unit}".replace(".00", "")
            value /= 1024
        return f"{size} B"

    def _safe_extract_target(self, root: Path, relative_name: str) -> Path:
        target = (root / relative_name).resolve()
        resolved_root = root.resolve()
        if resolved_root not in target.parents and target != resolved_root:
            raise ValueError("Backup contains an unsafe media path.")
        return target

    def _slug(self, value: str) -> str:
        slug = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
        return slug or "backup"


backup_service = BackupService()
