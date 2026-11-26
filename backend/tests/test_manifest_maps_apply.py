"""Manifest version 2 maps outside a dry run: create and update by key.

Requirements: the docker database must be running with migrations applied.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import event, func, select, text, update
from sqlalchemy.engine import Engine

from app.modules.catalog.datasets.domain.models import Dataset, Record
from app.modules.catalog.maps import manifest_apply
from app.modules.catalog.maps.manifest_columns import (
    named_columns,
    rename_layer_columns,
)
from app.modules.catalog.maps.models import Map, MapEditHistoryEvent, MapLayer
from app.modules.catalog.maps.schemas import MapLayerInput
from app.modules.embed_tokens.models import EmbedToken
from app.modules.embed_tokens.service import create_embed_token
from app.platform.jobs.models import IngestJob
from app.platform.request_credential import ApiKeyCredential, record_api_key
from app.processing.ingest.manifest_schemas import ManifestApplyRequest
from app.processing.ingest.manifest_service import apply_manifest
from tests.factories import create_dataset
from tests.test_manifest_maps_dry_run import (
    _READS,
    _COLUMNS,
    _admin,
    _body,
    _codes,
    _http_request,
    _layer,
    _local_dataset_entry,
    _person,
    _published_under,
    _stage_fixture,
)

from tests.test_manifest_maps_dry_run import _map as _new_map

pytestmark = pytest.mark.anyio


def _map(key: str = "qgis-map-parks", *layers: dict, **fields) -> dict:
    """A map entry that replaces styling unless it says otherwise."""
    return _new_map(key, *layers, **{"styling": "replace", **fields})


_CATEGORIES = [
    {"value": "city", "label": "City park", "color": "#4daf4a"},
    {"value": "state", "label": "State park", "color": "#377eb8"},
]
_PARKS = {
    "style_config": {
        "mode": "categorical",
        "column": "PARK_TYPE",
        "categories": _CATEGORIES,
    },
    "paint": {
        "fill-color": [
            "match",
            ["get", "PARK_TYPE"],
            "city",
            "#4daf4a",
            "state",
            "#377eb8",
            "#cccccc",
        ]
    },
    "filter": ["==", "PARK_TYPE", "city"],
    "label_config": {"column": "PARK_NAME", "fontSize": 12},
    "popup_config": {"enabled": True, "visible_fields": ["PARK_NAME"]},
    "min_zoom": 8,
}


async def _dataset(session, owner_id, *, visibility="public", **fields) -> uuid.UUID:
    dataset = await create_dataset(
        session,
        created_by=owner_id,
        visibility=visibility,
        column_info=[dict(column) for column in _COLUMNS],
        **fields,
    )
    await session.commit()
    return dataset.id


async def _apply(session, user, *maps, dry_run=False, **fields):
    body = {**_body(*maps, dry_run=dry_run), **fields}
    return await apply_manifest(
        session, ManifestApplyRequest.model_validate(body), user, _http_request()
    )


async def _layers(session, map_id) -> list[MapLayer]:
    rows = await session.execute(
        select(MapLayer)
        .where(MapLayer.map_id == map_id)
        .order_by(MapLayer.sort_order)
        .execution_options(populate_existing=True)
    )
    return list(rows.scalars())


async def _map_row(session, map_id) -> Map:
    return (
        await session.execute(
            select(Map)
            .where(Map.id == map_id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()


async def _history(session, map_id) -> list[MapEditHistoryEvent]:
    rows = await session.execute(
        select(MapEditHistoryEvent)
        .where(MapEditHistoryEvent.map_id == map_id)
        .order_by(MapEditHistoryEvent.created_at)
    )
    return list(rows.scalars())


async def _count(session, model, *keys: str) -> int:
    """Rows of ``model`` on the maps published under ``keys``, so maps other
    tests committed don't count."""
    maps = select(Map.id).where(Map.manifest_key.in_(keys))
    column = Map.id if model is Map else model.map_id
    return await session.scalar(
        select(func.count()).select_from(model).where(column.in_(maps))
    )


def _as_publish_key(session) -> None:
    record_api_key(
        session, ApiKeyCredential(id=uuid.uuid4(), scope="publish", dataset_id=None)
    )


# ---------------------------------------------------------------------------
# Create and update
# ---------------------------------------------------------------------------


async def test_a_new_key_creates_the_map_with_stored_column_names(
    test_db_session, clean_tables
):
    admin = await _admin(test_db_session)
    dataset_id = await _dataset(test_db_session, admin.id)

    response = await _apply(
        test_db_session,
        admin,
        _map(
            "qgis-map-parks",
            _layer("parks", dataset_id=str(dataset_id), **_PARKS),
            _layer("names", dataset_id=str(dataset_id), opacity=0.5),
            description="Parks and trails.",
            view={"center": [-89.65, 39.78], "zoom": 11.2},
            basemap_style="openfreemap-positron",
        ),
    )

    [result] = response.maps
    assert response.accepted is True
    assert (result.action, result.messages, result.visibility, result.styling) == (
        "create",
        [],
        "private",
        "applied",
    )
    map_obj = await _map_row(test_db_session, result.map_id)
    assert (map_obj.manifest_key, map_obj.name, map_obj.description) == (
        "qgis-map-parks",
        "Springfield parks",
        "Parks and trails.",
    )
    assert (map_obj.center_lng, map_obj.center_lat, map_obj.zoom) == (
        -89.65,
        39.78,
        11.2,
    )
    assert (map_obj.created_by, map_obj.basemap_style) == (
        admin.id,
        "openfreemap-positron",
    )
    parks, names = await _layers(test_db_session, result.map_id)
    assert [
        (parks.manifest_key, parks.sort_order),
        (names.manifest_key, names.sort_order),
    ] == [
        ("parks", 0),
        ("names", 1),
    ]
    assert (parks.layer_type, names.opacity) == ("vector_geolens", 0.5)
    assert parks.style_config["column"] == "park_type"
    assert parks.paint["fill-color"][1] == ["get", "park_type"]
    assert parks.filter == ["==", ["get", "park_type"], "city"]
    assert parks.label_config["column"] == "park_name"
    assert parks.popup_config["visible_fields"] == ["park_name"]
    assert parks.layout["_minzoom"] == 8


