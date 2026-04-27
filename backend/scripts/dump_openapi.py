"""Snapshot the FastAPI OpenAPI schema to backend/openapi.json.

Usage:
    uv run python scripts/dump_openapi.py            # write backend/openapi.json
    uv run python scripts/dump_openapi.py --check    # diff against committed snapshot

The snapshot is the source of truth for SDK generation, contract testing, and
documentation rendering. The CI workflow runs ``--check`` so unintentional API
changes fail the build instead of silently shipping.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT_PATH = REPO_ROOT / "openapi.json"


def _load_spec() -> dict:
    # Imported lazily so --help / argparse can run without a DB.
    from app.api.main import app

    return app.openapi()


def _dump(spec: dict) -> str:
    # Sorted keys + trailing newline → deterministic diff-friendly output.
    return json.dumps(spec, indent=2, sort_keys=True) + "\n"


def main() -> int:
    check = "--check" in sys.argv
    spec = _load_spec()
    text = _dump(spec)

    if check:
        if not SNAPSHOT_PATH.exists():
            sys.stderr.write(
                f"openapi.json snapshot is missing at {SNAPSHOT_PATH}.\n"
                "Run `make openapi` and commit the result.\n"
            )
            return 1
        existing = SNAPSHOT_PATH.read_text()
        if existing != text:
            sys.stderr.write(
                "openapi.json snapshot is out of date.\n"
                "Run `make openapi` and commit the result.\n"
            )
            return 1
        return 0

    SNAPSHOT_PATH.write_text(text)
    sys.stdout.write(f"Wrote {SNAPSHOT_PATH}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
