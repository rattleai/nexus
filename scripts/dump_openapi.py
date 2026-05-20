"""Write the FastAPI OpenAPI spec to a path passed on argv.

Used by:
    - the OpenAPI Lock Drift CI job to detect unintended API surface changes
    - `make openapi-lock` to refresh the committed openapi.lock.json

Usage:
    python scripts/dump_openapi.py path/to/openapi.json
"""

from __future__ import annotations

import json
import logging
import sys


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: dump_openapi.py <output_path>", file=sys.stderr)
        return 2

    # Silence structlog/uvicorn startup noise so the only stdout is the spec
    # (when output_path is "-" we'll print to stdout instead of writing).
    logging.disable(logging.CRITICAL)
    from app.main import create_app

    app = create_app()
    spec = app.openapi()
    serialized = json.dumps(spec, indent=2, sort_keys=True) + "\n"

    if sys.argv[1] == "-":
        sys.stdout.write(serialized)
    else:
        with open(sys.argv[1], "w") as f:
            f.write(serialized)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