async def test_a_republish_keeps_the_map_and_each_keyed_layer_row(
    test_db_session, clean_tables
):
    admin = await _admin(test_db_session)
    dataset_id = await _dataset(test_db_session, admin.id)
    parks = _layer("parks", dataset_id=str(dataset_id), **_PARKS)
    names = _layer("names", dataset_id=str(dataset_id))
    [created] = (
        await _apply(test_db_session, admin, _map("qgis-map-parks", parks, names))
    ).maps
    ids = {
        layer.manifest_key: layer.id
        for layer in await _layers(test_db_session, created.map_id)
    }

    recoloured = {**parks, "opacity": 0.25, "display_name": "Parks"}
    [updated] = (
        await _apply(
            test_db_session,
            admin,
            _map("qgis-map-parks", names, recoloured, name="Renamed"),
        )
    ).maps

    assert (updated.action, updated.map_id, updated.messages) == (
        "update",
        created.map_id,
        [],
    )
    stored = await _layers(test_db_session, created.map_id)
    assert [(layer.manifest_key, layer.id) for layer in stored] == [
        ("names", ids["names"]),
        ("parks", ids["parks"]),
    ]
    assert (stored[1].opacity, stored[1].display_name) == (0.25, "Parks")
    assert (await _map_row(test_db_session, created.map_id)).name == "Renamed"
    assert await _count(test_db_session, Map, "qgis-map-parks") == 1


async def test_a_republish_adds_new_keys_and_removes_missing_ones(
    test_db_session, clean_tables
):
    admin = await _admin(test_db_session)
    dataset_id = await _dataset(test_db_session, admin.id)
    trails_id = await _dataset(test_db_session, admin.id)
    [created] = (
        await _apply(
            test_db_session,
            admin,
            _map(
                "qgis-map-parks",
                _layer("parks", dataset_id=str(dataset_id)),
                _layer("names", dataset_id=str(dataset_id)),
            ),
        )
    ).maps
    names_id = {
        layer.manifest_key: layer.id
        for layer in await _layers(test_db_session, created.map_id)
    }["names"]

    [updated] = (
        await _apply(
            test_db_session,
            admin,
            _map(
                "qgis-map-parks",
                _layer("names", dataset_id=str(dataset_id)),
                _layer("trails", dataset_id=str(trails_id)),
            ),
        )
    ).maps

    assert updated.action == "update"
    assert [(r.key, r.dataset_id) for r in updated.removed_layers] == [
        ("parks", dataset_id)
    ]
    assert _codes(updated) == [("A059", "info", "parks")]
    stored = await _layers(test_db_session, created.map_id)
    assert [(layer.manifest_key, layer.dataset_id) for layer in stored] == [
        ("names", dataset_id),
        ("trails", trails_id),
    ]
    assert stored[0].id == names_id
    # The dataset of a removed layer stays.
    assert await test_db_session.get(Dataset, dataset_id) is not None


async def test_a_layer_added_in_geolens_keeps_its_slot_and_styling(
    test_db_session, clean_tables
):
    admin = await _admin(test_db_session)
    dataset_id = await _dataset(test_db_session, admin.id)
    builder_dataset = await _dataset(test_db_session, admin.id)
    parks = _layer("parks", dataset_id=str(dataset_id))
    names = _layer("names", dataset_id=str(dataset_id))
    [created] = (
        await _apply(test_db_session, admin, _map("qgis-map-parks", parks, names))
    ).maps
    # As the builder adds a layer between the two.
    await test_db_session.execute(
        update(MapLayer)
        .where(MapLayer.map_id == created.map_id, MapLayer.manifest_key == "names")
        .values(sort_order=2)
    )
    added = MapLayer(
        map_id=created.map_id,
        dataset_id=builder_dataset,
        sort_order=1,
        paint={"fill-color": "#123456"},
        layout={},
        display_name="Added in GeoLens",
    )
    test_db_session.add(added)
    await test_db_session.commit()
    added_id = added.id

    [updated] = (
        await _apply(
            test_db_session,
            admin,
            _map(
                "qgis-map-parks",
                names,
                parks,
                _layer("trails", dataset_id=str(dataset_id)),
            ),
        )
    ).maps

    assert (updated.action, updated.messages) == ("update", [])
    stored = await _layers(test_db_session, created.map_id)
    assert [(layer.manifest_key, layer.sort_order) for layer in stored] == [
        ("names", 0),
        (None, 1),
        ("parks", 2),
        ("trails", 3),
    ]
    kept = stored[1]
    assert (kept.id, kept.paint, kept.display_name) == (
        added_id,
        {"fill-color": "#123456"},
        "Added in GeoLens",
    )


async def test_the_api_publishes_maps_outside_a_dry_run(
    client, test_db_session, editor_auth_header, clean_tables
):
    me = await client.get("/auth/me", headers=editor_auth_header)
    dataset_id = await _dataset(test_db_session, uuid.UUID(me.json()["id"]))

    response = await client.post(
        "/ingest/manifest/apply",
        json=_body(
            _map("qgis-map-api", _layer(dataset_id=str(dataset_id))), dry_run=False
        ),
        headers=editor_auth_header,
    )

    assert response.status_code == 200, response.text
    [result] = response.json()["maps"]
    assert (result["action"], result["visibility"], result["styling"]) == (
        "create",
        "private",
        "applied",
    )
    map_obj = await _map_row(test_db_session, uuid.UUID(result["map_id"]))
    assert map_obj.manifest_key == "qgis-map-api"


# ---------------------------------------------------------------------------
# Who may write what
# ---------------------------------------------------------------------------


async def test_another_users_key_answers_a050_and_writes_nothing(
    client, test_db_session, admin_auth_header, clean_tables
):
    admin = await _admin(test_db_session)
    editor, _ = await _person(client, test_db_session, admin_auth_header)
    dataset_id = await _dataset(test_db_session, admin.id)
    [created] = (
        await _apply(
            test_db_session,
            admin,
            _map("qgis-map-taken", _layer(dataset_id=str(dataset_id))),
        )
    ).maps

    [result] = (
        await _apply(
            test_db_session,
            editor,
            _map(
                "qgis-map-taken",
                _layer("other", dataset_id=str(dataset_id)),
                name="Hijacked",
            ),
        )
    ).maps

    assert (result.action, result.map_id) == ("error", None)
    assert _codes(result) == [("A050", "error", None)]
    assert (await _map_row(test_db_session, created.map_id)).name == "Springfield parks"
    assert [
        layer.manifest_key for layer in await _layers(test_db_session, created.map_id)
    ] == ["parks"]


async def test_a_caller_without_edit_metadata_gets_a003(
    client, test_db_session, admin_auth_header, clean_tables
):
    admin = await _admin(test_db_session)
    viewer, _ = await _person(client, test_db_session, admin_auth_header, "viewer")
    dataset_id = await _dataset(test_db_session, admin.id)

    [result] = (
        await _apply(
            test_db_session,
            viewer,
            _map("qgis-map-viewer", _layer(dataset_id=str(dataset_id))),
        )
    ).maps

    assert _codes(result) == [("A003", "error", None)]
    assert await _count(test_db_session, Map, "qgis-map-viewer") == 0


