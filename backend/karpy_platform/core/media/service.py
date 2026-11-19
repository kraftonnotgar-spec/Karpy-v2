from __future__ import annotations

import hashlib
import mimetypes
import posixpath
import secrets
import urllib.request
import uuid
import warnings
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any

from fastapi import UploadFile
from app.http_security import safe_upload_filename
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from karpy_platform.core.base.helpers import clean, slugify
from karpy_platform.core.media.config import get_media_config
from karpy_platform.core.media.models import MediaFile, MediaFolder, MediaSetting
from karpy_platform.core.media.settings import (
    media_image_quality,
    media_max_upload_size_mb,
    media_settings_payload,
    media_thumbnail_sizes,
    media_upload_prefix,
    setting_value,
    truthy,
)
from karpy_platform.core.media.storage import StorageProviderError, clean_storage_path, storage_manager
from karpy_platform.core.setting.store import setting_store


class MediaValidationError(ValueError):
    pass


@dataclass
class ChunkUploadResult:
    complete: bool
    progress: int
    file: dict | None = None


class RvMediaService:
    def get_config(self, key: str | None = None, default=None):
        return get_media_config(key, default)

    def providers(self) -> list[dict]:
        return storage_manager.providers()

    def type_from_mime(self, mime_type: str) -> str:
        for group, mime_types in self.get_config("mime_types", {}).items():
            if mime_type in mime_types:
                return group
        return "other"

    def can_generate_thumbnails(self, mime_type: str, values: dict[str, Any] | None = None) -> bool:
        enabled = truthy(setting_value(values or {}, "media_enable_thumbnail_sizes", "1"))
        return enabled and bool(self.get_config("thumbnails.enabled", True)) and mime_type in self.get_config(
            "thumbnails.supported_mime_types",
            [],
        )

    def thumbnail_sizes(self, values: dict[str, Any] | None = None) -> dict[str, dict]:
        configured = media_thumbnail_sizes(values or {})
        return configured or self.get_config("thumbnails.sizes", {})

    async def folder_full_path(self, db: AsyncSession, folder: MediaFolder | None) -> str:
        if not folder:
            return ""

        segments = [folder.slug]
        parent = folder.parent
        while parent:
            segments.append(parent.slug)
            parent = parent.parent
        return "/".join(reversed(segments))

    async def create_folder(
        self,
        db: AsyncSession,
        name: str,
        parent_id: str | None = None,
        user_id: str | None = None,
        color: str | None = None,
    ) -> MediaFolder:
        parent = await self._folder_or_none(db, parent_id)
        base_name = clean(name) or "New folder"
        name = await self._unique_folder_name(db, base_name, parent.id if parent else None)
        slug = await self._unique_folder_slug(db, slugify(name, "folder"), parent.id if parent else None)
        folder = MediaFolder(name=name, slug=slug, parent_id=parent.id if parent else None, user_id=user_id, color=color)
        db.add(folder)
        await db.flush()

        path = await self.folder_full_path(db, folder)
        values = await setting_store.all(db, flat=True)
        storage_manager.provider(None, values).make_directory(clean_storage_path(posixpath.join(media_upload_prefix(values), path)))
        await db.commit()
        await db.refresh(folder, ["parent", "children", "files"])
        return folder

    async def update_folder(
        self,
        db: AsyncSession,
        folder_id: str,
        name: str | None = None,
        parent_id: str | None = None,
        color: str | None = None,
    ) -> MediaFolder:
        folder = await self.get_folder(db, folder_id)
        if parent_id == folder.id:
            raise MediaValidationError("A folder cannot be its own parent.")

        if parent_id is not None:
            parent = await self._folder_or_none(db, parent_id)
            folder.parent_id = parent.id if parent else None
        if name is not None:
            folder.name = await self._unique_folder_name(db, clean(name) or folder.name, folder.parent_id, folder.id)
            folder.slug = await self._unique_folder_slug(db, slugify(folder.name, "folder"), folder.parent_id, folder.id)
        if color is not None:
            allowed_colors = self.get_config("folder_colors", [])
            folder.color = color if color in allowed_colors else None

        await db.commit()
        await db.refresh(folder, ["parent", "children", "files"])
        return folder

    async def delete_folder(self, db: AsyncSession, folder_id: str, force: bool = False) -> None:
        folder = await self.get_folder(db, folder_id)
        await db.refresh(folder, ["files", "children", "parent"])

        if force:
            folder_path = await self.folder_full_path(db, folder)
            values = await setting_store.all(db, flat=True)
            storage_manager.provider(None, values).delete_directory(clean_storage_path(posixpath.join(media_upload_prefix(values), folder_path)))
            await self._delete_folder_tree(db, folder)
        else:
            await self._soft_delete_folder_tree(folder)
        await db.commit()

    async def upload_file(
        self,
        db: AsyncSession,
        upload: UploadFile,
        folder_id: str | None = None,
        user_id: str | None = None,
        visibility: str = "public",
        provider_name: str | None = None,
        skip_validation: bool = False,
    ) -> MediaFile:
        values = await setting_store.all(db, flat=True)
        provider = storage_manager.provider(provider_name, values)
        if not provider.configured():
            raise MediaValidationError(f'Media storage provider "{provider.name}" is not configured.')

        folder = await self._folder_or_none(db, folder_id)
        visibility = visibility if visibility in self.get_config("visibility", []) else "public"
        content = await upload.read()
        self._validate_upload(upload.filename or "file", upload.content_type, len(content), values, skip_validation)

        original_name = safe_upload_filename(upload.filename)
        guessed_mime = upload.content_type or mimetypes.guess_type(original_name)[0] or "application/octet-stream"
        content, storage_filename, guessed_mime = self._prepare_upload_content(original_name, guessed_mime, content, values)
        file_type = self.type_from_mime(guessed_mime)
        base_name = await self._unique_file_name(db, Path(original_name).stem or "file", folder.id if folder else None)
        storage_name = await self._unique_storage_name(db, storage_filename, folder, provider.name, values)
        folder_path = await self.folder_full_path(db, folder)
        relative_path = clean_storage_path(posixpath.join(media_upload_prefix(values), folder_path, storage_name))

        saved_path = provider.save(relative_path, content, visibility=visibility)
        options = {"original_name": original_name}

        media_file = MediaFile(
            user_id=user_id,
            name=base_name,
            folder_id=folder.id if folder else None,
            mime_type=guessed_mime,
            type=file_type,
            size=len(content),
            url=saved_path,
            options=options,
            visibility=visibility,
            provider=provider.name,
            random_hash=self._random_hash(saved_path),
        )
        db.add(media_file)
        await db.flush()
        await self._generate_thumbnail(media_file, content, values)
        await db.commit()
        await db.refresh(media_file, ["folder"])
        return media_file

    async def update_file(
        self,
        db: AsyncSession,
        file_id: str,
        name: str | None = None,
        alt: str | None = None,
        visibility: str | None = None,
        folder_id: str | None = None,
    ) -> MediaFile:
        media_file = await self.get_file(db, file_id)
        if name is not None:
            media_file.name = await self._unique_file_name(db, clean(name) or media_file.name, media_file.folder_id, media_file.id)
        if alt is not None:
            media_file.alt = clean(alt)
        if visibility is not None:
            media_file.visibility = visibility if visibility in self.get_config("visibility", []) else media_file.visibility
        if folder_id is not None:
            folder = await self._folder_or_none(db, folder_id)
            media_file.folder_id = folder.id if folder else None
        await db.commit()
        await db.refresh(media_file, ["folder"])
        return media_file

    async def delete_file(self, db: AsyncSession, file_id: str, force: bool = False) -> None:
        media_file = await self.get_file(db, file_id, include_deleted=force)
        if force:
            values = await setting_store.all(db, flat=True)
            provider = storage_manager.provider(media_file.provider, values)
            provider.delete(media_file.url)
            for path in self._variant_paths(media_file):
                provider.delete(path)
            await db.delete(media_file)
        else:
            media_file.is_deleted = True
        await db.commit()

    async def restore_file(self, db: AsyncSession, file_id: str) -> MediaFile:
        media_file = await self.get_file(db, file_id, include_deleted=True)
        media_file.is_deleted = False
        await db.commit()
        await db.refresh(media_file, ["folder"])
        return media_file

    async def copy_file(self, db: AsyncSession, file_id: str, user_id: str | None = None) -> MediaFile:
        media_file = await self.get_file(db, file_id)
        values = await setting_store.all(db, flat=True)
        provider = storage_manager.provider(media_file.provider, values)
        local_path = provider.public_path(media_file.url)

        if local_path and local_path.exists():
            content = local_path.read_bytes()
        elif media_file.visibility == "public":
            try:
                with urllib.request.urlopen(provider.url(media_file.url), timeout=30) as response:
                    content = response.read()
            except Exception as exception:  # pragma: no cover - remote provider availability depends on deployment.
                raise StorageProviderError("Unable to read the original file from the media provider.") from exception
        else:
            raise StorageProviderError("Private media files can only be copied when the original file is available locally.")

        folder = await self._folder_or_none(db, media_file.folder_id)
        original_name = str((media_file.options or {}).get("original_name") or posixpath.basename(media_file.url) or media_file.name)
        base_name = await self._unique_file_name(db, f"{media_file.name} copy", folder.id if folder else None)
        storage_name = await self._unique_storage_name(db, original_name, folder, provider.name, values)
        folder_path = await self.folder_full_path(db, folder)
        relative_path = clean_storage_path(posixpath.join(media_upload_prefix(values), folder_path, storage_name))
        saved_path = provider.save(relative_path, content, visibility=media_file.visibility)

        options = dict(media_file.options or {})
        options["original_name"] = original_name
        options.pop("thumbnail", None)
        options.pop("variants", None)
        options.pop("responsive", None)

        copied_file = MediaFile(
            user_id=user_id or media_file.user_id,
            name=base_name,
            folder_id=folder.id if folder else None,
            mime_type=media_file.mime_type,
            type=media_file.type,
            size=len(content),
            url=saved_path,
            options=options,
            alt=media_file.alt,
            visibility=media_file.visibility,
            provider=provider.name,
            random_hash=self._random_hash(saved_path),
        )
        db.add(copied_file)
        await db.flush()
        await self._generate_thumbnail(copied_file, content, values)
        await db.commit()
        await db.refresh(copied_file, ["folder"])
        return copied_file

    async def list_media(
        self,
        db: AsyncSession,
        folder_id: str | None = None,
        q: str = "",
        type_: str | None = None,
        include_deleted: bool = False,
        view: str = "all",
        user_id: str | None = None,
    ) -> dict:
        folder_filter = MediaFolder.parent_id.is_(None) if not folder_id else MediaFolder.parent_id == folder_id
        file_filter = MediaFile.folder_id.is_(None) if not folder_id else MediaFile.folder_id == folder_id
        view = view if view in {"all", "trash", "recent", "favorites"} else "all"
        if view == "trash":
            folder_filter = folder_filter & (MediaFolder.is_deleted.is_(True))
            file_filter = file_filter & (MediaFile.is_deleted.is_(True))
        elif not include_deleted:
            folder_filter = folder_filter & (MediaFolder.is_deleted.is_(False))
            file_filter = file_filter & (MediaFile.is_deleted.is_(False))

        folder_statement = select(MediaFolder).where(folder_filter, ~MediaFolder.slug.startswith("tp-media-")).order_by(MediaFolder.name)
        file_statement = select(MediaFile).options(selectinload(MediaFile.folder)).where(file_filter, MediaFile.provider != "merchant-private")
        if view == "favorites":
            folder_statement = folder_statement.where(False)
            favorite_filter = and_(
                MediaSetting.media_id == MediaFile.id,
                MediaSetting.key == "favorite",
                MediaSetting.value == "1",
            )
            if user_id:
                favorite_filter = favorite_filter & (MediaSetting.user_id == user_id)
            file_statement = file_statement.join(MediaSetting, favorite_filter)
        if q:
            like = f"%{q}%"
            folder_statement = folder_statement.where(or_(MediaFolder.name.ilike(like), MediaFolder.slug.ilike(like)))
            file_statement = file_statement.where(or_(MediaFile.name.ilike(like), MediaFile.url.ilike(like)))
        if type_:
            file_statement = file_statement.where(MediaFile.type == type_)
        if view == "recent":
            folder_statement = folder_statement.where(False)
        file_statement = file_statement.order_by(MediaFile.created_at.desc())

        folders = (await db.execute(folder_statement)).scalars().all()
        files = (await db.execute(file_statement)).scalars().all()
        current_folder = await self._folder_or_none(db, folder_id)
        values = await setting_store.all(db, flat=True)

        return {
            "folder": await self.folder_payload(db, current_folder) if current_folder else None,
            "breadcrumbs": await self.breadcrumbs(db, current_folder),
            "folders": [await self.folder_payload(db, folder) for folder in folders],
            "files": [self.file_payload(file) for file in files],
            "providers": storage_manager.providers(values),
            "config": {
                "allowedExtensions": self.get_config("allowed_extensions", []),
                "maxUploadSizeMb": media_max_upload_size_mb(values),
                "chunk": self._chunk_config(values),
            },
            "view": view,
            "settings": media_settings_payload(values),
        }

    async def favorite(self, db: AsyncSession, media_id: str, user_id: str, value: bool) -> MediaSetting:
        setting = await db.scalar(
            select(MediaSetting).where(
                MediaSetting.key == "favorite",
                MediaSetting.media_id == media_id,
                MediaSetting.user_id == user_id,
            )
        )
        if not setting:
            setting = MediaSetting(key="favorite", media_id=media_id, user_id=user_id)
            db.add(setting)
        setting.value = "1" if value else "0"
        await db.commit()
        await db.refresh(setting)
        return setting

    async def get_folder(self, db: AsyncSession, folder_id: str) -> MediaFolder:
        folder = await db.scalar(
            select(MediaFolder)
            .options(selectinload(MediaFolder.parent), selectinload(MediaFolder.children), selectinload(MediaFolder.files))
            .where(MediaFolder.id == folder_id, MediaFolder.is_deleted.is_(False), ~MediaFolder.slug.startswith("tp-media-"))
        )
        if not folder:
            raise MediaValidationError("Media folder not found.")
        return folder

    async def get_file(self, db: AsyncSession, file_id: str, include_deleted: bool = False) -> MediaFile:
        # Private merchant files have a separate quarantine/authorization workflow.
        filters = [MediaFile.id == file_id, MediaFile.provider != "merchant-private"]
        if not include_deleted:
            filters.append(MediaFile.is_deleted.is_(False))
        media_file = await db.scalar(
            select(MediaFile)
            .options(selectinload(MediaFile.folder))
            .where(*filters)
        )
        if not media_file:
            raise MediaValidationError("Media file not found.")
        return media_file

    async def regenerate_thumbnails(self, db: AsyncSession, file_id: str) -> MediaFile:
        media_file = await self.get_file(db, file_id)
        values = await setting_store.all(db, flat=True)
        provider = storage_manager.provider(media_file.provider)
        local_path = provider.public_path(media_file.url)
        if not local_path or not local_path.exists():
            raise MediaValidationError("Original media file is not available on local storage.")
        for path in self._variant_paths(media_file):
            provider.delete(path)
        await self._generate_thumbnail(media_file, local_path.read_bytes(), values)
        await db.commit()
        await db.refresh(media_file, ["folder"])
        return media_file

    async def regenerate_all_thumbnails(self, db: AsyncSession) -> dict[str, int]:
        values = await setting_store.all(db, flat=True)
        statement = select(MediaFile).where(MediaFile.is_deleted.is_(False), MediaFile.type == "image", MediaFile.provider != "merchant-private")
        files = (await db.execute(statement)).scalars().all()
        generated = 0
        skipped = 0
        for media_file in files:
            provider = storage_manager.provider(media_file.provider)
            local_path = provider.public_path(media_file.url)
            if not local_path or not local_path.exists():
                skipped += 1
                continue
            for path in self._variant_paths(media_file):
                provider.delete(path)
            await self._generate_thumbnail(media_file, local_path.read_bytes(), values)
            generated += 1
        await db.commit()
        return {"total": len(files), "generated": generated, "skipped": skipped}

    def image_url(self, media_file: MediaFile, size: str | None = None) -> str | None:
        if media_file.visibility != "public":
            return None
        provider = storage_manager.provider(media_file.provider)
        if not size:
            return provider.url(media_file.url)
        variant = ((media_file.options or {}).get("variants") or {}).get(size)
        if isinstance(variant, dict) and variant.get("path"):
            return provider.url(variant["path"])
        return provider.url(media_file.url)

    async def folder_payload(self, db: AsyncSession, folder: MediaFolder) -> dict:
        await db.refresh(folder, ["parent"])
        return {
            "id": folder.id,
            "name": folder.name,
            "slug": folder.slug,
            "parentId": folder.parent_id,
            "fullPath": await self.folder_full_path(db, folder),
            "color": folder.color,
            "createdAt": folder.created_at.isoformat() if folder.created_at else None,
            "updatedAt": folder.updated_at.isoformat() if folder.updated_at else None,
        }

    def file_payload(self, media_file: MediaFile) -> dict:
        provider = storage_manager.provider(media_file.provider)
        full_url = provider.url(media_file.url) if media_file.visibility == "public" else None
        thumbnail = (media_file.options or {}).get("thumbnail")
        variants = (media_file.options or {}).get("variants", {})
        responsive = (media_file.options or {}).get("responsive", {})
        return {
            "id": media_file.id,
            "name": media_file.name,
            "folderId": media_file.folder_id,
            "mimeType": media_file.mime_type,
            "type": media_file.type,
            "size": media_file.size,
            "humanSize": media_file.human_size,
            "url": media_file.url,
            "fullUrl": full_url,
            "thumbnail": provider.url(thumbnail) if thumbnail and media_file.visibility == "public" else None,
            "variants": {
                key: {
                    **value,
                    "url": provider.url(value["path"]) if value.get("path") and media_file.visibility == "public" else None,
                }
                for key, value in variants.items()
                if isinstance(value, dict)
            },
            "srcset": responsive.get("srcset", ""),
            "sizes": responsive.get("sizes", "100vw"),
            "alt": media_file.alt,
            "visibility": media_file.visibility,
            "provider": media_file.provider,
            "previewType": self._preview_type(media_file),
            "indirectUrl": f"/api/admin/media/files/{media_file.id}/download",
            "isDeleted": media_file.is_deleted,
            "canGenerateThumbnails": media_file.can_generate_thumbnails,
            "options": media_file.options or {},
            "createdAt": media_file.created_at.isoformat() if media_file.created_at else None,
            "updatedAt": media_file.updated_at.isoformat() if media_file.updated_at else None,
        }

    async def breadcrumbs(self, db: AsyncSession, folder: MediaFolder | None) -> list[dict]:
        if not folder:
            return [{"id": None, "name": "Media", "path": ""}]

        crumbs = []
        current = folder
        while current:
            crumbs.append({"id": current.id, "name": current.name, "path": await self.folder_full_path(db, current)})
            current = current.parent
        crumbs.append({"id": None, "name": "Media", "path": ""})
        return list(reversed(crumbs))

    async def _folder_or_none(self, db: AsyncSession, folder_id: str | None) -> MediaFolder | None:
        if not folder_id:
            return None
        return await self.get_folder(db, folder_id)

    async def _unique_folder_name(
        self,
        db: AsyncSession,
        name: str,
        parent_id: str | None,
        ignore_id: str | None = None,
    ) -> str:
        return await self._unique_value(db, MediaFolder, MediaFolder.name, name, parent_id, ignore_id)

    async def _unique_folder_slug(
        self,
        db: AsyncSession,
        slug: str,
        parent_id: str | None,
        ignore_id: str | None = None,
    ) -> str:
        return await self._unique_value(db, MediaFolder, MediaFolder.slug, slug, parent_id, ignore_id)

    async def _unique_file_name(
        self,
        db: AsyncSession,
        name: str,
        folder_id: str | None,
        ignore_id: str | None = None,
    ) -> str:
        return await self._unique_value(db, MediaFile, MediaFile.name, clean(name), folder_id, ignore_id, "folder_id")

    async def _unique_value(
        self,
        db: AsyncSession,
        model,
        column,
        value: str,
        parent_id: str | None,
        ignore_id: str | None = None,
        parent_column: str = "parent_id",
    ) -> str:
        base = value or "item"
        candidate = base
        suffix = 2
        while True:
            parent_attr = getattr(model, parent_column)
            statement = select(func.count()).select_from(model).where(column == candidate, model.is_deleted.is_(False))
            statement = statement.where(parent_attr.is_(None) if parent_id is None else parent_attr == parent_id)
            if ignore_id:
                statement = statement.where(model.id != ignore_id)
            if not await db.scalar(statement):
                return candidate
            candidate = f"{base}-{suffix}"
            suffix += 1

    async def _unique_storage_name(
        self,
        db: AsyncSession,
        filename: str,
        folder: MediaFolder | None,
        provider_name: str,
        values: dict[str, Any],
    ) -> str:
        path = Path(filename)
        if truthy(setting_value(values, "media_convert_file_name_to_uuid", "0")):
            stem = str(uuid.uuid4())
        elif truthy(setting_value(values, "media_use_original_name_for_file_path", "0")):
            stem = clean(path.stem).replace("/", "-").replace("\\", "-") or "file"
        else:
            stem = slugify(path.stem, "file")
        suffix = path.suffix.lower()
        candidate = f"{stem}{suffix}"
        folder_path = clean_storage_path(posixpath.join(media_upload_prefix(values), await self.folder_full_path(db, folder)))
        provider = storage_manager.provider(provider_name, values)
        counter = 2
        while await db.scalar(select(func.count()).select_from(MediaFile).where(MediaFile.url == clean_storage_path(posixpath.join(folder_path, candidate)))) or provider.exists(posixpath.join(folder_path, candidate)):
            candidate = f"{stem}-{counter}{suffix}"
            counter += 1
        return candidate

    def _validate_upload(self, filename: str, mime_type: str | None, size: int, values: dict[str, Any], skip_validation: bool = False) -> None:
        if skip_validation:
            return
        max_size = int(media_max_upload_size_mb(values) * 1024 * 1024)
        if size > max_size:
            raise MediaValidationError(f"File is too large. Max upload size is {media_max_upload_size_mb(values):g} MB.")
        extension = Path(filename).suffix.lower().lstrip(".")
        if extension not in self.get_config("allowed_extensions", []):
            raise MediaValidationError(f'File extension "{extension}" is not allowed.')
        if mime_type:
            known = set()
            for values in self.get_config("mime_types", {}).values():
                known.update(values)
            guessed = mimetypes.guess_type(filename)[0]
            if mime_type not in known and guessed not in known:
                raise MediaValidationError(f'File MIME type "{mime_type}" is not allowed.')

    def _prepare_upload_content(self, filename: str, mime_type: str, content: bytes, values: dict[str, Any]) -> tuple[bytes, str, str]:
        extension = Path(filename).suffix.lower().lstrip(".")
        should_convert_to_webp = extension in {"jpg", "jpeg", "png"} and truthy(setting_value(values, "media_convert_image_to_webp", "0"))
        if not self.can_generate_thumbnails(mime_type, values):
            return content, filename, mime_type

        try:
            from PIL import Image, ImageOps
        except ImportError:
            return content, filename, mime_type

        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                probe = Image.open(BytesIO(content))
                probe.verify()
                image = Image.open(BytesIO(content))
                image.load()
        except (Image.DecompressionBombError, Image.DecompressionBombWarning, OSError, SyntaxError, ValueError) as exc:
            raise MediaValidationError("The uploaded image is malformed or exceeds safe decoding limits.") from exc

        keep_original = truthy(setting_value(values, "media_keep_original_file_size_and_quality", "0"))
        if keep_original and not should_convert_to_webp:
            return content, filename, mime_type

        try:
            image = ImageOps.exif_transpose(image)
            if truthy(setting_value(values, "media_reduce_large_image_size", "0")):
                max_width = self._optional_int(setting_value(values, "media_image_max_width", 0))
                max_height = self._optional_int(setting_value(values, "media_image_max_height", 0))
                if max_width or max_height:
                    image.thumbnail((max_width or image.width, max_height or image.height))
            image = self._apply_watermark(image, values)
            save_format = "WEBP" if should_convert_to_webp else (image.format or extension or "JPEG").upper()
            output_name = str(Path(filename).with_suffix(".webp")) if should_convert_to_webp else filename
            output_mime = "image/webp" if should_convert_to_webp else mime_type
            return self._encode_image(image, save_format, values), output_name, output_mime
        except Exception as exc:
            raise MediaValidationError("The uploaded image could not be processed safely.") from exc

    async def _generate_thumbnail(self, media_file: MediaFile, content: bytes, values: dict[str, Any]) -> None:
        if not self.can_generate_thumbnails(media_file.mime_type, values):
            return
        try:
            from PIL import Image, ImageOps
        except ImportError:
            return

        try:
            image = Image.open(BytesIO(content))
            image = ImageOps.exif_transpose(image)
            original_format = image.format or Path(media_file.url).suffix.lstrip(".").upper()
            variants = {}
            provider = storage_manager.provider(media_file.provider, values)
            for name, size in self.thumbnail_sizes(values).items():
                generated = self._resize_image(image.copy(), size)
                if generated is None:
                    continue
                variant_path = self._variant_path(media_file.url, self._readable_size(size))
                variant_content = self._encode_image(generated, original_format, values)
                provider.save(variant_path, variant_content, visibility=media_file.visibility)
                variants[name] = {
                    "path": variant_path,
                    "width": generated.width,
                    "height": generated.height,
                    "size": len(variant_content),
                    "label": self._readable_size(size),
                }
            responsive_variants = sorted(
                [item for item in variants.values() if item.get("width")],
                key=lambda item: item["width"],
            )
            srcset = ", ".join(f"{provider.url(item['path'])} {item['width']}w" for item in responsive_variants)
            media_file.options = {
                **(media_file.options or {}),
                "thumbnail": variants.get("thumb", {}).get("path"),
                "variants": variants,
                "responsive": {"srcset": srcset, "sizes": "100vw"},
            }
        except Exception:
            return

    def _resize_image(self, image, size: dict):
        from PIL import Image, ImageOps

        width = size.get("width")
        height = size.get("height")
        mode = size.get("mode", "cover")
        width = 0 if width in {None, "", "auto"} else int(width)
        height = 0 if height in {None, "", "auto"} else int(height)
        if not width and not height:
            return None
        if width and height and mode in {"cover", "fit"}:
            return ImageOps.fit(image, (width, height), method=Image.Resampling.LANCZOS, centering=self._crop_centering())
        if width and height and mode == "resize":
            return image.resize((width, height), Image.Resampling.LANCZOS)
        original_width, original_height = image.size
        if width:
            if original_width <= width:
                return image.copy()
            height = max(1, round(original_height * (width / original_width)))
            return image.resize((width, height), Image.Resampling.LANCZOS)
        if height:
            if original_height <= height:
                return image.copy()
            width = max(1, round(original_width * (height / original_height)))
            return image.resize((width, height), Image.Resampling.LANCZOS)
        return None

    def _encode_image(self, image, original_format: str, values: dict[str, Any]) -> bytes:
        save_format = (original_format or "JPEG").upper()
        if save_format == "JPG":
            save_format = "JPEG"
        if save_format not in {"JPEG", "PNG", "GIF", "WEBP", "AVIF"}:
            save_format = "JPEG"
        quality = media_image_quality(values)
        save_kwargs = {}
        if save_format in {"JPEG", "WEBP", "AVIF"}:
            save_kwargs.update({"quality": quality, "optimize": True})
            if image.mode not in {"RGB", "L"}:
                image = image.convert("RGB")
        elif save_format == "PNG":
            save_kwargs.update({"optimize": True})
        buffer = BytesIO()
        image.save(buffer, format=save_format, **save_kwargs)
        return buffer.getvalue()

    def _apply_watermark(self, image, values: dict[str, Any]):
        if not truthy(setting_value(values, "media_watermark_enabled", "0")):
            return image
        source = str(setting_value(values, "media_watermark_source", "")).strip()
        if not source:
            return image
        try:
            from PIL import Image

            provider = storage_manager.provider("local", values)
            source_path = source.removeprefix("/media/").removeprefix("media/")
            local_path = provider.public_path(source_path)
            if not local_path or not local_path.exists():
                return image
            watermark = Image.open(local_path).convert("RGBA")
            target_width = max(1, round(image.width * (float(setting_value(values, "media_watermark_size", 10)) / 100)))
            watermark.thumbnail((target_width, image.height))
            opacity = max(0, min(100, float(setting_value(values, "media_watermark_opacity", 70)))) / 100
            if opacity < 1:
                alpha = watermark.getchannel("A")
                alpha = alpha.point(lambda point: int(point * opacity))
                watermark.putalpha(alpha)
            base = image.convert("RGBA")
            x, y = self._watermark_position(base.size, watermark.size, values)
            base.alpha_composite(watermark, dest=(x, y))
            return base.convert(image.mode if image.mode in {"RGB", "RGBA"} else "RGB")
        except Exception:
            return image

    def _watermark_position(self, image_size: tuple[int, int], watermark_size: tuple[int, int], values: dict[str, Any]) -> tuple[int, int]:
        image_width, image_height = image_size
        mark_width, mark_height = watermark_size
        offset_x = self._optional_int(setting_value(values, "media_watermark_position_x", 10), 10)
        offset_y = self._optional_int(setting_value(values, "media_watermark_position_y", 10), 10)
        position = str(setting_value(values, "media_watermark_position", "bottom-right"))
        if position == "top-left":
            return offset_x, offset_y
        if position == "top-right":
            return max(0, image_width - mark_width - offset_x), offset_y
        if position == "bottom-left":
            return offset_x, max(0, image_height - mark_height - offset_y)
        if position == "center":
            return max(0, (image_width - mark_width) // 2), max(0, (image_height - mark_height) // 2)
        return max(0, image_width - mark_width - offset_x), max(0, image_height - mark_height - offset_y)

    def _crop_centering(self) -> tuple[float, float]:
        return (0.5, 0.5)

    def _optional_int(self, value: Any, default: int = 0) -> int:
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return default

    def _chunk_config(self, values: dict[str, Any]) -> dict[str, Any]:
        return {
            "enabled": truthy(setting_value(values, "media_chunk_enabled", "1")),
            "storage": "chunks",
            "max_file_size_mb": self._optional_int(setting_value(values, "media_max_file_size", 512), 512),
            "chunk_size_mb": self._optional_int(setting_value(values, "media_chunk_size", 2), 2),
        }

    def _variant_path(self, url: str, size: str) -> str:
        path = Path(url)
        return clean_storage_path(posixpath.join(str(path.parent) if str(path.parent) != "." else "", f"{path.stem}-{size}{path.suffix}"))

    def _readable_size(self, size: dict) -> str:
        width = size.get("width") or "auto"
        height = size.get("height") or "auto"
        return f"{width}x{height}"

    def _variant_paths(self, media_file: MediaFile) -> list[str]:
        options = media_file.options or {}
        paths = []
        thumbnail = options.get("thumbnail")
        if thumbnail:
            paths.append(thumbnail)
        variants = options.get("variants") or {}
        for variant in variants.values():
            if isinstance(variant, dict) and variant.get("path"):
                paths.append(variant["path"])
        return list(dict.fromkeys(paths))

    async def _delete_folder_tree(self, db: AsyncSession, folder: MediaFolder) -> None:
        await db.refresh(folder, ["children", "files"])
        for child in list(folder.children):
            await self._delete_folder_tree(db, child)
        for media_file in list(folder.files):
            await db.delete(media_file)
        await db.delete(folder)

    async def _soft_delete_folder_tree(self, folder: MediaFolder) -> None:
        folder.is_deleted = True
        for media_file in folder.files:
            media_file.is_deleted = True
        for child in folder.children:
            await self._soft_delete_folder_tree(child)

    def _preview_type(self, media_file: MediaFile) -> str:
        if media_file.type in {"image", "video", "audio"}:
            return media_file.type
        if media_file.mime_type == "application/pdf":
            return "pdf"
        return "document"

    def _random_hash(self, value: str) -> str:
        return hashlib.sha1(f"{value}:{secrets.token_urlsafe(16)}".encode("utf-8")).hexdigest()


rv_media = RvMediaService()
