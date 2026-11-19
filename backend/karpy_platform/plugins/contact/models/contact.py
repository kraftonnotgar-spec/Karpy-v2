"""Contact plugin models.

The tables mirror Botble's contact plugin shape: incoming messages live in
``contacts``, admin replies in ``contact_replies``, and configurable form
fields in ``contact_custom_fields`` with optional values.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Boolean, ForeignKey, Index, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from karpy_platform.core.base.models import BaseModel


class Contact(BaseModel):
    __tablename__ = "contacts"
    __table_args__ = (
        Index("idx_contacts_status_created", "status", "created_at"),
        Index("idx_contacts_email_created", "email", "created_at"),
    )

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    email: Mapped[str] = mapped_column(String(190), nullable=False, index=True)
    phone: Mapped[str | None] = mapped_column(String(60), nullable=True)
    address: Mapped[str | None] = mapped_column(String(190), nullable=True)
    subject: Mapped[str | None] = mapped_column(String(190), nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(60), default="unread", nullable=False, index=True)
    custom_fields: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True, default=dict)

    replies: Mapped[list["ContactReply"]] = relationship(
        "ContactReply",
        back_populates="contact",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class ContactReply(BaseModel):
    __tablename__ = "contact_replies"
    __table_args__ = (Index("idx_contact_replies_contact_created", "contact_id", "created_at"),)

    message: Mapped[str] = mapped_column(Text, nullable=False)
    contact_id: Mapped[str] = mapped_column(String(36), ForeignKey("contacts.id"), nullable=False, index=True)

    contact: Mapped[Contact] = relationship("Contact", back_populates="replies", lazy="selectin")


class ContactCustomField(BaseModel):
    __tablename__ = "contact_custom_fields"
    __table_args__ = (
        Index("idx_contact_custom_fields_status_order", "status", "order"),
        Index("idx_contact_custom_fields_type", "type"),
    )

    type: Mapped[str] = mapped_column(String(40), default="text", nullable=False)
    required: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    name: Mapped[str] = mapped_column(String(190), nullable=False)
    placeholder: Mapped[str | None] = mapped_column(String(190), nullable=True)
    order: Mapped[int] = mapped_column(Integer, default=999, nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="published", nullable=False)

    options: Mapped[list["ContactCustomFieldOption"]] = relationship(
        "ContactCustomFieldOption",
        back_populates="custom_field",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="ContactCustomFieldOption.order",
    )


class ContactCustomFieldOption(BaseModel):
    __tablename__ = "contact_custom_field_options"
    __table_args__ = (Index("idx_contact_custom_field_options_field_order", "custom_field_id", "order"),)

    custom_field_id: Mapped[str] = mapped_column(String(36), ForeignKey("contact_custom_fields.id"), nullable=False, index=True)
    label: Mapped[str | None] = mapped_column(String(190), nullable=True)
    value: Mapped[str] = mapped_column(String(190), nullable=False)
    order: Mapped[int] = mapped_column(Integer, default=999, nullable=False)

    custom_field: Mapped[ContactCustomField] = relationship("ContactCustomField", back_populates="options", lazy="selectin")