class _Inserts:
    def __init__(self) -> None:
        self.maps = 0

    def __call__(self, conn, cursor, statement, *args) -> None:
        if statement.lstrip().upper().startswith("INSERT INTO CATALOG.MAPS "):
            self.maps += 1


async def test_a_layer_on_a_dataset_the_caller_cant_read_writes_no_map_row(
    client, test_db_session, admin_auth_header, clean_tables
):
    admin = await _admin(test_db_session)
    editor, _ = await _person(client, test_db_session, admin_auth_header)
    private_id = await _dataset(test_db_session, admin.id, visibility="private")
    entry = _map("qgis-map-peek", _layer(dataset_id=str(private_id)))
    inserts = _Inserts()

    event.listen(Engine, "before_cursor_execute", inserts)
    try:
        [refused] = (await _apply(test_db_session, editor, entry)).maps
        # Read as readable, as if the dataset narrowed after the check: the
        # write still checks every layer before the map row exists.
        real = manifest_apply._readable_datasets

        async def as_if_readable(session, dataset_ids, user):
            return await real(session, dataset_ids, admin)

        with patch.object(manifest_apply, "_readable_datasets", as_if_readable):
            [late] = (await _apply(test_db_session, editor, entry)).maps
    finally:
        event.remove(Engine, "before_cursor_execute", inserts)

    assert _codes(refused) == [("A052", "error", "parks")]
    assert (late.action, _codes(late)) == ("error", [("A099", "error", None)])
    assert "Cannot access" in late.messages[0].message
    assert inserts.maps == 0
    assert await _count(test_db_session, Map, "qgis-map-peek") == 0


async def test_a_dataset_a_map_cant_show_is_refused_and_a_table_is_noted(
    test_db_session, clean_tables
):
    admin = await _admin(test_db_session)
    tileset = await _dataset(
        test_db_session, admin.id, record_type="tiles3d_dataset", geometry_type=None
    )
    table = await _dataset(
        test_db_session, admin.id, record_type="table", geometry_type=None
    )
    entry = _map(
        "qgis-map-kinds",
        _layer("tileset", dataset_id=str(tileset)),
        _layer("table", dataset_id=str(table)),
    )

    [checked] = (await _apply(test_db_session, admin, entry, dry_run=True)).maps
    [applied] = (await _apply(test_db_session, admin, entry)).maps

    for result in (checked, applied):
        assert _codes(result) == [
            ("A099", "error", "tileset"),
            ("A032", "info", "table"),
        ]
    assert await _count(test_db_session, Map, "qgis-map-kinds", "qgis-map-table") == 0
    [table_only] = (
        await _apply(
            test_db_session,
            admin,
            _map("qgis-map-table", _layer("table", dataset_id=str(table))),
        )
    ).maps
    assert (table_only.action, _codes(table_only)) == (
        "create",
        [("A032", "info", "table")],
    )


# ---------------------------------------------------------------------------
# Visibility
# ---------------------------------------------------------------------------


async def test_a_public_map_over_a_private_dataset_is_a020_in_both_runs(
    client, test_db_session, admin_auth_header, clean_tables
):
    editor, _ = await _person(client, test_db_session, admin_auth_header)
    private_id = await _dataset(test_db_session, editor.id, visibility="private")
    entry = _map(
        "qgis-map-open", _layer(dataset_id=str(private_id)), visibility="public"
    )

    [checked] = (await _apply(test_db_session, editor, entry, dry_run=True)).maps
    [refused] = (await _apply(test_db_session, editor, entry)).maps
    [fell_back] = (
        await _apply(test_db_session, editor, entry, public_fallback="internal")
    ).maps

    for result in (checked, refused):
        assert (result.action, _codes(result)) == ("error", [("A020", "error", None)])
        assert "datasets that aren't public" in result.messages[0].message
    assert (fell_back.action, fell_back.visibility) == ("create", "internal")
    # The organization reads the map, and not the private layer's dataset.
    assert _codes(fell_back) == [
        ("A020", "warning", None),
        ("A056", "warning", "parks"),
    ]
    assert (await _map_row(test_db_session, fell_back.map_id)).visibility == "internal"
    assert await _count(test_db_session, Map, "qgis-map-open") == 1


async def test_a_dry_run_judges_the_requests_own_datasets_as_they_publish(
    test_db_session, clean_tables
):
    _stage_fixture()
    admin = await _admin(test_db_session)
    public_map = _map(
        "qgis-map-own", _layer(dataset_key="qgis-parks"), visibility="public"
    )

    async def dry_run(visibility):
        entry = {**_local_dataset_entry("qgis-parks"), "visibility": visibility}
        body = {**_body(public_map, datasets=[entry])}
        response = await apply_manifest(
            test_db_session,
            ManifestApplyRequest.model_validate(body),
            admin,
            _http_request(),
        )
        return response.maps[0]

    public = await dry_run("public")
    private = await dry_run("private")

    assert (public.action, public.messages, public.visibility) == (
        "create",
        [],
        "public",
    )
    assert _codes(private) == [("A020", "error", None)]


async def test_public_is_restricted_to_admins_when_the_server_says_so(
    client, test_db_session, admin_auth_header, clean_tables, monkeypatch
):
    import app.core.persistent_config as pc

    class _On:
        async def get(self, _db):
            return True

        get_uncached = get

    monkeypatch.setattr(pc, "RESTRICT_PUBLIC_VISIBILITY", _On())
    admin = await _admin(test_db_session)
    editor, _ = await _person(client, test_db_session, admin_auth_header)
    dataset_id = await _dataset(test_db_session, admin.id)

    [refused] = (
        await _apply(
            test_db_session,
            editor,
            _map("qgis-map-e", _layer(dataset_id=str(dataset_id)), visibility="public"),
        )
    ).maps
    [allowed] = (
        await _apply(
            test_db_session,
            admin,
            _map("qgis-map-a", _layer(dataset_id=str(dataset_id)), visibility="public"),
        )
    ).maps

    assert _codes(refused) == [("A020", "error", None)]
    assert "restricted on this server" in refused.messages[0].message
    assert (allowed.action, allowed.visibility) == ("create", "public")


