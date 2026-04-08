"""Integration tests for feature CRUD (INSERT, UPDATE, DELETE) endpoints.

Tests use a manually created PostGIS table in the data schema to avoid
dependency on the layer creation endpoint (Plan 01).
"""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import text

from app.datasets.models import Dataset, Record

from tests.factories import get_user_id


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _create_test_table_and_dataset(
    session,
    *,
    created_by: uuid.UUID,
    table_name: str | None = None,
    geometry_type: str = "POINT",
    visibility: str = "public",
) -> Dataset:
    """Create a PostGIS data table and register it as a dataset.

    Returns the Dataset record. The table has geom, geom_4326, name, and
    status columns.
    """
    if table_name is None:
        table_name = f"test_crud_{uuid.uuid4().hex[:8]}"

    pg_geom_type = geometry_type.title().replace(" ", "")

    await session.execute(
        text(
            f"CREATE TABLE IF NOT EXISTS data.{table_name} ("
            f"gid SERIAL PRIMARY KEY, "
            f"geom geometry({pg_geom_type}, 4326), "
            f"geom_4326 geometry(Geometry, 4326), "
            f"name TEXT, "
            f"status TEXT)"
        )
    )
    await session.execute(text(f"GRANT SELECT ON data.{table_name} TO geolens_reader"))

    record = Record(
        title=f"Test CRUD Layer {table_name}",
        visibility=visibility,
        record_status="published",
        created_by=created_by,
    )
    session.add(record)
    await session.flush()
    dataset = Dataset(
        record_id=record.id,
        table_name=table_name,
        srid=4326,
        geometry_type=geometry_type,
        feature_count=0,
        column_info=[
            {"name": "name", "type": "text"},
            {"name": "status", "type": "text"},
        ],
        source_format="created",
    )
    session.add(dataset)
    await session.commit()
    await session.refresh(dataset)
    return dataset


async def _cleanup_table(session, table_name: str) -> None:
    """Drop a test data table."""
    await session.execute(text(f"DROP TABLE IF EXISTS data.{table_name}"))
    await session.commit()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def test_layer(client: AsyncClient, test_db_session, admin_auth_header):
    """Create a Point layer for testing feature CRUD."""
    admin_id = await get_user_id(test_db_session, "admin")
    dataset = await _create_test_table_and_dataset(
        test_db_session,
        created_by=admin_id,
        geometry_type="POINT",
    )
    # Capture identifiers before yield (attributes may expire during tests)
    tbl = dataset.table_name
    rec_id = dataset.record_id
    yield dataset
    await _cleanup_table(test_db_session, tbl)
    await test_db_session.execute(
        text("DELETE FROM catalog.records WHERE id = :id"),
        {"id": rec_id},
    )
    await test_db_session.commit()


@pytest.fixture
async def polygon_layer(client: AsyncClient, test_db_session, admin_auth_header):
    """Create a Polygon layer for geometry type mismatch testing."""
    admin_id = await get_user_id(test_db_session, "admin")
    dataset = await _create_test_table_and_dataset(
        test_db_session,
        created_by=admin_id,
        geometry_type="POLYGON",
    )
    tbl = dataset.table_name
    rec_id = dataset.record_id
    yield dataset
    await _cleanup_table(test_db_session, tbl)
    await test_db_session.execute(
        text("DELETE FROM catalog.records WHERE id = :id"),
        {"id": rec_id},
    )
    await test_db_session.commit()


@pytest.fixture
async def multipolygon_layer(client: AsyncClient, test_db_session, admin_auth_header):
    """Create a MultiPolygon layer for ST_Multi promotion testing."""
    admin_id = await get_user_id(test_db_session, "admin")
    dataset = await _create_test_table_and_dataset(
        test_db_session,
        created_by=admin_id,
        geometry_type="MULTIPOLYGON",
    )
    tbl = dataset.table_name
    rec_id = dataset.record_id
    yield dataset
    await _cleanup_table(test_db_session, tbl)
    await test_db_session.execute(
        text("DELETE FROM catalog.records WHERE id = :id"),
        {"id": rec_id},
    )
    await test_db_session.commit()


