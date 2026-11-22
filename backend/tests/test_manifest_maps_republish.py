"""Manifest version 2 maps on republish: the styling policy, notes and thumbnail.

Requirements: the docker database must be running with migrations applied.
"""

from __future__ import annotations

import ast
import hashlib
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import select

from app.modules.catalog.maps import manifest_apply, manifest_republish, service_history
from app.modules.catalog.maps.manifest_republish import (
    NOTES_LIMIT,
    OTHER_HISTORY_ACTIONS,
    STYLING_EDIT_ACTIONS,
    managed_notes,
    styling_applies,
)
from app.modules.catalog.maps.models import Map
from app.modules.catalog.maps.schemas import MapUpdate
from app.modules.catalog.maps.service_update import _as_the_builder_saves, _view_moved
from tests.test_manifest_maps_apply import (
    _PARKS,
    _apply,
    _as_publish_key,
    _dataset,
    _history,
    _layers,
    _map_row,
)
from tests.test_manifest_maps_dry_run import (
    _PNG,
    _admin,
    _codes,
    _layer,
    _person,
)
from tests.test_manifest_maps_dry_run import _map as _entry

pytestmark = pytest.mark.anyio

_STYLING_FIELDS = (
    "paint",
    "layout",
    "style_config",
    "label_config",
    "popup_config",
    "filter",
    "opacity",
    "visible",
    "display_name",
)
_VIEW = {"center": [-89.65, 39.78], "zoom": 11.2}
_LOSS = {
    "items": [{"path": "layers[0].style", "kind": "approximated", "detail": "3 rules"}]
}


def _publish(dataset_id, **fields) -> dict:
    return _entry(
        "qgis-map-parks",
        _layer("parks", dataset_id=str(dataset_id), **_PARKS),
        _layer("names", dataset_id=str(dataset_id)),
        **{"view": _VIEW, "basemap_style": "openfreemap-positron", **fields},
    )


def _snapshot(layers, map_obj) -> dict:
    return {
        "layers": {
            layer.manifest_key: {f: getattr(layer, f) for f in _STYLING_FIELDS}
            for layer in layers
        },
        "map": (
            map_obj.center_lng,
            map_obj.center_lat,
            map_obj.zoom,
            map_obj.basemap_style,
        ),
    }


async def _state(session, map_id) -> dict:
    return _snapshot(await _layers(session, map_id), await _map_row(session, map_id))


async def _edit_paint_in_the_builder(client, headers, session, map_id) -> None:
    [parks, _] = await _layers(session, map_id)
    response = await client.patch(
        f"/maps/{map_id}/layers",
        json={"updated": [{"id": str(parks.id), "paint": {"fill-color": "#ff0000"}}]},
        headers=headers,
    )
    assert response.status_code == 200, response.text


# ---------------------------------------------------------------------------
# The decision
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("mode", "edited", "applies"),
    [
        ("replace", False, True),
        ("replace", True, True),
        ("keep", False, False),
        ("keep", True, False),
        ("replace_if_unedited", False, True),
        ("replace_if_unedited", True, False),
    ],
)
def test_the_mode_and_the_edits_decide(mode, edited, applies):
    assert styling_applies(mode, edited=edited) is applies


def _recorded_history_actions() -> set[str]:
    """Every action a history event is recorded with, read from the source:
    constants passed as ``action=``, and the action strings of the
    functions that build them for a call."""
    app = Path(__file__).parents[1] / "app"
    actions: set[str] = set()
    for path in app.rglob("*.py"):
        if path.name == "manifest_republish.py":
            continue
        source = path.read_text()
        if (
            "record_map_history_event" not in source
            and "_history_actions" not in source
        ):
            continue
        tree = ast.parse(source)
        audit = {
            id(keyword.value)
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and getattr(node.func, "id", getattr(node.func, "attr", None))
            == "AuditEvent"
            for keyword in node.keywords
        }
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and id(node) not in audit
                and node.value.split(".")[0] in ("map", "layer", "manifest")
                and node.value.replace(".", "").replace("_", "").isalpha()
                and node.value.count(".") == 1
            ):
                actions.add(node.value)
    return actions


def test_every_history_action_is_a_styling_edit_or_not():
    """A new history action must be put in one of the two sets."""
    assert STYLING_EDIT_ACTIONS.isdisjoint(OTHER_HISTORY_ACTIONS)
    recorded = _recorded_history_actions()
    assert {"layer.style_update", "layer.reorder", "manifest.publish"} <= recorded
    assert recorded == STYLING_EDIT_ACTIONS | OTHER_HISTORY_ACTIONS


async def test_replace_if_unedited_replaces_an_unedited_map(
    test_db_session, clean_tables
):
    admin = await _admin(test_db_session)
    dataset_id = await _dataset(test_db_session, admin.id)
    await _apply(test_db_session, admin, _publish(dataset_id))

    [result] = (
        await _apply(
            test_db_session,
            admin,
            _publish(dataset_id, view={"center": [0, 0], "zoom": 3}),
        )
    ).maps

    assert (result.action, result.styling, result.messages) == ("update", "applied", [])
    assert (await _map_row(test_db_session, result.map_id)).zoom == 3


async def test_a_builder_edit_keeps_every_styling_field_and_answers_a070(
    client, test_db_session, admin_auth_header, clean_tables
):
    admin = await _admin(test_db_session)
    dataset_id = await _dataset(test_db_session, admin.id)
    [created] = (await _apply(test_db_session, admin, _publish(dataset_id))).maps
    await _edit_paint_in_the_builder(
        client, admin_auth_header, test_db_session, created.map_id
    )
    before = await _state(test_db_session, created.map_id)
    restyled = _entry(
        "qgis-map-parks",
        _layer(
            "parks",
            dataset_id=str(dataset_id),
            paint={"fill-color": "#000000"},
            opacity=0.1,
            visible=False,
            display_name="Renamed",
        ),
        _layer("names", dataset_id=str(dataset_id), filter=["==", "PARK_TYPE", "x"]),
        view={"center": [1, 1], "zoom": 2},
        basemap_style="openfreemap-dark",
        name="New name",
        description="New description",
    )

    [checked] = (await _apply(test_db_session, admin, restyled, dry_run=True)).maps
    [kept] = (await _apply(test_db_session, admin, restyled)).maps

    for result in (checked, kept):
        assert (result.action, result.styling) == ("update", "kept")
        assert _codes(result) == [("A070", "info", None)]
        assert "since the last publish that replaced it" in result.messages[0].message
    assert await _state(test_db_session, created.map_id) == before
    map_obj = await _map_row(test_db_session, created.map_id)
    assert (map_obj.name, map_obj.description) == ("New name", "New description")
    publishes = [
        e
        for e in await _history(test_db_session, created.map_id)
        if e.action == "manifest.publish"
    ]
    assert [e.details["styling_applied"] for e in publishes] == [True, False]


