"""fix(#934): per-dataset extent producers must not fold a crossing table naively.

Since #888 shifts a 0..360 Pacific source onto both sides of the antimeridian
instead of clipping it, an ordinary ingest can produce a table whose naive
``ST_Extent`` reads -170..170 — a 340-degree bbox for a 100-degree footprint.
The producer sites (``ingest/metadata_extent.py`` ``get_extent`` /
``extract_metadata`` and ``catalog/features/service.py``
``_refresh_count_and_extent``) now emit the two-ring MULTIPOLYGON via
``bbox_to_extent_wkt`` when the honest extent crosses
the seam, and stay byte-identical otherwise.

Requires the Docker test database.
"""

import uuid

import pytest
from geoalchemy2 import WKTElement
from sqlalchemy import text

from app.core.geo import extent_to_bbox
from app.modules.catalog.features.service import _refresh_count_and_extent
from app.processing.ingest.metadata import extract_metadata, get_extent

pytestmark = pytest.mark.anyio

# A 150..250 (0..360 convention) Pacific source after the #888 shift: two
# points on each side of the seam. Honest footprint: lon 150 .. -110.
PACIFIC_POINTS = [(150.0, -10.0), (170.0, 0.0), (-170.0, 5.0), (-110.0, 10.0)]
PACIFIC_SPEC_BBOX = [150.0, -10.0, -110.0, 10.0]

# Europe spanning the prime meridian — the footprint that a bare
# per-vertex shift tears apart. Must never move.
EUROPE_POINTS = [(-10.0, 40.0), (30.0, 55.0)]


async def _make_table(session, points):
    table = f"ext_prod_934_{uuid.uuid4().hex[:10]}"
    await session.execute(
        text(
            f"CREATE TABLE data.{table} ("
            "gid serial PRIMARY KEY, geom geometry(Point, 4326), "
            "geom_4326 geometry(Point, 4326))"
        )
    )
    for x, y in points:
        await session.execute(
            text(
                f"INSERT INTO data.{table} (geom, geom_4326) VALUES "
                "(ST_SetSRID(ST_MakePoint(:x, :y), 4326), "
                " ST_SetSRID(ST_MakePoint(:x, :y), 4326))"
            ).bindparams(x=x, y=y)
        )
    await session.commit()
    return table


async def _drop_table(session, table):
    await session.execute(text(f"DROP TABLE IF EXISTS data.{table}"))
    await session.commit()


async def _naive_extent_wkt(session, table):
    """The pre-#934 producer output, for byte-identity assertions."""
    return (
        await session.execute(
            text(
                f"SELECT CASE "
                f"  WHEN ext IS NULL THEN NULL "
                f"  WHEN GeometryType(ext::geometry) = 'POLYGON' "
                f"    THEN ST_AsText(ST_SetSRID(ext::geometry, 4326)) "
                f"  ELSE ST_AsText(ST_Expand(ST_SetSRID(ext::geometry, 4326), 1e-9)) "
                f"END FROM (SELECT ST_Extent(geom_4326) AS ext FROM data.{table}) s"
            )
        )
    ).scalar_one_or_none()


def _spec_bbox(wkt: str) -> list[float] | None:
    return extent_to_bbox(WKTElement(wkt, srid=4326))


class TestGetExtent:
    async def test_pacific_crossing_table_stores_two_ring_extent(self, test_db_session):
        table = await _make_table(test_db_session, PACIFIC_POINTS)
        try:
            wkt = await get_extent(test_db_session, table)
            assert wkt is not None
            assert wkt.startswith("MULTIPOLYGON")
            assert _spec_bbox(wkt) == pytest.approx(PACIFIC_SPEC_BBOX)
        finally:
            await _drop_table(test_db_session, table)

    async def test_prime_meridian_europe_is_byte_identical(self, test_db_session):
        table = await _make_table(test_db_session, EUROPE_POINTS)
        try:
            wkt = await get_extent(test_db_session, table)
            assert wkt == await _naive_extent_wkt(test_db_session, table)
        finally:
            await _drop_table(test_db_session, table)

    async def test_wide_but_not_crossing_table_is_byte_identical(self, test_db_session):
        # Width > 180 forces the second (two-domain) aggregate to run, but the
        # normal domain still wins (largest gap is across the seam, 160 deg,
        # so the shifted span of 260 loses to the normal 200) — output must
        # not change.
        table = await _make_table(
            test_db_session, [(-100.0, 0.0), (0.0, 5.0), (100.0, 10.0)]
        )
        try:
            wkt = await get_extent(test_db_session, table)
            assert wkt == await _naive_extent_wkt(test_db_session, table)
        finally:
            await _drop_table(test_db_session, table)

    async def test_positive_seam_edge_still_covers_the_stored_row(
        self, test_db_session
    ):
        """fix(#934 codex r2): features at +180 and -170. The winning shifted
        fold is west == 180, whose west..180 half has zero width;
        ``bbox_to_extent_wkt`` drops such halves, which would leave only the
        -180..-170 lobe — and that ring does not contain the row stored at the
        literal planar +180. The producer pads the +180 edge to a sliver first,
        so both planar representations of the seam stay covered."""
        table = await _make_table(test_db_session, [(180.0, -10.0), (-170.0, 10.0)])
        try:
            wkt = await get_extent(test_db_session, table)
            assert wkt is not None
            assert wkt.startswith("MULTIPOLYGON")
            covered = (
                await test_db_session.execute(
                    text(
                        f"SELECT count(*) FROM data.{table} t "
                        "WHERE ST_Intersects(t.geom_4326, "
                        "ST_GeomFromText(:wkt, 4326))"
                    ).bindparams(wkt=wkt)
                )
            ).scalar_one()
            assert covered == 2, "the extent must cover every row it describes"
            bbox = _spec_bbox(wkt)
            assert bbox is not None
            assert bbox[0] == pytest.approx(180.0, abs=1e-6)
            assert bbox[2] == pytest.approx(-170.0)
            assert bbox[0] > bbox[2]
        finally:
            await _drop_table(test_db_session, table)

    async def test_negative_seam_edge_still_reads_as_crossing(self, test_db_session):
        """fix(#934 codex r3): features at -180 and 170. ST_ShiftLongitude
        maps the stored -180 to +180, so the winning shifted fold read as the
        apparently non-crossing [170..180] and the producer fell back to the
        naive 350-degree extent. The helper re-expresses it as the crossing
        form, with the -180 lobe padded to a sliver covering the stored
        planar representation."""
        table = await _make_table(test_db_session, [(-180.0, -10.0), (170.0, 10.0)])
        try:
            wkt = await get_extent(test_db_session, table)
            assert wkt is not None
            assert wkt.startswith("MULTIPOLYGON")
            bbox = _spec_bbox(wkt)
            assert bbox is not None
            assert bbox[0] == pytest.approx(170.0)
            assert bbox[2] == pytest.approx(-180.0, abs=1e-6)
            assert bbox[0] > bbox[2]
        finally:
            await _drop_table(test_db_session, table)

    async def test_degenerate_single_point_is_still_padded(self, test_db_session):
        table = await _make_table(test_db_session, [(179.9, -17.0)])
        try:
            wkt = await get_extent(test_db_session, table)
            assert wkt is not None
            assert wkt.startswith("POLYGON")
            assert wkt == await _naive_extent_wkt(test_db_session, table)
        finally:
            await _drop_table(test_db_session, table)

    async def test_empty_table_returns_none(self, test_db_session):
        table = await _make_table(test_db_session, [])
        try:
            assert await get_extent(test_db_session, table) is None
        finally:
            await _drop_table(test_db_session, table)


