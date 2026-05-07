"""Phase 275 / API-02 regression: CHANGELOG [Unreleased] routes match OpenAPI.

Locks in the contract that the v1.1.0-ready CHANGELOG block lists every
new route, and that every route it lists actually exists in the public
API surface. Drift between the two will fail CI.
"""

from __future__ import annotations

import json
import re
from pathlib import Path


# CHANGELOG entries format the route as a single backtick-wrapped pair, e.g.
# `POST /maps/import` — both method + path inside one pair of backticks.
_ROUTE_RE = re.compile(
    r"`(GET|POST|PUT|PATCH|DELETE)\s+(/[^`]+)`"
)


def _repo_root() -> Path:
    """Walk upward from this file until we find CHANGELOG.md.

    The test runs with the backend project as cwd under uv, so resolving via
    the file path is more robust than relying on cwd.
    """
    here = Path(__file__).resolve()
    for ancestor in here.parents:
        if (ancestor / "CHANGELOG.md").is_file():
            return ancestor
    raise FileNotFoundError("Could not locate CHANGELOG.md from test file path")


def _read_unreleased() -> str:
    """Return everything between `## [Unreleased]` and the next `## [` header."""
    text = (_repo_root() / "CHANGELOG.md").read_text(encoding="utf-8")
    unreleased_start = text.index("## [Unreleased]")
    next_section = text.index("\n## [", unreleased_start + 1)
    return text[unreleased_start:next_section]


def _read_added_map_builder_block() -> str:
    """Isolate the `### Added — Map Builder API surface` sub-section."""
    unreleased = _read_unreleased()
    block_start = unreleased.index("### Added — Map Builder API surface")
    next_heading = unreleased.index("\n### ", block_start + 1)
    return unreleased[block_start:next_heading]


def test_changelog_unreleased_routes_exist_in_openapi() -> None:
    """Every `METHOD /path` in the Map Builder API surface block is in openapi.json."""
    block = _read_added_map_builder_block()
    spec = json.loads(
        (_repo_root() / "backend" / "openapi.json").read_text(encoding="utf-8")
    )
    openapi_paths = set(spec["paths"].keys())

    cited_routes = _ROUTE_RE.findall(block)
    assert cited_routes, (
        "No `METHOD /path` strings found in CHANGELOG `### Added — Map Builder "
        "API surface`. Either the block was rewritten without preserving the "
        "monospace route format, or the regex is wrong."
    )

    missing: list[str] = []
    for method, path in cited_routes:
        if path not in openapi_paths:
            missing.append(f"{method} {path}")
            continue
        method_lower = method.lower()
        ops = spec["paths"][path]
        if method_lower not in ops:
            missing.append(f"{method} {path} (path exists, method missing)")

    assert not missing, (
        f"CHANGELOG cites routes not in openapi.json: {missing}. "
        "Either restore the route or update the changelog."
    )


def test_changelog_unreleased_lists_at_least_10_distinct_routes() -> None:
    """Sanity-check that the API-02 block was not partially trimmed."""
    block = _read_added_map_builder_block()
    cited = _ROUTE_RE.findall(block)
    unique = {(m, p) for m, p in cited}
    assert len(unique) >= 10, (
        f"Expected >=10 distinct routes in `### Added — Map Builder API surface`; "
        f"got {len(unique)}: {sorted(unique)}"
    )


def test_phase_269_breaking_change_block_intact() -> None:
    """The PUT /maps/{id}/thumbnail/ breaking-change wording must not regress.

    The on-disk format wraps method+path in a single pair of backticks
    (`PUT /maps/{id}/thumbnail/`). The signature below matches the
    Phase 269 wording verbatim so any rewrite of the breaking-change
    paragraph will fail this test.
    """
    unreleased = _read_unreleased()
    signature = (
        "`PUT /maps/{id}/thumbnail/` request body changed from `text/plain`"
    )
    assert signature in unreleased, (
        "Phase 269 breaking-change paragraph for PUT /maps/{id}/thumbnail/ has "
        "been rewritten or removed from CHANGELOG [Unreleased]. Restore it."
    )
