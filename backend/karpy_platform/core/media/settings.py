from __future__ import annotations

from typing import Any

from app.config import settings


TRUE_VALUES = {True, 1, "1", "true", "yes", "on"}


DRIVER_LABELS: dict[str, str] = {
    "local": "Local disk",
    "s3": "Amazon S3",
    "r2": "Cloudflare R2",
    "do_spaces": "DigitalOcean Spaces",
    "wasabi": "Wasabi",
    "bunnycdn": "BunnyCDN",
    "backblaze": "Backblaze B2",
}


DEFAULT_THUMBNAIL_SIZES: dict[str, tuple[int, int, str]] = {
    "thumb": (150, 150, "Thumb"),
    "featured": (565, 375, "Featured"),
    "medium": (540, 360, "Medium"),
    "small": (375, 250, "Small"),
    "size_270x180": (270, 180, "270X180"),
}


DRIVER_REQUIRED_FIELDS: dict[str, list[str]] = {
    "local": [],
    "s3": [
        "media_aws_access_key_id",
        "media_aws_secret_key",
        "media_aws_default_region",
        "media_aws_bucket",
        "media_aws_url",
    ],
    "r2": [
        "media_r2_access_key_id",
        "media_r2_secret_key",
        "media_r2_bucket",
        "media_r2_endpoint",
        "media_r2_url",
    ],
    "do_spaces": [
        "media_do_spaces_access_key_id",
        "media_do_spaces_secret_key",
        "media_do_spaces_default_region",
        "media_do_spaces_bucket",
        "media_do_spaces_endpoint",
    ],
    "wasabi": [
        "media_wasabi_access_key_id",
        "media_wasabi_secret_key",
        "media_wasabi_default_region",
        "media_wasabi_bucket",
    ],
    "bunnycdn": [
        "media_bunnycdn_zone",
        "media_bunnycdn_hostname",
        "media_bunnycdn_key",
    ],
    "backblaze": [
        "media_backblaze_access_key_id",
        "media_backblaze_secret_key",
        "media_backblaze_default_region",
        "media_backblaze_bucket",
        "media_backblaze_endpoint",
    ],
}


def truthy(value: Any) -> bool:
    return value in TRUE_VALUES or str(value).strip().lower() in TRUE_VALUES


def setting_value(values: dict[str, Any], key: str, default: Any = "") -> Any:
    value = values.get(key)
    return default if value is None or value == "" else value


def media_driver(values: dict[str, Any]) -> str:
    driver = str(setting_value(values, "media_driver", "local")).strip() or "local"
    return driver if driver in DRIVER_LABELS else "local"


def media_max_upload_size_mb(values: dict[str, Any]) -> float:
    try:
        return float(setting_value(values, "max_upload_filesize", settings.MAX_UPLOAD_SIZE_MB))
    except (TypeError, ValueError):
        return float(settings.MAX_UPLOAD_SIZE_MB)


def media_image_quality(values: dict[str, Any]) -> int:
    try:
        return max(1, min(100, int(setting_value(values, "media_image_quality", 75))))
    except (TypeError, ValueError):
        return 75


def media_thumbnail_sizes(values: dict[str, Any]) -> dict[str, dict[str, Any]]:
    if not truthy(setting_value(values, "media_enable_thumbnail_sizes", "1")):
        return {}

    sizes: dict[str, dict[str, Any]] = {}
    for key, (default_width, default_height, label) in DEFAULT_THUMBNAIL_SIZES.items():
        width = _safe_int(setting_value(values, f"media_sizes_{key}_width", default_width), default_width)
        height = _safe_int(setting_value(values, f"media_sizes_{key}_height", default_height), default_height)
        if width <= 0 and height <= 0:
            continue
        sizes[key] = {
            "width": width,
            "height": height,
            "mode": "cover" if width > 0 and height > 0 else "width" if width > 0 else "height",
            "label": label,
        }
    return sizes


def media_upload_prefix(values: dict[str, Any]) -> str:
    from karpy_platform.core.media.storage import clean_storage_path

    if not truthy(setting_value(values, "media_customize_upload_path", "0")):
        return ""
    return clean_storage_path(str(setting_value(values, "media_upload_path", "storage")).strip("/"))


def media_settings_payload(values: dict[str, Any]) -> dict[str, Any]:
    current_driver = media_driver(values)
    missing = [
        key
        for key in DRIVER_REQUIRED_FIELDS.get(current_driver, [])
        if not str(setting_value(values, key, "")).strip()
    ]
    return {
        "drivers": [
            {
                "value": value,
                "label": label,
                "configured": not [
                    key for key in DRIVER_REQUIRED_FIELDS.get(value, []) if not str(setting_value(values, key, "")).strip()
                ],
                "active": value == current_driver,
                "requiredFields": DRIVER_REQUIRED_FIELDS.get(value, []),
            }
            for value, label in DRIVER_LABELS.items()
        ],
        "currentDriver": current_driver,
        "driverConfigured": not missing,
        "missingDriverFields": missing,
        "thumbnailSizes": media_thumbnail_sizes(values),
        "maxUploadSizeMb": media_max_upload_size_mb(values),
        "imageQuality": media_image_quality(values),
        "uploadPrefix": media_upload_prefix(values),
    }


def validate_media_settings(values: dict[str, Any]) -> dict[str, str]:
    errors: dict[str, str] = {}
    if "media_driver" in values:
        driver = media_driver(values)
        for key in DRIVER_REQUIRED_FIELDS.get(driver, []):
            if key in values and not str(values.get(key) or "").strip():
                errors[key] = "This setting is required for the selected media driver."

    numeric_min = {
        "max_upload_filesize": 0,
        "media_chunk_size": 0,
        "media_max_file_size": 0,
        "media_image_quality": 1,
        "media_image_max_width": 200,
        "media_image_max_height": 200,
        "media_watermark_size": 0,
        "media_watermark_opacity": 0,
        "media_watermark_position_x": 0,
        "media_watermark_position_y": 0,
    }
    for key, minimum in numeric_min.items():
        if key not in values or values.get(key) in {None, ""}:
            continue
        try:
            value = float(values[key])
        except (TypeError, ValueError):
            errors[key] = "Must be a number."
            continue
        if value < minimum:
            errors[key] = f"Must be at least {minimum}."
        if key == "max_upload_filesize" and value > settings.MAX_UPLOAD_SIZE_MB:
            errors[key] = f"Must be at most {settings.MAX_UPLOAD_SIZE_MB}."
        if key in {"media_image_quality", "media_watermark_opacity"} and value > 100:
            errors[key] = "Must be at most 100."

    crop = values.get("media_thumbnail_crop_position")
    if crop and crop not in {"left", "right", "top", "bottom", "center"}:
        errors["media_thumbnail_crop_position"] = "Invalid option."
    position = values.get("media_watermark_position")
    if position and position not in {"top-left", "top-right", "bottom-left", "bottom-right", "center"}:
        errors["media_watermark_position"] = "Invalid option."

    for key in DEFAULT_THUMBNAIL_SIZES:
        for suffix in ("width", "height"):
            field = f"media_sizes_{key}_{suffix}"
            if field not in values:
                continue
            try:
                if float(values[field]) < 0:
                    errors[field] = "Must be at least 0."
            except (TypeError, ValueError):
                errors[field] = "Must be a number."

    return errors


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