async def test_a_republish_after_a_kept_one_still_keeps(
    client, test_db_session, admin_auth_header, clean_tables
):
    admin = await _admin(test_db_session)
    dataset_id = await _dataset(test_db_session, admin.id)
    [created] = (await _apply(test_db_session, admin, _publish(dataset_id))).maps
    await _edit_paint_in_the_builder(
        client, admin_auth_header, test_db_session, created.map_id
    )
    [first] = (await _apply(test_db_session, admin, _publish(dataset_id))).maps
    before = await _state(test_db_session, created.map_id)

    [second] = (await _apply(test_db_session, admin, _publish(dataset_id))).maps

    assert (first.styling, second.styling) == ("kept", "kept")
    assert await _state(test_db_session, created.map_id) == before


# The basemap appearance the builder sends when the map has none stored.
_BUILDER_BASEMAP_CONFIG = {
    "label_mode": "full",
    "road_visibility": "full",
    "boundary_visibility": "full",
    "building_visibility": True,
    "land_water_tone": "default",
    "relief_contrast": None,
    "opacity": 1,
    "background_color": None,
}
# A view as a desktop GIS computes it, at full double precision.
_DESKTOP_VIEW = {"center": [-89.6543210987654, 39.7812345678912], "zoom": 11.23456789}


def _as_the_builder_reads(value):
    """A stored camera value as the builder reads it back, 6 decimals."""
    return None if value is None else float(f"{value:.6f}")


async def _builder_save(client, headers, session, map_id, **changes) -> None:
    """A metadata save as the builder sends it: every setting, changed or
    not, with the camera it shows and its default basemap appearance."""
    map_obj = await _map_row(session, map_id)
    payload = {
        "name": map_obj.name,
        "description": map_obj.description,
        "notes": map_obj.notes,
        "basemap_style": map_obj.basemap_style,
        "show_basemap_labels": True,
        "basemap_config": map_obj.basemap_config or _BUILDER_BASEMAP_CONFIG,
        "terrain_config": None,
        **{
            field: _as_the_builder_reads(getattr(map_obj, field))
            for field in ("center_lng", "center_lat", "zoom", "bearing", "pitch")
        },
        "plugins": map_obj.plugins,
        "legend_title": None,
        **changes,
    }
    response = await client.put(f"/maps/{map_id}", json=payload, headers=headers)
    assert response.status_code == 200, response.text


@pytest.mark.parametrize(
    ("changes", "styling"),
    [
        ({"zoom": 4}, "kept"),
        # More than the builder's rounding.
        ({"zoom": 11.234578}, "kept"),
        ({"basemap_style": "openfreemap-dark"}, "kept"),
        ({"basemap_config": {**_BUILDER_BASEMAP_CONFIG, "opacity": 0.5}}, "applied"),
        ({"notes": "Mine"}, "applied"),
        ({"description": "Mine", "name": "Renamed in GeoLens"}, "applied"),
        ({}, "applied"),
    ],
)
async def test_a_builder_save_counts_only_when_it_moves_the_view_or_basemap(
    client, test_db_session, admin_auth_header, clean_tables, changes, styling
):
    admin = await _admin(test_db_session)
    dataset_id = await _dataset(test_db_session, admin.id)
    entry = _publish(dataset_id, view=_DESKTOP_VIEW)
    [created] = (await _apply(test_db_session, admin, entry)).maps
    await _builder_save(
        client, admin_auth_header, test_db_session, created.map_id, **changes
    )

    [result] = (await _apply(test_db_session, admin, entry)).maps

    assert result.styling == styling
    assert _codes(result) == ([("A070", "info", None)] if styling == "kept" else [])


_FITTED = {"center_lng": -89.654321, "center_lat": 39.781235, "zoom": 11.234568}


def _camera(map_obj) -> dict:
    return {field: getattr(map_obj, field) for field in _FITTED}


@pytest.mark.parametrize(
    ("sends_view", "styling"), [(False, "applied"), (True, "kept")]
)
async def test_a_camera_saved_on_a_map_without_a_view_counts_when_a_view_is_sent(
    client, test_db_session, admin_auth_header, clean_tables, sends_view, styling
):
    """The builder's first save stores the camera it shows, fitted or chosen.
    A publish without a view leaves it; one with a view would overwrite it."""
    admin = await _admin(test_db_session)
    dataset_id = await _dataset(test_db_session, admin.id)
    entry = _publish(dataset_id, view=None)
    [created] = (await _apply(test_db_session, admin, entry)).maps
    await _builder_save(
        client,
        admin_auth_header,
        test_db_session,
        created.map_id,
        **_FITTED,
        notes="Mine",
    )
    if sends_view:
        entry = _publish(dataset_id)

    [result] = (await _apply(test_db_session, admin, entry)).maps

    assert result.styling == styling
    assert _codes(result) == ([("A070", "info", None)] if sends_view else [])
    assert _camera(await _map_row(test_db_session, created.map_id)) == _FITTED


async def test_a_publish_without_a_view_doesnt_clear_a_camera_edit(
    client, test_db_session, admin_auth_header, clean_tables
):
    admin = await _admin(test_db_session)
    dataset_id = await _dataset(test_db_session, admin.id)
    without_view = _publish(dataset_id, view=None)
    [created] = (await _apply(test_db_session, admin, without_view)).maps
    await _builder_save(
        client, admin_auth_header, test_db_session, created.map_id, **_FITTED
    )

    [first] = (await _apply(test_db_session, admin, without_view)).maps
    [second] = (await _apply(test_db_session, admin, _publish(dataset_id))).maps

    assert first.styling == "applied"
    assert (second.styling, _codes(second)) == ("kept", [("A070", "info", None)])
    assert _camera(await _map_row(test_db_session, created.map_id)) == _FITTED


async def test_a_publish_without_a_basemap_doesnt_clear_a_basemap_edit(
    client, test_db_session, admin_auth_header, clean_tables
):
    admin = await _admin(test_db_session)
    dataset_id = await _dataset(test_db_session, admin.id)
    without_basemap = _publish(dataset_id, basemap_style=None)
    [created] = (await _apply(test_db_session, admin, without_basemap)).maps
    await _builder_save(
        client,
        admin_auth_header,
        test_db_session,
        created.map_id,
        basemap_style="openfreemap-dark",
    )

    [first] = (await _apply(test_db_session, admin, without_basemap)).maps
    after_first = (await _map_row(test_db_session, created.map_id)).basemap_style
    [second] = (await _apply(test_db_session, admin, _publish(dataset_id))).maps

    assert (first.styling, after_first) == ("applied", "openfreemap-dark")
    assert (second.styling, _codes(second)) == ("kept", [("A070", "info", None)])
    stored = await _map_row(test_db_session, created.map_id)
    assert stored.basemap_style == "openfreemap-dark"


