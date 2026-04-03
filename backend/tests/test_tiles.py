"""Integration tests for tile gateway endpoint.

Tests the /tiles/data.{table}/{z}/{x}/{y}.pbf endpoint that serves
vector tiles via PostGIS ST_AsMVT.

Requirements:
  - Docker database must be running (docker compose up db)
  - Alembic migrations must be applied
"""

import uuid
from unittest.mock import AsyncMock, patch

import asyncpg
import pytest
from httpx import AsyncClient
from sqlalchemy import text

from app.config import settings
from app.datasets.models import Dataset, Record

from tests.factories import get_user_id


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _create_tile_test_dataset(
    session,
    *,
    created_by: uuid.UUID,
    table_name: str,
) -> Dataset:
    """Insert a Record + Dataset with column_info and create an actual data table."""
    record = Record(
        title="Tile Test Dataset",
        summary="Dataset for tile tests",
        theme_category=["test"],
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
        geometry_type="Point",
        feature_count=1,
        source_format="geojson",
        source_filename="test.geojson",
        column_info=[
            {"name": "gid", "type": "integer"},
            {"name": "name", "type": "text"},
            {"name": "value", "type": "integer"},
            {"name": "geom", "type": "geometry"},
            {"name": "geom_4326", "type": "geometry"},
        ],
    )
    session.add(dataset)
    await session.commit()
    await session.refresh(dataset)
    return dataset


async def _create_data_table(session, table_name: str) -> None:
    """Create a PostGIS data table in the 'data' schema with a point feature."""
    await session.execute(
        text(
            f"CREATE TABLE IF NOT EXISTS data.{table_name} ("
            f"  gid SERIAL PRIMARY KEY,"
            f"  name TEXT,"
            f"  value INTEGER,"
            f"  geom GEOMETRY(Point, 3857),"
            f"  geom_4326 GEOMETRY(Point, 4326)"
            f")"
        )
    )
    await session.execute(
        text(
            f"CREATE INDEX IF NOT EXISTS idx_{table_name}_geom_4326 "
            f"ON data.{table_name} USING GIST (geom_4326)"
        )
    )
    # Insert a point at (0, 0) -- falls within tile 0/0/0
    await session.execute(
        text(
            f"INSERT INTO data.{table_name} (name, value, geom, geom_4326) VALUES ("
            f"  'test_point', 42,"
            f"  ST_Transform(ST_SetSRID(ST_MakePoint(0, 0), 4326), 3857),"
            f"  ST_SetSRID(ST_MakePoint(0, 0), 4326)"
            f")"
        )
    )
    await session.commit()


async def _cleanup_data_table(session, table_name: str) -> None:
    """Drop the test data table."""
    await session.execute(text(f"DROP TABLE IF EXISTS data.{table_name}"))
    await session.commit()


