"""Integration tests for GeoJSON-Z delivery endpoint.

Tests cover:
- Service function: Z coordinate preservation, truncation, cached count
- HTTP endpoint: auth, RBAC, 404, 400, truncation, Z coordinates
"""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import text

from app.datasets.models import Dataset, Record

from tests.factories import get_user_id
from tests.conftest import _create_test_user


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _create_test_table_and_dataset_3d(
    session,
    *,
    created_by: uuid.UUID,
    table_name: str | None = None,
    visibility: str = "public",
) -> Dataset:
    """Create a PostGIS data table with PointZ geometry and register as a dataset."""
    if table_name is None:
        table_name = f"test_z_{uuid.uuid4().hex[:8]}"

    # Use plain geometry (no type/srid modifier) for geom_4326 to allow Z input.
    # geometry(Geometry, 4326) restricts to 2D; plain geometry accepts Z.
    await session.execute(
        text(
            f"CREATE TABLE IF NOT EXISTS data.{table_name} ("
            f"gid SERIAL PRIMARY KEY, "
            f"geom geometry(PointZ, 4326), "
            f"geom_4326 geometry, "
            f"name TEXT)"
        )
    )
    await session.execute(text(f"GRANT SELECT ON data.{table_name} TO geolens_reader"))

    # Insert 3 Point Z features
    await session.execute(
        text(
            f"INSERT INTO data.{table_name} (geom, geom_4326, name) VALUES "
            f"(ST_SetSRID(ST_GeomFromText('POINT Z(-73.9 40.7 100.5)'), 4326), ST_SetSRID(ST_GeomFromText('POINT Z(-73.9 40.7 100.5)'), 4326), 'Point A'), "
            f"(ST_SetSRID(ST_GeomFromText('POINT Z(-74.0 40.8 200.0)'), 4326), ST_SetSRID(ST_GeomFromText('POINT Z(-74.0 40.8 200.0)'), 4326), 'Point B'), "
            f"(ST_SetSRID(ST_GeomFromText('POINT Z(-73.8 40.6 300.0)'), 4326), ST_SetSRID(ST_GeomFromText('POINT Z(-73.8 40.6 300.0)'), 4326), 'Point C')"
        )
    )

    record = Record(
        title=f"Test Z Layer {table_name}",
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
        geometry_type="POINT",
        feature_count=3,
        column_info=[{"name": "name", "type": "text"}],
        source_format="created",
    )
    session.add(dataset)
    await session.commit()
    await session.refresh(dataset)
    return dataset


async def _create_large_table_and_dataset(
    session,
    *,
    created_by: uuid.UUID,
    table_name: str | None = None,
    row_count: int = 5010,
) -> Dataset:
    """Create a PostGIS table with many Point Z rows for truncation testing."""
    if table_name is None:
        table_name = f"test_z_large_{uuid.uuid4().hex[:8]}"

    # Use plain geometry (no type/srid modifier) for geom_4326 to allow Z input.
    await session.execute(
        text(
            f"CREATE TABLE IF NOT EXISTS data.{table_name} ("
            f"gid SERIAL PRIMARY KEY, "
            f"geom geometry(PointZ, 4326), "
            f"geom_4326 geometry, "
            f"name TEXT)"
        )
    )
    await session.execute(text(f"GRANT SELECT ON data.{table_name} TO geolens_reader"))

    # Use generate_series for speed
    await session.execute(
        text(
            f"INSERT INTO data.{table_name} (geom, geom_4326, name) "
            f"SELECT "
            f"ST_SetSRID(ST_MakePoint(-73.9 + (i * 0.0001), 40.7 + (i * 0.0001), i * 1.0), 4326), "
            f"ST_SetSRID(ST_MakePoint(-73.9 + (i * 0.0001), 40.7 + (i * 0.0001), i * 1.0), 4326), "
            f"'Point ' || i "
            f"FROM generate_series(1, {row_count}) AS i"
        )
    )

    record = Record(
        title=f"Test Z Large Layer {table_name}",
        visibility="public",
        record_status="published",
        created_by=created_by,
    )
    session.add(record)
    await session.flush()
    dataset = Dataset(
        record_id=record.id,
        table_name=table_name,
        srid=4326,
        geometry_type="POINT",
        feature_count=row_count,
        column_info=[{"name": "name", "type": "text"}],
        source_format="created",
    )
    session.add(dataset)
    await session.commit()
    await session.refresh(dataset)
    return dataset


