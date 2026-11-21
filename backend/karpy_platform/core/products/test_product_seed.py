"""Neutral tests for the core product-layer loader against the ``_example`` product."""

from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from karpy_platform.core import products
from karpy_platform.core.acl.models import Role, User
from karpy_platform.core.products.testing import ProductSeedTestCase, app_env
from karpy_platform.core.setting.models import Setting

EXAMPLE = "_example"


class ExampleProductSeedTests(ProductSeedTestCase):
    async def seed(self) -> products.SeedReport:
        return await products.run_product_seed(self.Session, products.load_product(EXAMPLE))

    async def test_example_product_seeds_settings_and_roles(self) -> None:
        report = await self.seed()
        self.assertEqual(await self.count(Role), 1)
        self.assertGreaterEqual(report.inserted["settings"], 1)
        self.assertEqual(report.inserted["staff_roles"], 1)
        async with self.Session() as session:
            self.assertEqual(await session.scalar(select(Setting.value).where(Setting.key == "locale.currency")), "USD")
            self.assertEqual(await session.scalar(select(Setting.value).where(Setting.key == "product.key")), EXAMPLE)
            role = await session.scalar(select(Role).where(Role.slug == "support"))
            self.assertEqual(role.permissions, {"dashboard.index": True})

    async def test_seeding_twice_is_idempotent_and_keeps_admin_edits(self) -> None:
        await self.seed()
        async with self.Session() as session:
            role = await session.scalar(select(Role).where(Role.slug == "support"))
            role.name = "Edited by admin"
            setting = await session.get(Setting, "locale.currency")
            setting.value = "EUR"
            await session.commit()
        again = await self.seed()
        self.assertEqual(again.total(), 0)
        self.assertEqual(await self.count(Role), 1)
        async with self.Session() as session:
            self.assertEqual((await session.scalar(select(Role).where(Role.slug == "support"))).name, "Edited by admin")
            self.assertEqual((await session.get(Setting, "locale.currency")).value, "EUR")

    async def test_demo_refused_in_production(self) -> None:
        product = products.load_product(EXAMPLE)
        with app_env("production"):
            with self.assertRaises(products.ProductSeedError):
                await products.run_demo_seed(self.Session, product)
        self.assertEqual(await self.count(User), 0)
        self.assertEqual(await self.count(Setting), 0)

    async def test_demo_seed_is_idempotent_clearable_and_keeps_real_accounts(self) -> None:
        product = products.load_product(EXAMPLE)
        async with self.Session() as session:  # a real account that demo:clear must keep
            session.add(User(email="real@example.org", username="real@example.org", first_name="Real", last_name="Person", password="x"))
            await session.commit()

        _, report = await products.run_demo_seed(self.Session, product)
        self.assertEqual(report.inserted["demo users"], 2)
        _, again = await products.run_demo_seed(self.Session, product)
        self.assertEqual(again.total(), 0)
        async with self.Session() as session:
            demo_users = (await session.execute(select(User).where(User.email.like("%@demo.example")))).scalars().all()
            self.assertEqual(len(demo_users), 2)
            self.assertTrue(all(user.email_verified_at is not None for user in demo_users))
            self.assertTrue(all(user.password for user in demo_users))

        cleared = await products.run_demo_clear(self.Session, product)
        self.assertEqual(cleared.inserted["demo users"], 2)
        self.assertEqual(await self.count(User, User.email.like("%@demo.example")), 0)
        self.assertEqual(await self.count(User, User.email == "real@example.org"), 1)
        # Seed settings stay after a demo clear.
        self.assertEqual(await self.count(Setting, Setting.key == "locale.currency"), 1)

    async def test_demo_password_from_setting_is_usable(self) -> None:
        from karpy_platform.core.acl.routes import verify_password

        await products.run_demo_seed(self.Session, products.load_product(EXAMPLE), password="demo-pass-123")
        async with self.Session() as session:
            user = await session.scalar(select(User).where(User.email == "owner@demo.example"))
        self.assertTrue(verify_password("demo-pass-123", user.password))


