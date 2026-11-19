from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from karpy_platform.core.acl.models import User
from karpy_platform.core.acl.routes import ensure_admin_user, hash_password
from karpy_platform.core.base.hooks import hooks
from karpy_platform.core.base.responses import BaseHttpResponse
from karpy_platform.packages.get_started.constants import GET_STARTED_ACTION_SAVED
from karpy_platform.packages.get_started.service import get_started_service

router = APIRouter()


class GetStartedSaveRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    step: int = Field(ge=1, le=4)
    username: str | None = Field(default=None, min_length=4, max_length=30)
    email: EmailStr | None = Field(default=None, min_length=6, max_length=60)
    password: str | None = Field(default=None, min_length=6, max_length=60)
    password_confirmation: str | None = Field(default=None, min_length=6, max_length=60)

    @model_validator(mode="after")
    def validate_account_step(self) -> "GetStartedSaveRequest":
        if self.step != 3:
            return self
        missing = [
            field
            for field in ("username", "email", "password", "password_confirmation")
            if not getattr(self, field)
        ]
        if missing:
            raise ValueError(f"Missing required fields for step 3: {', '.join(missing)}")
        if self.password != self.password_confirmation:
            raise ValueError("Password confirmation does not match password")
        return self


@router.get("")
async def get_started_schema(db: AsyncSession = Depends(get_db)):
    user = await ensure_admin_user(db)
    return await get_started_service.schema(db, user)


@router.get("/notice")
async def get_started_notice(db: AsyncSession = Depends(get_db)):
    if not await get_started_service.should_show(db):
        return {"notice": None}
    return {"notice": get_started_service.dashboard_notice()}


@router.post("/save")
async def save_get_started(payload: GetStartedSaveRequest, db: AsyncSession = Depends(get_db)):
    user = await ensure_admin_user(db)
    step = payload.step
    next_step = step + 1

    if step == 2:
        await get_started_service.save_branding(db, _payload_values(payload))
        if not get_started_service.account_is_default(user):
            next_step = 4

    if step == 3:
        await _update_default_account(db, user, payload)

    if step == 4:
        await get_started_service.complete(db)
        next_step = 4

    await hooks.do_action_async(GET_STARTED_ACTION_SAVED, step, user)
    return BaseHttpResponse.make().set_data({"step": next_step}).to_dict()


async def _update_default_account(db: AsyncSession, user: User, payload: GetStartedSaveRequest) -> None:
    assert payload.email is not None
    assert payload.username is not None
    assert payload.password is not None

    email = str(payload.email)
    if user.email != email:
        existing = await db.scalar(select(User).where(User.email == email, User.id != user.id))
        if existing:
            raise HTTPException(status.HTTP_409_CONFLICT, "Email already exists")
        user.email = email

    if user.username != payload.username:
        existing = await db.scalar(select(User).where(User.username == payload.username, User.id != user.id))
        if existing:
            raise HTTPException(status.HTTP_409_CONFLICT, "Username already exists")
        user.username = payload.username

    user.password = hash_password(payload.password)
    await db.commit()


def _payload_values(payload: GetStartedSaveRequest) -> dict[str, Any]:
    values = payload.model_dump(exclude_none=True)
    values.update(payload.model_extra or {})
    return values