async def test_a_replace_that_writes_the_view_sets_its_baseline(
    client, test_db_session, admin_auth_header, clean_tables
):
    admin = await _admin(test_db_session)
    dataset_id = await _dataset(test_db_session, admin.id)
    [created] = (
        await _apply(test_db_session, admin, _publish(dataset_id, view=None))
    ).maps
    await _builder_save(
        client, admin_auth_header, test_db_session, created.map_id, **_FITTED
    )
    await _apply(test_db_session, admin, _publish(dataset_id, styling="replace"))
    await _builder_save(client, admin_auth_header, test_db_session, created.map_id)

    [result] = (await _apply(test_db_session, admin, _publish(dataset_id))).maps

    assert result.styling == "applied"


async def test_each_publish_records_whether_it_wrote_the_view_and_basemap(
    client, test_db_session, admin_auth_header, clean_tables
):
    admin = await _admin(test_db_session)
    dataset_id = await _dataset(test_db_session, admin.id)
    [created] = (await _apply(test_db_session, admin, _publish(dataset_id))).maps
    await _apply(test_db_session, admin, _publish(dataset_id, basemap_style=None))
    await _edit_paint_in_the_builder(
        client, admin_auth_header, test_db_session, created.map_id
    )
    [kept] = (await _apply(test_db_session, admin, _publish(dataset_id))).maps

    assert kept.styling == "kept"
    assert [
        (
            e.details["styling_applied"],
            e.details["view_written"],
            e.details["basemap_written"],
        )
        for e in await _history(test_db_session, created.map_id)
        if e.action == "manifest.publish"
    ] == [(True, True, True), (True, True, False), (False, False, False)]


async def test_a_pan_stays_when_the_publish_sends_no_view(
    client, test_db_session, admin_auth_header, clean_tables
):
    admin = await _admin(test_db_session)
    dataset_id = await _dataset(test_db_session, admin.id)
    [created] = (await _apply(test_db_session, admin, _publish(dataset_id))).maps
    await _builder_save(
        client, admin_auth_header, test_db_session, created.map_id, zoom=4.0
    )

    [result] = (
        await _apply(test_db_session, admin, _publish(dataset_id, view=None))
    ).maps

    assert result.styling == "applied"
    assert (await _map_row(test_db_session, created.map_id)).zoom == 4.0


@pytest.mark.parametrize(
    ("sends_basemap", "styling"), [(False, "applied"), (True, "kept")]
)
async def test_a_basemap_choice_counts_only_when_the_publish_sends_one(
    client, test_db_session, admin_auth_header, clean_tables, sends_basemap, styling
):
    admin = await _admin(test_db_session)
    dataset_id = await _dataset(test_db_session, admin.id)
    [created] = (await _apply(test_db_session, admin, _publish(dataset_id))).maps
    await _builder_save(
        client,
        admin_auth_header,
        test_db_session,
        created.map_id,
        basemap_style="openfreemap-dark",
    )
    entry = _publish(dataset_id, **({} if sends_basemap else {"basemap_style": None}))

    [result] = (await _apply(test_db_session, admin, entry)).maps

    assert result.styling == styling
    stored = await _map_row(test_db_session, created.map_id)
    assert stored.basemap_style == "openfreemap-dark"


# Inputs with Number(v.toFixed(6)) as node computes it.
@pytest.mark.parametrize(
    ("value", "javascript"),
    [
        (0.0078125, "0.007813"),
        (-0.0078125, "-0.007813"),
        (179.9921875, "179.992188"),
        (-179.9921875, "-179.992188"),
        (179.9999995, "180.000000"),
        (-89.0000004999, "-89.000000"),
        (-89.0000005, "-89.000000"),
        (1.5000005, "1.500001"),
        (-0.0000005, "-0.000000"),
    ],
)
def test_camera_values_round_as_the_builders_to_fixed(value, javascript):
    assert _as_the_builder_saves(value) == Decimal(javascript)


def test_view_fields_compare_as_the_builder_saves_them():
    assert not _view_moved("bearing", -180.0, 180.0)
    assert not _view_moved("center_lng", 179.9999995, -180.0)
    assert not _view_moved("zoom", 11.23456789, 11.234568)
    assert _view_moved("center_lng", -89.0000004999, -89.000001)
    assert _view_moved("zoom", None, 3.0)


@pytest.mark.parametrize(
    ("stored", "sent", "styling"),
    [
        # One step at the builder's precision is a pan.
        (-89.0, -89.000001, "kept"),
        (-89.0000004999, -89.000001, "kept"),
        # The stored full-precision value, resent as the builder rounds it, is not.
        (-89.0000004999, -89.0, "applied"),
    ],
)
async def test_a_pan_counts_at_the_builders_precision(
    client, test_db_session, admin_auth_header, clean_tables, stored, sent, styling
):
    admin = await _admin(test_db_session)
    dataset_id = await _dataset(test_db_session, admin.id)
    entry = _publish(dataset_id, view={"center": [stored, 39.78], "zoom": 11.2})
    [created] = (await _apply(test_db_session, admin, entry)).maps
    await _builder_save(
        client, admin_auth_header, test_db_session, created.map_id, center_lng=sent
    )

    [result] = (await _apply(test_db_session, admin, entry)).maps

    assert result.styling == styling


async def test_a_bearing_the_builder_reads_back_a_turn_away_is_no_edit(
    client, test_db_session, admin_auth_header, clean_tables
):
    """MapLibre shows a bearing of -180 as 180."""
    admin = await _admin(test_db_session)
    dataset_id = await _dataset(test_db_session, admin.id)
    entry = _publish(dataset_id, view={**_VIEW, "bearing": -180})
    [created] = (await _apply(test_db_session, admin, entry)).maps
    await _builder_save(
        client, admin_auth_header, test_db_session, created.map_id, bearing=180.0
    )

    [result] = (await _apply(test_db_session, admin, entry)).maps

    assert result.styling == "applied"


class _HostClock(datetime):
    """An API host's clock, ``offset`` off the database's."""

    offset = timedelta(0)

    @classmethod
    def now(cls, tz=None):
        return datetime.now(tz) + cls.offset


def _host_clock_off_by(offset: timedelta):
    clock = type("_Skewed", (_HostClock,), {"offset": offset})
    return patch.object(service_history, "datetime", clock, create=True)


async def test_an_edit_from_a_host_whose_clock_runs_behind_still_counts(
    client, test_db_session, admin_auth_header, clean_tables
):
    admin = await _admin(test_db_session)
    dataset_id = await _dataset(test_db_session, admin.id)
    [created] = (await _apply(test_db_session, admin, _publish(dataset_id))).maps
    with _host_clock_off_by(-timedelta(hours=1)):
        await _edit_paint_in_the_builder(
            client, admin_auth_header, test_db_session, created.map_id
        )

    [result] = (await _apply(test_db_session, admin, _publish(dataset_id))).maps

    assert result.styling == "kept"


