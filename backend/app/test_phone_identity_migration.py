import unittest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from app.database import Base, load_models
from app.migrations.versions.v0002_phone_identities import up, down, validate
from karpy_platform.core.acl.models import User, UserMeta


class PhoneMigrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_verified_legacy_owner_wins_and_email_case_duplicates_are_blocked(self):
        load_models()
        engine=create_async_engine("sqlite+aiosqlite:///:memory:")
        try:
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
                await connection.execute(User.__table__.insert(), [{"id":"one","email":"one@example.com","phone":"+255684104712"},{"id":"two","email":"two@example.com","phone":"+255684104712"}])
                await connection.execute(UserMeta.__table__.insert(), [{"user_id":"one","key":"auth.phone.verified_number","value":"+255684104712"},{"user_id":"one","key":"auth.phone.verified_at","value":"2026-10-19"}])
                await up(connection)
                await validate(connection)
                row=(await connection.execute(text("SELECT user_id,verified FROM auth_phone_identities"))).one()
                self.assertEqual(row.user_id,"one")
                self.assertTrue(row.verified)
                from sqlalchemy.exc import IntegrityError
                with self.assertRaises(IntegrityError):
                    await connection.execute(User.__table__.insert().values(id="three",email="ONE@example.com"))
                await down(connection)
        finally:
            await engine.dispose()
