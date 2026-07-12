"""End-to-end tests for the GeoParquet export path.

Unlike test_export.py (which mocks the ogr2ogr service), the parquet path is
written directly via pyarrow and must run against a real data table. These
tests create a 3-row point table, export it, and read the bytes back with
pyarrow to assert the GeoParquet `geo` metadata and geometry decoding.

Requires the Docker database (docker compose up db) with migrations applied.
"""

import json
import uuid

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from httpx import AsyncClient
from sqlalchemy import text

from tests.factories import get_user_id
from tests.test_export import _create_dataset


@pytest.fixture
async def parquet_dataset(test_db_session):
    """Real 3-row point table + Dataset row for GeoParquet export."""
    table_name = f"exp_pq_{uuid.uuid4().hex[:12]}"
    await test_db_session.execute(
        text(
            f"CREATE TABLE data.{table_name} "
            "(gid serial PRIMARY KEY, pop integer, name text, "
            "geom geometry(Point, 4326), geom_4326 geometry(Point, 4326))"
        )
    )
    await test_db_session.execute(
        text(
            f"INSERT INTO data.{table_name} (pop, name, geom, geom_4326) VALUES "
            "(10, 'a', ST_SetSRID(ST_MakePoint(0, 0), 4326), "
            " ST_SetSRID(ST_MakePoint(0, 0), 4326)), "
            "(20, 'b', ST_SetSRID(ST_MakePoint(1, 1), 4326), "
            " ST_SetSRID(ST_MakePoint(1, 1), 4326)), "
            "(30, 'c', ST_SetSRID(ST_MakePoint(2, 2), 4326), "
            " ST_SetSRID(ST_MakePoint(2, 2), 4326))"
        )
    )
    await test_db_session.commit()

    admin_id = await get_user_id(test_db_session, "admin")
    ds = await _create_dataset(
        test_db_session,
        created_by=admin_id,
        name="ParquetExportDS",
        table_name=table_name,
        geometry_type="Point",
        feature_count=3,
        column_info=[
            {"name": "gid", "type": "integer"},
            {"name": "pop", "type": "integer"},
            {"name": "name", "type": "text"},
        ],
    )
    yield ds
    await test_db_session.execute(text(f"DROP TABLE IF EXISTS data.{table_name}"))
    await test_db_session.commit()


def _read_parquet(content: bytes):
    return pq.read_table(pa.BufferReader(content))


class TestGeoParquetExport:
    @pytest.mark.anyio
    async def test_export_parquet_valid_geoparquet(
        self, client: AsyncClient, admin_auth_header: dict, parquet_dataset
    ):
        """format=parquet returns a valid GeoParquet: geo metadata + all rows."""
        resp = await client.get(
            f"/datasets/{parquet_dataset.id}/export",
            params={"format": "parquet"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 200
        assert "parquet" in resp.headers["content-type"]

        table = _read_parquet(resp.content)
        assert table.num_rows == 3
        assert "geometry" in table.column_names
        assert {"pop", "name"} <= set(table.column_names)

        # GeoParquet file-level `geo` metadata is present and well-formed.
        meta = table.schema.metadata
        assert meta is not None and b"geo" in meta
        geo = json.loads(meta[b"geo"])
        assert geo["version"] == "1.1.0"
        assert geo["primary_column"] == "geometry"
        assert geo["columns"]["geometry"]["encoding"] == "WKB"

        # Geometry column decodes as valid WKB.
        from shapely import wkb as shapely_wkb

        geoms = table.column("geometry").to_pylist()
        assert len(geoms) == 3
        pt = shapely_wkb.loads(geoms[0])
        assert pt.geom_type == "Point"

    @pytest.mark.anyio
    async def test_export_parquet_where_filter(
        self, client: AsyncClient, admin_auth_header: dict, parquet_dataset
    ):
        """A where clause narrows the exported rows."""
        resp = await client.get(
            f"/datasets/{parquet_dataset.id}/export",
            params={"format": "parquet", "where": "pop > 25"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 200
        table = _read_parquet(resp.content)
        assert table.num_rows == 1

    @pytest.mark.anyio
    async def test_export_parquet_bbox_exact_intersection(
        self, client: AsyncClient, admin_auth_header: dict, parquet_dataset
    ):
        """A bbox selects only features that actually intersect it (points at
        (0,0),(1,1),(2,2); bbox around (1,1) returns exactly one)."""
        resp = await client.get(
            f"/datasets/{parquet_dataset.id}/export",
            params={"format": "parquet", "bbox": "0.5,0.5,1.5,1.5"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 200
        assert _read_parquet(resp.content).num_rows == 1

    @pytest.mark.anyio
    async def test_export_parquet_rejects_non_4326_crs(
        self, client: AsyncClient, admin_auth_header: dict, parquet_dataset
    ):
        """A non-4326 target_crs is rejected (parquet is CRS84-only)."""
        resp = await client.get(
            f"/datasets/{parquet_dataset.id}/export",
            params={"format": "parquet", "target_crs": "EPSG:3857"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 400
        assert "4326" in resp.json()["detail"]

    @pytest.mark.anyio
    async def test_export_parquet_allows_4326_crs(
        self, client: AsyncClient, admin_auth_header: dict, parquet_dataset
    ):
        """target_crs=EPSG:4326 is the identity case and is allowed."""
        resp = await client.get(
            f"/datasets/{parquet_dataset.id}/export",
            params={"format": "parquet", "target_crs": "EPSG:4326"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 200

    @pytest.mark.anyio
    async def test_export_parquet_non_spatial_400(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """A non-spatial dataset cannot be exported as parquet."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_dataset(
            test_db_session,
            created_by=admin_id,
            name="NonSpatialParquetDS",
            geometry_type=None,
        )
        resp = await client.get(
            f"/datasets/{ds.id}/export",
            params={"format": "parquet"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 400
        assert "non-spatial" in resp.json()["detail"].lower()
