"""KARPy CMS — Async Database Engine."""

import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
from app.config import settings

logger = logging.getLogger("karpy.database")

engine_options = {
    "echo": settings.DEBUG,
    "future": True,
    "pool_pre_ping": True,
}
if not settings.DATABASE_URL.startswith("sqlite"):
    engine_options.update(pool_size=10, max_overflow=20, pool_recycle=1800)

engine = create_async_engine(settings.DATABASE_URL, **engine_options)

async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    """Base class for all KARPy models."""
    pass


async def get_db() -> AsyncSession:
    """FastAPI dependency — yields an async DB session."""
    async with async_session() as session:
        try:
            yield session
        finally:
            await session.close()


def load_models() -> None:
    """Import core and active-plugin models before migration planning."""
    # Import model modules so SQLAlchemy knows every table before create_all().
    import karpy_platform.core.base.models  # noqa: F401
    import karpy_platform.core.acl.models  # noqa: F401
    import karpy_platform.core.dashboard.models  # noqa: F401
    import karpy_platform.core.media.models  # noqa: F401
    import karpy_platform.core.setting.models  # noqa: F401
    import karpy_platform.packages.menu.models  # noqa: F401
    import karpy_platform.packages.page.models  # noqa: F401
    import karpy_platform.packages.revision.models  # noqa: F401
    import karpy_platform.packages.slug.models  # noqa: F401
    import karpy_platform.packages.widget.models  # noqa: F401

    try:
        from karpy_platform.packages.plugin_management.service import plugin_service

        plugin_service.import_active_plugin_models()
    except Exception as exc:
        logger.warning("Could not import active plugin models before database initialization: %s", exc)

async def init_db():
    """Apply and validate numbered migrations before serving requests."""
    load_models()
    from app.migrations import migrate_up, validate_migrations

    await migrate_up(engine)
    await validate_migrations(engine)


async def _sync_sqlite_acl_columns(conn):
    """Grow older dev SQLite databases to the current Botble-shaped ACL schema."""
    if conn.dialect.name != "sqlite":
        return

    result = await conn.execute(text("PRAGMA table_info(users)"))
    existing_columns = {row[1] for row in result.fetchall()}
    columns = {
        "username": "VARCHAR(120)",
        "phone": "VARCHAR(30)",
        "avatar_id": "VARCHAR(36)",
        "permissions": "TEXT",
        "super_user": "BOOLEAN DEFAULT 0",
        "manage_supers": "BOOLEAN DEFAULT 0",
        "last_login": "DATETIME",
        "email_verified_at": "DATETIME",
        "remember_token": "VARCHAR(100)",
        "updated_at": "DATETIME",
    }

    for column_name, column_type in columns.items():
        if column_name not in existing_columns:
            await conn.execute(text(f"ALTER TABLE users ADD COLUMN {column_name} {column_type}"))



async def _sync_sqlite_faq_columns(conn):
    """Grow older dev SQLite databases to the current FAQ category schema."""
    if conn.dialect.name != "sqlite":
        return

    result = await conn.execute(text("PRAGMA table_info(faq_categories)"))
    rows = result.fetchall()
    if not rows:
        return

    existing_columns = {row[1] for row in rows}
    if "parent_id" not in existing_columns:
        await conn.execute(text("ALTER TABLE faq_categories ADD COLUMN parent_id VARCHAR(36)"))
