"""One canonical phone reservation per account; preserve verified legacy owners."""
import hashlib
from collections import defaultdict
from pathlib import Path

import phonenumbers
from sqlalchemy import Boolean, Column, ForeignKey, Index, MetaData, String, Table, func, inspect, select, text
from sqlalchemy.schema import CreateIndex, DropIndex

from app.migrations.runner import Migration

metadata = MetaData()
users = Table("users", metadata, Column("id", String(36), primary_key=True), Column("phone", String(30)), Column("email", String(120)))
email_index = Index("uq_users_email_lower", func.lower(users.c.email), unique=True)
meta = Table("user_meta", metadata, Column("user_id", String(36)), Column("key", String(120)), Column("value", String))
identities = Table("auth_phone_identities", metadata,
    Column("phone", String(16), primary_key=True),
    Column("user_id", String(36), ForeignKey("users.id", ondelete="SET NULL"), unique=True, nullable=True),
    Column("verified", Boolean, nullable=False, default=False))


async def up(connection):
    duplicates = await connection.scalar(select(func.count()).select_from(
        select(func.lower(users.c.email)).group_by(func.lower(users.c.email)).having(func.count() > 1).subquery()))
    if duplicates:
        raise RuntimeError("Case-insensitive duplicate emails require review")
    await connection.execute(CreateIndex(email_index, if_not_exists=True))
    await connection.run_sync(lambda sync: identities.create(sync, checkfirst=True))
    values = defaultdict(dict)
    for user_id, key, value in (await connection.execute(select(meta.c.user_id, meta.c.key, meta.c.value).where(
            meta.c.key.in_(["auth.phone.verified_number", "auth.phone.verified_at"])))):
        if key in values[user_id]:
            raise RuntimeError("Duplicate legacy phone verification metadata")
        values[user_id][key] = value
    groups = defaultdict(list)
    for user_id, phone in (await connection.execute(select(users.c.id, users.c.phone).where(users.c.phone.is_not(None)))):
        try:
            parsed = phonenumbers.parse(phone, None)
            if not phonenumbers.is_valid_number(parsed):
                continue
            normalized = phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
        except phonenumbers.NumberParseException:
            continue
        verified = values[user_id].get("auth.phone.verified_number") == phone and bool(values[user_id].get("auth.phone.verified_at"))
        groups[normalized].append((user_id, verified))
    for phone, owners in groups.items():
        verified = [user_id for user_id, proven in owners if proven]
        if len(verified) > 1:
            raise RuntimeError("Conflicting verified phone owners require review")
        owner = verified[0] if verified else owners[0][0] if len(owners) == 1 else None
        existing = await connection.scalar(select(identities.c.phone).where(identities.c.phone == phone))
        if existing is None:
            await connection.execute(identities.insert().values(phone=phone, user_id=owner, verified=bool(verified)))


async def down(connection):
    await connection.run_sync(lambda sync: identities.drop(sync, checkfirst=True))
    await connection.execute(DropIndex(email_index, if_exists=True))


async def validate(connection):
    if connection.dialect.name == "sqlite":
        definition = await connection.scalar(text("SELECT sql FROM sqlite_master WHERE type='index' AND name='uq_users_email_lower'"))
    else:
        definition = await connection.scalar(text("SELECT indexdef FROM pg_indexes WHERE schemaname=current_schema() AND tablename='users' AND indexname='uq_users_email_lower'"))
    if not definition or "unique" not in definition.lower() or "lower" not in definition.lower() or "email" not in definition.lower():
        raise RuntimeError("Email uniqueness index drift")
    def check(sync):
        inspector = inspect(sync)
        if not inspector.has_table(identities.name):
            raise RuntimeError("Phone identity schema missing")
        columns = {item["name"]: item for item in inspector.get_columns(identities.name)}
        if set(columns) != {"phone", "user_id", "verified"} or columns["phone"]["nullable"] or not columns["user_id"]["nullable"] or columns["verified"]["nullable"]:
            raise RuntimeError("Phone identity column drift")
        if inspector.get_pk_constraint(identities.name)["constrained_columns"] != ["phone"]:
            raise RuntimeError("Phone uniqueness drift")
        if not any(item["column_names"] == ["user_id"] for item in inspector.get_unique_constraints(identities.name)):
            raise RuntimeError("Phone account uniqueness drift")
        if not any(item["referred_table"] == "users" and item["constrained_columns"] == ["user_id"]
                   and item.get("options", {}).get("ondelete", "").upper() == "SET NULL"
                   for item in inspector.get_foreign_keys(identities.name)):
            raise RuntimeError("Phone identity foreign key drift")
    await connection.run_sync(check)


migration = Migration(2, "unique_phone_identities", "v2:" + hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), up, down, validate)
