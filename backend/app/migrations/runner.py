from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Awaitable, Callable

from sqlalchemy import DateTime, Integer, MetaData, String, Table, Column, delete, insert, select
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

class MigrationDriftError(RuntimeError):
    pass


metadata = MetaData()
migration_table = Table(
    "karpy_schema_migrations",
    metadata,
    Column("version", Integer, primary_key=True),
    Column("name", String(160), nullable=False),
    Column("checksum", String(64), nullable=False),
    Column("applied_at", DateTime, nullable=False, default=datetime.utcnow),
)


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    identity: str
    up: Callable[[AsyncConnection], Awaitable[None]]
    down: Callable[[AsyncConnection], Awaitable[None]]
    validate: Callable[[AsyncConnection], Awaitable[None]]

    @property
    def checksum(self) -> str:
        return hashlib.sha256(self.identity.encode()).hexdigest()


from .versions import MIGRATIONS

CURRENT_VERSION = len(MIGRATIONS)


def _validate_registry() -> None:
    for index, migration in enumerate(MIGRATIONS, start=1):
        if migration.version != index:
            raise MigrationDriftError(f"migration registry has a gap before version {migration.version}")


async def _ensure_table(connection: AsyncConnection) -> None:
    await connection.run_sync(lambda sync_connection: metadata.create_all(sync_connection, tables=[migration_table], checkfirst=True))


async def _records(connection: AsyncConnection) -> dict[int, tuple[str, str]]:
    rows = (await connection.execute(select(migration_table.c.version, migration_table.c.name, migration_table.c.checksum).order_by(migration_table.c.version))).all()
    return {int(row.version): (str(row.name), str(row.checksum)) for row in rows}


async def current_version(engine: AsyncEngine) -> int:
    async with engine.begin() as connection:
        await _ensure_table(connection)
        records = await _records(connection)
    return max(records, default=0)


async def validate_migrations(engine: AsyncEngine) -> None:
    _validate_registry()
    async with engine.begin() as connection:
        await _ensure_table(connection)
        records = await _records(connection)
        if sorted(records) != list(range(1, CURRENT_VERSION + 1)):
            raise MigrationDriftError(f"expected migration sequence 1..{CURRENT_VERSION}")
        for migration in MIGRATIONS:
            name, checksum = records[migration.version]
            if name != migration.name or checksum != migration.checksum:
                raise MigrationDriftError(f"migration {migration.version} identity drift")
            await migration.validate(connection)


async def migrate_up(engine: AsyncEngine, target: int = CURRENT_VERSION) -> None:
    _validate_registry()
    if target < 0 or target > CURRENT_VERSION:
        raise ValueError(f"target must be from 0 through {CURRENT_VERSION}")
    async with engine.begin() as connection:
        await _ensure_table(connection)
        records = await _records(connection)
    for migration in MIGRATIONS:
        if migration.version > target:
            break
        async with engine.begin() as connection:
            records = await _records(connection)
            if migration.version in records:
                name, checksum = records[migration.version]
                if name != migration.name or checksum != migration.checksum:
                    raise MigrationDriftError(f"migration {migration.version} identity drift")
                await migration.validate(connection)
                continue
            await migration.up(connection)
            await migration.validate(connection)
            await connection.execute(insert(migration_table).values(version=migration.version, name=migration.name, checksum=migration.checksum, applied_at=utcnow()))


async def migrate_down(engine: AsyncEngine, target: int) -> None:
    _validate_registry()
    if target < 0 or target > CURRENT_VERSION:
        raise ValueError(f"target must be from 0 through {CURRENT_VERSION}")
    for migration in reversed(MIGRATIONS):
        if migration.version <= target:
            continue
        async with engine.begin() as connection:
            records = await _records(connection)
            if migration.version not in records:
                continue
            name, checksum = records[migration.version]
            if name != migration.name or checksum != migration.checksum:
                raise MigrationDriftError(f"migration {migration.version} identity drift")
            await migration.down(connection)
            await connection.execute(delete(migration_table).where(migration_table.c.version == migration.version))
