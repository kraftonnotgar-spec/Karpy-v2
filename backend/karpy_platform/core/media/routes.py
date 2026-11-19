from __future__ import annotations

import hashlib
import json
import posixpath
import re
import unicodedata
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.http_security import safe_upload_filename
from karpy_platform.core.acl.routes import ensure_admin_user
from karpy_platform.core.base.responses import BaseHttpResponse
from karpy_platform.core.media.service import MediaValidationError, rv_media
from karpy_platform.core.media.storage import StorageProviderError, storage_manager
from karpy_platform.core.setting.store import setting_store

router = APIRouter()

CHUNK_MAX_BYTES = 8 * 1024 * 1024
CHUNK_TOTAL_BYTES = 128 * 1024 * 1024
CHUNK_MAX_COUNT = 1024
CHUNK_MAX_SESSIONS = 128
CHUNK_MAX_USERS = 256


def _chunk_same_origin(request: Request) -> None:
    # Headerless API clients remain supported; browser cross-origin writes do not.
    if request.headers.get("sec-fetch-site") == "cross-site":
        raise HTTPException(403, "Cross-origin upload is not allowed.")
    source = request.headers.get("origin") or request.headers.get("referer")
    if source:
        try:
            parsed = urlsplit(source)
            expected = urlsplit(str(request.base_url))
            origin = (parsed.scheme, parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80))
            target = (expected.scheme, expected.hostname, expected.port or (443 if expected.scheme == "https" else 80))
            if parsed.scheme not in {"http", "https"} or parsed.username or parsed.password or origin != target:
                raise ValueError
        except ValueError:
            raise HTTPException(403, "Cross-origin upload is not allowed.") from None


def _chunk_root() -> Path:
    root = Path(settings.STORAGE_DIR) / "core-media-chunks"
    public_roots = (settings.MEDIA_DIR, settings.THEME_PUBLIC_DIR, settings.BASE_DIR / "admin-ui" / "dist")
    if any(root.resolve().is_relative_to(Path(public).resolve()) for public in public_roots):
        raise HTTPException(503, "Chunk storage must be outside public mounts.")
    if root.is_symlink():
        raise HTTPException(503, "Invalid chunk storage.")
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    return root


def _chunk_directory(path: Path) -> None:
    if path.is_symlink() or (path.exists() and not path.is_dir()):
        raise HTTPException(409, "Invalid chunk session.")
    path.mkdir(mode=0o700, exist_ok=True)


def _chunk_manifest(path: Path, state: dict) -> None:
    temporary = path.with_suffix(".tmp")
    with temporary.open("x", encoding="utf-8") as target:
        json.dump(state, target)
    temporary.replace(path)


class FolderCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    parentId: str | None = None
    color: str | None = None


class FolderUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    parentId: str | None = None
    color: str | None = None


class FileUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    alt: str | None = Field(default=None, max_length=255)
    visibility: str | None = None
    folderId: str | None = None


class FavoriteUpdate(BaseModel):
    value: bool = True


@router.get("/media")
async def list_media(
    folderId: str | None = None,
    q: str = "",
    type: str | None = Query(default=None),
    includeDeleted: bool = False,
    view: str = Query(default="all"),
    db: AsyncSession = Depends(get_db),
):
    user = await ensure_admin_user(db)
    try:
        return await rv_media.list_media(db, folder_id=folderId, q=q, type_=type, include_deleted=includeDeleted, view=view, user_id=user.id)
    except MediaValidationError as exception:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exception)) from exception


@router.get("/media/config")
async def media_config(db: AsyncSession = Depends(get_db)):
    await ensure_admin_user(db)
    values = await setting_store.all(db, flat=True)
    return {"config": rv_media.get_config(), "providers": storage_manager.providers(values)}


@router.get("/media/providers")
async def media_providers(db: AsyncSession = Depends(get_db)):
    await ensure_admin_user(db)
    values = await setting_store.all(db, flat=True)
    return {"providers": storage_manager.providers(values)}


@router.post("/media/folders", status_code=status.HTTP_201_CREATED)
async def create_folder(data: FolderCreate, db: AsyncSession = Depends(get_db)):
    user = await ensure_admin_user(db)
    try:
        folder = await rv_media.create_folder(db, data.name, data.parentId, user.id, data.color)
        return BaseHttpResponse.make().set_data(await rv_media.folder_payload(db, folder)).with_created_success_message().to_dict()
    except (MediaValidationError, StorageProviderError) as exception:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exception)) from exception


