"""A dataset's catalog facts come from measuring its feature table and projecting the result."""

from __future__ import annotations

import uuid
from dataclasses import replace

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import joinedload

import app.core.db as db_module
from app.core import record_types
from app.modules.catalog.datasets.domain.models import (
    Dataset,
    Record,
    RecordDistribution,
)
from app.modules.catalog.features.router import _require_feature_table
from app.modules.catalog.records.service import (
    create_distribution,
    generate_distributions,
)
from app.modules.catalog.search.service_records import build_assets
from app.platform.catalog_locks import lock_catalog_rows
from app.processing.ingest.catalog_projection import (
    Measurement,
    ProjectionRefused,
    _effective_geometry_type,
    measure,
    project,
    scored,
)
from app.processing.ingest.metadata import refresh_attribute_metadata
from app.processing.ingest.tasks_staging import StagingResult
from tests.factories import create_dataset, get_user_id

pytestmark = pytest.mark.anyio

_SPATIAL_PAIRS = {
    ("download", "gpkg"),
    ("download", "geojson"),
    ("download", "shp"),
    ("download", "parquet"),
    ("download", "csv"),
    ("download", "fgb"),
    ("download", "pmtiles"),
    ("ogc_features", "geojson"),
    ("vector_tiles", "pbf"),
}
_TABULAR_PAIRS = {("download", "csv"), ("ogc_features", "geojson")}
_POINTS = ["POINT(1 1)", "POINT(2 3)"]


async def _dataset(
    session,
    *,
    geometry_type: str | None,
    record_type: str,
    feature_count: int = 2,
    column_info: list[dict] | None = None,
) -> Dataset:
    """A private dataset with its generated distributions and attribute rows."""
    admin_id = await get_user_id(session, "admin")
    dataset = await create_dataset(
        session,
        created_by=admin_id,
        name="Catalog projection",
        visibility="private",
        geometry_type=geometry_type,
        record_type=record_type,
        feature_count=feature_count,
        column_info=column_info or [{"name": "name", "type": "text"}],
        spatial_extent_wkt="POLYGON((10 10, 10 11, 11 11, 11 10, 10 10))",
    )
    await generate_distributions(
        session,
        dataset.id,
        dataset.record_id,
        dataset.table_name,
        geometry_type=geometry_type,
    )
    await refresh_attribute_metadata(
        session,
        dataset.id,
        dataset.column_info,
        geometry_type=geometry_type,
    )
    await session.commit()
    return await _reload(session, dataset.id)


async def _table(
    session,
    name: str,
    *,
    geometry: str | None,
    wkts: list[str] = (),
    columns: str = "name text",
) -> None:
    """``data.<name>`` with ``columns`` and, unless ``geometry`` is None, geom columns."""
    spatial = (
        f", geom geometry({geometry}, 4326), geom_4326 geometry(Geometry, 4326)"
        if geometry is not None
        else ""
    )
    await session.execute(
        sa.text(
            f"CREATE TABLE data.{name} (gid serial PRIMARY KEY, {columns}{spatial})"
        )
    )
    for index, wkt in enumerate(wkts):
        await session.execute(
            sa.text(
                f"INSERT INTO data.{name} (name, geom, geom_4326) VALUES "
                "(:name, ST_GeomFromText(:wkt, 4326), "
                "ST_Force2D(ST_GeomFromText(:wkt, 4326)))"
            ),
            {"name": f"row {index}", "wkt": wkt},
        )
    await session.commit()


async def _drop(session, name: str) -> None:
    await session.rollback()
    await session.execute(sa.text(f"DROP TABLE IF EXISTS data.{name}"))
    await session.commit()


async def _reload(session, dataset_id: uuid.UUID) -> Dataset:
    session.expire_all()
    return (
        await session.execute(
            sa.select(Dataset)
            .options(joinedload(Dataset.record))
            .where(Dataset.id == dataset_id)
        )
    ).scalar_one()


async def _measure_and_project(session, dataset: Dataset, table: str) -> dict:
    """Measure ``table``, then project under the catalog lock, and commit."""
    measurement = await measure(session, dataset, table=table, schema="data")
    await lock_catalog_rows(
        session,
        dataset_cls=Dataset,
        record_cls=Record,
        dataset_id=dataset.id,
        record_id=dataset.record_id,
        lock_timeout=None,
    )
    diff = await project(session, dataset, measurement)
    await session.commit()
    return diff


async def _pairs(session, record_id: uuid.UUID) -> set[tuple[str, str]]:
    rows = await session.execute(
        sa.select(
            RecordDistribution.distribution_type, RecordDistribution.format
        ).where(RecordDistribution.record_id == record_id)
    )
    return {(row[0], row[1]) for row in rows}


