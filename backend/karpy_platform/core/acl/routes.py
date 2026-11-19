from __future__ import annotations

import re
import secrets
import hashlib
import hmac
import time
from datetime import timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.database import get_db
from karpy_platform.core.acl.models import Activation, Notification, Role, RoleUser, User, UserMeta, utcnow
from karpy_platform.core.setting.phone import validate_phone_number
from karpy_platform.core.setting.store import setting_store

router = APIRouter()


ACL_PERMISSIONS = [
    {"name": "Dashboard", "flag": "dashboard.index", "parent_flag": None},
    {"name": "Dashboard Analytics", "flag": "dashboard.analytics", "parent_flag": "dashboard.index"},
    {"name": "CMS", "flag": "cms.index", "parent_flag": None},
    {"name": "Pages", "flag": "pages.index", "parent_flag": "cms.index"},
    {"name": "Create", "flag": "pages.create", "parent_flag": "pages.index"},
    {"name": "Edit", "flag": "pages.edit", "parent_flag": "pages.index"},
    {"name": "Delete", "flag": "pages.destroy", "parent_flag": "pages.index"},
    {"name": "Media", "flag": "media.index", "parent_flag": "cms.index"},
    {"name": "Upload", "flag": "media.upload", "parent_flag": "media.index"},
    {"name": "Edit", "flag": "media.edit", "parent_flag": "media.index"},
    {"name": "Delete", "flag": "media.destroy", "parent_flag": "media.index"},
    {"name": "Plugins", "flag": "plugins.index", "parent_flag": None},
    {"name": "Activate", "flag": "plugins.activate", "parent_flag": "plugins.index"},
    {"name": "Deactivate", "flag": "plugins.deactivate", "parent_flag": "plugins.index"},
    {"name": "Marketplace", "flag": "plugins.marketplace", "parent_flag": "plugins.index"},
    {"name": "Appearance", "flag": "appearance.index", "parent_flag": None},
    {"name": "Themes", "flag": "theme.index", "parent_flag": "appearance.index"},
    {"name": "Theme Options", "flag": "theme.options", "parent_flag": "appearance.index"},
    {"name": "Menus", "flag": "menus.index", "parent_flag": "appearance.index"},
    {"name": "Widgets", "flag": "widgets.index", "parent_flag": "appearance.index"},
    {"name": "Settings", "flag": "settings.index", "parent_flag": None},
    {"name": "Common", "flag": "settings.common", "parent_flag": "settings.index"},
    {"name": "Website Tracking", "flag": "settings.tracking", "parent_flag": "settings.index"},
    {"name": "Tools", "flag": "core.tools", "parent_flag": None},
    {"name": "Export/Import Data", "flag": "tools.data-synchronize", "parent_flag": "core.tools"},
    {"name": "Shortcodes", "flag": "shortcodes.index", "parent_flag": "core.tools"},
    {"name": "Sitemap", "flag": "sitemap.index", "parent_flag": "core.tools"},
    {"name": "Optimize", "flag": "optimize.index", "parent_flag": "core.tools"},
    {"name": "Icons", "flag": "icons.index", "parent_flag": "core.tools"},
    {"name": "Tables", "flag": "tables.index", "parent_flag": "core.tools"},
    {"name": "Locations", "flag": "plugin.location", "parent_flag": None},
    {"name": "Countries", "flag": "country.index", "parent_flag": "plugin.location"},
    {"name": "Create", "flag": "country.create", "parent_flag": "country.index"},
    {"name": "Edit", "flag": "country.edit", "parent_flag": "country.index"},
    {"name": "Delete", "flag": "country.destroy", "parent_flag": "country.index"},
    {"name": "States", "flag": "state.index", "parent_flag": "plugin.location"},
    {"name": "Create", "flag": "state.create", "parent_flag": "state.index"},
    {"name": "Edit", "flag": "state.edit", "parent_flag": "state.index"},
    {"name": "Delete", "flag": "state.destroy", "parent_flag": "state.index"},
    {"name": "Cities", "flag": "city.index", "parent_flag": "plugin.location"},
    {"name": "Create", "flag": "city.create", "parent_flag": "city.index"},
    {"name": "Edit", "flag": "city.edit", "parent_flag": "city.index"},
    {"name": "Delete", "flag": "city.destroy", "parent_flag": "city.index"},
    {"name": "Platform Administration", "flag": "core.system", "parent_flag": None},
    {"name": "Users", "flag": "users.index", "parent_flag": "core.system"},
    {"name": "Create", "flag": "users.create", "parent_flag": "users.index"},
    {"name": "Edit", "flag": "users.edit", "parent_flag": "users.index"},
    {"name": "Delete", "flag": "users.destroy", "parent_flag": "users.index"},
    {"name": "Roles", "flag": "roles.index", "parent_flag": "core.system"},
    {"name": "Create", "flag": "roles.create", "parent_flag": "roles.index"},
    {"name": "Edit", "flag": "roles.edit", "parent_flag": "roles.index"},
    {"name": "Delete", "flag": "roles.destroy", "parent_flag": "roles.index"},
    {"name": "Request Logs", "flag": "request-logs.index", "parent_flag": "core.system"},
    {"name": "Activity Logs", "flag": "activity-logs.index", "parent_flag": "core.system"},
    {"name": "Backup", "flag": "backup.index", "parent_flag": "core.system"},
    {"name": "Cronjob", "flag": "cronjob.index", "parent_flag": "core.system"},
    {"name": "Security Settings", "flag": "security.index", "parent_flag": "core.system"},
    {"name": "Cache Management", "flag": "cache.index", "parent_flag": "core.system"},
    {"name": "Cleanup System", "flag": "cleanup.index", "parent_flag": "core.system"},
    {"name": "System Information", "flag": "system.information", "parent_flag": "core.system"},
    {"name": "System Updater", "flag": "system.updater", "parent_flag": "core.system"},
]

