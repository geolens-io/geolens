"""The tile cache key names the effective projection, not the request (#1778).

``parse_cols_param`` used to return the caller's own string as the cache-key
segment and defer validation to ``_select_tile_columns``, which drops a name it
does not recognise silently. So the key varied on input the projection ignores,
and it did so in three ways that compound:

* an unknown name, which is dropped and leaves the unfiltered tile under a
  fresh key;
* ANY valid subset at or above ``_DEFAULT_NO_ATTR_BELOW_ZOOM``, where the zoom
  default already projects every column, so a wide public table offered
  exponentially many keys for one set of bytes. A name already on an explicit
  ``tile_columns`` allowlist is the same case at any zoom;
* a name no query builder emits: ``gid``/``geom``/``geom_4326`` on either
  route, and the cluster query's own ``point_count``/``cluster_id`` family on
  the cluster route.

Each cost a full ``ST_AsMVT`` on an anonymous, ``@limiter.exempt`` route
serving public datasets, and then wrote the result. The default production
stack has no Valkey, so the writes land in an ``LRUCache(maxsize=50_000)`` and
evict legitimate tiles.

The property these tests state is one sentence: two requests that produce the
same SQL produce the same cache key. The key carries what a request ADDS to the
projection the tile would have had anyway, which is well defined because
``additional_columns`` only ever unions into the base selection, and which
keeps an empty suffix meaning what it has always meant.
"""

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from app.core.config import settings
from app.processing.tiles.service import (
    _DEFAULT_NO_ATTR_BELOW_ZOOM,
    parse_cols_param,
)

from tests.factories import get_user_id
from tests.test_tiles import (
    _cleanup_data_table,
    _create_data_table,
    _create_tile_test_dataset,
)

# Make fixtures defined in test_tiles.py (especially _init_tile_pool_for_tests)
# available to this module without duplicating the fixture body.
pytest_plugins = ["tests.test_tiles"]

# The shape test_tiles.py's helper registers, plus a third attribute so
# "two distinct subsets" has somewhere to go.
COLUMNS = [
    {"name": "gid", "type": "integer"},
    {"name": "name", "type": "text"},
    {"name": "value", "type": "integer"},
    {"name": "pop", "type": "integer"},
    {"name": "geom", "type": "geometry"},
    {"name": "geom_4326", "type": "geometry"},
]

LOW = _DEFAULT_NO_ATTR_BELOW_ZOOM - 1  # zoom default projects nothing
HIGH = _DEFAULT_NO_ATTR_BELOW_ZOOM  # zoom default projects everything


def _key(cols, z, **kwargs):
    return parse_cols_param(cols, COLUMNS, z, **kwargs)[1]


# ---------------------------------------------------------------------------
# At and above the zoom threshold every valid subset is the same tile
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "cols",
    [None, "name", "value", "pop", "name,value", "name,value,pop", "pop,name"],
)
def test_every_subset_collapses_onto_one_key_at_high_zoom(cols):
    """z >= the threshold projects every column, so no subset changes anything.

    This is the expensive half of the finding: on a wide table the caller had
    2**n keys for one set of bytes, and cycling them is cheaper for the caller
    than serving them is for the server.
    """
    assert _key(cols, HIGH) == ""


def test_an_allowlisted_name_adds_nothing_at_any_zoom():
    """An explicit `tile_columns` allowlist is the same case as the zoom default.

    fix(#1778, second pass): a name OUTSIDE the allowlist now adds nothing
    either, because `_select_tile_columns` intersects `cols=` with
    `tile_columns` instead of unioning past it. That is the same collapse this
    module was written for -- the tile is byte-identical to the unfiltered one
    -- reached by the projection no longer changing at all.
    """
    for z in (LOW, HIGH):
        assert _key("name", z, tile_columns=["name"]) == ""
        assert _key("value", z, tile_columns=["name"]) == ""
        assert _key("name,value", z, tile_columns=["name"]) == ""


# ---------------------------------------------------------------------------
# Below it, the key still separates projections that really differ
# ---------------------------------------------------------------------------


def test_two_distinct_subsets_keep_distinct_keys_below_the_threshold():
    """The control. Collapsing everything would be a correctness bug, not a fix."""
    assert _key("name", LOW) == "name"
    assert _key("value", LOW) == "value"
    assert _key("name,value", LOW) == "name,value"
    assert len({_key(c, LOW) for c in ("name", "value", "name,value")}) == 3


def test_permutations_and_duplicates_still_collapse():
    """The fix(#403) property survives: sorted and deduped."""
    assert _key("value,name", LOW) == "name,value"
    assert _key("name,value", LOW) == "name,value"
    assert _key("value,value, name ", LOW) == "name,value"


@pytest.mark.parametrize("excluded", ["gid", "geom", "geom_4326"])
def test_a_subset_carrying_an_excluded_name_keys_as_the_subset_without_it(excluded):
    """No query builder emits these, so naming one changes no byte."""
    assert _key(f"name,{excluded}", LOW) == _key("name", LOW) == "name"
    assert _key(excluded, LOW) == _key(None, LOW) == ""