async def test_a_replace_after_an_edit_from_a_host_whose_clock_runs_ahead_resets(
    client, test_db_session, admin_auth_header, clean_tables
):
    admin = await _admin(test_db_session)
    dataset_id = await _dataset(test_db_session, admin.id)
    [created] = (await _apply(test_db_session, admin, _publish(dataset_id))).maps
    with _host_clock_off_by(timedelta(hours=1)):
        await _edit_paint_in_the_builder(
            client, admin_auth_header, test_db_session, created.map_id
        )
    await _apply(test_db_session, admin, _publish(dataset_id, styling="replace"))

    [result] = (await _apply(test_db_session, admin, _publish(dataset_id))).maps

    assert result.styling == "applied"


async def _move_event(session, map_id, action, by: timedelta) -> None:
    """Shift the map's newest ``action`` event, as a row an API host's clock
    stamped."""
    from sqlalchemy import update

    from app.modules.catalog.maps.models import MapEditHistoryEvent

    [newest, *_] = [
        e for e in reversed(await _history(session, map_id)) if e.action == action
    ]
    await session.execute(
        update(MapEditHistoryEvent)
        .where(MapEditHistoryEvent.id == newest.id)
        .values(created_at=newest.created_at + by)
    )
    await session.commit()


async def test_an_edit_after_a_publish_stamped_in_the_future_counts(
    client, test_db_session, admin_auth_header, clean_tables
):
    admin = await _admin(test_db_session)
    dataset_id = await _dataset(test_db_session, admin.id)
    [created] = (await _apply(test_db_session, admin, _publish(dataset_id))).maps
    await _move_event(
        test_db_session, created.map_id, "manifest.publish", timedelta(hours=1)
    )
    await _edit_paint_in_the_builder(
        client, admin_auth_header, test_db_session, created.map_id
    )

    [result] = (await _apply(test_db_session, admin, _publish(dataset_id))).maps

    assert (result.styling, _codes(result)) == ("kept", [("A070", "info", None)])


async def test_a_replace_after_an_edit_stamped_in_the_future_resets(
    client, test_db_session, admin_auth_header, clean_tables
):
    admin = await _admin(test_db_session)
    dataset_id = await _dataset(test_db_session, admin.id)
    [created] = (await _apply(test_db_session, admin, _publish(dataset_id))).maps
    await _edit_paint_in_the_builder(
        client, admin_auth_header, test_db_session, created.map_id
    )
    await _move_event(
        test_db_session, created.map_id, "layer.style_update", timedelta(hours=1)
    )
    await _apply(test_db_session, admin, _publish(dataset_id, styling="replace"))
    await _builder_save(client, admin_auth_header, test_db_session, created.map_id)

    [result] = (await _apply(test_db_session, admin, _publish(dataset_id))).maps

    assert result.styling == "applied"


async def test_events_of_one_transaction_list_in_the_order_recorded(
    test_db_session, clean_tables
):
    from app.modules.catalog.maps.service import record_map_history_event
    from app.modules.catalog.maps.service_history import list_map_history

    admin = await _admin(test_db_session)
    dataset_id = await _dataset(test_db_session, admin.id)
    [created] = (await _apply(test_db_session, admin, _publish(dataset_id))).maps
    await _move_event(
        test_db_session, created.map_id, "manifest.publish", timedelta(hours=1)
    )
    recorded = [
        await record_map_history_event(
            test_db_session,
            map_id=created.map_id,
            actor=admin,
            target_type="map",
            action=action,
            summary=action,
        )
        for action in ("map.rename", "map.visibility_update")
    ]
    times = [event.created_at for event in recorded]
    await test_db_session.commit()

    events, _ = await list_map_history(test_db_session, created.map_id)

    assert [e.action for e in events] == [
        "map.visibility_update",
        "map.rename",
        "manifest.publish",
    ]
    assert times[0] < times[1]


async def test_a_view_save_records_the_basemap_appearance_it_replaced(
    client, test_db_session, admin_auth_header, clean_tables
):
    """The previous values are read under the map row lock, so a change
    committed while the save waited for it is the one it replaced."""
    from sqlalchemy import update

    import app.core.db as db_module
    from app.modules.catalog.maps import service_update

    admin = await _admin(test_db_session)
    dataset_id = await _dataset(test_db_session, admin.id)
    [created] = (await _apply(test_db_session, admin, _publish(dataset_id))).maps
    other_save = {**_BUILDER_BASEMAP_CONFIG, "opacity": 0.25}
    real_lock = service_update.lock_map_layers

    async def another_save_commits_first(session, map_id):
        async with db_module.async_session() as other:
            await other.execute(
                update(Map).where(Map.id == map_id).values(basemap_config=other_save)
            )
            await other.commit()
        await real_lock(session, map_id)

    with patch.object(service_update, "lock_map_layers", another_save_commits_first):
        await _builder_save(
            client,
            admin_auth_header,
            test_db_session,
            created.map_id,
            basemap_config={**_BUILDER_BASEMAP_CONFIG, "opacity": 0.5},
        )

    [event] = [
        e
        for e in await _history(test_db_session, created.map_id)
        if e.action == "map.basemap_update"
    ]
    assert event.details["previous"] == other_save


async def test_a_settings_event_from_before_view_changed_counts_a_sent_view(
    test_db_session, clean_tables
):
    """Older events list the fields sent; any view field among them counts."""
    from app.modules.catalog.maps.service import record_map_history_event

    admin = await _admin(test_db_session)
    dataset_id = await _dataset(test_db_session, admin.id)
    [created] = (await _apply(test_db_session, admin, _publish(dataset_id))).maps
    await record_map_history_event(
        test_db_session,
        map_id=created.map_id,
        actor=admin,
        target_type="map",
        action="map.config_update",
        summary="Updated map settings",
        details={"changed_fields": ["notes", "zoom"]},
    )
    await test_db_session.commit()

    [result] = (await _apply(test_db_session, admin, _publish(dataset_id))).maps

    assert result.styling == "kept"


async def test_a_reorder_in_the_builder_is_not_a_styling_edit(
    client, test_db_session, admin_auth_header, clean_tables
):
    admin = await _admin(test_db_session)
    dataset_id = await _dataset(test_db_session, admin.id)
    [created] = (await _apply(test_db_session, admin, _publish(dataset_id))).maps
    parks, names = await _layers(test_db_session, created.map_id)
    response = await client.patch(
        f"/maps/{created.map_id}/layers",
        json={"order": [str(names.id), str(parks.id)]},
        headers=admin_auth_header,
    )
    assert response.status_code == 200, response.text

    [result] = (await _apply(test_db_session, admin, _publish(dataset_id))).maps

    assert result.styling == "applied"


async def test_replace_overrides_a_builder_edit(
    client, test_db_session, admin_auth_header, clean_tables
):
    admin = await _admin(test_db_session)
    dataset_id = await _dataset(test_db_session, admin.id)
    [created] = (await _apply(test_db_session, admin, _publish(dataset_id))).maps
    await _edit_paint_in_the_builder(
        client, admin_auth_header, test_db_session, created.map_id
    )

    [result] = (
        await _apply(test_db_session, admin, _publish(dataset_id, styling="replace"))
    ).maps

    assert (result.styling, result.messages) == ("applied", [])
    [parks, _] = await _layers(test_db_session, created.map_id)
    assert parks.paint["fill-color"][0] == "match"