SUPER_ADMIN_ROLE_SLUG = "super-admin"
SUPER_ADMIN_ROLE_NAME = "Super Admin"
ADMIN_SESSION_COOKIE = "karpy_admin_session"
ADMIN_SESSION_MAX_AGE = 60 * 60 * 12
# Bumping this per-user value revokes every admin session for that user.
ADMIN_SESSION_EPOCH_KEY = "admin.session_epoch"
ADMIN_LOGIN_WINDOW_MINUTES = 15
ADMIN_LOGIN_MAX_PER_IP = 5
ADMIN_LOGIN_MAX_PER_IDENTITY = 20
DEFAULT_BOOTSTRAP_PASSWORD = "12345678"
# Equalizes timing when the login does not match any account.
_DUMMY_PASSWORD_HASH = "pbkdf2_sha256$00000000000000000000000000000000$" + "0" * 64


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
    return slug or secrets.token_hex(4)


def permission_catalog() -> list[dict[str, str | None]]:
    """Return core and active-plugin permissions without coupling ACL to a plugin."""
    from karpy_platform.packages.plugin_management.service import plugin_service

    combined = [*ACL_PERMISSIONS, *plugin_service.get_permissions()]
    unique: dict[str, dict[str, str | None]] = {}
    for permission in combined:
        flag = str(permission.get("flag") or "").strip()
        if flag and flag not in unique:
            unique[flag] = permission
    return list(unique.values())


def clean_permissions(flags: list[str] | None) -> dict[str, bool]:
    allowed = {permission["flag"] for permission in permission_catalog()}
    return {flag: True for flag in flags or [] if flag in allowed}


def all_acl_permissions() -> dict[str, bool]:
    return {permission["flag"]: True for permission in permission_catalog()}


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 260000)
    return f"pbkdf2_sha256${salt}${digest.hex()}"


def verify_password(password: str, hashed: str | None) -> bool:
    if not hashed:
        return False
    try:
        algorithm, salt, digest = hashed.split("$", 2)
    except ValueError:
        return False
    if algorithm != "pbkdf2_sha256":
        return False
    candidate = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 260000).hex()
    return hmac.compare_digest(candidate, digest)


def password_fingerprint(password_hash: str | None) -> str:
    """Binds admin sessions to the current password: changing it ends them."""
    return hashlib.sha256(password_hash.encode("utf-8")).hexdigest()[:32] if password_hash else ""


def session_signature(user_id: str, issued_at: int, epoch: str = "0", fingerprint: str = "") -> str:
    message = f"{user_id}:{issued_at}:{epoch}:{fingerprint}".encode("utf-8")
    secret = settings.SECRET_KEY.encode("utf-8")
    return hmac.new(secret, message, hashlib.sha256).hexdigest()


def make_session_token(user_id: str, epoch: str = "0", fingerprint: str = "") -> str:
    issued_at = int(time.time())
    return f"{user_id}:{issued_at}:{session_signature(user_id, issued_at, epoch, fingerprint)}"


def parse_session_token(token: str | None) -> tuple[str, int, str] | None:
    if not token or len(token) > 512:
        return None
    try:
        user_id, issued_at_raw, signature = token.split(":", 2)
        issued_at = int(issued_at_raw)
    except ValueError:
        return None
    age = int(time.time()) - issued_at
    if age > ADMIN_SESSION_MAX_AGE or age < -60:
        return None
    return user_id, issued_at, signature


async def admin_session_epoch(db: AsyncSession, user_id: str) -> str:
    value = await db.scalar(
        select(UserMeta.value).where(UserMeta.user_id == user_id, UserMeta.key == ADMIN_SESSION_EPOCH_KEY)
    )
    return value or "0"


async def revoke_admin_sessions(db: AsyncSession, user_id: str) -> None:
    """Invalidate every admin session of this user (caller commits)."""
    item = await db.scalar(
        select(UserMeta).where(UserMeta.user_id == user_id, UserMeta.key == ADMIN_SESSION_EPOCH_KEY)
    )
    value = secrets.token_hex(8)
    if item:
        item.value = value
    else:
        db.add(UserMeta(user_id=user_id, key=ADMIN_SESSION_EPOCH_KEY, value=value))


async def issue_admin_session(db: AsyncSession, response: Response, user: User) -> None:
    epoch = await admin_session_epoch(db, user.id)
    attach_session_cookie(response, make_session_token(user.id, epoch, password_fingerprint(user.password)))


# Console permissions held by staff (not Super Admins) that admit them to a console area.
# Plugins add theirs with the ``acl.console_flags`` filter (a list of permission keys).
CONSOLE_FLAGS: tuple[str, ...] = ()


def console_flags() -> tuple[str, ...]:
    from karpy_platform.core.base.hooks import hooks
    return tuple(dict.fromkeys([*CONSOLE_FLAGS, *hooks.apply_filters("acl.console_flags", [])]))


def role_flags_of(user: User) -> set[str]:
    granted = {flag for flag, allowed in (user.permissions or {}).items() if allowed}
    for role in user.roles or []:
        granted |= {flag for flag, allowed in (role.permissions or {}).items() if allowed}
    return granted


def admin_capable(user: User) -> bool:
    """Super users, or users granted at least one platform ACL or console permission."""
    if user.super_user:
        return True
    known = {item["flag"] for item in ACL_PERMISSIONS} | set(console_flags())
    return bool(role_flags_of(user) & known)


def console_permissions(user: User) -> list[str]:
    if user.super_user:
        return list(console_flags())
    return sorted(role_flags_of(user) & set(console_flags()))


def attach_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        ADMIN_SESSION_COOKIE,
        token,
        max_age=ADMIN_SESSION_MAX_AGE,
        # Admin sessions are never readable by scripts nor sent cross-site.
        httponly=True,
        secure=settings.secure_cookies,
        samesite="strict",
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(ADMIN_SESSION_COOKIE, path="/")


