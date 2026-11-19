from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from karpy_platform.core.base.helpers import plugin_path
from karpy_platform.packages.plugin_management.service import plugin_service

router = APIRouter()


class PluginStatusUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=120)


@router.get("")
async def list_plugins(status_filter: str | None = None):
    return {"plugins": await plugin_service.get_all_plugins_info_async(status_filter=status_filter), "stats": plugin_service.stats()}


@router.get("/installed")
async def installed_plugins(status_filter: str | None = None):
    return await list_plugins(status_filter)


@router.get("/stats")
async def plugin_stats():
    return {"stats": plugin_service.stats()}


@router.put("/status")
async def change_plugin_status(payload: PluginStatusUpdate, request: Request):
    result = plugin_service.toggle(payload.name)
    if not result.get("error"):
        if result.get("data", {}).get("status") == "activated":
            install_result = await plugin_service.install_database(payload.name)
            if install_result.get("error"):
                return install_result
            _mount_plugin_routes(request, payload.name)
    return result


@router.post("/{plugin_name}/activate")
async def activate_plugin(plugin_name: str, request: Request):
    result = plugin_service.activate(plugin_name)
    if not result.get("error"):
        install_result = await plugin_service.install_database(plugin_name)
        if install_result.get("error"):
            return install_result
        _mount_plugin_routes(request, plugin_name)
    return result


@router.post("/{plugin_name}/deactivate")
async def deactivate_plugin(plugin_name: str):
    return plugin_service.deactivate(plugin_name)


@router.post("/{plugin_name}/remove")
async def remove_plugin(plugin_name: str):
    return plugin_service.remove(plugin_name)


@router.delete("/{plugin_name}")
async def destroy_plugin(plugin_name: str):
    return plugin_service.remove(plugin_name)


@router.post("/activate-all")
async def activate_all_plugins(request: Request):
    result = plugin_service.activate_all()
    for plugin_name, item in result.get("data", {}).items():
        if not item.get("error"):
            install_result = await plugin_service.install_database(plugin_name)
            if install_result.get("error"):
                item.update(install_result)
                continue
            _mount_plugin_routes(request, plugin_name)
    return result


@router.post("/deactivate-all")
async def deactivate_all_plugins():
    return plugin_service.deactivate_all()


@router.post("/check-requirement")
async def check_requirement(payload: PluginStatusUpdate):
    return plugin_service.check_requirement(payload.name)


@router.get("/marketplace/ajax/plugins")
async def marketplace_plugins(q: str | None = None, page: int = 1):
    return plugin_service.marketplace_list({"q": q, "page": page, "type": "plugin"})


@router.get("/marketplace/ajax/check-update")
async def check_update():
    return {"products": plugin_service.get_installed_plugin_ids(), "updates": [], "offline": True}


@router.get("/{plugin_name}")
async def get_plugin(plugin_name: str):
    info = plugin_service.get_plugin_info(plugin_name)
    if not info:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Plugin not found")
    return plugin_service.plugin_payload(plugin_name, info)


@router.get("/{plugin_name}/screenshot")
async def plugin_screenshot(plugin_name: str):
    path = plugin_path(plugin_name) / "screenshot.png"
    if not path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Screenshot not found")
    return FileResponse(path)


def _mount_plugin_routes(request: Request, plugin_name: str) -> None:
    router_obj = plugin_service.get_plugin_routers().get(plugin_name)
    if router_obj:
        prefix = f"/api/plugins/{plugin_name}"
        if any(str(getattr(route, "path", "")).startswith(prefix) for route in request.app.router.routes):
            return
        before_count = len(request.app.router.routes)
        request.app.include_router(router_obj, prefix=f"/api/plugins/{plugin_name}", tags=[plugin_name])
        new_routes = request.app.router.routes[before_count:]
        existing_routes = request.app.router.routes[:before_count]
        catch_all_index = next(
            (index for index, route in enumerate(existing_routes) if getattr(route, "path", "") == "/{path:path}"),
            len(existing_routes),
        )
        request.app.router.routes = existing_routes[:catch_all_index] + new_routes + existing_routes[catch_all_index:]