async def test_a_publish_key_never_makes_a_map_public_or_wider(
    client, test_db_session, admin_auth_header, clean_tables
):
    editor, _ = await _person(client, test_db_session, admin_auth_header)
    dataset_id = await _dataset(test_db_session, editor.id)
    _as_publish_key(test_db_session)
    layer = _layer(dataset_id=str(dataset_id))

    [public] = (
        await _apply(
            test_db_session, editor, _map("k-public", layer, visibility="public")
        )
    ).maps
    [fell_back] = (
        await _apply(
            test_db_session,
            editor,
            _map("k-public", layer, visibility="public"),
            public_fallback="internal",
        )
    ).maps
    [private] = (await _apply(test_db_session, editor, _map("k-private", layer))).maps
    [widened] = (
        await _apply(
            test_db_session, editor, _map("k-private", layer, visibility="internal")
        )
    ).maps

    assert _codes(public) == [("A020", "error", None)]
    assert "publish key" in public.messages[0].message
    assert (fell_back.action, fell_back.visibility) == ("create", "internal")
    assert _codes(fell_back) == [("A020", "warning", None)]
    assert (private.action, private.visibility) == ("create", "private")
    # The widening is left out and the map is still published, at its level.
    assert (widened.action, widened.visibility) == ("update", "private")
    assert _codes(widened) == [("A056", "warning", None)]
    assert "can't share the map" in widened.messages[0].message
    assert (await _map_row(test_db_session, private.map_id)).visibility == "private"


async def test_a_republish_that_omits_visibility_keeps_a_public_maps_share_link(
    client, test_db_session, admin_auth_header, clean_tables
):
    admin = await _admin(test_db_session)
    dataset_id = await _dataset(test_db_session, admin.id)
    entry = _map("qgis-map-shared", _layer(dataset_id=str(dataset_id), **_PARKS))
    [created] = (await _apply(test_db_session, admin, entry)).maps
    # Shared in GeoLens: made public, with a share link.
    response = await client.put(
        f"/maps/{created.map_id}",
        json={"visibility": "public"},
        headers=admin_auth_header,
    )
    assert response.status_code == 200, response.text
    share = await client.post(
        f"/maps/{created.map_id}/share", json={}, headers=admin_auth_header
    )
    assert share.status_code in (200, 201), share.text
    token = share.json()["token"]
    _as_publish_key(test_db_session)

    [republished] = (await _apply(test_db_session, admin, entry)).maps

    assert (republished.action, republished.visibility) == ("update", "public")
    shared = await client.get(f"/maps/shared/{token}")
    assert shared.status_code == 200, shared.text


async def test_dropping_a_layers_dataset_revokes_the_maps_embed_tokens(
    test_db_session, clean_tables
):
    admin = await _admin(test_db_session)
    parks_id = await _dataset(test_db_session, admin.id)
    trails_id = await _dataset(test_db_session, admin.id)
    [created] = (
        await _apply(
            test_db_session,
            admin,
            _map(
                "qgis-map-embed",
                _layer("parks", dataset_id=str(parks_id)),
                _layer("trails", dataset_id=str(trails_id)),
                visibility="public",
            ),
        )
    ).maps
    token, _ = await create_embed_token(test_db_session, created.map_id, admin.id)
    await test_db_session.commit()
    token_id = token.id

    await _apply(
        test_db_session,
        admin,
        _map("qgis-map-embed", _layer("parks", dataset_id=str(parks_id))),
    )

    active = await test_db_session.scalar(
        select(EmbedToken.is_active)
        .where(EmbedToken.id == token_id)
        .execution_options(populate_existing=True)
    )
    assert active is False


# ---------------------------------------------------------------------------
# History, transactions and the lock
# ---------------------------------------------------------------------------


async def test_each_apply_records_one_manifest_publish_event(
    test_db_session, clean_tables
):
    admin = await _admin(test_db_session)
    dataset_id = await _dataset(test_db_session, admin.id)
    entry = _map(
        "qgis-map-history",
        _layer("parks", dataset_id=str(dataset_id)),
        _layer("names", dataset_id=str(dataset_id)),
    )
    [created] = (await _apply(test_db_session, admin, entry)).maps
    await _apply(test_db_session, admin, {**entry, "visibility": "internal"})

    events = await _history(test_db_session, created.map_id)

    assert [e.action for e in events] == ["manifest.publish", "manifest.publish"]
    assert events[0].details.pop("notes_digest")
    assert events[0].details == {
        "client_id": "geolens-qgis",
        "client_version": "0.2.0",
        "styling_applied": True,
        "view_written": False,
        "basemap_written": False,
        "bookmarks_written": False,
        "layer_keys": ["parks", "names"],
    }
    assert events[1].details["visibility"] == {
        "previous": "private",
        "current": "internal",
    }


async def test_one_maps_failed_write_leaves_the_other_maps_written(
    test_db_session, clean_tables
):
    admin = await _admin(test_db_session)
    dataset_id = await _dataset(test_db_session, admin.id)
    real = manifest_apply.record_map_history_event

    async def failing_for_b(session, **kwargs):
        if kwargs["target_name"] == "B":
            raise RuntimeError("boom")
        return await real(session, **kwargs)

    with patch.object(manifest_apply, "record_map_history_event", failing_for_b):
        failed, written = (
            await _apply(
                test_db_session,
                admin,
                _map("qgis-map-b", _layer(dataset_id=str(dataset_id)), name="B"),
                _map("qgis-map-a", _layer(dataset_id=str(dataset_id)), name="A"),
            )
        ).maps

    assert written.action == "create"
    assert (failed.action, _codes(failed)) == ("error", [("A099", "error", None)])
    names = (await test_db_session.scalars(select(Map.name))).all()
    assert names == ["A"]
    assert await _count(test_db_session, MapLayer, "qgis-map-a", "qgis-map-b") == 1


async def test_applies_of_one_key_wait_for_its_lock(test_db_session, clean_tables):
    import app.core.db as db_module

    admin = await _admin(test_db_session)
    dataset_id = await _dataset(test_db_session, admin.id)
    waiting_query = text(
        "SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND NOT granted "
        "AND database = (SELECT oid FROM pg_database "
        "WHERE datname = current_database())"
    )

    async with db_module.async_session() as holder:
        await holder.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": "manifest_map:qgis-map-race"},
        )
        apply = asyncio.create_task(
            _apply(
                test_db_session,
                admin,
                _map("qgis-map-race", _layer(dataset_id=str(dataset_id))),
            )
        )
        waiting = 0
        for _ in range(200):
            waiting = await holder.scalar(waiting_query)
            if waiting or apply.done():
                break
            await asyncio.sleep(0.05)
        assert waiting == 1
        assert not apply.done()
        # The holder publishes the key meanwhile; its commit ends the lock.
        holder.add(Map(name="First", created_by=admin.id, manifest_key="qgis-map-race"))
        await holder.commit()

    [result] = (await apply).maps
    assert result.action == "update"
    assert await _count(test_db_session, Map, "qgis-map-race") == 1


