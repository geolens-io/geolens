"""Integration tests for quality scoring (PREV-05).

Tests verify quality score computation logic and its presence in API responses.
Since compute_quality_score requires a real data table for geometry validity
and attribute completeness, we test the metadata-only components directly
and verify API exposure via the search/dataset endpoints.

Requirements:
  - Docker database must be running (docker compose up db)
  - Alembic migrations must be applied (quality_score column)
"""

import uuid
from datetime import date

import pytest
from httpx import AsyncClient
from app.datasets.models import Dataset, Record, RecordKeyword

from tests.factories import get_user_id


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _create_dataset_with_quality(
    session,
    *,
    created_by: uuid.UUID,
    name: str,
    description: str | None = None,
    theme_category: list[str] | None = None,
    keywords: list[str] | None = None,
    license_val: str | None = None,
    source_organization: str | None = None,
    data_vintage_start: date | None = None,
    srid: int | None = 4326,
    quality_score: dict | None = None,
    visibility: str = "public",
    lineage_summary: str | None = None,
    update_frequency: str | None = None,
    usage_constraints: str | None = None,
    access_constraints: str | None = None,
) -> Dataset:
    """Insert a Dataset with optional quality_score metadata."""
    table_name = f"ds_{uuid.uuid4().hex[:12]}"
    record = Record(
        title=name,
        summary=description,
        theme_category=theme_category,
        license=license_val,
        source_organization=source_organization,
        temporal_start=data_vintage_start,
        visibility=visibility,
        record_status="published",
        created_by=created_by,
        lineage_summary=lineage_summary,
        update_frequency=update_frequency,
        usage_constraints=usage_constraints,
        access_constraints=access_constraints,
    )
    session.add(record)
    await session.flush()
    if keywords:
        for kw in keywords:
            session.add(
                RecordKeyword(record_id=record.id, keyword=kw, keyword_type="theme")
            )
        await session.flush()
    dataset = Dataset(
        record_id=record.id,
        table_name=table_name,
        srid=srid,
        geometry_type="MultiPolygon",
        feature_count=100,
        source_format="geojson",
        source_filename="test.geojson",
        quality_detail=quality_score,
    )
    session.add(dataset)
    await session.commit()
    await session.refresh(dataset)
    return dataset


# ---------------------------------------------------------------------------
# Unit-level tests for quality score computation logic
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_compute_quality_score_complete_dataset(test_db_session):
    """A dataset with all optional metadata fields filled scores high on
    metadata_completeness and crs_defined."""
    from app.ingest.metadata import compute_quality_score as _compute

    admin_id = await get_user_id(test_db_session, "admin")

    ds = await _create_dataset_with_quality(
        test_db_session,
        created_by=admin_id,
        name="Complete Dataset",
        description="Full description",
        theme_category=["hydrology", "water"],
        keywords=["hydrology", "water"],
        license_val="CC-BY-4.0",
        source_organization="USGS",
        data_vintage_start=date(2023, 1, 1),
        srid=4326,
        lineage_summary="Collected from USGS gauges",
        update_frequency="monthly",
        usage_constraints="Public domain",
        access_constraints="None",
    )

    # compute_quality_score requires a real table for geometry/attribute checks.
    # We create a minimal temporary table so the function can execute.
    from sqlalchemy import text

    tmp_table = ds.table_name
    await test_db_session.execute(
        text(
            f"CREATE TABLE IF NOT EXISTS data.{tmp_table} "
            f"(gid serial PRIMARY KEY, geom geometry(Point, 4326), val text)"
        )
    )
    await test_db_session.execute(
        text(
            f"INSERT INTO data.{tmp_table} (geom, val) VALUES "
            f"(ST_SetSRID(ST_MakePoint(-73.9, 40.7), 4326), 'test')"
        )
    )
    await test_db_session.commit()

    score = await _compute(
        test_db_session,
        tmp_table,
        [{"name": "val", "type": "text"}],
        ds,
    )

    assert score["metadata_completeness"] == 100.0
    assert score["crs_defined"] == 100.0
    assert score["overall"] > 0

    # Cleanup
    await test_db_session.execute(text(f"DROP TABLE IF EXISTS data.{tmp_table}"))
    await test_db_session.commit()


@pytest.mark.anyio
async def test_compute_quality_score_minimal_dataset(test_db_session):
    """A dataset with only required fields scores low on metadata_completeness
    and 0 on crs_defined if srid is None."""
    from app.ingest.metadata import compute_quality_score as _compute

    admin_id = await get_user_id(test_db_session, "admin")

    ds = await _create_dataset_with_quality(
        test_db_session,
        created_by=admin_id,
        name="Minimal Dataset",
        srid=None,
    )

    from sqlalchemy import text

    tmp_table = ds.table_name
    await test_db_session.execute(
        text(
            f"CREATE TABLE IF NOT EXISTS data.{tmp_table} "
            f"(gid serial PRIMARY KEY, geom geometry(Point, 4326))"
        )
    )
    await test_db_session.execute(
        text(
            f"INSERT INTO data.{tmp_table} (geom) VALUES "
            f"(ST_SetSRID(ST_MakePoint(0, 0), 4326))"
        )
    )
    await test_db_session.commit()

    score = await _compute(
        test_db_session,
        tmp_table,
        [],
        ds,
    )

    # No optional metadata filled
    assert score["metadata_completeness"] == 0.0
    assert score["crs_defined"] == 0.0

    # Cleanup
    await test_db_session.execute(text(f"DROP TABLE IF EXISTS data.{tmp_table}"))
    await test_db_session.commit()


