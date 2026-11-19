from __future__ import annotations

from sqlalchemy import Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from karpy_platform.core.base.models import BaseModel


class Slug(BaseModel):
    """Botble-style polymorphic slug record."""

    __tablename__ = "slugs"
    __table_args__ = (
        UniqueConstraint("key", "prefix", name="uq_slugs_key_prefix"),
        Index("idx_slugs_reference", "reference_type", "reference_id"),
        Index("idx_slugs_lookup", "key", "prefix", "reference_type"),
    )

    key: Mapped[str] = mapped_column(String(255), nullable=False)
    reference_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    reference_type: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    prefix: Mapped[str] = mapped_column(String(120), nullable=True, default="")
