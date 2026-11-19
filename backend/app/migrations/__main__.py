from __future__ import annotations

import argparse
import asyncio

from app.database import engine, load_models
from app.migrations import CURRENT_VERSION, current_version, migrate_down, migrate_up, validate_migrations


async def run() -> None:
    parser = argparse.ArgumentParser(description="KARPy numbered schema migrations")
    parser.add_argument("direction", choices=("up", "down", "status"))
    parser.add_argument("target", nargs="?", type=int)
    args = parser.parse_args()
    load_models()
    if args.direction == "up":
        await migrate_up(engine, CURRENT_VERSION if args.target is None else args.target)
        await validate_migrations(engine)
    elif args.direction == "down":
        if args.target is None:
            parser.error("down requires a target version")
        await migrate_down(engine, args.target)
    else:
        await validate_migrations(engine)
    print(f"KARPy schema version {await current_version(engine)}")


if __name__ == "__main__":
    asyncio.run(run())
