from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine

from app.database import Base, load_models
from app.migrations import MigrationDriftError, current_version, migrate_down, migrate_up, validate_migrations
from app.migrations.runner import CURRENT_VERSION


class NumberedMigrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        load_models()
        self.tempdir = tempfile.TemporaryDirectory()
        self.database = Path(self.tempdir.name) / "karpy.sqlite"
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{self.database.as_posix()}")

    async def asyncTearDown(self) -> None:
        await self.engine.dispose()
        self.tempdir.cleanup()

    async def table_names(self) -> set[str]:
        async with self.engine.connect() as connection:
            return await connection.run_sync(lambda sync_connection: set(inspect(sync_connection).get_table_names()))

    async def test_fresh_migration_rollback_and_reapply(self) -> None:
        await migrate_up(self.engine)
        await validate_migrations(self.engine)
        self.assertEqual(await current_version(self.engine), CURRENT_VERSION)
        self.assertTrue({"auth_phone_identities"}.issubset(await self.table_names()))

        await migrate_down(self.engine, 1)
        self.assertEqual(await current_version(self.engine), 1)
        self.assertFalse({"auth_phone_identities"} & await self.table_names())
        await migrate_up(self.engine)
        await validate_migrations(self.engine)

    async def test_upgrade_adopts_current_deployed_schema(self) -> None:
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        await migrate_up(self.engine)
        await validate_migrations(self.engine)
        self.assertEqual(await current_version(self.engine), CURRENT_VERSION)

    async def test_recorded_version_schema_drift_is_rejected(self) -> None:
        await migrate_up(self.engine)
        async with self.engine.begin() as connection:
            await connection.execute(text("DROP TABLE auth_phone_identities"))
        with self.assertRaises((MigrationDriftError, RuntimeError)):
            await validate_migrations(self.engine)

    async def test_checksum_drift_is_rejected(self) -> None:
        await migrate_up(self.engine)
        async with self.engine.begin() as connection:
            await connection.execute(text("UPDATE karpy_schema_migrations SET checksum='changed' WHERE version=2"))
        with self.assertRaises(MigrationDriftError):
            await validate_migrations(self.engine)


if __name__ == "__main__":
    unittest.main()
