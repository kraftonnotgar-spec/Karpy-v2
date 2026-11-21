"""Demo data: opt-in sample rows for staging. Neutral core framework only.

Demo is not seed. Demo data is loaded with ``demo:seed``, refused when ``APP_ENV`` is
production, and recognisable: people use the product's demo e-mail domain and phone
range, and get an unusable random password unless ``DEMO_PASSWORD`` is set. ``clear_demo``
removes exactly those rows (and anything a registered clearer removes).

Demo files (``products/<p>/demo/*.json``) are JSON objects whose top-level keys pick a
loader. The neutral core ships one loader, ``users`` (core ACL accounts). Products and
plugins add their own content loaders/clearers with :func:`register_demo_loader`; the
loader logic here is generic and carries no product-specific content.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from .manifest import Product, ProductSeedError, read_json
from .seed import META_KEYS, SeedReport, missing_tables

RANDOM_PASSWORD_BYTES = 32


def ensure_demo_allowed() -> None:
    from app.config import settings

    if settings.is_production:
        raise ProductSeedError("Demo data is refused when APP_ENV is production.")


DemoLoaderFn = Callable[["DemoContext", dict[str, Any], SeedReport], Awaitable[None]]
DemoClearerFn = Callable[[AsyncSession, str, SeedReport], Awaitable[None]]


@dataclass(frozen=True)
class DemoExtension:
    key: str
    loader: DemoLoaderFn
    clearer: DemoClearerFn | None
    tables: tuple[str, ...]


_DEMO_EXTENSIONS: dict[str, DemoExtension] = {}


def register_demo_loader(
    key: str,
    loader: DemoLoaderFn,
    *,
    clearer: DemoClearerFn | None = None,
    tables: tuple[str, ...] = (),
) -> None:
    """Add a demo content loader (and optional clearer) for a top-level demo key."""
    if not key:
        raise ValueError("demo loader key is required")
    _DEMO_EXTENSIONS[key] = DemoExtension(key=key, loader=loader, clearer=clearer, tables=tuple(tables))


def known_demo_keys() -> frozenset[str]:
    return frozenset({"users"}) | frozenset(_DEMO_EXTENSIONS) | META_KEYS


class DemoContext:
    """Shared state and guards handed to every demo loader (built-in and registered)."""

    def __init__(self, session: AsyncSession, product: Product, report: SeedReport, *, password: str | None) -> None:
        if product.manifest.demo is None:
            raise ProductSeedError(f"Product {product.name!r} has no demo section in product.json.")
        self.session = session
        self.product = product
        self.report = report
        self.password = password
        self.domain = product.manifest.demo.email_domain.lower()
        self.phone_bounds = product.manifest.demo.phone_bounds()
        self.currency = product.manifest.currency
        self.users: dict[str, Any] = {}

    def check_email(self, email: str) -> str:
        email = str(email or "").strip().lower()
        if not email.endswith("@" + self.domain):
            raise ProductSeedError(f"Demo e-mail {email!r} must use the demo domain @{self.domain}.")
        return email

    def check_phone(self, phone: str | None) -> str | None:
        if not phone:
            return None
        digits = "".join(ch for ch in phone if ch.isdigit())
        if self.phone_bounds is not None:
            low, high = self.phone_bounds
            if not phone.startswith("+") or not low <= int(digits) <= high:
                raise ProductSeedError(
                    f"Demo phone {phone!r} is outside the demo range {self.product.manifest.demo.phone_range}."
                )
        return phone

    def _password(self) -> str:
        from karpy_platform.core.acl.routes import hash_password

        return hash_password(self.password or secrets.token_urlsafe(RANDOM_PASSWORD_BYTES))

    async def user(self, key: str):
        if key not in self.users:
            raise ProductSeedError(f"Unknown demo user {key!r} (add it to users).")
        return self.users[key]


async def _load_users(context: DemoContext, data: dict[str, Any], report: SeedReport) -> None:
    """Built-in demo loader: create core ACL accounts, idempotent by e-mail."""
    from karpy_platform.core.acl.models import User, utcnow

    added = 0
    for item in data["users"]:
        email = context.check_email(item["email"])
        phone = context.check_phone(item.get("phone"))
        existing = await context.session.scalar(select(User).where(User.email == email))
        if existing is not None:
            context.users[item["key"]] = existing
            continue
        user = User(
            first_name=item.get("first_name") or "Sample",
            last_name=item.get("last_name") or "User",
            username=email,
            email=email,
            phone=phone,
            password=context._password(),
            email_verified_at=utcnow() if item.get("verified") else None,
        )
        context.session.add(user)
        await context.session.flush()
        context.users[item["key"]] = user
        added += 1
    report.add("demo users", added)


async def seed_demo(session: AsyncSession, product: Product, *, password: str | None = None) -> SeedReport:
    """Load the product's demo files (idempotent; the caller commits)."""
    report = SeedReport()
    context = DemoContext(session, product, report, password=password)
    for path in product.demo_files():
        data = read_json(path)
        unknown = sorted(set(data) - known_demo_keys())
        if unknown:
            raise ProductSeedError(f"{path}: unknown demo keys {unknown}.")
        if "users" in data:
            absent = await missing_tables(session, "users")
            if absent:
                report.skip("demo users", f"table {absent[0]} missing")
            else:
                await _load_users(context, data, report)
        for key, extension in _DEMO_EXTENSIONS.items():
            if key not in data:
                continue
            absent = await missing_tables(session, *extension.tables)
            if absent:
                report.skip(key, f"table {absent[0]} missing")
                continue
            try:
                await extension.loader(context, data, report)
            except ImportError as exc:
                report.skip(key, f"plugin not installed ({exc.name})")
    return report


async def clear_demo(session: AsyncSession, product: Product) -> SeedReport:
    """Remove demo rows: registered content first, then demo accounts and their core rows."""
    if product.manifest.demo is None:
        raise ProductSeedError(f"Product {product.name!r} has no demo section in product.json.")
    report = SeedReport()
    domain = product.manifest.demo.email_domain.lower()

    # Product/plugin content that references demo accounts is removed before the accounts.
    for key, extension in _DEMO_EXTENSIONS.items():
        if extension.clearer is None:
            continue
        if await missing_tables(session, *extension.tables):
            continue
        try:
            await extension.clearer(session, domain, report)
        except ImportError:
            continue

    if await missing_tables(session, "users"):
        return report

    from karpy_platform.core.acl.models import Activation, RoleUser, User, UserMeta

    like = f"%@{domain}"
    user_ids = list((await session.execute(select(User.id).where(User.email.like(like)))).scalars())
    if not user_ids:
        return report
    for model in (UserMeta, RoleUser, Activation):
        if not await missing_tables(session, model.__tablename__):
            await session.execute(delete(model).where(model.user_id.in_(user_ids)))
    await session.execute(delete(User).where(User.id.in_(user_ids)))
    report.add("demo users", len(user_ids))
    return report
