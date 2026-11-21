"""Test-only helpers for product seed/demo tests (never imported by runtime code)."""

from __future__ import annotations

import unittest
from contextlib import contextmanager
from typing import Iterator
from unittest import mock

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


@contextmanager
def app_env(value: str) -> Iterator[None]:
    from app.config import settings

    with mock.patch.object(settings, "APP_ENV", value):
        yield


class ProductSeedTestCase(unittest.IsolatedAsyncioTestCase):
    """In-memory SQLite with the core tables, for neutral product seed/demo tests."""

    async def asyncSetUp(self) -> None:
        from app.database import Base, load_models

        load_models()
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        self.Session = async_sessionmaker(self.engine, class_=AsyncSession, expire_on_commit=False)

    async def asyncTearDown(self) -> None:
        await self.engine.dispose()

    async def count(self, model, *where) -> int:
        async with self.Session() as session:
            return int(await session.scalar(select(func.count()).select_from(model).where(*where)) or 0)
