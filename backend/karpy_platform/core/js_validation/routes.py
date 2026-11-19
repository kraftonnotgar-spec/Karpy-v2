from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from fastapi import Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from karpy_platform.core.js_validation import js_validator
from karpy_platform.core.js_validation.remote import validate_remote_field

router = APIRouter()


class ValidationSchemaRequest(BaseModel):
    rules: dict[str, str | list[str]]
    messages: dict[str, str] = Field(default_factory=dict)
    attributes: dict[str, str] = Field(default_factory=dict)
    selector: str | None = None
    remote: bool = True
    ignore: str | None = ""


class RemoteValidationRequest(BaseModel):
    field: str
    value: Any = None
    data: dict[str, Any] = Field(default_factory=dict)
    rules: dict[str, str | list[str]]
    validateAll: bool = False


@router.post("/js-validation/schema")
async def build_validation_schema(data: ValidationSchemaRequest):
    validator = js_validator.make(data.rules, data.messages, data.attributes, data.selector)
    validator.remote(data.remote).ignore(data.ignore)
    return validator.to_dict()


@router.post("/js-validation/render")
async def render_validation_script(data: ValidationSchemaRequest):
    validator = js_validator.make(data.rules, data.messages, data.attributes, data.selector)
    validator.remote(data.remote).ignore(data.ignore)
    return {"html": validator.render()}


@router.post("/js-validation/remote")
async def remote_validate(data: RemoteValidationRequest, db: AsyncSession = Depends(get_db)):
    return {
        "result": await validate_remote_field(
            data.field,
            data.value,
            data.data,
            data.rules,
            validate_all=data.validateAll,
            db=db,
        )
    }
