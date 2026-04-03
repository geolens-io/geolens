"""Integration tests for record validation and quality scoring.

Tests cover: hard validation gates, soft validation warnings,
validation endpoint, publish blocking, quality score ISO fields.

Requirements:
  - Docker database must be running (docker compose up db)
  - Alembic migrations must be applied
"""

import uuid
from datetime import date

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select, text, update

from app.datasets.models import (
    Dataset,
    Record,
    RecordContact,
    RecordKeyword,
)

from tests.factories import get_user_id


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _create_validation_dataset(
    session,
    *,
    created_by: uuid.UUID,
    title: str = "Test Dataset",
    summary: str | None = None,
    license_val: str | None = None,
    lineage_summary: str | None = None,
    srid: int | None = 4326,
    extent_wkt: str | None = None,
    record_status: str = "draft",
    visibility: str = "public",
    update_frequency: str | None = None,
    quality_statement: str | None = None,
    source_url: str | None = None,
    usage_constraints: str | None = None,
    access_constraints: str | None = None,
    theme_category: list[str] | None = None,
    add_contact: bool = False,
    add_keyword: bool = False,
    temporal_start: date | None = None,
) -> Dataset:
    """Insert a Record + Dataset pair for validation tests."""
    table_name = f"ds_{uuid.uuid4().hex[:12]}"
    record = Record(
        title=title,
        summary=summary,
        license=license_val,
        lineage_summary=lineage_summary,
        visibility=visibility,
        record_status=record_status,
        created_by=created_by,
        update_frequency=update_frequency,
        usage_constraints=usage_constraints,
        access_constraints=access_constraints,
        theme_category=theme_category,
        temporal_start=temporal_start,
    )
    session.add(record)
    await session.flush()

    if add_contact:
        session.add(
            RecordContact(
                record_id=record.id,
                role="pointOfContact",
                name="Test User",
                email="test@example.com",
            )
        )

    if add_keyword:
        session.add(
            RecordKeyword(
                record_id=record.id,
                keyword="test-keyword",
                keyword_type="theme",
            )
        )

    dataset = Dataset(
        record_id=record.id,
        table_name=table_name,
        srid=srid,
        geometry_type="MultiPolygon",
        feature_count=100,
        source_format="geojson",
        source_filename="test.geojson",
        quality_statement=quality_statement,
        source_url=source_url,
    )
    session.add(dataset)
    await session.flush()

    # Set extent via raw SQL if provided
    if extent_wkt:
        await session.execute(
            update(Record)
            .where(Record.id == record.id)
            .values(spatial_extent=func.ST_GeomFromText(extent_wkt, 4326))
        )

    await session.commit()
    await session.refresh(dataset)
    return dataset


async def _make_fully_valid_dataset(session, *, created_by: uuid.UUID) -> Dataset:
    """Create a dataset that passes all hard validation checks."""
    extent_wkt = "POLYGON((-180 -90, 180 -90, 180 90, -180 90, -180 -90))"
    return await _create_validation_dataset(
        session,
        created_by=created_by,
        title="Valid Dataset",
        summary="A valid dataset with all required fields",
        license_val="CC-BY-4.0",
        lineage_summary="Derived from official sources",
        srid=4326,
        extent_wkt=extent_wkt,
        record_status="draft",
        add_contact=True,
        add_keyword=True,
    )


