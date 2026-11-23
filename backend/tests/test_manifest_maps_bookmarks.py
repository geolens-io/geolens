"""Manifest version 2 maps: bookmarks are styling on create, republish and dry run.

Requirements: the docker database must be running with migrations applied.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select

from app.platform.map_bookmarks import MAX_MAP_BOOKMARKS
from app.modules.catalog.maps.models import Map
from tests.test_manifest_maps_apply import _apply, _dataset, _history, _map_row
from tests.test_manifest_maps_dry_run import _admin, _codes
from tests.test_manifest_maps_republish import (
    _builder_save,
    _edit_paint_in_the_builder,
    _publish,
)

pytestmark = pytest.mark.anyio

_PARK = {"name": "Park", "extent": [-89.7, 39.7, -89.6, 39.8]}
_RIVER = {"name": "River", "extent": [-89.9, 39.5, -89.5, 39.9], "bearing": 20}
_KEY = "qgis-map-parks"
_BUILDERS = [{"name": "Mine", "extent": [0, 0, 1, 1]}]


def _names(map_obj) -> list[str]:
    return [b["name"] for b in map_obj.bookmarks or []]


async def test_create_writes_the_bookmarks_in_order(test_db_session, clean_tables):
    admin = await _admin(test_db_session)
    dataset_id = await _dataset(test_db_session, admin.id)

    [created] = (
        await _apply(
            test_db_session,
            admin,
            _publish(dataset_id, bookmarks=[_RIVER, _PARK]),
        )
    ).maps

    stored = (await _map_row(test_db_session, created.map_id)).bookmarks
    assert [b["name"] for b in stored] == ["River", "Park"]
    assert stored[0]["bearing"] == 20


async def test_a_builder_bookmarks_edit_is_kept_and_answers_a070(
    client, test_db_session, admin_auth_header, clean_tables
):
    admin = await _admin(test_db_session)
    dataset_id = await _dataset(test_db_session, admin.id)
    entry = _publish(dataset_id, bookmarks=[_PARK])
    [created] = (await _apply(test_db_session, admin, entry)).maps
    await _builder_save(
        client,
        admin_auth_header,
        test_db_session,
        created.map_id,
        bookmarks=_BUILDERS,
    )

    [checked] = (await _apply(test_db_session, admin, entry, dry_run=True)).maps
    [kept] = (await _apply(test_db_session, admin, entry)).maps

    for result in (checked, kept):
        assert (result.styling, _codes(result)) == ("kept", [("A070", "info", None)])
    assert _names(await _map_row(test_db_session, created.map_id)) == ["Mine"]


async def test_replace_overwrites_a_builder_bookmarks_edit(
    client, test_db_session, admin_auth_header, clean_tables
):
    admin = await _admin(test_db_session)
    dataset_id = await _dataset(test_db_session, admin.id)
    [created] = (
        await _apply(test_db_session, admin, _publish(dataset_id, bookmarks=[_PARK]))
    ).maps
    await _builder_save(
        client,
        admin_auth_header,
        test_db_session,
        created.map_id,
        bookmarks=_BUILDERS,
    )

    [result] = (
        await _apply(
            test_db_session,
            admin,
            _publish(dataset_id, bookmarks=[_RIVER], styling="replace"),
        )
    ).maps

    assert result.styling == "applied"
    assert _names(await _map_row(test_db_session, created.map_id)) == ["River"]


async def test_a_republish_without_bookmarks_leaves_them(test_db_session, clean_tables):
    admin = await _admin(test_db_session)
    dataset_id = await _dataset(test_db_session, admin.id)
    [created] = (
        await _apply(test_db_session, admin, _publish(dataset_id, bookmarks=[_PARK]))
    ).maps

    [result] = (
        await _apply(test_db_session, admin, _publish(dataset_id, view=None))
    ).maps

    assert result.styling == "applied"
    assert _names(await _map_row(test_db_session, created.map_id)) == ["Park"]


async def test_an_empty_list_clears_them_when_styling_applies(
    test_db_session, clean_tables
):
    admin = await _admin(test_db_session)
    dataset_id = await _dataset(test_db_session, admin.id)
    [created] = (
        await _apply(test_db_session, admin, _publish(dataset_id, bookmarks=[_PARK]))
    ).maps

    await _apply(test_db_session, admin, _publish(dataset_id, bookmarks=[]))

    assert (await _map_row(test_db_session, created.map_id)).bookmarks is None


async def test_a_kept_publish_leaves_bookmarks_whatever_it_sends(
    test_db_session, clean_tables
):
    admin = await _admin(test_db_session)
    dataset_id = await _dataset(test_db_session, admin.id)
    [created] = (
        await _apply(test_db_session, admin, _publish(dataset_id, bookmarks=[_PARK]))
    ).maps

    [result] = (
        await _apply(
            test_db_session,
            admin,
            _publish(dataset_id, bookmarks=[_RIVER], styling="keep"),
        )
    ).maps

    assert result.styling == "kept"
    assert _names(await _map_row(test_db_session, created.map_id)) == ["Park"]


async def test_a_builder_bookmarks_edit_doesnt_block_a_publish_without_bookmarks(
    client, test_db_session, admin_auth_header, clean_tables
):
    admin = await _admin(test_db_session)
    dataset_id = await _dataset(test_db_session, admin.id)
    [created] = (await _apply(test_db_session, admin, _publish(dataset_id))).maps
    await _builder_save(
        client,
        admin_auth_header,
        test_db_session,
        created.map_id,
        bookmarks=_BUILDERS,
    )

    [result] = (await _apply(test_db_session, admin, _publish(dataset_id))).maps

    assert (result.styling, result.messages) == ("applied", [])
    assert _names(await _map_row(test_db_session, created.map_id)) == ["Mine"]


async def test_a_bookmarks_edit_before_the_last_publish_that_wrote_them_is_replaced(
    client, test_db_session, admin_auth_header, clean_tables
):
    admin = await _admin(test_db_session)
    dataset_id = await _dataset(test_db_session, admin.id)
    entry = _publish(dataset_id, bookmarks=[_PARK])
    [created] = (await _apply(test_db_session, admin, entry)).maps
    await _builder_save(
        client,
        admin_auth_header,
        test_db_session,
        created.map_id,
        bookmarks=_BUILDERS,
    )
    await _apply(test_db_session, admin, {**entry, "styling": "replace"})

    [result] = (await _apply(test_db_session, admin, entry)).maps

    assert result.styling == "applied"


async def test_a_save_that_sends_no_bookmarks_isnt_a_bookmarks_edit(
    client, test_db_session, admin_auth_header, clean_tables
):
    admin = await _admin(test_db_session)
    dataset_id = await _dataset(test_db_session, admin.id)
    entry = _publish(dataset_id, bookmarks=[_PARK])
    [created] = (await _apply(test_db_session, admin, entry)).maps
    await _builder_save(
        client, admin_auth_header, test_db_session, created.map_id, notes="Mine"
    )

    [result] = (await _apply(test_db_session, admin, entry)).maps

    assert result.styling == "applied"


async def test_layer_edits_still_keep_bookmarks_with_the_rest(
    client, test_db_session, admin_auth_header, clean_tables
):
    admin = await _admin(test_db_session)
    dataset_id = await _dataset(test_db_session, admin.id)
    entry = _publish(dataset_id, bookmarks=[_PARK])
    [created] = (await _apply(test_db_session, admin, entry)).maps
    await _edit_paint_in_the_builder(
        client, admin_auth_header, test_db_session, created.map_id
    )

    [result] = (
        await _apply(test_db_session, admin, {**entry, "bookmarks": [_RIVER]})
    ).maps

    assert result.styling == "kept"
    assert _names(await _map_row(test_db_session, created.map_id)) == ["Park"]


async def test_each_publish_records_whether_it_wrote_bookmarks(
    test_db_session, clean_tables
):
    admin = await _admin(test_db_session)
    dataset_id = await _dataset(test_db_session, admin.id)
    [created] = (
        await _apply(test_db_session, admin, _publish(dataset_id, bookmarks=[_PARK]))
    ).maps
    await _apply(test_db_session, admin, _publish(dataset_id))

    assert [
        e.details["bookmarks_written"]
        for e in await _history(test_db_session, created.map_id)
        if e.action == "manifest.publish"
    ] == [True, False]


async def test_a_dry_run_writes_no_bookmarks(test_db_session, clean_tables):
    admin = await _admin(test_db_session)
    dataset_id = await _dataset(test_db_session, admin.id)
    [created] = (
        await _apply(test_db_session, admin, _publish(dataset_id, bookmarks=[_PARK]))
    ).maps

    [checked] = (
        await _apply(
            test_db_session,
            admin,
            _publish(dataset_id, bookmarks=[_RIVER]),
            dry_run=True,
        )
    ).maps

    assert (checked.action, checked.styling) == ("update", "applied")
    assert _names(await _map_row(test_db_session, created.map_id)) == ["Park"]


@pytest.mark.parametrize(
    "bookmarks",
    [
        [{"name": "Far", "extent": [-181, 0, 0, 1]}],
        [{"name": "Upside down", "extent": [0, 5, 1, 4]}],
        [{"name": "Tilted", "extent": [0, 0, 1, 1], "pitch": 90}],
        [
            {"name": f"b{i}", "extent": [0, 0, 1, 1]}
            for i in range(MAX_MAP_BOOKMARKS + 1)
        ],
    ],
)
async def test_an_invalid_bookmark_is_refused_before_anything_is_written(
    test_db_session, clean_tables, bookmarks
):
    admin = await _admin(test_db_session)
    dataset_id = await _dataset(test_db_session, admin.id)

    with pytest.raises(ValidationError):
        await _apply(test_db_session, admin, _publish(dataset_id, bookmarks=bookmarks))

    mine = select(func.count()).select_from(Map).where(Map.manifest_key == _KEY)
    assert await test_db_session.scalar(mine) == 0


async def test_a_publish_that_wrote_no_bookmarks_doesnt_clear_a_bookmarks_edit(
    client, test_db_session, admin_auth_header, clean_tables
):
    admin = await _admin(test_db_session)
    dataset_id = await _dataset(test_db_session, admin.id)
    [created] = (await _apply(test_db_session, admin, _publish(dataset_id))).maps
    await _builder_save(
        client,
        admin_auth_header,
        test_db_session,
        created.map_id,
        bookmarks=_BUILDERS,
    )
    await _apply(test_db_session, admin, _publish(dataset_id))

    [result] = (
        await _apply(test_db_session, admin, _publish(dataset_id, bookmarks=[_PARK]))
    ).maps

    assert result.styling == "kept"
    assert _names(await _map_row(test_db_session, created.map_id)) == ["Mine"]