# ---------------------------------------------------------------------------
# API exposure tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_quality_score_in_search_results(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
):
    """quality_score is included in OGC record properties from search."""
    admin_id = await get_user_id(test_db_session, "admin")
    score_data = {
        "overall": 82,
        "metadata_completeness": 83.3,
        "geometry_validity": 100.0,
        "attribute_completeness": 95.0,
        "crs_defined": 100.0,
    }
    ds = await _create_dataset_with_quality(
        test_db_session,
        created_by=admin_id,
        name="Scored Rivers Dataset",
        quality_score=score_data,
    )

    resp = await client.get(
        "/search/datasets/",
        params={"q": "Scored Rivers", "limit": 100},
        headers=admin_auth_header,
    )
    assert resp.status_code == 200
    data = resp.json()
    matching = [f for f in data["features"] if f["id"] == str(ds.id)]
    assert len(matching) == 1
    props = matching[0]["properties"]
    assert props["quality_detail"] is not None
    assert props["quality_detail"]["overall"] == 82


@pytest.mark.anyio
async def test_quality_score_in_dataset_response(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
):
    """GET /datasets/{id} includes quality_score field."""
    admin_id = await get_user_id(test_db_session, "admin")
    score_data = {
        "overall": 75,
        "metadata_completeness": 66.7,
        "geometry_validity": 100.0,
        "attribute_completeness": 80.0,
        "crs_defined": 100.0,
    }
    ds = await _create_dataset_with_quality(
        test_db_session,
        created_by=admin_id,
        name="Quality Check Dataset",
        quality_score=score_data,
    )

    resp = await client.get(
        f"/datasets/{ds.id}",
        headers=admin_auth_header,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["quality_detail"] is not None
    assert data["quality_detail"]["overall"] == 75


# ---------------------------------------------------------------------------
# Regression tests for PERF-N3/N9 — single-query attribute-completeness
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_attribute_completeness_uses_single_query(test_db_session):
    """compute_quality_score must issue one SQL query for attribute completeness,
    not one per column (PERF-N3/N9).

    Previously a 50-column dataset triggered 50 sequential full-table scans. The
    refactored implementation coalesces all per-column COUNT(col) aggregations
    into a single SELECT. This test asserts that by counting executions against
    the data.* table.
    """
    from sqlalchemy import text

    from app.ingest.metadata import compute_quality_score as _compute

    admin_id = await get_user_id(test_db_session, "admin")
    ds = await _create_dataset_with_quality(
        test_db_session,
        created_by=admin_id,
        name="Many Columns Dataset",
        srid=4326,
    )

    tmp_table = ds.table_name
    col_names = [f"c{i}" for i in range(10)]
    col_defs = ", ".join(f"{c} text" for c in col_names)
    await test_db_session.execute(
        text(
            f"CREATE TABLE IF NOT EXISTS data.{tmp_table} "
            f"(gid serial PRIMARY KEY, geom geometry(Point, 4326), {col_defs})"
        )
    )
    values = ", ".join("'x'" for _ in col_names)
    await test_db_session.execute(
        text(
            f"INSERT INTO data.{tmp_table} (geom, {', '.join(col_names)}) VALUES "
            f"(ST_SetSRID(ST_MakePoint(0, 0), 4326), {values})"
        )
    )
    await test_db_session.commit()

    # Count calls that reference data.{tmp_table} (excludes metadata / keyword
    # lookups, includes geometry validity + attribute completeness).
    original_execute = test_db_session.execute
    recorded: list[str] = []

    async def recording_execute(clause, *args, **kwargs):
        sql_text = str(clause) if clause is not None else ""
        if f"data.{tmp_table}" in sql_text:
            recorded.append(sql_text)
        return await original_execute(clause, *args, **kwargs)

    test_db_session.execute = recording_execute  # type: ignore[method-assign]
    try:
        column_info = [{"name": name, "type": "text"} for name in col_names]
        score = await _compute(test_db_session, tmp_table, column_info, ds)
    finally:
        test_db_session.execute = original_execute  # type: ignore[method-assign]

    # Expect at most 2 executions against the data table: one for the geometry
    # validity scan, one for the coalesced attribute completeness scan.
    assert len(recorded) <= 2, (
        f"expected ≤2 data-table queries (1 geometry, 1 attribute), "
        f"got {len(recorded)}: {recorded}"
    )
    # Attribute query must reference all 10 columns in a single SELECT.
    attribute_query = next(
        (q for q in recorded if 'COUNT("c0"' in q or "COUNT(c0)" in q), None
    )
    assert attribute_query is not None, (
        f"attribute completeness query not found in {recorded}"
    )
    for name in col_names:
        assert name in attribute_query, (
            f"column {name!r} missing from single-query SELECT: {attribute_query}"
        )

    # Sanity: computed score is structurally valid
    assert score["attribute_completeness"] == 100.0
    assert 0 <= score["overall"] <= 100

    # Cleanup
    await test_db_session.execute(text(f"DROP TABLE IF EXISTS data.{tmp_table}"))
    await test_db_session.commit()


@pytest.mark.anyio
async def test_validate_dataset_returns_cached_quality_by_default(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
):
    """GET /datasets/{id}/validate/ returns persisted quality_detail without
    recomputing. Recomputation requires ?refresh=true."""
    admin_id = await get_user_id(test_db_session, "admin")
    cached = {
        "overall": 42,
        "metadata_completeness": 50.0,
        "geometry_validity": 100.0,
        "attribute_completeness": 30.0,
        "crs_defined": 100.0,
        "computed_at": "2026-04-08T00:00:00+00:00",
    }
    ds = await _create_dataset_with_quality(
        test_db_session,
        created_by=admin_id,
        name="Cached Quality Dataset",
        quality_score=cached,
    )

    resp = await client.get(
        f"/datasets/{ds.id}/validate/",
        headers=admin_auth_header,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["quality_score"]["overall"] == 42
    assert data["quality_score"]["attribute_completeness"] == 30.0


# ---------------------------------------------------------------------------
# Table record quality scoring tests (260408-iny)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_compute_quality_score_table_record(test_db_session):
    """Tables skip geometry_validity and crs_defined; overall is re-normalized
    from metadata (30/55) + attribute (25/55) weights only.

    Record with full metadata and one attribute column should score:
      - metadata_completeness: 100
      - attribute_completeness: 100
      - overall: round(100 * 30/55 + 100 * 25/55) = round(100) = 100
      - geometry_validity: None (not applicable)
      - crs_defined: None (not applicable)
    """
    from app.ingest.metadata import compute_quality_score as _compute

    admin_id = await get_user_id(test_db_session, "admin")

    # Create a Record with record_type='table' (no geometry, no srid)
    import uuid
    from datetime import date as _date

    from sqlalchemy import text

    from app.datasets.models import Dataset, Record, RecordKeyword

    table_name = f"tbl_{uuid.uuid4().hex[:12]}"
    record = Record(
        title="Test Table Record",
        summary="A non-spatial table for quality score testing",
        theme_category=["finance", "grants"],
        license="CC-BY-4.0",
        source_organization="Test Org",
        temporal_start=_date(2023, 1, 1),
        visibility="public",
        record_status="published",
        created_by=admin_id,
        record_type="table",
        lineage_summary="Collected from test source",
        update_frequency="annually",
        usage_constraints="Public domain",
        access_constraints="None",
    )
    test_db_session.add(record)
    await test_db_session.flush()
    for kw in ["grants", "funding"]:
        test_db_session.add(
            RecordKeyword(record_id=record.id, keyword=kw, keyword_type="theme")
        )
    await test_db_session.flush()
    dataset = Dataset(
        record_id=record.id,
        table_name=table_name,
        srid=None,
        geometry_type=None,
        feature_count=29,
        source_format="arcgis_featureserver",
        source_filename="Bulletin",
    )
    test_db_session.add(dataset)
    await test_db_session.commit()
    await test_db_session.refresh(dataset)

    # Create the actual data table (only gid — no geometry, one attribute)
    await test_db_session.execute(
        text(
            f"CREATE TABLE IF NOT EXISTS data.{table_name} "
            f"(gid serial PRIMARY KEY, opportunity_number text)"
        )
    )
    await test_db_session.execute(
        text(
            f"INSERT INTO data.{table_name} (opportunity_number) VALUES ('OPP-001')"
        )
    )
    await test_db_session.commit()

    score = await _compute(
        test_db_session,
        table_name,
        [{"name": "opportunity_number", "type": "text"}],
        dataset,
    )

    # Tables get only metadata and attribute dimensions
    assert score["metadata_completeness"] == 100.0
    assert score["attribute_completeness"] == 100.0
    assert score["geometry_validity"] is None
    assert score["crs_defined"] is None

    # overall = round(100 * 30/55 + 100 * 25/55) = round(54.55 + 45.45) = 100
    expected_overall = round(100.0 * (30 / 55) + 100.0 * (25 / 55))
    assert score["overall"] == expected_overall

    # Cleanup
    await test_db_session.execute(text(f"DROP TABLE IF EXISTS data.{table_name}"))
    await test_db_session.commit()
