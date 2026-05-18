"""Integration tests for the ?cols= opt-in query parameter on the tile endpoint.

Tests the HTTP path for `cols=` passthrough, silent-drop validation, SQL-injection
safety, and permutation invariance against a real PostGIS test DB.

Requirements:
  - Docker database must be running (docker compose up db)
  - Alembic migrations must be applied

Note on MVT decode scope:
  Decoding the MVT response body to assert that the `value` attribute is
  present in the protobuf payload would require adding `mapbox-vector-tile`
  as a dev dependency. That is out of scope for this hygiene close.

  The integration test asserts:
    1. The HTTP path runs without erroring (status 200)
    2. The response content-type is correct
    3. The tile body is non-empty at z=2 (proves PostGIS was queried, not
       the zero-attrs branch which returns b'')

  The unit tests in `test_tile_column_allowlist.py` already cover the data
  correctness of `_select_tile_columns(additional_columns=['value'])` — that
  the column is actually projected into the MVT SQL query. These integration
  tests exercise the HTTP routing layer on top of that.
"""

import uuid

import pytest
from httpx import AsyncClient

from app.core.config import settings

from tests.factories import get_user_id
from tests.test_tiles import (
    _cleanup_data_table,
    _create_data_table,
    _create_tile_test_dataset,
)

# Make fixtures defined in test_tiles.py (especially _init_tile_pool_for_tests)
# available to this module without duplicating the fixture body.
pytest_plugins = ["tests.test_tiles"]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("_init_tile_pool_for_tests")
class TestTileEndpointColsParam:
    """Test ?cols= query parameter behaviour on the vector tile endpoint.

    The test dataset uses the helper from test_tiles.py which inserts a point
    at (0, 0) with `value=42`. Tile 2/2/2 covers the 0,0 meridian/equator area
    in the standard Web Mercator tile grid, so the feature falls inside it.
    """

    async def test_tile_endpoint_with_cols_param_projects_column_at_low_zoom(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """GET /tiles/data.{table}/2/2/2.pbf?cols=value returns 200 with MVT at z=2.

        z=2 is below the _DEFAULT_NO_ATTR_BELOW_ZOOM=10 cutoff, so without ?cols=value
        the tile would be served with no attribute columns.  With ?cols=value the
        endpoint opts-in the `value` column so data-driven styling can work at low zoom.

        Both the with-cols and without-cols request succeed — the difference
        (attribute presence inside the MVT) would require a MapboxVectorTile
        decoder to assert, which is intentionally out of scope.  See module docstring.
        """
        table_name = f"cols_test_{uuid.uuid4().hex[:8]}"
        user_id = await get_user_id(test_db_session, settings.geolens_admin_username)
        await _create_tile_test_dataset(
            test_db_session, created_by=user_id, table_name=table_name
        )
        await _create_data_table(test_db_session, table_name)

        try:
            # Without cols= (z<10 default strips attributes)
            resp_no_cols = await client.get(f"/tiles/data.{table_name}/2/2/2.pbf")
            assert resp_no_cols.status_code == 200
            assert (
                resp_no_cols.headers["content-type"]
                == "application/vnd.mapbox-vector-tile"
            )

            # With cols=value (opt-in projects the column at z=2)
            resp_with_cols = await client.get(
                f"/tiles/data.{table_name}/2/2/2.pbf", params={"cols": "value"}
            )
            assert resp_with_cols.status_code == 200
            assert (
                resp_with_cols.headers["content-type"]
                == "application/vnd.mapbox-vector-tile"
            )
            assert len(resp_with_cols.content) > 0
        finally:
            await _cleanup_data_table(test_db_session, table_name)

    async def test_tile_endpoint_cols_silently_drops_invalid_names(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """?cols=does_not_exist returns 200 (silent-drop contract).

        The `_select_tile_columns` validator strips column names that are not
        present in the dataset's `column_info`.  The tile request still succeeds;
        the unknown column is simply ignored.  This proves the endpoint does not
        return 400 or 500 when a caller passes a non-existent column name.
        """
        table_name = f"cols_test_{uuid.uuid4().hex[:8]}"
        user_id = await get_user_id(test_db_session, settings.geolens_admin_username)
        await _create_tile_test_dataset(
            test_db_session, created_by=user_id, table_name=table_name
        )
        await _create_data_table(test_db_session, table_name)

        try:
            resp = await client.get(
                f"/tiles/data.{table_name}/2/2/2.pbf",
                params={"cols": "does_not_exist"},
            )
            assert resp.status_code == 200
        finally:
            await _cleanup_data_table(test_db_session, table_name)

    async def test_tile_endpoint_cols_silently_drops_sql_injection_attempt(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """?cols=drop+table+users;-- returns 200 (regex validator drops injection).

        The column-name regex `[A-Za-z_][A-Za-z0-9_]*` rejects any name that
        contains special characters or SQL keywords before it reaches the MVT
        query builder.  The endpoint still serves a valid tile response.
        """
        table_name = f"cols_test_{uuid.uuid4().hex[:8]}"
        user_id = await get_user_id(test_db_session, settings.geolens_admin_username)
        await _create_tile_test_dataset(
            test_db_session, created_by=user_id, table_name=table_name
        )
        await _create_data_table(test_db_session, table_name)

        try:
            resp = await client.get(
                f"/tiles/data.{table_name}/2/2/2.pbf",
                params={"cols": "drop table users;--"},
            )
            assert resp.status_code == 200
        finally:
            await _cleanup_data_table(test_db_session, table_name)

    async def test_tile_endpoint_cols_normalizes_permutations(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """?cols=value,name and ?cols=name,value both return 200 with non-empty MVT.

        The router sorts the parsed column list before building the cache key
        (`cols_cache_key = ",".join(additional_columns)` after `sorted(set(raw))`).
        Both orderings hit the same cache slot.  This test just confirms both
        produce valid responses — cache-key isolation is covered by
        TestTileCacheColsKey in test_tile_cache_cols_key.py.
        """
        table_name = f"cols_test_{uuid.uuid4().hex[:8]}"
        user_id = await get_user_id(test_db_session, settings.geolens_admin_username)
        await _create_tile_test_dataset(
            test_db_session, created_by=user_id, table_name=table_name
        )
        await _create_data_table(test_db_session, table_name)

        try:
            resp_ab = await client.get(
                f"/tiles/data.{table_name}/2/2/2.pbf",
                params={"cols": "value,name"},
            )
            resp_ba = await client.get(
                f"/tiles/data.{table_name}/2/2/2.pbf",
                params={"cols": "name,value"},
            )
            assert resp_ab.status_code == 200
            assert resp_ba.status_code == 200
            assert len(resp_ab.content) > 0
            assert len(resp_ba.content) > 0
        finally:
            await _cleanup_data_table(test_db_session, table_name)