async def _geom_row_is_current(session, dataset_id: uuid.UUID) -> bool | None:
    return await session.scalar(
        sa.text(
            "SELECT is_current FROM catalog.attribute_metadata "
            "WHERE dataset_id = :did AND field_name = 'geom'"
        ),
        {"did": dataset_id},
    )


async def _extent(session, record_id: uuid.UUID) -> str | None:
    return await session.scalar(
        sa.text("SELECT ST_AsText(spatial_extent) FROM catalog.records WHERE id = :id"),
        {"id": record_id},
    )


async def test_an_empty_table_with_a_declared_point_column_stays_a_point_dataset(
    test_db_session,
) -> None:
    """An empty table keeps its declared type and record type, with no extent."""
    session = test_db_session
    dataset = await _dataset(
        session, geometry_type="POINT", record_type="vector_dataset"
    )
    before = await _pairs(session, dataset.record_id)
    await _table(session, dataset.table_name, geometry="Point")
    try:
        await _measure_and_project(session, dataset, dataset.table_name)

        projected = await _reload(session, dataset.id)
        assert projected.geometry_type == "POINT"
        assert projected.record.record_type == "vector_dataset"
        assert projected.feature_count == 0
        assert await _extent(session, projected.record_id) is None
        assert await _pairs(session, projected.record_id) == before
        assert await _geom_row_is_current(session, projected.id) is True
        _require_feature_table(projected)
    finally:
        await _drop(session, dataset.table_name)


async def test_a_dropped_geometry_column_makes_the_dataset_a_table(
    test_db_session,
) -> None:
    """Without a geometry column the dataset becomes a table and loses its spatial rows."""
    session = test_db_session
    dataset = await _dataset(
        session, geometry_type="POINT", record_type="vector_dataset"
    )
    mine = await create_distribution(
        session,
        dataset.record_id,
        distribution_type="download",
        format="gpkg",
        url="https://example.org/mine.gpkg",
    )
    mine_id = mine.id
    await session.commit()
    await _table(session, dataset.table_name, geometry=None)
    await session.execute(
        sa.text(f"INSERT INTO data.{dataset.table_name} (name) VALUES ('a'), ('b')")
    )
    await session.commit()
    try:
        await _measure_and_project(session, dataset, dataset.table_name)

        projected = await _reload(session, dataset.id)
        assert projected.geometry_type is None
        assert projected.record.record_type == "table"
        assert await _geom_row_is_current(session, projected.id) is False
        # The user's own row survives on a pair the demote removes.
        assert await _pairs(session, projected.record_id) == _TABULAR_PAIRS | {
            ("download", "gpkg")
        }
        assert await session.get(RecordDistribution, mine_id) is not None
        assert projected.quality_detail["geometry_validity"] is None
        assert projected.quality_detail["crs_defined"] is None
        assets = build_assets(projected, "https://api.test")
        assert "vector_tiles" not in assets and "ogc_features" not in assets
    finally:
        await _drop(session, dataset.table_name)


@pytest.mark.parametrize(
    ("stored", "record_type", "expected"),
    [("POLYGON", "vector_dataset", "POLYGON"), (None, "table", "GEOMETRY")],
)
async def test_an_empty_generic_column_keeps_the_stored_type_or_says_geometry(
    test_db_session, stored: str | None, record_type: str, expected: str
) -> None:
    """An empty untyped column keeps the stored type, or GEOMETRY when none is stored."""
    session = test_db_session
    dataset = await _dataset(session, geometry_type=stored, record_type=record_type)
    await _table(session, dataset.table_name, geometry="Geometry")
    try:
        await _measure_and_project(session, dataset, dataset.table_name)

        projected = await _reload(session, dataset.id)
        assert projected.geometry_type == expected
        assert projected.record.record_type == "vector_dataset"
        _require_feature_table(projected)
    finally:
        await _drop(session, dataset.table_name)


async def test_3d_points_record_their_dimensions_and_z_range(test_db_session) -> None:
    """3D points record is_3d, n_dims and the z range, and no elev column is added."""
    session = test_db_session
    dataset = await _dataset(
        session, geometry_type="POINT", record_type="vector_dataset"
    )
    await _table(
        session,
        dataset.table_name,
        geometry="PointZ",
        wkts=["POINT Z (1 1 100)", "POINT Z (2 2 250.5)"],
    )
    try:
        await _measure_and_project(session, dataset, dataset.table_name)

        projected = await _reload(session, dataset.id)
        assert (projected.is_3d, projected.n_dims) == (True, 3)
        assert (projected.z_min, projected.z_max) == (100.0, 250.5)
        columns = await session.scalars(
            sa.text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = 'data' AND table_name = :t"
            ),
            {"t": dataset.table_name},
        )
        assert "elev" not in set(columns)
    finally:
        await _drop(session, dataset.table_name)


