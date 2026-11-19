from __future__ import annotations

from sqlalchemy import JSON, Boolean, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from karpy_platform.core.base.models import BaseModel


class DashboardWidget(BaseModel):
    __tablename__ = "dashboard_widgets"

    name: Mapped[str] = mapped_column(String(120), unique=True, index=True)

    settings: Mapped[list["DashboardWidgetSetting"]] = relationship(
        "DashboardWidgetSetting",
        back_populates="widget",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class DashboardWidgetSetting(BaseModel):
    __tablename__ = "dashboard_widget_settings"
    __table_args__ = (UniqueConstraint("user_id", "widget_id", name="uq_dashboard_widget_user"),)

    settings: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    widget_id: Mapped[str] = mapped_column(String(36), ForeignKey("dashboard_widgets.id", ondelete="CASCADE"), index=True)
    order: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[bool] = mapped_column(Boolean, default=True)

    widget: Mapped[DashboardWidget] = relationship("DashboardWidget", back_populates="settings")
