from __future__ import annotations

from sqlalchemy import JSON, Boolean, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from karpy_platform.core.base.models import BaseModel


class Menu(BaseModel):
    """Botble menu record."""

    __tablename__ = "menus"

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    slug: Mapped[str | None] = mapped_column(String(120), unique=True, nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(60), default="published", index=True)

    nodes: Mapped[list["MenuNode"]] = relationship(
        "MenuNode",
        back_populates="menu",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="MenuNode.position",
    )
    locations: Mapped[list["MenuLocation"]] = relationship(
        "MenuLocation",
        back_populates="menu",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class MenuNode(BaseModel):
    """A nested item inside a menu."""

    __tablename__ = "menu_nodes"
    __table_args__ = (
        Index("ix_menu_nodes_menu_parent_position", "menu_id", "parent_id", "position"),
        Index("ix_menu_nodes_reference", "reference_type", "reference_id"),
    )

    menu_id: Mapped[str] = mapped_column(String(36), ForeignKey("menus.id", ondelete="CASCADE"), index=True)
    parent_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("menu_nodes.id", ondelete="CASCADE"), nullable=True, index=True)
    reference_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    reference_type: Mapped[str | None] = mapped_column(String(160), nullable=True, index=True)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    icon_font: Mapped[str | None] = mapped_column(String(120), nullable=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    css_class: Mapped[str | None] = mapped_column(String(255), nullable=True)
    target: Mapped[str] = mapped_column(String(20), default="_self")
    has_child: Mapped[bool] = mapped_column(Boolean, default=False)
    meta: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    menu: Mapped[Menu] = relationship("Menu", back_populates="nodes")
    parent: Mapped["MenuNode | None"] = relationship("MenuNode", remote_side="MenuNode.id", back_populates="children")
    children: Mapped[list["MenuNode"]] = relationship(
        "MenuNode",
        back_populates="parent",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="MenuNode.position",
    )


class MenuLocation(BaseModel):
    """Maps a menu to a theme location such as main-menu."""

    __tablename__ = "menu_locations"
    __table_args__ = (
        UniqueConstraint("menu_id", "location", name="uq_menu_locations_menu_location"),
        Index("ix_menu_locations_menu_created", "menu_id", "created_at"),
    )

    menu_id: Mapped[str] = mapped_column(String(36), ForeignKey("menus.id", ondelete="CASCADE"), index=True)
    location: Mapped[str] = mapped_column(String(160), index=True)

    menu: Mapped[Menu] = relationship("Menu", back_populates="locations")