# ---------------------------------------------------------------------------
# Datasets and maps in one request
# ---------------------------------------------------------------------------


async def test_a_layer_on_a_dataset_the_request_only_queued_answers_a052(
    test_db_session, clean_tables
):
    _stage_fixture()
    admin = await _admin(test_db_session)
    dataset_id = await _dataset(test_db_session, admin.id)
    await _published_under(test_db_session, admin.id, "qgis-old", dataset_id)
    body = _body(
        _map("qgis-map-new", _layer(dataset_key="qgis-new")),
        _map("qgis-map-old", _layer(dataset_key="qgis-old")),
        dry_run=False,
        datasets=[_local_dataset_entry("qgis-new")],
    )

    with patch(
        "app.processing.ingest.manifest_service.queue_ingest_job", new=AsyncMock()
    ):
        response = await apply_manifest(
            test_db_session,
            ManifestApplyRequest.model_validate(body),
            admin,
            _http_request(),
        )

    [dataset] = response.results
    assert dataset.action == "create"
    new, old = response.maps
    assert (new.action, _codes(new)) == ("error", [("A052", "error", "parks")])
    assert old.action == "create"
    assert (await test_db_session.scalars(select(Map.manifest_key))).all() == [
        "qgis-map-old"
    ]


# ---------------------------------------------------------------------------
# Column names
# ---------------------------------------------------------------------------


def _stored(name: str) -> str:
    return f"stored_{name.lower()}"


_FORMS = {
    **_READS,
    "categorical": _PARKS,
    "legacy_filter": {"filter": ["!in", "{c}", "a", "b"]},
    "property_function": {"paint": {"fill-color": {"property": "{c}", "stops": []}}},
    "text_field_token": {"layout": {"text-field": "{{c}} park"}},
    "popup_title": {"popup_config": {"enabled": True, "expression": "{{c}}"}},
    "heatmap_weight": {"style_config": {"builder": {"heatmapWeightColumn": "{c}"}}},
    "saved_heatmap_paint": {
        "style_config": {"heatmapPaint": {"heatmap-weight": ["get", "{c}"]}}
    },
    "saved_circle_paint": {
        "style_config": {
            "savedCirclePaint": {"circle-radius": {"property": "{c}", "stops": []}}
        }
    },
    "builder_saved_opacity": {
        "style_config": {"builder": {"fillOpacitySaved": ["get", "{c}"]}}
    },
    "builder_saved_outline_width": {
        "style_config": {"builder": {"outlineWidthSaved": ["get", "{c}"]}}
    },
}


@pytest.mark.parametrize("form", sorted(_FORMS))
def test_every_column_a_check_reads_is_the_column_an_apply_rewrites(form):
    fields = {
        key: value
        for key, value in json.loads(
            json.dumps(_FORMS[form]).replace("{c}", "MISSING")
        ).items()
        if key not in ("min_zoom",)
    }
    layer = MapLayerInput(dataset_id=uuid.uuid4(), **fields)

    renamed = rename_layer_columns(layer, _stored)

    named = named_columns(layer)
    assert "MISSING" in named or form == "categorical"
    assert named_columns(renamed) == {_stored(name) for name in named}
    # Nothing but the names changed: the labels and values beside them stay.
    restored = renamed.model_dump_json()
    for name in named:
        restored = restored.replace(_stored(name), name)
    assert restored == layer.model_dump_json()


def test_a_rename_leaves_the_layer_it_was_given_alone():
    layer = MapLayerInput(
        dataset_id=uuid.uuid4(), **{k: v for k, v in _PARKS.items() if k != "min_zoom"}
    )
    before = layer.model_dump_json()

    rename_layer_columns(layer, _stored)

    assert layer.model_dump_json() == before


async def test_a_categorical_layer_renders_its_colours_in_the_style_export(
    client, test_db_session, admin_auth_header, clean_tables
):
    admin = await _admin(test_db_session)
    dataset_id = await _dataset(test_db_session, admin.id)
    [created] = (
        await _apply(
            test_db_session,
            admin,
            _map("qgis-map-style", _layer(dataset_id=str(dataset_id), **_PARKS)),
        )
    ).maps

    response = await client.get(
        f"/maps/{created.map_id}/style.json", headers=admin_auth_header
    )

    assert response.status_code == 200, response.text
    painted = json.dumps(response.json()["layers"])
    assert '["get", "park_type"]' in painted
    assert "#4daf4a" in painted and "#377eb8" in painted
    assert "PARK_TYPE" not in painted


async def test_record_visibility_is_read_from_the_record(test_db_session, clean_tables):
    """The judgement reads the dataset's record, as the map read path does."""
    admin = await _admin(test_db_session)
    dataset_id = await _dataset(test_db_session, admin.id)
    record_id = select(Dataset.record_id).where(Dataset.id == dataset_id)
    await test_db_session.execute(
        update(Record)
        .where(Record.id == record_id.scalar_subquery())
        .values(record_status="draft")
    )
    await test_db_session.commit()

    [result] = (
        await _apply(
            test_db_session,
            admin,
            _map(
                "qgis-map-draft",
                _layer(dataset_id=str(dataset_id)),
                visibility="public",
            ),
            dry_run=True,
        )
    ).maps

    assert _codes(result) == [("A020", "error", None)]


# ---------------------------------------------------------------------------
# Round 2: the map row lock, styling modes, dataset readiness, groups, caps
# ---------------------------------------------------------------------------


@contextlib.asynccontextmanager
async def _racing_write(work):
    """Run ``work`` in a second session right before the apply's write.

    The write goes ahead once ``work`` has committed or waits on a lock the
    apply holds, and the second session finishes after the block. Both extra
    sessions connect first: a race that waited for a connection would prove
    nothing.
    """
    import app.core.db as db_module

    real = manifest_apply._write_map
    tasks: list[asyncio.Task] = []
    async with db_module.async_session() as other, db_module.async_session() as probe:
        pid = await other.scalar(text("SELECT pg_backend_pid()"))
        await probe.execute(text("SELECT 1"))
        waiting_query = text(
            "SELECT count(*) FROM pg_locks WHERE pid = :pid AND NOT granted"
        )

        async def racing(session, entry, request, plan):
            async def run():
                await work(other)
                await other.commit()

            task = asyncio.create_task(run())
            tasks.append(task)
            for _ in range(200):
                if task.done() or await probe.scalar(waiting_query, {"pid": pid}):
                    break
                await asyncio.sleep(0.05)
            else:
                raise AssertionError("the second session neither finished nor waited")
            return await real(session, entry, request, plan)

        with patch.object(manifest_apply, "_write_map", racing):
            yield
        await asyncio.gather(*tasks)