@pytest.mark.parametrize("wkts", [_POINTS, []], ids=["rows", "empty"])
async def test_a_table_that_gains_geometry_becomes_a_vector_dataset(
    test_db_session, wkts: list[str]
) -> None:
    """A table that gains a point column becomes a vector dataset with spatial rows."""
    session = test_db_session
    dataset = await _dataset(session, geometry_type=None, record_type="table")
    assert await _pairs(session, dataset.record_id) == _TABULAR_PAIRS
    await _table(session, dataset.table_name, geometry="Point", wkts=wkts)
    try:
        await _measure_and_project(session, dataset, dataset.table_name)

        projected = await _reload(session, dataset.id)
        assert projected.geometry_type == "POINT"
        assert projected.record.record_type == "vector_dataset"
        assert await _pairs(session, projected.record_id) == _SPATIAL_PAIRS
        assert await _geom_row_is_current(session, projected.id) is True
        assert projected.quality_detail["geometry_validity"] is not None
        assert "vector_tiles" in build_assets(projected, "https://api.test")
    finally:
        await _drop(session, dataset.table_name)


async def _assert_refused_without_a_write(
    session,
    dataset: Dataset,
    table: str,
    *,
    score: bool = True,
    error: type[Exception] = ProjectionRefused,
):
    measurement = await measure(
        session, dataset, table=table, schema="data", score=score
    )
    with pytest.raises(error):
        await project(session, dataset, measurement)
    # Flushed so that anything project assigned before refusing shows below.
    await session.flush()
    row = (
        await session.execute(
            sa.text(
                "SELECT d.geometry_type, d.feature_count, r.record_type "
                "FROM catalog.datasets d JOIN catalog.records r ON r.id = d.record_id "
                "WHERE d.id = :id"
            ),
            {"id": dataset.id},
        )
    ).one()
    return tuple(row), await _geom_row_is_current(session, dataset.id)


@pytest.mark.parametrize(
    "record_type", ["raster_dataset", "vrt_dataset", "tiles3d_dataset"]
)
async def test_a_record_without_a_feature_table_is_refused_before_anything_is_written(
    test_db_session, record_type: str
) -> None:
    """A dataset without a feature table is refused, and nothing about it changes."""
    session = test_db_session
    dataset = await _dataset(session, geometry_type="POINT", record_type=record_type)
    await _table(session, dataset.table_name, geometry=None)
    try:
        row, geom_current = await _assert_refused_without_a_write(
            session, dataset, dataset.table_name
        )
        assert row == ("POINT", 2, record_type)
        assert geom_current is True
    finally:
        await _drop(session, dataset.table_name)


async def test_a_record_type_missing_from_the_table_is_refused(
    test_db_session, monkeypatch
) -> None:
    """A record type the capability table does not list is refused, and nothing changes."""
    session = test_db_session
    dataset = await _dataset(
        session, geometry_type="POINT", record_type="vector_dataset"
    )
    await _table(session, dataset.table_name, geometry=None)
    monkeypatch.delitem(record_types._CAPABILITIES, "vector_dataset")
    try:
        row, geom_current = await _assert_refused_without_a_write(
            session, dataset, dataset.table_name
        )
        assert row == ("POINT", 2, "vector_dataset")
        assert geom_current is True
    finally:
        await _drop(session, dataset.table_name)


async def test_an_unscored_measurement_is_refused_before_anything_is_written(
    test_db_session,
) -> None:
    """A measurement taken without scoring is refused, and nothing changes."""
    session = test_db_session
    dataset = await _dataset(
        session, geometry_type="POINT", record_type="vector_dataset"
    )
    await _table(session, dataset.table_name, geometry=None)
    try:
        row, geom_current = await _assert_refused_without_a_write(
            session, dataset, dataset.table_name, score=False, error=ValueError
        )
        assert row == ("POINT", 2, "vector_dataset")
        assert geom_current is True
    finally:
        await _drop(session, dataset.table_name)


async def test_scoring_after_the_measurement_scores_the_measured_table(
    test_db_session,
) -> None:
    """scored() adds the quality of the table measure read and changes nothing else."""
    session = test_db_session
    dataset = await _dataset(session, geometry_type=None, record_type="table")
    await _table(session, dataset.table_name, geometry="Point", wkts=_POINTS)
    try:
        unscored = await measure(
            session, dataset, table=dataset.table_name, schema="data", score=False
        )
        assert unscored.quality_detail is None

        measurement = await scored(
            session, dataset, unscored, table=dataset.table_name, schema="data"
        )

        assert measurement.quality_detail["geometry_validity"] == 100.0
        assert measurement.quality_detail["crs_defined"] == 100.0
        assert replace(measurement, quality_detail=None) == unscored
    finally:
        await _drop(session, dataset.table_name)


