from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from karpy_platform.core.base.hooks import hooks


class SupportRequest(BaseModel):
    """Base request model with Botble-like validation hook points."""

    @classmethod
    async def validation_rules(cls) -> dict[str, Any]:
        rules: dict[str, Any] = {}
        return await hooks.apply_filters_async("core_request_rules", rules, cls)

    @classmethod
    async def validation_messages(cls) -> dict[str, str]:
        messages: dict[str, str] = {}
        return await hooks.apply_filters_async("core_request_messages", messages, cls)

    @classmethod
    async def validation_attributes(cls) -> dict[str, str]:
        attributes: dict[str, str] = {}
        return await hooks.apply_filters_async("core_request_attributes", attributes, cls)

    async def validation_data(self) -> dict[str, Any]:
        return await hooks.apply_filters_async("core_request_validation_data", self.model_dump(), self)