async def test_keep_keeps_styling_and_dropped_layers_without_an_edit(
    test_db_session, clean_tables
):
    admin = await _admin(test_db_session)
    dataset_id = await _dataset(test_db_session, admin.id)
    [created] = (await _apply(test_db_session, admin, _publish(dataset_id))).maps
    before = await _state(test_db_session, created.map_id)
    only_parks = _entry(
        "qgis-map-parks",
        _layer("parks", dataset_id=str(dataset_id), paint={"fill-color": "#000"}),
        styling="keep",
    )

    [result] = (await _apply(test_db_session, admin, only_parks)).maps

    assert (result.styling, result.messages, result.removed_layers) == ("kept", [], [])
    assert await _state(test_db_session, created.map_id) == before


async def test_a_kept_replace_if_unedited_still_removes_dropped_layers(
    client, test_db_session, admin_auth_header, clean_tables
):
    admin = await _admin(test_db_session)
    dataset_id = await _dataset(test_db_session, admin.id)
    [created] = (await _apply(test_db_session, admin, _publish(dataset_id))).maps
    await _edit_paint_in_the_builder(
        client, admin_auth_header, test_db_session, created.map_id
    )
    only_parks = _entry(
        "qgis-map-parks", _layer("parks", dataset_id=str(dataset_id), **_PARKS)
    )

    [result] = (await _apply(test_db_session, admin, only_parks)).maps

    assert result.styling == "kept"
    assert [r.key for r in result.removed_layers] == ["names"]
    assert [
        layer.manifest_key for layer in await _layers(test_db_session, created.map_id)
    ] == ["parks"]


@pytest.mark.parametrize("mode", ["replace_if_unedited", "keep"])
async def test_a_kept_layer_says_it_still_shows_its_earlier_dataset(
    client, test_db_session, admin_auth_header, clean_tables, mode
):
    admin = await _admin(test_db_session)
    first = await _dataset(test_db_session, admin.id)
    second = await _dataset(test_db_session, admin.id)
    [created] = (await _apply(test_db_session, admin, _publish(first))).maps
    if mode == "replace_if_unedited":
        await _edit_paint_in_the_builder(
            client, admin_auth_header, test_db_session, created.map_id
        )
    moved = _entry(
        "qgis-map-parks",
        _layer("parks", dataset_id=str(second), **_PARKS),
        _layer("names", dataset_id=str(first)),
        styling=mode,
    )

    [checked] = (await _apply(test_db_session, admin, moved, dry_run=True)).maps
    [kept] = (await _apply(test_db_session, admin, moved)).maps

    for result in (checked, kept):
        assert result.styling == "kept"
        [warning] = [m for m in result.messages if m.code == "A073"]
        assert (warning.severity, warning.layer) == ("warning", "parks")
        assert "still shows its earlier dataset" in warning.message
    parks, names = await _layers(test_db_session, created.map_id)
    assert (parks.dataset_id, names.dataset_id) == (first, first)


# A dataset id nothing has; a literal, so xdist workers collect the same ids.
_NO_SUCH_DATASET = "7d1f3c2a-9b4e-4f60-8a21-5c0e9d3b7f14"


async def _hide(session, dataset_id) -> None:
    """Make the dataset private, so only its owner and admins read it."""
    from sqlalchemy import update

    from app.modules.catalog.datasets.domain.models import Dataset, Record

    record_id = select(Dataset.record_id).where(Dataset.id == dataset_id)
    await session.execute(
        update(Record)
        .where(Record.id == record_id.scalar_subquery())
        .values(visibility="private")
    )
    await session.commit()


@pytest.mark.parametrize("hidden_side", ["stored", "manifest"])
@pytest.mark.parametrize("mode", ["keep", "replace_if_unedited"])
async def test_a_kept_publish_answers_alike_for_a_hidden_and_a_missing_dataset(
    client, test_db_session, admin_auth_header, clean_tables, mode, hidden_side
):
    """A dataset the caller can't read answers as one that doesn't exist,
    whether the stored layer or the manifest names it."""
    admin = await _admin(test_db_session)
    editor, headers = await _person(client, test_db_session, admin_auth_header)
    own = await _dataset(test_db_session, editor.id)
    admins = await _dataset(test_db_session, admin.id)
    stored = admins if hidden_side == "stored" else own
    first = _entry(
        "qgis-map-parks",
        _layer("parks", dataset_id=str(stored)),
        _layer("names", dataset_id=str(own)),
    )
    [created] = (await _apply(test_db_session, editor, first)).maps
    if mode == "replace_if_unedited":
        await _edit_paint_in_the_builder(
            client, headers, test_db_session, created.map_id
        )
    await _hide(test_db_session, admins)
    answers = {}
    # The hidden dataset's own id, or one nothing has.
    for name, parks_dataset in (("hidden", str(admins)), ("missing", _NO_SUCH_DATASET)):
        entry = _entry(
            "qgis-map-parks",
            _layer("parks", dataset_id=parks_dataset),
            _layer("names", dataset_id=str(own)),
            styling=mode,
        )
        answers[name] = [
            (await _apply(test_db_session, editor, entry, dry_run=dry_run)).maps[0]
            for dry_run in (True, False)
        ]

    [hidden_checked, hidden_applied] = answers["hidden"]
    [missing_checked, missing_applied] = answers["missing"]
    assert hidden_checked.model_dump() == missing_checked.model_dump()
    assert hidden_applied.model_dump() == missing_applied.model_dump()
    assert ("A052", "error", "parks") in _codes(hidden_applied)
    assert _codes(hidden_checked) == _codes(hidden_applied)
    # A readable kept layer still says the manifest named another dataset.
    kept_warning = ("A073", "warning", "parks") in _codes(hidden_applied)
    assert kept_warning is (hidden_side == "manifest")


async def test_a_kept_layer_on_a_dataset_the_request_creates_says_so(
    test_db_session, clean_tables
):
    from app.processing.ingest.manifest_maps import run_manifest_maps
    from app.processing.ingest.manifest_schemas import ManifestApplyEntryResult
    from tests.test_manifest_maps_apply import _maps_only
    from tests.test_manifest_maps_dry_run import _local_dataset_entry

    admin = await _admin(test_db_session)
    dataset_id = await _dataset(test_db_session, admin.id)
    await _apply(test_db_session, admin, _publish(dataset_id))
    request = _maps_only(
        _entry(
            "qgis-map-parks",
            _layer("parks", dataset_key="qgis-new"),
            _layer("names", dataset_id=str(dataset_id)),
            styling="keep",
        ),
        datasets=[_local_dataset_entry("qgis-new")],
        dry_run=True,
    )
    results = [
        ManifestApplyEntryResult(dataset_key="qgis-new", action="create", message="m")
    ]

    [result] = await run_manifest_maps(test_db_session, request, admin, results)

    assert _codes(result) == [("A073", "warning", "parks")]