POINT_GEOJSON = {
    "type": "Point",
    "coordinates": [-73.9857, 40.7484],
}

POINT_GEOJSON_2 = {
    "type": "Point",
    "coordinates": [-118.2437, 34.0522],
}

POLYGON_GEOJSON = {
    "type": "Polygon",
    "coordinates": [
        [
            [-73.99, 40.74],
            [-73.98, 40.74],
            [-73.98, 40.75],
            [-73.99, 40.75],
            [-73.99, 40.74],
        ]
    ],
}

MULTIPOLYGON_GEOJSON = {
    "type": "MultiPolygon",
    "coordinates": [
        [
            [
                [-73.99, 40.74],
                [-73.98, 40.74],
                [-73.98, 40.75],
                [-73.99, 40.75],
                [-73.99, 40.74],
            ]
        ],
        [
            [
                [-74.01, 40.71],
                [-74.00, 40.71],
                [-74.00, 40.72],
                [-74.01, 40.72],
                [-74.01, 40.71],
            ]
        ],
    ],
}


# ---------------------------------------------------------------------------
# INSERT tests
# ---------------------------------------------------------------------------


class TestInsertFeature:
    async def test_insert_feature(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_layer: Dataset,
    ):
        """POST a Point feature with properties. Assert 201 and GeoJSON response."""
        resp = await client.post(
            f"/datasets/{test_layer.id}/features/",
            json={
                "geometry": POINT_GEOJSON,
                "properties": {"name": "Empire State", "status": "active"},
            },
            headers=admin_auth_header,
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["type"] == "Feature"
        assert data["id"] is not None
        assert data["geometry"]["type"] == "Point"
        assert data["properties"]["name"] == "Empire State"
        assert data["properties"]["status"] == "active"

    async def test_insert_feature_wrong_geometry_type(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_layer: Dataset,
    ):
        """POST a Polygon to a Point layer. Assert 400."""
        resp = await client.post(
            f"/datasets/{test_layer.id}/features/",
            json={
                "geometry": POLYGON_GEOJSON,
                "properties": {"name": "Bad Shape"},
            },
            headers=admin_auth_header,
        )
        assert resp.status_code == 400
        assert "mismatch" in resp.json()["detail"].lower()

    async def test_insert_feature_viewer_forbidden(
        self,
        client: AsyncClient,
        viewer_auth_header: dict,
        test_layer: Dataset,
    ):
        """POST as viewer. Assert 403."""
        resp = await client.post(
            f"/datasets/{test_layer.id}/features/",
            json={
                "geometry": POINT_GEOJSON,
                "properties": {"name": "Forbidden"},
            },
            headers=viewer_auth_header,
        )
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# REPLACE (PUT) tests
# ---------------------------------------------------------------------------


class TestReplaceFeature:
    async def test_replace_feature(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_layer: Dataset,
    ):
        """Insert then PUT with new geometry and properties."""
        # Insert first
        create_resp = await client.post(
            f"/datasets/{test_layer.id}/features/",
            json={
                "geometry": POINT_GEOJSON,
                "properties": {"name": "Original", "status": "draft"},
            },
            headers=admin_auth_header,
        )
        assert create_resp.status_code == 201
        gid = create_resp.json()["id"]

        # Replace
        resp = await client.put(
            f"/datasets/{test_layer.id}/features/{gid}",
            json={
                "geometry": POINT_GEOJSON_2,
                "properties": {"name": "Replaced", "status": "final"},
            },
            headers=admin_auth_header,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["geometry"]["coordinates"][0] == pytest.approx(-118.2437, abs=0.001)
        assert data["properties"]["name"] == "Replaced"
        assert data["properties"]["status"] == "final"


# ---------------------------------------------------------------------------
# UPDATE (PATCH) tests
# ---------------------------------------------------------------------------


class TestUpdateFeature:
    async def test_update_feature_geometry_only(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_layer: Dataset,
    ):
        """PATCH with only geometry. Properties unchanged."""
        # Insert
        create_resp = await client.post(
            f"/datasets/{test_layer.id}/features/",
            json={
                "geometry": POINT_GEOJSON,
                "properties": {"name": "Keep Me", "status": "ok"},
            },
            headers=admin_auth_header,
        )
        assert create_resp.status_code == 201
        gid = create_resp.json()["id"]

        # Patch geometry only
        resp = await client.patch(
            f"/datasets/{test_layer.id}/features/{gid}",
            json={
                "geometry": POINT_GEOJSON_2,
            },
            headers=admin_auth_header,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["geometry"]["coordinates"][0] == pytest.approx(-118.2437, abs=0.001)
        assert data["properties"]["name"] == "Keep Me"
        assert data["properties"]["status"] == "ok"

    async def test_update_feature_properties_only(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_layer: Dataset,
    ):
        """PATCH with only properties. Geometry unchanged."""
        # Insert
        create_resp = await client.post(
            f"/datasets/{test_layer.id}/features/",
            json={
                "geometry": POINT_GEOJSON,
                "properties": {"name": "Old Name", "status": "draft"},
            },
            headers=admin_auth_header,
        )
        assert create_resp.status_code == 201
        gid = create_resp.json()["id"]
        original_coords = create_resp.json()["geometry"]["coordinates"]

        # Patch properties only
        resp = await client.patch(
            f"/datasets/{test_layer.id}/features/{gid}",
            json={
                "properties": {"name": "New Name"},
            },
            headers=admin_auth_header,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["properties"]["name"] == "New Name"
        # Geometry should be unchanged
        assert data["geometry"]["coordinates"] == pytest.approx(
            original_coords, abs=0.0001
        )

    async def test_update_feature_viewer_forbidden(
        self,
        client: AsyncClient,
        viewer_auth_header: dict,
        test_layer: Dataset,
    ):
        """PATCH as viewer. Assert 403."""
        resp = await client.patch(
            f"/datasets/{test_layer.id}/features/999999",
            json={"properties": {"name": "Nope"}},
            headers=viewer_auth_header,
        )
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# DELETE tests
# ---------------------------------------------------------------------------


class TestDeleteFeature:
    async def test_delete_feature(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_layer: Dataset,
    ):
        """Insert then DELETE. Assert 204. GET confirms 404."""
        # Insert
        create_resp = await client.post(
            f"/datasets/{test_layer.id}/features/",
            json={
                "geometry": POINT_GEOJSON,
                "properties": {"name": "Delete Me"},
            },
            headers=admin_auth_header,
        )
        assert create_resp.status_code == 201
        gid = create_resp.json()["id"]

        # Delete
        resp = await client.delete(
            f"/datasets/{test_layer.id}/features/{gid}",
            headers=admin_auth_header,
        )
        assert resp.status_code == 204

        # Confirm gone
        get_resp = await client.get(
            f"/datasets/{test_layer.id}/features/{gid}",
            headers=admin_auth_header,
        )
        assert get_resp.status_code == 404

    async def test_delete_feature_not_found(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_layer: Dataset,
    ):
        """DELETE a non-existent gid. Assert 404."""
        resp = await client.delete(
            f"/datasets/{test_layer.id}/features/999999",
            headers=admin_auth_header,
        )
        assert resp.status_code == 404

    async def test_delete_feature_viewer_forbidden(
        self,
        client: AsyncClient,
        viewer_auth_header: dict,
        test_layer: Dataset,
    ):
        """DELETE as viewer. Assert 403."""
        resp = await client.delete(
            f"/datasets/{test_layer.id}/features/999999",
            headers=viewer_auth_header,
        )
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Metadata refresh tests
# ---------------------------------------------------------------------------


class TestMultiPromotion:
    """ST_Multi promotion: single-part geometries stored as Multi* in Multi* columns."""

    async def test_insert_polygon_into_multipolygon_promotes(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        multipolygon_layer: Dataset,
        test_db_session,
    ):
        """INSERT a Polygon into a MULTIPOLYGON dataset -> stored as MultiPolygon."""
        resp = await client.post(
            f"/datasets/{multipolygon_layer.id}/features/",
            json={
                "geometry": POLYGON_GEOJSON,
                "properties": {"name": "Promote me"},
            },
            headers=admin_auth_header,
        )
        assert resp.status_code == 201, resp.text
        gid = resp.json()["id"]

        result = await test_db_session.execute(
            text(
                f"SELECT ST_GeometryType(geom_4326) FROM data.{multipolygon_layer.table_name} WHERE gid = :gid"
            ).bindparams(gid=gid)
        )
        geom_type = result.scalar_one()
        assert geom_type == "ST_MultiPolygon"

    async def test_patch_polygon_into_multipolygon_promotes(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        multipolygon_layer: Dataset,
        test_db_session,
    ):
        """PATCH a Polygon geometry into a MULTIPOLYGON dataset -> stored as MultiPolygon."""
        # Insert first with a valid MultiPolygon
        create_resp = await client.post(
            f"/datasets/{multipolygon_layer.id}/features/",
            json={
                "geometry": MULTIPOLYGON_GEOJSON,
                "properties": {"name": "Original"},
            },
            headers=admin_auth_header,
        )
        assert create_resp.status_code == 201
        gid = create_resp.json()["id"]

        # Patch with single Polygon
        resp = await client.patch(
            f"/datasets/{multipolygon_layer.id}/features/{gid}",
            json={"geometry": POLYGON_GEOJSON},
            headers=admin_auth_header,
        )
        assert resp.status_code == 200, resp.text

        result = await test_db_session.execute(
            text(
                f"SELECT ST_GeometryType(geom_4326) FROM data.{multipolygon_layer.table_name} WHERE gid = :gid"
            ).bindparams(gid=gid)
        )
        geom_type = result.scalar_one()
        assert geom_type == "ST_MultiPolygon"

    async def test_insert_multipolygon_no_double_wrapping(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        multipolygon_layer: Dataset,
        test_db_session,
    ):
        """INSERT a MultiPolygon into MULTIPOLYGON dataset -> still MultiPolygon (no double wrap)."""
        resp = await client.post(
            f"/datasets/{multipolygon_layer.id}/features/",
            json={
                "geometry": MULTIPOLYGON_GEOJSON,
                "properties": {"name": "Already multi"},
            },
            headers=admin_auth_header,
        )
        assert resp.status_code == 201, resp.text
        gid = resp.json()["id"]

        result = await test_db_session.execute(
            text(
                f"SELECT ST_GeometryType(geom_4326), ST_NumGeometries(geom_4326) "
                f"FROM data.{multipolygon_layer.table_name} WHERE gid = :gid"
            ).bindparams(gid=gid)
        )
        row = result.one()
        assert row[0] == "ST_MultiPolygon"
        assert row[1] == 2  # Two polygons, not nested

    async def test_insert_point_no_promotion(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_layer: Dataset,
        test_db_session,
    ):
        """INSERT a Point into a POINT dataset -> stored as Point (no promotion)."""
        resp = await client.post(
            f"/datasets/{test_layer.id}/features/",
            json={
                "geometry": POINT_GEOJSON,
                "properties": {"name": "Stay single"},
            },
            headers=admin_auth_header,
        )
        assert resp.status_code == 201, resp.text
        gid = resp.json()["id"]

        result = await test_db_session.execute(
            text(
                f"SELECT ST_GeometryType(geom_4326) FROM data.{test_layer.table_name} WHERE gid = :gid"
            ).bindparams(gid=gid)
        )
        geom_type = result.scalar_one()
        assert geom_type == "ST_Point"


# ---------------------------------------------------------------------------
# Private dataset auth tests
# ---------------------------------------------------------------------------


class TestPrivateDatasetFeatureAuth:
    async def test_unauthenticated_user_cannot_list_private_features(
        self,
        client: AsyncClient,
        test_db_session,
        admin_auth_header: dict,
    ):
        """GET features list for a private dataset without auth returns 401."""
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _create_test_table_and_dataset(
            test_db_session,
            created_by=admin_id,
            geometry_type="POINT",
            visibility="private",
        )
        try:
            resp = await client.get(f"/datasets/{dataset.id}/features/")
            assert resp.status_code == 401
        finally:
            await _cleanup_table(test_db_session, dataset.table_name)
            await test_db_session.execute(
                text("DELETE FROM catalog.records WHERE id = :id"),
                {"id": dataset.record_id},
            )
            await test_db_session.commit()

    async def test_viewer_cannot_list_private_features_without_permission(
        self,
        client: AsyncClient,
        test_db_session,
        admin_auth_header: dict,
        viewer_auth_header: dict,
    ):
        """Viewer without explicit permission cannot list features of a private dataset."""
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _create_test_table_and_dataset(
            test_db_session,
            created_by=admin_id,
            geometry_type="POINT",
            visibility="private",
        )
        try:
            resp = await client.get(
                f"/datasets/{dataset.id}/features/",
                headers=viewer_auth_header,
            )
            # Private datasets return 404 to unauthorized viewers (not 403)
            assert resp.status_code in (403, 404)
        finally:
            await _cleanup_table(test_db_session, dataset.table_name)
            await test_db_session.execute(
                text("DELETE FROM catalog.records WHERE id = :id"),
                {"id": dataset.record_id},
            )
            await test_db_session.commit()


class TestMetadataRefresh:
    async def test_insert_feature_refreshes_metadata(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_layer: Dataset,
        test_db_session,
    ):
        """Insert into empty layer, verify feature_count updated to 1."""
        dataset_id = test_layer.id

        resp = await client.post(
            f"/datasets/{dataset_id}/features/",
            json={
                "geometry": POINT_GEOJSON,
                "properties": {"name": "First"},
            },
            headers=admin_auth_header,
        )
        assert resp.status_code == 201

        # Query feature_count directly via SQL to avoid expired ORM state
        result = await test_db_session.execute(
            text(
                "SELECT feature_count FROM catalog.datasets WHERE id = :id"
            ).bindparams(id=dataset_id)
        )
        count = result.scalar_one()
        assert count == 1

    async def test_delete_feature_refreshes_metadata(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_layer: Dataset,
        test_db_session,
    ):
        """Insert then delete, verify feature_count returns to 0."""
        dataset_id = test_layer.id

        # Insert
        create_resp = await client.post(
            f"/datasets/{dataset_id}/features/",
            json={
                "geometry": POINT_GEOJSON,
                "properties": {"name": "Temp"},
            },
            headers=admin_auth_header,
        )
        assert create_resp.status_code == 201
        gid = create_resp.json()["id"]

        # Delete
        resp = await client.delete(
            f"/datasets/{dataset_id}/features/{gid}",
            headers=admin_auth_header,
        )
        assert resp.status_code == 204

        # Query feature_count directly via SQL to avoid expired ORM state
        result = await test_db_session.execute(
            text(
                "SELECT feature_count FROM catalog.datasets WHERE id = :id"
            ).bindparams(id=dataset_id)
        )
        count = result.scalar_one()
        assert count == 0


# ---------------------------------------------------------------------------
# BBOX filtering tests (including antimeridian crossing)
# ---------------------------------------------------------------------------


class TestBboxFiltering:
    """Exercises the bbox query parameter in GET /datasets/{id}/features/.

    Covers the antimeridian-crossing split in
    backend/app/features/service.py:102-110, which splits a bbox where
    minx > maxx into two ST_MakeEnvelope calls (one clipped to 180, one
    clipped at -180).
    """

    async def test_bbox_filter_normal(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_layer: Dataset,
    ):
        """Normal bbox (minx < maxx) returns only features inside the envelope."""
        dataset_id = test_layer.id

        # Feature inside NYC bbox
        resp = await client.post(
            f"/datasets/{dataset_id}/features/",
            json={
                "geometry": {"type": "Point", "coordinates": [-73.9857, 40.7484]},
                "properties": {"name": "Empire State"},
            },
            headers=admin_auth_header,
        )
        assert resp.status_code == 201

        # Feature outside NYC bbox
        resp = await client.post(
            f"/datasets/{dataset_id}/features/",
            json={
                "geometry": {"type": "Point", "coordinates": [-118.2437, 34.0522]},
                "properties": {"name": "LA"},
            },
            headers=admin_auth_header,
        )
        assert resp.status_code == 201

        # Query with bbox covering only NYC
        resp = await client.get(
            f"/datasets/{dataset_id}/features/?bbox=-74.1,40.6,-73.9,40.8",
            headers=admin_auth_header,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["numberReturned"] == 1
        names = {f["properties"]["name"] for f in data["features"]}
        assert names == {"Empire State"}

    async def test_bbox_antimeridian_crossing(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_layer: Dataset,
    ):
        """Bbox crossing the antimeridian (minx > maxx) matches features on both sides.

        This exercises the split-envelope logic in features/service.py:102-110.
        A bbox like [170, -10, -170, 10] should match points at longitude 175
        AND longitude -175, but NOT a point at longitude 0.
        """
        dataset_id = test_layer.id

        # Feature on the east side of the dateline (longitude 175)
        resp = await client.post(
            f"/datasets/{dataset_id}/features/",
            json={
                "geometry": {"type": "Point", "coordinates": [175.0, 0.0]},
                "properties": {"name": "East Fiji"},
            },
            headers=admin_auth_header,
        )
        assert resp.status_code == 201

        # Feature on the west side of the dateline (longitude -175)
        resp = await client.post(
            f"/datasets/{dataset_id}/features/",
            json={
                "geometry": {"type": "Point", "coordinates": [-175.0, 0.0]},
                "properties": {"name": "West Samoa"},
            },
            headers=admin_auth_header,
        )
        assert resp.status_code == 201

        # Feature NOT in the antimeridian region (Greenwich)
        resp = await client.post(
            f"/datasets/{dataset_id}/features/",
            json={
                "geometry": {"type": "Point", "coordinates": [0.0, 0.0]},
                "properties": {"name": "Greenwich"},
            },
            headers=admin_auth_header,
        )
        assert resp.status_code == 201

        # Query with antimeridian-crossing bbox: minx=170, maxx=-170 (crosses dateline)
        resp = await client.get(
            f"/datasets/{dataset_id}/features/?bbox=170,-10,-170,10",
            headers=admin_auth_header,
        )
        assert resp.status_code == 200
        data = resp.json()
        names = {f["properties"]["name"] for f in data["features"]}
        assert "East Fiji" in names, "Feature at lon=175 should match antimeridian bbox"
        assert "West Samoa" in names, (
            "Feature at lon=-175 should match antimeridian bbox"
        )
        assert "Greenwich" not in names, (
            "Feature at lon=0 should NOT match antimeridian bbox"
        )
        assert data["numberReturned"] == 2

    async def test_bbox_antimeridian_excludes_mid_longitude(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_layer: Dataset,
    ):
        """Antimeridian bbox must not accidentally match features mid-globe.

        Regression check: if the bbox split logic were wrong and treated
        [170, -10, -170, 10] as [-170, -10, 170, 10], it would match
        EVERYTHING between -170 and 170 longitude, which is the opposite
        of what we want.
        """
        dataset_id = test_layer.id

        # Feature mid-Pacific at longitude 0 (should NOT match antimeridian bbox)
        resp = await client.post(
            f"/datasets/{dataset_id}/features/",
            json={
                "geometry": {"type": "Point", "coordinates": [0.0, 0.0]},
                "properties": {"name": "Mid"},
            },
            headers=admin_auth_header,
        )
        assert resp.status_code == 201

        # Feature at longitude 100 (should NOT match)
        resp = await client.post(
            f"/datasets/{dataset_id}/features/",
            json={
                "geometry": {"type": "Point", "coordinates": [100.0, 0.0]},
                "properties": {"name": "West-of-AM"},
            },
            headers=admin_auth_header,
        )
        assert resp.status_code == 201

        resp = await client.get(
            f"/datasets/{dataset_id}/features/?bbox=170,-10,-170,10",
            headers=admin_auth_header,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["numberReturned"] == 0, (
            "Mid-globe features must not match antimeridian bbox"
        )
