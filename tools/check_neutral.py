#!/usr/bin/env python3
"""Fail when product names or raw colours appear in the product-neutral core.

Usage:  python tools/check_neutral.py            (from the repository root)
        python tools/check_neutral.py --list     (print the rules)

Rules
1. Product / provider names from tools/neutral_terms.txt must not appear in core code:
   backend/app, backend/karpy_platform, backend/tools, web/src (except web/src/products/),
   mobile/src, mobile/modules, services/ -- Markdown files are excepted. A project built on
   Karpy keeps its own names in its product layer (web/src/products/<p>/, backend/products/<p>/).
2. No raw hex colours in web/src/**/*.ts(x) or mobile/src/**/*.ts(x); colours live in theme
   files only (web/src/products/<p>/theme.css, mobile/src/theme/tokens.ts).

Exit code 0 = clean, 1 = findings (printed as path:line: text).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TERMS_FILE = Path(__file__).with_name("neutral_terms.txt")

CORE_DIRS = [
    "backend/app", "backend/karpy_platform", "backend/tools",
    "web/src", "mobile/src", "mobile/modules", "mobile/plugins", "services",
]
NAME_EXCLUDE_DIRS = ("web/src/products/", "backend/products/")
SKIP_PARTS = {"node_modules", ".next", ".venv", "__pycache__", ".expo", "dist", "build", "coverage"}
TEXT_SUFFIXES = {".py", ".ts", ".tsx", ".js", ".mjs", ".cjs", ".json", ".css", ".go", ".yaml", ".yml",
                 ".toml", ".html", ".jinja", ".txt", ".sql", ".sh", ".mod"}
COLOUR_DIRS = ["web/src", "mobile/src"]
# components/ui is upstream shadcn, kept unmodified (chart.tsx targets recharts' own #ccc stroke).
COLOUR_ALLOWED = ("web/src/products/", "mobile/src/theme/", "web/src/components/ui/")
HEX = re.compile(r"(?<![\w&])#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})\b")


def load_terms() -> list[re.Pattern]:
    terms = []
    for line in TERMS_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            terms.append(re.compile(line, re.IGNORECASE))
    return terms


def files(base: str):
    root = ROOT / base
    if not root.exists():
        return
    for path in root.rglob("*"):
        if path.is_file() and not SKIP_PARTS.intersection(path.relative_to(ROOT).parts):
            yield path


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def main() -> int:
    if "--list" in sys.argv:
        print(__doc__)
        print("Terms:", ", ".join(term.pattern for term in load_terms()))
        return 0
    terms = load_terms()
    findings: list[str] = []
    for base in CORE_DIRS:
        for path in files(base):
            name = rel(path)
            if path.suffix not in TEXT_SUFFIXES or name.endswith(".md") or name.startswith(NAME_EXCLUDE_DIRS):
                continue
            if name in {"tools/neutral_terms.txt"} or path.name in {"package-lock.json", "go.sum"}:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            for number, line in enumerate(text.splitlines(), 1):
                for term in terms:
                    if term.search(line):
                        findings.append(f"{name}:{number}: product name /{term.pattern}/: {line.strip()[:160]}")
                        break
    for base in COLOUR_DIRS:
        for path in files(base):
            name = rel(path)
            if path.suffix not in {".ts", ".tsx"} or name.startswith(COLOUR_ALLOWED):
                continue
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if HEX.search(line):
                    findings.append(f"{name}:{number}: raw colour (use design tokens): {line.strip()[:160]}")
    for item in findings:
        print(item)
    if findings:
        print(f"\ncheck_neutral: {len(findings)} finding(s).", file=sys.stderr)
        return 1
    print("check_neutral: clean")
    return 0


if __name__ == "__main__":
    sys.exit(main())
