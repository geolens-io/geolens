"""Integration tests for feature CRUD (INSERT, UPDATE, DELETE) endpoints.

Tests use a manually created PostGIS table in the data schema to avoid
dependency on the layer creation endpoint (Plan 01).
"""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import text

from app.modules.catalog.datasets.domain.models import Dataset, Record

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
    srid: int = 4326,
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
            f"geom geometry({pg_geom_type}, {srid}), "
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
        srid=srid,
        geometry_type=geometry_type,
        feature_count=0,
        column_info=[
            {"name": "name", "type": "text"},
            {"name": "status", "type": "text"},
        ],
        # fix(#430 codex r7): deliberately 'created' WITH a concretely typed
        # geom column (see pg_geom_type above) — this mirrors the layers-module
        # creation path (layers/service.py), whose typed tables must KEEP typed
        # validation + ST_Multi promotion. effective_geometry_type() only goes
        # generic when the geometry_columns probe reports a generic column.
        source_format="created",
    )
    session.add(dataset)
    await session.commit()
    await session.refresh(dataset)
    return dataset


async def _create_raster_dataset(
    session,
    *,
    created_by: uuid.UUID,
    visibility: str = "public",
    record_type: str = "raster_dataset",
) -> Dataset:
    """Register a raster/VRT dataset with NO backing PostGIS feature table.

    Raster records carry a table_name (NOT NULL on the model) but no data.<table>
    is ever created — this is exactly the (#315) bug-trigger condition where a feature
    query would raise UndefinedTableError -> 500.
    """
    table_name = f"test_crud_raster_{uuid.uuid4().hex[:8]}"
    record = Record(
        title=f"Test Raster Layer {table_name}",
        visibility=visibility,
        record_status="published",
        record_type=record_type,
        created_by=created_by,
    )
    session.add(record)
    await session.flush()
    dataset = Dataset(
        record_id=record.id,
        table_name=table_name,
        srid=4326,
        geometry_type=None,
        feature_count=None,
        source_format="geotiff",
    )
    session.add(dataset)
    await session.commit()
    await session.refresh(dataset)
    return dataset