async def ensure_super_admin_role(db: AsyncSession) -> Role:
    role = await db.scalar(select(Role).where(Role.slug == SUPER_ADMIN_ROLE_SLUG))
    if role:
        role.name = SUPER_ADMIN_ROLE_NAME
        role.permissions = all_acl_permissions()
        return role

    role = Role(
        slug=SUPER_ADMIN_ROLE_SLUG,
        name=SUPER_ADMIN_ROLE_NAME,
        description="Full platform access for super administrators.",
        permissions=all_acl_permissions(),
        is_default=False,
    )
    db.add(role)
    await db.flush()
    return role


async def sync_super_admin_role(db: AsyncSession, user: User, enabled: bool) -> None:
    role = await ensure_super_admin_role(db)
    has_role = any(existing.id == role.id for existing in user.roles)

    if enabled and not has_role:
        user.roles.append(role)
    elif not enabled and has_role:
        user.roles = [existing for existing in user.roles if existing.id != role.id]


def bootstrap_admin_password() -> str:
    value = settings.ADMIN_BOOTSTRAP_PASSWORD
    if settings.is_production and (not value or len(value) < 20 or value == DEFAULT_BOOTSTRAP_PASSWORD):
        raise HTTPException(status_code=503, detail="Secure administrator bootstrap is not configured.")
    return value or DEFAULT_BOOTSTRAP_PASSWORD


async def ensure_admin_user(db: AsyncSession) -> User:
    result = await db.execute(select(User).options(selectinload(User.roles)).limit(1))
    user = result.scalar_one_or_none()

    if user:
        if user.username == "admin" and not user.password:
            user.password = hash_password(bootstrap_admin_password())
        if user.super_user:
            await sync_super_admin_role(db, user, True)
            user.manage_supers = True
            user.permissions = all_acl_permissions()
            await db.commit()
            await db.refresh(user, ["roles"])
        return user

    role = await ensure_super_admin_role(db)
    user = User(
        first_name="System",
        last_name="Admin",
        username=settings.ADMIN_BOOTSTRAP_USERNAME,
        email=settings.ADMIN_BOOTSTRAP_EMAIL,
        password=hash_password(bootstrap_admin_password()),
        super_user=True,
        manage_supers=True,
        permissions=all_acl_permissions(),
    )
    db.add(user)
    await db.flush()
    db.add(RoleUser(user_id=user.id, role_id=role.id))

    activation = Activation(
        user_id=user.id,
        code=secrets.token_urlsafe(32),
        completed=True,
        completed_at=utcnow(),
    )
    db.add(activation)
    await db.commit()
    await db.refresh(user, ["roles"])
    return user


def user_payload(user: User) -> dict:
    return {
        "id": user.id,
        "firstName": user.first_name,
        "lastName": user.last_name,
        "name": user.name,
        "username": user.username,
        "email": user.email,
        "phone": user.phone,
        "avatar": user.avatar,
        "avatarId": user.avatar_id,
        "superUser": user.super_user,
        "manageSupers": user.manage_supers,
        "permissions": user.permissions or {},
        "roles": [{"id": role.id, "name": role.name, "slug": role.slug} for role in user.roles],
        "lastLogin": user.last_login.isoformat() if user.last_login else None,
        "createdAt": user.created_at.isoformat() if user.created_at else None,
        "updatedAt": user.updated_at.isoformat() if user.updated_at else None,
    }


def role_payload(role: Role) -> dict:
    return {
        "id": role.id,
        "name": role.name,
        "slug": role.slug,
        "description": role.description,
        "permissions": role.permissions or {},
        "isDefault": role.is_default,
        "createdBy": role.created_by,
        "updatedBy": role.updated_by,
        "usersCount": len(role.users),
        "createdAt": role.created_at.isoformat() if role.created_at else None,
        "updatedAt": role.updated_at.isoformat() if role.updated_at else None,
    }


class ProfileUpdate(BaseModel):
    firstName: Optional[str] = Field(default=None, min_length=2, max_length=60)
    lastName: Optional[str] = Field(default=None, min_length=2, max_length=60)
    username: Optional[str] = Field(default=None, min_length=3, max_length=120)
    email: Optional[EmailStr] = Field(default=None, max_length=120)
    phone: Optional[str] = Field(default=None, max_length=30)
    currentPassword: Optional[str] = Field(default=None, max_length=120)
    newPassword: Optional[str] = Field(default=None, min_length=12, max_length=120)
    avatar: Optional[str] = None
    code: str = Field(default="", max_length=64)


class UserCreate(BaseModel):
    firstName: str = Field(min_length=2, max_length=60)
    lastName: str = Field(min_length=2, max_length=60)
    username: str = Field(min_length=3, max_length=120)
    email: EmailStr
    password: str = Field(min_length=12, max_length=120)
    phone: Optional[str] = Field(default=None, max_length=30)
    roleId: Optional[str] = None
    permissions: list[str] = Field(default_factory=list)

    @field_validator("username")
    @classmethod
    def validate_username(cls, value: str) -> str:
        if not re.match(r"^[A-Za-z0-9_-]+$", value):
            raise ValueError("Username may only contain letters, numbers, dashes and underscores")
        return value


class UserUpdate(BaseModel):
    firstName: Optional[str] = Field(default=None, min_length=2, max_length=60)
    lastName: Optional[str] = Field(default=None, min_length=2, max_length=60)
    username: Optional[str] = Field(default=None, min_length=3, max_length=120)
    email: Optional[EmailStr] = None
    password: Optional[str] = Field(default=None, min_length=12, max_length=120)
    phone: Optional[str] = Field(default=None, max_length=30)
    roleIds: Optional[list[str]] = None
    permissions: Optional[list[str]] = None
    superUser: Optional[bool] = None
    manageSupers: Optional[bool] = None


class RoleCreate(BaseModel):
    name: str = Field(min_length=3, max_length=120)
    description: Optional[str] = Field(default=None, max_length=255)
    permissions: list[str] = Field(default_factory=list)
    isDefault: bool = False


class RoleUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=3, max_length=120)
    description: Optional[str] = Field(default=None, max_length=255)
    permissions: Optional[list[str]] = None
    isDefault: Optional[bool] = None


