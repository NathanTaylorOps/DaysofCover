"""Pre-commit hook: refuse any diff, path or git identity that matches the local deny-list.

The deny-list itself lives in `.denylist` at the repo root, one regular expression
per line, and is gitignored so its contents never enter history. The same patterns
live in a GitHub Actions secret and are checked again in CI. This hook fails closed:
a missing `.denylist` is an error, not a pass.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

DENYLIST_NAME = ".denylist"


def repo_root() -> Path:
    out = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, check=True
    )
    return Path(out.stdout.strip())


def load_patterns(root: Path) -> list[re.Pattern[str]]:
    path = root / DENYLIST_NAME
    if not path.is_file():
        sys.stderr.write(
            f"{DENYLIST_NAME} not found at {path}.\n"
            f"Copy {DENYLIST_NAME}.example to {DENYLIST_NAME} and fill it in. "
            "It is gitignored and never committed.\n"
        )
        sys.exit(2)
    patterns: list[re.Pattern[str]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        patterns.append(re.compile(line, re.IGNORECASE))
    if not patterns:
        sys.stderr.write(f"{DENYLIST_NAME} has no patterns. Add at least one.\n")
        sys.exit(2)
    return patterns


def git_identity() -> dict[str, str]:
    ident: dict[str, str] = {}
    for key in ("user.name", "user.email"):
        out = subprocess.run(["git", "config", key], capture_output=True, text=True)
        ident[key] = out.stdout.strip()
    return ident


def scan_text(label: str, text: str, patterns: list[re.Pattern[str]]) -> list[str]:
    hits: list[str] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        for pat in patterns:
            if pat.search(line):
                hits.append(f"{label}:{lineno}: matches /{pat.pattern}/")
                break
    return hits


def main(argv: list[str]) -> int:
    root = repo_root()
    patterns = load_patterns(root)
    hits: list[str] = []

    for key, value in git_identity().items():
        for pat in patterns:
            if value and pat.search(value):
                hits.append(f"git config {key} = {value!r} matches /{pat.pattern}/")

    for name in argv:
        path = Path(name)
        for pat in patterns:
            if pat.search(name):
                hits.append(f"path {name} matches /{pat.pattern}/")
                break
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue  # binary or unreadable; not scanned
        hits.extend(scan_text(name, text, patterns))

    if hits:
        sys.stderr.write("Deny-list hit. Nothing was committed.\n")
        for hit in hits:
            sys.stderr.write(f"  {hit}\n")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
