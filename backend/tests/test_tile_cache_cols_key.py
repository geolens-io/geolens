"""Integration tests for cols_key participation in the tile cache key.

Tests that the `cols=` query parameter is threaded through to the tile cache
`get` and `set` calls with the correct `cols_key` value, ensuring that tile
requests with different column projections never collide in the cache.

The mock-cache tests fall through to a real PostGIS query (get returns None),
so they require the asyncpg tile pool fixture to be wired up.
"""

import uuid
from unittest.mock import AsyncMock, patch

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
class TestTileCacheColsKey:
    """Test that cols_key participates correctly in the tile cache key.

    Pattern mirrors test_empty_tile_sentinel_cache_hit_returns_204 in test_tiles.py:
    mock the cache, set get.return_value = None so the route falls through to
    the real PostGIS path, then assert the call_args on get and set.
    """

    async def test_tile_cache_key_includes_cols_suffix_isolates_projections(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """?cols=value causes tile_cache.get/set to be called with cols_key='value'.

        Two different cols= values cannot collide in the cache because the suffix
        participates in the key construction:
          key = f"tile:{table}:{z}:{x}:{y}:{cols_key}"

        This test asserts that the router passes cols_key="value" when
        ?cols=value is present and cols_key="" when the param is absent.
        """
        table_name = f"cache_key_{uuid.uuid4().hex[:8]}"
        user_id = await get_user_id(test_db_session, settings.geolens_admin_username)
        await _create_tile_test_dataset(
            test_db_session, created_by=user_id, table_name=table_name
        )
        await _create_data_table(test_db_session, table_name)

        try:
            mock_cache = AsyncMock()
            # get returns None → route falls through to PostGIS
            mock_cache.get.return_value = None

            with patch(
                "app.processing.tiles.router.get_tile_cache",
                return_value=mock_cache,
            ):
                resp = await client.get(
                    f"/tiles/data.{table_name}/2/2/2.pbf",
                    params={"cols": "value"},
                )

            assert resp.status_code == 200

            # Assert get was called with cols_key="value"
            get_kwargs = mock_cache.get.call_args
            assert get_kwargs is not None, "tile_cache.get was not called"
            assert get_kwargs.kwargs.get("cols_key") == "value", (
                f"Expected cols_key='value' but got: {get_kwargs.kwargs.get('cols_key')!r}"
            )

            # Assert set was also called with cols_key="value" (write path)
            set_kwargs = mock_cache.set.call_args
            assert set_kwargs is not None, "tile_cache.set was not called"
            assert set_kwargs.kwargs.get("cols_key") == "value", (
                f"Expected set cols_key='value' but got: {set_kwargs.kwargs.get('cols_key')!r}"
            )
        finally:
            await _cleanup_data_table(test_db_session, table_name)

    async def test_tile_cache_key_omits_suffix_when_cols_absent_or_empty(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """No ?cols and empty ?cols= both call tile_cache.get with cols_key=''.

        This is the backward-compatible case: pre-fix callers that don't pass
        any `cols` parameter should still hit the original cache key shape
        (no suffix), so existing cached tiles remain valid after the fix ships.
        """
        table_name = f"cache_key_{uuid.uuid4().hex[:8]}"
        user_id = await get_user_id(test_db_session, settings.geolens_admin_username)
        await _create_tile_test_dataset(
            test_db_session, created_by=user_id, table_name=table_name
        )
        await _create_data_table(test_db_session, table_name)

        try:
            # Case 1: no cols param at all
            mock_cache_no_cols = AsyncMock()
            mock_cache_no_cols.get.return_value = None

            with patch(
                "app.processing.tiles.router.get_tile_cache",
                return_value=mock_cache_no_cols,
            ):
                resp_no_cols = await client.get(
                    f"/tiles/data.{table_name}/2/2/2.pbf"
                )

            assert resp_no_cols.status_code == 200
            get_kwargs_no_cols = mock_cache_no_cols.get.call_args
            assert get_kwargs_no_cols is not None
            assert get_kwargs_no_cols.kwargs.get("cols_key") == "", (
                f"Expected empty cols_key for no-cols request, "
                f"got: {get_kwargs_no_cols.kwargs.get('cols_key')!r}"
            )

            # Case 2: empty ?cols= string
            mock_cache_empty = AsyncMock()
            mock_cache_empty.get.return_value = None

            with patch(
                "app.processing.tiles.router.get_tile_cache",
                return_value=mock_cache_empty,
            ):
                resp_empty = await client.get(
                    f"/tiles/data.{table_name}/2/2/2.pbf",
                    params={"cols": ""},
                )

            assert resp_empty.status_code == 200
            get_kwargs_empty = mock_cache_empty.get.call_args
            assert get_kwargs_empty is not None
            assert get_kwargs_empty.kwargs.get("cols_key") == "", (
                f"Expected empty cols_key for empty-string cols request, "
                f"got: {get_kwargs_empty.kwargs.get('cols_key')!r}"
            )
        finally:
            await _cleanup_data_table(test_db_session, table_name)
