"""Measurement: area and length as computed columns (#954).

One test per acceptance criterion on the issue.

Requirements:
  - Docker database must be running (docker compose up db)
"""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.analysis_sql import MAX_SOURCE_FEATURES
from app.processing.analysis.tasks import _materialize

from tests.factories import get_user_id
from tests.test_analysis_materialize import _create_job
from tests.test_analysis_spatial_join import _create_layer

# 1 degree of latitude is ~111.32 km; a 1x1 degree box at the equator is
# therefore ~1.23e10 m². The tolerance is deliberately loose (2%) because the
# exact value depends on the spheroid, and the point of the assertion is that
# the number is a real geodesic measure rather than degrees-squared.
TOLERANCE = 0.02


def _preview_url(dataset_id) -> str:
    return f"/datasets/{dataset_id}/analysis/preview/"


def _materialize_url(dataset_id) -> str:
    return f"/datasets/{dataset_id}/analysis/materialize/"


class TestMeasurePreview:
    async def test_area_and_length_match_postgis_ground_truth(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """Criterion 2: both measures match an independently computed number.

        Ground truth comes from PostGIS itself rather than a hardcoded
        constant, so the assertion pins the operation's plumbing (right column,
        right geometry, geography not planar) instead of re-deriving spheroid
        maths in the test.
        """
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_layer(
            test_db_session,
            created_by=admin_id,
            column_type="Geometry",
            geometry_type="POLYGON",
            values_sql=(
                "('box', ST_MakeEnvelope(0,0,1,1,4326), ST_MakeEnvelope(0,0,1,1,4326)),"
                "('line',"
                " ST_GeomFromText('LINESTRING(0 0, 1 0)', 4326),"
                " ST_GeomFromText('LINESTRING(0 0, 1 0)', 4326))"
            ),
            feature_count=2,
        )

        resp = await client.post(
            _preview_url(ds.id),
            json={"operation": "measure"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 200, resp.text
        got = {
            f["properties"]["gid"]: (
                f["properties"]["area_sqm"],
                f["properties"]["length_m"],
            )
            for f in resp.json()["geojson"]["features"]
        }

        expected = {
            gid: (a, ln)
            for gid, a, ln in (
                await test_db_session.execute(
                    text(
                        f"SELECT gid, ST_Area(geom_4326::geography), "  # noqa: S608
                        f"ST_Length(geom_4326::geography) "
                        f"FROM data.{ds.table_name} ORDER BY gid"
                    )
                )
            ).all()
        }
        assert set(got) == set(expected)
        for gid, (area, length) in got.items():
            exp_area, exp_length = expected[gid]
            assert area == pytest.approx(exp_area, rel=1e-6)
            assert length == pytest.approx(exp_length, rel=1e-6)

        # The polygon has area and no length; the line the reverse. Both
        # columns are emitted for both rows (see render_measure_columns on why
        # the catalog's geometry_type is not trusted to pick one).
        assert got[1][0] > 0 and got[1][1] == 0
        assert got[2][0] == 0 and got[2][1] > 0
        # Sanity that this is metres, not degrees: a 1x1 degree box at the
        # equator is ~1.23e10 m2, which degrees-squared (1.0) would never be.
        assert got[1][0] == pytest.approx(1.23e10, rel=TOLERANCE)

    async def test_antimeridian_polygon_measures_correctly(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """Criterion 5: a polygon crossing +/-180 measures as the small box it
        is, not the ~359-degree-wide one its planar envelope suggests.

        This is the whole reason the renderer casts to geography. The same
        shape measured planar spans nearly the globe.
        """
        admin_id = await get_user_id(test_db_session, "admin")
        # 2 degrees wide, straddling the seam: 179 -> -179.
        ds = await _create_layer(
            test_db_session,
            created_by=admin_id,
            column_type="Geometry",
            geometry_type="POLYGON",
            values_sql=(
                "('seam',"
                " ST_GeomFromText('POLYGON((179 0, 179 1, -179 1, -179 0, 179 0))',"
                " 4326),"
                " ST_GeomFromText('POLYGON((179 0, 179 1, -179 1, -179 0, 179 0))',"
                " 4326))"
            ),
        )

        resp = await client.post(
            _preview_url(ds.id),
            json={"operation": "measure"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 200, resp.text
        area = resp.json()["geojson"]["features"][0]["properties"]["area_sqm"]

        # A 2x1 degree box near the equator is ~2.46e10 m2. The planar reading
        # of the same ring is 358 degrees wide — a different answer by two
        # orders of magnitude, which is what this pins against.
        assert area == pytest.approx(2 * 1.23e10, rel=0.05)
        planar_degrees = (
            await test_db_session.execute(
                text(f"SELECT ST_Area(geom_4326) FROM data.{ds.table_name}")  # noqa: S608
            )
        ).scalar_one()
        assert planar_degrees > 300, "fixture must actually straddle the seam"

    async def test_null_and_empty_geometries_produce_no_feature(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """Criterion 4: the decided value for a NULL/empty source geometry in
        the PREVIEW is 'no feature at all' — not a zero, and not a null-valued
        row.

        That is the answer that agrees with materialize, where _wrap_not_empty
        and the post-CTAS DELETE remove those rows outright, so the saved
        dataset and the approved preview describe the same set of features.
        """
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_layer(
            test_db_session,
            created_by=admin_id,
            column_type="Geometry",
            geometry_type="POLYGON",
            values_sql=(
                "('real', ST_MakeEnvelope(0,0,1,1,4326), ST_MakeEnvelope(0,0,1,1,4326)),"
                "('nullgeom', NULL, NULL),"
                "('empty',"
                " ST_GeomFromText('POLYGON EMPTY', 4326),"
                " ST_GeomFromText('POLYGON EMPTY', 4326))"
            ),
            feature_count=3,
        )

        resp = await client.post(
            _preview_url(ds.id),
            json={"operation": "measure"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 200, resp.text
        features = resp.json()["geojson"]["features"]
        assert [f["properties"]["gid"] for f in features] == [1]
        assert resp.json()["feature_count"] == 1


class TestMeasureEnqueue:
    async def test_generated_column_collision_rejected(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """Criterion 3, mirroring dissolve's source_count guard."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_layer(
            test_db_session,
            created_by=admin_id,
            column_type="Geometry",
            geometry_type="POLYGON",
            extra_columns="area_sqm DOUBLE PRECISION,",
            values_sql=(
                "('box', 1.0, ST_MakeEnvelope(0,0,1,1,4326),"
                " ST_MakeEnvelope(0,0,1,1,4326))"
            ),
            column_info=[
                {"name": "name", "type": "text"},
                {"name": "area_sqm", "type": "double precision"},
            ],
        )

        resp = await client.post(
            _materialize_url(ds.id),
            json={"operation": "measure", "title": "Nope"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 422
        assert "area_sqm" in resp.text

    async def test_oversized_source_rejected_at_enqueue(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """Criterion 6: measure has a MAX_SOURCE_FEATURES entry that fires.

        Without the entry the router's .get() skips the gate entirely rather
        than applying a default, so the operation would have NO ceiling.
        """
        assert "measure" in MAX_SOURCE_FEATURES
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_layer(
            test_db_session,
            created_by=admin_id,
            column_type="Geometry",
            geometry_type="POLYGON",
            values_sql=(
                "('box', ST_MakeEnvelope(0,0,1,1,4326), ST_MakeEnvelope(0,0,1,1,4326))"
            ),
        )
        ds.feature_count = MAX_SOURCE_FEATURES["measure"] + 1
        await test_db_session.commit()

        resp = await client.post(
            _materialize_url(ds.id),
            json={"operation": "measure", "title": "Too big"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 422
        assert "too large" in resp.text


class TestMeasureWorker:
    async def test_materialize_carries_the_measured_columns(
        self,
        test_db_session: AsyncSession,
    ):
        """The saved dataset carries both measures and agrees with the preview
        renderer, since both go through render_measure_columns."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_layer(
            test_db_session,
            created_by=admin_id,
            column_type="Geometry",
            geometry_type="POLYGON",
            values_sql=(
                "('box', ST_MakeEnvelope(0,0,1,1,4326),"
                " ST_MakeEnvelope(0,0,1,1,4326)),"
                "('nullgeom', NULL, NULL)"
            ),
            feature_count=2,
        )
        job = await _create_job(test_db_session, admin_id)

        await _materialize(
            job_id=str(job.id),
            dataset_id=str(ds.id),
            user_id=str(admin_id),
            operation="measure",
            title=f"Measured {uuid.uuid4().hex[:6]}",
        )

        await test_db_session.refresh(job)
        assert job.status == "complete", job.error_message

        from app.modules.catalog.datasets.domain.models import Dataset

        new_ds = await test_db_session.get(Dataset, job.dataset_id)
        assert new_ds is not None
        # The NULL-geometry row is gone, so criterion 4 needs no materialize
        # fixture of its own.
        assert new_ds.feature_count == 1
        assert new_ds.geometry_type == "POLYGON"

        rows = (
            await test_db_session.execute(
                text(
                    f"SELECT name, area_sqm, length_m FROM data.{new_ds.table_name}"  # noqa: S608
                )
            )
        ).all()
        assert len(rows) == 1
        name, area, length = rows[0]
        assert name == "box"
        assert area == pytest.approx(1.23e10, rel=TOLERANCE)
        assert length == 0