class AssignRole(BaseModel):
    roleId: str


class LoginRequest(BaseModel):
    login: Optional[str] = Field(default=None, min_length=1, max_length=120)
    username: Optional[str] = Field(default=None, min_length=1, max_length=120)
    email: Optional[EmailStr] = None
    password: str = Field(min_length=1, max_length=120)
    remember: bool = False
    code: str = Field(default="", max_length=64)

    def login_value(self) -> str:
        return (self.login or self.username or self.email or "").strip()


async def current_admin_user(request: Request, db: AsyncSession) -> User:
    from karpy_platform.plugins.auth.account_state import account_status

    parsed = parse_session_token(request.cookies.get(ADMIN_SESSION_COOKIE))
    if not parsed:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Unauthenticated")
    user_id, issued_at, signature = parsed
    user = await db.scalar(
        select(User).options(selectinload(User.roles), selectinload(User.meta)).where(User.id == user_id)
    )
    if not user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Unauthenticated")
    epoch = await admin_session_epoch(db, user.id)
    expected = session_signature(user.id, issued_at, epoch, password_fingerprint(user.password))
    # Revoked (logout/epoch bump), password changed, or banned: the session is over.
    if not hmac.compare_digest(expected, signature) or account_status(user) != "active":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Unauthenticated")
    return user


def granted_flags(user: User) -> set[str]:
    if user.super_user:
        return {item["flag"] for item in ACL_PERMISSIONS}
    granted = {flag for flag, allowed in (user.permissions or {}).items() if allowed}
    for role in user.roles or []:
        granted |= {flag for flag, allowed in (role.permissions or {}).items() if allowed}
    return granted


def require_acl(flag: str):
    """Route dependency: a signed-in admin holding `flag` (super users hold all)."""

    async def dependency(request: Request, db: AsyncSession = Depends(get_db)) -> User:
        user = await current_admin_user(request, db)
        if flag not in granted_flags(user):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "permission_denied")
        return user

    return dependency


def ensure_can_grant(actor: User, flags: set[str]) -> None:
    """Admins may only hand out permissions they hold themselves."""
    if not actor.super_user and not flags <= granted_flags(actor):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "permission_denied")


def ensure_can_manage_supers(actor: User) -> None:
    if not (actor.super_user and actor.manage_supers):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "permission_denied")


def _role_flags(role: Role) -> set[str]:
    return {flag for flag, allowed in (role.permissions or {}).items() if allowed}


def _client_ip(request: Request) -> str:
    # Uvicorn resolves forwarded headers only for FORWARDED_ALLOW_IPS peers.
    return (request.client.host if request.client else "unknown")[:64]


async def _admin_event(db: AsyncSession, request: Request, identity: str, event: str, user_id: str | None = None) -> None:
    from karpy_platform.plugins.auth.models import AuthSecurityEvent

    if event == "admin.login.succeeded" and user_id:
        # Plugins (e.g. "admin sign-in from a new device" alerts) run before this sign-in is recorded.
        from karpy_platform.plugins.auth import extensions
        await extensions.action("acl.admin_signed_in", db, user_id, _client_ip(request), request.headers.get("user-agent", ""))
    db.add(AuthSecurityEvent(
        identity=identity[:160], event=event, user_id=user_id,
        ip_address=_client_ip(request), user_agent=request.headers.get("user-agent", "")[:500],
    ))
    if event == "admin.login.failed":
        # Repeated failed admin password or authenticator checks: security listeners decide.
        from karpy_platform.plugins.auth import extensions
        await extensions.security_event(event, _client_ip(request), identity)


async def _admin_login_blocked(db: AsyncSession, identity: str, ip: str) -> bool:
    from karpy_platform.plugins.auth.models import AuthSecurityEvent

    since = utcnow() - timedelta(minutes=ADMIN_LOGIN_WINDOW_MINUTES)
    failures = select(func.count()).select_from(AuthSecurityEvent).where(
        AuthSecurityEvent.identity == identity,
        AuthSecurityEvent.event == "admin.login.failed",
        AuthSecurityEvent.created_at >= since,
    )
    from_ip = int(await db.scalar(failures.where(AuthSecurityEvent.ip_address == ip)) or 0)
    overall = int(await db.scalar(failures) or 0)
    all_ip = int(await db.scalar(select(func.count()).select_from(AuthSecurityEvent).where(
        AuthSecurityEvent.event == "admin.login.failed", AuthSecurityEvent.ip_address == ip,
        AuthSecurityEvent.created_at >= since)) or 0)
    return from_ip >= ADMIN_LOGIN_MAX_PER_IP or overall >= ADMIN_LOGIN_MAX_PER_IDENTITY or all_ip >= 20


@router.get("/auth/status")
async def auth_status(request: Request, db: AsyncSession = Depends(get_db)):
    await ensure_admin_user(db)
    try:
        user = await current_admin_user(request, db)
    except HTTPException:
        return {"authenticated": False, "user": None}
    from karpy_platform.plugins.auth.account_timezone import account_timezone
    # Display-only: admin timestamps follow the account's country timezone (None when unknown).
    return {"authenticated": True, "user": {**user_payload(user), "consolePermissions": console_permissions(user), "timezone": account_timezone(user)}}


