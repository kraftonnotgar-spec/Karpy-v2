"""Entry point for KARPy console commands.

Usage:
    python -m karpy_platform.cli plugin:create Speed
"""

from karpy_platform.core.console.commands import main


if __name__ == "__main__":
    raise SystemExit(main())