async def _lock_map_row(session, map_id) -> None:
    """What a builder save does first: take the map's row lock."""
    await session.execute(
        text("SELECT id FROM catalog.maps WHERE id = :id FOR NO KEY UPDATE"),
        {"id": map_id},
    )


async def test_a_builder_save_during_a_republish_keeps_its_layer(
    test_db_session, clean_tables
):
    admin = await _admin(test_db_session)
    dataset_id = await _dataset(test_db_session, admin.id)
    entry = _map("qgis-map-race", _layer("parks", dataset_id=str(dataset_id)))
    [created] = (await _apply(test_db_session, admin, entry)).maps

    async def builder_adds_a_layer(other):
        await _lock_map_row(other, created.map_id)
        other.add(
            MapLayer(
                map_id=created.map_id,
                dataset_id=dataset_id,
                sort_order=1,
                paint={"fill-color": "#abcdef"},
                layout={},
            )
        )

    async with _racing_write(builder_adds_a_layer):
        [result] = (await _apply(test_db_session, admin, entry)).maps

    assert result.action == "update"
    stored = await _layers(test_db_session, created.map_id)
    assert sorted((layer.manifest_key or "") for layer in stored) == ["", "parks"]


async def test_an_owners_private_during_a_key_republish_is_not_widened(
    client, test_db_session, admin_auth_header, clean_tables
):
    editor, _ = await _person(client, test_db_session, admin_auth_header)
    dataset_id = await _dataset(test_db_session, editor.id)
    layer = _layer(dataset_id=str(dataset_id))
    [created] = (
        await _apply(
            test_db_session, editor, _map("qgis-map-vis", layer, visibility="public")
        )
    ).maps
    assert created.visibility == "public"
    _as_publish_key(test_db_session)

    async def owner_makes_it_private(other):
        await _lock_map_row(other, created.map_id)
        await other.execute(
            update(Map).where(Map.id == created.map_id).values(visibility="private")
        )

    async with _racing_write(owner_makes_it_private):
        await _apply(
            test_db_session, editor, _map("qgis-map-vis", layer, visibility="internal")
        )

    assert (await _map_row(test_db_session, created.map_id)).visibility == "private"


async def test_a_new_map_takes_the_default_styling_mode(test_db_session, clean_tables):
    admin = await _admin(test_db_session)
    dataset_id = await _dataset(test_db_session, admin.id)

    [created] = (
        await _apply(
            test_db_session,
            admin,
            _new_map("qgis-map-default", _layer(dataset_id=str(dataset_id))),
        )
    ).maps

    assert (created.action, created.styling) == ("create", "applied")


def _maps_only(*maps, datasets=(), dry_run=False) -> ManifestApplyRequest:
    return ManifestApplyRequest.model_validate(
        _body(*maps, dry_run=dry_run, datasets=list(datasets))
    )


def _reference(form: str, dataset_id) -> dict:
    return (
        _layer(dataset_key="qgis-parks")
        if form == "key"
        else _layer(dataset_id=str(dataset_id))
    )


@pytest.mark.parametrize("form", ["key", "id"])
@pytest.mark.parametrize(
    ("action", "written"),
    [("create", False), ("update", False), ("blocked", False), ("skip", True)],
)
async def test_an_apply_writes_a_layer_only_on_a_settled_dataset(
    test_db_session, clean_tables, action, written, form
):
    from app.processing.ingest.manifest_maps import run_manifest_maps
    from app.processing.ingest.manifest_schemas import ManifestApplyEntryResult

    if (action, form) == ("create", "id"):
        pytest.skip("a create has no dataset to name by id")
    admin = await _admin(test_db_session)
    dataset_id = await _dataset(test_db_session, admin.id)
    await _published_under(test_db_session, admin.id, "qgis-parks", dataset_id)
    request = _maps_only(
        _map("qgis-map-a", _reference(form, dataset_id)),
        datasets=[_local_dataset_entry("qgis-parks")],
    )
    results = [
        ManifestApplyEntryResult(
            dataset_key="qgis-parks",
            action=action,
            message="m",
            dataset_id=None if action == "create" else dataset_id,
        )
    ]

    [result] = await run_manifest_maps(test_db_session, request, admin, results)

    if written:
        assert (result.action, result.messages) == ("create", [])
    else:
        assert _codes(result) == [("A052", "error", "parks")]
    assert await _count(test_db_session, Map, "qgis-map-a") == int(written)


@pytest.mark.parametrize("form", ["key", "id"])
async def test_a_public_map_over_a_dataset_the_request_narrows_is_not_written(
    test_db_session, clean_tables, form
):
    from app.processing.ingest.manifest_maps import run_manifest_maps
    from app.processing.ingest.manifest_schemas import ManifestApplyEntryResult

    admin = await _admin(test_db_session)
    dataset_id = await _dataset(test_db_session, admin.id)
    await _published_under(test_db_session, admin.id, "qgis-parks", dataset_id)
    request = _maps_only(
        _map("qgis-map-a", _reference(form, dataset_id), visibility="public"),
        datasets=[{**_local_dataset_entry("qgis-parks"), "visibility": "private"}],
    )
    results = [
        ManifestApplyEntryResult(
            dataset_key="qgis-parks",
            action="update",
            message="m",
            dataset_id=dataset_id,
        )
    ]

    [result] = await run_manifest_maps(test_db_session, request, admin, results)

    assert _codes(result) == [("A052", "error", "parks")]
    assert await _count(test_db_session, Map, "qgis-map-a") == 0


@pytest.mark.parametrize("form", ["key", "id"])
@pytest.mark.parametrize("dry_run", [True, False])
async def test_a_key_with_a_job_in_flight_answers_a052(
    test_db_session, clean_tables, dry_run, form
):
    admin = await _admin(test_db_session)
    dataset_id = await _dataset(test_db_session, admin.id)
    await _published_under(test_db_session, admin.id, "qgis-parks", dataset_id)
    # By key, a job that names no dataset yet still holds the key.
    await _published_under(
        test_db_session,
        admin.id,
        "qgis-parks",
        dataset_id if form == "id" else None,
        status="running",
    )

    [result] = (
        await _apply(
            test_db_session,
            admin,
            _map("qgis-map-a", _reference(form, dataset_id)),
            dry_run=dry_run,
        )
    ).maps

    assert _codes(result) == [("A052", "error", "parks")]
    assert await _count(test_db_session, Map, "qgis-map-a") == 0