async def _create_tabular_dataset(
    session,
    *,
    created_by: uuid.UUID,
    visibility: str = "public",
) -> Dataset:
    """Register a non-spatial (tabular) dataset: a real data table with NO geom
    column and geometry_type=None — the read path's has_geometry=False signal."""
    table_name = f"test_crud_tab_{uuid.uuid4().hex[:8]}"
    await session.execute(
        text(
            f"CREATE TABLE IF NOT EXISTS data.{table_name} "
            f"(gid SERIAL PRIMARY KEY, name TEXT)"
        )
    )
    await session.execute(text(f"GRANT SELECT ON data.{table_name} TO geolens_reader"))
    record = Record(
        title=f"Test Tabular Layer {table_name}",
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
        geometry_type=None,
        feature_count=0,
        column_info=[{"name": "name", "type": "text"}],
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


@pytest.fixture
async def tabular_layer(client: AsyncClient, test_db_session, admin_auth_header):
    """Create a non-spatial (tabular) dataset for the geometry_type=None guard."""
    admin_id = await get_user_id(test_db_session, "admin")
    dataset = await _create_tabular_dataset(test_db_session, created_by=admin_id)
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
async def raster_layer(client: AsyncClient, test_db_session, admin_auth_header):
    """Create a raster dataset with no backing feature table (#315 guard)."""
    admin_id = await get_user_id(test_db_session, "admin")
    dataset = await _create_raster_dataset(
        test_db_session,
        created_by=admin_id,
    )
    rec_id = dataset.record_id
    # No data.<table> exists, so nothing to drop on teardown.
    yield dataset
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

    async def test_insert_feature_non_owner_editor_forbidden(
        self,
        client: AsyncClient,
        editor_auth_header: dict,
        test_layer: Dataset,
    ):
        """A non-owner editor cannot insert a feature into a peer's dataset (403).

        test_layer is owned by admin; editing feature rows requires owner-or-admin
        (the edit_metadata capability alone is not ownership).
        """
        resp = await client.post(
            f"/datasets/{test_layer.id}/features/",
            json={
                "geometry": POINT_GEOJSON,
                "properties": {"name": "Not yours"},
            },
            headers=editor_auth_header,
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


# ---------------------------------------------------------------------------
# fix(#315): raster/VRT datasets have no feature table — must 404, never 500
# ---------------------------------------------------------------------------


class TestRasterDatasetFeatureGuard:
    """A raster/VRT dataset has a table_name but no backing data.<table>.

    Before the guard, a feature query raised UndefinedTableError. The native
    features router previously diverged: list_features -> 503,
    features.geojson -> 400, and get_single_feature -> an UNHANDLED 500 (a DoS
    reachable by any authenticated user). All three read paths must now return a
    uniform fast 404 before any table query, matching the OGC contract.
    """

    async def test_single_feature_on_raster_returns_404(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        raster_layer: Dataset,
    ):
        """GET /datasets/{raster_id}/features/{gid} returns 404 (was 500 DoS)."""
        resp = await client.get(
            f"/datasets/{raster_layer.id}/features/1",
            headers=admin_auth_header,
        )
        assert resp.status_code == 404, resp.text
        assert "raster collection" in resp.json()["detail"].lower()

    async def test_list_features_on_raster_returns_404(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        raster_layer: Dataset,
    ):
        """GET /datasets/{raster_id}/features/ returns 404 (was 503)."""
        resp = await client.get(
            f"/datasets/{raster_layer.id}/features/",
            headers=admin_auth_header,
        )
        assert resp.status_code == 404, resp.text
        assert "raster collection" in resp.json()["detail"].lower()

    async def test_geojson_tile_on_raster_returns_404(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        raster_layer: Dataset,
    ):
        """GET /datasets/{raster_id}/features.geojson returns 404 (was 400)."""
        resp = await client.get(
            f"/datasets/{raster_layer.id}/features.geojson",
            headers=admin_auth_header,
        )
        assert resp.status_code == 404, resp.text
        assert "raster collection" in resp.json()["detail"].lower()


class TestCreateEmptyDatasetGenericGeometry:
    """fix(#430 codex r5, P1): create_empty_dataset stores geometry_type='GEOMETRY'
    (fix #430 BA-32), which the chk_datasets_geometry_type allow-list rejected —
    every empty-dataset create 500'd at flush with ZERO endpoint coverage.
    Migration 0011 admits the generic sentinel; this pins the whole flow."""

    async def _stored_geometry_type(self, session, dataset_id: str) -> str | None:
        result = await session.execute(
            text(
                "SELECT geometry_type FROM catalog.datasets WHERE id = :id"
            ).bindparams(id=uuid.UUID(str(dataset_id)))
        )
        return result.scalar_one()

    async def test_create_empty_dataset_then_insert_mixed_geometries(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
    ):
        resp = await client.post(
            "/datasets/create/",
            json={
                "title": "Mixed Sketch Layer",
                "columns": [{"name": "name", "type": "text"}],
            },
            headers=admin_auth_header,
        )
        assert resp.status_code == 201, resp.text
        dataset_id = resp.json()["id"]

        # fix(#430 BA-32): the generic-typed dataset accepts ANY concrete
        # geometry subtype — previously the stored 'POINT' rejected polygons.
        geometries = [
            {"type": "Point", "coordinates": [-73.9857, 40.7484]},
            {
                "type": "Polygon",
                "coordinates": [
                    [
                        [-74.0, 40.7],
                        [-73.9, 40.7],
                        [-73.9, 40.8],
                        [-74.0, 40.8],
                        [-74.0, 40.7],
                    ]
                ],
            },
            {"type": "LineString", "coordinates": [[-74.0, 40.7], [-73.9, 40.8]]},
        ]
        for geometry in geometries:
            feature_resp = await client.post(
                f"/datasets/{dataset_id}/features/",
                json={"geometry": geometry, "properties": {"name": geometry["type"]}},
                headers=admin_auth_header,
            )
            assert feature_resp.status_code == 201, (
                f"{geometry['type']}: {feature_resp.text}"
            )

        # fix(#430 codex r7): a cross-family mix stays generic (renders as fill,
        # the honest fallback — same as GEOMETRYCOLLECTION datasets).
        assert await self._stored_geometry_type(test_db_session, dataset_id) == (
            "GEOMETRY"
        )

    async def test_homogeneous_created_layer_derives_renderable_type(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
    ):
        """fix(#430 codex r7): a point-only sketch layer must expose a concrete
        geometry_type ('POINT') so the builder renders circles — the 'GEOMETRY'
        sentinel classified as an invisible fill layer. Later inserting another
        family must still be ACCEPTED (validation stays generic for created
        datasets) and flips the display type back to 'GEOMETRY'."""
        resp = await client.post(
            "/datasets/create/",
            json={
                "title": "Point Sketch Layer",
                "columns": [{"name": "name", "type": "text"}],
            },
            headers=admin_auth_header,
        )
        assert resp.status_code == 201, resp.text
        dataset_id = resp.json()["id"]

        point_resp = await client.post(
            f"/datasets/{dataset_id}/features/",
            json={
                "geometry": {"type": "Point", "coordinates": [-73.99, 40.75]},
                "properties": {"name": "p1"},
            },
            headers=admin_auth_header,
        )
        assert point_resp.status_code == 201, point_resp.text
        assert await self._stored_geometry_type(test_db_session, dataset_id) == "POINT"

        # fix(#430 codex r18): even with a concrete DISPLAY type derived, the
        # detail endpoint must expose the genericity signal so the drawing
        # toolbar keeps offering every mode (the column still accepts any
        # subtype).
        detail = await client.get(f"/datasets/{dataset_id}", headers=admin_auth_header)
        assert detail.status_code == 200
        assert detail.json()["geometry_type"] == "POINT"
        assert detail.json()["has_generic_geometry"] is True

        # Single-family mix (Point + MultiPoint) -> the MULTI variant.
        multipoint_resp = await client.post(
            f"/datasets/{dataset_id}/features/",
            json={
                "geometry": {
                    "type": "MultiPoint",
                    "coordinates": [[-73.98, 40.74], [-73.97, 40.73]],
                },
                "properties": {"name": "p2"},
            },
            headers=admin_auth_header,
        )
        assert multipoint_resp.status_code == 201, multipoint_resp.text
        assert await self._stored_geometry_type(test_db_session, dataset_id) == (
            "MULTIPOINT"
        )

        # A different family is STILL accepted (derived type must not
        # re-restrict inserts — that would reintroduce the BA-32 bug)...
        line_resp = await client.post(
            f"/datasets/{dataset_id}/features/",
            json={
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[-74.0, 40.7], [-73.9, 40.8]],
                },
                "properties": {"name": "l1"},
            },
            headers=admin_auth_header,
        )
        assert line_resp.status_code == 201, line_resp.text
        # ...and the display type honestly degrades to generic.
        assert await self._stored_geometry_type(test_db_session, dataset_id) == (
            "GEOMETRY"
        )

    async def test_geometry_collection_accepted_on_generic_rejected_on_typed(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_layer: Dataset,
        test_db_session,
    ):
        """fix(#430 codex r9): a GeoJSON GeometryCollection is insertable into a
        generic GEOMETRY column (the constraint and column allow it) but was
        400'd as 'Unsupported geometry type' because GEOJSON_TYPE_MAP had no
        entry. Typed datasets must keep rejecting it — as a type MISMATCH, not
        as an unknown type."""
        resp = await client.post(
            "/datasets/create/",
            json={
                "title": "GC Sketch Layer",
                "columns": [{"name": "name", "type": "text"}],
            },
            headers=admin_auth_header,
        )
        assert resp.status_code == 201, resp.text
        dataset_id = resp.json()["id"]

        collection = {
            "type": "GeometryCollection",
            "geometries": [
                {"type": "Point", "coordinates": [-73.9857, 40.7484]},
                {
                    "type": "LineString",
                    "coordinates": [[-74.0, 40.7], [-73.9, 40.8]],
                },
            ],
        }
        gc_resp = await client.post(
            f"/datasets/{dataset_id}/features/",
            json={"geometry": collection, "properties": {"name": "gc"}},
            headers=admin_auth_header,
        )
        assert gc_resp.status_code == 201, gc_resp.text

        # codex r13 (refuted as proposed): a NESTED collection cannot
        # round-trip PostGIS's GeoJSON boundary in either direction —
        # ST_GeomFromGeoJSON rejects it on write and ST_AsGeoJSON raises
        # 'GeoJson: geometry not supported' on read — so the schema stays
        # non-recursive and the write path rejects nesting with a CLEAR 422
        # (previously a misleading 'coordinates: Field required').
        nested = {
            "type": "GeometryCollection",
            "geometries": [
                {
                    "type": "GeometryCollection",
                    "geometries": [
                        {"type": "Point", "coordinates": [-73.95, 40.75]},
                    ],
                },
            ],
        }
        nested_resp = await client.post(
            f"/datasets/{dataset_id}/features/",
            json={"geometry": nested, "properties": {"name": "nested"}},
            headers=admin_auth_header,
        )
        assert nested_resp.status_code == 422, nested_resp.text
        assert "Nested GeometryCollections" in nested_resp.text

        # codex r14: a malformed collection WITHOUT a 'geometries' array must
        # 422 too — it would otherwise slip through the union's broad
        # GeoJSONGeometry member (type is plain str) and reach
        # ST_GeomFromGeoJSON as a raw database error.
        for malformed in (
            {"type": "GeometryCollection", "coordinates": []},
            {"type": "GeometryCollection", "geometries": "nope", "coordinates": []},
        ):
            malformed_resp = await client.post(
                f"/datasets/{dataset_id}/features/",
                json={"geometry": malformed, "properties": {"name": "bad"}},
                headers=admin_auth_header,
            )
            assert malformed_resp.status_code == 422, malformed_resp.text
            assert "requires a 'geometries' array" in malformed_resp.text

        # Read side: the stored FLAT collection serializes back out through
        # the GeoJSONGeometryCollection response variant.
        read_resp = await client.get(
            f"/datasets/{dataset_id}/features?limit=50",
            headers=admin_auth_header,
        )
        assert read_resp.status_code == 200, read_resp.text
        geoms = [f["geometry"]["type"] for f in read_resp.json()["features"]]
        assert geoms.count("GeometryCollection") == 1

        # Typed dataset (Point layer): still rejected, but as a mismatch.
        typed_resp = await client.post(
            f"/datasets/{test_layer.id}/features/",
            json={"geometry": collection, "properties": {"name": "gc"}},
            headers=admin_auth_header,
        )
        assert typed_resp.status_code == 400
        assert "mismatch" in typed_resp.json()["detail"].lower()

        # fix(#430 codex r18): typed datasets report no generic signal.
        typed_detail = await client.get(
            f"/datasets/{test_layer.id}", headers=admin_auth_header
        )
        assert typed_detail.status_code == 200
        assert typed_detail.json()["has_generic_geometry"] is False

    async def test_geometrycollection_typed_dataset_accepts_collections(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
    ):
        """fix(#430 codex r20): a dataset whose column IS typed
        GEOMETRYCOLLECTION (ingested GC data — the check constraint allows the
        type) must accept flat GeoJSON collections through the feature API;
        r9's empty compatibility set rejected them as a mismatch. Non-collection
        subtypes stay rejected (the typed column cannot store them)."""
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _create_test_table_and_dataset(
            test_db_session,
            created_by=admin_id,
            geometry_type="GEOMETRYCOLLECTION",
        )
        try:
            gc_resp = await client.post(
                f"/datasets/{dataset.id}/features/",
                json={
                    "geometry": {
                        "type": "GeometryCollection",
                        "geometries": [
                            {"type": "Point", "coordinates": [-73.9, 40.7]},
                        ],
                    },
                    "properties": {"name": "gc"},
                },
                headers=admin_auth_header,
            )
            assert gc_resp.status_code == 201, gc_resp.text

            point_resp = await client.post(
                f"/datasets/{dataset.id}/features/",
                json={"geometry": POINT_GEOJSON, "properties": {"name": "p"}},
                headers=admin_auth_header,
            )
            assert point_resp.status_code == 400
            assert "mismatch" in point_resp.json()["detail"].lower()
        finally:
            tbl = dataset.table_name
            rec_id = dataset.record_id
            await _cleanup_table(test_db_session, tbl)
            await test_db_session.execute(
                text("DELETE FROM catalog.records WHERE id = :id"),
                {"id": rec_id},
            )
            await test_db_session.commit()