async def test_a_map_another_change_holds_answers_busy(test_db_session, clean_tables):
    """Losing the wait for the map row is routine; the map says to retry."""
    from sqlalchemy import text

    import app.core.db as db_module

    admin = await _admin(test_db_session)
    dataset_id = await _dataset(test_db_session, admin.id)
    [created] = (await _apply(test_db_session, admin, _publish(dataset_id))).maps

    async with db_module.async_session() as other:
        await other.execute(
            text("SELECT 1 FROM catalog.maps WHERE id = :id FOR UPDATE"),
            {"id": created.map_id},
        )
        with patch.object(manifest_apply, "log") as logged:
            [result] = (await _apply(test_db_session, admin, _publish(dataset_id))).maps
        await other.rollback()

    assert result.action == "error"
    assert "Another change to this map is in progress" in result.messages[0].message
    logged.exception.assert_not_called()


# ---------------------------------------------------------------------------
# Notes
# ---------------------------------------------------------------------------


def test_the_notes_limit_is_the_maps():
    assert MapUpdate.model_fields["notes"].metadata[-1].max_length == NOTES_LIMIT


_BLOCK = "Published from old\nold: loss"
_WRITTEN = hashlib.sha256(_BLOCK.encode()).hexdigest()


def test_the_block_last_written_is_replaced_and_the_users_text_kept():
    existing = f"{_BLOCK}\n---\nMy notes\n---\nstill mine"

    notes = managed_notes(existing, ["Published from new", "a: b"], {_WRITTEN})

    assert notes.text == "Published from new\na: b\n---\nMy notes\n---\nstill mine"
    assert notes.digest == hashlib.sha256(b"Published from new\na: b").hexdigest()


@pytest.mark.parametrize(
    ("existing", "written"),
    [
        # A map's own notes with a divider, before any publish wrote a block.
        ("Survey instructions\n---\nObservations", None),
        # Text typed above the block.
        (f"Read me first\n{_BLOCK}\n---\nMine", _WRITTEN),
        # The block deleted, a divider of the user's own left.
        ("Intro\n---\nMine", _WRITTEN),
        # The block edited by the user.
        (f"{_BLOCK} (checked)\n---\nMine", _WRITTEN),
        # No divider at all.
        ("Written in GeoLens", _WRITTEN),
    ],
    ids=[
        "legacy-divider",
        "typed-above",
        "block-deleted",
        "block-edited",
        "no-divider",
    ],
)
def test_notes_the_last_publish_didnt_write_are_kept_whole(existing, written):
    notes = managed_notes(existing, ["P"], () if written is None else {written})

    assert notes.text == f"P\n---\n{existing}"


def test_a_block_saved_back_with_windows_line_endings_is_still_ours():
    existing = _BLOCK.replace("\n", "\r\n") + "\r\n---\r\nMine\r\n"

    assert managed_notes(existing, ["P"], {_WRITTEN}).text == "P\n---\nMine\r\n"


def test_a_block_the_builder_trimmed_is_still_ours():
    assert managed_notes(f"{_BLOCK}\n---", ["P"], {_WRITTEN}).text == "P\n---\n"


def test_a_long_loss_report_is_cut_and_the_users_text_kept_whole():
    user = "u" * 30_000
    lines = ["Published", *(f"layers[{i}]: kind (detail)" for i in range(5_000))]

    notes = managed_notes(f"{_BLOCK}\n---\n{user}", lines, {_WRITTEN}).text

    assert len(notes) <= NOTES_LIMIT
    assert notes.endswith(f"\n---\n{user}")
    managed = notes[: -len(f"\n---\n{user}")].split("\n")
    assert managed[0] == "Published"
    shown = len(managed) - 2
    assert managed[-1] == f"... {5_000 - shown} more entries"
    assert managed[1:-1] == lines[1 : shown + 1]


@pytest.mark.parametrize("over", [0, 1])
def test_notes_at_the_limit_keep_the_users_text_and_drop_the_block(over):
    line = "Published from geolens-qgis 0.2.0 on 2026-11-22"
    user = "u" * (NOTES_LIMIT - len(line) - len("\n---\n") + over)

    notes = managed_notes(user, [line, "a: loss"], ())

    if over == 0:
        assert (notes.text, notes.digest is not None) == (f"{line}\n---\n{user}", True)
    else:
        assert (notes.text, notes.digest) == (user, None)
    assert len(notes.text) <= NOTES_LIMIT


async def test_a_publish_writes_the_managed_block_and_keeps_the_users_text(
    client, test_db_session, admin_auth_header, clean_tables
):
    admin = await _admin(test_db_session)
    dataset_id = await _dataset(test_db_session, admin.id)
    entry = _publish(dataset_id, loss_report=_LOSS)
    [created] = (await _apply(test_db_session, admin, entry)).maps
    first = (await _map_row(test_db_session, created.map_id)).notes
    response = await client.put(
        f"/maps/{created.map_id}",
        json={"notes": first + "Notes the user wrote."},
        headers=admin_auth_header,
    )
    assert response.status_code == 200, response.text

    await _apply(test_db_session, admin, _publish(dataset_id))

    notes = (await _map_row(test_db_session, created.map_id)).notes
    header, separator, user = notes.split("\n", 2)
    assert first.startswith("Published from geolens-qgis 0.2.0 on ")
    assert "layers[0].style: approximated (3 rules)" in first
    assert header.startswith("Published from geolens-qgis 0.2.0 on ")
    assert (separator, user) == ("---", "Notes the user wrote.")


async def test_a_kept_publish_writes_no_loss_lines(
    client, test_db_session, admin_auth_header, clean_tables
):
    admin = await _admin(test_db_session)
    dataset_id = await _dataset(test_db_session, admin.id)
    [created] = (await _apply(test_db_session, admin, _publish(dataset_id))).maps
    await _edit_paint_in_the_builder(
        client, admin_auth_header, test_db_session, created.map_id
    )

    [kept] = (
        await _apply(test_db_session, admin, _publish(dataset_id, loss_report=_LOSS))
    ).maps

    assert kept.styling == "kept"
    notes = (await _map_row(test_db_session, created.map_id)).notes
    assert "approximated" not in notes


async def test_notes_are_one_line_per_item_whatever_the_client_sends(
    test_db_session, clean_tables
):
    admin = await _admin(test_db_session)
    dataset_id = await _dataset(test_db_session, admin.id)
    body_client = {"id": "geolens-qgis", "version": "0.2.0\n---", "app": "QGIS\n4"}
    entry = _publish(dataset_id)

    from app.processing.ingest.manifest_schemas import ManifestApplyRequest
    from app.processing.ingest.manifest_service import apply_manifest
    from tests.test_manifest_maps_dry_run import _body, _http_request

    request = ManifestApplyRequest.model_validate(
        {**_body(entry, dry_run=False), "client": body_client}
    )
    [created] = (
        await apply_manifest(test_db_session, request, admin, _http_request())
    ).maps

    notes = (await _map_row(test_db_session, created.map_id)).notes
    assert notes.split("\n")[1] == "---"