class TestExtractMetadata:
    async def test_cte_fast_path_emits_two_ring_extent(self, test_db_session):
        table = await _make_table(test_db_session, PACIFIC_POINTS)
        try:
            meta = await extract_metadata(test_db_session, table)
            assert meta["feature_count"] == len(PACIFIC_POINTS)
            wkt = meta["extent_wkt"]
            assert wkt is not None
            assert wkt.startswith("MULTIPOLYGON")
            assert _spec_bbox(wkt) == pytest.approx(PACIFIC_SPEC_BBOX)
        finally:
            await _drop_table(test_db_session, table)

    async def test_cte_fast_path_non_crossing_is_byte_identical(self, test_db_session):
        table = await _make_table(test_db_session, EUROPE_POINTS)
        try:
            meta = await extract_metadata(test_db_session, table)
            assert meta["extent_wkt"] == await _naive_extent_wkt(test_db_session, table)
        finally:
            await _drop_table(test_db_session, table)


class TestRefreshCountAndExtent:
    """The feature-write refresh path recomputes the same producer extent."""

    async def test_refresh_emits_two_ring_extent(self, test_db_session):
        table = await _make_table(test_db_session, PACIFIC_POINTS)
        try:
            count, wkt = await _refresh_count_and_extent(test_db_session, table)
            assert count == len(PACIFIC_POINTS)
            assert wkt is not None
            assert wkt.startswith("MULTIPOLYGON")
            assert _spec_bbox(wkt) == pytest.approx(PACIFIC_SPEC_BBOX)
        finally:
            await _drop_table(test_db_session, table)

    async def test_refresh_non_crossing_is_byte_identical(self, test_db_session):
        table = await _make_table(test_db_session, EUROPE_POINTS)
        try:
            _, wkt = await _refresh_count_and_extent(test_db_session, table)
            assert wkt == await _naive_extent_wkt(test_db_session, table)
        finally:
            await _drop_table(test_db_session, table)

    async def test_refresh_degenerate_point_is_still_padded(self, test_db_session):
        table = await _make_table(test_db_session, [(0.0, 0.0)])
        try:
            count, wkt = await _refresh_count_and_extent(test_db_session, table)
            assert count == 1
            assert wkt is not None
            assert wkt.startswith("POLYGON")
        finally:
            await _drop_table(test_db_session, table)


class TestCreateDatasetSink:
    """fix(#934 codex r1): the dataset-creation sink accepted only POLYGON
    extents, so a first-ingest two-ring MULTIPOLYGON silently became a NULL
    ``Record.spatial_extent``."""

    async def test_two_ring_extent_survives_dataset_creation(self, test_db_session):
        from geoalchemy2.shape import to_shape as _to_shape  # noqa: F401

        from app.modules.catalog.datasets.domain.service import create_dataset
        from tests.factories import get_user_id

        admin_id = await get_user_id(test_db_session, "admin")
        two_ring = (
            "MULTIPOLYGON(((150 -10,180 -10,180 10,150 10,150 -10)),"
            "((-180 -10,-110 -10,-110 10,-180 10,-180 -10)))"
        )
        dataset = await create_dataset(
            test_db_session,
            table_name=f"ext_sink_934_{uuid.uuid4().hex[:10]}",
            title="Crossing extent sink test",
            created_by=admin_id,
            srid=4326,
            geometry_type="Point",
            feature_count=4,
            extent_wkt=two_ring,
            source_format="geojson",
        )
        await test_db_session.commit()
        await test_db_session.refresh(dataset.record)
        assert dataset.record.spatial_extent is not None
        bbox = extent_to_bbox(dataset.record.spatial_extent)
        assert bbox == pytest.approx([150.0, -10.0, -110.0, 10.0])