# ---------------------------------------------------------------------------
# Native-SRID write tests
# ---------------------------------------------------------------------------


class TestNativeSridWrites:
    """fix(#458 E-01): geometry writes must land in the geom column's native SRID.

    File-ingested layers keep their source CRS in ``geom`` (the file path runs
    ogr2ogr without -t_srs); ``ST_GeomFromGeoJSON`` emits SRID 4326, so before
    the ST_Transform fix every geometry write on a projected-SRID dataset
    violated the column typmod and returned 500.
    """

    # Empire State Building, WGS84. EPSG:2263 = NY State Plane Long Island (ft).
    NYC_POINT = {"type": "Point", "coordinates": [-73.9857, 40.7484]}

    async def _make_stateplane_layer(self, test_db_session):
        admin_id = await get_user_id(test_db_session, "admin")
        return await _create_test_table_and_dataset(
            test_db_session,
            created_by=admin_id,
            geometry_type="POINT",
            srid=2263,
        )

    async def _geom_srids(self, session, table_name: str, gid: int):
        row = (
            await session.execute(
                text(
                    f"SELECT ST_SRID(geom), ST_SRID(geom_4326), "
                    f"ST_X(geom), ST_Y(geom) "
                    f"FROM data.{table_name} WHERE gid = :gid"
                ),
                {"gid": gid},
            )
        ).one()
        return row

    async def test_insert_transforms_geom_to_native_srid(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
    ):
        dataset = await self._make_stateplane_layer(test_db_session)
        try:
            resp = await client.post(
                f"/datasets/{dataset.id}/features/",
                json={"geometry": self.NYC_POINT, "properties": {"name": "esb"}},
                headers=admin_auth_header,
            )
            assert resp.status_code == 201, resp.text
            data = resp.json()
            gid = data["id"]
            # API response reads geom_4326 -> WGS84 round-trip.
            lon, lat = data["geometry"]["coordinates"]
            assert abs(lon - self.NYC_POINT["coordinates"][0]) < 1e-4
            assert abs(lat - self.NYC_POINT["coordinates"][1]) < 1e-4

            srid, srid4326, x, y = await self._geom_srids(
                test_db_session, dataset.table_name, gid
            )
            assert srid == 2263
            assert srid4326 == 4326
            # Manhattan in NY-LI State Plane feet: ~987k east, ~211k north.
            assert 900_000 < x < 1_100_000
            assert 150_000 < y < 300_000
        finally:
            tbl = dataset.table_name
            rec_id = dataset.record_id
            await _cleanup_table(test_db_session, tbl)
            await test_db_session.execute(
                text("DELETE FROM catalog.records WHERE id = :id"),
                {"id": rec_id},
            )
            await test_db_session.commit()

    async def test_put_and_patch_geometry_on_native_srid_layer(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
    ):
        dataset = await self._make_stateplane_layer(test_db_session)
        try:
            resp = await client.post(
                f"/datasets/{dataset.id}/features/",
                json={"geometry": self.NYC_POINT, "properties": {"name": "esb"}},
                headers=admin_auth_header,
            )
            assert resp.status_code == 201, resp.text
            gid = resp.json()["id"]

            moved = {"type": "Point", "coordinates": [-73.9772, 40.7527]}
            put_resp = await client.put(
                f"/datasets/{dataset.id}/features/{gid}",
                json={"geometry": moved, "properties": {"name": "grand central"}},
                headers=admin_auth_header,
            )
            assert put_resp.status_code == 200, put_resp.text

            patch_resp = await client.patch(
                f"/datasets/{dataset.id}/features/{gid}",
                json={"geometry": self.NYC_POINT},
                headers=admin_auth_header,
            )
            assert patch_resp.status_code == 200, patch_resp.text

            srid, srid4326, _x, _y = await self._geom_srids(
                test_db_session, dataset.table_name, gid
            )
            assert srid == 2263
            assert srid4326 == 4326
        finally:
            tbl = dataset.table_name
            rec_id = dataset.record_id
            await _cleanup_table(test_db_session, tbl)
            await test_db_session.execute(
                text("DELETE FROM catalog.records WHERE id = :id"),
                {"id": rec_id},
            )
            await test_db_session.commit()


