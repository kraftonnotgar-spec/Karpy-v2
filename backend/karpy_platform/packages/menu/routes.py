from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from karpy_platform.core.base.responses import BaseHttpResponse
from karpy_platform.packages.menu.service import menu_service

router = APIRouter()


class MenuCreate(BaseModel):
    name: str = Field(min_length=3, max_length=120)
    slug: str | None = Field(default=None, max_length=120)
    status: str = Field(default="published", max_length=60)
    locations: list[str] = Field(default_factory=list)


class MenuUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=3, max_length=120)
    slug: str | None = Field(default=None, max_length=120)
    status: str | None = Field(default=None, max_length=60)
    locations: list[str] | None = None


class MenuNodeTreeUpdate(BaseModel):
    menu_nodes: list[dict[str, Any]] = Field(default_factory=list)
    deleted_nodes: list[str] = Field(default_factory=list)


class MenuNodeCreate(BaseModel):
    data: dict[str, Any] = Field(default_factory=dict)


@router.get("")
async def list_menus(db: AsyncSession = Depends(get_db)):
    menus = await menu_service.list_menus(db)
    return {"menus": [menu_service.menu_payload(menu) for menu in menus]}


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_menu(payload: MenuCreate, db: AsyncSession = Depends(get_db)):
    menu = await menu_service.create_menu(
        db,
        name=payload.name,
        slug=payload.slug,
        status=payload.status,
        locations=payload.locations,
    )
    return BaseHttpResponse.make().set_data(menu_service.menu_payload(menu, include_tree=True)).with_created_success_message().to_dict()


@router.get("/locations")
async def list_locations(db: AsyncSession = Depends(get_db)):
    locations = await menu_service.locations()
    menus = await menu_service.list_menus(db)
    assigned = {
        location: [
            {"id": menu.id, "name": menu.name, "slug": menu.slug}
            for menu in menus
            if location in [item.location for item in menu.locations]
        ]
        for location in locations
    }
    return {"locations": locations, "assigned": assigned}


@router.get("/options")
async def list_menu_options():
    return {"options": await menu_service.option_providers()}


@router.get("/render/location/{location}")
async def render_menu_location(location: str, db: AsyncSession = Depends(get_db)):
    return {"location": location, "menus": await menu_service.render_location(db, location)}


@router.get("/{menu_id_or_slug}")
async def get_menu(menu_id_or_slug: str, db: AsyncSession = Depends(get_db)):
    menu = await menu_service.get_menu(db, menu_id_or_slug)
    if not menu:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Menu not found")
    return menu_service.menu_payload(menu, include_tree=True)


@router.patch("/{menu_id}")
async def update_menu(menu_id: str, payload: MenuUpdate, db: AsyncSession = Depends(get_db)):
    menu = await menu_service.get_menu(db, menu_id)
    if not menu:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Menu not found")
    menu = await menu_service.update_menu(db, menu, payload.model_dump(exclude_unset=True))
    return BaseHttpResponse.make().set_data(menu_service.menu_payload(menu, include_tree=True)).with_updated_success_message().to_dict()


@router.delete("/{menu_id}")
async def delete_menu(menu_id: str, db: AsyncSession = Depends(get_db)):
    menu = await menu_service.get_menu(db, menu_id)
    if not menu:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Menu not found")
    await menu_service.delete_menu(db, menu)
    return BaseHttpResponse.make().with_deleted_success_message().to_dict()


@router.post("/{menu_id}/nodes")
async def create_menu_node(menu_id: str, payload: MenuNodeCreate, db: AsyncSession = Depends(get_db)):
    menu = await menu_service.get_menu(db, menu_id)
    if not menu:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Menu not found")
    node = await menu_service.save_node(
        db,
        menu_id=menu.id,
        parent_id=payload.data.get("parent_id") or payload.data.get("parentId"),
        values=payload.data,
    )
    await db.commit()
    return BaseHttpResponse.make().set_data(menu_service.node_payload(node)).with_created_success_message().to_dict()


@router.put("/{menu_id}/nodes/tree")
async def save_menu_tree(menu_id: str, payload: MenuNodeTreeUpdate, db: AsyncSession = Depends(get_db)):
    menu = await menu_service.get_menu(db, menu_id)
    if not menu:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Menu not found")
    saved = await menu_service.save_tree(db, menu, payload.menu_nodes, payload.deleted_nodes)
    return BaseHttpResponse.make().set_data({"menuNodes": saved}).with_updated_success_message().to_dict()
