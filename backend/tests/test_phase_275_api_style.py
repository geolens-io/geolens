"""Phase 275 / API-03 + API-07 regression: API style guide and health tag."""

from __future__ import annotations

import json

from tests.repo_paths import repo_root

REPO_ROOT = repo_root(__file__)


def test_api_reference_points_to_public_docs_site() -> None:
    """API-03: public API docs live on docs.getgeolens.com, not root docs/."""
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    assert "docs.getgeolens.com/guides/api/" in readme
    assert "docs/api-style.md" not in readme


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


def test_maps_namespace_slash_convention_examples_exist() -> None:
    """Sanity-check: public API example routes exist in the OpenAPI snapshot.

    This isn't an exhaustive lint. It catches drift if a future PR removes
    a public example route without updating the external docs/OpenAPI story.
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
        f"Public API example routes are absent from openapi.json: {sorted(missing)}. "
        "Either restore the route or update the docs/OpenAPI story."
    )