def test_the_cluster_route_also_drops_the_names_its_own_query_emits():
    """`point_count` is an output column of the cluster query, not an input.

    The vector route has no such output, so the same request is a real
    projection change there. The key has to follow the route, which is why
    `mode` reaches it.
    """
    columns = COLUMNS + [{"name": "point_count", "type": "integer"}]
    cluster = parse_cols_param("point_count", columns, LOW, mode="cluster")[1]
    vector = parse_cols_param("point_count", columns, LOW)[1]
    assert cluster == ""
    assert vector == "point_count"


# ---------------------------------------------------------------------------
# Names the dataset does not have
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
def test_a_name_the_dataset_does_not_have_leaves_the_key_empty(cols):
    """Nothing a request cannot project may distinguish its cache entry."""
    assert parse_cols_param(cols, COLUMNS, LOW) == (None, "")


def test_the_returned_list_is_still_the_validated_request():
    """Only the KEY moved. The projection input is unchanged, and still filtered.

    ``_select_tile_columns`` re-validates whatever reaches it, so handing it
    the request rather than the difference keeps this function's two outputs
    independently checkable.
    """
    assert parse_cols_param("value,bogus", COLUMNS, LOW) == (["value"], "value")
    assert parse_cols_param("value", COLUMNS, HIGH) == (["value"], "")


def test_a_dataset_with_no_column_info_projects_nothing():
    """No column set to validate against means no name can be validated."""
    assert parse_cols_param("value", [], LOW) == (None, "")
    assert parse_cols_param("value", None, LOW) == (None, "")


def test_absent_and_empty_cols_are_unchanged():
    assert parse_cols_param(None, COLUMNS, LOW) == (None, "")
    assert parse_cols_param("", COLUMNS, LOW) == (None, "")


# ---------------------------------------------------------------------------
# The HTTP path
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("_init_tile_pool_for_tests")
class TestTheKeyTheRouterActuallyPasses:
    """Mirrors TestTileCacheColsKey: mock the cache, read the call args.

    ``get`` returns None so the route falls through to the real PostGIS path,
    which is what makes the ``set`` assertion meaningful: the write is the half
    that fills the LRU.
    """

    async def _cols_keys(self, client, table_name, path, cols):
        mock_cache = AsyncMock()
        mock_cache.get.return_value = None
        with patch(
            "app.processing.tiles.router.get_tile_cache",
            return_value=mock_cache,
        ):
            resp = await client.get(path, params={"cols": cols})
        assert resp.status_code in (200, 204), resp.text
        return (
            mock_cache.get.call_args.kwargs.get("cols_key"),
            mock_cache.set.call_args.kwargs.get("cols_key"),
        )

    async def _dataset(self, test_db_session, prefix):
        table_name = f"{prefix}_{uuid.uuid4().hex[:8]}"
        user_id = await get_user_id(test_db_session, settings.geolens_admin_username)
        await _create_tile_test_dataset(
            test_db_session, created_by=user_id, table_name=table_name
        )
        await _create_data_table(test_db_session, table_name)
        return table_name

    async def test_high_zoom_requests_share_the_no_cols_entry(
        self, client: AsyncClient, test_db_session
    ):
        """Tile 12/2048/2048 corners on (0, 0), where the fixture's point sits.

        z=12 is past the attribute-budget threshold, so the tile carries every
        column whatever the caller asks for, and all four requests here must
        read and write one entry.
        """
        table_name = await self._dataset(test_db_session, "cols_hi")
        path = f"/tiles/data.{table_name}/12/2048/2048.pbf"
        try:
            for cols in ("name", "value", "name,value", uuid.uuid4().hex):
                get_key, set_key = await self._cols_keys(client, table_name, path, cols)
                assert get_key == "", (
                    f"?cols={cols} at z=12 projects what the tile already "
                    f"carried, so it must read the default entry; got {get_key!r}"
                )
                assert set_key == "", (
                    f"and must write it rather than a new one; got {set_key!r}"
                )
        finally:
            await _cleanup_data_table(test_db_session, table_name)

    async def test_low_zoom_keeps_a_real_projection_apart(
        self, client: AsyncClient, test_db_session
    ):
        """The control at the other side of the threshold, over HTTP."""
        table_name = await self._dataset(test_db_session, "cols_lo")
        path = f"/tiles/data.{table_name}/2/2/2.pbf"
        try:
            value_key, _ = await self._cols_keys(client, table_name, path, "value")
            name_key, _ = await self._cols_keys(client, table_name, path, "name")
            unknown_key, unknown_set = await self._cols_keys(
                client, table_name, path, uuid.uuid4().hex
            )
            assert value_key == "value"
            assert name_key == "name"
            assert unknown_key == "", (
                "an unknown name must not distinguish the lookup key: the tile "
                f"it produces is the unfiltered one. Got {unknown_key!r}"
            )
            assert unknown_set == "", (
                "nor the write key, which is the half that fills the LRU. Got "
                f"{unknown_set!r}"
            )
        finally:
            await _cleanup_data_table(test_db_session, table_name)