# ---------------------------------------------------------------------------
# Geometry validity tests
# ---------------------------------------------------------------------------


class TestGeometryValidity:
    """fix(#458 E-02): degenerate/invalid geometry is rejected with 400.

    Before the shapely validity gate, degenerate input 500'd at
    ST_GeomFromGeoJSON and self-intersecting polygons persisted, then 500'd
    later bbox/tile reads with GEOS TopologyException.
    """

    BOWTIE = {
        "type": "Polygon",
        "coordinates": [[[0.0, 0.0], [2.0, 2.0], [2.0, 0.0], [0.0, 2.0], [0.0, 0.0]]],
    }
    TWO_POINT_RING = {
        "type": "Polygon",
        "coordinates": [[[0.0, 0.0], [1.0, 1.0], [0.0, 0.0]]],
    }

    async def test_self_intersecting_polygon_rejected(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        polygon_layer: Dataset,
    ):
        resp = await client.post(
            f"/datasets/{polygon_layer.id}/features/",
            json={"geometry": self.BOWTIE, "properties": {"name": "bowtie"}},
            headers=admin_auth_header,
        )
        assert resp.status_code == 400, resp.text
        assert "self-intersection" in resp.json()["detail"].lower()

    async def test_degenerate_ring_rejected(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        polygon_layer: Dataset,
    ):
        resp = await client.post(
            f"/datasets/{polygon_layer.id}/features/",
            json={"geometry": self.TWO_POINT_RING, "properties": {"name": "sliver"}},
            headers=admin_auth_header,
        )
        # 400 from the shapely gate or 422 from schema-level coordinate checks;
        # the pre-fix behavior was a 500.
        assert resp.status_code in (400, 422), resp.text

    async def test_empty_coordinates_rejected(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        polygon_layer: Dataset,
    ):
        resp = await client.post(
            f"/datasets/{polygon_layer.id}/features/",
            json={
                "geometry": {"type": "Polygon", "coordinates": []},
                "properties": {"name": "empty"},
            },
            headers=admin_auth_header,
        )
        assert resp.status_code in (400, 422), resp.text

    async def test_patch_with_invalid_geometry_rejected(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        polygon_layer: Dataset,
    ):
        create = await client.post(
            f"/datasets/{polygon_layer.id}/features/",
            json={"geometry": POLYGON_GEOJSON, "properties": {"name": "ok"}},
            headers=admin_auth_header,
        )
        assert create.status_code == 201, create.text
        gid = create.json()["id"]

        patch = await client.patch(
            f"/datasets/{polygon_layer.id}/features/{gid}",
            json={"geometry": self.BOWTIE},
            headers=admin_auth_header,
        )
        assert patch.status_code == 400, patch.text