async def test_a_dry_run_and_an_apply_report_the_visibility_groups_leave(
    test_db_session, clean_tables
):
    from app.modules.auth.models import Group
    from app.modules.catalog.maps.models import MapGroupGrant

    admin = await _admin(test_db_session)
    dataset_id = await _dataset(test_db_session, admin.id)
    entry = _map("qgis-map-groups", _layer(dataset_id=str(dataset_id)))
    [created] = (await _apply(test_db_session, admin, entry)).maps
    group = Group(name=f"gl-23b-{uuid.uuid4().hex[:8]}")
    test_db_session.add(group)
    await test_db_session.flush()
    test_db_session.add(MapGroupGrant(map_id=created.map_id, group_id=group.id))
    await test_db_session.execute(
        update(Map).where(Map.id == created.map_id).values(visibility="restricted")
    )
    await test_db_session.commit()
    private = {**entry, "visibility": "private"}

    [checked] = (await _apply(test_db_session, admin, private, dry_run=True)).maps
    [applied] = (await _apply(test_db_session, admin, private)).maps

    assert (checked.visibility, applied.visibility) == ("restricted", "restricted")


async def test_a_saved_heatmap_paint_is_written_with_stored_names(
    test_db_session, clean_tables
):
    admin = await _admin(test_db_session)
    dataset_id = await _dataset(test_db_session, admin.id)
    saved = {"heatmapPaint": {"heatmap-weight": ["get", "PARK_TYPE"]}}

    [created] = (
        await _apply(
            test_db_session,
            admin,
            _map(
                "qgis-map-heat",
                _layer(dataset_id=str(dataset_id), style_config=saved),
            ),
        )
    ).maps

    [layer] = await _layers(test_db_session, created.map_id)
    assert layer.style_config["heatmapPaint"] == {
        "heatmap-weight": ["get", "park_type"]
    }


async def test_a_layer_past_the_size_cap_once_renamed_is_refused(
    test_db_session, clean_tables
):
    admin = await _admin(test_db_session)
    long_name = "x" * 60
    dataset = await create_dataset(
        test_db_session,
        created_by=admin.id,
        column_info=[{"name": long_name, "type": "text", "source_name": "A"}],
    )
    await test_db_session.commit()
    # About 18 KB as sent and about 100 KB with the stored name.
    paint = {"circle-radius": ["coalesce", *(["get", "A"] for _ in range(1500)), 1]}

    [result] = (
        await _apply(
            test_db_session,
            admin,
            _map("qgis-map-big", _layer(dataset_id=str(dataset.id), paint=paint)),
        )
    ).maps

    assert (result.action, _codes(result)) == ("error", [("A099", "error", "parks")])
    assert "too large" in result.messages[0].message
    assert await _count(test_db_session, Map, "qgis-map-big") == 0


async def test_a_reupload_in_flight_holds_a_layer_named_by_id(
    test_db_session, clean_tables
):
    """A replacement job names its dataset in its metadata until it lands."""
    admin = await _admin(test_db_session)
    dataset_id = await _dataset(test_db_session, admin.id)
    test_db_session.add(
        IngestJob(
            source_filename="parks.fgb",
            created_by=admin.id,
            status="pending",
            user_metadata={"reupload": True, "dataset_id": str(dataset_id)},
        )
    )
    await test_db_session.commit()

    [result] = (
        await _apply(
            test_db_session,
            admin,
            _map("qgis-map-a", _layer(dataset_id=str(dataset_id))),
        )
    ).maps

    assert _codes(result) == [("A052", "error", "parks")]


@pytest.mark.parametrize("dry_run", [True, False])
async def test_a_completed_skip_is_judged_on_the_dataset_as_it_is(
    test_db_session, clean_tables, dry_run
):
    from app.processing.ingest.manifest_maps import run_manifest_maps
    from app.processing.ingest.manifest_schemas import ManifestApplyEntryResult

    admin = await _admin(test_db_session)
    dataset_id = await _dataset(test_db_session, admin.id)
    await _published_under(test_db_session, admin.id, "qgis-parks", dataset_id)
    # Made private in GeoLens after the last publish, which the unchanged
    # manifest still calls public.
    record_id = select(Dataset.record_id).where(Dataset.id == dataset_id)
    await test_db_session.execute(
        update(Record)
        .where(Record.id == record_id.scalar_subquery())
        .values(visibility="private")
    )
    await test_db_session.commit()
    request = _maps_only(
        _map("qgis-map-a", _layer(dataset_key="qgis-parks"), visibility="public"),
        datasets=[{**_local_dataset_entry("qgis-parks"), "visibility": "public"}],
        dry_run=dry_run,
    )
    results = [
        ManifestApplyEntryResult(
            dataset_key="qgis-parks", action="skip", message="m", dataset_id=dataset_id
        )
    ]

    [result] = await run_manifest_maps(test_db_session, request, admin, results)

    assert _codes(result) == [("A020", "error", None)]
    assert await _count(test_db_session, Map, "qgis-map-a") == 0


async def test_an_apply_refuses_a_symbol_icon_that_isnt_a_name(
    test_db_session, clean_tables
):
    admin = await _admin(test_db_session)
    dataset_id = await _dataset(test_db_session, admin.id)
    symbol = {"iconImage": ["match", ["get", "PARK_TYPE"], "city", "bus", "marker"]}

    [result] = (
        await _apply(
            test_db_session,
            admin,
            _map(
                "qgis-map-icons",
                _layer(dataset_id=str(dataset_id), style_config={"symbol": symbol}),
            ),
        )
    ).maps

    assert _codes(result) == [("A099", "error", "parks")]
    assert await _count(test_db_session, Map, "qgis-map-icons") == 0


@pytest.mark.parametrize("names_dataset", [True, False])
@pytest.mark.parametrize("form", ["key", "id"])
async def test_a_failed_entrys_dataset_supplies_no_layer(
    test_db_session, clean_tables, form, names_dataset
):
    from app.processing.ingest.manifest_maps import run_manifest_maps
    from app.processing.ingest.manifest_schemas import ManifestApplyEntryResult

    admin = await _admin(test_db_session)
    dataset_id = await _dataset(test_db_session, admin.id)
    await _published_under(test_db_session, admin.id, "qgis-parks", dataset_id)
    request = _maps_only(
        _map("qgis-map-a", _reference(form, dataset_id)),
        datasets=[_local_dataset_entry("qgis-parks")],
    )
    results = [
        ManifestApplyEntryResult(
            dataset_key="qgis-parks",
            action="error",
            message="m",
            dataset_id=dataset_id if names_dataset else None,
        )
    ]

    [result] = await run_manifest_maps(test_db_session, request, admin, results)

    assert _codes(result) == [("A052", "error", "parks")]
    assert await _count(test_db_session, Map, "qgis-map-a") == 0


