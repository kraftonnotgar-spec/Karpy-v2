from __future__ import annotations

from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy import select

from app.database import get_db
from karpy_platform.core.acl.models import User
from karpy_platform.core.acl.routes import admin_capable
from karpy_platform.plugins.auth.account_state import account_status
from karpy_platform.plugins.social_login.services.google import (
    SocialLoginError,
    consume_flow,
    create_google_flow,
    exchange_code,
    google_configuration,
    resolve_social_user,
    safe_return_to,
    verify_google_identity,
)

router = APIRouter()


@router.get("/providers")
async def providers(db: AsyncSession = Depends(get_db)) -> dict:
    config = await google_configuration(db)
    return {
        "enabled": config.globally_enabled,
        "style": config.style,
        "providers": [
            {
                "key": "google",
                "name": "Google",
                "enabled": config.enabled,
                "configured": bool(config.client_id and config.client_secret),
                "loginUrl": "/api/plugins/social_login/google/redirect",
            }
        ],
    }


@router.get("/status")
async def status(db: AsyncSession = Depends(get_db)) -> dict:
    config = await google_configuration(db)
    return {
        "enabled": config.globally_enabled,
        "style": config.style,
        "google": {
            "enabled": config.enabled,
            "configured": config.configured,
            "hasClientId": bool(config.client_id),
            "hasClientSecret": bool(config.client_secret),
            "allowRegistration": config.allow_registration,
            "callbackUrl": config.callback_url,
        },
    }


@router.get("/google/redirect")
async def google_redirect(
    request: Request,
    return_to: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    config = await google_configuration(db)
    if not config.configured:
        raise HTTPException(400, "Google login is disabled or incomplete in Settings -> Others -> Social Login.")
    origin = str(request.base_url).rstrip("/")
    target = safe_return_to(return_to, origin)
    authorization_url = await create_google_flow(db, config, target)
    return RedirectResponse(authorization_url, status_code=302)


def _error_redirect(return_to: str, message: str) -> RedirectResponse:
    separator = "&" if "?" in return_to else "?"
    return RedirectResponse(f"{return_to}{separator}{urlencode({'social_login_error': message})}", status_code=302)


@router.get("/google/callback")
async def google_callback(
    state: str | None = None,
    code: str | None = None,
    error: str | None = None,
    error_description: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    if not state:
        raise HTTPException(400, "Missing OAuth state.")
    flow = await consume_flow(db, state)
    if error:
        return _error_redirect(flow.return_to, error_description or "Google login was cancelled.")
    if not code:
        return _error_redirect(flow.return_to, "Google did not return an authorization code.")
    try:
        config = await google_configuration(db)
        if not config.configured:
            raise SocialLoginError("Google login was disabled before the request completed.")
        token_data = await exchange_code(config, flow, code)
        claims = await verify_google_identity(str(token_data["id_token"]), config, flow.nonce)
        user = await resolve_social_user(db, claims, config.allow_registration)
        user = await db.scalar(select(User).options(selectinload(User.roles), selectinload(User.meta)).where(User.id == user.id))
        # Google never grants admin rights, and never an admin session: those need password + authenticator code.
        if not user or account_status(user) != "active" or not admin_capable(user):
            raise SocialLoginError("This account cannot sign in to the admin dashboard.")
        raise SocialLoginError("Sign in to the admin dashboard with your password and authenticator code.")
    except SocialLoginError as exc:
        return _error_redirect(flow.return_to, str(exc))
    except Exception:
        return _error_redirect(flow.return_to, "Google login could not be completed. Please try again.")
