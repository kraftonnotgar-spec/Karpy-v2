"""
KARPy CMS — Base Models.

Every model in the system (core + plugins) extends these base classes.
This gives all models: UUID primary keys, timestamps, and soft-delete.
"""

import uuid
from datetime import datetime
from sqlalchemy import Boolean, Column, DateTime, Index, JSON, String
from app.database import Base


class BaseModel(Base):
    """Abstract base with UUID, timestamps, and soft-delete."""
    __abstract__ = True

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    is_deleted = Column(Boolean, default=False, nullable=False)

    def to_dict(self) -> dict:
        """Serialize model to dictionary (used by API responses)."""
        result = {}
        for column in self.__table__.columns:
            value = getattr(self, column.name)
            if isinstance(value, datetime):
                value = value.isoformat()
            result[column.name] = value
        return result


class MetaBox(BaseModel):
    """Botble-style polymorphic metadata storage."""

    __tablename__ = "meta_boxes"
    __table_args__ = (
        Index("ix_meta_boxes_reference", "reference_id", "reference_type"),
        Index("ix_meta_boxes_key_reference", "meta_key", "reference_id", "reference_type"),
    )

    meta_key = Column(String(120), nullable=False)
    meta_value = Column(JSON, nullable=True)
    reference_id = Column(String(36), nullable=False, index=True)
    reference_type = Column(String(120), nullable=False)


class AdminNotification(BaseModel):
    """Admin notification feed, ported from Botble core/base."""

    __tablename__ = "admin_notifications"

    title = Column(String(255), nullable=False)
    action_label = Column(String(120), nullable=True)
    action_url = Column(String(500), nullable=True)
    description = Column(String(400), nullable=True)
    permission = Column(String(120), nullable=True)
    read_at = Column(DateTime, nullable=True)

    def mark_as_read(self) -> None:
        self.read_at = datetime.utcnow()


class SlugMixin:
    """Mixin for models that need URL-friendly slugs (like Pages, Posts)."""
    slug = Column(String(255), unique=True, nullable=True, index=True)


class StatusMixin:
    """Mixin for models with publish status (draft/published/hidden)."""
    status = Column(String(20), default="draft", nullable=False)


class SeoMixin:
    """Mixin for models that need SEO metadata."""
    seo_title = Column(String(255), nullable=True)
    seo_description = Column(String(500), nullable=True)
    seo_image = Column(String(500), nullable=True)
