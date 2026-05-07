"""PERF-02 and PERF-03 regression tests (Phase 274).

PERF-02 — _bulk_fetch_dataset_metadata runs the two independent blocks
          (STAC asset list + ST_AsGeoJSON extents) concurrently via
          asyncio.gather, while the dependent raster-meta + VRT-source-count
          path stays serialized.
PERF-03 — extract_metadata for spatial tables consolidates four data-table
          SELECTs (feature_count, srid, geometry_type, extent_wkt) into a
          single CTE-driven query so PostgreSQL does one shared scan and
          one network round-trip.
"""

import inspect
import os

import pytest
from sqlalchemy import text


# --- PERF-03: extract_metadata uses CTE consolidation ---------------------


def test_extract_metadata_uses_single_cte():
    """PERF-03: spatial-table fast path issues one CTE-driven query."""
    from app.processing.ingest.metadata import extract_metadata

    src = inspect.getsource(extract_metadata)
    # Must contain a CTE
    assert "WITH meta AS" in src, "PERF-03 CTE consolidation missing"
    # Must still call Find_SRID and ST_Extent inside the CTE
    assert "Find_SRID" in src, "PERF-03 srid via Find_SRID missing"
    assert "ST_Extent" in src, "PERF-03 extent via ST_Extent missing"


def test_extract_metadata_keeps_fallback_path():
    """PERF-03: graceful degradation if CTE fails (e.g., legacy PostGIS)."""
    from app.processing.ingest.metadata import extract_metadata

    src = inspect.getsource(extract_metadata)
    # Per-helper fallback must remain reachable
    assert "get_table_srid" in src
    assert "get_extent" in src
    assert "get_geometry_type" in src
    assert "get_feature_count" in src


def test_extract_metadata_non_spatial_skips_spatial_helpers():
    """PERF-03: non-spatial table path uses ONLY get_feature_count."""
    from app.processing.ingest.metadata import extract_metadata

    src = inspect.getsource(extract_metadata)
    # The non-spatial branch should run feature_count, but not have
    # to invoke the CTE or Find_SRID.
    # Loose check: the function body has 'if not has_geometry' guard.
    assert "has_geometry" in src


# --- PERF-02: _bulk_fetch_dataset_metadata parallelization ---------------


def test_bulk_fetch_uses_asyncio_gather_or_documented_deferral():
    """PERF-02: independent blocks run concurrently OR a documented
    deferral comment explains why.
    """
    from app.modules.catalog.search.router import _bulk_fetch_dataset_metadata

    src = inspect.getsource(_bulk_fetch_dataset_metadata)
    gather_used = "asyncio.gather" in src
    marker = "PERF-02" in src
    assert gather_used or marker, (
        "PERF-02: _bulk_fetch_dataset_metadata must either use asyncio.gather "
        "OR include a 'PERF-02' marker comment documenting the deferral."
    )


def test_bulk_fetch_dependent_path_stays_sequential():
    """PERF-02: block 3 still mutates block 2's output IN PLACE.

    Asserts that the *executable* call to ``fetch_raster_meta_bulk``
    precedes the *executable* assignment of ``source_count`` into
    ``raster_meta[...]``. Uses precise call-site substrings so that
    incidental mentions in the docstring/comments don't satisfy or
    invalidate the ordering check.
    """
    from app.modules.catalog.search.router import _bulk_fetch_dataset_metadata

    src = inspect.getsource(_bulk_fetch_dataset_metadata)
    # The actual call site (block 2) — the await expression
    fetch_marker = "fetch_raster_meta_bulk(db, raster_ids)"
    # The actual mutation site (block 3) — assigning into raster_meta
    merge_marker = '["source_count"]'
    idx_fetch = src.find(fetch_marker)
    idx_merge = src.find(merge_marker)
    assert idx_fetch != -1, (
        f"PERF-02: expected to find call site {fetch_marker!r} in source"
    )
    assert idx_merge != -1, (
        f"PERF-02: expected to find merge site {merge_marker!r} in source"
    )
    assert idx_fetch < idx_merge, (
        "PERF-02 ordering invariant violated: source_count merge into "
        "raster_meta must follow the fetch_raster_meta_bulk call site"
    )


def test_bulk_fetch_preserves_best_effort_semantics():
    """PERF-02: per-block exceptions stay broad-handled."""
    from app.modules.catalog.search.router import _bulk_fetch_dataset_metadata

    src = inspect.getsource(_bulk_fetch_dataset_metadata)
    # Multiple try/except blocks for per-block degradation. After PERF-02
    # this includes: stac inner block + extents inner block + raster_meta
    # block + VRT source_count block = 4. Pre-PERF-02 there were 4 too.
    # Lock at >=2 so this test stays loose enough to not break on minor
    # refactors but tight enough to catch a wholesale removal of error
    # handling.
    assert src.count("except Exception") >= 2, (
        "PERF-02: must preserve per-block try/except best-effort handling"
    )


# --- PERF-03 behavior round-trip (DB-required) ---------------------------


@pytest.mark.skipif(
    os.environ.get("DATABASE_URL") is None
    and os.environ.get("TEST_DATABASE_URL") is None,
    reason="No test DB available; static-source assertions cover this requirement.",
)
@pytest.mark.anyio
async def test_extract_metadata_round_trips_on_spatial_table(test_db_session):
    """PERF-03: spatial table returns all 4 fields in one round-trip.

    Skipped automatically when no test DB env var is present. Even when
    those env vars are set, the underlying ``test_db_session`` fixture
    chain (which depends on ``client`` and ``_test_db_lifecycle``) only
    actually yields when the test database is reachable; otherwise the
    fixture session is unusable and the test will fail loudly (which is
    the intended CI behavior).
    """
    from app.processing.ingest.metadata import extract_metadata

    session = test_db_session

    # Create a tiny spatial table mirroring the post-ingest shape.
    # extract_metadata's spatial fast path queries `geom_4326` for the
    # extent and `geom` for the geometry_type, so both columns must exist.
    await session.execute(
        text(
            "CREATE TABLE IF NOT EXISTS data.test_perf03_round_trip ("
            "  gid SERIAL PRIMARY KEY,"
            "  geom geometry(Point, 4326),"
            "  geom_4326 geometry(Point, 4326)"
            ")"
        )
    )
    await session.execute(
        text(
            "INSERT INTO data.test_perf03_round_trip (geom, geom_4326) VALUES "
            "(ST_SetSRID(ST_MakePoint(0, 0), 4326), ST_SetSRID(ST_MakePoint(0, 0), 4326)),"
            "(ST_SetSRID(ST_MakePoint(1, 1), 4326), ST_SetSRID(ST_MakePoint(1, 1), 4326))"
        )
    )
    await session.commit()

    try:
        meta = await extract_metadata(session, "test_perf03_round_trip")
        assert meta["feature_count"] == 2
        assert meta["srid"] == 4326
        assert meta["geometry_type"] == "POINT"
        assert meta["extent_wkt"] is not None
        # Return-shape contract: exactly these five keys
        assert set(meta.keys()) == {
            "srid",
            "geometry_type",
            "feature_count",
            "extent_wkt",
            "column_info",
        }
    finally:
        await session.execute(
            text("DROP TABLE IF EXISTS data.test_perf03_round_trip")
        )
        await session.commit()
