"""Add the payment_notifications table for the in-app admin notification channel."""
import hashlib
from pathlib import Path

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Index,
    JSON,
    MetaData,
    Numeric,
    String,
    Table,
    Text,
    inspect,
)

from app.migrations.runner import Migration

metadata = MetaData()

payment_notifications = Table(
    "payment_notifications",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("created_at", DateTime, nullable=False),
    Column("updated_at", DateTime, nullable=False),
    Column("is_deleted", Boolean, nullable=False, default=False),
    Column("event", String(60), nullable=False),
    Column("title", String(255), nullable=False),
    Column("body", Text, nullable=True),
    Column("payment_id", String(36), nullable=True),
    Column("reference", String(120), nullable=True),
    Column("amount", Numeric(14, 2), nullable=True),
    Column("currency", String(12), nullable=True),
    Column("status", String(40), nullable=True),
    Column("customer_label", String(190), nullable=True),
    Column("data", JSON, nullable=True),
    Column("read_at", DateTime, nullable=True),
)

Index("idx_payment_notifications_read_created", payment_notifications.c.read_at, payment_notifications.c.created_at)
Index("idx_payment_notifications_event_created", payment_notifications.c.event, payment_notifications.c.created_at)
Index("ix_payment_notifications_event", payment_notifications.c.event)
Index("ix_payment_notifications_payment_id", payment_notifications.c.payment_id)
Index("ix_payment_notifications_reference", payment_notifications.c.reference)


async def up(connection):
    await connection.run_sync(lambda sync: payment_notifications.create(sync, checkfirst=True))


async def down(connection):
    await connection.run_sync(lambda sync: payment_notifications.drop(sync, checkfirst=True))


async def validate(connection):
    def check(sync):
        inspector = inspect(sync)
        if not inspector.has_table(payment_notifications.name):
            raise RuntimeError("payment_notifications table missing")
        columns = {item["name"] for item in inspector.get_columns(payment_notifications.name)}
        required = {"id", "event", "title", "read_at", "created_at"}
        missing = required - columns
        if missing:
            raise RuntimeError("payment_notifications columns missing: " + ", ".join(sorted(missing)))

    await connection.run_sync(check)


migration = Migration(
    3,
    "payment_notifications",
    "v3:" + hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    up,
    down,
    validate,
)
