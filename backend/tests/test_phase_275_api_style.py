"""Phase 275 / API-03 + API-07 regression: API style guide and health tag."""

from __future__ import annotations

import json
from pathlib import Path

# Resolve repo root from this test file's location:
#   backend/tests/test_phase_275_api_style.py -> parents[2] -> repo root.
# This lets pytest pass whether it's invoked from the repo root or from backend/
# (CI's working-directory: backend convention).
REPO_ROOT = Path(__file__).resolve().parents[2]


def test_api_style_guide_exists() -> None:
    """API-03: docs/api-style.md is the public-facing convention reference."""
    guide = REPO_ROOT / "docs" / "api-style.md"
    assert guide.exists(), "docs/api-style.md is missing — API-03 deliverable"
    body = guide.read_text(encoding="utf-8")
    # Required sections — keep these in sync with the guide's heading text.
    for required in (
        "Trailing-Slash Convention",
        "Status Code Convention",
        "Health Check Endpoint",
        "/ingest/manifest/apply",
    ):
        assert required in body, f"docs/api-style.md missing section: {required}"


def test_health_endpoint_tagged() -> None:
    """API-07 / L-06: GET /health gains tags=['Health'] in the OpenAPI snapshot."""
    spec = json.loads(
        (REPO_ROOT / "backend" / "openapi.json").read_text(encoding="utf-8")
    )
    health_op = spec["paths"]["/health"]["get"]
    tags = health_op.get("tags", [])
    assert "Health" in tags, (
        f"GET /health is not tagged 'Health' in openapi.json — got tags={tags}. "
        "API-07 / L-06 regression."
    )


def test_maps_namespace_slash_convention_matches_doc() -> None:
    """Sanity-check: the slash convention documented in api-style.md describes routes that exist.

    This isn't an exhaustive lint — it's a static guard that catches drift if a future
    PR removes one of the cited example routes without updating the doc.
    """
    spec = json.loads(
        (REPO_ROOT / "backend" / "openapi.json").read_text(encoding="utf-8")
    )
    paths = set(spec["paths"].keys())

    # Routes the api-style.md guide explicitly cites.
    cited = {
        "/maps/",
        "/maps/{map_id}",
        "/maps/{map_id}/history",
        "/maps/{map_id}/duplicate/",
        "/maps/{map_id}/thumbnail/",
        "/maps/{map_id}/share/",
        "/maps/icons",
        "/maps/import",
        "/maps/sprites/geolens.json",
        "/maps/{map_id}/style.json",
        "/ingest/manifest/apply",
    }
    missing = cited - paths
    assert not missing, (
        f"docs/api-style.md cites these routes but they're absent from openapi.json: {sorted(missing)}. "
        "Either restore the route or update the style guide."
    )
