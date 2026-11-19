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

    return parser


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