class ProductFolderTests(ProductSeedTestCase):
    def make_product(self, root: Path, manifest: dict, files: dict[str, dict]) -> None:
        folder = root / "acme2"
        (folder / "seed").mkdir(parents=True)
        (folder / "demo").mkdir()
        (folder / "product.json").write_text(json.dumps(manifest), encoding="utf-8")
        for name, data in files.items():
            (folder / name).write_text(json.dumps(data), encoding="utf-8")

    def manifest(self, **extra) -> dict:
        return {
            "key": "acme2", "name": "Acme Two", "seed_version": 1, "default_locale": "en",
            "locales": ["en"], "currency": "USD", "timezone": "UTC", **extra,
        }

    async def test_product_must_be_set(self) -> None:
        with mock.patch.object(settings, "PRODUCT", None), mock.patch.dict("os.environ", {}, clear=False) as env:
            env.pop("PRODUCT", None)
            with self.assertRaises(products.ProductSeedError) as caught:
                products.load_product()
        self.assertIn("PRODUCT is not set", str(caught.exception))
        with self.assertRaises(products.ProductSeedError):
            products.load_product("../etc")
        with self.assertRaises(products.ProductSeedError):
            products.load_product("no_such_product")

    async def test_demo_rows_must_use_demo_domain_and_phone_range(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            demo = {"email_domain": "demo.example", "phone_range": "+15550100000-+15550199999", "files": ["people.json"]}
            self.make_product(root, self.manifest(demo=demo), {"demo/people.json": {"users": [
                {"key": "x", "first_name": "A", "last_name": "B", "email": "someone@real-company.org"}]}})
            with mock.patch.object(settings, "PRODUCTS_DIR", root):
                with self.assertRaises(products.ProductSeedError):
                    await products.run_demo_seed(self.Session, products.load_product("acme2"))
                (root / "acme2/demo/people.json").write_text(json.dumps({"users": [
                    {"key": "x", "first_name": "A", "last_name": "B", "email": "a@demo.example", "phone": "+447700900123"}]}), encoding="utf-8")
                with self.assertRaises(products.ProductSeedError):
                    await products.run_demo_seed(self.Session, products.load_product("acme2"))

    async def test_unknown_seed_keys_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_product(root, self.manifest(seed=["x.json"]), {"seed/x.json": {"colours": ["red"]}})
            with mock.patch.object(settings, "PRODUCTS_DIR", root):
                with self.assertRaises(products.ProductSeedError):
                    await products.run_product_seed(self.Session, products.load_product("acme2"))


class ProductConsoleTests(unittest.IsolatedAsyncioTestCase):
    """The product:seed console command end-to-end against a temp-file database."""

    async def asyncSetUp(self) -> None:
        from app.database import Base, load_models

        load_models()
        self.tempdir = tempfile.TemporaryDirectory()
        database = Path(self.tempdir.name) / "karpy.sqlite"
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{database.as_posix()}")
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        self.Session = async_sessionmaker(self.engine, class_=AsyncSession, expire_on_commit=False)

    async def asyncTearDown(self) -> None:
        await self.engine.dispose()
        self.tempdir.cleanup()

    async def test_console_product_seed(self) -> None:
        from karpy_platform.core.console import commands

        with mock.patch("builtins.print") as printed:
            code = await asyncio.to_thread(
                commands.run_product_command, "product:seed", EXAMPLE, session_factory=self.Session
            )
        self.assertEqual(code, 0)
        self.assertIn("Seed data for '_example'", " ".join(str(call.args[0]) for call in printed.call_args_list if call.args))
        async with self.Session() as session:
            self.assertEqual(await session.scalar(select(Role.slug).where(Role.slug == "support")), "support")

    async def test_console_demo_seed_refused_in_production(self) -> None:
        from karpy_platform.core.console import commands

        with app_env("production"), mock.patch("sys.stderr"):
            code = await asyncio.to_thread(
                commands.run_product_command, "demo:seed", EXAMPLE, session_factory=self.Session
            )
        self.assertEqual(code, 1)
        async with self.Session() as session:
            self.assertEqual(await session.scalar(select(User.id).where(User.email.like("%@demo.example"))), None)


if __name__ == "__main__":
    unittest.main()
