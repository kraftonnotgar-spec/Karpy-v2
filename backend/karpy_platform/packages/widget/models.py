from __future__ import annotations

from sqlalchemy import JSON, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from karpy_platform.core.base.models import BaseModel


class Widget(BaseModel):
    """Botble-style per-theme widget placement."""

    __tablename__ = "widgets"
    __table_args__ = (
        Index("idx_widgets_theme_sidebar", "theme", "sidebar_id", "position"),
        Index("idx_widgets_lookup", "theme", "sidebar_id", "widget_id"),
    )

    widget_id: Mapped[str] = mapped_column(String(120), nullable=False)
    sidebar_id: Mapped[str] = mapped_column(String(120), nullable=False)
    theme: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    data: Mapped[dict | list | None] = mapped_column(JSON, nullable=True, default=dict)
