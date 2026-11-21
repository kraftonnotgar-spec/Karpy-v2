"""Product layer loader: seed and demo data from ``backend/products/<PRODUCT>/``.

The neutral core stays product-agnostic: the product folder is chosen by the ``PRODUCT``
env setting (or ``--product``) and all values come from its JSON files. See ``docs/REUSE.md``.

Console: ``python -m karpy_platform product:seed | demo:seed | demo:clear``.
"""

from __future__ import annotations

from .demo import clear_demo, ensure_demo_allowed, register_demo_loader, seed_demo
from .manifest import (
    Product,
    ProductManifest,
    ProductSeedError,
    load_product,
    product_name,
)
from .seed import SeedReport, register_seed_loader, seed_product

__all__ = [
    "Product",
    "ProductManifest",
    "ProductSeedError",
    "SeedReport",
    "clear_demo",
    "ensure_demo_allowed",
    "load_product",
    "product_name",
    "register_demo_loader",
    "register_seed_loader",
    "seed_demo",
    "seed_product",
    "run_product_seed",
    "run_demo_seed",
    "run_demo_clear",
]


async def run_product_seed(session_factory, product: Product) -> SeedReport:
    async with session_factory() as session:
        report = await seed_product(session, product)
        await session.commit()
        return report


async def run_demo_seed(
    session_factory, product: Product, *, password: str | None = None
) -> tuple[SeedReport, SeedReport]:
    """Seed, then demo, each in its own transaction. Refused in production before any write."""
    ensure_demo_allowed()
    seeded = await run_product_seed(session_factory, product)
    async with session_factory() as session:
        report = await seed_demo(session, product, password=password)
        await session.commit()
    return seeded, report


async def run_demo_clear(session_factory, product: Product) -> SeedReport:
    """Allowed in every environment: it only removes demo rows."""
    async with session_factory() as session:
        report = await clear_demo(session, product)
        await session.commit()
        return report
