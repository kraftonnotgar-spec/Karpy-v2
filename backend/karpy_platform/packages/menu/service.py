from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from karpy_platform.core.base.dashboard_menu import DashboardMenuItem, dashboard_menu
from karpy_platform.core.base.helpers import clean, slugify
from karpy_platform.core.base.hooks import hooks
from karpy_platform.packages.menu.constants import (
    MENU_ACTION_DELETED,
    MENU_ACTION_LOCATION_REGISTERED,
    MENU_ACTION_SAVED,
    MENU_FILTER_LOCATIONS,
    MENU_FILTER_NODE_URL,
    MENU_FILTER_OPTIONS,
    MENU_FILTER_TREE,
)
from karpy_platform.packages.menu.models import Menu, MenuLocation, MenuNode


@dataclass
class MenuOptionProvider:
    key: str
    name: str
    source: str
    endpoint: str | None = None
    items: list[dict[str, Any]] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "name": self.name,
            "source": self.source,
            "endpoint": self.endpoint,
            "items": self.items or [],
        }


class MenuService:
    """Python equivalent of Botble's packages/menu Menu facade."""

    def __init__(self) -> None:
        self._booted = False
        self._locations: dict[str, str] = {}
        self._option_providers: dict[str, MenuOptionProvider] = {}

    def boot(self) -> None:
        if self._booted:
            return
        self.add_location("main-menu", "Main Navigation")
        self.register_option_provider(
            "custom-link",
            "Custom link",
            source="custom",
            items=[
                {
                    "title": "Custom link",
                    "referenceType": "custom-link",
                    "referenceId": None,
                    "url": "/",
                }
            ],
        )
        self.register_option_provider("pages", "Pages", source="package:page", endpoint="/api/admin/pages")
        dashboard_menu.default().register_item(
            DashboardMenuItem(
                id="menus",
                name="Menus",
                url="/admin/appearance/menus",
                icon="network",
                priority=20,
                parent_id="appearance",
                permissions=["menus.index"],
            )
        )
        self._booted = True

    def add_location(self, location: str, description: str) -> None:
        self._locations[location] = description
        hooks.do_action(MENU_ACTION_LOCATION_REGISTERED, location, description)

    def remove_location(self, location: str) -> None:
        self._locations.pop(location, None)

    async def locations(self) -> dict[str, str]:
        return await hooks.apply_filters_async(MENU_FILTER_LOCATIONS, dict(self._locations))

    def register_option_provider(
        self,
        key: str,
        name: str,
        source: str,
        endpoint: str | None = None,
        items: list[dict[str, Any]] | None = None,
    ) -> None:
        self._option_providers[key] = MenuOptionProvider(key, name, source, endpoint, items or [])

    async def option_providers(self) -> list[dict[str, Any]]:
        providers = [provider.to_dict() for provider in self._option_providers.values()]
        providers = await hooks.apply_filters_async(MENU_FILTER_OPTIONS, providers)
        return sorted(providers, key=lambda provider: provider["name"])

    async def list_menus(self, db: AsyncSession, status: str | None = None) -> list[Menu]:
        statement = (
            select(Menu)
            .options(selectinload(Menu.locations), selectinload(Menu.nodes))
            .where(Menu.is_deleted == False)
            .order_by(Menu.name)
        )
        if status:
            statement = statement.where(Menu.status == status)
        result = await db.execute(statement)
        return list(result.scalars().unique().all())

    async def get_menu(self, db: AsyncSession, menu_id_or_slug: str) -> Menu | None:
        statement = (
            select(Menu)
            .options(
                selectinload(Menu.locations),
                selectinload(Menu.nodes).selectinload(MenuNode.children),
            )
            .where(Menu.is_deleted == False)
            .where((Menu.id == menu_id_or_slug) | (Menu.slug == menu_id_or_slug))
        )
        result = await db.execute(statement)
        return result.scalars().unique().one_or_none()

    async def create_menu(
        self,
        db: AsyncSession,
        name: str,
        slug: str | None = None,
        status: str = "published",
        locations: list[str] | None = None,
    ) -> Menu:
        menu = Menu(name=clean(name), slug=await self.unique_slug(db, slug or name), status=status)
        db.add(menu)
        await db.flush()
        await self.sync_locations(db, menu, locations or [])
        await db.commit()
        await db.refresh(menu, ["locations", "nodes"])
        await hooks.do_action_async(MENU_ACTION_SAVED, menu)
        return menu

    async def update_menu(
        self,
        db: AsyncSession,
        menu: Menu,
        values: dict[str, Any],
    ) -> Menu:
        if "name" in values and values["name"] is not None:
            menu.name = clean(values["name"])
        if "slug" in values and values["slug"]:
            menu.slug = await self.unique_slug(db, values["slug"], ignore_id=menu.id)
        if "status" in values and values["status"] is not None:
            menu.status = values["status"]
        if "locations" in values and values["locations"] is not None:
            await self.sync_locations(db, menu, values["locations"])
        await db.commit()
        await db.refresh(menu, ["locations", "nodes"])
        await hooks.do_action_async(MENU_ACTION_SAVED, menu)
        return menu

    async def delete_menu(self, db: AsyncSession, menu: Menu) -> None:
        await db.delete(menu)
        await db.commit()
        await hooks.do_action_async(MENU_ACTION_DELETED, menu)

    async def sync_locations(self, db: AsyncSession, menu: Menu, locations: list[str]) -> None:
        clean_locations = [slugify(location, fallback="location") for location in locations if location]
        await db.execute(
            delete(MenuLocation).where(
                MenuLocation.menu_id == menu.id,
                MenuLocation.location.not_in(clean_locations or [""]),
            )
        )
        existing = {
            location.location
            for location in (
                await db.execute(select(MenuLocation).where(MenuLocation.menu_id == menu.id))
            ).scalars().all()
        }
        for location in clean_locations:
            if location not in existing:
                db.add(MenuLocation(menu_id=menu.id, location=location))

    async def save_tree(
        self,
        db: AsyncSession,
        menu: Menu,
        nodes: list[dict[str, Any]],
        deleted_nodes: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        if deleted_nodes:
            await db.execute(delete(MenuNode).where(MenuNode.menu_id == menu.id, MenuNode.id.in_(deleted_nodes)))
        saved = await self._recursive_save(db, menu.id, None, nodes)
        await db.commit()
        await hooks.do_action_async(MENU_ACTION_SAVED, menu)
        return saved

    async def _recursive_save(
        self,
        db: AsyncSession,
        menu_id: str,
        parent_id: str | None,
        rows: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        saved_rows: list[dict[str, Any]] = []
        for position, row in enumerate(rows):
            item = row.get("menuItem", row)
            children = row.get("children", []) or item.pop("children", []) if isinstance(item, dict) else []
            node = await self.save_node(db, menu_id, parent_id, item, position=position, has_child=bool(children))
            saved_item = self.node_payload(node, include_children=False)
            child_rows = await self._recursive_save(db, menu_id, node.id, children)
            saved_rows.append({"menuItem": saved_item, "children": child_rows})
        return saved_rows

    async def save_node(
        self,
        db: AsyncSession,
        menu_id: str,
        parent_id: str | None,
        values: dict[str, Any],
        position: int = 0,
        has_child: bool = False,
    ) -> MenuNode:
        node = None
        node_id = values.get("id")
        if node_id:
            node = await db.get(MenuNode, node_id)
        if not node:
            node = MenuNode(menu_id=menu_id)
            db.add(node)

        node.menu_id = menu_id
        node.parent_id = parent_id
        node.position = int(values.get("position", position) or position)
        node.has_child = has_child
        node.title = clean(values.get("title") or "")
        node.css_class = clean(values.get("css_class") or values.get("cssClass") or "")
        node.icon_font = clean(values.get("icon_font") or values.get("iconFont") or "")
        node.target = values.get("target") or "_self"
        node.reference_type = values.get("reference_type") or values.get("referenceType")
        node.reference_id = values.get("reference_id") or values.get("referenceId")
        node.url = await self.resolve_node_url(values)
        node.meta = values.get("meta") or self._extract_node_meta(values)
        await db.flush()
        return node

    async def resolve_node_url(self, values: dict[str, Any]) -> str:
        reference_type = values.get("reference_type") or values.get("referenceType")
        url = values.get("url")
        if not reference_type or reference_type == "custom-link":
            resolved = url or "/"
        else:
            resolved = url or "/"
        return await hooks.apply_filters_async(MENU_FILTER_NODE_URL, resolved, values)

    async def render_location(self, db: AsyncSession, location: str) -> list[dict[str, Any]]:
        statement = (
            select(Menu)
            .join(MenuLocation)
            .options(selectinload(Menu.locations), selectinload(Menu.nodes))
            .where(Menu.is_deleted == False, Menu.status == "published", MenuLocation.location == location)
            .order_by(Menu.name)
        )
        result = await db.execute(statement)
        trees = [self.menu_tree_payload(menu) for menu in result.scalars().unique().all()]
        return await hooks.apply_filters_async(MENU_FILTER_TREE, trees, location)

    async def unique_slug(self, db: AsyncSession, value: str, ignore_id: str | None = None) -> str:
        base = slugify(value, fallback="menu")
        slug = base
        suffix = 2
        while True:
            statement = select(Menu).where(Menu.slug == slug)
            if ignore_id:
                statement = statement.where(Menu.id != ignore_id)
            exists = await db.scalar(statement)
            if not exists:
                return slug
            slug = f"{base}-{suffix}"
            suffix += 1

    def menu_payload(self, menu: Menu, include_tree: bool = False) -> dict[str, Any]:
        payload = {
            "id": menu.id,
            "name": menu.name,
            "slug": menu.slug,
            "status": menu.status,
            "locations": [location.location for location in menu.locations],
            "nodesCount": len(menu.nodes),
            "createdAt": menu.created_at.isoformat() if menu.created_at else None,
            "updatedAt": menu.updated_at.isoformat() if menu.updated_at else None,
        }
        if include_tree:
            payload["tree"] = self.build_tree(menu.nodes)
        return payload

    def menu_tree_payload(self, menu: Menu) -> dict[str, Any]:
        return {**self.menu_payload(menu), "tree": self.build_tree(menu.nodes)}

    def build_tree(self, nodes: list[MenuNode], parent_id: str | None = None) -> list[dict[str, Any]]:
        children = sorted(
            [node for node in nodes if node.parent_id == parent_id],
            key=lambda node: (node.position, node.title or ""),
        )
        return [
            self.node_payload(node, children=self.build_tree(nodes, node.id))
            for node in children
        ]

    def node_payload(
        self,
        node: MenuNode,
        children: list[dict[str, Any]] | None = None,
        include_children: bool = True,
    ) -> dict[str, Any]:
        payload = {
            "id": node.id,
            "menuId": node.menu_id,
            "parentId": node.parent_id,
            "referenceId": node.reference_id,
            "referenceType": node.reference_type,
            "url": node.url or "/",
            "iconFont": node.icon_font,
            "position": node.position,
            "title": node.title,
            "cssClass": node.css_class,
            "target": node.target,
            "hasChild": node.has_child,
            "meta": node.meta or {},
        }
        if include_children:
            payload["children"] = children or []
        return payload

    def _extract_node_meta(self, values: dict[str, Any]) -> dict[str, Any]:
        meta = {}
        for key in ("icon_image", "badge_text", "badge_color"):
            if key in values:
                meta[key] = values[key]
        return meta


menu_service = MenuService()


def boot_menu_package() -> None:
    menu_service.boot()