# ---------------------------------------------------------------------------
# Test: Validation endpoint returns errors for incomplete record
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_validate_endpoint_returns_errors_for_incomplete_record(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
):
    """A minimal dataset missing required fields shows errors."""
    admin_id = await get_user_id(test_db_session, "admin")

    ds = await _create_validation_dataset(
        test_db_session,
        created_by=admin_id,
        title="Incomplete",
        # No summary, license, lineage, contacts, keywords
    )

    resp = await client.get(
        f"/datasets/{ds.id}/validate/",
        headers=admin_auth_header,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["is_valid"] is False

    error_fields = {e["field"] for e in data["errors"]}
    assert "summary" in error_fields
    assert "license" in error_fields
    assert "lineage_summary" in error_fields
    assert "contacts" in error_fields
    assert "keywords" in error_fields
    # spatial_extent is None since no extent_wkt was provided
    assert "spatial_extent" in error_fields


# ---------------------------------------------------------------------------
# Test: Validation endpoint returns warnings for recommended fields
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_validate_endpoint_returns_warnings(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
):
    """A dataset with all required fields but missing recommended fields shows warnings."""
    admin_id = await get_user_id(test_db_session, "admin")

    # Create fully valid dataset (passes hard checks)
    ds = await _make_fully_valid_dataset(test_db_session, created_by=admin_id)

    resp = await client.get(
        f"/datasets/{ds.id}/validate/",
        headers=admin_auth_header,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["is_valid"] is True

    warning_fields = {w["field"] for w in data["warnings"]}
    assert "temporal_extent" in warning_fields
    assert "update_frequency" in warning_fields
    assert "quality_statement" in warning_fields
    assert "source_url" in warning_fields


# ---------------------------------------------------------------------------
# Test: Publish blocked when hard validation fails
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_publish_blocked_when_hard_validation_fails(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
):
    """PATCH with record_status=published on incomplete record returns 422 when require_metadata is ON."""
    from app.settings.models import AppSetting

    admin_id = await get_user_id(test_db_session, "admin")

    # Enable require_metadata_for_publish so validation gate is active
    test_db_session.add(
        AppSetting(key="require_metadata_for_publish", value={"v": True})
    )
    await test_db_session.commit()

    ds = await _create_validation_dataset(
        test_db_session,
        created_by=admin_id,
        title="Incomplete for Publish",
        # Missing summary, license, lineage, contacts, keywords, spatial_extent
    )

    resp = await client.patch(
        f"/datasets/{ds.id}",
        json={"record_status": "published"},
        headers=admin_auth_header,
    )
    assert resp.status_code == 422
    assert "Cannot publish" in resp.json()["detail"]

    # Cleanup: remove the setting override
    result = await test_db_session.execute(
        select(AppSetting).where(AppSetting.key == "require_metadata_for_publish")
    )
    setting = result.scalar_one_or_none()
    if setting:
        await test_db_session.delete(setting)
        await test_db_session.commit()


# ---------------------------------------------------------------------------
# Test: Publish succeeds when all required fields present
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_publish_succeeds_when_all_required_fields_present(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
):
    """PATCH with record_status=published on complete record succeeds."""
    admin_id = await get_user_id(test_db_session, "admin")

    ds = await _make_fully_valid_dataset(test_db_session, created_by=admin_id)

    resp = await client.patch(
        f"/datasets/{ds.id}",
        json={"record_status": "published"},
        headers=admin_auth_header,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["record_status"] == "published"


# ---------------------------------------------------------------------------
# Test: Already-published record can be edited without re-validation
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_already_published_record_can_be_edited(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
):
    """Editing a published record does not trigger validation."""
    admin_id = await get_user_id(test_db_session, "admin")

    # Create a published record directly (bypassing validation, like pre-existing data)
    ds = await _create_validation_dataset(
        test_db_session,
        created_by=admin_id,
        title="Already Published",
        record_status="published",
        # No summary, license, etc. -- simulates pre-existing published record
    )

    # Edit title -- should succeed even though record is incomplete
    resp = await client.patch(
        f"/datasets/{ds.id}",
        json={"title": "Renamed Published Dataset"},
        headers=admin_auth_header,
    )
    assert resp.status_code == 200
    assert resp.json()["title"] == "Renamed Published Dataset"


# ---------------------------------------------------------------------------
# Test: Quality score includes ISO fields
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_quality_score_includes_iso_fields(test_db_session):
    """Metadata completeness reflects the new 10-field denominator.

    Having keywords (RecordKeyword entries) should increase the score.
    """
    from app.ingest.metadata import compute_quality_score as _compute

    admin_id = await get_user_id(test_db_session, "admin")

    # Create dataset with some ISO fields filled
    ds = await _create_validation_dataset(
        test_db_session,
        created_by=admin_id,
        title="ISO Fields Test",
        summary="Has summary",
        lineage_summary="Lineage info",
        update_frequency="annually",
        theme_category=["farming"],
        record_status="draft",
        add_keyword=True,  # This adds a RecordKeyword entry
    )

    # Create a minimal temp table for quality score computation
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

    # With 10 fields total: summary, keywords, license, source_org, temporal_start,
    # lineage_summary, update_frequency, usage_constraints, access_constraints, theme_category
    # We filled: summary, keywords, lineage_summary, update_frequency, theme_category = 5/10 = 50%
    assert score["metadata_completeness"] == 50.0

    # Now create a dataset WITHOUT keywords and verify score is lower
    ds2 = await _create_validation_dataset(
        test_db_session,
        created_by=admin_id,
        title="No Keywords Test",
        summary="Has summary",
        lineage_summary="Lineage info",
        update_frequency="annually",
        theme_category=["farming"],
        record_status="draft",
        add_keyword=False,
    )

    tmp_table2 = ds2.table_name
    await test_db_session.execute(
        text(
            f"CREATE TABLE IF NOT EXISTS data.{tmp_table2} "
            f"(gid serial PRIMARY KEY, geom geometry(Point, 4326), val text)"
        )
    )
    await test_db_session.execute(
        text(
            f"INSERT INTO data.{tmp_table2} (geom, val) VALUES "
            f"(ST_SetSRID(ST_MakePoint(-73.9, 40.7), 4326), 'test')"
        )
    )
    await test_db_session.commit()

    score2 = await _compute(
        test_db_session,
        tmp_table2,
        [{"name": "val", "type": "text"}],
        ds2,
    )

    # Without keywords: summary, lineage_summary, update_frequency, theme_category = 4/10 = 40%
    assert score2["metadata_completeness"] == 40.0
    assert score2["metadata_completeness"] < score["metadata_completeness"]

    # Cleanup
    await test_db_session.execute(text(f"DROP TABLE IF EXISTS data.{tmp_table}"))
    await test_db_session.execute(text(f"DROP TABLE IF EXISTS data.{tmp_table2}"))
    await test_db_session.commit()


# ---------------------------------------------------------------------------
# Test: Publish allowed with incomplete metadata when setting is OFF (default)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_publish_allowed_when_require_metadata_off(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
):
    """With require_metadata_for_publish=False (default), incomplete records can be published."""
    admin_id = await get_user_id(test_db_session, "admin")

    ds = await _create_validation_dataset(
        test_db_session,
        created_by=admin_id,
        title="Incomplete But Publishable",
        # Missing summary, license, lineage, contacts, keywords, spatial_extent
    )

    # Default setting is False -- publish should succeed
    resp = await client.patch(
        f"/datasets/{ds.id}",
        json={"record_status": "published"},
        headers=admin_auth_header,
    )
    assert resp.status_code == 200
    assert resp.json()["record_status"] == "published"