# ---------------------------------------------------------------------------
# Editing enforcement + write-path contracts (fix #458 E-08/E-09/E-11/E-25)
# ---------------------------------------------------------------------------


class TestEditingEnforcementAndContracts:
    async def test_write_blocked_when_editing_disabled(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_layer: Dataset,
        monkeypatch,
    ):
        """E-11: with the flag off, feature writes AND column DDL 403 even for admin."""
        import app.core.persistent_config as pc

        class _AlwaysOff:
            async def get(self, _db):
                return False

        monkeypatch.setattr(pc, "ENABLE_DATASET_EDITING", _AlwaysOff())

        feature = await client.post(
            f"/datasets/{test_layer.id}/features/",
            json={"geometry": POINT_GEOJSON, "properties": {"name": "blocked"}},
            headers=admin_auth_header,
        )
        assert feature.status_code == 403, feature.text

        column = await client.post(
            f"/layers/{test_layer.id}/columns/",
            json={"column": {"name": "pop", "type": "integer"}},
            headers=admin_auth_header,
        )
        assert column.status_code == 403, column.text

    async def test_unknown_property_key_rejected(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_layer: Dataset,
    ):
        """E-25: a property key that names no column is a 400, not a silent drop."""
        resp = await client.post(
            f"/datasets/{test_layer.id}/features/",
            json={
                "geometry": POINT_GEOJSON,
                "properties": {"name": "ok", "typoed_column": "x"},
            },
            headers=admin_auth_header,
        )
        assert resp.status_code == 400, resp.text
        assert "typoed_column" in resp.json()["detail"]

    async def test_write_to_raster_dataset_is_404_not_500(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        raster_layer: Dataset,
    ):
        """E-08: feature write to a dataset with no feature table 404s (was 500)."""
        resp = await client.post(
            f"/datasets/{raster_layer.id}/features/",
            json={"geometry": POINT_GEOJSON, "properties": {}},
            headers=admin_auth_header,
        )
        assert resp.status_code == 404, resp.text

    async def test_write_to_tabular_dataset_is_400_not_500(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        tabular_layer: Dataset,
    ):
        """E-08 (PR #463 review): a non-spatial dataset rejects feature writes with
        400 — including DELETE, which touches no geometry and used to slip past to
        refresh_dataset_metadata's geom_4326 read and 500."""
        post = await client.post(
            f"/datasets/{tabular_layer.id}/features/",
            json={"geometry": POINT_GEOJSON, "properties": {}},
            headers=admin_auth_header,
        )
        assert post.status_code == 400, post.text

        delete = await client.delete(
            f"/datasets/{tabular_layer.id}/features/1",
            headers=admin_auth_header,
        )
        assert delete.status_code == 400, delete.text

    async def test_type_mismatch_is_400_not_500(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_layer: Dataset,
    ):
        """E-09/E-26: a value incompatible with a column's type is a 400, not a 500."""
        add = await client.post(
            f"/layers/{test_layer.id}/columns/",
            json={"column": {"name": "population", "type": "integer"}},
            headers=admin_auth_header,
        )
        assert add.status_code == 201, add.text

        resp = await client.post(
            f"/datasets/{test_layer.id}/features/",
            json={
                "geometry": POINT_GEOJSON,
                "properties": {"name": "x", "population": "not-a-number"},
            },
            headers=admin_auth_header,
        )
        assert resp.status_code == 400, resp.text