@router.post("/auth/login")
async def login_admin(data: LoginRequest, request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    from karpy_platform.plugins.auth.account_state import account_status

    await ensure_admin_user(db)
    login_value = data.login_value().lower()
    if not login_value:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            {"message": "Login is required.", "errors": {"username": "The username or email field is required."}},
        )
    identity = f"admin:{login_value}"[:160]
    if await _admin_login_blocked(db, identity, _client_ip(request)):
        from karpy_platform.plugins.auth import extensions
        await extensions.security_event("admin.login.blocked", _client_ip(request), identity)
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            {"message": "Too many sign-in attempts. Please try again later."},
            headers={"Retry-After": str(ADMIN_LOGIN_WINDOW_MINUTES * 60)},
        )
    result = await db.execute(
        select(User)
        .options(selectinload(User.roles), selectinload(User.meta))
        .where((func.lower(User.email) == login_value) | (func.lower(User.username) == login_value))
        .limit(1)
        .with_for_update()
    )
    user = result.scalar_one_or_none()
    # Always run one hash check so unknown logins take the same time as wrong passwords.
    password_ok = verify_password(data.password, user.password if user else _DUMMY_PASSWORD_HASH)
    # Merchant accounts, inactive accounts and wrong passwords all get the same answer.
    if not user or not password_ok or account_status(user) != "active" or not admin_capable(user):
        # Failure listeners (honeytokens, alerting) only on this path; never change the answer.
        from karpy_platform.plugins.auth import extensions
        extensions.failed_sign_in(request, "admin", login_value, "", account_exists=user is not None)
        await _admin_event(db, request, identity, "admin.login.failed", user.id if user else None)
        await db.commit()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, {"message": "These credentials do not match our records.", "errors": {"login": "These credentials do not match our records."}})

    from karpy_platform.core.acl import mfa
    _, mfa_state = await mfa.load(db, user.id)
    if not mfa_state.get("secret"):
        # Every admin session needs an authenticator: enrol one first, then sign in (/auth/login/setup).
        secret, setup_state, setup_token = mfa.start_sign_in_setup(user.id, identity, password_fingerprint(user.password))
        await mfa.save(db, user.id, setup_state)
        await _admin_event(db, request, identity, "admin.authenticator.setup", user.id)
        await db.commit()
        response.headers["Cache-Control"] = "no-store"
        return {"mfa_setup_required": True, "setup_token": setup_token, "expires_in": mfa.SETUP_TTL,
                **mfa.provisioning(user, secret)}
    if not data.code:
        response.headers["Cache-Control"] = "no-store"
        return {"mfa_required": True}
    if not await mfa.consume(db, user.id, mfa_state, data.code):
        await _admin_event(db, request, identity, "admin.login.failed", user.id)
        await db.commit()
        raise HTTPException(422, "Invalid or already used verification code")
    user.last_login = utcnow()
    await _admin_event(db, request, identity, "admin.login.succeeded", user.id)
    await issue_admin_session(db, response, user)
    await db.commit()
    await db.refresh(user, ["roles"])
    response.headers["Cache-Control"] = "no-store"
    return {"message": "Logged in successfully", "user": user_payload(user)}


class LoginSetupRequest(BaseModel):
    token: str = Field(min_length=1, max_length=256)
    code: str = Field(min_length=1, max_length=64)


@router.post("/auth/login/setup")
async def complete_login_setup(data: LoginSetupRequest, request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    """Confirm the authenticator offered at sign-in; only then is the admin session issued."""
    from karpy_platform.plugins.auth.account_state import account_status
    from karpy_platform.core.acl import mfa
    from karpy_platform.core.security.secrets import decrypt_secret, encrypt_secret

    user_id = mfa.setup_token_user(data.token)
    user = await db.scalar(
        select(User).options(selectinload(User.roles), selectinload(User.meta))
        .where(User.id == user_id).limit(1).with_for_update()
    ) if user_id else None
    state = (await mfa.load(db, user.id))[1] if user else {}
    identity = str(state.get("setup_identity") or "admin:setup")[:160]
    if await _admin_login_blocked(db, identity, _client_ip(request)):
        from karpy_platform.plugins.auth import extensions
        await extensions.security_event("admin.login.blocked", _client_ip(request), identity)
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            {"message": "Too many sign-in attempts. Please try again later."},
            headers={"Retry-After": str(ADMIN_LOGIN_WINDOW_MINUTES * 60)},
        )
    if (not user or account_status(user) != "active" or not admin_capable(user)
            or not mfa.setup_token_matches(state, data.token, password_fingerprint(user.password))):
        await _admin_event(db, request, identity, "admin.login.failed", user.id if user else None)
        await db.commit()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, {"message": "This sign-in has expired. Sign in again."})
    secret = decrypt_secret(state.get("pending"))
    step = mfa.counter(secret, data.code)
    if step is None:
        state["setup_attempts"] = int(state.get("setup_attempts", 0)) + 1
        # Too many wrong codes ends this setup; the admin must sign in with the password again.
        await mfa.save(db, user.id, state if state["setup_attempts"] < mfa.SETUP_MAX_ATTEMPTS else {"setup_identity": identity})
        await _admin_event(db, request, identity, "admin.login.failed", user.id)
        await db.commit()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, {"message": "Invalid verification code"})
    codes, hashed = mfa.new_recovery_codes()
    await mfa.save(db, user.id, {"secret": encrypt_secret(secret), "last": step, "recovery": hashed})
    await revoke_admin_sessions(db, user.id)
    await db.flush()
    user.last_login = utcnow()
    await _admin_event(db, request, identity, "admin.authenticator.enable", user.id)
    await _admin_event(db, request, identity, "admin.login.succeeded", user.id)
    await issue_admin_session(db, response, user)
    await db.commit()
    await db.refresh(user, ["roles"])
    response.headers["Cache-Control"] = "no-store"
    return {"message": "Logged in successfully", "user": user_payload(user), "recovery_codes": codes}


