"""Integration tests for tile gateway endpoint.

Tests the /tiles/data.{table}/{z}/{x}/{y}.pbf endpoint that serves
vector tiles via PostGIS ST_AsMVT.

Requirements:
  - Docker database must be running (docker compose up db)
  - Alembic migrations must be applied
"""

import gzip
import math
import time
import uuid
from unittest.mock import AsyncMock, patch

import asyncpg
import pytest
from httpx import AsyncClient
from sqlalchemy import text

from app.core.config import settings
from app.modules.catalog.datasets.domain.models import Dataset, Record

from tests.conftest import _run_with_too_many_clients_retry
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


async def _create_multipoint_data_table(session, table_name: str) -> None:
    """Create a PostGIS data table with a multipoint feature."""
    await session.execute(
        text(
            f"CREATE TABLE IF NOT EXISTS data.{table_name} ("
            f"  gid SERIAL PRIMARY KEY,"
            f"  name TEXT,"
            f"  value INTEGER,"
            f"  geom GEOMETRY(MultiPoint, 3857),"
            f"  geom_4326 GEOMETRY(MultiPoint, 4326)"
            f")"
        )
    )
    await session.execute(
        text(
            f"CREATE INDEX IF NOT EXISTS idx_{table_name}_geom_4326 "
            f"ON data.{table_name} USING GIST (geom_4326)"
        )
    )
    await session.execute(
        text(
            f"INSERT INTO data.{table_name} (name, value, geom, geom_4326) VALUES ("
            f"  'test_multipoint', 42,"
            f"  ST_Transform(ST_Multi(ST_SetSRID(ST_MakePoint(0, 0), 4326)), 3857),"
            f"  ST_Multi(ST_SetSRID(ST_MakePoint(0, 0), 4326))"
            f")"
        )
    )
    await session.commit()


async def _cleanup_data_table(session, table_name: str) -> None:
    """Drop the test data table."""
    await session.execute(text(f"DROP TABLE IF EXISTS data.{table_name}"))
    await session.commit()


# fix(#868): coordinates for the cluster bucket-semantics regression test.
# EPSG:3857 meters. pair_a/pair_b sit ~30 CSS px apart on a z0 tile (512 px
# display), inside one absolute 48-px bucket; "lone" is far away in its own
# bucket so it must come through as an unclustered single.
_WEB_MERCATOR_WORLD_WIDTH = 40075016.6855785
_CLUSTER_SEMANTICS_POINTS = (
    ("pair_a", 300_000.0, 300_000.0),
    ("pair_b", 2_648_145.0, 300_000.0),
    ("lone", -10_000_000.0, -5_000_000.0),
)


async def _create_cluster_semantics_table(
    session, table_name: str, points=_CLUSTER_SEMANTICS_POINTS
) -> None:
    """Point table holding the fix(#868) bucket-semantics fixture points."""
    await session.execute(
        text(
            f"CREATE TABLE IF NOT EXISTS data.{table_name} ("
            f"  gid SERIAL PRIMARY KEY,"
            f"  name TEXT,"
            f"  geom_4326 GEOMETRY(Point, 4326)"
            f")"
        )
    )
    for name, x, y in points:
        await session.execute(
            text(
                f"INSERT INTO data.{table_name} (name, geom_4326) VALUES ("
                f"  :name,"
                f"  ST_Transform(ST_SetSRID(ST_MakePoint(:x, :y), 3857), 4326)"
                f")"
            ),
            {"name": name, "x": x, "y": y},
        )
    await session.commit()


