from __future__ import annotations

import json
import re
import shutil
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import settings
from app.http_security import safe_upload_filename


@dataclass(frozen=True)
class UpdateStep:
    key: str
    title: str
    description: str


class SystemUpdaterService:
    """Local package based updater foundation for KARPy core releases."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or settings.STORAGE_DIR / "system-updates"
        self.packages_dir = self.root / "packages"
        self.staged_dir = self.root / "staged"
        self.backups_dir = self.root / "file-backups"
        self.state_path = self.root / "state.json"
        self.allowed_roots = {"app", "karpy_platform", "public", "admin-ui"}

    def status(self) -> dict[str, Any]:
        self.ensure_dirs()
        packages = self.scan_packages()
        latest = packages[0] if packages else None
        current_version = settings.APP_VERSION
        update_available = bool(latest and self.version_gt(latest["version"], current_version))
        state = self.read_state()
        return {
            "currentVersion": current_version,
            "latestVersion": latest["version"] if latest else current_version,
            "updateAvailable": update_available,
            "enabled": self.enabled(),
            "packageDirectory": str(self.packages_dir),
            "stagedDirectory": str(self.staged_dir),
            "packages": packages,
            "selectedPackage": latest,
            "lastCheckedAt": state.get("lastCheckedAt"),
            "lastAction": state.get("lastAction"),
            "warnings": self.warnings(),
            "steps": [step.__dict__ for step in self.steps()],
            "changelog": latest.get("changelog") if latest else self.default_changelog(),
        }

    def check(self) -> dict[str, Any]:
        state = self.read_state()
        state["lastCheckedAt"] = datetime.now(timezone.utc).isoformat()
        self.write_state(state)
        return self.status()

    def upload(self, filename: str, contents: bytes) -> dict[str, Any]:
        self.ensure_dirs()
        safe_name = self.safe_filename(filename)
        if not safe_name.endswith(".zip"):
            raise ValueError("Only .zip update packages are supported.")
        path = self.packages_dir / safe_name
        path.write_bytes(contents)
        package = self.package_payload(path)
        if not package:
            path.unlink(missing_ok=True)
            raise ValueError("Update package must contain a valid manifest.json file.")
        self.record_action("upload", f"Uploaded update package {safe_name}.")
        return package

    def run_action(self, action: str) -> dict[str, Any]:
        if not self.enabled():
            raise ValueError("System updater is disabled by configuration.")

        if action == "download":
            return self.action_result(action, "Update package folder scanned.", {"status": self.check()})
        if action == "files":
            return self.stage_and_apply_files()
        if action == "database":
            return self.update_database()
        if action == "core-assets":
            return self.publish_assets("public", "Core assets published.")
        if action == "package-assets":
            return self.publish_assets("karpy_platform/packages", "Package assets published.")
        if action == "cleanup":
            return self.cleanup()
        if action == "one-click":
            return self.one_click_update(force=False)
        if action == "reinstall":
            return self.one_click_update(force=True)
        raise ValueError(f"Updater action [{action}] is not supported.")

    def one_click_update(self, force: bool = False) -> dict[str, Any]:
        package = self.latest_package()
        if not package:
            return self.action_result("one-click", "No update package found. Upload a KARPy update ZIP first.", {"status": self.status()})
        if not force and not self.version_gt(package["version"], settings.APP_VERSION):
            return self.action_result("one-click", "The system is already up-to-date.", {"status": self.status()})
        results = [
            self.stage_and_apply_files(package),
            self.update_database(package),
            self.publish_assets("public", "Core assets published."),
            self.publish_assets("karpy_platform/packages", "Package assets published."),
            self.cleanup(),
        ]
        return self.action_result("one-click", f"System update workflow completed for version {package['version']}.", {"results": results, "status": self.status()})

    def stage_and_apply_files(self, package: dict[str, Any] | None = None) -> dict[str, Any]:
        selected = package or self.latest_package()
        if not selected:
            return self.action_result("files", "No update package found. Upload a KARPy update ZIP first.", {"status": self.status()})
        zip_path = Path(selected["path"])
        staged = self.staged_dir / selected["version"]
        if staged.exists():
            shutil.rmtree(staged, ignore_errors=True)
        staged.mkdir(parents=True, exist_ok=True)

        with zipfile.ZipFile(zip_path) as archive:
            archive.extractall(staged)

        payload_dir = staged / "payload"
        if not payload_dir.exists():
            return self.action_result("files", "Update package staged. No payload/ directory was found, so no system files were changed.", {"package": selected, "status": self.status()})

        copied = self.copy_payload(payload_dir, selected["version"])
        return self.action_result("files", f"System files updated from package {selected['version']}.", {"copied": copied, "package": selected, "status": self.status()})

    def update_database(self, package: dict[str, Any] | None = None) -> dict[str, Any]:
        selected = package or self.latest_package()
        state = self.read_state()
        state["databaseUpdatedAt"] = datetime.now(timezone.utc).isoformat()
        state["databasePackage"] = selected["version"] if selected else None
        self.write_state(state)
        message = "Database update marker written. Alembic migration execution will plug into this step when release packages include migrations."
        return self.action_result("database", message, {"status": self.status()})

    def publish_assets(self, payload_subdir: str, message: str) -> dict[str, Any]:
        package = self.latest_package()
        if not package:
            return self.action_result(payload_subdir, "No update package found. Upload a KARPy update ZIP first.", {"status": self.status()})
        source = self.staged_dir / package["version"] / "payload" / payload_subdir
        if not source.exists():
            return self.action_result(payload_subdir, f"{message} No assets were found in this update package.", {"status": self.status()})
        copied = self.copy_payload(source, package["version"], base_prefix=payload_subdir)
        return self.action_result(payload_subdir, message, {"copied": copied, "status": self.status()})

    def cleanup(self) -> dict[str, Any]:
        removed = 0
        if self.staged_dir.exists():
            for path in self.staged_dir.iterdir():
                if path.is_dir():
                    shutil.rmtree(path, ignore_errors=True)
                    removed += 1
        return self.action_result("cleanup", "System update temporary files cleaned up.", {"removed": removed, "status": self.status()})

    def copy_payload(self, payload_dir: Path, version: str, base_prefix: str = "") -> list[str]:
        copied: list[str] = []
        backup_root = self.backups_dir / f"{version}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
        for source in payload_dir.rglob("*"):
            if not source.is_file():
                continue
            relative = source.relative_to(payload_dir)
            target_relative = Path(base_prefix) / relative if base_prefix else relative
            if not self.is_allowed_target(target_relative):
                continue
            target = (settings.BASE_DIR / target_relative).resolve()
            if target.exists():
                backup = backup_root / target_relative
                backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, backup)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            copied.append(str(target_relative).replace("\\", "/"))
        return copied

    def scan_packages(self) -> list[dict[str, Any]]:
        self.ensure_dirs()
        packages = [package for package in (self.package_payload(path) for path in self.packages_dir.glob("*.zip")) if package]
        return sorted(packages, key=lambda item: self.version_tuple(item["version"]), reverse=True)

    def package_payload(self, path: Path) -> dict[str, Any] | None:
        try:
            with zipfile.ZipFile(path) as archive:
                manifest_name = "manifest.json" if "manifest.json" in archive.namelist() else "update/manifest.json"
                if manifest_name not in archive.namelist():
                    return None
                manifest = json.loads(archive.read(manifest_name).decode("utf-8"))
        except (OSError, zipfile.BadZipFile, json.JSONDecodeError, UnicodeDecodeError):
            return None

        version = str(manifest.get("version") or "").strip()
        if not version:
            return None
        return {
            "id": path.stem,
            "name": manifest.get("name") or f"KARPy {version}",
            "version": version,
            "minimumVersion": manifest.get("minimumVersion"),
            "requiresPython": manifest.get("requiresPython"),
            "changelog": manifest.get("changelog") or "",
            "releasedAt": manifest.get("releasedAt"),
            "size": path.stat().st_size,
            "humanSize": self.human_size(path.stat().st_size),
            "path": str(path),
        }

    def latest_package(self) -> dict[str, Any] | None:
        packages = self.scan_packages()
        return packages[0] if packages else None

    def action_result(self, action: str, message: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
        self.record_action(action, message)
        return {"action": action, "message": message, **(data or {})}

    def record_action(self, action: str, message: str) -> None:
        state = self.read_state()
        state["lastAction"] = {"action": action, "message": message, "ranAt": datetime.now(timezone.utc).isoformat()}
        self.write_state(state)

    def steps(self) -> list[UpdateStep]:
        return [
            UpdateStep("download", "Download update files", "Scan uploaded packages and detect the newest KARPy release manifest."),
            UpdateStep("files", "Update system files", "Stage the selected update package and copy allowed payload files into the project."),
            UpdateStep("database", "Update databases", "Run the database update phase for package migrations and schema changes."),
            UpdateStep("core-assets", "Publish core assets", "Publish core public assets shipped in the update payload."),
            UpdateStep("package-assets", "Publish packages assets", "Publish assets shipped by package updates."),
            UpdateStep("cleanup", "Clean up system update files", "Remove temporary staged update files after the update is complete."),
        ]

    def warnings(self) -> list[str]:
        return [
            "Please back up your database and uploaded files before upgrading.",
            "If you don't need this 1-click update, disable it with KARPY_ENABLE_SYSTEM_UPDATER=false.",
            "An update package can overwrite files in app, karpy_platform, public, and admin-ui payload paths.",
        ]

    def default_changelog(self) -> str:
        return f"Version {settings.APP_VERSION}\n\n- Your KARPy installation is running the current local version.\n- Upload a signed update ZIP with manifest.json to detect future releases here."

    def enabled(self) -> bool:
        value = str(getattr(settings, "KARPY_ENABLE_SYSTEM_UPDATER", "true")).lower()
        return value not in {"0", "false", "no", "off"}

    def read_state(self) -> dict[str, Any]:
        if not self.state_path.exists():
            return {}
        try:
            return json.loads(self.state_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}

    def write_state(self, state: dict[str, Any]) -> None:
        self.ensure_dirs()
        self.state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")

    def ensure_dirs(self) -> None:
        self.packages_dir.mkdir(parents=True, exist_ok=True)
        self.staged_dir.mkdir(parents=True, exist_ok=True)
        self.backups_dir.mkdir(parents=True, exist_ok=True)

    def is_allowed_target(self, relative: Path) -> bool:
        parts = relative.parts
        if not parts or parts[0] not in self.allowed_roots:
            return False
        resolved = (settings.BASE_DIR / relative).resolve()
        return str(resolved).startswith(str(settings.BASE_DIR.resolve()))

    def safe_filename(self, filename: str) -> str:
        name = safe_upload_filename(filename, "karpy-update.zip")
        return re.sub(r"[^A-Za-z0-9_.-]+", "-", name).strip(".-") or "karpy-update.zip"

    def version_gt(self, left: str, right: str) -> bool:
        return self.version_tuple(left) > self.version_tuple(right)

    def version_tuple(self, version: str) -> tuple[int, ...]:
        parts = re.findall(r"\d+", version)
        return tuple(int(part) for part in parts[:4]) or (0,)

    def human_size(self, size: int) -> str:
        value = float(size)
        for unit in ("B", "KB", "MB", "GB"):
            if value < 1024 or unit == "GB":
                return f"{value:.2f} {unit}".replace(".00", "")
            value /= 1024
        return f"{size} B"


system_updater_service = SystemUpdaterService()