@router.post("/auth/logout")
async def logout_admin(request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    # Ends every admin session of this user server-side, not just this cookie.
    try:
        user = await current_admin_user(request, db)
    except HTTPException:
        user = None
    if user:
        await revoke_admin_sessions(db, user.id)
        await _admin_event(db, request, f"admin:{(user.username or user.email or user.id).lower()}", "admin.logout", user.id)
        await db.commit()
    clear_session_cookie(response)
    response.headers["Cache-Control"] = "no-store"
    return {"message": "Logged out successfully"}


@router.get("/profile")
async def get_profile(request: Request, db: AsyncSession = Depends(get_db)):
    await ensure_admin_user(db)
    user = await current_admin_user(request, db)
    await db.refresh(user, ["roles"])
    return user_payload(user)


IDENTITY_STATUS_KEY = "account.identity.status"


async def _identity_verified(db: AsyncSession, user_id: str) -> bool:
    value = await db.scalar(select(UserMeta.value).where(UserMeta.user_id == user_id, UserMeta.key == IDENTITY_STATUS_KEY).limit(1))
    return value == "verified"


def _name_changed(value: Optional[str], current: Optional[str]) -> bool:
    # Resending the saved name (as typed or as stored) is not a change.
    return value is not None and (current or "") not in {value, value.capitalize()}


@router.post("/profile")
async def update_profile(data: ProfileUpdate, request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    user = await current_admin_user(request, db)
    await db.execute(select(User.id).where(User.id == user.id).with_for_update())
    await db.refresh(user)
    settings = await setting_store.all(db, flat=True)
    # Sign-in identity and password changes need the current password.
    sensitive = bool(data.newPassword) or any(value is not None and value != current for value, current in
        ((data.email, user.email), (data.username, user.username), (data.phone, user.phone)))
    if sensitive:
        await _security_reauthenticate(db, request, user, data.currentPassword or "", data.code)

    if data.email and data.email != user.email:
        existing = await db.scalar(select(User).where(func.lower(User.email) == data.email.lower(), User.id != user.id))
        if existing:
            raise HTTPException(status.HTTP_409_CONFLICT, "Email already exists")

    if data.username and data.username != user.username:
        existing = await db.scalar(select(User).where(func.lower(User.username) == data.username.lower(), User.id != user.id))
        if existing:
            raise HTTPException(status.HTTP_409_CONFLICT, "Username already exists")
        user.username = data.username

    if data.email and data.email != user.email:
        user.email = data.email
        user.email_verified_at = None

    if await _identity_verified(db, user.id):
        # A verified ID sets the account name; only an administrator can change it after that.
        if _name_changed(data.firstName, user.first_name) or _name_changed(data.lastName, user.last_name):
            raise HTTPException(status.HTTP_409_CONFLICT, "Your name comes from your verified ID.")
    else:
        if data.firstName is not None:
            user.first_name = data.firstName.capitalize()
        if data.lastName is not None:
            user.last_name = data.lastName.capitalize()
    if data.phone is not None:
        try:
            user.phone = validate_phone_number(data.phone, settings)
        except ValueError as exception:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, {"message": "Invalid user data.", "errors": {"phone": str(exception)}}) from exception
    if data.avatar is not None:
        user.avatar = data.avatar
    if data.newPassword:
        user.password = hash_password(data.newPassword)
        await _admin_event(db, request, f"admin:{user.id}", "admin.password.changed", user.id)
    try:
        if sensitive:
            # Keep this browser signed in, but revoke the other admin sessions.
            await revoke_admin_sessions(db, user.id)
            await db.flush()
            await issue_admin_session(db, response, user)
        await _admin_event(db, request, f"admin:{user.id}", "admin.profile.updated", user.id)
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(409, "Email or username already exists") from exc
    return {"status": "success", "message": "Profile updated successfully", "user": user_payload(user)}


class SecurityChange(BaseModel):
    currentPassword: str = Field(min_length=1, max_length=120)
    code: str = Field(default="", max_length=64)


async def _security_reauthenticate(db, request, user, password, code):
    from karpy_platform.plugins.auth.models import AuthSecurityEvent
    from karpy_platform.core.acl import mfa
    failures = await db.scalar(select(func.count()).select_from(AuthSecurityEvent).where(
        AuthSecurityEvent.user_id == user.id, AuthSecurityEvent.event == "admin.security.failed",
        AuthSecurityEvent.created_at >= utcnow() - timedelta(minutes=15)))
    if failures >= 5:
        raise HTTPException(429, "Too many verification attempts", headers={"Retry-After": "900"})
    # mfa requires the user row lock before load/consume (single-use codes).
    await db.execute(select(User.id).where(User.id == user.id).with_for_update())
    _, state = await mfa.load(db, user.id)
    if not verify_password(password, user.password) or (state.get("secret") and not await mfa.consume(db, user.id, state, code)):
        await _admin_event(db, request, f"admin:{user.id}", "admin.security.failed", user.id)
        await db.commit()
        raise HTTPException(422, "Check your current password and verification code")


@router.get("/profile/security")
async def profile_security(request: Request, db: AsyncSession = Depends(get_db)):
    from karpy_platform.core.acl import mfa
    from karpy_platform.plugins.auth.models import AuthSecurityEvent
    user = await current_admin_user(request, db)
    _, state = await mfa.load(db, user.id)
    query = select(AuthSecurityEvent).where(AuthSecurityEvent.event.startswith("admin."))
    if not user.super_user:
        query = query.where(AuthSecurityEvent.user_id == user.id)
    events = (await db.scalars(query.order_by(AuthSecurityEvent.created_at.desc()).limit(100))).all()
    return {"enabled": bool(state.get("secret")), "recovery_remaining": len(state.get("recovery", [])),
            "events": [{"id": event.id, "event": event.event, "identity": event.identity,
                        "ip": event.ip_address, "user_agent": event.user_agent,
                        "at": event.created_at.replace(tzinfo=timezone.utc).isoformat()} for event in events]}


@router.post("/profile/security/{action}")
async def change_security(action: str, data: SecurityChange, request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    import time
    from karpy_platform.core.acl import mfa
    from karpy_platform.core.security.secrets import decrypt_secret, encrypt_secret
    if action not in {"setup", "enable", "disable", "recovery"}:
        raise HTTPException(404, "Not found")
    user = await current_admin_user(request, db)
    await db.execute(select(User.id).where(User.id == user.id).with_for_update())
    await db.refresh(user)
    await _security_reauthenticate(db, request, user, data.currentPassword, data.code)
    _, state = await mfa.load(db, user.id)
    result = {}
    if action == "setup":
        if state.get("secret"):
            raise HTTPException(409, "Authenticator is already enabled")
        secret, state = mfa.pending_state()
        result = mfa.provisioning(user, secret)
    elif action == "enable":
        if state.get("secret") or state.get("expires", 0) < time.time():
            raise HTTPException(422, "Start authenticator setup again")
        secret = decrypt_secret(state.get("pending"))
        step = mfa.counter(secret, data.code) if secret else None
        if step is None:
            await _admin_event(db, request, f"admin:{user.id}", "admin.security.failed", user.id)
            await db.commit()
            raise HTTPException(422, "Invalid verification code")
        codes, hashed = mfa.new_recovery_codes()
        state = {"secret": encrypt_secret(secret), "last": step, "recovery": hashed}
        result = {"recovery_codes": codes}
    elif action == "disable":
        state = {}
    else:
        if not state.get("secret"):
            raise HTTPException(409, "Enable authenticator first")
        codes, state["recovery"] = mfa.new_recovery_codes()
        result = {"recovery_codes": codes}
    await mfa.save(db, user.id, state)
    if action != "setup":
        await revoke_admin_sessions(db, user.id)
        await db.flush()
        await issue_admin_session(db, response, user)
    await _admin_event(db, request, f"admin:{user.id}", "admin.authenticator." + action, user.id)
    await db.commit()
    response.headers["Cache-Control"] = "no-store"
    return result


@router.get("/permissions")
async def list_permissions():
    return {"permissions": permission_catalog()}


@router.get("/users")
async def list_users(db: AsyncSession = Depends(get_db), actor: User = Depends(require_acl("users.index"))):
    await ensure_admin_user(db)
    result = await db.execute(select(User).options(selectinload(User.roles)).order_by(User.created_at.desc()))
    return {"users": [user_payload(user) for user in result.scalars().unique().all()]}


@router.post("/users", status_code=status.HTTP_201_CREATED)
async def create_user(data: UserCreate, db: AsyncSession = Depends(get_db), actor: User = Depends(require_acl("users.create"))):
    ensure_can_grant(actor, set(clean_permissions(data.permissions)))
    if await db.scalar(select(User).where(User.email == data.email)):
        raise HTTPException(status.HTTP_409_CONFLICT, "Email already exists")
    if await db.scalar(select(User).where(User.username == data.username)):
        raise HTTPException(status.HTTP_409_CONFLICT, "Username already exists")
    settings = await setting_store.all(db, flat=True)
    try:
        phone = validate_phone_number(data.phone, settings)
    except ValueError as exception:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, {"message": "Invalid user data.", "errors": {"phone": str(exception)}}) from exception

    user = User(
        first_name=data.firstName.capitalize(),
        last_name=data.lastName.capitalize(),
        username=data.username,
        email=data.email,
        phone=phone,
        password=hash_password(data.password),
        permissions=clean_permissions(data.permissions),
    )
    db.add(user)
    await db.flush()

    if data.roleId:
        role = await db.get(Role, data.roleId)
        if not role:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Role not found")
        ensure_can_grant(actor, _role_flags(role))
        db.add(RoleUser(user_id=user.id, role_id=role.id))

    db.add(Activation(user_id=user.id, code=secrets.token_urlsafe(32), completed=True, completed_at=utcnow()))
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            {"message": "User already exists", "errors": {"email": "The email or username has already been taken."}},
        ) from exc
    await db.refresh(user, ["roles"])
    return {"message": "User created successfully", "user": user_payload(user)}


