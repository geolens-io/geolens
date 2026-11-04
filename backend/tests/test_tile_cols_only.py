"""``cols_only=true`` makes a tile carry exactly the ``cols=`` columns.

The default projection stays: nothing below z10 and everything above, plus
whatever ``cols=`` adds. ``cols_only`` replaces that base with the requested
columns, still bounded by the admin allowlist.
"""

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from app.core.config import settings
from app.processing.tiles import service
from app.processing.tiles.service import (
    _DEFAULT_NO_ATTR_BELOW_ZOOM,
    _select_tile_columns,
    parse_cols_param,
)

from tests.factories import get_user_id
from tests.test_tiles import (
    _cleanup_data_table,
    _create_data_table,
    _create_tile_test_dataset,
)

pytest_plugins = ["tests.test_tiles"]

COLUMNS = [
    {"name": "gid", "type": "integer"},
    {"name": "name", "type": "text"},
    {"name": "value", "type": "integer"},
    {"name": "pop", "type": "integer"},
    {"name": "geom", "type": "geometry"},
    {"name": "geom_4326", "type": "geometry"},
]
HIGH = _DEFAULT_NO_ATTR_BELOW_ZOOM + 2


def _names(cols):
    return [c["name"] for c in cols]


def test_cols_only_carries_exactly_the_named_columns_at_high_zoom():
    result = _select_tile_columns(
        COLUMNS, HIGH, additional_columns=["name"], cols_only=True
    )
    assert _names(result) == ["name"]


def test_cols_only_without_cols_carries_nothing():
    assert _select_tile_columns(COLUMNS, HIGH, cols_only=True) == []
    assert (
        _select_tile_columns(COLUMNS, HIGH, additional_columns=[], cols_only=True) == []
    )


def test_without_cols_only_the_default_projection_is_unchanged():
    result = _select_tile_columns(COLUMNS, HIGH, additional_columns=["name"])
    assert {"name", "value", "pop"} <= set(_names(result))


def test_the_allowlist_still_bounds_cols_only():
    result = _select_tile_columns(
        COLUMNS,
        HIGH,
        tile_columns=["name"],
        additional_columns=["name", "pop"],
        cols_only=True,
    )
    assert _names(result) == ["name"]
    assert (
        _select_tile_columns(
            COLUMNS, HIGH, tile_columns=[], additional_columns=["name"], cols_only=True
        )
        == []
    )


def test_cols_only_still_drops_unknown_and_invalid_names():
    result = _select_tile_columns(
        COLUMNS,
        HIGH,
        additional_columns=["name", "nope", "drop table;"],
        cols_only=True,
    )
    assert _names(result) == ["name"]


def test_cols_only_key_differs_from_the_default_entry_at_every_zoom():
    for z in (2, HIGH):
        default = parse_cols_param("name", COLUMNS, z)[1]
        only = parse_cols_param("name", COLUMNS, z, cols_only=True)[1]
        assert only != default
        assert only == "only:name"
    assert parse_cols_param(None, COLUMNS, HIGH, cols_only=True) == ([], "only:")
    assert parse_cols_param(None, COLUMNS, HIGH) == (None, "")


def test_cols_only_key_names_the_effective_projection():
    a = parse_cols_param("name,value", COLUMNS, 2, cols_only=True)[1]
    b = parse_cols_param("value,name,bogus", COLUMNS, 2, cols_only=True)[1]
    assert a == b == "only:name,value"
    capped = parse_cols_param(
        "name,pop", COLUMNS, 2, tile_columns=["name"], cols_only=True
    )[1]
    assert capped == "only:name"


def test_cluster_mode_key_drops_reserved_names():
    key = parse_cols_param(
        "name,point_count", COLUMNS, 2, mode="cluster", cols_only=True
    )[1]
    assert key == "only:name"


async def _projected(fn, **kwargs):
    """The attribute names the query handed to the database selects."""
    captured = {}

    async def fake_fetch(_conn, query, *_a, **_k):
        captured["query"] = query
        return None

    with patch.object(service, "_fetch_rendered_tile", fake_fetch):
        await fn(AsyncMock(), "cols_only_tbl", 12, 0, 0, COLUMNS, **kwargs)
    return captured["query"]


async def test_plain_tile_query_selects_only_the_named_columns():
    query = await _projected(
        service.get_tile, additional_columns=["name"], cols_only=True
    )
    assert 't."name"' in query
    assert 't."value"' not in query
    assert 't."pop"' not in query


async def test_cluster_tile_query_selects_only_the_named_columns():
    query = await _projected(
        service.get_cluster_tile, additional_columns=["name"], cols_only=True
    )
    assert '"name"' in query
    assert '"value"' not in query
    assert '"pop"' not in query


async def test_tile_queries_without_cols_only_keep_every_column_at_high_zoom():
    query = await _projected(service.get_tile, additional_columns=["name"])
    assert 't."value"' in query and 't."pop"' in query


@pytest.mark.usefixtures("_init_tile_pool_for_tests")
class TestColsOnlyOverHttp:
    async def _dataset(self, test_db_session):
        table_name = f"cols_only_{uuid.uuid4().hex[:8]}"
        user_id = await get_user_id(test_db_session, settings.geolens_admin_username)
        await _create_tile_test_dataset(
            test_db_session, created_by=user_id, table_name=table_name
        )
        await _create_data_table(test_db_session, table_name)
        return table_name

    @pytest.mark.parametrize(
        ("prefix", "target"),
        [
            ("/tiles", "app.processing.tiles.router.get_tile"),
            ("/tiles/clusters", "app.processing.tiles.router.get_cluster_tile"),
        ],
    )
    async def test_the_flag_reaches_the_query_and_the_cache_key(
        self, client: AsyncClient, test_db_session, prefix, target
    ):
        table_name = await self._dataset(test_db_session)
        path = f"{prefix}/data.{table_name}/12/2048/2048.pbf"
        cache = AsyncMock()
        cache.get.return_value = None
        try:
            with (
                patch("app.processing.tiles.router.get_tile_cache", return_value=cache),
                patch(target, AsyncMock(return_value=None)) as spy,
            ):
                resp = await client.get(
                    path, params={"cols": "name", "cols_only": "true"}
                )
                assert resp.status_code in (200, 204), resp.text
                only_key = cache.get.call_args.kwargs["cols_key"]
                assert spy.call_args.kwargs["cols_only"] is True
                assert spy.call_args.kwargs["additional_columns"] == ["name"]

                await client.get(path, params={"cols": "name"})
                default_key = cache.get.call_args.kwargs["cols_key"]
                assert spy.call_args.kwargs["cols_only"] is False
            assert only_key == "only:name"
            assert default_key != only_key
        finally:
            await _cleanup_data_table(test_db_session, table_name)
