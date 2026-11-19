import unittest

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.database import Base
from .models import Setting
from .store import SettingStore, dot_forget, dot_get, dot_set, flatten


class DottedSettingsTests(unittest.TestCase):
    def test_scalar_parent_and_audit_children_survive_both_insertion_orders(self):
        for parent in ["encrypted-connection", [], None]:
            for reverse in [False, True]:
                pairs = [("example.media-storage.connections", parent), ("example.media-storage.connections.audit.1", "first"), ("example.media-storage.connections.audit.2", "second")]
                data = {}
                for key, value in reversed(pairs) if reverse else pairs:
                    dot_set(data, key, value)
                for key, value in pairs:
                    self.assertEqual(dot_get(data, key), value)
                    self.assertEqual(flatten(data)[key], value)
                dot_set(data, pairs[1][0], "changed")
                self.assertEqual(dot_get(data, pairs[1][0]), "changed")
                dot_forget(data, pairs[1][0])
                self.assertNotIn(pairs[1][0], flatten(data))
                self.assertEqual(dot_get(data, pairs[0][0]), parent)

    def test_regular_nested_settings_keep_existing_behavior(self):
        data = {}
        dot_set(data, "mail.transport.host", "smtp.example.test")
        dot_set(data, "mail.transport.port", "465")
        self.assertEqual(dot_get(data, "mail.transport"), {"host": "smtp.example.test", "port": "465"})
        dot_forget(data, "mail.transport.host")
        self.assertEqual(flatten(data), {"mail.transport.port": "465"})


class SettingsRoundTripTests(unittest.IsolatedAsyncioTestCase):
    async def test_loading_and_saving_overlap_preserves_every_database_value(self):
        engine = create_async_engine("sqlite+aiosqlite://")
        try:
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
            async with AsyncSession(engine) as db:
                values = {"example.media-storage.connections": "opaque-parent", "example.media-storage.connections.audit.1": "audit-one", "email_driver": "smtp"}
                db.add_all([Setting(key=k, value=v) for k, v in values.items()])
                await db.commit()
                store = SettingStore()
                self.assertEqual(await store.all(db, force=True), values)
                await store.set(db, "email_from_name", "Acme")
                await store.save(db)
                self.assertEqual(await store.all(db, force=True), {**values, "email_from_name": "Acme"})
        finally:
            await engine.dispose()
