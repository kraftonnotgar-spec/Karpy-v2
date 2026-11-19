from __future__ import annotations

from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import AsyncConnection

from app.database import Base, _sync_sqlite_acl_columns, _sync_sqlite_faq_columns

EXCLUDED_TABLES: set[str] = set()


async def up(connection: AsyncConnection) -> None:
    tables = [table for table in Base.metadata.sorted_tables if table.name not in EXCLUDED_TABLES]
    await connection.run_sync(lambda sync_connection: Base.metadata.create_all(sync_connection, tables=tables, checkfirst=True))
    await _sync_sqlite_acl_columns(connection)
    await _sync_sqlite_faq_columns(connection)


async def down(connection: AsyncConnection) -> None:
    tables = [table for table in reversed(Base.metadata.sorted_tables) if table.name not in EXCLUDED_TABLES]
    for table in tables:
        await connection.run_sync(lambda sync_connection, current=table: current.drop(sync_connection, checkfirst=True))


async def validate(connection: AsyncConnection) -> None:
    table_names = await connection.run_sync(lambda sync_connection: set(inspect(sync_connection).get_table_names()))
    required = {"users", "roles", "settings"}
    missing = sorted(required - table_names)
    if missing:
        raise RuntimeError("baseline schema is missing required tables: " + ", ".join(missing))


from app.migrations.runner import Migration

migration = Migration(1, "current_schema_baseline", "v1:current-schema-baseline:2026-08-22", up, down, validate)