@router.get("/users/{user_id}")
async def get_user(user_id: str, db: AsyncSession = Depends(get_db), actor: User = Depends(require_acl("users.index"))):
    user = await db.scalar(select(User).options(selectinload(User.roles)).where(User.id == user_id))
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    if user.super_user:
        await sync_super_admin_role(db, user, True)
        await db.commit()
        await db.refresh(user, ["roles"])
    return user_payload(user)


@router.patch("/users/{user_id}")
async def update_user(user_id: str, data: UserUpdate, db: AsyncSession = Depends(get_db), actor: User = Depends(require_acl("users.edit"))):
    user = await db.scalar(select(User).options(selectinload(User.roles)).where(User.id == user_id))
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    # Super users, and the super flags themselves, are managed by managing supers only.
    if user.super_user or data.superUser is not None or data.manageSupers is not None:
        ensure_can_manage_supers(actor)
    if data.permissions is not None:
        ensure_can_grant(actor, set(clean_permissions(data.permissions)))
    password_changed = bool(data.password)

    if data.email and data.email != user.email:
        if await db.scalar(select(User).where(User.email == data.email, User.id != user.id)):
            raise HTTPException(status.HTTP_409_CONFLICT, "Email already exists")
        user.email = data.email

    if data.username and data.username != user.username:
        if await db.scalar(select(User).where(User.username == data.username, User.id != user.id)):
            raise HTTPException(status.HTTP_409_CONFLICT, "Username already exists")
        user.username = data.username

    if data.firstName is not None:
        user.first_name = data.firstName.capitalize()
    if data.lastName is not None:
        user.last_name = data.lastName.capitalize()
    if data.phone is not None:
        settings = await setting_store.all(db, flat=True)
        try:
            user.phone = validate_phone_number(data.phone, settings)
        except ValueError as exception:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, {"message": "Invalid user data.", "errors": {"phone": str(exception)}}) from exception
    if data.password:
        user.password = hash_password(data.password)
    if data.permissions is not None:
        user.permissions = clean_permissions(data.permissions)
    if data.superUser is not None:
        user.super_user = data.superUser
        if data.superUser:
            user.manage_supers = True
            user.permissions = all_acl_permissions()
        else:
            user.manage_supers = False
            if data.permissions is None:
                user.permissions = {}
    if data.manageSupers is not None:
        user.manage_supers = data.manageSupers
    if data.roleIds is not None:
        roles = []
        for role_id in data.roleIds:
            role = await db.get(Role, role_id)
            if not role:
                raise HTTPException(status.HTTP_404_NOT_FOUND, f"Role not found: {role_id}")
            ensure_can_grant(actor, _role_flags(role))
            roles.append(role)
        user.roles = roles
    if data.superUser is not None:
        await sync_super_admin_role(db, user, data.superUser)

    if password_changed:
        # A password set by an admin ends that user's customer and admin sessions.
        from karpy_platform.plugins.auth.models import AuthSession

        sessions = await db.scalars(select(AuthSession).where(AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None)))
        for item in sessions:
            item.revoked_at = utcnow()
        await revoke_admin_sessions(db, user.id)

    await db.commit()
    await db.refresh(user, ["roles"])
    return {"message": "User updated successfully", "user": user_payload(user)}


