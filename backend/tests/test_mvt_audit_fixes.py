"""Unit tests for the builder-audit MVT remediation (service/router pure helpers).

Covers (no DB / no asyncpg pool):
  - MVT-07: continuous simplification-tolerance schedule across the z5->z6 boundary.
  - MVT-01: the MVT source-layer name stays schema-qualified (deferred cloud fix).
  - MVT-09: the table-name regex has a single shared definition.
  - MVT-04: ETag generation + conditional-request (If-None-Match -> 304) helpers.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.processing.tiles import router, service
from app.processing.tiles.router import (
    _if_none_match_satisfied,
    _tile_etag,
    _tile_headers,
    _tile_response,
)
from app.processing.tiles.service import (
    _NO_SIMPLIFY_AT_OR_ABOVE_ZOOM,
    _build_cluster_tile_query,
    _build_tile_query,
    _simplify_tolerance_degrees,
    get_tile,
)


# ---------------------------------------------------------------------------
# MVT-07: simplification-tolerance continuity
# ---------------------------------------------------------------------------


def test_simplify_tolerance_monotonic_and_continuous():
    """Tolerance shrinks continuously (halving each zoom) for every z below cutoff."""
    tols = [
        _simplify_tolerance_degrees(z) for z in range(_NO_SIMPLIFY_AT_OR_ABOVE_ZOOM)
    ]
    assert all(t is not None and t > 0 for t in tols)
    # Strictly decreasing AND each step is exactly a halving — no discontinuity.
    for prev, nxt in zip(tols, tols[1:]):
        assert nxt < prev
        assert nxt == pytest.approx(prev / 2.0)


def test_simplify_no_discontinuity_at_z5_z6_boundary():
    """Regression for the dropped 360 factor: z6 is half z5, not ~720x smaller."""
    t5 = _simplify_tolerance_degrees(5)
    t6 = _simplify_tolerance_degrees(6)
    assert t6 == pytest.approx(t5 / 2.0)
    # The old bug made z6 ~720x smaller than z5; assert we are nowhere near that.
    assert t6 > t5 / 4.0


def test_simplify_tolerance_none_at_and_above_cutoff():
    """z>=cutoff serves full-detail geometry (no simplification)."""
    assert _simplify_tolerance_degrees(_NO_SIMPLIFY_AT_OR_ABOVE_ZOOM) is None
    assert _simplify_tolerance_degrees(14) is None
    assert _simplify_tolerance_degrees(22) is None


def test_tile_query_uses_single_continuous_simplify_basis():
    """The SQL emits one continuous basis, not the old discontinuous two-branch CASE."""
    query = _build_tile_query("t", [{"name": "a"}])
    # The old z6-9 branch with the dropped 360 factor is gone.
    assert "1.0 / (4096 * power(2" not in query
    # Single degrees-per-unit basis remains.
    assert "360.0 / (4096 * power(2, $1::integer))" in query
    # Only one simplification branch now.
    assert query.count("ST_SimplifyPreserveTopology") == 1


# ---------------------------------------------------------------------------
# MVT-01: the source-layer name stays schema-qualified.
#
# builder-audit MVT-01 flagged that the multi_tenant MVT layer name
# (data_t_<tid>.table) diverges from the client's hardcoded data.table. In
# single_tenant (the only OSS-deployable mode) schema=="data", so the emitted
# layer name is already "data.table" and the client matches. The multi_tenant
# divergence is a deferred cloud-overlay concern whose fix belongs on the client
# (derive source-layer from the schema-qualified name) — the dormant-tenancy
# isolation guard (DP-02 / T1G) requires the server to keep schema qualification.
# ---------------------------------------------------------------------------


async def test_get_tile_layer_name_is_schema_qualified():
    """get_tile passes ``{schema}.{table}`` — "data.table" in single_tenant."""
    conn = AsyncMock()
    conn.fetchval.return_value = b"\x1a"  # non-empty MVT bytes
    await get_tile(None, "places", 5, 1, 1, [{"name": "gid"}], conn=conn, schema="data")
    # fetchval(query, z, x, y, layer_name) — single_tenant matches the client.
    assert conn.fetchval.call_args.args[4] == "data.places"


def test_tile_query_from_clause_is_schema_qualified():
    """The physical FROM stays schema-qualified for data-plane isolation."""
    query = _build_cluster_tile_query("places", schema="data_t_deadbeef")
    assert '"data_t_deadbeef"."places"' in query


# ---------------------------------------------------------------------------
# MVT-09: single source of truth for the table-name regex
# ---------------------------------------------------------------------------


def test_table_name_regex_is_single_source():
    """router imports the exact regex object defined in service (no duplicate)."""
    assert router._TABLE_NAME_RE is service._TABLE_NAME_RE


# ---------------------------------------------------------------------------
# MVT-04: ETag + conditional request helpers
# ---------------------------------------------------------------------------


def test_tile_etag_is_content_addressed_and_quoted():
    a = _tile_etag(b"abc")
    assert a == _tile_etag(b"abc")  # stable for identical bytes
    assert a != _tile_etag(b"abd")  # changes when the tile changes
    assert a.startswith('"') and a.endswith('"')


def test_if_none_match_satisfied():
    etag = _tile_etag(b"abc")
    assert _if_none_match_satisfied(etag, etag)
    assert _if_none_match_satisfied("*", etag)
    assert _if_none_match_satisfied(f'"other", {etag}', etag)
    assert _if_none_match_satisfied(f"W/{etag}", etag)  # weak validator prefix
    assert not _if_none_match_satisfied(None, etag)
    assert not _if_none_match_satisfied('"nope"', etag)


def test_tile_response_emits_etag_on_200():
    content = b"tilebytes"
    req = MagicMock()
    req.headers = {}
    resp = _tile_response(req, content, _tile_headers("public", 300))
    assert resp.status_code == 200
    assert resp.headers["ETag"] == _tile_etag(content)
    assert resp.body == content


def test_tile_response_returns_304_on_matching_if_none_match():
    content = b"tilebytes"
    etag = _tile_etag(content)
    req = MagicMock()
    req.headers = {"if-none-match": etag}
    resp = _tile_response(req, content, _tile_headers("public", 300))
    assert resp.status_code == 304
    assert resp.headers["ETag"] == etag
    # 304 carries no entity body, so Content-Encoding must be dropped.
    assert "content-encoding" not in resp.headers
    assert resp.body == b""
