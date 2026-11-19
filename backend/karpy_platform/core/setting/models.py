import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base

class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(255), primary_key=True)
    value: Mapped[str | None] = mapped_column(Text, nullable=True)


class WebsiteVisit(Base):
    """First-party website analytics captured from public page requests."""

    __tablename__ = "website_visits"
    __table_args__ = (
        Index("ix_website_visits_created_at", "created_at"),
        Index("ix_website_visits_path_created_at", "path", "created_at"),
        Index("ix_website_visits_visitor_created_at", "visitor_key", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    visitor_key: Mapped[str] = mapped_column(String(64), index=True)
    path: Mapped[str] = mapped_column(String(500), default="/", index=True)
    referrer: Mapped[str | None] = mapped_column(String(500), nullable=True)
    device: Mapped[str] = mapped_column(String(30), default="desktop", index=True)
    browser: Mapped[str] = mapped_column(String(80), default="Unknown", index=True)
    country: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    city: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    ip_hash: Mapped[str] = mapped_column(String(64), index=True)
    user_agent: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