# ---------------------------------------------------------------------------
# Thumbnail
# ---------------------------------------------------------------------------


async def test_a_thumbnail_is_stored_and_a_bad_one_is_a_warning(
    test_db_session, clean_tables
):
    admin = await _admin(test_db_session)
    dataset_id = await _dataset(test_db_session, admin.id)

    [stored] = (
        await _apply(test_db_session, admin, _publish(dataset_id, thumbnail=_PNG))
    ).maps
    first_uri = (await _map_row(test_db_session, stored.map_id)).thumbnail_uri
    [bad] = (
        await _apply(
            test_db_session,
            admin,
            _publish(dataset_id, thumbnail="data:image/png;base64,AAAA"),
        )
    ).maps

    assert (stored.action, stored.messages) == ("create", [])
    assert first_uri
    assert bad.action == "update"
    assert _codes(bad) == [("A072", "warning", None)]
    assert "not a valid image" in bad.messages[0].message
    assert (await _map_row(test_db_session, bad.map_id)).thumbnail_uri == first_uri


async def test_a_publish_key_adds_a_thumbnail_but_never_replaces_one(
    test_db_session, clean_tables
):
    admin = await _admin(test_db_session)
    dataset_id = await _dataset(test_db_session, admin.id)
    _as_publish_key(test_db_session)

    [first] = (
        await _apply(test_db_session, admin, _publish(dataset_id, thumbnail=_PNG))
    ).maps
    [second] = (
        await _apply(test_db_session, admin, _publish(dataset_id, thumbnail=_PNG))
    ).maps

    assert first.messages == []
    assert _codes(second) == [("A072", "warning", None)]
    assert "publish key" in second.messages[0].message
    assert await test_db_session.scalar(select(Map.thumbnail_uri)) is not None


def test_the_thumbnail_goes_through_the_upload_service():
    source = " ".join(Path(manifest_republish.__file__).read_text().split())
    assert (
        'store_map_image( session, map_id, data_uri, "thumbnail", user, '
        "expected_updated_at=published_at, )" in source
    )


async def test_a_kept_layer_is_judged_on_the_dataset_it_keeps(
    client, test_db_session, admin_auth_header, clean_tables
):
    from sqlalchemy import update

    from app.modules.catalog.datasets.domain.models import Dataset, Record

    admin = await _admin(test_db_session)
    kept_dataset = await _dataset(test_db_session, admin.id)
    named_now = await _dataset(test_db_session, admin.id)
    [created] = (
        await _apply(
            test_db_session, admin, _publish(kept_dataset, visibility="public")
        )
    ).maps
    await _edit_paint_in_the_builder(
        client, admin_auth_header, test_db_session, created.map_id
    )
    # The dataset the map goes on showing is narrowed after the publish.
    record_id = select(Dataset.record_id).where(Dataset.id == kept_dataset)
    await test_db_session.execute(
        update(Record)
        .where(Record.id == record_id.scalar_subquery())
        .values(visibility="private")
    )
    await test_db_session.commit()

    [result] = (await _apply(test_db_session, admin, _publish(named_now))).maps

    assert _codes(result) == [
        ("A070", "info", None),
        ("A073", "warning", "parks"),
        ("A073", "warning", "names"),
        ("A020", "error", None),
    ]


async def test_a_kept_publish_keeps_the_builders_layer_order(
    client, test_db_session, admin_auth_header, clean_tables
):
    admin = await _admin(test_db_session)
    dataset_id = await _dataset(test_db_session, admin.id)
    [created] = (await _apply(test_db_session, admin, _publish(dataset_id))).maps
    parks, names = await _layers(test_db_session, created.map_id)
    response = await client.patch(
        f"/maps/{created.map_id}/layers",
        json={"order": [str(names.id), str(parks.id)]},
        headers=admin_auth_header,
    )
    assert response.status_code == 200, response.text
    with_trails = _entry(
        "qgis-map-parks",
        _layer("parks", dataset_id=str(dataset_id)),
        _layer("names", dataset_id=str(dataset_id)),
        _layer("trails", dataset_id=str(dataset_id)),
        styling="keep",
    )

    [result] = (await _apply(test_db_session, admin, with_trails)).maps

    assert result.styling == "kept"
    stored = await _layers(test_db_session, created.map_id)
    assert [layer.manifest_key for layer in stored] == ["names", "parks", "trails"]


async def test_typing_above_the_block_keeps_that_text_on_the_next_publish(
    client, test_db_session, admin_auth_header, clean_tables
):
    admin = await _admin(test_db_session)
    dataset_id = await _dataset(test_db_session, admin.id)
    [created] = (await _apply(test_db_session, admin, _publish(dataset_id))).maps
    first = (await _map_row(test_db_session, created.map_id)).notes
    await _builder_save(
        client,
        admin_auth_header,
        test_db_session,
        created.map_id,
        notes=f"Read me first\n{first}",
    )

    await _apply(test_db_session, admin, _publish(dataset_id))

    notes = (await _map_row(test_db_session, created.map_id)).notes
    assert notes.endswith(f"\n---\nRead me first\n{first}")
    [publish, republish] = [
        e
        for e in await _history(test_db_session, created.map_id)
        if e.action == "manifest.publish"
    ]
    assert publish.details["notes_digest"] and republish.details["notes_digest"]


async def test_full_notes_answer_info_in_both_runs_and_stay_whole(
    test_db_session, clean_tables
):
    from sqlalchemy import update

    admin = await _admin(test_db_session)
    dataset_id = await _dataset(test_db_session, admin.id)
    [created] = (await _apply(test_db_session, admin, _publish(dataset_id))).maps
    full = "n" * NOTES_LIMIT
    await test_db_session.execute(
        update(Map).where(Map.id == created.map_id).values(notes=full)
    )
    await test_db_session.commit()

    [checked] = (
        await _apply(test_db_session, admin, _publish(dataset_id), dry_run=True)
    ).maps
    [applied] = (await _apply(test_db_session, admin, _publish(dataset_id))).maps

    for result in (checked, applied):
        assert (result.action, _codes(result)) == ("update", [("A071", "info", None)])
        assert "no room" in result.messages[0].message
    assert (await _map_row(test_db_session, created.map_id)).notes == full


