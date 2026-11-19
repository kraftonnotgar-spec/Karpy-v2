from __future__ import annotations

from app.config import settings


MEDIA_CONFIG: dict = {
    "driver": "local",
    "directory": settings.MEDIA_DIR,
    "url_prefix": "/media",
    "max_upload_size_mb": settings.MAX_UPLOAD_SIZE_MB,
    "allowed_extensions": [
        "jpg",
        "jpeg",
        "png",
        "gif",
        "txt",
        "docx",
        "zip",
        "mp3",
        "bmp",
        "csv",
        "xls",
        "xlsx",
        "ppt",
        "pptx",
        "pdf",
        "mp4",
        "m4v",
        "doc",
        "mpga",
        "wav",
        "webp",
        "webm",
        "mov",
        "jfif",
        "avif",
        "rar",
        "svg",
    ],
    "mime_types": {
        "image": [
            "image/jpeg",
            "image/png",
            "image/gif",
            "image/bmp",
            "image/webp",
            "image/svg+xml",
            "image/avif",
        ],
        "video": ["video/mp4", "video/x-m4v", "video/webm", "video/quicktime"],
        "document": [
            "text/plain",
            "text/csv",
            "application/pdf",
            "application/msword",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "application/vnd.ms-excel",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "application/vnd.ms-powerpoint",
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ],
        "zip": ["application/zip", "application/x-rar-compressed", "application/vnd.rar"],
        "audio": ["audio/mpeg", "audio/mp4", "audio/wav", "audio/x-wav"],
    },
    "thumbnails": {
        "enabled": True,
        "sizes": {
            "thumb": {"width": 150, "height": 150, "mode": "cover"},
            "small": {"width": 300, "height": "auto", "mode": "width"},
            "medium": {"width": 600, "height": "auto", "mode": "width"},
            "large": {"width": 1024, "height": "auto", "mode": "width"},
            "xlarge": {"width": 1600, "height": "auto", "mode": "width"},
        },
        "quality": 92,
        "supported_mime_types": ["image/jpeg", "image/png", "image/gif", "image/webp", "image/avif"],
    },
    "folder_colors": [
        "#4285f4",
        "#34a853",
        "#fbbc04",
        "#ea4335",
        "#7b61ff",
        "#00acc1",
        "#8d6e63",
        "#607d8b",
    ],
    "visibility": ["public", "private"],
    "chunk": {
        "enabled": True,
        "storage": "chunks",
        "max_file_size_mb": 512,
        "chunk_size_mb": 2,
    },
}


def get_media_config(key: str | None = None, default=None):
    if key is None:
        return MEDIA_CONFIG

    value = MEDIA_CONFIG
    for segment in key.split("."):
        if not isinstance(value, dict) or segment not in value:
            return default
        value = value[segment]
    return value
