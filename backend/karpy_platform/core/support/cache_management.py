from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from karpy_platform.core.base.dashboard_menu import dashboard_menu, register_core_admin_menu
from karpy_platform.core.setting.store import setting_store
from karpy_platform.core.support.cache import support_cache_manager


@dataclass(frozen=True)
class CacheAction:
    key: str
    title: str
    description: str
    kind: str
    tone: str
    button: str


class CacheManagementService:
    """Python-native cache management center for KARPy runtime caches."""

    cache_actions = [
        CacheAction(
            "cms",
            "Clear all CMS cache",
            "Clear database, settings, theme, widget, shortcode, sitemap, menu, and support caches.",
            "database",
            "blue",
            "Clear",
        ),
        CacheAction(
            "views",
            "Refresh Python compiled files",
            "Remove __pycache__ bytecode so Python rebuilds fresh compiled modules on demand.",
            "file",
            "amber",
            "Refresh",
        ),
        CacheAction(
            "config",
            "Clear config and settings cache",
            "Refresh cached database settings and environment-backed configuration values.",
            "settings",
            "blue",
            "Clear",
        ),
        CacheAction(
            "routes",
            "Clear route and menu cache",
            "Rebuild admin menu registrations and clear route-aware support cache groups.",
            "route",
            "green",
            "Clear",
        ),
        CacheAction(
            "logs",
            "Clear log files",
            "Remove application log files from storage/logs without touching backups or media.",
            "log",
            "red",
            "Clear",
        ),
    ]

    optimization_actions = [
        CacheAction(
            "optimize",
            "Optimize site performance",
            "Warm and reset runtime caches used by settings, routes, widgets, theme metadata, sitemap, and shortcodes.",
            "rocket",
            "green",
            "Optimize",
        ),
        CacheAction(
            "optimization",
            "Clear optimization cache",
            "Remove page optimization runtime caches and refresh optimized rendering state.",
            "eraser",
            "amber",
            "Clear",
        ),
    ]

    def status(self) -> dict[str, Any]:
        groups = support_cache_manager.groups()
        return {
            "groups": groups,
            "summary": {
                "currentSize": self.human_size(self.cache_size()),
                "trackedGroups": len(groups),
                "trackedKeys": sum(int(group.get("trackedKeys") or 0) for group in groups),
                "aliveKeys": sum(int(group.get("aliveKeys") or 0) for group in groups),
            },
            "cacheActions": [self._payload(action) for action in self.cache_actions],
            "optimizationActions": [self._payload(action) for action in self.optimization_actions],
        }

    async def run(self, db: AsyncSession, action: str) -> dict[str, Any]:
        if action == "cms":
            result = await self.clear_cms_cache(db)
        elif action == "views":
            result = self.refresh_python_compiled_files()
        elif action == "config":
            result = self.clear_config_cache()
        elif action == "routes":
            result = await self.clear_route_cache()
        elif action == "logs":
            result = self.clear_log_files()
        elif action == "optimize":
            result = await self.optimize_runtime(db)
        elif action == "optimization":
            result = self.clear_optimization_cache()
        else:
            raise ValueError(f"Cache action [{action}] is not supported.")
        return {**result, "status": self.status()}

    async def clear_cms_cache(self, db: AsyncSession) -> dict[str, Any]:
        await support_cache_manager.flush()
        self.clear_config_cache()
        await self.clear_route_cache()
        self._clear_package_caches()
        self._remove_files(settings.STORAGE_DIR / "framework" / "cache")
        return {"message": "All CMS cache cleared.", "cleared": ["support", "settings", "routes", "theme", "widgets", "shortcodes", "sitemap"]}

    def refresh_python_compiled_files(self) -> dict[str, Any]:
        removed = 0
        for root in [settings.BASE_DIR / "app", settings.PLATFORM_DIR]:
            if not root.exists():
                continue
            for path in root.rglob("__pycache__"):
                if path.is_dir():
                    shutil.rmtree(path, ignore_errors=True)
                    removed += 1
        return {"message": "Python compiled files refreshed.", "removed": removed}

    def clear_config_cache(self) -> dict[str, Any]:
        setting_store.clear_cache()
        return {"message": "Config and settings cache cleared."}

    async def clear_route_cache(self) -> dict[str, Any]:
        dashboard_menu.clear()
        register_core_admin_menu()
        await support_cache_manager.flush("routes")
        await support_cache_manager.flush("menus")
        return {"message": "Route and menu cache cleared."}

    def clear_log_files(self) -> dict[str, Any]:
        logs_dir = settings.STORAGE_DIR / "logs"
        removed = 0
        if logs_dir.exists():
            for path in logs_dir.iterdir():
                if path.is_file() and path.suffix.lower() in {".log", ".txt"}:
                    path.unlink(missing_ok=True)
                    removed += 1
        return {"message": "Log files cleared.", "removed": removed}

    async def optimize_runtime(self, db: AsyncSession) -> dict[str, Any]:
        await support_cache_manager.flush()
        self.clear_config_cache()
        await self.clear_route_cache()
        self._clear_package_caches()
        return {"message": "Runtime performance caches optimized."}

    def clear_optimization_cache(self) -> dict[str, Any]:
        self._clear_package_caches()
        self._remove_files(settings.STORAGE_DIR / "framework" / "views")
        self._remove_files(settings.STORAGE_DIR / "framework" / "cache")
        return {"message": "Optimization cache cleared."}

    def cache_size(self) -> int:
        paths = [
            settings.STORAGE_DIR / "support_cache_keys.json",
            settings.STORAGE_DIR / "framework" / "cache",
            settings.STORAGE_DIR / "framework" / "views",
        ]
        return sum(self.path_size(path) for path in paths)

    def path_size(self, path: Path) -> int:
        if path.is_file():
            return path.stat().st_size
        if path.is_dir():
            return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())
        return 0

    def human_size(self, size: int) -> str:
        value = float(size)
        for unit in ("B", "KB", "MB", "GB"):
            if value < 1024 or unit == "GB":
                return f"{value:.2f} {unit}".replace(".00", "")
            value /= 1024
        return f"{size} B"

    def _payload(self, action: CacheAction) -> dict[str, Any]:
        return {
            "key": action.key,
            "title": action.title,
            "description": action.description,
            "kind": action.kind,
            "tone": action.tone,
            "button": action.button,
        }

    def _clear_package_caches(self) -> None:
        try:
            from karpy_platform.packages.theme.service import theme_service

            theme_service.clear_cache()
            theme_service.asset.flush()
        except Exception:
            pass
        try:
            from karpy_platform.packages.widget.service import widget_service

            widget_service.factory.clear_cache()
        except Exception:
            pass
        try:
            from karpy_platform.packages.shortcode.engine import shortcode_engine

            shortcode_engine._cache.clear()
        except Exception:
            pass
        try:
            from karpy_platform.packages.sitemap.service import sitemap_service

            sitemap_service.clear_cache()
        except Exception:
            pass

    def _remove_files(self, path: Path) -> None:
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
        elif path.is_file():
            path.unlink(missing_ok=True)


cache_management_service = CacheManagementService()
