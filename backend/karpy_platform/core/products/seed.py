"""Load a product's seed data through core (and optionally plugin) seed loaders.

Each seed file is a JSON object; its top-level keys pick the loader (so file names are
free). The neutral core ships two loaders, both backed by core tables:

==================  ================================================  ==============
key                 loader                                            needs table
==================  ================================================  ==============
``settings``        insert missing rows into the setting store        ``settings``
``staff_roles``     insert missing ACL roles by slug                  ``roles``
==================  ================================================  ==============

Every loader inserts what is missing by a stable key and never overwrites an existing
row, so running the seed again is safe and keeps admins' later edits. A plugin (or a
product) adds its own loader with :func:`register_seed_loader`; a loader whose table is
absent is skipped and reported. Keys ``seed_version`` and ``source`` are metadata.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from sqlalchemy import inspect as sa_inspect, select
from sqlalchemy.ext.asyncio import AsyncSession

from .manifest import Product, ProductSeedError, read_json

META_KEYS = frozenset({"seed_version", "source", "demo"})
PRODUCT_KEY_SETTING = "product.key"
PRODUCT_SEED_VERSION_SETTING = "product.seed_version"


@dataclass
class SeedReport:
    """What a seed or demo run did: ``inserted[name] = count``, ``skipped[name] = reason``."""

    inserted: dict[str, int] = field(default_factory=dict)
    skipped: dict[str, str] = field(default_factory=dict)

    def add(self, name: str, count: int) -> None:
        self.inserted[name] = self.inserted.get(name, 0) + int(count)

    def skip(self, name: str, reason: str) -> None:
        self.skipped[name] = reason

    def total(self) -> int:
        return sum(self.inserted.values())

    def lines(self) -> list[str]:
        rows = [f"  {name:<28} +{count}" for name, count in self.inserted.items()]
        rows += [f"  {name:<28} skipped ({reason})" for name, reason in self.skipped.items()]
        return rows


async def missing_tables(session: AsyncSession, *names: str) -> list[str]:
    def check(sync_session) -> list[str]:
        inspector = sa_inspect(sync_session.connection())
        return [name for name in names if not inspector.has_table(name)]

    return await session.run_sync(check)


async def insert_missing_settings(session: AsyncSession, values: dict[str, Any]) -> int:
    from karpy_platform.core.setting.models import Setting
    from karpy_platform.core.setting.store import encode_setting_value

    added = 0
    for key, value in values.items():
        if await session.scalar(select(Setting.key).where(Setting.key == key)) is None:
            session.add(Setting(key=key, value=encode_setting_value(value)))
            added += 1
    await session.flush()
    return added


# ── built-in core loaders ────────────────────────────────────────────

async def _settings(session: AsyncSession, data: dict[str, Any], report: SeedReport) -> None:
    report.add("settings", await insert_missing_settings(session, dict(data["settings"])))


async def _staff_roles(session: AsyncSession, data: dict[str, Any], report: SeedReport) -> None:
    from karpy_platform.core.acl.models import Role

    existing = set((await session.execute(select(Role.slug))).scalars())
    added = 0
    for item in data["staff_roles"]:
        if item["slug"] in existing:
            continue
        session.add(
            Role(
                slug=item["slug"],
                name=item["name"],
                description=item.get("description"),
                permissions={flag: True for flag in item.get("permissions", [])},
                is_default=bool(item.get("is_default", False)),
            )
        )
        existing.add(item["slug"])
        added += 1
    await session.flush()
    report.add("staff_roles", added)


Loader = Callable[[AsyncSession, dict[str, Any], SeedReport], Awaitable[None]]


@dataclass(frozen=True)
class SeedLoader:
    key: str
    name: str
    loader: Loader
    tables: tuple[str, ...]


# key → loader. Order of application follows registration order (core first).
_LOADERS: dict[str, SeedLoader] = {}


def register_seed_loader(key: str, name: str, loader: Loader, tables: tuple[str, ...]) -> None:
    """Add a seed loader for a top-level key (used by plugins/products to extend seeding)."""
    if not key:
        raise ValueError("seed loader key is required")
    _LOADERS[key] = SeedLoader(key=key, name=name, loader=loader, tables=tuple(tables))


def seed_loaders() -> tuple[SeedLoader, ...]:
    return tuple(_LOADERS.values())


# Core loaders, registered on import.
register_seed_loader("settings", "settings", _settings, ("settings",))
register_seed_loader("staff_roles", "staff_roles", _staff_roles, ("roles",))


def known_seed_keys() -> frozenset[str]:
    return frozenset(_LOADERS) | META_KEYS


async def load_seed_data(session: AsyncSession, data: dict[str, Any], report: SeedReport, *, source: str = "seed") -> None:
    unknown = sorted(set(data) - known_seed_keys())
    if unknown:
        raise ProductSeedError(
            f"{source}: unknown seed keys {unknown}. Register a loader with "
            "register_seed_loader() or remove the key."
        )
    for entry in seed_loaders():
        if entry.key not in data:
            continue
        absent = await missing_tables(session, *entry.tables)
        if absent:
            report.skip(entry.name, f"table {absent[0]} missing")
            continue
        try:
            await entry.loader(session, data, report)
        except ImportError as exc:
            report.skip(entry.name, f"plugin not installed ({exc.name})")


async def seed_product(session: AsyncSession, product: Product) -> SeedReport:
    """Load every seed file named in ``product.json`` (idempotent; the caller commits)."""
    report = SeedReport()
    manifest = product.manifest
    if not await missing_tables(session, "settings"):
        report.add(
            "settings",
            await insert_missing_settings(
                session,
                {PRODUCT_KEY_SETTING: manifest.key, PRODUCT_SEED_VERSION_SETTING: manifest.seed_version},
            ),
        )
    for path in product.seed_files():
        await load_seed_data(session, read_json(path), report, source=str(path))
    return report
