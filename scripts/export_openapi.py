"""Export the public OpenAPI spec to a JSON file.

Usage:
    python -m scripts.export_openapi          # writes openapi.json
    python -m scripts.export_openapi out.json  # custom path
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> None:
    dest = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("openapi.json")

    # NOTE: This import triggers create_app() and all middleware registration.
    # It works because app.openapi() only needs route metadata, not running
    # services. If module-level initialization is added that requires DB/Redis,
    # this script will need a minimal app construction path instead.
    from app.main import app
    from app.api.openapi_enrichment import filter_internal_paths

    schema = filter_internal_paths(app.openapi())
    dest.write_text(json.dumps(schema, indent=2) + "\n")
    print(f"OpenAPI spec written to {dest} ({len(schema.get('paths', {}))} paths)")


if __name__ == "__main__":
    main()