async def test_a_replacement_queued_while_the_apply_waits_answers_a052(
    test_db_session, clean_tables
):
    import app.core.db as db_module

    admin = await _admin(test_db_session)
    dataset_id = await _dataset(test_db_session, admin.id)
    entry = _map("qgis-map-wait", _layer("parks", dataset_id=str(dataset_id)))
    [created] = (await _apply(test_db_session, admin, entry)).maps
    # Backends blocked by the holder: only the apply runs while it holds the
    # map's row lock.
    blocked_query = text(
        "SELECT count(*) FROM pg_stat_activity "
        "WHERE :holder = ANY(pg_blocking_pids(pid))"
    )

    async with (
        db_module.async_session() as holder,
        db_module.async_session() as probe,
    ):
        await probe.execute(text("SELECT 1"))
        holder_pid = await holder.scalar(text("SELECT pg_backend_pid()"))
        await _lock_map_row(holder, created.map_id)
        apply = asyncio.create_task(_apply(test_db_session, admin, entry))
        for _ in range(200):
            await probe.execute(text("SELECT pg_stat_clear_snapshot()"))
            if apply.done():
                raise AssertionError("the apply didn't wait for the map's lock")
            if await probe.scalar(blocked_query, {"holder": holder_pid}):
                break
            await asyncio.sleep(0.05)
        else:
            raise AssertionError("the apply never waited on the holder's lock")
        # A replacement is queued while the apply waits for the map.
        holder.add(
            IngestJob(
                source_filename="parks.fgb",
                created_by=admin.id,
                status="pending",
                user_metadata={"reupload": True, "dataset_id": str(dataset_id)},
            )
        )
        await holder.commit()
        [result] = (await apply).maps

    assert _codes(result) == [("A052", "error", "parks")]


@pytest.mark.parametrize(
    ("now", "planned", "refused"),
    [("private", "public", False), ("public", "private", True)],
)
async def test_a_kept_layer_is_judged_on_what_the_request_publishes(
    test_db_session, clean_tables, now, planned, refused
):
    from app.processing.ingest.manifest_maps import run_manifest_maps
    from app.processing.ingest.manifest_schemas import ManifestApplyEntryResult

    admin = await _admin(test_db_session)
    listed = await _dataset(test_db_session, admin.id)
    changed = await _dataset(test_db_session, admin.id, visibility=now)
    await _published_under(test_db_session, admin.id, "qgis-changed", changed)
    entry = _map("qgis-map-kept", _layer("listed", dataset_id=str(listed)))
    [created] = (await _apply(test_db_session, admin, entry)).maps
    test_db_session.add(
        MapLayer(map_id=created.map_id, dataset_id=changed, sort_order=1)
    )
    await test_db_session.commit()
    request = _maps_only(
        {**entry, "visibility": "public"},
        datasets=[{**_local_dataset_entry("qgis-changed"), "visibility": planned}],
        dry_run=True,
    )
    results = [
        ManifestApplyEntryResult(
            dataset_key="qgis-changed",
            action="update",
            message="m",
            dataset_id=changed,
        )
    ]

    [result] = await run_manifest_maps(test_db_session, request, admin, results)

    # The private map the dry run opens to everyone says so.
    assert _codes(result) == (
        [("A020", "error", None)] if refused else [("A057", "warning", None)]
    )


async def test_a_kept_layer_survives_its_dataset_becoming_readable_mid_apply(
    client, test_db_session, admin_auth_header, clean_tables
):
    admin = await _admin(test_db_session)
    editor, _ = await _person(client, test_db_session, admin_auth_header)
    listed = await _dataset(test_db_session, editor.id)
    hidden = await _dataset(test_db_session, admin.id, visibility="private")
    entry = _map("qgis-map-hidden", _layer("listed", dataset_id=str(listed)))
    [created] = (await _apply(test_db_session, editor, entry)).maps
    # A layer added in GeoLens on a dataset the editor can't read now.
    kept = MapLayer(
        map_id=created.map_id,
        dataset_id=hidden,
        sort_order=1,
        paint={"fill-color": "#123456"},
    )
    test_db_session.add(kept)
    await test_db_session.commit()
    kept_id = kept.id
    record_id = select(Dataset.record_id).where(Dataset.id == hidden)

    async def becomes_readable(other):
        await other.execute(
            update(Record)
            .where(Record.id == record_id.scalar_subquery())
            .values(visibility="public")
        )

    async with _racing_write(becomes_readable):
        [result] = (await _apply(test_db_session, editor, entry)).maps

    assert result.action == "update"
    stored = await _layers(test_db_session, created.map_id)
    survivor = [layer for layer in stored if layer.id == kept_id]
    assert survivor and survivor[0].paint == {"fill-color": "#123456"}


@pytest.mark.parametrize("dry_run", [True, False])
async def test_an_admin_cant_write_another_users_map_through_its_key(
    client, test_db_session, admin_auth_header, clean_tables, dry_run
):
    """Keys are global, so a map key is the owner's, as a dataset key is."""
    admin = await _admin(test_db_session)
    editor, _ = await _person(client, test_db_session, admin_auth_header)
    dataset_id = await _dataset(test_db_session, editor.id)
    entry = _map("qgis-map-editors", _layer(dataset_id=str(dataset_id)))
    [created] = (await _apply(test_db_session, editor, entry)).maps

    [result] = (
        await _apply(
            test_db_session, admin, {**entry, "name": "Taken"}, dry_run=dry_run
        )
    ).maps

    assert (result.action, result.map_id) == ("error", None)
    assert _codes(result) == [("A050", "error", None)]
    assert (await _map_row(test_db_session, created.map_id)).name == (
        "Springfield parks"
    )


async def test_a_dry_run_checks_a_key_in_flight_against_the_dataset_it_names(
    test_db_session, clean_tables
):
    from app.processing.ingest.manifest_maps import run_manifest_maps
    from app.processing.ingest.manifest_schemas import ManifestApplyEntryResult

    admin = await _admin(test_db_session)
    dataset_id = await _dataset(test_db_session, admin.id)
    await _published_under(test_db_session, admin.id, "qgis-parks", dataset_id)
    await _published_under(
        test_db_session, admin.id, "qgis-parks", None, status="running"
    )
    styled = {"style_config": {"mode": "categorical", "column": "MISSING"}}
    request = _maps_only(
        _map("qgis-map-a", _layer(dataset_key="qgis-parks", **styled)),
        datasets=[_local_dataset_entry("qgis-parks")],
        dry_run=True,
    )
    results = [
        ManifestApplyEntryResult(
            dataset_key="qgis-parks", action="skip", message="m", dataset_id=dataset_id
        )
    ]

    [result] = await run_manifest_maps(test_db_session, request, admin, results)

    assert _codes(result) == [("A063", "warning", "parks")]
