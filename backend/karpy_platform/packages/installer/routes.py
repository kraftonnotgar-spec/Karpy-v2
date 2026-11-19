from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, EmailStr, Field, model_validator
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db, init_db
from karpy_platform.core.acl.models import Activation, RoleUser, User
from karpy_platform.core.acl.routes import hash_password, permission_catalog
from karpy_platform.core.base.hooks import hooks
from karpy_platform.core.base.responses import BaseHttpResponse
from karpy_platform.packages.installer.constants import (
    INSTALLER_ACTION_ENVIRONMENT_SAVED,
    INSTALLER_ACTION_FINISHED,
)
from karpy_platform.packages.installer.service import installer_service

async def installer_open(request: Request, db: AsyncSession = Depends(get_db)) -> None:
    """Installer writes are allowed only before the first install completes.

    Without this, anyone reaching the API could wipe every user and create a
    new super admin, or rewrite the environment file.
    """
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return
    if settings.is_production or await installer_service.is_installed(db):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "installer_locked")


router = APIRouter(dependencies=[Depends(installer_open)])


class WelcomeRequest(BaseModel):
    language: str = Field(default="en", min_length=2, max_length=12)


class EnvironmentRequest(BaseModel):
    app_name: str = Field(default=settings.APP_NAME, min_length=2, max_length=120)
    app_url: str = Field(default=settings.APP_URL, min_length=4, max_length=255)
    app_env: Literal["local", "development", "staging", "production"] = settings.APP_ENV
    debug: bool = settings.DEBUG
    database_url: str = Field(default=settings.DATABASE_URL, min_length=8, max_length=500)
    admin_dir: str = Field(default=settings.ADMIN_DIR, min_length=2, max_length=60)


class AccountRequest(BaseModel):
    first_name: str = Field(min_length=2, max_length=60)
    last_name: str = Field(min_length=2, max_length=60)
    username: str = Field(min_length=4, max_length=30)
    email: EmailStr = Field(max_length=120)
    password: str = Field(min_length=6, max_length=120)
    password_confirmation: str = Field(min_length=6, max_length=120)

    @model_validator(mode="after")
    def validate_confirmation(self) -> "AccountRequest":
        if self.password != self.password_confirmation:
            raise ValueError("Password confirmation does not match password")
        return self


class LicenseRequest(BaseModel):
    buyer: str | None = Field(default=None, max_length=120)
    purchase_code: str | None = Field(default=None, max_length=120)
    skip: bool = False


@router.get("")
async def installer_status(db: AsyncSession = Depends(get_db)):
    return await installer_service.status(db)


@router.post("/welcome")
async def save_welcome(payload: WelcomeRequest):
    await installer_service.mark_installing()
    return BaseHttpResponse.make().set_data({"language": payload.language, "nextStep": "requirements"}).to_dict()


@router.get("/requirements")
async def requirements():
    return await installer_service.requirements()


@router.post("/environment")
async def save_environment(payload: EnvironmentRequest, db: AsyncSession = Depends(get_db)):
    result = await installer_service.save_environment(db, payload.model_dump())
    await init_db()
    await hooks.do_action_async(INSTALLER_ACTION_ENVIRONMENT_SAVED, payload.model_dump())
    return BaseHttpResponse.make().set_data({**result, "nextStep": "account"}).to_dict()


@router.post("/account")
async def save_account(payload: AccountRequest, db: AsyncSession = Depends(get_db)):
    await _replace_super_admin(db, payload)
    return BaseHttpResponse.make().set_data({"nextStep": "license"}).set_message("Admin account created successfully").to_dict()


@router.post("/license")
async def save_license(payload: LicenseRequest, db: AsyncSession = Depends(get_db)):
    if not payload.skip and not payload.purchase_code:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Purchase code is required unless license is skipped")
    await installer_service.save_license(db, payload.buyer, payload.purchase_code, skipped=payload.skip)
    return BaseHttpResponse.make().set_data({"nextStep": "final", "skipped": payload.skip}).to_dict()


@router.post("/license/skip")
async def skip_license(db: AsyncSession = Depends(get_db)):
    await installer_service.save_license(db, None, None, skipped=True)
    return BaseHttpResponse.make().set_data({"nextStep": "final", "skipped": True}).to_dict()


@router.post("/final")
async def finish_installation(db: AsyncSession = Depends(get_db)):
    data = await installer_service.finish(db)
    await hooks.do_action_async(INSTALLER_ACTION_FINISHED, data)
    return BaseHttpResponse.make().set_data(data).set_message("Installation finished successfully").to_dict()


async def _replace_super_admin(db: AsyncSession, payload: AccountRequest) -> User:
    await db.execute(delete(RoleUser))
    await db.execute(delete(Activation))
    await db.execute(delete(User))

    user = User(
        first_name=payload.first_name.capitalize(),
        last_name=payload.last_name.capitalize(),
        username=payload.username,
        email=str(payload.email),
        password=hash_password(payload.password),
        super_user=True,
        manage_supers=True,
        permissions={permission["flag"]: True for permission in permission_catalog()},
    )
    db.add(user)
    await db.flush()
    db.add(Activation(user_id=user.id, code="installed", completed=True))
    await db.commit()
    await db.refresh(user, ["roles"])
    return user
