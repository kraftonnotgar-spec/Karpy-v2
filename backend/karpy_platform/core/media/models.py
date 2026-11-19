from __future__ import annotations

from sqlalchemy import JSON, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from karpy_platform.core.base.models import BaseModel
from karpy_platform.core.media.config import get_media_config


class MediaFolder(BaseModel):
    __tablename__ = "media_folders"
    __table_args__ = (
        Index("ix_media_folders_parent", "parent_id"),
        UniqueConstraint("parent_id", "slug", name="uq_media_folders_parent_slug"),
    )

    user_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    name: Mapped[str] = mapped_column(String(255))
    slug: Mapped[str] = mapped_column(String(255), index=True)
    parent_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("media_folders.id"), nullable=True)
    color: Mapped[str | None] = mapped_column(String(20), nullable=True)

    parent: Mapped["MediaFolder | None"] = relationship(
        "MediaFolder",
        remote_side="MediaFolder.id",
        back_populates="children",
        lazy="selectin",
    )
    children: Mapped[list["MediaFolder"]] = relationship(
        "MediaFolder",
        back_populates="parent",
        lazy="selectin",
    )
    files: Mapped[list["MediaFile"]] = relationship(
        "MediaFile",
        back_populates="folder",
        lazy="selectin",
    )


class MediaFile(BaseModel):
    __tablename__ = "media_files"
    __table_args__ = (
        Index("ix_media_files_folder", "folder_id"),
        UniqueConstraint("folder_id", "url", name="uq_media_files_folder_url"),
    )

    user_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    name: Mapped[str] = mapped_column(String(255))
    folder_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("media_folders.id"), nullable=True)
    mime_type: Mapped[str] = mapped_column(String(120))
    type: Mapped[str] = mapped_column(String(40), default="other", index=True)
    size: Mapped[int] = mapped_column(Integer, default=0)
    url: Mapped[str] = mapped_column(String(1000), index=True)
    options: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    alt: Mapped[str | None] = mapped_column(String(255), nullable=True)
    visibility: Mapped[str] = mapped_column(String(20), default="public", index=True)
    provider: Mapped[str] = mapped_column(String(60), default="local", index=True)
    random_hash: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)

    folder: Mapped[MediaFolder | None] = relationship("MediaFolder", back_populates="files", lazy="selectin")

    @property
    def human_size(self) -> str:
        size = float(self.size or 0)
        for unit in ["B", "KB", "MB", "GB", "TB"]:
            if size < 1024 or unit == "TB":
                return f"{size:.0f} {unit}" if unit == "B" else f"{size:.2f} {unit}"
            size /= 1024
        return "0 B"

    @property
    def can_generate_thumbnails(self) -> bool:
        return self.visibility == "public" and self.mime_type in get_media_config("thumbnails.supported_mime_types", [])


class MediaSetting(BaseModel):
    __tablename__ = "media_settings"
    __table_args__ = (UniqueConstraint("key", "user_id", "media_id", name="uq_media_settings_scope"),)

    key: Mapped[str] = mapped_column(String(120), index=True)
    value: Mapped[str | None] = mapped_column(Text, nullable=True)
    media_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    user_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
