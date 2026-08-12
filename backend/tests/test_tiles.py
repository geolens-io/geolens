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

import pytest
from httpx import AsyncClient
from sqlalchemy import text

from app.core.config import settings
from app.modules.catalog.datasets.domain.models import Dataset, Record

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
# display), inside one 48-px bucket of the world-min-anchored grid; "lone"
# is far away in its own bucket so it must come through as a single.
_WEB_MERCATOR_WORLD_WIDTH = 40075016.6855785
_WORLD_MIN = -_WEB_MERCATOR_WORLD_WIDTH / 2
_CLUSTER_SEMANTICS_POINTS = (
    ("pair_a", -800_000.0, 300_000.0),
    ("pair_b", 1_548_145.0, 300_000.0),
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
        dataset = await _create_tile_test_dataset(
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
        # fix(#868): the key carries the cluster SQL semantic version, bumped to
        # v3 by fix(#874) (per-cluster expansion_zoom) so deploys drop stale tiles.
        # fix(#1429): the dataset id sits between the table and the cluster
        # segments, so a reused table name cannot read the previous dataset's
        # cluster tiles, and `label` carries the bare table name for the metric.
        mock_cache.get.assert_awaited_once_with(
            f"{table_name}:ds{dataset.id.hex}:cluster:v3:r64:z12",
            0,
            0,
            0,
            cols_key="",
            label=table_name,
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
    def _rows_sql(
        table_name: str,
        input_cap: int | None = None,
        feature_cap: int | None = None,
    ) -> str:
        """The shipped cluster query with ST_AsMVT swapped for a row SELECT.

        Reuses every CTE of _build_cluster_tile_query verbatim (bounds,
        candidates, bucketed, grouped, features) so the assertions exercise
        the exact SQL the endpoint executes; only the final MVT encode is
        replaced because the suite carries no MVT decoder dependency.
        ``input_cap`` / ``feature_cap`` swap the candidate / feature LIMITs
        for tiny values so tests can saturate the caps without huge
        fixtures. ``mvt_x``/``mvt_y`` expose the emitted geometry in tile
        coordinates ([0, 4096] means inside the tile).
        """
        from app.processing.tiles.service import (
            _CLUSTER_INPUT_LIMIT,
            _TILE_FEATURE_LIMIT,
            _build_cluster_tile_query,
        )

        query = _build_cluster_tile_query(
            table_name, attr_columns=[{"name": "name", "type": "text"}]
        )
        for cap, current in (
            (input_cap, _CLUSTER_INPUT_LIMIT),
            (feature_cap, _TILE_FEATURE_LIMIT),
        ):
            if cap is not None:
                capped = query.replace(f"LIMIT {current}", f"LIMIT {cap}")
                assert capped != query, "LIMIT not found; update this test"
                query = capped
        head, sep, _tail = query.rpartition("SELECT ST_AsMVT")
        assert sep, "cluster query tail changed; update this test's split point"
        # $4 (layer name) only appeared inside ST_AsMVT; keep it referenced so
        # the prepared statement still binds all six parameters.
        return head + (
            "SELECT $4::text AS layer_name, cluster, point_count,\n"
            "    point_count_abbreviated, expansion_zoom, source_gid, name,\n"
            "    ST_X(geom) AS mvt_x, ST_Y(geom) AS mvt_y\n"
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
        assert math.floor((xs[0] - _WORLD_MIN) / old_bucket) != math.floor(
            (xs[1] - _WORLD_MIN) / old_bucket
        ), "fixture points no longer demonstrate the pre-#868 split"
        # New math: world-min-anchored grid, 48 real CSS px per bucket.
        new_bucket = _WEB_MERCATOR_WORLD_WIDTH * 48 * (4096 / 512) / 4096
        assert math.floor((xs[0] - _WORLD_MIN) / new_bucket) == math.floor(
            (xs[1] - _WORLD_MIN) / new_bucket
        )

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
        tile whose envelope contains the cell's ownership anchor (the cell
        origin). A point in the neighbor's interior never leaks into the
        other tile's output."""
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
        # The pair shares one world-min-anchored bucket cell that straddles
        # the border, and the cell ORIGIN (the ownership anchor) falls on the
        # x=0 side: tile (0,1) owns the cell.
        cell = math.floor((points[0][1] - _WORLD_MIN) / bucket)
        assert cell == math.floor((points[1][1] - _WORLD_MIN) / bucket)
        assert points[0][1] < border < points[1][1]
        assert _WORLD_MIN + cell * bucket < border
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

    async def test_past_max_zoom_ring_does_not_starve_cap(self, test_db_session):
        """fix(#868, codex round 3): past cluster max zoom nothing clusters,
        so the scan uses NO envelope expansion. With expansion, lower-gid
        neighbor points could consume the whole candidate cap and then all
        be discarded as ring-only, leaving the tile empty — a starvation
        mode the pre-PR tile-bounded scan never had."""
        from app.processing.tiles.pool import get_tile_pool

        table_name = f"cluster_ring_{uuid.uuid4().hex[:8]}"
        points = (
            # gids 1-3: just west of the z2 x=0/x=1 border — inside the
            # would-be expansion ring of tile (1,1), outside the tile itself.
            ("ring_1", -10_118_754.0, 5_000_000.0),
            ("ring_2", -10_120_000.0, 5_000_000.0),
            ("ring_3", -10_130_000.0, 5_000_000.0),
            # gid 4: interior of tile (1,1). Highest gid: an expanded scan
            # with cap 2 would pick two ring rows and drop this one.
            ("interior", -5_000_000.0, 5_000_000.0),
        )
        await _create_cluster_semantics_table(
            test_db_session, table_name, points=points
        )

        try:
            pool = get_tile_pool()
            # z=2 > cluster_max_zoom=1: unclustered mode, cap saturated at 2.
            sql = self._rows_sql(table_name, input_cap=2)
            rows = await pool.fetch(sql, 2, 1, 1, f"data.{table_name}", 1, 48)
        finally:
            await _cleanup_data_table(test_db_session, table_name)

        # The tile's own point survives; the un-expanded scan never spends
        # the cap on neighbor rows that ownership would discard.
        assert [r["name"] for r in rows] == ["interior"]
        assert rows[0]["cluster"] is None

    async def test_west_edge_cell_is_owned(self, test_db_session):
        """fix(#868, codex round 3): the grid anchors at the world minimum,
        so the cell holding a point near lon -180 has an in-world origin
        and IS owned by the west edge tile. A 0-anchored grid put that
        cell's origin outside the world: no tile owned it and the point
        vanished at clustering zooms."""
        from app.processing.tiles.pool import get_tile_pool

        table_name = f"cluster_west_{uuid.uuid4().hex[:8]}"
        points = (("west", _WORLD_MIN + 1_000.0, 5_000_000.0),)
        await _create_cluster_semantics_table(
            test_db_session, table_name, points=points
        )

        try:
            pool = get_tile_pool()
            sql = self._rows_sql(table_name)
            # Clustering zoom (z=1 <= cmz=14): ownership uses cell origins.
            rows = await pool.fetch(sql, 1, 0, 0, f"data.{table_name}", 14, 48)
        finally:
            await _cleanup_data_table(test_db_session, table_name)

        assert [r["name"] for r in rows] == ["west"]
        assert rows[0]["cluster"] is None

    async def test_emitted_geometry_is_clamped_into_owner_tile(self, test_db_session):
        """fix(#868, codex round 4): a cell owned via its anchor can have a
        raw centroid inside the NEIGHBOR tile; a viewport covering the
        centroid but not the owner tile never requests the owner tile, so
        out-of-tile geometry would be invisible. The emitted point is
        clamped into the owning tile (here: its east edge), and the
        neighbor still emits nothing for the cell."""
        from app.processing.tiles.pool import get_tile_pool

        table_name = f"cluster_clamp_{uuid.uuid4().hex[:8]}"
        tile_w = _WEB_MERCATOR_WORLD_WIDTH / 4
        bucket = tile_w * 48 * (4096 / 512) / 4096
        border = -tile_w  # boundary between z2 tiles x=0 and x=1
        points = (
            ("pair_left", -10_038_754.0, 5_000_000.0),  # tile x=0 side
            ("pair_right", -9_718_754.0, 5_000_000.0),  # tile x=1 side
        )
        # Same cell (its origin on the x=0 side: tile (0,1) owns it), but
        # the pair's centroid falls on the x=1 side of the border.
        cell = math.floor((points[0][1] - _WORLD_MIN) / bucket)
        assert cell == math.floor((points[1][1] - _WORLD_MIN) / bucket)
        assert _WORLD_MIN + cell * bucket < border
        assert (points[0][1] + points[1][1]) / 2 > border
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

        assert len(owner_rows) == 1
        assert owner_rows[0]["cluster"] is True
        assert owner_rows[0]["point_count"] == 2
        # The emitted geometry lies within the owner tile's coordinate
        # space, pulled to just inside its east edge (extent = 4096).
        assert 0 <= owner_rows[0]["mvt_x"] <= 4096
        assert owner_rows[0]["mvt_x"] >= 4090
        assert 0 <= owner_rows[0]["mvt_y"] <= 4096
        # The neighbor (which contains the raw centroid) emits nothing.
        assert len(neighbor_rows) == 0

    async def test_expansion_zoom_is_the_cluster_split_zoom(self, test_db_session):
        """fix(#874): expansion_zoom is the zoom at which THIS cluster stops
        sharing one bucket cell, not the constant cluster_max_zoom + 1 the
        query used to emit for every cluster (click-to-zoom on a z2
        continent-sized cluster jumped straight to z15).

        Three pairs, each alone in its own cell of one z2 tile, so one query
        returns three clusters with three different honest values.
        """
        from app.processing.tiles.pool import get_tile_pool

        table_name = f"cluster_expand_{uuid.uuid4().hex[:8]}"
        # z2 grid: bucket = tile width * 48 CSS px * 8 extent units/px / 4096.
        bucket = (_WEB_MERCATOR_WORLD_WIDTH / 4) * 48 * (4096 / 512) / 4096

        # Cells 12/15/18 have their origins inside tile (2, 1, 1); y is shared
        # within each pair, so only the x spread can split a cell. Inside cell
        # k the zoom-(2+n) cell boundaries sit at offsets j/2^n, and
        # floor((k + offset) * 2^n) == k * 2^n + floor(offset * 2^n), so the
        # split zoom depends on the offsets alone, not on k.
        def at(cell: int, offset: float) -> float:
            return _WORLD_MIN + (cell + offset) * bucket

        y = 5_000_000.0
        points = (
            # gid 1-2: offsets 0.4 / 0.6 straddle the cell's z3 midline.
            ("wide_a", at(12, 0.4), y),
            ("wide_b", at(12, 0.6), y),
            # gid 3-4: offsets 0.1 / 0.105. floor(o * 2^n) first differs at
            # n = 7 (12.8 vs 13.44), so this pair holds together until z9.
            ("tight_a", at(15, 0.1), y),
            ("tight_b", at(15, 0.105), y),
            # gid 5-6: half a metre apart, with no cell boundary between them
            # at any zoom <= 14 (the z14 bucket is ~229 m) — the pair never
            # splits while clustering is active, so the clamp still applies.
            ("never_a", at(18, 0.1), y),
            ("never_b", at(18, 0.1) + 0.5, y),
        )
        await _create_cluster_semantics_table(
            test_db_session, table_name, points=points
        )

        try:
            pool = get_tile_pool()
            rows = await pool.fetch(
                self._rows_sql(table_name),
                2,  # z
                1,  # x
                1,  # y
                f"data.{table_name}",
                14,  # cluster_max_zoom
                48,  # cluster_radius, CSS px
            )
        finally:
            await _cleanup_data_table(test_db_session, table_name)

        assert len(rows) == 3
        assert all(r["cluster"] is True and r["point_count"] == 2 for r in rows)
        # Clusters carry no attributes, so key them by source_gid = min(gid).
        # Pre-#874 every value here was 15.
        assert {r["source_gid"]: r["expansion_zoom"] for r in rows} == {
            1: 3,  # wide pair: splits at the very next zoom
            3: 9,  # tight pair: 7 halvings of the bucket
            5: 15,  # never splits by cluster_max_zoom -> cluster_max_zoom + 1
        }

    async def test_feature_cap_applies_after_ownership(self, test_db_session):
        """fix(#868, codex round 4): the feature cap applies AFTER the
        ownership filter, so neighbor-owned cells seen through the expanded
        scan can never consume the output budget and displace this tile's
        own cells."""
        from app.processing.tiles.pool import get_tile_pool

        table_name = f"cluster_fcap_{uuid.uuid4().hex[:8]}"
        points = (
            # Three neighbor-owned cells visible to tile (1,1)'s expanded
            # scan (cell origins on the x=0 side of the z2 border).
            ("ring_a", -10_038_754.0, 5_000_000.0),
            ("ring_b", -10_700_000.0, 5_000_000.0),
            ("ring_c", -10_700_000.0, 6_000_000.0),
            # The tile's own cell; must survive a feature cap of 1.
            ("interior", -5_000_000.0, 5_000_000.0),
        )
        await _create_cluster_semantics_table(
            test_db_session, table_name, points=points
        )

        try:
            pool = get_tile_pool()
            sql = self._rows_sql(table_name, feature_cap=1)
            rows = await pool.fetch(sql, 2, 1, 1, f"data.{table_name}", 14, 48)
        finally:
            await _cleanup_data_table(test_db_session, table_name)

        # With ownership filtered before the cap, the single budgeted
        # feature is the tile's own cell, not a discarded neighbor cell.
        assert [r["name"] for r in rows] == ["interior"]
        assert rows[0]["cluster"] is None