async def test_the_diff_compares_stored_columns_with_the_measured_ones(
    test_db_session,
) -> None:
    """The returned diff compares the stored columns and count with the table's."""
    session = test_db_session
    dataset = await _dataset(
        session,
        geometry_type="POINT",
        record_type="vector_dataset",
        feature_count=5,
        column_info=[{"name": "retired", "type": "text"}],
    )
    await _table(
        session,
        dataset.table_name,
        geometry="Point",
        wkts=_POINTS,
        columns="name text, population integer",
    )
    try:
        diff = await _measure_and_project(session, dataset, dataset.table_name)

        assert [c["name"] for c in diff["columns_added"]] == ["name", "population"]
        assert [c["name"] for c in diff["columns_removed"]] == ["retired"]
        assert (diff["row_count_old"], diff["row_count_new"]) == (5, 2)
        projected = await _reload(session, dataset.id)
        assert [c["name"] for c in projected.column_info] == ["name", "population"]
    finally:
        await _drop(session, dataset.table_name)


async def test_the_diff_reads_the_stored_values_under_the_lock(test_db_session) -> None:
    """A count committed after the dataset was loaded is the diff's old count."""
    session = test_db_session
    dataset = await _dataset(
        session, geometry_type="POINT", record_type="vector_dataset"
    )
    await _table(session, dataset.table_name, geometry="Point", wkts=_POINTS)
    try:
        measurement = await measure(
            session, dataset, table=dataset.table_name, schema="data"
        )
        async with db_module.async_session() as editor:
            await editor.execute(
                sa.text("UPDATE catalog.datasets SET feature_count = 9 WHERE id = :id"),
                {"id": dataset.id},
            )
            await editor.commit()
        await lock_catalog_rows(
            session,
            dataset_cls=Dataset,
            record_cls=Record,
            dataset_id=dataset.id,
            record_id=dataset.record_id,
            lock_timeout=None,
        )

        diff = await project(session, dataset, measurement)

        assert (diff["row_count_old"], diff["row_count_new"]) == (9, 2)
    finally:
        await _drop(session, dataset.table_name)


async def test_a_staging_result_is_reused_rather_than_read_again(
    test_db_session, monkeypatch
) -> None:
    """With a staging result, measure takes its metadata, samples and 3D facts."""
    session = test_db_session
    dataset = await _dataset(
        session, geometry_type="POINT", record_type="vector_dataset"
    )
    await _table(session, dataset.table_name, geometry="Point", wkts=_POINTS)

    async def _unexpected(*args, **kwargs):
        raise AssertionError("measure read what the staging result already held")

    for name in ("extract_metadata", "get_sample_values", "detect_3d_metadata"):
        monkeypatch.setattr(f"app.processing.ingest.metadata.{name}", _unexpected)
    staged = StagingResult(
        metadata={
            "srid": 4326,
            "geometry_type": "POINT",
            "feature_count": 2,
            "extent_wkt": None,
            "column_info": [{"name": "name", "type": "text"}],
        },
        sample_values={"name": ["row 0", "row 1"]},
        three_d={"is_3d": False, "n_dims": 2, "z_min": None, "z_max": None},
        has_geometry=True,
        geometry_type="POINT",
    )
    try:
        measurement = await measure(
            session, dataset, table=dataset.table_name, schema="data", staged=staged
        )

        assert isinstance(measurement, Measurement)
        assert measurement.metadata is staged.metadata
        assert measurement.sample_values is staged.sample_values
        assert measurement.three_d is staged.three_d
        assert measurement.geometry_type == "POINT"
    finally:
        await _drop(session, dataset.table_name)


@pytest.mark.parametrize(
    ("measured", "declared", "stored", "expected"),
    [
        ("POINT", "GEOMETRY", "MULTIPOLYGON", "POINT"),
        ("POINT", None, None, "POINT"),
        (None, "MULTIPOLYGON", "POINT", "MULTIPOLYGON"),
        (None, "GEOMETRY", "POINT", "POINT"),
        (None, "GEOMETRY", None, "GEOMETRY"),
        (None, None, "POINT", None),
        (None, None, None, None),
    ],
)
def test_the_effective_geometry_type_prefers_a_row_then_the_declaration(
    measured: str | None, declared: str | None, stored: str | None, expected: str | None
) -> None:
    """A sampled row wins, then a specific declaration, then the stored type."""
    assert (
        _effective_geometry_type(measured=measured, declared=declared, stored=stored)
        == expected
    )
