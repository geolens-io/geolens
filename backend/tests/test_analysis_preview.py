"""Tests for the parameterized PostGIS analysis preview endpoint (M4).

Exercises /datasets/{id}/analysis/preview/ plus the pure SQL builder.

Requirements:
  - Docker database must be running (docker compose up db)
"""

import math
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalog.datasets.domain.schemas import AnalysisPreviewRequest
from app.modules.catalog.datasets.domain.service import build_preview_sql

from tests.factories import create_dataset, get_user_id

SQUARE = "POLYGON((0 0, 0 1, 1 1, 1 0, 0 0))"
FAR_SQUARE = "POLYGON((10 10, 10 11, 11 11, 11 10, 10 10))"

# Mask overlapping only SQUARE's lower-left quarter.
CLIP_MASK = {
    "type": "Polygon",
    "coordinates": [[[-0.5, -0.5], [-0.5, 0.5], [0.5, 0.5], [0.5, -0.5], [-0.5, -0.5]]],
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _create_polygon_dataset(
    session: AsyncSession,
    *,
    created_by: uuid.UUID,
    visibility: str = "public",
):
    """Create a real data table with two polygons + its catalog rows."""
    table_name = f"ds_{uuid.uuid4().hex[:12]}"
    await session.execute(
        text(
            f"CREATE TABLE data.{table_name} ("
            f"  gid SERIAL PRIMARY KEY,"
            f"  name TEXT,"
            f"  geom geometry(Polygon, 4326),"
            f"  geom_4326 geometry(Polygon, 4326)"
            f")"
        )
    )
    await session.execute(
        text(
            f"INSERT INTO data.{table_name} (name, geom, geom_4326) VALUES "
            f"('a', ST_GeomFromText('{SQUARE}', 4326),"
            f" ST_GeomFromText('{SQUARE}', 4326)),"
            f"('b', ST_GeomFromText('{FAR_SQUARE}', 4326),"
            f" ST_GeomFromText('{FAR_SQUARE}', 4326))"
        )
    )
    await session.commit()
    return await create_dataset(
        session,
        created_by=created_by,
        table_name=table_name,
        geometry_type="POLYGON",
        feature_count=2,
        visibility=visibility,
    )


async def _create_point_dataset(
    session: AsyncSession, *, created_by: uuid.UUID, n: int
):
    """Create a data table with ``n`` points along the equator."""
    table_name = f"ds_{uuid.uuid4().hex[:12]}"
    await session.execute(
        text(
            f"CREATE TABLE data.{table_name} ("
            f"  gid SERIAL PRIMARY KEY,"
            f"  geom geometry(Point, 4326),"
            f"  geom_4326 geometry(Point, 4326)"
            f")"
        )
    )
    await session.execute(
        text(
            f"INSERT INTO data.{table_name} (geom, geom_4326) "
            f"SELECT ST_SetSRID(ST_MakePoint(i * 0.001, 0), 4326),"
            f"       ST_SetSRID(ST_MakePoint(i * 0.001, 0), 4326) "
            f"FROM generate_series(1, {n}) AS i"
        )
    )
    await session.commit()
    return await create_dataset(
        session,
        created_by=created_by,
        table_name=table_name,
        geometry_type="POINT",
        feature_count=n,
    )


def _preview_url(dataset_id) -> str:
    return f"/datasets/{dataset_id}/analysis/preview/"


# ---------------------------------------------------------------------------
# Endpoint tests
# ---------------------------------------------------------------------------


class TestAnalysisPreviewEndpoint:
    async def test_buffer_preview(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_polygon_dataset(test_db_session, created_by=admin_id)
        resp = await client.post(
            _preview_url(ds.id),
            json={"operation": "buffer", "distance_meters": 1000},
            headers=admin_auth_header,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["feature_count"] == 2
        assert data["truncated"] is False
        fc = data["geojson"]
        assert fc["type"] == "FeatureCollection"
        assert len(fc["features"]) == 2
        for feature in fc["features"]:
            assert feature["geometry"]["type"] in ("Polygon", "MultiPolygon")
            assert "gid" in feature["properties"]
        # A 1km buffer extends past the unit square's origin corner.
        assert data["bbox"][0] < 0

    async def test_centroid_preview(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_polygon_dataset(test_db_session, created_by=admin_id)
        resp = await client.post(
            _preview_url(ds.id),
            json={"operation": "centroid"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["feature_count"] == 2
        types = {f["geometry"]["type"] for f in data["geojson"]["features"]}
        assert types == {"Point"}
        # Centroid of the unit square is (0.5, 0.5).
        first = data["geojson"]["features"][0]["geometry"]["coordinates"]
        assert first == pytest.approx([0.5, 0.5])

    async def test_clip_preview(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_polygon_dataset(test_db_session, created_by=admin_id)
        resp = await client.post(
            _preview_url(ds.id),
            json={"operation": "clip", "mask": CLIP_MASK},
            headers=admin_auth_header,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        # Only the near square intersects the mask.
        assert data["feature_count"] == 1
        bbox = data["bbox"]
        assert bbox == pytest.approx([0.0, 0.0, 0.5, 0.5])

    async def test_buffer_requires_distance(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_polygon_dataset(test_db_session, created_by=admin_id)
        resp = await client.post(
            _preview_url(ds.id),
            json={"operation": "buffer"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 422

    async def test_buffer_distance_cap(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_polygon_dataset(test_db_session, created_by=admin_id)
        resp = await client.post(
            _preview_url(ds.id),
            json={"operation": "buffer", "distance_meters": 200_000},
            headers=admin_auth_header,
        )
        assert resp.status_code == 422

    async def test_clip_rejects_non_polygon_mask(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_polygon_dataset(test_db_session, created_by=admin_id)
        resp = await client.post(
            _preview_url(ds.id),
            json={
                "operation": "clip",
                "mask": {"type": "LineString", "coordinates": [[0, 0], [1, 1]]},
            },
            headers=admin_auth_header,
        )
        assert resp.status_code == 422

    async def test_clip_rejects_malformed_mask(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_polygon_dataset(test_db_session, created_by=admin_id)
        resp = await client.post(
            _preview_url(ds.id),
            json={
                "operation": "clip",
                "mask": {"type": "Polygon", "coordinates": "'; DROP TABLE x; --"},
            },
            headers=admin_auth_header,
        )
        assert resp.status_code == 422

    async def test_requires_auth(
        self,
        client: AsyncClient,
        test_db_session: AsyncSession,
    ):
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_polygon_dataset(test_db_session, created_by=admin_id)
        resp = await client.post(
            _preview_url(ds.id),
            json={"operation": "centroid"},
        )
        assert resp.status_code == 401

    async def test_private_dataset_hidden_from_other_user(
        self,
        client: AsyncClient,
        viewer_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """IDOR guard: a private dataset 404s for a non-owner."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_polygon_dataset(
            test_db_session, created_by=admin_id, visibility="private"
        )
        resp = await client.post(
            _preview_url(ds.id),
            json={"operation": "centroid"},
            headers=viewer_auth_header,
        )
        assert resp.status_code == 404

    async def test_non_vector_dataset_rejected(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await create_dataset(
            test_db_session,
            created_by=admin_id,
            geometry_type=None,
        )
        resp = await client.post(
            _preview_url(ds.id),
            json={"operation": "centroid"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 422

    async def test_truncation_at_feature_cap(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_point_dataset(test_db_session, created_by=admin_id, n=501)
        resp = await client.post(
            _preview_url(ds.id),
            json={"operation": "centroid"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["feature_count"] == 500
        assert data["truncated"] is True


# ---------------------------------------------------------------------------
# Pure SQL-builder tests (no DB)
# ---------------------------------------------------------------------------


class TestBuildPreviewSql:
    def test_buffer_sql(self):
        req = AnalysisPreviewRequest(operation="buffer", distance_meters=500)
        sql = build_preview_sql('"data"."t1"', req)
        assert "ST_Buffer(geom_4326::geography, 500.0)::geometry" in sql
        assert 'FROM "data"."t1"' in sql
        assert "ORDER BY gid" in sql

    def test_centroid_sql(self):
        req = AnalysisPreviewRequest(operation="centroid")
        sql = build_preview_sql('"data"."t1"', req)
        assert "ST_Centroid(geom_4326)" in sql

    def test_clip_mask_is_reserialized(self):
        req = AnalysisPreviewRequest(operation="clip", mask=CLIP_MASK)
        sql = build_preview_sql('"data"."t1"', req)
        assert "ST_GeomFromGeoJSON" in sql
        assert "ST_Intersects" in sql
        # The mask appears twice (expression + WHERE); each embed contributes
        # exactly its two wrapping quotes — shapely re-serialization guarantees
        # no quote characters inside the JSON itself.
        assert sql.count("'") == 4

    def test_clip_mask_injection_rejected(self):
        req = AnalysisPreviewRequest(
            operation="clip",
            mask={"type": "Polygon", "coordinates": "'; DROP TABLE x; --"},
        )
        with pytest.raises(ValueError):
            build_preview_sql('"data"."t1"', req)

    def test_clip_mask_vertex_cap(self):
        ring = [
            [
                math.cos(i * 2 * math.pi / 6000) * 0.01,
                math.sin(i * 2 * math.pi / 6000) * 0.01,
            ]
            for i in range(6000)
        ]
        ring.append(ring[0])
        req = AnalysisPreviewRequest(
            operation="clip", mask={"type": "Polygon", "coordinates": [ring]}
        )
        with pytest.raises(ValueError, match="vertices"):
            build_preview_sql('"data"."t1"', req)