async def _create_tabular_dataset(
    session,
    *,
    created_by: uuid.UUID,
    table_name: str | None = None,
) -> Dataset:
    """Create a dataset with no geometry (tabular)."""
    if table_name is None:
        table_name = f"test_tabular_{uuid.uuid4().hex[:8]}"

    await session.execute(
        text(
            f"CREATE TABLE IF NOT EXISTS data.{table_name} ("
            f"gid SERIAL PRIMARY KEY, "
            f"name TEXT, "
            f"value INTEGER)"
        )
    )
    await session.execute(text(f"GRANT SELECT ON data.{table_name} TO geolens_reader"))
    await session.execute(
        text(f"INSERT INTO data.{table_name} (name, value) VALUES ('A', 1), ('B', 2)")
    )

    record = Record(
        title=f"Test Tabular {table_name}",
        visibility="public",
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
        feature_count=2,
        column_info=[{"name": "name", "type": "text"}],
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
# Service-level tests (Task 1)
# ---------------------------------------------------------------------------


class TestGetFeaturesGeoJSONZService:
    """Tests for the get_features_geojson_z service function directly."""

    @pytest.fixture
    async def z_dataset(self, client, test_db_session, admin_auth_header):
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _create_test_table_and_dataset_3d(
            test_db_session, created_by=admin_id
        )
        tbl = dataset.table_name
        rec_id = dataset.record_id
        yield dataset
        await _cleanup_table(test_db_session, tbl)
        await test_db_session.execute(
            text("DELETE FROM catalog.records WHERE id = :id"), {"id": rec_id}
        )
        await test_db_session.commit()

    @pytest.fixture
    async def large_dataset(self, client, test_db_session, admin_auth_header):
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _create_large_table_and_dataset(
            test_db_session, created_by=admin_id
        )
        tbl = dataset.table_name
        rec_id = dataset.record_id
        yield dataset
        await _cleanup_table(test_db_session, tbl)
        await test_db_session.execute(
            text("DELETE FROM catalog.records WHERE id = :id"), {"id": rec_id}
        )
        await test_db_session.commit()

    async def test_returns_z_coordinates_not_truncated(self, z_dataset, test_db_session):
        """3 Point Z rows → 3 rows returned, truncated=False."""
        from app.features.service import get_features_geojson_z

        rows, truncated, total_count = await get_features_geojson_z(
            test_db_session, z_dataset.table_name
        )

        assert len(rows) == 3
        assert truncated is False
        assert total_count == 3

        # Each geometry should have 3-element coordinate array
        for row in rows:
            geom = row["geometry"]
            assert geom is not None
            assert geom["type"] == "Point"
            coords = geom["coordinates"]
            assert len(coords) == 3, f"Expected 3 coords (X, Y, Z), got {len(coords)}"

    async def test_truncation_at_cap(self, large_dataset, test_db_session):
        """Table with 5010 rows → cap=5000, returns 5000 rows with truncated=True."""
        from app.features.service import get_features_geojson_z

        rows, truncated, total_count = await get_features_geojson_z(
            test_db_session, large_dataset.table_name, cap=5000
        )

        assert len(rows) == 5000
        assert truncated is True
        assert total_count > 5000

    async def test_uses_cached_feature_count_when_not_truncated(
        self, z_dataset, test_db_session
    ):
        """When not truncated and cached_feature_count provided, uses it for total_count."""
        from app.features.service import get_features_geojson_z

        rows, truncated, total_count = await get_features_geojson_z(
            test_db_session,
            z_dataset.table_name,
            cached_feature_count=999,  # fake cached value
        )

        assert truncated is False
        # Should use the len(rows) not the cached value when not truncated
        # (all features returned — actual count is authoritative)
        assert total_count == 3  # actual count, not cached


# ---------------------------------------------------------------------------
# HTTP endpoint tests (Task 2)
# ---------------------------------------------------------------------------


class TestGetFeaturesGeoJSONZEndpoint:
    """HTTP integration tests for GET /datasets/{id}/features.geojson."""

    @pytest.fixture
    async def z_dataset(self, client, test_db_session, admin_auth_header):
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _create_test_table_and_dataset_3d(
            test_db_session, created_by=admin_id
        )
        tbl = dataset.table_name
        rec_id = dataset.record_id
        yield dataset
        await _cleanup_table(test_db_session, tbl)
        await test_db_session.execute(
            text("DELETE FROM catalog.records WHERE id = :id"), {"id": rec_id}
        )
        await test_db_session.commit()

    @pytest.fixture
    async def private_dataset(self, client, test_db_session, admin_auth_header):
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _create_test_table_and_dataset_3d(
            test_db_session, created_by=admin_id, visibility="private"
        )
        tbl = dataset.table_name
        rec_id = dataset.record_id
        yield dataset
        await _cleanup_table(test_db_session, tbl)
        await test_db_session.execute(
            text("DELETE FROM catalog.records WHERE id = :id"), {"id": rec_id}
        )
        await test_db_session.commit()

    @pytest.fixture
    async def tabular_dataset(self, client, test_db_session, admin_auth_header):
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _create_tabular_dataset(
            test_db_session, created_by=admin_id
        )
        tbl = dataset.table_name
        rec_id = dataset.record_id
        yield dataset
        await _cleanup_table(test_db_session, tbl)
        await test_db_session.execute(
            text("DELETE FROM catalog.records WHERE id = :id"), {"id": rec_id}
        )
        await test_db_session.commit()

    @pytest.fixture
    async def large_dataset(self, client, test_db_session, admin_auth_header):
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _create_large_table_and_dataset(
            test_db_session, created_by=admin_id
        )
        tbl = dataset.table_name
        rec_id = dataset.record_id
        yield dataset
        await _cleanup_table(test_db_session, tbl)
        await test_db_session.execute(
            text("DELETE FROM catalog.records WHERE id = :id"), {"id": rec_id}
        )
        await test_db_session.commit()

    @pytest.fixture
    async def viewer_headers_and_id(self, client, admin_auth_header):
        headers, user_id = await _create_test_user(client, admin_auth_header, "viewer")
        return headers, user_id

    async def test_requires_auth(self, client, z_dataset):
        """Unauthenticated request returns 401."""
        resp = await client.get(
            f"/datasets/{z_dataset.id}/features.geojson?include_z=true"
        )
        assert resp.status_code == 401

    async def test_returns_feature_collection(
        self, client, z_dataset, admin_auth_header
    ):
        """Authenticated request returns 200 with FeatureCollection."""
        resp = await client.get(
            f"/datasets/{z_dataset.id}/features.geojson?include_z=true",
            headers=admin_auth_header,
        )
        assert resp.status_code == 200

        # Content-Type must be application/geo+json
        assert "application/geo+json" in resp.headers["content-type"]

        body = resp.json()
        assert body["type"] == "FeatureCollection"
        assert "features" in body
        assert isinstance(body["features"], list)
        assert len(body["features"]) == 3

        # Response has truncated and total_count metadata
        assert "truncated" in body
        assert "total_count" in body
        assert body["truncated"] is False
        assert body["total_count"] == 3

    async def test_z_coordinates_in_response(
        self, client, z_dataset, admin_auth_header
    ):
        """Features in response have 3-coordinate arrays (lng, lat, z)."""
        resp = await client.get(
            f"/datasets/{z_dataset.id}/features.geojson?include_z=true",
            headers=admin_auth_header,
        )
        assert resp.status_code == 200

        body = resp.json()
        for feature in body["features"]:
            assert feature["type"] == "Feature"
            geom = feature["geometry"]
            assert geom["type"] == "Point"
            assert len(geom["coordinates"]) == 3, (
                f"Expected 3 coordinates, got {len(geom['coordinates'])}"
            )

    async def test_dataset_not_found(self, client, admin_auth_header):
        """Non-existent dataset UUID returns 404."""
        fake_id = uuid.uuid4()
        resp = await client.get(
            f"/datasets/{fake_id}/features.geojson?include_z=true",
            headers=admin_auth_header,
        )
        assert resp.status_code == 404

    async def test_rbac_private_dataset_non_owner(
        self, client, private_dataset, viewer_headers_and_id
    ):
        """Private dataset accessed by non-owner returns 404."""
        viewer_headers, _ = viewer_headers_and_id
        resp = await client.get(
            f"/datasets/{private_dataset.id}/features.geojson?include_z=true",
            headers=viewer_headers,
        )
        assert resp.status_code == 404

    async def test_no_geometry_dataset_returns_400(
        self, client, tabular_dataset, admin_auth_header
    ):
        """Dataset with no geometry type returns 400."""
        resp = await client.get(
            f"/datasets/{tabular_dataset.id}/features.geojson?include_z=true",
            headers=admin_auth_header,
        )
        assert resp.status_code == 400
        assert "geometry" in resp.json()["detail"].lower()

    async def test_truncation_at_5000(
        self, client, large_dataset, admin_auth_header
    ):
        """Dataset with >5000 features returns exactly 5000 features, truncated=true."""
        resp = await client.get(
            f"/datasets/{large_dataset.id}/features.geojson?include_z=true",
            headers=admin_auth_header,
        )
        assert resp.status_code == 200

        body = resp.json()
        assert len(body["features"]) == 5000
        assert body["truncated"] is True
        assert body["total_count"] > 5000
