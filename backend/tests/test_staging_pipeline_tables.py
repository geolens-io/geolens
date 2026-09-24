"""The staging pipeline stages a real table the same way for each caller's arguments."""

from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest
from sqlalchemy import text

from app.processing.ingest import metadata as ingest_metadata
from app.processing.ingest.tasks_staging import _run_staging_pipeline

pytestmark = pytest.mark.anyio


async def _table(session, columns: str, rows: list[str]) -> str:
    """``data.<name>`` with ``columns``, loaded with ``rows``, uncommitted."""
    name = f"stage_{uuid.uuid4().hex[:10]}"
    await session.execute(
        text(f"CREATE TABLE data.{name} (ogc_fid serial PRIMARY KEY, {columns})")
    )
    for row in rows:
        await session.execute(text(f"INSERT INTO data.{name} {row}"))
    return name


async def _columns(session, table: str) -> set[str]:
    result = await session.execute(
        text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = 'data' AND table_name = :t"
        ),
        {"t": table},
    )
    return set(result.scalars())


@pytest.fixture
async def session(test_db_session):
    """The test session, rolled back afterwards so no staged table outlives the test."""
    yield test_db_session
    await test_db_session.rollback()


@pytest.mark.parametrize("has_geometry", [None, True])
async def test_a_spatial_table_is_staged_whether_or_not_the_caller_knew(
    session, has_geometry: bool | None
) -> None:
    """An undeclared or known spatial table gets geom, geom_4326, metadata and samples."""
    table = await _table(
        session,
        "name text, _geolens_geom geometry(Point, 4326)",
        [
            "(name, _geolens_geom) VALUES ('a', ST_GeomFromText('POINT(1 2)', 4326))",
            "(name, _geolens_geom) VALUES ('b', ST_GeomFromText('POINT(3 4)', 4326))",
        ],
    )

    result = await _run_staging_pipeline(
        session, table_name=table, has_geometry=has_geometry, effective_srid=4326
    )

    assert result.has_geometry is True
    assert result.geometry_type == "POINT"
    assert {"geom", "geom_4326"} <= await _columns(session, table)
    assert result.metadata["feature_count"] == 2
    assert set(result.sample_values["name"]) == {"a", "b"}
    assert result.mercator_clip is not None


@pytest.mark.parametrize("has_geometry", [None, False])
async def test_a_non_spatial_table_skips_the_geometry_steps(
    session, has_geometry: bool | None
) -> None:
    """A table without geometry gets no render column and reports none."""
    table = await _table(session, "name text", ["(name) VALUES ('a')"])

    result = await _run_staging_pipeline(
        session, table_name=table, has_geometry=has_geometry, effective_srid=None
    )

    assert result.has_geometry is False
    assert result.geometry_type is None
    assert result.mercator_clip is None
    assert "geom_4326" not in await _columns(session, table)
    assert result.metadata["feature_count"] == 1


async def test_the_render_column_comes_from_the_given_srid(session) -> None:
    """geom_4326 reprojects geom from the SRID the caller passes."""
    table = await _table(
        session,
        "_geolens_geom geometry(Point, 3857)",
        [
            "(_geolens_geom) VALUES "
            "(ST_Transform(ST_GeomFromText('POINT(10 20)', 4326), 3857))"
        ],
    )

    await _run_staging_pipeline(
        session, table_name=table, has_geometry=None, effective_srid=3857
    )

    lon, lat = (
        await session.execute(
            text(f"SELECT ST_X(geom_4326), ST_Y(geom_4326) FROM data.{table}")
        )
    ).one()
    assert (round(lon, 6), round(lat, 6)) == (10.0, 20.0)


async def test_a_3d_point_table_gains_elev_in_its_metadata(session) -> None:
    """A 3D point table reports its z range and gains an elev column the samples see."""
    table = await _table(
        session,
        "_geolens_geom geometry(PointZ, 4326)",
        [
            "(_geolens_geom) VALUES (ST_GeomFromText('POINT Z (1 1 5)', 4326))",
            "(_geolens_geom) VALUES (ST_GeomFromText('POINT Z (2 2 40)', 4326))",
        ],
    )

    result = await _run_staging_pipeline(
        session, table_name=table, has_geometry=True, effective_srid=4326
    )

    assert (result.three_d["is_3d"], result.three_d["n_dims"]) == (True, 3)
    assert (result.three_d["z_min"], result.three_d["z_max"]) == (5.0, 40.0)
    assert "elev" in {column["name"] for column in result.metadata["column_info"]}
    assert set(result.sample_values["elev"]) == {"5", "40"}


async def test_the_staged_table_is_granted_to_the_tenant_reader(session) -> None:
    """The reader grant runs on the staged table with the tenant's schema and role."""
    table = await _table(session, "name text", ["(name) VALUES ('a')"])

    with patch.object(
        ingest_metadata,
        "grant_reader_access",
        wraps=ingest_metadata.grant_reader_access,
    ) as grant:
        await _run_staging_pipeline(
            session, table_name=table, has_geometry=False, effective_srid=None
        )

    grant.assert_awaited_once_with(session, table, schema="data", role="geolens_reader")
