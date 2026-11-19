"""
KARPy CMS — Plugin Service.

The heart of the plugin system. Handles the full lifecycle:
activate → deactivate → remove.

This is the Python equivalent of Botble's PluginService.php.
Each plugin has a plugin.json manifest and a Plugin class with lifecycle hooks.
"""

import importlib
import importlib.util
import shutil
import sys
from typing import Any
from karpy_platform.core.base.dashboard_menu import DashboardMenuItem, dashboard_menu
from karpy_platform.core.base.helpers import scan_folder, get_file_data, write_file_data, plugin_path
from karpy_platform.core.base.hooks import hooks
from karpy_platform.core.setting.registry import setting_panel_registry
from app.config import settings
import logging

from karpy_platform.core.dashboard.constants import DASHBOARD_FILTER_ADMIN_LIST
from karpy_platform.packages.plugin_management.constants import (
    PLUGIN_ACTION_ACTIVATED,
    PLUGIN_ACTION_DEACTIVATED,
    PLUGIN_ACTION_REMOVED,
    PLUGIN_ACTION_UPDATED,
    PLUGIN_ACTION_UPDATING,
    PLUGIN_FILTER_LIST,
    PLUGIN_FILTER_MARKETPLACE_LIST,
)

logger = logging.getLogger("karpy.plugins")


# ─── Plugin Manifest Schema ──────────────────────────────────

REQUIRED_MANIFEST_FIELDS = ["id", "name", "namespace", "provider", "version"]


class PluginInfo:
    """Parsed plugin.json data."""

    def __init__(self, data: dict):
        self.id = data.get("id", "")
        self.name = data.get("name", "")
        self.namespace = data.get("namespace", "")
        self.provider = data.get("provider", "")
        self.version = data.get("version", "0.0.0")
        self.author = data.get("author", "")
        self.description = data.get("description", "")
        self.url = data.get("url", "")
        self.required_plugins = data.get("required_plugins", [])
        if not self.required_plugins:
            self.required_plugins = [item.split("/")[-1] for item in data.get("require", []) if item != "botble/platform"]
        self.minimum_core_version = data.get("minimum_core_version", None)
        self.ready = data.get("ready", True)
        self.icon = data.get("icon", "package")
        self.screenshot = data.get("screenshot", "")
        self._raw = data

    def to_dict(self) -> dict:
        return {
            **self._raw,
            "id": self.id,
            "name": self.name,
            "namespace": self.namespace,
            "provider": self.provider,
            "version": self.version,
            "author": self.author,
            "description": self.description,
            "url": self.url,
            "icon": self.icon,
            "screenshot": self.screenshot,
            "required_plugins": self.required_plugins,
            "minimum_core_version": self.minimum_core_version,
            "ready": self.ready,
        }

    def is_valid(self) -> bool:
        return all(getattr(self, f, None) for f in REQUIRED_MANIFEST_FIELDS)


# ─── Active Plugins Store ─────────────────────────────────────

ACTIVE_PLUGINS_FILE = settings.PLATFORM_DIR / "activated_plugins.json"


def get_active_plugins() -> list[str]:
    """Read the list of activated plugin folder names."""
    data = get_file_data(ACTIVE_PLUGINS_FILE)
    return data.get("plugins", [])


def save_active_plugins(plugins: list[str]):
    """Persist the list of activated plugin folder names."""
    ordered = list(dict.fromkeys(plugins))
    write_file_data(ACTIVE_PLUGINS_FILE, {"plugins": ordered})


# ─── Plugin Service ───────────────────────────────────────────

