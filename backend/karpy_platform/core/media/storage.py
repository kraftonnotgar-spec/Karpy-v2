from __future__ import annotations

import os
import posixpath
import urllib.request
from abc import ABC, abstractmethod
from importlib.util import find_spec
from pathlib import Path
from typing import Any

from app.config import settings
from karpy_platform.core.media.config import get_media_config
from karpy_platform.core.media.settings import media_driver, setting_value, truthy


class StorageProviderError(RuntimeError):
    def __init__(self, message, *, code="storage_unavailable"):
        super().__init__(message)
        self.code = code


class StorageProvider(ABC):
    name: str

    @abstractmethod
    def save(self, path: str, content: bytes, visibility: str = "public") -> str:
        raise NotImplementedError

    @abstractmethod
    def delete(self, path: str) -> bool:
        raise NotImplementedError

    @abstractmethod
    def exists(self, path: str) -> bool:
        raise NotImplementedError

    @abstractmethod
    def url(self, path: str) -> str:
        raise NotImplementedError

    def make_directory(self, path: str) -> None:
        return None

    def delete_directory(self, path: str) -> bool:
        return False

    def public_path(self, path: str) -> Path | None:
        return None

    def configured(self) -> bool:
        return True


def clean_storage_path(path: str) -> str:
    normalized = posixpath.normpath(path.replace("\\", "/")).lstrip("/")
    if normalized == ".":
        return ""
    if normalized.startswith("../") or normalized == "..":
        raise StorageProviderError("Invalid media path.")
    return normalized


class LocalStorageProvider(StorageProvider):
    name = "local"

    def __init__(self, root: Path | None = None, url_prefix: str | None = None) -> None:
        self.root = Path(root or settings.MEDIA_DIR).resolve()
        self.url_prefix = (url_prefix or get_media_config("url_prefix", "/media")).rstrip("/")
        # Loading this module must never fail in a worker that cannot write media (for example the
        # developer policy publisher): the folder is needed only when a file is actually written.
        try:
            self.root.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass

    def _absolute(self, path: str) -> Path:
        cleaned = clean_storage_path(path)
        absolute = (self.root / cleaned).resolve()
        if self.root != absolute and self.root not in absolute.parents:
            raise StorageProviderError("Media path escapes the storage root.")
        return absolute

    def save(self, path: str, content: bytes, visibility: str = "public") -> str:
        absolute = self._absolute(path)
        absolute.parent.mkdir(parents=True, exist_ok=True)
        absolute.write_bytes(content)
        return clean_storage_path(path)

    def delete(self, path: str) -> bool:
        absolute = self._absolute(path)
        if absolute.exists() and absolute.is_file():
            absolute.unlink()
            return True
        return False

    def exists(self, path: str) -> bool:
        return self._absolute(path).exists()

    def url(self, path: str) -> str:
        return f"{self.url_prefix}/{clean_storage_path(path)}"

    def make_directory(self, path: str) -> None:
        self._absolute(path).mkdir(parents=True, exist_ok=True)

    def delete_directory(self, path: str) -> bool:
        absolute = self._absolute(path)
        if not absolute.exists() or not absolute.is_dir():
            return False
        for child in sorted(absolute.rglob("*"), reverse=True):
            if child.is_file():
                child.unlink()
            elif child.is_dir():
                child.rmdir()
        absolute.rmdir()
        return True

    def public_path(self, path: str) -> Path | None:
        return self._absolute(path)


