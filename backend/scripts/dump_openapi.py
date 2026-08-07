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


def ordered_for_snapshot(node, *, preserve_keys: bool = False):
    """Recursively sort dict keys, except each schema's ``properties`` map.

    fix(#1257): property insertion order is Pydantic field declaration order,
    and openapi-python-client derives generated constructor argument order
    from it — alphabetizing it silently reorders positional arguments for SDK
    consumers whenever an optional field is added. Everything else stays
    sorted for deterministic, diff-friendly snapshots.
    """
    if isinstance(node, dict):
        keys = node if preserve_keys else sorted(node)
        return {
            k: ordered_for_snapshot(node[k], preserve_keys=(k == "properties"))
            for k in keys
        }
    if isinstance(node, list):
        return [ordered_for_snapshot(v) for v in node]
    return node


def _dump(spec: dict) -> str:
    # Sorted keys + trailing newline → deterministic diff-friendly output,
    # with schema property order preserved (see ordered_for_snapshot).
    return json.dumps(ordered_for_snapshot(spec), indent=2) + "\n"


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
