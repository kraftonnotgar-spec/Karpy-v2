from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from karpy_platform.core.icon.exceptions import SvgNotFoundError
from karpy_platform.core.icon.manager import icon_manager

router = APIRouter()


class IconRenderRequest(BaseModel):
    name: str
    attributes: dict[str, str | int | bool | None] = Field(default_factory=dict)
    size: str | None = None
    component: bool = False


@router.get("/icons")
async def list_icons(
    q: str = "",
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    svg: bool = False,
):
    icons = icon_manager.search(q, limit=limit, offset=offset)
    if svg:
        icons = [{**icon, "svg": icon_manager.render(icon["name"])} for icon in icons]
    return {
        "icons": icons,
        "total": icon_manager.count(q),
        "limit": limit,
        "offset": offset,
    }


@router.get("/icons/rendered")
async def render_icon_query(name: str):
    try:
        return {"svg": icon_manager.render(name)}
    except SvgNotFoundError as exception:
        raise HTTPException(404, str(exception)) from exception


@router.get("/icons/{name}")
async def get_icon(name: str):
    if not icon_manager.has(name):
        raise HTTPException(404, f'Icon "{name}" not found.')
    icon = icon_manager.driver().all()[icon_manager.driver().normalize_full_name(name)]
    return icon


@router.get("/icons/{name}/svg")
async def render_icon_svg(name: str):
    try:
        return {"svg": icon_manager.render(name)}
    except SvgNotFoundError as exception:
        raise HTTPException(404, str(exception)) from exception


@router.post("/icons/render")
async def render_icon(data: IconRenderRequest):
    try:
        if data.component:
            svg = icon_manager.component(data.name, size=data.size, attributes=data.attributes)
        else:
            svg = icon_manager.render(data.name, data.attributes)
    except SvgNotFoundError as exception:
        raise HTTPException(404, str(exception)) from exception

    return {"html": svg}