class PluginService:
    """
    Manages the full plugin lifecycle: discovery, activation, deactivation, removal.
    
    This mirrors Botble's PluginService with the same concepts:
    - plugin.json manifest
    - Plugin class with activate/deactivate/remove lifecycle hooks
    - Dynamic module loading via importlib
    - Dependency checking between plugins
    """

    def __init__(self):
        self._loaded_modules: dict[str, Any] = {}
        self._routers: dict[str, Any] = {}
        self._booted = False
        self.cache_installed_plugins_enabled = True
        self._installed_cache: list[str] | None = None
        self._installed_cache_signature: tuple[tuple[str, float], ...] | None = None

    def boot_package(self) -> None:
        if self._booted:
            return
        dashboard_menu.default().register_item(
            DashboardMenuItem(
                id="plugins",
                name="Plugins",
                url="/admin/plugins",
                icon="plug",
                priority=90,
                permissions=["plugins.index"],
            )
        )
        dashboard_menu.default().register_item(
            DashboardMenuItem(
                id="installed-plugins",
                name="Installed Plugins",
                url="/admin/plugins",
                parent_id="plugins",
                priority=10,
                permissions=["plugins.index"],
            )
        )
        dashboard_menu.default().register_item(
            DashboardMenuItem(
                id="add-plugin",
                name="Add New Plugin",
                url="/admin/plugins/marketplace",
                parent_id="plugins",
                priority=20,
                permissions=["plugins.marketplace"],
            )
        )
        hooks.add_filter(DASHBOARD_FILTER_ADMIN_LIST, self._add_stats_widget, priority=15)
        self._booted = True

    # ─── Discovery ────────────────────────────────────────────

    def get_installed_plugins(self) -> list[str]:
        """Scan the plugins directory and return all installed plugin names."""
        signature = self._installed_plugins_signature()
        if (
            self.cache_installed_plugins_enabled
            and self._installed_cache is not None
            and self._installed_cache_signature == signature
        ):
            return list(self._installed_cache)

        installed = [name for name, _mtime in signature]
        if self.cache_installed_plugins_enabled:
            self._installed_cache = list(installed)
            self._installed_cache_signature = signature
        return installed

    def clear_installed_plugins_cache(self) -> None:
        self._installed_cache = None
        self._installed_cache_signature = None

    def _installed_plugins_signature(self) -> tuple[tuple[str, float], ...]:
        plugins_dir = plugin_path()
        if not plugins_dir.exists():
            plugins_dir.mkdir(parents=True, exist_ok=True)
            return ()

        signature: list[tuple[str, float]] = []
        for name in scan_folder(plugins_dir):
            manifest = plugin_path(name) / "plugin.json"
            if manifest.exists():
                signature.append((name, manifest.stat().st_mtime))
        return tuple(sorted(signature))

    def validate(self, plugin_name: str) -> dict:
        info = self.get_plugin_info(plugin_name)
        if not plugin_path(plugin_name).exists():
            return {"error": True, "message": f"Plugin '{plugin_name}' does not exist"}
        if not info:
            return {"error": True, "message": f"Plugin '{plugin_name}' is missing plugin.json"}
        if not info.is_valid():
            return {"error": True, "message": f"Plugin '{plugin_name}' has an invalid manifest"}
        if not info.ready:
            return {"error": True, "message": f"Plugin '{info.name}' is not ready to activate"}
        if self.is_blacklisted(plugin_name, info):
            return {"error": True, "message": f"Plugin '{plugin_name}' is not allowed"}
        if info.minimum_core_version and not self._is_version_compatible(settings.APP_VERSION, info.minimum_core_version):
            return {
                "error": True,
                "message": f"Plugin '{info.name}' requires KARPy {info.minimum_core_version} or newer",
            }
        return {"error": False}

    def is_blacklisted(self, plugin_name: str, info: PluginInfo | None = None) -> bool:
        blacklist = {"activator", "botble-activator", "botble-activator-main", "shaqi/botble-activator"}
        info = info or self.get_plugin_info(plugin_name)
        return plugin_name in blacklist or bool(info and info.id in blacklist)

    def get_plugin_info(self, plugin_name: str) -> PluginInfo | None:
        """Read and parse a plugin's plugin.json manifest."""
        manifest_path = plugin_path(plugin_name) / "plugin.json"
        data = get_file_data(manifest_path)
        if not data:
            return None
        return PluginInfo(data)

    async def get_all_plugins_info_async(self, status_filter: str | None = None) -> list[dict]:
        """Get info for all installed plugins with their active status."""
        active = get_active_plugins()
        result = []
        for name in self.get_installed_plugins():
            info = self.get_plugin_info(name)
            if info:
                d = self.plugin_payload(name, info, active)
                if status_filter == "active" and not d["is_active"]:
                    continue
                if status_filter == "inactive" and d["is_active"]:
                    continue
                if status_filter == "invalid" and d["is_valid"]:
                    continue
                result.append(d)
        result.sort(key=lambda item: (not item["is_active"], item["name"].lower()))
        return await hooks.apply_filters_async(PLUGIN_FILTER_LIST, result)

    def get_all_plugins_info(self) -> list[dict]:
        active = get_active_plugins()
        return [
            self.plugin_payload(name, info, active)
            for name in self.get_installed_plugins()
            if (info := self.get_plugin_info(name))
        ]

    def plugin_payload(self, folder: str, info: PluginInfo, active: list[str] | None = None) -> dict:
        active = active if active is not None else get_active_plugins()
        required_by = self.required_by(folder, active)
        missing = [dep for dep in info.required_plugins if dep not in active]
        payload = info.to_dict()
        payload.update(
            {
                "folder": folder,
                "path": folder,
                "status": folder in active,
                "is_active": folder in active,
                "is_valid": info.is_valid(),
                "missing_dependencies": missing,
                "required_by": required_by,
                "can_activate": info.is_valid() and not missing and folder not in active and bool(info.ready),
                "can_deactivate": folder in active and not required_by,
                "can_remove": not required_by,
                "admin_url": f"/admin/plugins/{folder}",
                "api_url": f"/api/admin/plugins/{folder}",
                "image": self.screenshot_url(folder, info),
            }
        )
        return payload

    def screenshot_url(self, folder: str, info: PluginInfo) -> str | None:
        if info.screenshot:
            return info.screenshot
        if (plugin_path(folder) / "screenshot.png").exists():
            return f"/api/admin/plugins/{folder}/screenshot"
        return None

    def required_by(self, plugin_name: str, active: list[str] | None = None) -> list[str]:
        active = active if active is not None else get_active_plugins()
        required_by = []
        for other_name in active:
            if other_name == plugin_name:
                continue
            other_info = self.get_plugin_info(other_name)
            if other_info and plugin_name in other_info.required_plugins:
                required_by.append(other_name)
        return required_by

    # ─── Activation ───────────────────────────────────────────

    def activate(self, plugin_name: str) -> dict:
        """
        Activate a plugin:
        1. Validate manifest
        2. Check dependencies
        3. Load the module dynamically
        4. Call Plugin.activate()
        5. Register routes
        6. Save to active list
        """
        validation = self.validate(plugin_name)
        if validation["error"]:
            return validation

        info = self.get_plugin_info(plugin_name)
        assert info is not None

        active = get_active_plugins()
        if plugin_name in active:
            return {"error": True, "message": f"Plugin '{plugin_name}' is already activated"}

        # Check dependencies
        missing = [dep for dep in info.required_plugins if dep not in active]
        if missing:
            return {"error": True, "message": f"Missing required plugins: {', '.join(missing)}"}

        # Load the plugin module dynamically
        try:
            plugin_class = self._load_plugin_class(plugin_name, info)
        except Exception as e:
            logger.error(f"Failed to load plugin '{plugin_name}': {e}")
            return {"error": True, "message": f"Failed to load plugin: {str(e)}"}

        # Call activate lifecycle hook
        try:
            if hasattr(plugin_class, "activate"):
                plugin_class.activate()
        except Exception as e:
            logger.error(f"Plugin '{plugin_name}' activate() failed: {e}")
            return {"error": True, "message": f"Plugin activation failed: {str(e)}"}

        try:
            if hasattr(plugin_class, "boot"):
                plugin_class.boot()
        except Exception as e:
            logger.error(f"Plugin '{plugin_name}' boot() failed: {e}")
            return {"error": True, "message": f"Plugin boot failed: {str(e)}"}

        try:
            self.import_plugin_models(plugin_name, plugin_class)
        except Exception as e:
            logger.error(f"Plugin '{plugin_name}' model import failed: {e}")
            return {"error": True, "message": f"Plugin model import failed: {str(e)}"}

        # Register routes if the plugin provides them
        if hasattr(plugin_class, "get_routes"):
            router = plugin_class.get_routes()
            if router:
                self._routers[plugin_name] = router

        # Save to active plugins
        active.append(plugin_name)
        save_active_plugins(active)
        self.clear_installed_plugins_cache()

        setting_panel_registry.register_plugin_settings(plugin_name, info.to_dict())

        # Fire hook so other plugins can react
        hooks.do_action("plugin_activated", plugin_name, info)
        hooks.do_action(PLUGIN_ACTION_ACTIVATED, plugin_name, info)

        logger.info(f"Plugin '{plugin_name}' activated successfully")
        return {"error": False, "message": f"Plugin '{info.name}' activated successfully"}

    # ─── Deactivation ─────────────────────────────────────────

    def deactivate(self, plugin_name: str) -> dict:
        """
        Deactivate a plugin:
        1. Check if any other active plugin depends on it
        2. Call Plugin.deactivate()
        3. Unregister routes
        4. Remove from active list
        """
        active = get_active_plugins()
        if plugin_name not in active:
            return {"error": True, "message": f"Plugin '{plugin_name}' is not active"}

        required_by = self.required_by(plugin_name, active)

        if required_by:
            return {
                "error": True,
                "message": f"Cannot deactivate: required by {', '.join(required_by)}"
            }

        info = self.get_plugin_info(plugin_name)

        # Call deactivate lifecycle hook
        try:
            plugin_class = self._get_loaded_plugin(plugin_name, info)
            if plugin_class and hasattr(plugin_class, "deactivate"):
                plugin_class.deactivate()
        except Exception as e:
            logger.warning(f"Plugin '{plugin_name}' deactivate() had issues: {e}")

        # Unregister routes
        self._routers.pop(plugin_name, None)

        # Remove from active list
        active.remove(plugin_name)
        save_active_plugins(active)
        self.clear_installed_plugins_cache()

        hooks.do_action("plugin_deactivated", plugin_name)
        hooks.do_action(PLUGIN_ACTION_DEACTIVATED, plugin_name)

        logger.info(f"Plugin '{plugin_name}' deactivated")
        return {"error": False, "message": f"Plugin '{plugin_name}' deactivated successfully"}

    # ─── Removal ──────────────────────────────────────────────

    def remove(self, plugin_name: str) -> dict:
        """
        Remove a plugin completely:
        1. Deactivate first
        2. Call Plugin.remove() (drop tables, cleanup)
        3. Delete plugin folder from disk
        """
        # Deactivate first if active
        active = get_active_plugins()
        if plugin_name in active:
            result = self.deactivate(plugin_name)
            if result["error"]:
                return result

        info = self.get_plugin_info(plugin_name)
        if not info:
            return {"error": True, "message": f"Plugin '{plugin_name}' not found"}

        # Call remove lifecycle hook
        try:
            plugin_class = self._get_loaded_plugin(plugin_name, info)
            if plugin_class and hasattr(plugin_class, "uninstall"):
                plugin_class.uninstall()
            if plugin_class and hasattr(plugin_class, "remove"):
                plugin_class.remove()
        except Exception as e:
            logger.warning(f"Plugin '{plugin_name}' remove() had issues: {e}")

        # Delete plugin directory
        plugin_dir = plugin_path(plugin_name)
        if plugin_dir.exists():
            shutil.rmtree(plugin_dir)

        # Cleanup loaded module
        self._loaded_modules.pop(plugin_name, None)
        self.clear_installed_plugins_cache()

        hooks.do_action("plugin_removed", plugin_name)
        hooks.do_action(PLUGIN_ACTION_REMOVED, plugin_name)

        logger.info(f"Plugin '{plugin_name}' removed from disk")
        return {"error": False, "message": f"Plugin '{plugin_name}' removed successfully"}

    def toggle(self, plugin_name: str) -> dict:
        if plugin_name in get_active_plugins():
            result = self.deactivate(plugin_name)
            if not result.get("error"):
                result["data"] = {"status": "deactivated"}
            return result
        result = self.activate(plugin_name)
        if not result.get("error"):
            result["data"] = {"status": "activated"}
        return result

    def activate_all(self) -> dict:
        results = {name: self.activate(name) for name in self.get_installed_plugins()}
        return {"error": any(item.get("error") for item in results.values()), "data": results}

    def deactivate_all(self) -> dict:
        results = {}
        for name in reversed(get_active_plugins()):
            results[name] = self.deactivate(name)
        return {"error": any(item.get("error") for item in results.values()), "data": results}

    def check_requirement(self, plugin_name: str) -> dict:
        info = self.get_plugin_info(plugin_name)
        if not info:
            return {"error": True, "message": f"Plugin '{plugin_name}' not found"}
        active = get_active_plugins()
        missing = [dep for dep in info.required_plugins if dep not in active]
        return {
            "error": bool(missing),
            "message": f"Missing required plugins: {', '.join(missing)}" if missing else "Requirement satisfied",
            "data": {
                "pluginName": info.id or plugin_name,
                "requiredPlugins": info.required_plugins,
                "missingPlugins": missing,
            },
        }

    def marketplace_list(self, query: dict[str, Any] | None = None) -> dict:
        query = query or {}
        data = []
        payload = {
            "data": data,
            "meta": {
                "offline": True,
                "query": query,
                "message": "Marketplace API is not connected yet. Local install/update hooks are ready.",
            },
        }
        return hooks.apply_filters(PLUGIN_FILTER_MARKETPLACE_LIST, payload)

    def update_plugin(self, plugin_name: str, update_callback=None) -> dict:
        validation = self.validate(plugin_name)
        if validation["error"]:
            return validation
        hooks.do_action(PLUGIN_ACTION_UPDATING, plugin_name)
        result = update_callback() if update_callback else {"updated": False}
        hooks.do_action(PLUGIN_ACTION_UPDATED, plugin_name, result)
        return {"error": False, "message": f"Plugin '{plugin_name}' update hook completed", "data": result}

    def get_installed_plugin_ids(self) -> dict[str, str]:
        output = {}
        for name in self.get_installed_plugins():
            info = self.get_plugin_info(name)
            if info and info.id:
                output[info.id] = info.version
        return output

    # ─── Route Access ─────────────────────────────────────────

    def get_plugin_routers(self) -> dict:
        """Return all registered plugin routers (for FastAPI to mount)."""
        return self._routers

    def get_admin_menus(self) -> list[dict]:
        """Collect sidebar menu items from all active plugins."""
        menus = []
        for plugin_name in get_active_plugins():
            info = self.get_plugin_info(plugin_name)
            plugin_class = self._get_loaded_plugin(plugin_name, info)
            if plugin_class and hasattr(plugin_class, "get_admin_menus"):
                try:
                    plugin_menus = plugin_class.get_admin_menus()
                    if plugin_menus:
                        menus.extend(plugin_menus)
                except Exception as e:
                    logger.warning(f"Failed to get menus from '{plugin_name}': {e}")
        return menus

    def get_user_menus(self) -> list[dict]:
        """Collect user navigation metadata from active plugins."""
        menus = []
        for plugin_name in get_active_plugins():
            info = self.get_plugin_info(plugin_name)
            plugin_class = self._get_loaded_plugin(plugin_name, info)
            if plugin_class and hasattr(plugin_class, "get_user_menus"):
                try:
                    plugin_menus = plugin_class.get_user_menus()
                    if plugin_menus:
                        menus.extend(plugin_menus)
                except Exception as exception:
                    logger.warning("Failed to get user menus from '%s': %s", plugin_name, exception)
        return menus

    def get_lifecycle_handlers(self) -> dict[str, list]:
        """Collect server-side lifecycle subscribers without invoking them."""
        handlers: dict[str, list] = {}
        for plugin_name in get_active_plugins():
            info = self.get_plugin_info(plugin_name)
            plugin_class = self._get_loaded_plugin(plugin_name, info)
            if plugin_class and hasattr(plugin_class, "get_lifecycle_handlers"):
                try:
                    for event_name, handler in (plugin_class.get_lifecycle_handlers() or {}).items():
                        handlers.setdefault(event_name, []).append(handler)
                except Exception as exception:
                    logger.warning("Failed to get lifecycle handlers from '%s': %s", plugin_name, exception)
        return handlers

    def get_permissions(self) -> list[dict]:
        """Collect permission definitions exposed by active plugins."""
        permissions = []
        for plugin_name in get_active_plugins():
            info = self.get_plugin_info(plugin_name)
            plugin_class = self._get_loaded_plugin(plugin_name, info)
            if plugin_class and hasattr(plugin_class, "get_permissions"):
                try:
                    plugin_permissions = plugin_class.get_permissions()
                    if plugin_permissions:
                        permissions.extend(plugin_permissions)
                except Exception as exception:
                    logger.warning("Failed to get permissions from '%s': %s", plugin_name, exception)
        return permissions

    def import_active_plugin_models(self) -> None:
        """Import SQLAlchemy models for all active plugins before create_all()."""
        for plugin_name in get_active_plugins():
            info = self.get_plugin_info(plugin_name)
            if not info:
                continue
            plugin_class = self._get_loaded_plugin(plugin_name, info)
            if plugin_class:
                self.import_plugin_models(plugin_name, plugin_class)

    def import_plugin_models(self, plugin_name: str, plugin_class: Any | None = None) -> list[str]:
        """Import model modules declared by a plugin provider."""
        info = self.get_plugin_info(plugin_name)
        plugin_class = plugin_class or self._get_loaded_plugin(plugin_name, info)
        if not plugin_class or not hasattr(plugin_class, "get_model_modules"):
            return []
        modules = plugin_class.get_model_modules() or []
        imported = []
        for module in modules:
            importlib.import_module(module)
            imported.append(module)
        return imported

    async def install_database(self, plugin_name: str) -> dict:
        """Create missing plugin tables after activation.

        KARPy currently uses SQLAlchemy metadata for local development and simple
        installs. Plugin migration files are still generated so the same plugin
        shape can move to Alembic-managed production migrations later.
        """
        info = self.get_plugin_info(plugin_name)
        plugin_class = self._get_loaded_plugin(plugin_name, info)
        if not plugin_class:
            return {"error": True, "message": f"Plugin '{plugin_name}' is not loaded"}

        try:
            self.import_plugin_models(plugin_name, plugin_class)
            from app.database import Base, engine

            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            if hasattr(plugin_class, "install"):
                plugin_class.install()
            return {"error": False, "message": f"Plugin '{plugin_name}' database installed"}
        except Exception as e:
            logger.error(f"Plugin '{plugin_name}' database install failed: {e}")
            return {"error": True, "message": f"Plugin database install failed: {str(e)}"}

    def stats(self) -> dict:
        installed = self.get_installed_plugins()
        active = get_active_plugins()
        return {
            "installed": len(installed),
            "active": len([name for name in installed if name in active]),
            "inactive": len([name for name in installed if name not in active]),
            "invalid": len([name for name in installed if not ((info := self.get_plugin_info(name)) and info.is_valid())]),
        }

    # ─── Internal: Dynamic Module Loading ─────────────────────

    def _load_plugin_class(self, plugin_name: str, info: PluginInfo):
        """Dynamically import a plugin's Provider class using importlib."""
        plugin_dir = plugin_path(plugin_name)

        # Add the plugins directory to sys.path if not already there
        plugins_parent = str(settings.PLUGINS_DIR)
        if plugins_parent not in sys.path:
            sys.path.insert(0, plugins_parent)

        # Also add the plugin's own directory
        plugin_dir_str = str(plugin_dir)
        if plugin_dir_str not in sys.path:
            sys.path.insert(0, plugin_dir_str)

        module_path = plugin_dir / f"{info.provider.replace('.', '/')}.py"
        if module_path.exists():
            module_name = f"karpy_platform.plugins.{plugin_name}.{info.provider}".replace("-", "_")
            spec = importlib.util.spec_from_file_location(module_name, str(module_path))
            if not spec or not spec.loader:
                raise ModuleNotFoundError(f"Cannot load plugin provider from {module_path}")
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)
        else:
            module = importlib.import_module(info.provider)

        # Find the Plugin class in the module
        plugin_class_name = info.name.replace(" ", "") + "Plugin"
        plugin_class = getattr(module, plugin_class_name, None)

        # Fallback: look for any class ending with "Plugin"
        if not plugin_class:
            for attr_name in dir(module):
                if attr_name.endswith("Plugin") and attr_name != "BasePlugin":
                    plugin_class = getattr(module, attr_name)
                    break

        if not plugin_class:
            raise ValueError(f"No Plugin class found in {info.provider}")

        self._loaded_modules[plugin_name] = plugin_class
        return plugin_class

    def _get_loaded_plugin(self, plugin_name: str, info: PluginInfo | None = None):
        """Get an already-loaded plugin class, or try to load it."""
        if plugin_name in self._loaded_modules:
            return self._loaded_modules[plugin_name]

        if info:
            try:
                return self._load_plugin_class(plugin_name, info)
            except Exception:
                return None
        return None

    def _is_version_compatible(self, current: str, minimum: str) -> bool:
        def normalize(value: str) -> tuple[int, int, int]:
            numbers = []
            for part in value.split("."):
                digits = "".join(char for char in part if char.isdigit())
                numbers.append(int(digits or 0))
            return tuple((numbers + [0, 0, 0])[:3])

        return normalize(current) >= normalize(minimum)

    # ─── Boot (called at startup) ─────────────────────────────

    def boot_active_plugins(self):
        """Load and initialize all active plugins at application startup."""
        active = get_active_plugins()
        for plugin_name in active:
            info = self.get_plugin_info(plugin_name)
            if not info:
                logger.warning(f"Active plugin '{plugin_name}' has no valid manifest, skipping")
                continue

            try:
                plugin_class = self._load_plugin_class(plugin_name, info)

                # Call boot() if it exists (runs after all plugins are registered)
                if hasattr(plugin_class, "boot"):
                    plugin_class.boot()

                setting_panel_registry.register_plugin_settings(plugin_name, info.to_dict())

                # Register routes
                if hasattr(plugin_class, "get_routes"):
                    router = plugin_class.get_routes()
                    if router:
                        self._routers[plugin_name] = router

                logger.info(f"Booted plugin: {info.name} v{info.version}")

            except Exception as e:
                logger.error(f"Failed to boot plugin '{plugin_name}': {e}")

    async def _add_stats_widget(self, widgets: list[dict], widget_models=None, db=None) -> list[dict]:
        widgets.append(
            {
                "id": "widget_total_plugins",
                "name": "widget_total_plugins",
                "type": "stats",
                "title": "Plugins",
                "icon": "plug",
                "color": "success",
                "route": "/admin/plugins",
                "column": "col-12 col-md-6 col-lg-3",
                "statsTotal": self.stats()["installed"],
                "priority": 16,
                "status": True,
                "order": 16,
                "settings": {},
                "predefinedRanges": [],
            }
        )
        return widgets


# Global singleton
plugin_service = PluginService()


def boot_plugin_management_package() -> None:
    plugin_service.boot_package()
