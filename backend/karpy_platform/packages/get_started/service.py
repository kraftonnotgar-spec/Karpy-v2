from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from karpy_platform.core.base.hooks import hooks
from karpy_platform.core.dashboard.constants import DASHBOARD_FILTER_ADMIN_NOTIFICATIONS
from karpy_platform.core.setting.registry import SettingField, SettingSection, setting_panel_registry
from karpy_platform.core.setting.store import setting_store
from karpy_platform.packages.get_started.constants import (
    GET_STARTED_COMPLETED_KEY,
    GET_STARTED_FILTER_SCHEMA,
    GET_STARTED_PACKAGE_ID,
)


@dataclass
class WizardField:
    key: str
    label: str
    type: str = "text"
    default: Any = ""
    required: bool = False
    description: str = ""

    def to_dict(self, values: dict[str, Any]) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "type": self.type,
            "value": values.get(self.key, self.default),
            "default": self.default,
            "required": self.required,
            "description": self.description,
        }


@dataclass
class WizardStep:
    step: int
    title: str
    description: str
    action_label: str
    fields: list[WizardField] = field(default_factory=list)

    def to_dict(self, values: dict[str, Any]) -> dict[str, Any]:
        return {
            "step": self.step,
            "title": self.title,
            "description": self.description,
            "actionLabel": self.action_label,
            "fields": [field.to_dict(values) for field in self.fields],
        }


class GetStartedService:
    """Python port of Botble's packages/get-started onboarding engine."""

    theme_option_fields = {
        "primary_color",
        "primary_font",
        "site_title",
        "logo",
        "favicon",
    }

    admin_setting_fields = {
        "site_title",
        "admin_logo",
        "admin_favicon",
    }

    def __init__(self) -> None:
        self._booted = False

    async def should_show(self, db: AsyncSession) -> bool:
        completed = await setting_store.get(db, GET_STARTED_COMPLETED_KEY, "0")
        return str(completed) != "1"

    async def schema(self, db: AsyncSession, user: Any | None = None) -> dict[str, Any]:
        values = await setting_store.all(db, flat=True)
        theme_values = self._theme_values(values)
        completed = str(values.get(GET_STARTED_COMPLETED_KEY, "0")) == "1"
        account_is_default = self.account_is_default(user)
        steps = [step.to_dict({**values, **theme_values}) for step in self.steps(account_is_default)]
        payload = {
            "id": GET_STARTED_PACKAGE_ID,
            "completed": completed,
            "shouldShow": not completed,
            "currentStep": 1 if not completed else 4,
            "saveAction": "/api/admin/get-started/save",
            "notice": self.dashboard_notice(),
            "steps": steps,
        }
        return await hooks.apply_filters_async(GET_STARTED_FILTER_SCHEMA, payload, values, user)

    def steps(self, account_is_default: bool = True) -> list[WizardStep]:
        steps = [
            WizardStep(
                step=1,
                title="Welcome to KARPy",
                description="Make the site ready in a few steps.",
                action_label="Get started",
            ),
            WizardStep(
                step=2,
                title="Customize branding",
                description="Set the site identity, logo, favicon, color, and admin brand assets.",
                action_label="Next step",
                fields=[
                    WizardField("site_title", "Site title", default="KARPy CMS", required=True),
                    WizardField("primary_color", "Primary color", type="color", default="#206bc4"),
                    WizardField("primary_font", "Primary font", default="Inter"),
                    WizardField("logo", "Logo", type="media"),
                    WizardField("favicon", "Favicon", type="media"),
                    WizardField("admin_logo", "Admin logo", type="media"),
                    WizardField("admin_favicon", "Admin favicon", type="media"),
                ],
            ),
        ]
        if account_is_default:
            steps.append(
                WizardStep(
                    step=3,
                    title="Change default account info",
                    description="Replace the default admin username, email, and password.",
                    action_label="Next step",
                    fields=[
                        WizardField("username", "Username", required=True),
                        WizardField("email", "Email", type="email", required=True),
                        WizardField("password", "Password", type="password", required=True),
                        WizardField("password_confirmation", "Password confirmation", type="password", required=True),
                    ],
                )
            )
        steps.append(
            WizardStep(
                step=4,
                title="Your site is ready",
                description="Finish the wizard and hide the setup reminder.",
                action_label="Finish",
            )
        )
        return steps

    def account_is_default(self, user: Any | None) -> bool:
        if not user:
            return True
        return (user.username or "") == "admin" or (user.email or "") == "admin@company.com"

    async def save_branding(self, db: AsyncSession, values: dict[str, Any]) -> None:
        direct_settings: dict[str, Any] = {}
        theme_settings: dict[str, Any] = {}

        for key, value in values.items():
            if value is None or key in {"step", "username", "email", "password", "password_confirmation"}:
                continue
            if key in self.theme_option_fields:
                theme_settings[f"theme_options.{key}"] = value
            if key in self.admin_setting_fields:
                direct_settings[key] = value
            if key == "primary_color":
                direct_settings["admin_primary_color"] = value

        if direct_settings:
            await setting_store.set(db, direct_settings)
        if theme_settings:
            await setting_store.set(db, theme_settings)
        await setting_store.save(db)

    async def complete(self, db: AsyncSession) -> None:
        await setting_store.set(db, GET_STARTED_COMPLETED_KEY, "1")
        await setting_store.save(db)

    def dashboard_notice(self) -> dict[str, Any]:
        return {
            "id": GET_STARTED_PACKAGE_ID,
            "type": "info",
            "title": "Setup wizard",
            "message": "Your site setup is not completed yet.",
            "action": {
                "label": "Resume setup wizard",
                "url": "/admin/get-started",
                "api": "/api/admin/get-started",
            },
        }

    def register_theme_field(self, key: str) -> None:
        self.theme_option_fields.add(key)

    def boot(self) -> None:
        if self._booted:
            return
        setting_panel_registry.register_section(
            SettingSection(
                id="get_started",
                title="Get Started",
                description="Onboarding state for the setup wizard.",
                icon="sparkles",
                route="/admin/get-started",
                priority=5,
                group="settings.others",
                source="package:get-started",
                hidden=True,
                fields=[
                    SettingField(
                        GET_STARTED_COMPLETED_KEY,
                        "Completed setup wizard",
                        type="switch",
                        default="0",
                    )
                ],
            )
        )
        hooks.add_filter(DASHBOARD_FILTER_ADMIN_NOTIFICATIONS, self._add_dashboard_notice, priority=4)
        self._booted = True

    async def _add_dashboard_notice(
        self,
        notifications: list[dict[str, Any]],
        widget_data: list[dict[str, Any]] | None = None,
        db: AsyncSession | None = None,
    ) -> list[dict[str, Any]]:
        if db and await self.should_show(db):
            notifications.append(self.dashboard_notice())
        return notifications

    def _theme_values(self, values: dict[str, Any]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        prefix = "theme_options."
        for key, value in values.items():
            if key.startswith(prefix):
                result[key.removeprefix(prefix)] = value
        return result


get_started_service = GetStartedService()


def boot_get_started_package() -> None:
    get_started_service.boot()