class BunnyCDNStorageProvider(StorageProvider):
    name = "bunnycdn"

    def __init__(
        self,
        storage_zone: str | None = None,
        access_key: str | None = None,
        region: str | None = None,
        pull_zone_url: str | None = None,
    ) -> None:
        self.storage_zone = storage_zone or os.getenv("BUNNY_STORAGE_ZONE", "")
        self.access_key = access_key or os.getenv("BUNNY_ACCESS_KEY", "")
        self.region = region or os.getenv("BUNNY_REGION", "")
        self.pull_zone_url = (pull_zone_url or os.getenv("BUNNY_PULL_ZONE_URL", "")).rstrip("/")

    def configured(self) -> bool:
        return bool(self.storage_zone and self.access_key and self.pull_zone_url)

    def _endpoint(self, path: str) -> str:
        if not self.configured():
            raise StorageProviderError("BunnyCDN storage is not configured.")
        host = "storage.bunnycdn.com" if not self.region else f"{self.region}.storage.bunnycdn.com"
        return f"https://{host}/{self.storage_zone}/{clean_storage_path(path)}"

    def save(self, path: str, content: bytes, visibility: str = "public") -> str:
        request = urllib.request.Request(
            self._endpoint(path),
            data=content,
            method="PUT",
            headers={"AccessKey": self.access_key, "Content-Type": "application/octet-stream"},
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            if response.status not in {200, 201}:
                raise StorageProviderError(f"BunnyCDN upload failed with status {response.status}.")
        return clean_storage_path(path)

    def delete(self, path: str) -> bool:
        request = urllib.request.Request(self._endpoint(path), method="DELETE", headers={"AccessKey": self.access_key})
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status in {200, 204}

    def exists(self, path: str) -> bool:
        request = urllib.request.Request(self._endpoint(path), method="HEAD", headers={"AccessKey": self.access_key})
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                return response.status == 200
        except Exception:
            return False

    def url(self, path: str) -> str:
        if not self.pull_zone_url:
            raise StorageProviderError("BunnyCDN pull zone URL is not configured.")
        return f"{self.pull_zone_url}/{clean_storage_path(path)}"


class S3CompatibleStorageProvider(StorageProvider):
    def __init__(
        self,
        name: str,
        access_key: str,
        secret_key: str,
        bucket: str,
        region: str = "",
        public_url: str = "",
        endpoint_url: str = "",
        root: str = "",
        use_path_style_endpoint: bool = False,
    ) -> None:
        self.name = name
        self.access_key = access_key
        self.secret_key = secret_key
        self.bucket = bucket
        self.region = region
        self.public_url = public_url.rstrip("/")
        self.endpoint_url = endpoint_url.rstrip("/")
        self.root = clean_storage_path(root) if root else ""
        self.use_path_style_endpoint = use_path_style_endpoint

    def configured(self) -> bool:
        return bool(self.access_key and self.secret_key and self.bucket and (self.public_url or self.endpoint_url))

    def _client(self):
        if find_spec("boto3") is None:
            raise StorageProviderError("Install boto3 to use this S3-compatible media driver.")
        import boto3
        from botocore.config import Config

        config = Config(s3={"addressing_style": "path" if self.use_path_style_endpoint else "auto"})
        return boto3.client(
            "s3",
            aws_access_key_id=self.access_key,
            aws_secret_access_key=self.secret_key,
            region_name=self.region or None,
            endpoint_url=self.endpoint_url or None,
            config=config,
        )

    def _key(self, path: str) -> str:
        path = clean_storage_path(path)
        return clean_storage_path(posixpath.join(self.root, path)) if self.root else path

    def save(self, path: str, content: bytes, visibility: str = "public") -> str:
        if not self.configured():
            raise StorageProviderError(f"{self.name} storage is not configured.")
        key = self._key(path)
        extra_args = {"ACL": "public-read"} if visibility == "public" else {}
        self._client().put_object(Bucket=self.bucket, Key=key, Body=content, **extra_args)
        return clean_storage_path(path)

    def delete(self, path: str) -> bool:
        if not self.configured():
            return False
        self._client().delete_object(Bucket=self.bucket, Key=self._key(path))
        return True

    def exists(self, path: str) -> bool:
        if not self.configured() or find_spec("boto3") is None:
            return False
        try:
            self._client().head_object(Bucket=self.bucket, Key=self._key(path))
            return True
        except Exception:
            return False

    def url(self, path: str) -> str:
        cleaned = self._key(path)
        if self.public_url:
            return f"{self.public_url}/{cleaned}"
        if self.endpoint_url:
            return f"{self.endpoint_url.rstrip('/')}/{self.bucket}/{cleaned}"
        return f"https://{self.bucket}.s3.{self.region}.amazonaws.com/{cleaned}"


class UnconfiguredStorageProvider(StorageProvider):
    def __init__(self, name: str, message: str) -> None:
        self.name = name
        self.message = message

    def configured(self) -> bool:
        return False

    def save(self, path: str, content: bytes, visibility: str = "public") -> str:
        raise StorageProviderError(self.message)

    def delete(self, path: str) -> bool:
        raise StorageProviderError(self.message)

    def exists(self, path: str) -> bool:
        return False

    def url(self, path: str) -> str:
        raise StorageProviderError(self.message)


class StorageManager:
    def __init__(self) -> None:
        self._providers: dict[str, StorageProvider] = {}
        self.default_driver = os.getenv("MEDIA_STORAGE_DRIVER", get_media_config("driver", "local"))

    def register(self, provider: StorageProvider) -> None:
        self._providers[provider.name] = provider

    def provider(self, name: str | None = None, settings_values: dict[str, Any] | None = None) -> StorageProvider:
        if settings_values is not None:
            return self._provider_from_settings(name, settings_values)

        driver = name or self.default_driver
        provider = self._providers.get(driver)
        if not provider:
            raise StorageProviderError(f'Media storage provider "{driver}" is not registered.')
        return provider

    def providers(self, settings_values: dict[str, Any] | None = None) -> list[dict]:
        if settings_values is not None:
            current = media_driver(settings_values)
            return [
                {
                    "name": driver,
                    "configured": self._provider_from_settings(driver, settings_values).configured(),
                    "default": driver == current,
                }
                for driver in ["local", "s3", "r2", "do_spaces", "wasabi", "bunnycdn", "backblaze"]
            ]
        return [
            {"name": name, "configured": provider.configured(), "default": name == self.default_driver}
            for name, provider in sorted(self._providers.items())
        ]

    def _provider_from_settings(self, name: str | None, values: dict[str, Any]) -> StorageProvider:
        driver = name or media_driver(values)
        if driver == "local":
            return LocalStorageProvider()
        if driver == "bunnycdn":
            hostname = str(setting_value(values, "media_bunnycdn_hostname", "")).strip()
            return BunnyCDNStorageProvider(
                storage_zone=str(setting_value(values, "media_bunnycdn_zone", "")),
                access_key=str(setting_value(values, "media_bunnycdn_key", "")),
                region=str(setting_value(values, "media_bunnycdn_region", "")),
                pull_zone_url=f"https://{hostname}" if hostname and not hostname.startswith(("http://", "https://")) else hostname,
            )
        if driver == "s3":
            return S3CompatibleStorageProvider(
                "s3",
                access_key=str(setting_value(values, "media_aws_access_key_id", "")),
                secret_key=str(setting_value(values, "media_aws_secret_key", "")),
                bucket=str(setting_value(values, "media_aws_bucket", "")),
                region=str(setting_value(values, "media_aws_default_region", "")),
                public_url=str(setting_value(values, "media_aws_url", "")),
                endpoint_url=str(setting_value(values, "media_aws_endpoint", "")),
                root=str(setting_value(values, "media_s3_path", "")),
                use_path_style_endpoint=truthy(setting_value(values, "media_aws_use_path_style_endpoint", "0")),
            )
        if driver == "r2":
            return S3CompatibleStorageProvider(
                "r2",
                access_key=str(setting_value(values, "media_r2_access_key_id", "")),
                secret_key=str(setting_value(values, "media_r2_secret_key", "")),
                bucket=str(setting_value(values, "media_r2_bucket", "")),
                endpoint_url=str(setting_value(values, "media_r2_endpoint", "")),
                public_url=str(setting_value(values, "media_r2_url", "")),
                use_path_style_endpoint=truthy(setting_value(values, "media_r2_use_path_style_endpoint", "1")),
            )
        if driver == "do_spaces":
            cdn_domain = str(setting_value(values, "media_do_spaces_cdn_custom_domain", "")).strip()
            endpoint = str(setting_value(values, "media_do_spaces_endpoint", ""))
            return S3CompatibleStorageProvider(
                "do_spaces",
                access_key=str(setting_value(values, "media_do_spaces_access_key_id", "")),
                secret_key=str(setting_value(values, "media_do_spaces_secret_key", "")),
                bucket=str(setting_value(values, "media_do_spaces_bucket", "")),
                region=str(setting_value(values, "media_do_spaces_default_region", "")),
                endpoint_url=endpoint,
                public_url=cdn_domain if truthy(setting_value(values, "media_do_spaces_cdn_enabled", "0")) else endpoint,
                use_path_style_endpoint=truthy(setting_value(values, "media_do_spaces_use_path_style_endpoint", "0")),
            )
        if driver == "wasabi":
            region = str(setting_value(values, "media_wasabi_default_region", ""))
            endpoint = f"https://s3.{region}.wasabisys.com" if region else ""
            return S3CompatibleStorageProvider(
                "wasabi",
                access_key=str(setting_value(values, "media_wasabi_access_key_id", "")),
                secret_key=str(setting_value(values, "media_wasabi_secret_key", "")),
                bucket=str(setting_value(values, "media_wasabi_bucket", "")),
                region=region,
                endpoint_url=endpoint,
                public_url=str(setting_value(values, "media_wasabi_url", "")),
                root=str(setting_value(values, "media_wasabi_root", "")),
            )
        if driver == "backblaze":
            cdn_domain = str(setting_value(values, "media_backblaze_cdn_custom_domain", "")).strip()
            public_url = cdn_domain if truthy(setting_value(values, "media_backblaze_cdn_enabled", "0")) else str(setting_value(values, "media_backblaze_url", ""))
            return S3CompatibleStorageProvider(
                "backblaze",
                access_key=str(setting_value(values, "media_backblaze_access_key_id", "")),
                secret_key=str(setting_value(values, "media_backblaze_secret_key", "")),
                bucket=str(setting_value(values, "media_backblaze_bucket", "")),
                region=str(setting_value(values, "media_backblaze_default_region", "")),
                endpoint_url=str(setting_value(values, "media_backblaze_endpoint", "")),
                public_url=public_url,
                use_path_style_endpoint=truthy(setting_value(values, "media_backblaze_use_path_style_endpoint", "1")),
            )
        return UnconfiguredStorageProvider(driver, f'Media storage provider "{driver}" is not registered.')


storage_manager = StorageManager()
storage_manager.register(LocalStorageProvider())
storage_manager.register(BunnyCDNStorageProvider())
storage_manager.register(UnconfiguredStorageProvider("s3", "S3 storage needs a boto3-backed provider registration."))
storage_manager.register(UnconfiguredStorageProvider("r2", "Cloudflare R2 storage needs settings-backed provider configuration."))
storage_manager.register(UnconfiguredStorageProvider("do_spaces", "DigitalOcean Spaces storage needs settings-backed provider configuration."))
storage_manager.register(UnconfiguredStorageProvider("wasabi", "Wasabi storage needs settings-backed provider configuration."))
storage_manager.register(UnconfiguredStorageProvider("backblaze", "Backblaze B2 storage needs settings-backed provider configuration."))