@pytest.fixture
async def _init_tile_pool_for_tests():
    """Initialize a real asyncpg pool pointing at the test database for tile tests.

    The test client uses ASGITransport which does not run the app lifespan,
    so we need to create the tile pool manually.
    """
    import app.processing.tiles.pool as pool_module

    dsn = settings.test_database_url.replace("postgresql+asyncpg://", "postgresql://")
    pool = await _run_with_too_many_clients_retry(
        lambda: asyncpg.create_pool(dsn=dsn, min_size=1, max_size=3, command_timeout=10)
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

    async def test_tile_response_has_etag_and_supports_304(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """MVT-04: vector tile carries an ETag and honors If-None-Match -> 304."""
        table_name = f"tile_etag_{uuid.uuid4().hex[:8]}"
        user_id = await get_user_id(test_db_session, settings.geolens_admin_username)
        await _create_tile_test_dataset(
            test_db_session, created_by=user_id, table_name=table_name
        )
        await _create_data_table(test_db_session, table_name)

        try:
            resp = await client.get(f"/tiles/data.{table_name}/0/0/0.pbf")
            assert resp.status_code == 200
            etag = resp.headers.get("etag")
            assert etag

            conditional = await client.get(
                f"/tiles/data.{table_name}/0/0/0.pbf",
                headers={"If-None-Match": etag},
            )
            assert conditional.status_code == 304
            assert conditional.headers.get("etag") == etag
        finally:
            await _cleanup_data_table(test_db_session, table_name)

    async def test_cluster_tile_response_has_etag_and_supports_304(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """MVT-04: cluster tile carries an ETag and honors If-None-Match -> 304."""
        table_name = f"cluster_etag_{uuid.uuid4().hex[:8]}"
        user_id = await get_user_id(test_db_session, settings.geolens_admin_username)
        await _create_tile_test_dataset(
            test_db_session, created_by=user_id, table_name=table_name
        )
        await _create_data_table(test_db_session, table_name)

        try:
            resp = await client.get(f"/tiles/clusters/data.{table_name}/0/0/0.pbf")
            assert resp.status_code == 200
            etag = resp.headers.get("etag")
            assert etag

            conditional = await client.get(
                f"/tiles/clusters/data.{table_name}/0/0/0.pbf",
                headers={"If-None-Match": etag},
            )
            assert conditional.status_code == 304
            assert conditional.headers.get("etag") == etag
        finally:
            await _cleanup_data_table(test_db_session, table_name)

    async def test_cluster_tile_endpoint_returns_mvt(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """GET /tiles/clusters/data.{table}/{z}/{x}/{y}.pbf returns MVT bytes."""
        table_name = f"cluster_tile_{uuid.uuid4().hex[:8]}"
        user_id = await get_user_id(test_db_session, settings.geolens_admin_username)
        await _create_tile_test_dataset(
            test_db_session, created_by=user_id, table_name=table_name
        )
        await _create_data_table(test_db_session, table_name)

        try:
            resp = await client.get(f"/tiles/clusters/data.{table_name}/0/0/0.pbf")
            assert resp.status_code == 200
            assert resp.headers["content-type"] == "application/vnd.mapbox-vector-tile"
            assert resp.headers["content-encoding"] == "gzip"
            assert len(resp.content) > 0
        finally:
            await _cleanup_data_table(test_db_session, table_name)

    async def test_cluster_tile_endpoint_handles_multipoint(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """Point-family cluster tiles handle imported multipoint geometries."""
        table_name = f"cluster_multi_{uuid.uuid4().hex[:8]}"
        user_id = await get_user_id(test_db_session, settings.geolens_admin_username)
        dataset = await _create_tile_test_dataset(
            test_db_session, created_by=user_id, table_name=table_name
        )
        dataset.geometry_type = "MultiPoint"
        await test_db_session.commit()
        await _create_multipoint_data_table(test_db_session, table_name)

        try:
            resp = await client.get(f"/tiles/clusters/data.{table_name}/0/0/0.pbf")
            assert resp.status_code == 200
            assert resp.headers["content-type"] == "application/vnd.mapbox-vector-tile"
            assert len(resp.content) > 0
        finally:
            await _cleanup_data_table(test_db_session, table_name)

    async def test_cluster_tile_rejects_non_point_dataset(
        self, client: AsyncClient, test_db_session
    ):
        """Cluster tiles fail before PostGIS for non-point vector datasets."""
        table_name = f"cluster_poly_{uuid.uuid4().hex[:8]}"
        user_id = await get_user_id(test_db_session, settings.geolens_admin_username)
        dataset = await _create_tile_test_dataset(
            test_db_session, created_by=user_id, table_name=table_name
        )
        dataset.geometry_type = "Polygon"
        await test_db_session.commit()

        resp = await client.get(f"/tiles/clusters/data.{table_name}/0/0/0.pbf")

        assert resp.status_code == 400
        assert resp.json()["detail"] == "Cluster tiles require a vector point dataset"

    async def test_cluster_tile_cache_key_includes_options(
        self, client: AsyncClient, test_db_session
    ):
        """Cluster tile cache keys are separate from normal vector tile keys."""
        table_name = f"cluster_cache_{uuid.uuid4().hex[:8]}"
        user_id = await get_user_id(test_db_session, settings.geolens_admin_username)
        await _create_tile_test_dataset(
            test_db_session, created_by=user_id, table_name=table_name
        )
        mock_cache = AsyncMock()
        mock_cache.get.return_value = gzip.compress(b"cached-cluster-tile")

        with patch(
            "app.processing.tiles.router.get_tile_cache", return_value=mock_cache
        ):
            resp = await client.get(
                f"/tiles/clusters/data.{table_name}/0/0/0.pbf",
                params={"cluster_radius": 64, "cluster_max_zoom": 12},
            )

        assert resp.status_code == 200
        # fix(#403): the cluster endpoint now supports the cols= opt-in, so
        # its cache lookups carry a cols_key segment (empty without cols=).
        # fix(#868): the key carries the cluster SQL semantic version (v2).
        mock_cache.get.assert_awaited_once_with(
            f"{table_name}:cluster:v2:r64:z12", 0, 0, 0, cols_key=""
        )

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

            with patch(
                "app.processing.tiles.router.get_tile_cache", return_value=mock_cache
            ):
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


@pytest.mark.usefixtures("_init_tile_pool_for_tests")
class TestVectorTileAuth:
    """Vector tile access control for private datasets.

    The /tiles/{table_path}/{z}/{x}/{y}.pbf endpoint is exempt from the
    normal auth dependency so that public datasets can be served with
    zero-cost requests. For non-public datasets it must enforce a valid
    HMAC signature (sig/exp/scope query params).
    """

    async def test_private_tile_unsigned_returns_403(
        self, client: AsyncClient, test_db_session
    ):
        """Private dataset tile request without signature returns 403."""
        table_name = f"tile_priv_{uuid.uuid4().hex[:8]}"
        user_id = await get_user_id(test_db_session, settings.geolens_admin_username)
        # Create a private dataset
        record = Record(
            title="Private tile dataset",
            visibility="private",
            record_status="published",
            created_by=user_id,
        )
        test_db_session.add(record)
        await test_db_session.flush()
        dataset = Dataset(
            record_id=record.id,
            table_name=table_name,
            srid=4326,
            geometry_type="Point",
            feature_count=0,
            source_format="geojson",
            column_info=[{"name": "gid", "type": "integer"}],
        )
        test_db_session.add(dataset)
        await test_db_session.commit()
        await _create_data_table(test_db_session, table_name)
        try:
            resp = await client.get(f"/tiles/data.{table_name}/0/0/0.pbf")
            assert resp.status_code == 403
        finally:
            await _cleanup_data_table(test_db_session, table_name)

    async def test_private_tile_invalid_signature_returns_403(
        self, client: AsyncClient, test_db_session
    ):
        """Private dataset tile request with tampered signature returns 403."""
        table_name = f"tile_priv_{uuid.uuid4().hex[:8]}"
        user_id = await get_user_id(test_db_session, settings.geolens_admin_username)
        record = Record(
            title="Private tile dataset 2",
            visibility="private",
            record_status="published",
            created_by=user_id,
        )
        test_db_session.add(record)
        await test_db_session.flush()
        dataset = Dataset(
            record_id=record.id,
            table_name=table_name,
            srid=4326,
            geometry_type="Point",
            feature_count=0,
            source_format="geojson",
            column_info=[{"name": "gid", "type": "integer"}],
        )
        test_db_session.add(dataset)
        await test_db_session.commit()
        await _create_data_table(test_db_session, table_name)
        try:
            # Tampered signature with valid-looking exp in the future
            resp = await client.get(
                f"/tiles/data.{table_name}/0/0/0.pbf"
                f"?sig=deadbeef&exp=9999999999&scope={table_name}"
            )
            assert resp.status_code == 403
        finally:
            await _cleanup_data_table(test_db_session, table_name)

    async def test_private_cluster_tile_requires_signature(
        self, client: AsyncClient, test_db_session
    ):
        """Private cluster tile requests reuse vector tile HMAC auth rules."""
        table_name = f"cluster_priv_{uuid.uuid4().hex[:8]}"
        user_id = await get_user_id(test_db_session, settings.geolens_admin_username)
        record = Record(
            title="Private cluster dataset",
            visibility="private",
            record_status="published",
            created_by=user_id,
        )
        test_db_session.add(record)
        await test_db_session.flush()
        dataset = Dataset(
            record_id=record.id,
            table_name=table_name,
            srid=4326,
            geometry_type="Point",
            feature_count=0,
            source_format="geojson",
            column_info=[{"name": "gid", "type": "integer"}],
        )
        test_db_session.add(dataset)
        await test_db_session.commit()

        resp = await client.get(f"/tiles/clusters/data.{table_name}/0/0/0.pbf")

        assert resp.status_code == 403
        assert "Signature required" in resp.json()["detail"]

    async def test_private_cluster_tile_with_valid_signature(
        self, client: AsyncClient, test_db_session
    ):
        """Private cluster tiles accept the normal vector tile HMAC signature."""
        from app.processing.tiles.signing import generate_tile_signature

        table_name = f"cluster_signed_{uuid.uuid4().hex[:8]}"
        user_id = await get_user_id(test_db_session, settings.geolens_admin_username)
        record = Record(
            title="Signed private cluster dataset",
            visibility="private",
            record_status="published",
            created_by=user_id,
        )
        test_db_session.add(record)
        await test_db_session.flush()
        dataset = Dataset(
            record_id=record.id,
            table_name=table_name,
            srid=4326,
            geometry_type="Point",
            feature_count=1,
            source_format="geojson",
            column_info=[{"name": "gid", "type": "integer"}],
        )
        test_db_session.add(dataset)
        await test_db_session.commit()
        await _create_data_table(test_db_session, table_name)

        try:
            exp = int(time.time()) + 300
            sig = generate_tile_signature(table_name, exp)
            resp = await client.get(
                f"/tiles/clusters/data.{table_name}/0/0/0.pbf",
                params={"sig": sig, "exp": exp, "scope": table_name},
            )

            assert resp.status_code == 200
            assert resp.headers["content-type"] == "application/vnd.mapbox-vector-tile"
        finally:
            await _cleanup_data_table(test_db_session, table_name)


class TestTileQueryStructure:
    """Test tile query SQL structure and column selection."""

    def test_tile_query_column_selection(self):
        """Tile query excludes geom, geom_4326 from attribute columns."""
        from app.processing.tiles.service import _build_attr_columns

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
        from app.processing.tiles.service import _build_tile_query

        columns = [{"name": "name", "type": "text"}]
        query = _build_tile_query("test_table", columns)
        assert "4096" in query
        assert "256" in query
        assert "ST_AsMVTGeom" in query
        assert "ST_AsMVT" in query
        assert '"data"."test_table"' in query  # DP-02: schema-qualified
        # Verify bounds CTE precomputes geom_4326
        assert "bounds.geom_4326" in query
        assert "ST_Transform(bounds.geom, 4326)" not in query

    def test_tile_query_single_transform_in_where(self):
        """WHERE clause uses precomputed bounds.geom_4326, not ST_Transform."""
        from app.processing.tiles.service import _build_tile_query

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
        from app.processing.tiles.service import _build_tile_query

        columns = [{"name": "name", "type": "text"}]
        query = _build_tile_query("my_dataset", columns)
        # The layer name is passed as a parameter ($4), but we verify the query
        # structure expects it
        assert "$4" in query  # layer name parameter

    def test_cluster_tile_query_emits_cluster_properties(self):
        """Cluster tile query emits MapLibre-compatible cluster properties."""
        from app.processing.tiles.service import _build_cluster_tile_query

        query = _build_cluster_tile_query("cluster_dataset")

        assert '"data"."cluster_dataset"' in query  # DP-02: schema-qualified
        assert "point_count" in query
        assert "point_count_abbreviated" in query
        assert "cluster_id" in query
        assert "source_gid" in query
        assert "ST_AsMVTGeom" in query
        assert "ST_AsMVT" in query
        assert "ST_PointOnSurface(t.geom_4326)" in query
        assert "$5::integer" in query  # cluster max zoom
        assert "$6::float8" in query  # cluster radius


class TestTilePool:
    """Test separate asyncpg pool initialization."""

    def test_get_tile_pool_raises_when_not_initialized(self):
        """get_tile_pool raises RuntimeError when pool not initialized."""
        import app.processing.tiles.pool as pool_module

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
        from app.processing.tiles.service import _validate_tile_table_name

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


@pytest.mark.usefixtures("_init_tile_pool_for_tests")
class TestClusterBucketSemantics:
    """fix(#868): SQL-level regression tests for the cluster bucket grid.

    The shipped math treated cluster_radius (CSS px) as MVT extent units,
    building a ~8x-too-fine grid: overlapping cluster circles plus
    unclustered singles leaking at low zoom.
    """

    @staticmethod
    def _rows_sql(table_name: str, input_cap: int | None = None) -> str:
        """The shipped cluster query with ST_AsMVT swapped for a row SELECT.

        Reuses every CTE of _build_cluster_tile_query verbatim (bounds,
        candidates, bucketed, grouped, features) so the assertions exercise
        the exact SQL the endpoint executes; only the final MVT encode is
        replaced because the suite carries no MVT decoder dependency.
        ``input_cap`` swaps the candidate LIMIT for a tiny value so tests
        can saturate the cap without 100k fixture rows.
        """
        from app.processing.tiles.service import (
            _CLUSTER_INPUT_LIMIT,
            _build_cluster_tile_query,
        )

        query = _build_cluster_tile_query(
            table_name, attr_columns=[{"name": "name", "type": "text"}]
        )
        if input_cap is not None:
            capped = query.replace(
                f"LIMIT {_CLUSTER_INPUT_LIMIT}", f"LIMIT {input_cap}"
            )
            assert capped != query, "candidate LIMIT not found; update this test"
            query = capped
        head, sep, _tail = query.rpartition("SELECT ST_AsMVT")
        assert sep, "cluster query tail changed; update this test's split point"
        # $4 (layer name) only appeared inside ST_AsMVT; keep it referenced so
        # the prepared statement still binds all six parameters.
        return head + (
            "SELECT $4::text AS layer_name, cluster, point_count,\n"
            "    point_count_abbreviated, source_gid, name\n"
            "FROM features\nWHERE geom IS NOT NULL"
        )

    async def test_radius_is_css_px_and_lone_point_stays_single(self, test_db_session):
        """Two points ~30 px apart at z0 with radius 48 land in ONE cluster
        (the pre-#868 math split them), and a lone point comes through as an
        unclustered single carrying its projected attributes."""
        from app.processing.tiles.pool import get_tile_pool

        table_name = f"cluster_sem_{uuid.uuid4().hex[:8]}"
        await _create_cluster_semantics_table(test_db_session, table_name)

        # Spec of the regression in plain arithmetic (z0 tile = whole world).
        xs = [_CLUSTER_SEMANTICS_POINTS[0][1], _CLUSTER_SEMANTICS_POINTS[1][1]]
        pair_px = abs(xs[1] - xs[0]) / _WEB_MERCATOR_WORLD_WIDTH * 512
        assert 29.0 < pair_px < 31.0  # ~30 CSS px apart
        # Old math: tile-anchored grid, px treated as extent units (~5.5 px).
        old_bucket = _WEB_MERCATOR_WORLD_WIDTH * 48 / 4096
        half_world = _WEB_MERCATOR_WORLD_WIDTH / 2
        assert math.floor((xs[0] + half_world) / old_bucket) != math.floor(
            (xs[1] + half_world) / old_bucket
        ), "fixture points no longer demonstrate the pre-#868 split"
        # New math: absolute grid, 48 real CSS px per bucket.
        new_bucket = _WEB_MERCATOR_WORLD_WIDTH * 48 * (4096 / 512) / 4096
        assert math.floor(xs[0] / new_bucket) == math.floor(xs[1] / new_bucket)

        try:
            pool = get_tile_pool()
            rows = await pool.fetch(
                self._rows_sql(table_name),
                0,  # z
                0,  # x
                0,  # y
                f"data.{table_name}",
                14,  # cluster_max_zoom
                48,  # cluster_radius, CSS px
            )
        finally:
            await _cleanup_data_table(test_db_session, table_name)

        assert len(rows) == 2
        clusters = [r for r in rows if r["cluster"]]
        singles = [r for r in rows if not r["cluster"]]
        assert len(clusters) == 1
        assert clusters[0]["point_count"] == 2
        assert clusters[0]["point_count_abbreviated"] == "2"
        assert clusters[0]["name"] is None  # attrs stay off cluster features
        assert len(singles) == 1
        assert singles[0]["point_count"] is None
        assert singles[0]["source_gid"] is not None
        assert singles[0]["name"] == "lone"  # attr projection on singles

    async def test_straddling_cell_emitted_by_exactly_one_tile(self, test_db_session):
        """fix(#868, codex P2 on PR #872): a bucket cell straddling a tile
        border is computed from its complete membership by both neighbors
        (expanded candidate scan) and emitted by exactly one of them, the
        tile whose envelope contains the cell centroid. A point in the
        neighbor's interior never leaks into the other tile's output."""
        from app.processing.tiles.pool import get_tile_pool

        table_name = f"cluster_seam_{uuid.uuid4().hex[:8]}"
        # z2 arithmetic: tile width = world/4, bucket = width * 48 px * 8/4096.
        tile_w = _WEB_MERCATOR_WORLD_WIDTH / 4
        bucket = tile_w * 48 * (4096 / 512) / 4096
        border = -tile_w  # boundary between z2 tiles x=0 and x=1
        points = (
            ("pair_left", -10_218_754.0, 5_000_000.0),  # tile x=0 side
            ("pair_right", -9_918_754.0, 5_000_000.0),  # tile x=1 side
            ("interior", -5_000_000.0, 5_000_000.0),  # tile x=1 interior
        )
        # The pair shares one absolute bucket cell that straddles the border,
        # and the cell ORIGIN (the ownership anchor) falls on the x=0 side:
        # tile (0,1) owns the cell.
        assert math.floor(points[0][1] / bucket) == math.floor(points[1][1] / bucket)
        assert points[0][1] < border < points[1][1]
        assert math.floor(points[0][1] / bucket) * bucket < border
        await _create_cluster_semantics_table(
            test_db_session, table_name, points=points
        )

        try:
            pool = get_tile_pool()
            sql = self._rows_sql(table_name)
            layer = f"data.{table_name}"
            owner_rows = await pool.fetch(sql, 2, 0, 1, layer, 14, 48)
            neighbor_rows = await pool.fetch(sql, 2, 1, 1, layer, 14, 48)
        finally:
            await _cleanup_data_table(test_db_session, table_name)

        # Owning tile: exactly the straddling cluster with FULL membership.
        assert len(owner_rows) == 1
        assert owner_rows[0]["cluster"] is True
        assert owner_rows[0]["point_count"] == 2
        # Neighbor: only its interior single. The straddling cell is not
        # re-emitted, and the expanded scan leaks nothing else.
        assert len(neighbor_rows) == 1
        assert neighbor_rows[0]["cluster"] is None
        assert neighbor_rows[0]["name"] == "interior"

    async def test_world_edge_point_owned_by_edge_tile(self, test_db_session):
        """fix(#868, codex round 2): a feature sitting exactly on the world's
        east boundary is emitted by exactly one tile — the edge tile, whose
        upper ownership bound is inclusive (no neighbor exists beyond the
        world). Runs past cluster max zoom, where the ownership anchor is
        the point itself: the only anchor that can land exactly on the
        boundary (lon 180 transforms to exactly the world XMax; verified
        against PostGIS/proj on the test DB)."""
        from app.processing.tiles.pool import get_tile_pool

        table_name = f"cluster_edge_{uuid.uuid4().hex[:8]}"
        await test_db_session.execute(
            text(
                f"CREATE TABLE IF NOT EXISTS data.{table_name} ("
                f"  gid SERIAL PRIMARY KEY,"
                f"  name TEXT,"
                f"  geom_4326 GEOMETRY(Point, 4326)"
                f")"
            )
        )
        # Inserted in 4326 directly so lon stays exactly 180.
        await test_db_session.execute(
            text(
                f"INSERT INTO data.{table_name} (name, geom_4326) VALUES "
                f"('edge', ST_SetSRID(ST_MakePoint(180, 85.05112877980659), 4326))"
            )
        )
        await test_db_session.commit()

        try:
            pool = get_tile_pool()
            sql = self._rows_sql(table_name)
            layer = f"data.{table_name}"
            rows_by_tile = {}
            for tx, ty in ((0, 0), (1, 0), (0, 1), (1, 1)):
                # cluster_max_zoom=0 < z=1: unclustered mode, point anchors.
                rows_by_tile[(tx, ty)] = await pool.fetch(sql, 1, tx, ty, layer, 0, 48)
        finally:
            await _cleanup_data_table(test_db_session, table_name)

        assert sum(len(r) for r in rows_by_tile.values()) == 1
        assert len(rows_by_tile[(1, 0)]) == 1
        assert rows_by_tile[(1, 0)][0]["cluster"] is None
        assert rows_by_tile[(1, 0)][0]["name"] == "edge"

    async def test_cap_divergence_emits_shared_cell_at_most_once(self, test_db_session):
        """fix(#868, codex round 2): when the input cap truncates DIFFERENT
        candidate subsets in neighboring tiles, the shared straddling cell
        is still emitted by at most one tile (the anchor owner). The
        degradation is an undercounted single in the owner tile, never a
        cross-tile double-emit."""
        from app.processing.tiles.pool import get_tile_pool

        table_name = f"cluster_cap_{uuid.uuid4().hex[:8]}"
        points = (
            # gid 1: interior of tile (0,1) only — pushes the pair past a
            # cap of 2 in that tile's scan but not in the neighbor's.
            ("west_interior", -15_000_000.0, 5_000_000.0),
            # gids 2 and 3: the straddling pair from the seam test.
            ("pair_left", -10_218_754.0, 5_000_000.0),
            ("pair_right", -9_918_754.0, 5_000_000.0),
        )
        await _create_cluster_semantics_table(
            test_db_session, table_name, points=points
        )

        try:
            pool = get_tile_pool()
            sql = self._rows_sql(table_name, input_cap=2)
            layer = f"data.{table_name}"
            # Owner scan (ordered by gid, cap 2) sees gids 1,2,3 -> keeps 1,2:
            # the owned straddling cell has only one visible member.
            owner_rows = await pool.fetch(sql, 2, 0, 1, layer, 14, 48)
            # Neighbor scan sees gids 2,3 -> keeps both: it computes the full
            # cell but does not own its anchor.
            neighbor_rows = await pool.fetch(sql, 2, 1, 1, layer, 14, 48)
        finally:
            await _cleanup_data_table(test_db_session, table_name)

        # Owner: its interior single plus the UNDERCOUNTED cell (one member
        # visible -> emitted as a single carrying that member's attributes).
        assert sorted(r["name"] for r in owner_rows) == [
            "pair_left",
            "west_interior",
        ]
        assert all(r["cluster"] is None for r in owner_rows)
        # Neighbor: nothing. Anchor ownership does not depend on the scanned
        # subset, so the cell is never double-emitted.
        assert len(neighbor_rows) == 0
