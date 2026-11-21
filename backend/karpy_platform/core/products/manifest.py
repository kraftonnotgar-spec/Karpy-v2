"""Find and validate a product folder (``<PRODUCTS_DIR>/<PRODUCT>/product.json``).

The neutral core knows no product by name: the folder is chosen by the ``PRODUCT``
setting (env) or an explicit argument, and everything product-specific is read from
that folder's JSON files. See ``docs/REUSE.md``.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

PRODUCT_NAME_PATTERN = re.compile(r"^[a-z0-9_][a-z0-9_-]{0,63}$")
MANIFEST_FILE = "product.json"
SEED_DIR = "seed"
DEMO_DIR = "demo"


class ProductSeedError(RuntimeError):
    """A product folder is missing, invalid, or a command is not allowed here."""


class DemoConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    email_domain: str = Field(pattern=r"^[a-z0-9-]+(\.[a-z0-9-]+)+$")
    phone_range: str | None = Field(default=None, pattern=r"^\+\d{6,15}-\+\d{6,15}$")
    files: list[str] = Field(default_factory=list)

    def phone_bounds(self) -> tuple[int, int] | None:
        if not self.phone_range:
            return None
        low, high = (int(part.lstrip("+")) for part in self.phone_range.split("-"))
        return low, high


class ProductManifest(BaseModel):
    model_config = ConfigDict(extra="allow")

    key: str = Field(pattern=PRODUCT_NAME_PATTERN.pattern)
    name: str
    seed_version: int = Field(ge=1)
    default_locale: str = Field(pattern=r"^[a-z]{2}(-[A-Z]{2})?$")
    locales: list[str] = Field(min_length=1)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    timezone: str
    country: str | None = Field(default=None, pattern=r"^[A-Z]{2}$")
    enabled_plugins: list[str] = Field(default_factory=list)
    seed: list[str] = Field(default_factory=list)
    demo: DemoConfig | None = None

    @field_validator("locales")
    @classmethod
    def _dedupe_locales(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(value))


@dataclass(frozen=True)
class Product:
    name: str
    path: Path
    manifest: ProductManifest

    @property
    def seed_dir(self) -> Path:
        return self.path / SEED_DIR

    @property
    def demo_dir(self) -> Path:
        return self.path / DEMO_DIR

    def seed_files(self) -> list[Path]:
        return [self._file(self.seed_dir, name) for name in self.manifest.seed]

    def demo_files(self) -> list[Path]:
        if self.manifest.demo is None:
            return []
        return [self._file(self.demo_dir, name) for name in self.manifest.demo.files]

    @staticmethod
    def _file(folder: Path, name: str) -> Path:
        path = (folder / name).resolve()
        if folder.resolve() not in path.parents:
            raise ProductSeedError(f"{name!r} is outside {folder}")
        if not path.is_file():
            raise ProductSeedError(f"Seed file not found: {path}")
        return path


def read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ProductSeedError(f"{path}: invalid JSON ({exc})") from exc
    if not isinstance(data, dict):
        raise ProductSeedError(f"{path}: the top level must be an object")
    return data


def product_name(explicit: str | None = None) -> str:
    """The product to use: the explicit name, else ``PRODUCT``. Fails clearly when unset."""
    from app.config import settings

    name = (explicit or settings.PRODUCT or os.environ.get("PRODUCT") or "").strip()
    if not name:
        raise ProductSeedError(
            "PRODUCT is not set. Set the PRODUCT environment variable (a folder under "
            "backend/products) or pass --product."
        )
    if not PRODUCT_NAME_PATTERN.match(name):
        raise ProductSeedError(f"Invalid product name {name!r}.")
    return name


def load_product(name: str | None = None, *, root: Path | None = None) -> Product:
    from app.config import settings

    product = product_name(name)
    folder = Path(root or settings.PRODUCTS_DIR) / product
    manifest_path = folder / MANIFEST_FILE
    if not manifest_path.is_file():
        raise ProductSeedError(f"Product {product!r} not found: {manifest_path} does not exist.")
    try:
        manifest = ProductManifest.model_validate(read_json(manifest_path))
    except ValidationError as exc:
        raise ProductSeedError(f"{manifest_path}: {exc}") from exc
    if manifest.default_locale not in manifest.locales:
        raise ProductSeedError(f"{manifest_path}: default_locale must be one of locales")
    return Product(name=product, path=folder, manifest=manifest)
