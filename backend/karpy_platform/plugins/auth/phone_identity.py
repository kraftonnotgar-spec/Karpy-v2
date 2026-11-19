"""Canonical phone reservations shared by signup and phone ownership checks."""
import phonenumbers
import re
from fastapi import HTTPException
from sqlalchemy import Boolean, Column, ForeignKey, String, Table, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class PhoneIdentityBase(DeclarativeBase):
    pass


Table("users", PhoneIdentityBase.metadata, Column("id", String(36), primary_key=True))


class PhoneIdentity(PhoneIdentityBase):
    __tablename__ = "auth_phone_identities"
    phone: Mapped[str] = mapped_column(String(16), primary_key=True)
    user_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id", ondelete="SET NULL"), unique=True)
    verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


def canonical_phone(value, countries, country=None):
    if not re.fullmatch(r"[+0-9()\-\s]{6,30}", value):
        raise HTTPException(422, "phone_country_not_allowed")
    # An empty list accepts every country (AUTH_PHONE_COUNTRIES / auth.phone_countries).
    if country and countries and country not in countries:
        raise HTTPException(422, "phone_country_not_allowed")
    try:
        parsed = phonenumbers.parse(value, country or (countries[0] if len(countries) == 1 else None))
        region = phonenumbers.region_code_for_number(parsed)
        if not phonenumbers.is_valid_number(parsed) or (countries and region not in countries) or country and region != country:
            raise ValueError()
        return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
    except (ValueError, phonenumbers.NumberParseException):
        raise HTTPException(422, "phone_country_not_allowed") from None


async def reserve_phone(db, user, phone, *, legacy=False, verified=False):
    target = await db.scalar(select(PhoneIdentity).where(PhoneIdentity.phone == phone).with_for_update())
    same_legacy_number = False
    if target and target.user_id is None and not target.verified and legacy:
        try:
            same_legacy_number = phonenumbers.format_number(phonenumbers.parse(user.phone or "", None), phonenumbers.PhoneNumberFormat.E164) == phone
        except phonenumbers.NumberParseException:
            pass
    if target and target.user_id != user.id and not same_legacy_number:
        raise HTTPException(409, "phone_already_in_use")
    old = await db.scalar(select(PhoneIdentity).where(PhoneIdentity.user_id == user.id))
    if old and old.verified and old.phone != phone:
        raise HTTPException(409, "verified_phone_cannot_change")
    try:
        if old and old.phone != phone:
            await db.delete(old)
            await db.flush()
        if target:
            if target.user_id is not None or verified:
                target.user_id = user.id
            target.verified = target.verified or verified
        else:
            db.add(PhoneIdentity(phone=phone, user_id=user.id, verified=verified))
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(409, "phone_already_in_use") from None
