"""Botble-style console commands for KARPy."""

from __future__ import annotations

import argparse
import sys

from karpy_platform.core.console.generators import CrudGenerator, PluginGenerator
from karpy_platform.packages.plugin_management.service import plugin_service


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="karpy",
        description="KARPy CMS console commands.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    plugin_create = subparsers.add_parser(
        "plugin:create",
        help="Create a Botble-style KARPy plugin scaffold.",
    )
    plugin_create.add_argument("name", help="Plugin name, e.g. Speed or Payment Gateway.")
    plugin_create.add_argument("--id", dest="plugin_id", help="Marketplace id in vendor/name format, e.g. krafton/speed.")
    plugin_create.add_argument("--author", help="Plugin author or vendor name.")
    plugin_create.add_argument("--version", default="1.0.0", help="Semantic version. Default: 1.0.0.")
    plugin_create.add_argument("--description", help="Short plugin summary for the admin panel and marketplace.")
    plugin_create.add_argument("--namespace", help="Python namespace. Defaults to karpy_platform.plugins.<folder>.")
    plugin_create.add_argument("--quick", action="store_true", help="Use development defaults for missing metadata.")
    plugin_create.add_argument("--force", action="store_true", help="Overwrite existing scaffold files.")

    plugin_activate = subparsers.add_parser(
        "plugin:activate",
        help="Activate an installed KARPy plugin.",
    )
    plugin_activate.add_argument("name", help="Plugin folder name or title.")

    plugin_deactivate = subparsers.add_parser(
        "plugin:deactivate",
        help="Deactivate an installed KARPy plugin.",
    )
    plugin_deactivate.add_argument("name", help="Plugin folder name or title.")

    crud_create = subparsers.add_parser(
        "crud:create",
        help="Create model/schema/route/table stubs for a plugin CRUD resource.",
    )
    crud_create.add_argument("name", help="Resource name, e.g. SpeedReport.")
    crud_create.add_argument("--plugin", required=True, help="Target plugin folder, e.g. speed.")
    crud_create.add_argument("--force", action="store_true", help="Overwrite existing scaffold files.")

    product_seed = subparsers.add_parser(
        "product:seed",
        help="Load the product's seed data (products/<PRODUCT>/seed). Idempotent; never overwrites.",
    )
    product_seed.add_argument("--product", help="Product folder under backend/products. Default: the PRODUCT env setting.")

    demo_seed = subparsers.add_parser(
        "demo:seed",
        help="Load seed data, then the product's demo data. Refused when APP_ENV is production.",
    )
    demo_seed.add_argument("--product", help="Product folder under backend/products. Default: the PRODUCT env setting.")

    demo_clear = subparsers.add_parser(
        "demo:clear",
        help="Remove demo accounts (and registered demo content) for the product.",
    )
    demo_clear.add_argument("--product", help="Product folder under backend/products. Default: the PRODUCT env setting.")

    return parser


def run_product_command(command: str, product_arg: str | None, session_factory=None) -> int:
    """Run product:seed / demo:seed / demo:clear and print a summary. Returns the exit code."""
    import asyncio

    from karpy_platform.core import products

    try:
        product = products.load_product(product_arg)
        if command == "demo:seed":
            products.ensure_demo_allowed()
        if session_factory is None:
            from app.database import async_session as session_factory
        if command == "product:seed":
            report = asyncio.run(products.run_product_seed(session_factory, product))
            print(f"Seed data for {product.name!r} (seed_version {product.manifest.seed_version}): {report.total()} rows added")
            print("\n".join(report.lines()) or "  nothing to load")
        elif command == "demo:seed":
            from app.config import settings

            seeded, report = asyncio.run(products.run_demo_seed(session_factory, product, password=settings.DEMO_PASSWORD))
            print(f"Seed data for {product.name!r}: {seeded.total()} rows added")
            if seeded.skipped:
                print("\n".join(line for line in seeded.lines() if "skipped" in line))
            print(f"Demo data for {product.name!r}: {report.total()} rows added")
            print("\n".join(report.lines()) or "  nothing to load")
            if not settings.DEMO_PASSWORD:
                print("Demo accounts have random passwords nobody knows; set DEMO_PASSWORD before demo:seed to sign in as them.")
        else:
            report = asyncio.run(products.run_demo_clear(session_factory, product))
            print(f"Demo data removed for {product.name!r}: {report.total()} rows")
            print("\n".join(report.lines()) or "  nothing to remove")
    except products.ProductSeedError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


def normalize_plugin_name(value: str) -> str:
    return PluginGenerator.slug(value.split("/")[-1])


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "plugin:create":
            result = PluginGenerator().create(
                args.name,
                plugin_id=args.plugin_id,
                author=args.author,
                version=args.version,
                description=args.description,
                namespace=args.namespace,
                quick=args.quick,
                force=args.force,
            )
            print(result.message)
            for path in result.files:
                print(f"  created {path}")
            return 0

        if args.command == "plugin:activate":
            result = plugin_service.activate(normalize_plugin_name(args.name))
            if not result.get("error"):
                import asyncio

                asyncio.run(plugin_service.install_database(normalize_plugin_name(args.name)))
            print(result.get("message", result))
            return 1 if result.get("error") else 0

        if args.command == "plugin:deactivate":
            result = plugin_service.deactivate(normalize_plugin_name(args.name))
            print(result.get("message", result))
            return 1 if result.get("error") else 0

        if args.command in ("product:seed", "demo:seed", "demo:clear"):
            return run_product_command(args.command, args.product)

        if args.command == "crud:create":
            result = CrudGenerator().create(args.name, plugin=args.plugin, force=args.force)
            print(result.message)
            for path in result.files:
                print(f"  created {path}")
            return 0

    except FileExistsError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    parser.error(f"Unknown command: {args.command}")
    return 2