async def test_a_dataset_a_kept_layer_drops_doesnt_refuse_a_public_map(
    client, test_db_session, admin_auth_header, clean_tables
):
    admin = await _admin(test_db_session)
    shown = await _dataset(test_db_session, admin.id)
    discarded = await _dataset(test_db_session, admin.id, visibility="private")
    [created] = (
        await _apply(test_db_session, admin, _publish(shown, visibility="public"))
    ).maps
    await _edit_paint_in_the_builder(
        client, admin_auth_header, test_db_session, created.map_id
    )

    [result] = (await _apply(test_db_session, admin, _publish(discarded))).maps

    assert (result.action, result.styling, result.visibility) == (
        "update",
        "kept",
        "public",
    )
    assert _codes(result) == [
        ("A070", "info", None),
        ("A073", "warning", "parks"),
        ("A073", "warning", "names"),
    ]


async def test_a_kept_publish_leaves_the_thumbnail(
    client, test_db_session, admin_auth_header, clean_tables
):
    admin = await _admin(test_db_session)
    dataset_id = await _dataset(test_db_session, admin.id)
    [created] = (await _apply(test_db_session, admin, _publish(dataset_id))).maps
    await _edit_paint_in_the_builder(
        client, admin_auth_header, test_db_session, created.map_id
    )

    [kept] = (
        await _apply(test_db_session, admin, _publish(dataset_id, thumbnail=_PNG))
    ).maps

    assert (kept.styling, kept.messages[-1].code) == ("kept", "A070")
    assert (await _map_row(test_db_session, created.map_id)).thumbnail_uri is None


async def test_decomposed_text_in_the_block_still_matches_on_the_next_publish(
    test_db_session, clean_tables
):
    """The notes field stores NFC, so the block is hashed as stored."""
    from app.processing.ingest.manifest_schemas import ManifestApplyRequest
    from app.processing.ingest.manifest_service import apply_manifest
    from tests.test_manifest_maps_dry_run import _body, _http_request

    admin = await _admin(test_db_session)
    dataset_id = await _dataset(test_db_session, admin.id)
    decomposed = "Café"
    loss = {
        "items": [{"path": "layers[0]", "kind": "approximated", "detail": decomposed}]
    }
    body = {
        **_body(_publish(dataset_id, loss_report=loss), dry_run=False),
        "client": {"id": "geolens-qgis", "version": "0.2.0", "app": decomposed},
    }

    for _ in range(2):
        [result] = (
            await apply_manifest(
                test_db_session,
                ManifestApplyRequest.model_validate(body),
                admin,
                _http_request(),
            )
        ).maps

    notes = (await _map_row(test_db_session, result.map_id)).notes
    assert notes.count("Published from") == 1
    assert notes.split("\n").count("---") == 1
    assert "Café" in notes


async def test_the_notes_block_is_recognised_whatever_order_the_clocks_give(
    test_db_session, clean_tables
):
    """A row from an older release can carry an earlier time than the
    publish before it; its block is still the one the notes hold."""
    from datetime import timedelta

    from sqlalchemy import update

    from app.modules.catalog.maps.models import MapEditHistoryEvent

    admin = await _admin(test_db_session)
    dataset_id = await _dataset(test_db_session, admin.id)
    [created] = (
        await _apply(test_db_session, admin, _publish(dataset_id, loss_report=_LOSS))
    ).maps
    await _apply(test_db_session, admin, _publish(dataset_id))
    first, second = [
        e
        for e in await _history(test_db_session, created.map_id)
        if e.action == "manifest.publish"
    ]
    assert first.details["notes_digest"] != second.details["notes_digest"]
    # The second publish's host clock ran behind the first's.
    await test_db_session.execute(
        update(MapEditHistoryEvent)
        .where(MapEditHistoryEvent.id == second.id)
        .values(created_at=first.created_at - timedelta(minutes=5))
    )
    await test_db_session.commit()

    await _apply(test_db_session, admin, _publish(dataset_id))

    notes = (await _map_row(test_db_session, created.map_id)).notes
    assert notes.count("Published from") == 1
    assert notes.split("\n").count("---") == 1


@pytest.mark.parametrize("case", ["bomb", "parser-raises", "gif"])
async def test_a_thumbnail_the_upload_route_refuses_or_accepts_never_fails_the_publish(
    test_db_session, clean_tables, case
):
    """The upload route's own rules: an unreadable image is a warning, and a
    format Pillow verifies is stored, as the route stores it."""
    from tests.test_map_image_verified_format import (
        _data_uri,
        _dds_without_pixel_format_flags,
        _image_bytes,
        _png_declaring,
    )

    image = {
        "bomb": _png_declaring(100_000, 100_000),
        "parser-raises": _dds_without_pixel_format_flags(),
        "gif": _image_bytes("GIF"),
    }[case]
    admin = await _admin(test_db_session)
    dataset_id = await _dataset(test_db_session, admin.id)

    [result] = (
        await _apply(
            test_db_session,
            admin,
            _publish(dataset_id, thumbnail=_data_uri("image/png", image)),
        )
    ).maps

    assert result.action == "create"
    stored = (await _map_row(test_db_session, result.map_id)).thumbnail_uri
    if case == "gif":
        assert (result.messages, bool(stored)) == ([], True)
    else:
        assert _codes(result) == [("A072", "warning", None)]
        assert "not a valid image" in result.messages[0].message
        assert stored is None


async def test_a_publish_whose_map_changed_before_its_thumbnail_keeps_the_newer_one(
    test_db_session, clean_tables
):
    """Publish A commits; before its thumbnail is stored, publish B commits
    with its own. A's thumbnail is then refused, and B's stays."""
    from unittest.mock import patch

    import app.core.db as db_module
    from app.modules.catalog.maps import manifest_apply
    from tests.test_map_image_verified_format import _data_uri, _image_bytes

    admin = await _admin(test_db_session)
    dataset_id = await _dataset(test_db_session, admin.id)
    await _apply(test_db_session, admin, _publish(dataset_id))
    real = manifest_apply.store_manifest_thumbnail
    calls: list[str] = []
    after_b: dict[str, str | None] = {}

    async def b_publishes_first(session, map_id, data_uri, user, published_at):
        calls.append(data_uri)
        if len(calls) == 1:
            async with db_module.async_session() as other:
                [b] = (
                    await _apply(
                        other,
                        admin,
                        _publish(
                            dataset_id,
                            thumbnail=_data_uri("image/png", _image_bytes("PNG")),
                        ),
                    )
                ).maps
                assert (b.action, b.messages) == ("update", [])
                after_b["uri"] = (await _map_row(other, map_id)).thumbnail_uri
        return await real(session, map_id, data_uri, user, published_at)

    with patch.object(manifest_apply, "store_manifest_thumbnail", b_publishes_first):
        [a] = (
            await _apply(
                test_db_session,
                admin,
                _publish(
                    dataset_id, thumbnail=_data_uri("image/jpeg", _image_bytes("JPEG"))
                ),
            )
        ).maps

    assert after_b["uri"]
    assert _codes(a) == [("A072", "warning", None)]
    assert "changed after this publish" in a.messages[0].message
    assert (await _map_row(test_db_session, a.map_id)).thumbnail_uri == after_b["uri"]
