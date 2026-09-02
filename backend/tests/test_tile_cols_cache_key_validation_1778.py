"""An unknown `cols=` name never reaches the tile cache key (#1778).

``parse_cols_param`` used to return the caller's own string as the cache-key
segment and leave validation to ``_select_tile_columns``, which drops an
unrecognised name silently. The two together made the key vary on input the
projection ignored: ``?cols=<random>`` missed the byte cache every time, ran the
full ``ST_AsMVT`` behind the miss, gzipped it, and then WROTE an entry holding
bytes byte-identical to the unfiltered tile. The route is ``@limiter.exempt``
and serves public datasets with no credential, so the loop is anonymous and the
default production stack has no Valkey, which puts the writes into an
``LRUCache(maxsize=50_000)`` where ~50k of them evict every legitimate tile.

The property is simple and is what these tests state: two requests that produce
the same bytes produce the same key. An all-unknown ``cols=`` is answered from
the same entry as a request with no ``cols=`` at all.
"""

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from app.core.config import settings
from app.processing.tiles.service import parse_cols_param

from tests.factories import get_user_id
from tests.test_tiles import (
    _cleanup_data_table,
    _create_data_table,
    _create_tile_test_dataset,
)

# Make fixtures defined in test_tiles.py (especially _init_tile_pool_for_tests)
# available to this module without duplicating the fixture body.
pytest_plugins = ["tests.test_tiles"]

COLUMNS = [
    {"name": "gid", "type": "integer"},
    {"name": "name", "type": "text"},
    {"name": "value", "type": "integer"},
]


# ---------------------------------------------------------------------------
# parse_cols_param
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "cols",
    [
        "does_not_exist",
        "nope,also_nope",
        "drop table users;--",
        "  ,  ",
        "1_starts_with_a_digit",
        "x" * 500,
    ],
)
def test_a_name_the_dataset_does_not_have_leaves_the_key_empty(cols: str):
    """Nothing a request cannot project may distinguish its cache entry."""
    assert parse_cols_param(cols, COLUMNS) == (None, "")


def test_the_key_is_built_from_the_surviving_names_only():
    """A partly-bogus request keys on exactly what it will project."""
    assert parse_cols_param("value,bogus", COLUMNS) == (["value"], "value")
    assert parse_cols_param("value", COLUMNS) == (["value"], "value")


def test_permutations_and_duplicates_still_collapse():
    """The #403 property survives: sorted and deduped, so orderings collide."""
    assert parse_cols_param("value,name", COLUMNS)[1] == "name,value"
    assert parse_cols_param("name,value", COLUMNS)[1] == "name,value"
    assert parse_cols_param("value,value, name ", COLUMNS)[1] == "name,value"


def test_a_dataset_with_no_column_info_projects_nothing():
    """No column set to validate against means no name can be validated."""
    assert parse_cols_param("value", []) == (None, "")
    assert parse_cols_param("value", None) == (None, "")


def test_absent_and_empty_cols_are_unchanged():
    assert parse_cols_param(None, COLUMNS) == (None, "")
    assert parse_cols_param("", COLUMNS) == (None, "")


# ---------------------------------------------------------------------------
# The HTTP path
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("_init_tile_pool_for_tests")
class TestUnknownColsSharesTheUnfilteredEntry:
    """Mirrors TestTileCacheColsKey: mock the cache, read the call args.

    ``get`` returns None so the route falls through to the real PostGIS path,
    which is what makes the ``set`` assertion meaningful: the write is the half
    that fills the LRU.
    """

    async def test_unknown_cols_reads_and_writes_the_no_cols_entry(
        self, client: AsyncClient, test_db_session
    ):
        table_name = f"cols_v_{uuid.uuid4().hex[:8]}"
        user_id = await get_user_id(test_db_session, settings.geolens_admin_username)
        await _create_tile_test_dataset(
            test_db_session, created_by=user_id, table_name=table_name
        )
        await _create_data_table(test_db_session, table_name)

        try:
            mock_cache = AsyncMock()
            mock_cache.get.return_value = None
            with patch(
                "app.processing.tiles.router.get_tile_cache",
                return_value=mock_cache,
            ):
                resp = await client.get(
                    f"/tiles/data.{table_name}/2/2/2.pbf",
                    params={"cols": uuid.uuid4().hex},
                )

            assert resp.status_code == 200
            assert mock_cache.get.call_args.kwargs.get("cols_key") == "", (
                "an unknown name must not distinguish the lookup key: the tile "
                "it produces is the unfiltered one. Got "
                f"{mock_cache.get.call_args.kwargs.get('cols_key')!r}"
            )
            assert mock_cache.set.call_args.kwargs.get("cols_key") == "", (
                "nor the write key, which is the half that fills the LRU. Got "
                f"{mock_cache.set.call_args.kwargs.get('cols_key')!r}"
            )
        finally:
            await _cleanup_data_table(test_db_session, table_name)

    async def test_a_real_column_still_gets_its_own_entry(
        self, client: AsyncClient, test_db_session
    ):
        """The control: validation must not collapse projections that differ."""
        table_name = f"cols_r_{uuid.uuid4().hex[:8]}"
        user_id = await get_user_id(test_db_session, settings.geolens_admin_username)
        await _create_tile_test_dataset(
            test_db_session, created_by=user_id, table_name=table_name
        )
        await _create_data_table(test_db_session, table_name)

        try:
            mock_cache = AsyncMock()
            mock_cache.get.return_value = None
            with patch(
                "app.processing.tiles.router.get_tile_cache",
                return_value=mock_cache,
            ):
                resp = await client.get(
                    f"/tiles/data.{table_name}/2/2/2.pbf",
                    params={"cols": "value,not_a_column"},
                )

            assert resp.status_code == 200
            assert mock_cache.get.call_args.kwargs.get("cols_key") == "value"
        finally:
            await _cleanup_data_table(test_db_session, table_name)
