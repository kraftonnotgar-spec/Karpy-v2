import unittest

from fastapi import HTTPException
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.database import Base, load_models
from karpy_platform.core.acl.models import User
from .phone_identity import PhoneIdentity, PhoneIdentityBase, canonical_phone, reserve_phone


class PhoneIdentityTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        load_models()
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        @event.listens_for(self.engine.sync_engine, "connect")
        def foreign_keys(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
            await connection.run_sync(lambda sync: PhoneIdentity.__table__.create(sync))
        async with AsyncSession(self.engine) as db:
            db.add_all([User(id="one",email="one@example.com",phone="+255684104712"),
                        User(id="two",email="two@example.com",phone="+255684104712")])
            await db.commit()

    async def asyncTearDown(self):
        await self.engine.dispose()

    def test_local_and_international_numbers_normalize_identically(self):
        for value in ["0684104712", "684104712", "+255684104712", "0684 104 712"]:
            self.assertEqual(canonical_phone(value,["TZ"],"TZ"),"+255684104712")
        with self.assertRaises(HTTPException):
            canonical_phone("+14155552671",["TZ"],"TZ")
        with self.assertRaises(HTTPException):
            canonical_phone("0684104712",["TZ"],"US")
        for value in ["684104712GSDFSFS", "0684104ABC", "letters"]:
            with self.subTest(value=value), self.assertRaises(HTTPException):
                canonical_phone(value, ["TZ"], "TZ")

    async def test_verified_number_cannot_be_reassigned_changed_or_freed_by_account_deletion(self):
        async with AsyncSession(self.engine,expire_on_commit=False) as db:
            one,two=await db.get(User,"one"),await db.get(User,"two")
            await reserve_phone(db,one,one.phone,verified=True)
            await db.commit()
            await reserve_phone(db,one,one.phone,verified=True)
            with self.assertRaises(HTTPException) as conflict:
                await reserve_phone(db,two,one.phone)
            self.assertEqual(conflict.exception.detail,"phone_already_in_use")
            with self.assertRaises(HTTPException) as conflict:
                await reserve_phone(db,one,"+255712345678")
            self.assertEqual(conflict.exception.detail,"verified_phone_cannot_change")
            await db.delete(one)
            await db.commit()
            identity=await db.get(PhoneIdentity,"+255684104712")
            await db.refresh(identity)
            self.assertIsNone(identity.user_id)
            self.assertTrue(identity.verified)
            with self.assertRaises(HTTPException):
                await reserve_phone(db,two,"+255684104712",legacy=True,verified=True)

    async def test_ambiguous_unverified_legacy_number_requires_otp_before_ownership(self):
        async with AsyncSession(self.engine,expire_on_commit=False) as db:
            db.add(PhoneIdentity(phone="+255684104712",user_id=None,verified=False))
            await db.commit()
            one,two=await db.get(User,"one"),await db.get(User,"two")
            await reserve_phone(db,one,one.phone,legacy=True)
            self.assertIsNone((await db.get(PhoneIdentity,one.phone)).user_id)
            await reserve_phone(db,one,one.phone,legacy=True,verified=True)
            await db.commit()
            with self.assertRaises(HTTPException):
                await reserve_phone(db,two,two.phone,legacy=True,verified=True)

    async def test_unverified_reservation_can_change_but_not_duplicate(self):
        async with AsyncSession(self.engine,expire_on_commit=False) as db:
            one,two=await db.get(User,"one"),await db.get(User,"two")
            await reserve_phone(db,one,one.phone)
            await db.commit()
            with self.assertRaises(HTTPException):
                await reserve_phone(db,two,two.phone)
            await reserve_phone(db,one,"+255712345678")
            await db.commit()
            self.assertIsNone(await db.get(PhoneIdentity,"+255684104712"))
