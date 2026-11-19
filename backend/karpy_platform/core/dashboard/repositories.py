from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from karpy_platform.core.dashboard.models import DashboardWidget, DashboardWidgetSetting
from karpy_platform.core.dashboard.widgets import ensure_widget_setting


class DashboardWidgetRepository:
    async def first_or_create(self, db: AsyncSession, name: str) -> DashboardWidget:
        widget = await db.scalar(select(DashboardWidget).where(DashboardWidget.name == name))
        if widget:
            return widget

        widget = DashboardWidget(name=name)
        db.add(widget)
        await db.commit()
        await db.refresh(widget)
        return widget

    async def get_by_name(self, db: AsyncSession, name: str) -> DashboardWidget | None:
        return await db.scalar(select(DashboardWidget).where(DashboardWidget.name == name))

    async def all(self, db: AsyncSession) -> list[DashboardWidget]:
        result = await db.execute(select(DashboardWidget).order_by(DashboardWidget.name))
        return result.scalars().all()


class DashboardWidgetSettingRepository:
    async def first_or_create(
        self,
        db: AsyncSession,
        widget_name: str,
        user_id: str,
    ) -> DashboardWidgetSetting:
        _, setting = await ensure_widget_setting(db, widget_name, user_id)
        await db.commit()
        await db.refresh(setting)
        return setting

    async def get_list_widget(self, db: AsyncSession, user_id: str) -> list[DashboardWidgetSetting]:
        result = await db.execute(
            select(DashboardWidgetSetting)
            .options(selectinload(DashboardWidgetSetting.widget))
            .where(DashboardWidgetSetting.user_id == user_id)
            .order_by(DashboardWidgetSetting.order)
        )
        return result.scalars().all()


dashboard_widget_repository = DashboardWidgetRepository()
dashboard_widget_setting_repository = DashboardWidgetSettingRepository()