@router.patch("/media/folders/{folder_id}")
async def update_folder(folder_id: str, data: FolderUpdate, db: AsyncSession = Depends(get_db)):
    await ensure_admin_user(db)
    try:
        folder = await rv_media.update_folder(db, folder_id, data.name, data.parentId, data.color)
        return BaseHttpResponse.make().set_data(await rv_media.folder_payload(db, folder)).with_updated_success_message().to_dict()
    except MediaValidationError as exception:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exception)) from exception


@router.delete("/media/folders/{folder_id}")
async def delete_folder(folder_id: str, force: bool = False, db: AsyncSession = Depends(get_db)):
    await ensure_admin_user(db)
    try:
        await rv_media.delete_folder(db, folder_id, force=force)
        return BaseHttpResponse.make().with_deleted_success_message().to_dict()
    except (MediaValidationError, StorageProviderError) as exception:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exception)) from exception


@router.post("/media/files", status_code=status.HTTP_201_CREATED)
async def upload_files(
    files: list[UploadFile] = File(...),
    folderId: str | None = Form(default=None),
    visibility: str = Form(default="public"),
    provider: str | None = Form(default=None),
    db: AsyncSession = Depends(get_db),
):
    user = await ensure_admin_user(db)
    uploaded = []
    try:
        for upload in files:
            media_file = await rv_media.upload_file(
                db,
                upload,
                folder_id=folderId,
                user_id=user.id,
                visibility=visibility,
                provider_name=provider,
            )
            uploaded.append(rv_media.file_payload(media_file))
    except (MediaValidationError, StorageProviderError) as exception:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exception)) from exception

    return BaseHttpResponse.make().set_data(uploaded).with_created_success_message().to_dict()


