"""Unit tests for the builder-audit #338 MVT remediation (service/router pure helpers).

Covers (no DB / no asyncpg pool):
  - MVT-07: continuous simplification-tolerance schedule across the z5->z6 boundary.
  - MVT-01: the MVT source-layer name stays schema-qualified for client parity.
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
    get_cluster_tile,
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
# builder-audit #338 MVT-01 flagged that the multi_tenant MVT layer name
# (data_t_<tid>.table) diverged from the client's hardcoded data.table. The
# tile-config contract now gives clients the resolved physical prefix while tile
# signing retains its logical data.table route. This server regression keeps the
# emitted layer schema-qualified, as the dormant-tenancy isolation guard requires.
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


# ---------------------------------------------------------------------------
# fix(#394) VT-05 / VT-06 / VT-07: 2026-07-03 builder-audit query-shape fixes
# ---------------------------------------------------------------------------


def test_tile_query_makevalid_guards_simplify_only():
    """VT-05: ST_MakeValid wraps the simplify input; the z>=cutoff branch is untouched."""
    query = _build_tile_query("places", [])
    assert "ST_MakeValid(t.geom_4326)" in query
    # The unsimplified branch must still serve the original geometry.
    assert "ELSE t.geom_4326" in query


def test_tile_query_drops_null_geometry_features():
    """VT-06: the vector query filters NULL post-clip geometries like the cluster query."""
    query = _build_tile_query("places", [])
    assert "WHERE mvtgeom.geom IS NOT NULL" in query


def test_cluster_query_emits_positive_offset_gid():
    """VT-07: cluster feature ids are positive (ST_AsMVT drops non-positive ids)
    and offset out of the realistic serial-gid range."""
    query = _build_cluster_tile_query("places")
    assert "-row_number()" not in query
    assert f"{service._CLUSTER_FEATURE_ID_OFFSET}::bigint + row_number()" in query
    # Offset must stay exactly representable as a JS double.
    assert service._CLUSTER_FEATURE_ID_OFFSET < 2**53


# ---------------------------------------------------------------------------
# fix(#394) B-019/VT-01: reupload purges the MVT tile cache post-commit
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_invalidate_tile_cache_for_table_calls_provider(monkeypatch):
    from app.platform.cache import provider as cache_provider
    from app.processing.ingest.tasks_common import invalidate_tile_cache_for_table

    fake_cache = MagicMock()
    fake_cache.invalidate_table = AsyncMock()
    monkeypatch.setattr(cache_provider, "get_tile_cache", lambda: fake_cache)

    await invalidate_tile_cache_for_table("reuploaded_table")

    fake_cache.invalidate_table.assert_awaited_once_with("reuploaded_table")


@pytest.mark.asyncio
async def test_invalidate_tile_cache_for_table_noop_without_provider(monkeypatch):
    from app.platform.cache import provider as cache_provider
    from app.processing.ingest.tasks_common import invalidate_tile_cache_for_table

    monkeypatch.setattr(cache_provider, "get_tile_cache", lambda: None)

    # Must not raise — the purge is best-effort.
    await invalidate_tile_cache_for_table("reuploaded_table")


def test_reupload_tasks_invalidate_tile_cache_after_commit():
    """Both reupload task bodies call the tile-cache purge after their commit.

    Guards the fix(#394) B-019 call sites the way the audit found them missing:
    the swap replaces table contents, so each task must purge post-commit.
    """
    import inspect

    from app.processing.ingest import tasks_reupload

    source = inspect.getsource(tasks_reupload)
    assert source.count("await invalidate_tile_cache_for_table(live_table_name)") == 2


# ---------------------------------------------------------------------------
# fix(#403): cluster tiles project attribute columns onto UNCLUSTERED features
# ---------------------------------------------------------------------------


def test_cluster_query_projects_attr_columns_on_unclustered():
    """Validated attribute columns join back to the source row for unclustered
    features (single-point buckets / past cluster max zoom); excluded,
    reserved, and regex-invalid names never reach the projection."""
    cols = [
        {"name": "mag"},
        {"name": "place"},
        {"name": "geom"},  # _EXCLUDED_COLUMNS
        {"name": "point_count"},  # _CLUSTER_RESERVED_COLUMNS
        {"name": "bad-name"},  # fails _COLUMN_NAME_RE
    ]
    query = _build_cluster_tile_query("places", attr_columns=cols)
    assert "src.mag AS mag" in query
    assert "src.place AS place" in query
    assert 'LEFT JOIN "data"."places" src' in query
    # Join only binds a source row for unclustered features.
    assert "grouped.raw_point_count = 1 OR $1::integer > $5::integer" in query
    assert "src.geom" not in query
    assert "src.point_count" not in query
    assert "bad-name" not in query


def test_cluster_query_without_attr_columns_has_no_join():
    """No attr columns -> the query keeps its original single-table shape."""
    query = _build_cluster_tile_query("places")
    assert "LEFT JOIN" not in query
    assert "src." not in query


async def test_get_cluster_tile_resolves_columns_like_get_tile():
    """get_cluster_tile runs the columns through _select_tile_columns: the
    cols= opt-in projects at ANY zoom, and the low-zoom default projects
    nothing without an opt-in."""
    conn = AsyncMock()
    conn.fetchval.return_value = b"\x1a"
    columns = [{"name": "mag"}, {"name": "place"}]

    # z=3 (< z10 default) with an explicit cols= opt-in for one column.
    await get_cluster_tile(
        None,
        "places",
        3,
        1,
        1,
        columns,
        additional_columns=["mag"],
        conn=conn,
        schema="data",
    )
    query = conn.fetchval.call_args.args[0]
    assert "src.mag AS mag" in query
    assert "src.place" not in query

    # Same zoom, no opt-in -> no projection at all.
    await get_cluster_tile(None, "places", 3, 1, 1, columns, conn=conn, schema="data")
    query = conn.fetchval.call_args.args[0]
    assert "src." not in query
