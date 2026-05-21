"""Static scan for runtime secret leaks via log / print calls.

Catches the common drift mode where a developer logs an OAuth token,
API key, or password during debugging and forgets to remove it. This
is intentionally narrow — it only flags log/print calls in `app/` (not
tests, not the encryption module that legitimately handles those
values) where a secret-named identifier appears as a value passed to
the call.

Exit code:
    0  no findings
    1  one or more findings printed to stderr (CI fails)

Usage:
    python scripts/scan_secret_leaks.py [path ...]    # default: app/
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

SECRET_NAMES = (
    "access_token",
    "refresh_token",
    "client_secret",
    "api_key",
    "password",
    "private_key",
)

LOG_CALL_RE = re.compile(
    r"(?:logger|log|logging)"
    r"\.(?:info|warning|error|debug|exception|critical)"
    r"\([^)]*\b(?:" + "|".join(SECRET_NAMES) + r")\b[^)]*\)",
)

PRINT_CALL_RE = re.compile(
    r"(?:print|sys\.stdout\.write)"
    r"\([^)]*\b(?:" + "|".join(SECRET_NAMES) + r")\b[^)]*\)",
)

# Lines that pass a redacted/star-masked literal are explicit and OK.
SAFE_HINT_RE = re.compile(r'=\s*"\*+"|"\[REDACTED\]"')

EXCLUDE_DIRS = {"__pycache__", "tests", ".venv", "node_modules"}
EXCLUDE_FILES = {"encryption.py", "scan_secret_leaks.py"}


def scan_file(path: Path) -> list[tuple[int, str, str]]:
    findings: list[tuple[int, str, str]] = []
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return findings
    for lineno, line in enumerate(text.splitlines(), start=1):
        if SAFE_HINT_RE.search(line):
            continue
        if LOG_CALL_RE.search(line):
            findings.append((lineno, "log", line.strip()))
        if PRINT_CALL_RE.search(line):
            findings.append((lineno, "print", line.strip()))
    return findings


def iter_python_files(roots: list[str]):
    for root in roots:
        for p in Path(root).rglob("*.py"):
            if any(part in EXCLUDE_DIRS for part in p.parts):
                continue
            if p.name in EXCLUDE_FILES:
                continue
            yield p


def main(argv: list[str]) -> int:
    roots = argv[1:] or ["app"]
    findings: list[tuple[Path, int, str, str]] = []
    for path in iter_python_files(roots):
        for lineno, kind, line in scan_file(path):
            findings.append((path, lineno, kind, line))

    if not findings:
        print("Secret-leak pattern scan: clean.")
        return 0

    print("::error::Secret-leak pattern scan: findings", file=sys.stderr)
    for path, lineno, kind, line in findings:
        print(f"{path}:{lineno}:{kind}:{line}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