@router.post("/media/files/chunk")
async def upload_file_chunk(
    request: Request,
    file: UploadFile = File(...),
    dzchunkindex: str = Form(default="0"),
    dztotalchunkcount: str = Form(default="1"),
    dzuuid: str = Form(...),
    filename: str = Form(...),
    folderId: str | None = Form(default=None),
    visibility: str = Form(default="public"),
    db: AsyncSession = Depends(get_db),
):
    user = await ensure_admin_user(db)
    _chunk_same_origin(request)
    try:
        session = str(UUID(dzuuid))
        if dzuuid.lower() != session:
            raise ValueError
    except ValueError:
        raise HTTPException(400, "Invalid chunk session UUID.") from None
    if (
        not filename or len(filename) > 255 or filename in {".", ".."}
        or any(char in filename for char in '/\\:')
        or any(unicodedata.category(char).startswith("C") for char in filename)
        or safe_upload_filename(filename) != filename
    ):
        raise HTTPException(400, "Invalid upload filename.")
    if not all(re.fullmatch(r"[0-9]{1,4}", value) for value in (dzchunkindex, dztotalchunkcount)):
        raise HTTPException(400, "Invalid chunk index or count.")
    index, count = int(dzchunkindex), int(dztotalchunkcount)
    if not 1 <= count <= CHUNK_MAX_COUNT or not 0 <= index < count:
        raise HTTPException(400, "Invalid chunk index or count.")
    content = await file.read(CHUNK_MAX_BYTES + 1)
    if len(content) > CHUNK_MAX_BYTES:
        raise HTTPException(413, "Chunk is too large.")
    root = _chunk_root()
    lock = root / ".lock"
    try:
        lock.mkdir(mode=0o700)
    except FileExistsError:
        raise HTTPException(409, "Chunk storage is busy; retry this chunk.") from None
    # An exclusive filesystem lock also serializes separate server workers.
    # Only fixed, validated session entries are ever removed, never a directory tree.
    try:
        owner = hashlib.sha256(str(user.id).encode()).hexdigest()
        user_dir = root / owner
        if not user_dir.exists() and sum(1 for item in root.iterdir() if item.name != ".lock") >= CHUNK_MAX_USERS:
            raise HTTPException(429, "Chunk storage user limit reached.")
        _chunk_directory(user_dir)
        chunk_dir = user_dir / session
        if not chunk_dir.exists() and sum(1 for _ in user_dir.iterdir()) >= CHUNK_MAX_SESSIONS:
            raise HTTPException(429, "Chunk session limit reached.")
        _chunk_directory(chunk_dir)
        metadata = {
            "user": str(user.id), "filename": filename, "content_type": file.content_type,
            "count": count, "folder": folderId, "visibility": visibility,
        }
        manifest = chunk_dir / "session.json"
        entries = list(chunk_dir.iterdir())
        allowed = {"session.json", *(f"{i:08d}.part" for i in range(count))}
        if any(entry.is_symlink() or not entry.is_file() or entry.name not in allowed for entry in entries):
            raise HTTPException(409, "Unexpected chunk session contents.")
        if manifest.exists():
            try:
                state = json.loads(manifest.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                raise HTTPException(409, "Invalid chunk session metadata.") from None
            if not isinstance(state, dict) or state.get("metadata") != metadata:
                raise HTTPException(409, "Chunk session metadata mismatch.")
            chunks = state.get("chunks")
            if (
                not isinstance(chunks, dict)
                or not set(chunks).issubset({str(i) for i in range(count)})
                or any(
                    not isinstance(part, dict)
                    or type(part.get("size")) is not int
                    or not 0 <= part["size"] <= CHUNK_MAX_BYTES
                    or not isinstance(part.get("sha256"), str)
                    or not re.fullmatch(r"[0-9a-f]{64}", part["sha256"])
                    for part in chunks.values()
                )
                or sum(part["size"] for part in chunks.values()) > CHUNK_TOTAL_BYTES
            ):
                raise HTTPException(409, "Invalid chunk session metadata.")
            present = {entry.name for entry in entries} - {"session.json"}
            recorded = {f"{int(i):08d}.part" for i in chunks}
            if ("result" not in state and present != recorded) or ("result" in state and len(chunks) != count):
                raise HTTPException(409, "Incomplete chunk set.")
        else:
            if entries:
                raise HTTPException(409, "Chunk session metadata is missing.")
            state = {"metadata": metadata, "chunks": {}}
        digest = hashlib.sha256(content).hexdigest()
        identity = {"sha256": digest, "size": len(content)}
        previous = state["chunks"].get(str(index))
        chunk_path = chunk_dir / f"{index:08d}.part"
        if previous is not None:
            if previous != identity or ("result" not in state and chunk_path.read_bytes() != content):
                raise HTTPException(409, "Conflicting duplicate chunk.")
        else:
            if sum(part["size"] for part in state["chunks"].values()) + len(content) > CHUNK_TOTAL_BYTES:
                raise HTTPException(413, "Assembled upload is too large.")
            with chunk_path.open("xb") as target:
                target.write(content)
            state["chunks"][str(index)] = identity
        if "result" in state:
            return state["result"]
        _chunk_manifest(manifest, state)
        if len(state["chunks"]) != count:
            return {"complete": False, "progress": int(len(state["chunks"]) / count * 100)}
        expected = {f"{i:08d}.part" for i in range(count)}
        if {entry.name for entry in chunk_dir.iterdir()} != expected | {"session.json"}:
            raise HTTPException(409, "Incomplete chunk set.")
        merged_path = chunk_dir / "assembled.upload"
        try:
            with merged_path.open("xb") as target:
                for i in range(count):
                    part = (chunk_dir / f"{i:08d}.part").read_bytes()
                    if {"sha256": hashlib.sha256(part).hexdigest(), "size": len(part)} != state["chunks"][str(i)]:
                        raise HTTPException(409, "Chunk content mismatch.")
                    target.write(part)

            class MergedUpload:
                async def read(self) -> bytes:
                    return merged_path.read_bytes()

            upload = MergedUpload()
            upload.filename = filename
            upload.content_type = file.content_type
            media_file = await rv_media.upload_file(
                db, upload, folder_id=folderId, user_id=user.id, visibility=visibility,
            )
            result = {"complete": True, "progress": 100, "file": rv_media.file_payload(media_file)}
            state["result"] = result
            _chunk_manifest(manifest, state)
            for name in expected:
                (chunk_dir / name).unlink()
            return result
        except (MediaValidationError, StorageProviderError) as exception:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exception)) from exception
        finally:
            if merged_path.is_file() and not merged_path.is_symlink():
                merged_path.unlink()
    finally:
        lock.rmdir()


