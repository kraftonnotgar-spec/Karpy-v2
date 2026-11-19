"""Migration acceptance only for a fresh, explicitly isolated loopback database."""
from __future__ import annotations

import asyncio
import os

from sqlalchemy import inspect
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from app.database import load_models
from app.migrations import current_version, migrate_down, migrate_up, validate_migrations
from app.migrations.runner import CURRENT_VERSION


async def main():
    url = make_url(os.environ["TEST_KARPY_DATABASE_URL"])
    if url.host != "127.0.0.1" or not (url.database or "").startswith("karpy_release_identity_") or url.drivername != "postgresql+asyncpg":
        raise ValueError("Requires a fresh karpy_release_identity_* loopback PostgreSQL database")
    load_models()
    engine = create_async_engine(url)
    try:
        async with engine.connect() as connection:
            tables = await connection.run_sync(lambda sync: inspect(sync).get_table_names())
        if tables:
            raise ValueError("Refusing acceptance in a nonempty database")
        await migrate_up(engine)
        await validate_migrations(engine)
        assert await current_version(engine) == CURRENT_VERSION
        print(f"PASS: fresh PostgreSQL identity migrations 0->{CURRENT_VERSION}")
        await migrate_down(engine, CURRENT_VERSION - 1)
        await migrate_up(engine)
        await validate_migrations(engine)
        print(f"PASS: PostgreSQL latest migration rollback/reapply {CURRENT_VERSION}->{CURRENT_VERSION - 1}->{CURRENT_VERSION}")
        await migrate_down(engine, 1)
        await migrate_up(engine)
        await validate_migrations(engine)
        assert await current_version(engine) == CURRENT_VERSION
        print(f"PASS: PostgreSQL integration migrations rollback/reapply {CURRENT_VERSION}->1->{CURRENT_VERSION}")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
