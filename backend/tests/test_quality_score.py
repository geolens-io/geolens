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
from sqlalchemy import select

from app.auth.models import User
from app.datasets.models import Dataset, Record, RecordKeyword


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _get_user_id(session, username: str) -> uuid.UUID:
    result = await session.execute(select(User).where(User.username == username))
    user = result.scalar_one()
    return user.id


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

    admin_id = await _get_user_id(test_db_session, "admin")

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

    admin_id = await _get_user_id(test_db_session, "admin")

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
    admin_id = await _get_user_id(test_db_session, "admin")
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
    admin_id = await _get_user_id(test_db_session, "admin")
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