@pytest.fixture
async def _init_tile_pool_for_tests():
    """Initialize a real asyncpg pool pointing at the test database for tile tests.

    The test client uses ASGITransport which does not run the app lifespan,
    so we need to create the tile pool manually.
    """
    import app.tiles.pool as pool_module

    dsn = settings.test_database_url.replace("postgresql+asyncpg://", "postgresql://")
    pool = await asyncpg.create_pool(
        dsn=dsn, min_size=1, max_size=3, command_timeout=10
    )
    pool_module._tile_pool = pool
    yield
    await pool.close()
    pool_module._tile_pool = None


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("_init_tile_pool_for_tests")
class TestTileEndpoint:
    """Test tile endpoint returns MVT bytes with correct headers."""

    async def test_tile_endpoint_returns_mvt(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """GET /tiles/data.{table}/{z}/{x}/{y}.pbf returns 200 with MVT bytes."""
        table_name = f"tile_test_{uuid.uuid4().hex[:8]}"
        user_id = await get_user_id(test_db_session, settings.geolens_admin_username)
        await _create_tile_test_dataset(
            test_db_session, created_by=user_id, table_name=table_name
        )
        await _create_data_table(test_db_session, table_name)

        try:
            resp = await client.get(f"/tiles/data.{table_name}/0/0/0.pbf")
            assert resp.status_code == 200
            assert resp.headers["content-type"] == "application/vnd.mapbox-vector-tile"

            # httpx auto-decompresses gzip, so resp.content is raw MVT bytes
            assert len(resp.content) > 0
        finally:
            await _cleanup_data_table(test_db_session, table_name)

    async def test_tile_response_headers(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """Response has correct Content-Type, gzip encoding, and Cache-Control."""
        table_name = f"tile_test_{uuid.uuid4().hex[:8]}"
        user_id = await get_user_id(test_db_session, settings.geolens_admin_username)
        await _create_tile_test_dataset(
            test_db_session, created_by=user_id, table_name=table_name
        )
        await _create_data_table(test_db_session, table_name)

        try:
            resp = await client.get(f"/tiles/data.{table_name}/0/0/0.pbf")
            assert resp.status_code == 200
            assert resp.headers["content-encoding"] == "gzip"
            assert f"max-age={settings.tile_cache_ttl}" in resp.headers["cache-control"]
            assert "public" in resp.headers["cache-control"]
        finally:
            await _cleanup_data_table(test_db_session, table_name)

    async def test_empty_tile_returns_204(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """GET for area with no features returns 204 No Content."""
        table_name = f"tile_test_{uuid.uuid4().hex[:8]}"
        user_id = await get_user_id(test_db_session, settings.geolens_admin_username)
        await _create_tile_test_dataset(
            test_db_session, created_by=user_id, table_name=table_name
        )
        await _create_data_table(test_db_session, table_name)

        try:
            # Tile at high zoom far from (0,0) should be empty
            resp = await client.get(f"/tiles/data.{table_name}/18/100000/100000.pbf")
            assert resp.status_code == 204
        finally:
            await _cleanup_data_table(test_db_session, table_name)

    async def test_empty_tile_sentinel_cache_hit_returns_204(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """Cached empty sentinel (b'') returns 204 without hitting PostGIS."""
        table_name = f"tile_test_{uuid.uuid4().hex[:8]}"
        user_id = await get_user_id(test_db_session, settings.geolens_admin_username)
        await _create_tile_test_dataset(
            test_db_session, created_by=user_id, table_name=table_name
        )
        await _create_data_table(test_db_session, table_name)

        try:
            mock_cache = AsyncMock()
            mock_cache.get.return_value = b""  # empty sentinel

            with patch("app.tiles.router.get_tile_cache", return_value=mock_cache):
                resp = await client.get(f"/tiles/data.{table_name}/0/0/0.pbf")

            assert resp.status_code == 204
            mock_cache.get.assert_called_once()
        finally:
            await _cleanup_data_table(test_db_session, table_name)

    async def test_invalid_table_name_returns_400(self, client: AsyncClient):
        """Invalid table name with SQL injection chars returns 400."""
        resp = await client.get("/tiles/data.drop_table;--/0/0/0.pbf")
        assert resp.status_code == 400

    async def test_nonexistent_table_returns_404(self, client: AsyncClient):
        """Non-existent table returns 404."""
        resp = await client.get("/tiles/data.nonexistent_table_xyz/0/0/0.pbf")
        assert resp.status_code == 404

    async def test_missing_data_prefix_returns_404(self, client: AsyncClient):
        """Table path without 'data.' prefix returns 404."""
        resp = await client.get("/tiles/sometable/0/0/0.pbf")
        assert resp.status_code == 404


class TestTileQueryStructure:
    """Test tile query SQL structure and column selection."""

    def test_tile_query_column_selection(self):
        """Tile query excludes geom, geom_4326 from attribute columns."""
        from app.tiles.service import _build_attr_columns

        columns = [
            {"name": "gid", "type": "integer"},
            {"name": "name", "type": "text"},
            {"name": "value", "type": "integer"},
            {"name": "geom", "type": "geometry"},
            {"name": "geom_4326", "type": "geometry"},
        ]
        result = _build_attr_columns(columns)
        assert "geom" not in result
        assert "geom_4326" not in result
        assert "t.name" in result
        assert "t.value" in result

    def test_tile_query_uses_correct_params(self):
        """Tile query uses ST_AsMVTGeom with 4096 extent, 256 buffer."""
        from app.tiles.service import _build_tile_query

        columns = [{"name": "name", "type": "text"}]
        query = _build_tile_query("test_table", columns)
        assert "4096" in query
        assert "256" in query
        assert "ST_AsMVTGeom" in query
        assert "ST_AsMVT" in query
        assert "data.test_table" in query
        # Verify bounds CTE precomputes geom_4326
        assert "bounds.geom_4326" in query
        assert "ST_Transform(bounds.geom, 4326)" not in query

    def test_tile_query_single_transform_in_where(self):
        """WHERE clause uses precomputed bounds.geom_4326, not ST_Transform."""
        from app.tiles.service import _build_tile_query

        columns = [{"name": "name", "type": "text"}]
        query = _build_tile_query("test_table", columns)
        # bounds CTE should compute geom_4326
        assert "AS geom_4326" in query
        # WHERE should reference bounds.geom_4326 directly
        assert "bounds.geom_4326" in query
        # Should NOT have ST_Transform(bounds.geom, 4326) in WHERE
        assert "ST_Transform(bounds.geom, 4326)" not in query

    def test_mvt_source_layer_name(self):
        """ST_AsMVT uses 'data.{table_name}' as source layer name."""
        from app.tiles.service import _build_tile_query

        columns = [{"name": "name", "type": "text"}]
        query = _build_tile_query("my_dataset", columns)
        # The layer name is passed as a parameter ($4), but we verify the query
        # structure expects it
        assert "$4" in query  # layer name parameter


class TestTilePool:
    """Test separate asyncpg pool initialization."""

    def test_get_tile_pool_raises_when_not_initialized(self):
        """get_tile_pool raises RuntimeError when pool not initialized."""
        import app.tiles.pool as pool_module

        # Ensure pool is None
        original = pool_module._tile_pool
        pool_module._tile_pool = None
        try:
            with pytest.raises(RuntimeError):
                pool_module.get_tile_pool()
        finally:
            pool_module._tile_pool = original

    def test_tile_table_name_validation(self):
        """Invalid table names are rejected."""
        from app.tiles.service import _validate_tile_table_name

        # Valid names
        _validate_tile_table_name("my_table")
        _validate_tile_table_name("table123")

        # Invalid names
        with pytest.raises(ValueError):
            _validate_tile_table_name("DROP TABLE;")
        with pytest.raises(ValueError):
            _validate_tile_table_name("table-name")
        with pytest.raises(ValueError):
            _validate_tile_table_name("Table_Name")
