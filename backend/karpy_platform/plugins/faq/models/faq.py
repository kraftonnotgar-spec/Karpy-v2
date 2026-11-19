"""Models for the KARPy FAQ plugin."""

from __future__ import annotations

from sqlalchemy import ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from karpy_platform.core.base.models import BaseModel


class FaqCategory(BaseModel):
    __tablename__ = "faq_categories"
    __table_args__ = (
        Index("idx_faq_categories_status_order", "status", "order"),
        Index("idx_faq_categories_slug_status", "slug", "status"),
    )

    name: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    slug: Mapped[str | None] = mapped_column(String(140), nullable=True, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    parent_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("faq_categories.id"), nullable=True, index=True)
    order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="published", nullable=False, index=True)

    parent: Mapped["FaqCategory | None"] = relationship(
        "FaqCategory",
        remote_side="FaqCategory.id",
        back_populates="children",
        lazy="selectin",
    )
    children: Mapped[list["FaqCategory"]] = relationship(
        "FaqCategory",
        back_populates="parent",
        lazy="selectin",
        order_by="FaqCategory.order",
    )
    faqs: Mapped[list["Faq"]] = relationship(
        "Faq",
        back_populates="category",
        lazy="selectin",
        order_by="Faq.order",
    )


class Faq(BaseModel):
    __tablename__ = "faqs"
    __table_args__ = (
        Index("idx_faqs_category_status_order", "category_id", "status", "order"),
        Index("idx_faqs_question", "question"),
    )

    category_id: Mapped[str] = mapped_column(String(36), ForeignKey("faq_categories.id"), nullable=False, index=True)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="published", nullable=False, index=True)

    category: Mapped[FaqCategory] = relationship("FaqCategory", back_populates="faqs", lazy="selectin")