@router.delete("/users/{user_id}")
async def delete_user(user_id: str, db: AsyncSession = Depends(get_db), actor: User = Depends(require_acl("users.destroy"))):
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    if user.id == actor.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "You cannot delete your own account")
    if user.super_user:
        ensure_can_manage_supers(actor)

    user_count = await db.scalar(select(func.count()).select_from(User))
    if user_count == 1:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Cannot delete the last user")

    await db.delete(user)
    await db.commit()
    return {"message": "User deleted successfully"}


@router.get("/roles")
async def list_roles(db: AsyncSession = Depends(get_db), actor: User = Depends(require_acl("roles.index"))):
    await ensure_admin_user(db)
    result = await db.execute(select(Role).options(selectinload(Role.users)).order_by(Role.name))
    return {"roles": [role_payload(role) for role in result.scalars().unique().all()]}


@router.post("/roles", status_code=status.HTTP_201_CREATED)
async def create_role(data: RoleCreate, db: AsyncSession = Depends(get_db), actor: User = Depends(require_acl("roles.create"))):
    ensure_can_grant(actor, set(clean_permissions(data.permissions)))
    if data.isDefault:
        roles = await db.execute(select(Role))
        for role in roles.scalars():
            role.is_default = False

    base_slug = slugify(data.name)
    slug = base_slug
    suffix = 2
    while await db.scalar(select(Role).where(Role.slug == slug)):
        slug = f"{base_slug}-{suffix}"
        suffix += 1

    role = Role(
        name=data.name,
        slug=slug,
        description=data.description,
        permissions=clean_permissions(data.permissions),
        is_default=data.isDefault,
    )
    db.add(role)
    await db.commit()
    await db.refresh(role, ["users"])
    return {"message": "Role created successfully", "role": role_payload(role)}


@router.get("/roles/{role_id}")
async def get_role(role_id: str, db: AsyncSession = Depends(get_db), actor: User = Depends(require_acl("roles.index"))):
    role = await db.scalar(select(Role).options(selectinload(Role.users)).where(Role.id == role_id))
    if not role:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Role not found")
    return role_payload(role)


@router.patch("/roles/{role_id}")
async def update_role(role_id: str, data: RoleUpdate, db: AsyncSession = Depends(get_db), actor: User = Depends(require_acl("roles.edit"))):
    if data.permissions is not None:
        ensure_can_grant(actor, set(clean_permissions(data.permissions)))
    role = await db.scalar(select(Role).options(selectinload(Role.users)).where(Role.id == role_id))
    if not role:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Role not found")
    if role.slug == SUPER_ADMIN_ROLE_SLUG and data.permissions is not None:
        role.permissions = all_acl_permissions()
        data.permissions = None

    if data.isDefault is True:
        roles = await db.execute(select(Role).where(Role.id != role.id))
        for other_role in roles.scalars():
            other_role.is_default = False

    if data.name is not None:
        role.name = data.name
    if data.description is not None:
        role.description = data.description
    if data.permissions is not None:
        role.permissions = clean_permissions(data.permissions)
    if data.isDefault is not None:
        role.is_default = data.isDefault

    await db.commit()
    await db.refresh(role, ["users"])
    return {"message": "Role updated successfully", "role": role_payload(role)}


@router.post("/roles/{role_id}/duplicate", status_code=status.HTTP_201_CREATED)
async def duplicate_role(role_id: str, db: AsyncSession = Depends(get_db), actor: User = Depends(require_acl("roles.create"))):
    role = await db.get(Role, role_id)
    if not role:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Role not found")

    duplicate = Role(
        name=f"{role.name} (Duplicate)",
        slug=f"{role.slug}-{secrets.token_hex(3)}",
        description=role.description,
        permissions=role.permissions,
    )
    db.add(duplicate)
    await db.commit()
    await db.refresh(duplicate, ["users"])
    return {"message": "Role duplicated successfully", "role": role_payload(duplicate)}


@router.delete("/roles/{role_id}")
async def delete_role(role_id: str, db: AsyncSession = Depends(get_db), actor: User = Depends(require_acl("roles.destroy"))):
    role = await db.get(Role, role_id)
    if not role:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Role not found")
    if role.slug == SUPER_ADMIN_ROLE_SLUG:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Cannot delete the Super Admin role")

    await db.delete(role)
    await db.commit()
    return {"message": "Role deleted successfully"}


@router.post("/users/{user_id}/assign-role")
async def assign_role(user_id: str, data: AssignRole, db: AsyncSession = Depends(get_db), actor: User = Depends(require_acl("users.edit"))):
    user = await db.scalar(select(User).options(selectinload(User.roles)).where(User.id == user_id))
    role = await db.get(Role, data.roleId)
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    if not role:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Role not found")

    if user.super_user:
        ensure_can_manage_supers(actor)
    ensure_can_grant(actor, _role_flags(role))
    user.roles = [role]
    await db.commit()
    await db.refresh(user, ["roles"])
    return {"message": "Role assigned successfully", "user": user_payload(user)}


@router.get("/notifications")
async def get_notifications(db: AsyncSession = Depends(get_db), actor: User = Depends(require_acl("dashboard.index"))):
    result = await db.execute(select(Notification).where(Notification.is_read == False))
    notifications = result.scalars().all()
    return [
        {
            "id": notification.id,
            "message": notification.message,
            "created_at": notification.created_at.isoformat(),
        }
        for notification in notifications
    ]