@router.get("/media/files/{file_id}")
async def get_file(file_id: str, db: AsyncSession = Depends(get_db)):
    await ensure_admin_user(db)
    try:
        media_file = await rv_media.get_file(db, file_id)
        return rv_media.file_payload(media_file)
    except MediaValidationError as exception:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exception)) from exception


@router.patch("/media/files/{file_id}")
async def update_file(file_id: str, data: FileUpdate, db: AsyncSession = Depends(get_db)):
    await ensure_admin_user(db)
    try:
        media_file = await rv_media.update_file(db, file_id, data.name, data.alt, data.visibility, data.folderId)
        return BaseHttpResponse.make().set_data(rv_media.file_payload(media_file)).with_updated_success_message().to_dict()
    except MediaValidationError as exception:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exception)) from exception


@router.delete("/media/files/{file_id}")
async def delete_file(file_id: str, force: bool = False, db: AsyncSession = Depends(get_db)):
    await ensure_admin_user(db)
    try:
        await rv_media.delete_file(db, file_id, force=force)
        return BaseHttpResponse.make().with_deleted_success_message().to_dict()
    except (MediaValidationError, StorageProviderError) as exception:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exception)) from exception


@router.post("/media/files/{file_id}/restore")
async def restore_file(file_id: str, db: AsyncSession = Depends(get_db)):
    await ensure_admin_user(db)
    try:
        media_file = await rv_media.restore_file(db, file_id)
        return BaseHttpResponse.make().set_data(rv_media.file_payload(media_file)).set_message("Media restored successfully").to_dict()
    except MediaValidationError as exception:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exception)) from exception


@router.post("/media/files/{file_id}/copy", status_code=status.HTTP_201_CREATED)
async def copy_file(file_id: str, db: AsyncSession = Depends(get_db)):
    user = await ensure_admin_user(db)
    try:
        media_file = await rv_media.copy_file(db, file_id, user.id)
        return BaseHttpResponse.make().set_data(rv_media.file_payload(media_file)).set_message("Media copied successfully").to_dict()
    except (MediaValidationError, StorageProviderError) as exception:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exception)) from exception


@router.post("/media/files/{file_id}/favorite")
async def favorite_file(file_id: str, data: FavoriteUpdate, db: AsyncSession = Depends(get_db)):
    user = await ensure_admin_user(db)
    await rv_media.favorite(db, file_id, user.id, data.value)
    return BaseHttpResponse.make().with_updated_success_message().to_dict()


@router.post("/media/files/{file_id}/thumbnails/regenerate")
async def regenerate_file_thumbnails(file_id: str, db: AsyncSession = Depends(get_db)):
    await ensure_admin_user(db)
    try:
        media_file = await rv_media.regenerate_thumbnails(db, file_id)
        return BaseHttpResponse.make().set_data(rv_media.file_payload(media_file)).set_message("Thumbnails regenerated successfully").to_dict()
    except (MediaValidationError, StorageProviderError) as exception:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exception)) from exception


@router.get("/media/files/{file_id}/url")
async def get_file_url(file_id: str, size: str | None = Query(default=None), db: AsyncSession = Depends(get_db)):
    await ensure_admin_user(db)
    try:
        media_file = await rv_media.get_file(db, file_id)
        return {"url": rv_media.image_url(media_file, size), "size": size}
    except MediaValidationError as exception:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exception)) from exception


@router.get("/media/files/{file_id}/download")
async def download_file(file_id: str, db: AsyncSession = Depends(get_db)):
    await ensure_admin_user(db)
    try:
        media_file = await rv_media.get_file(db, file_id)
        values = await setting_store.all(db, flat=True)
        provider = storage_manager.provider(media_file.provider, values)
        local_path = provider.public_path(media_file.url)
        if local_path and local_path.exists():
            return FileResponse(local_path, media_type=media_file.mime_type, filename=posixpath.basename(media_file.url))
        return RedirectResponse(provider.url(media_file.url))
    except (MediaValidationError, StorageProviderError) as exception:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exception)) from exception
