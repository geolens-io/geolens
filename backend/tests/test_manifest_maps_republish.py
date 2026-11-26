"""Manifest version 2 maps on republish: the styling policy, notes and thumbnail.

Requirements: the docker database must be running with migrations applied.
"""

from __future__ import annotations

import ast
import copy
import hashlib
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import select

from app.core.config import settings
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
from tests.factories import create_dataset
from tests.test_manifest_maps_dry_run import (
    _COLUMNS,
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
        assert f"Updated layer style by {admin.username}," in result.messages[0].message
    assert await _state(test_db_session, created.map_id) == before
    map_obj = await _map_row(test_db_session, created.map_id)
    assert (map_obj.name, map_obj.description) == ("New name", "New description")
    publishes = [
        e
        for e in await _history(test_db_session, created.map_id)
        if e.action == "manifest.publish"
    ]
    assert [e.details["styling_applied"] for e in publishes] == [True, False]


_MISSING = ["==", ["get", "NO_SUCH_COLUMN"], "x"]


def _asking_for_a_missing_column(dataset_id, *, mode, extra=()) -> dict:
    return _entry(
        "qgis-map-parks",
        _layer("parks", dataset_id=str(dataset_id), **{**_PARKS, "filter": _MISSING}),
        _layer("names", dataset_id=str(dataset_id)),
        *extra,
        styling=mode,
    )


@pytest.mark.parametrize(
    ("mode", "warned"),
    [("keep", False), ("replace", True)],
)
async def test_a_column_check_reads_the_styling_the_map_ends_with(
    test_db_session, clean_tables, mode, warned
):
    admin = await _admin(test_db_session)
    dataset_id = await _dataset(test_db_session, admin.id)
    await _apply(test_db_session, admin, _publish(dataset_id))
    entry = _asking_for_a_missing_column(dataset_id, mode=mode)

    [checked] = (await _apply(test_db_session, admin, entry, dry_run=True)).maps
    [applied] = (await _apply(test_db_session, admin, entry)).maps

    for result in (checked, applied):
        assert (("A063", "warning", "parks") in _codes(result)) is warned


async def test_a_new_layer_on_a_kept_publish_is_still_column_checked(
    test_db_session, clean_tables
):
    admin = await _admin(test_db_session)
    dataset_id = await _dataset(test_db_session, admin.id)
    await _apply(test_db_session, admin, _publish(dataset_id))
    entry = _asking_for_a_missing_column(
        dataset_id,
        mode="keep",
        extra=(
            _layer(
                "added",
                dataset_id=str(dataset_id),
                filter=_MISSING,
                label_config={"column": "NO_SUCH_COLUMN"},
            ),
        ),
    )

    [checked] = (await _apply(test_db_session, admin, entry, dry_run=True)).maps

    assert [c for c in _codes(checked) if c[0] == "A063"] == [
        ("A063", "warning", "added")
    ]


async def test_a070_shows_the_latest_edit_only_to_a_caller_who_reads_the_history(
    client, test_db_session, admin_auth_header, clean_tables
):
    from sqlalchemy import update

    admin = await _admin(test_db_session)
    viewer, _ = await _person(client, test_db_session, admin_auth_header, "viewer")
    dataset_id = await _dataset(test_db_session, admin.id)
    [created] = (await _apply(test_db_session, admin, _publish(dataset_id))).maps
    await service_history.record_map_history_event(
        test_db_session,
        map_id=created.map_id,
        actor=admin,
        target_type="map",
        action="layer.rename",
        summary="Renamed layer to Hidden Wetlands Survey",
    )
    await test_db_session.commit()
    [allowed] = (
        await _apply(test_db_session, admin, _publish(dataset_id), dry_run=True)
    ).maps
    await test_db_session.execute(
        update(Map).where(Map.id == created.map_id).values(created_by=viewer.id)
    )
    await test_db_session.commit()
    [denied] = (
        await _apply(test_db_session, viewer, _publish(dataset_id), dry_run=True)
    ).maps

    [a070] = [m for m in denied.messages if m.code == "A070"]
    assert "A003" in [m.code for m in denied.messages]
    assert "Wetlands" not in a070.message
    assert "UTC" not in a070.message
    assert "The latest edit: Renamed layer to Hidden Wetlands Survey" in (
        [m for m in allowed.messages if m.code == "A070"][0].message
    )


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
    # The schema bounds neither center coordinate, so any finite double can
    # arrive or be stored.
    assert not _view_moved("center_lng", 1e300, 1e300)
    assert _view_moved("center_lng", 1e300, -89.0)
    assert _view_moved("center_lat", 1e30, 1.5e30)
    assert _view_moved("center_lat", float("inf"), 12.0)


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


async def _patch_layers(client, headers, map_id, body) -> dict:
    response = await client.patch(f"/maps/{map_id}/layers", json=body, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


async def _add_a_builder_layer(client, headers, session, map_id, dataset_id):
    """A layer added in GeoLens: it has no manifest key."""
    await _patch_layers(
        client, headers, map_id, {"added": [{"dataset_id": str(dataset_id)}]}
    )
    [added] = [
        layer for layer in await _layers(session, map_id) if not layer.manifest_key
    ]
    return added


@pytest.mark.parametrize(
    ("edits", "styling"),
    [
        (("add",), "applied"),
        (("add", "restyle_added"), "applied"),
        (("restyle_keyed",), "kept"),
        (("restyle_keyed", "remove_keyed"), "applied"),
        (("restyle_keyed", "add", "restyle_added"), "kept"),
    ],
)
async def test_only_edits_to_layers_the_manifest_publishes_count(
    client, test_db_session, admin_auth_header, clean_tables, edits, styling
):
    admin = await _admin(test_db_session)
    dataset_id = await _dataset(test_db_session, admin.id)
    [created] = (await _apply(test_db_session, admin, _publish(dataset_id))).maps
    map_id = created.map_id
    added = None
    for edit in edits:
        if edit == "add":
            added = await _add_a_builder_layer(
                client, admin_auth_header, test_db_session, map_id, dataset_id
            )
        elif edit == "restyle_added":
            await _patch_layers(
                client,
                admin_auth_header,
                map_id,
                {
                    "updated": [
                        {"id": str(added.id), "paint": {"fill-color": "#00ff00"}}
                    ]
                },
            )
        elif edit == "restyle_keyed":
            await _edit_paint_in_the_builder(
                client, admin_auth_header, test_db_session, map_id
            )
        else:
            [parks] = [
                layer
                for layer in await _layers(test_db_session, map_id)
                if layer.manifest_key == "parks"
            ]
            await _patch_layers(
                client, admin_auth_header, map_id, {"removed": [str(parks.id)]}
            )

    [result] = (await _apply(test_db_session, admin, _publish(dataset_id))).maps

    assert result.styling == styling
    if added is not None:
        [kept] = [
            layer
            for layer in await _layers(test_db_session, map_id)
            if layer.id == added.id
        ]
        restyled = "restyle_added" in edits
        assert (kept.paint or {}).get("fill-color") == (
            "#00ff00" if restyled else (added.paint or {}).get("fill-color")
        )


async def test_a_settings_save_lists_only_view_fields_it_sent(
    test_db_session, clean_tables
):
    """``previous`` can be what the request loaded before a publish moved
    the view; a field the save didn't send isn't its move."""
    from app.modules.catalog.maps.service_update import _record_update_history
    from app.modules.catalog.maps.service_update import _HISTORY_FIELDS, VIEW_FIELDS

    admin = await _admin(test_db_session)
    dataset_id = await _dataset(test_db_session, admin.id)
    [created] = (await _apply(test_db_session, admin, _publish(dataset_id))).maps
    map_obj = await _map_row(test_db_session, created.map_id)
    stale = {f: getattr(map_obj, f) for f in (*_HISTORY_FIELDS, *VIEW_FIELDS)}
    stale["zoom"] = map_obj.zoom - 3
    for kwargs, changed in (({"notes": "Mine"}, ["notes"]), ({"zoom": 1.0}, ["zoom"])):
        await _record_update_history(
            test_db_session, map_obj, admin, kwargs, stale, changed, 0
        )
    await test_db_session.commit()

    assert [
        e.details["view_changed"]
        for e in await _history(test_db_session, created.map_id)
        if e.action == "map.config_update"
    ] == [[], ["zoom"]]


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


async def _dataset_of(
    session, owner_id, *, columns=_COLUMNS, geometry_type="MultiPolygon"
) -> uuid.UUID:
    dataset = await create_dataset(
        session,
        created_by=owner_id,
        geometry_type=geometry_type,
        column_info=[dict(column) for column in columns],
    )
    await session.commit()
    return dataset.id


async def _publish_then_edit(client, session, headers, user, entry, mode):
    """Publish ``entry``, then, for ``replace_if_unedited``, restyle a layer
    in the builder, so the next publish of either ``mode`` keeps the styling."""
    [created] = (await _apply(session, user, entry)).maps
    if mode == "replace_if_unedited":
        await _edit_paint_in_the_builder(client, headers, session, created.map_id)
    return created


def _moving(parks_dataset, names_dataset, mode, **parks) -> dict:
    """The parks layer pointed at ``parks_dataset``, with an opacity the
    stored layer doesn't have, so taking the manifest's styling shows."""
    return _entry(
        "qgis-map-parks",
        _layer(
            "parks",
            dataset_id=str(parks_dataset),
            **{**_PARKS, "opacity": 0.5, **parks},
        ),
        _layer("names", dataset_id=str(names_dataset)),
        styling=mode,
    )


async def _rows(session, map_id) -> list[tuple]:
    return [
        (layer.id, layer.manifest_key, layer.sort_order, layer.dataset_id)
        for layer in await _layers(session, map_id)
    ]


def _warnings(result) -> list[tuple]:
    return [code for code in _codes(result) if code[1] != "info"]


@pytest.mark.parametrize("mode", ["replace_if_unedited", "keep"])
async def test_a_kept_layer_moves_with_its_styling_to_a_dataset_it_fits(
    client, test_db_session, admin_auth_header, clean_tables, mode
):
    admin = await _admin(test_db_session)
    first = await _dataset(test_db_session, admin.id)
    # Single and multi part geometries are one type.
    second = await _dataset_of(test_db_session, admin.id, geometry_type="Polygon")
    created = await _publish_then_edit(
        client, test_db_session, admin_auth_header, admin, _publish(first), mode
    )
    rows = await _rows(test_db_session, created.map_id)
    styled = copy.deepcopy(await _state(test_db_session, created.map_id))
    entry = _moving(second, first, mode)

    [checked] = (await _apply(test_db_session, admin, entry, dry_run=True)).maps
    assert await _rows(test_db_session, created.map_id) == rows
    [moved] = (await _apply(test_db_session, admin, entry)).maps

    for result in (checked, moved):
        assert (result.action, result.styling, _warnings(result)) == (
            "update",
            "kept",
            [],
        )
    assert await _rows(test_db_session, created.map_id) == [
        (*row[:3], second if row[1] == "parks" else first) for row in rows
    ]
    assert await _state(test_db_session, created.map_id) == styled


@pytest.mark.parametrize("mode", ["replace_if_unedited", "keep"])
@pytest.mark.parametrize(
    ("geometry_type", "columns", "misfit"),
    [
        ("MultiPoint", _COLUMNS, "its geometry is point, not polygon"),
        ("MultiPolygon", _COLUMNS[:1], "it has no column park_name"),
    ],
    ids=["geometry", "missing-column"],
)
async def test_a_kept_layer_that_doesnt_fit_takes_the_manifests_styling(
    client,
    test_db_session,
    admin_auth_header,
    clean_tables,
    mode,
    geometry_type,
    columns,
    misfit,
):
    admin = await _admin(test_db_session)
    first = await _dataset(test_db_session, admin.id)
    second = await _dataset_of(
        test_db_session, admin.id, geometry_type=geometry_type, columns=columns
    )
    created = await _publish_then_edit(
        client, test_db_session, admin_auth_header, admin, _publish(first), mode
    )
    rows = await _rows(test_db_session, created.map_id)
    names_before = copy.deepcopy(
        (await _state(test_db_session, created.map_id))["layers"]["names"]
    )
    entry = _moving(second, first, mode)

    [checked] = (await _apply(test_db_session, admin, entry, dry_run=True)).maps
    assert await _rows(test_db_session, created.map_id) == rows
    [moved] = (await _apply(test_db_session, admin, entry)).maps

    for result in (checked, moved):
        assert result.styling == "kept"
        [warning] = [m for m in result.messages if m.code == "A073"]
        assert (warning.severity, warning.layer) == ("warning", "parks")
        assert f"doesn't fit that dataset: {misfit}." in warning.message
    assert await _rows(test_db_session, created.map_id) == [
        (*row[:3], second if row[1] == "parks" else first) for row in rows
    ]
    layers = (await _state(test_db_session, created.map_id))["layers"]
    assert layers["parks"]["opacity"] == 0.5
    assert layers["parks"]["paint"]["fill-color"][0] == "match"
    # The other layer keeps its styling and dataset.
    assert layers["names"] == names_before


_AREA = {"name": "area", "type": "double precision", "source_name": "AREA"}
_GRADUATED = {
    "style_config": {
        "mode": "graduated",
        "column": "AREA",
        "breaks": [10],
        "colors": ["#eeeeee", "#111111"],
        "target": "color",
    },
    "paint": {"fill-color": ["step", ["get", "AREA"], "#eeeeee", 10, "#111111"]},
}


@pytest.mark.parametrize(("area_type", "fits"), [("integer", True), ("text", False)])
async def test_a_graduated_layer_needs_a_number_where_it_moves(
    test_db_session, clean_tables, area_type, fits
):
    admin = await _admin(test_db_session)
    first = await _dataset_of(test_db_session, admin.id, columns=[*_COLUMNS, _AREA])
    second = await _dataset_of(
        test_db_session, admin.id, columns=[*_COLUMNS, {**_AREA, "type": area_type}]
    )
    graduated = _entry(
        "qgis-map-parks", _layer("parks", dataset_id=str(first), **_GRADUATED)
    )
    [created] = (await _apply(test_db_session, admin, graduated)).maps
    entry = _entry(
        "qgis-map-parks",
        _layer("parks", dataset_id=str(second), **_PARKS),
        styling="keep",
    )

    [result] = (await _apply(test_db_session, admin, entry)).maps

    [parks] = await _layers(test_db_session, created.map_id)
    assert parks.dataset_id == second
    if fits:
        assert _warnings(result) == []
        assert parks.style_config["mode"] == "graduated"
    else:
        [warning] = result.messages
        assert (warning.code, warning.layer) == ("A073", "parks")
        assert warning.message.endswith(": area (text) must be a number.")
        assert parks.style_config["mode"] == "categorical"


# A literal, so xdist workers collect the same parameters.
_WIDGET_ID = "3b0c8f4e-2d71-4a59-9e16-7f2a5c4d8b90"
_ACRES = {"name": "acres", "type": "numeric", "source_name": "ACRES"}
_INSPECTED = {"name": "inspected", "type": "date", "source_name": "INSPECTED"}
_HISTOGRAM = {"type": "histogram", "v": 1, "config": {"column": "acres", "bins": 10}}
_MONTHLY = {
    "type": "bar_chart",
    "v": 2,
    "config": {"mode": "date", "column": "inspected", "date_bucket": "month"},
}
_FILTERED = {
    **_HISTOGRAM,
    "v": 2,
    "filter": ["==", ["get", "inspected"], "2024-01-01"],
}


def _typed(column: dict, kind: str) -> dict:
    return {**column, "type": kind}


@pytest.mark.parametrize(
    ("widget", "columns", "version", "misfit"),
    [
        (_HISTOGRAM, [_ACRES, _INSPECTED], 1, None),
        (_HISTOGRAM, [_INSPECTED], 1, "it has no column acres"),
        (
            _HISTOGRAM,
            [_typed(_ACRES, "text"), _INSPECTED],
            1,
            "acres (text) must be a number",
        ),
        (_MONTHLY, [_ACRES, _INSPECTED], 1, None),
        (
            _MONTHLY,
            [_ACRES, _typed(_INSPECTED, "text")],
            1,
            "inspected (text) must be a date",
        ),
        (
            _FILTERED,
            [_ACRES, _typed(_INSPECTED, "integer")],
            1,
            "a dashboard widget's filter can't run on it",
        ),
        # A dashboard a newer server saved keeps its widgets through a move.
        (_HISTOGRAM, [_INSPECTED], 2, "it has no column acres"),
    ],
    ids=[
        "fits",
        "missing",
        "not-a-number",
        "date-fits",
        "not-a-date",
        "filter-misfit",
        "newer-dashboard",
    ],
)
async def test_a_column_only_a_dashboard_widget_reads_is_checked_too(
    test_db_session, clean_tables, widget, columns, version, misfit
):
    from sqlalchemy import update

    admin = await _admin(test_db_session)
    first = await _dataset_of(
        test_db_session, admin.id, columns=[*_COLUMNS, _ACRES, _INSPECTED]
    )
    second = await _dataset_of(test_db_session, admin.id, columns=[*_COLUMNS, *columns])
    [created] = (await _apply(test_db_session, admin, _publish(first))).maps
    parks, _ = await _layers(test_db_session, created.map_id)
    placed = {**widget, "id": _WIDGET_ID, "layer_id": str(parks.id)}
    await test_db_session.execute(
        update(Map)
        .where(Map.id == created.map_id)
        .values(dashboard_config={"version": version, "widgets": [placed]})
    )
    await test_db_session.commit()

    [result] = (
        await _apply(test_db_session, admin, _moving(second, first, "keep"))
    ).maps

    parks, _ = await _layers(test_db_session, created.map_id)
    assert parks.dataset_id == second
    widgets = (await _map_row(test_db_session, created.map_id)).dashboard_config[
        "widgets"
    ]
    if misfit is None:
        assert _warnings(result) == []
        # The widget fits the new dataset, so it stays on its layer.
        assert [w["layer_id"] for w in widgets] == [str(parks.id)]
    elif version == 1:
        [warning] = result.messages
        assert warning.message.endswith(". Its dashboard widgets are removed.")
        assert misfit in warning.message
        assert widgets == []
    else:
        [warning] = result.messages
        assert warning.message.endswith(f": {misfit}.")
        assert [w["layer_id"] for w in widgets] == [str(parks.id)]


@pytest.mark.parametrize(
    ("render_mode", "misfit"),
    [(None, None), ("heatmap", "it has no column acres")],
    ids=["stashed", "heatmap"],
)
async def test_a_heatmap_weight_counts_only_while_the_layer_is_a_heatmap(
    test_db_session, clean_tables, render_mode, misfit
):
    """The builder keeps a heatmap's weight column after the layer leaves
    heatmap mode; nothing draws with it then."""
    admin = await _admin(test_db_session)
    first = await _dataset_of(test_db_session, admin.id, columns=[*_COLUMNS, _ACRES])
    second = await _dataset_of(test_db_session, admin.id)
    style = {"builder": {"heatmap_weight_column": "ACRES"}}
    if render_mode is not None:
        style["render_mode"] = render_mode
    weighted = _entry(
        "qgis-map-parks",
        _layer("parks", dataset_id=str(first), style_config=style),
    )
    [created] = (await _apply(test_db_session, admin, weighted)).maps

    [result] = (
        await _apply(
            test_db_session,
            admin,
            _entry(
                "qgis-map-parks",
                _layer("parks", dataset_id=str(second), opacity=0.5),
                styling="keep",
            ),
        )
    ).maps

    [parks] = await _layers(test_db_session, created.map_id)
    assert parks.dataset_id == second
    if misfit is None:
        assert (_warnings(result), parks.opacity) == ([], 1.0)
    else:
        [warning] = result.messages
        assert warning.message.endswith(f": {misfit}.")
        assert parks.opacity == 0.5


async def _raster(session, owner_id, *, band_count, is_dem=False):
    from app.processing.raster.models import RasterAsset

    dataset = await create_dataset(
        session,
        created_by=owner_id,
        geometry_type=None,
        record_type="raster_dataset",
        source_format="geotiff",
        source_filename="ortho.tif",
    )
    session.add(
        RasterAsset(
            dataset_id=dataset.id,
            asset_uri=f"rasters/{dataset.id}/source.cog.tif",
            storage_backend="local",
            is_dem=is_dem,
            band_count=band_count,
        )
    )
    await session.commit()
    return dataset.id


@pytest.mark.parametrize(
    ("band_count", "is_dem", "misfit"),
    [
        (1, False, None),
        (3, False, "the colormap needs one band, and it has 3"),
        (1, True, "it is a DEM and the layer's earlier raster wasn't"),
    ],
    ids=["single-band", "three-band", "dem"],
)
async def test_a_raster_colormap_needs_one_band_where_it_moves(
    test_db_session, clean_tables, band_count, is_dem, misfit
):
    admin = await _admin(test_db_session)
    first = await _raster(test_db_session, admin.id, band_count=1)
    second = await _raster(
        test_db_session, admin.id, band_count=band_count, is_dem=is_dem
    )
    colormapped = _entry(
        "qgis-map-ortho",
        _layer("ortho", dataset_id=str(first), paint={"_colormap": "viridis"}),
    )
    [created] = (await _apply(test_db_session, admin, colormapped)).maps

    [result] = (
        await _apply(
            test_db_session,
            admin,
            _entry(
                "qgis-map-ortho",
                _layer("ortho", dataset_id=str(second), opacity=0.5),
                styling="keep",
            ),
        )
    ).maps

    [ortho] = await _layers(test_db_session, created.map_id)
    assert ortho.dataset_id == second
    if misfit is None:
        assert _warnings(result) == []
        assert ortho.style_config["builder"]["colormap"] == "viridis"
    else:
        [warning] = result.messages
        assert (warning.code, warning.layer) == ("A073", "ortho")
        assert warning.message.endswith(f": {misfit}.")
        assert "colormap" not in (ortho.style_config or {}).get("builder", {})


@pytest.mark.parametrize("mode", ["replace_if_unedited", "keep"])
async def test_a_kept_layer_on_a_dataset_the_publisher_cant_read_stays(
    client, test_db_session, admin_auth_header, clean_tables, mode
):
    """Its styling can't be judged without reading its dataset, so it stays
    there, and the map isn't judged on the dataset the manifest names."""
    admin = await _admin(test_db_session)
    editor, headers = await _person(client, test_db_session, admin_auth_header)
    admins = await _dataset(test_db_session, admin.id)
    own = await _dataset(test_db_session, editor.id)
    target = await _dataset(test_db_session, editor.id)
    first = _entry(
        "qgis-map-parks",
        _layer("parks", dataset_id=str(admins)),
        _layer("names", dataset_id=str(own)),
    )
    created = await _publish_then_edit(
        client, test_db_session, headers, editor, first, mode
    )
    await _hide(test_db_session, admins)
    entry = _entry(
        "qgis-map-parks",
        _layer("parks", dataset_id=str(target)),
        _layer("names", dataset_id=str(own)),
        styling=mode,
    )

    answers = [
        (await _apply(test_db_session, editor, entry, dry_run=dry_run)).maps[0]
        for dry_run in (True, False)
    ]

    for result in answers:
        assert (result.action, result.styling, _warnings(result)) == (
            "update",
            "kept",
            [],
        )
    assert {
        layer.manifest_key: layer.dataset_id
        for layer in await _layers(test_db_session, created.map_id)
    } == {"parks": admins, "names": own}


_MATCH = {"fill-color": ["match", ["get", "VALUE"], 1, "#ff0000", 2, "#00ff00", "#ccc"]}
_RADIUS = {
    "circle-radius": ["interpolate", ["linear"], ["get", "VALUE"], 0, 2, 100, 12]
}


def _value(kind: str) -> dict:
    return {"name": "value", "type": kind, "source_name": "VALUE"}


@pytest.mark.parametrize(
    ("paint", "geometry_type", "before", "after", "misfit"),
    [
        (_MATCH, "MultiPolygon", "integer", "text", "value: number before, text now"),
        (
            _RADIUS,
            "Point",
            "double precision",
            "text",
            "value: number before, text now",
        ),
        (_MATCH, "MultiPolygon", "integer", "bigint", None),
    ],
    ids=["match-labels", "interpolated-radius", "same-family"],
)
async def test_a_column_keeps_its_type_family_where_it_moves(
    test_db_session, clean_tables, paint, geometry_type, before, after, misfit
):
    """A match label or an interpolation reads the value by its type, so a
    number that becomes text changes what the layer draws."""
    admin = await _admin(test_db_session)
    first = await _dataset_of(
        test_db_session,
        admin.id,
        columns=[*_COLUMNS, _value(before)],
        geometry_type=geometry_type,
    )
    second = await _dataset_of(
        test_db_session,
        admin.id,
        columns=[*_COLUMNS, _value(after)],
        geometry_type=geometry_type,
    )
    styled = _entry(
        "qgis-map-parks", _layer("parks", dataset_id=str(first), paint=paint)
    )
    [created] = (await _apply(test_db_session, admin, styled)).maps

    [result] = (
        await _apply(
            test_db_session,
            admin,
            _entry(
                "qgis-map-parks",
                _layer("parks", dataset_id=str(second), opacity=0.5),
                styling="keep",
            ),
        )
    ).maps

    [parks] = await _layers(test_db_session, created.map_id)
    assert parks.dataset_id == second
    if misfit is None:
        assert (_warnings(result), parks.opacity) == ([], 1.0)
    else:
        [warning] = result.messages
        assert warning.message.endswith(f": {misfit}.")
        assert parks.opacity == 0.5


_SECRET_CATEGORY = "harbour-annex"
_SECRET = {
    "paint": {
        "fill-color": [
            "match",
            ["get", "PARK_TYPE"],
            _SECRET_CATEGORY,
            "#ff0000",
            "#cccccc",
        ]
    }
}


@pytest.mark.parametrize(
    ("was", "now", "widens"),
    [
        ("private", "public", True),
        ("internal", "public", True),
        ("private", "internal", True),
        ("public", "public", False),
        ("private", "private", False),
        # One narrowing move from each kind of dataset keeps its styling.
        ("public", "private", False),
        ("internal", "restricted", False),
        ("restricted", "private", False),
    ],
)
async def test_a_move_that_widens_who_reads_the_layer_takes_the_manifests_styling(
    client,
    test_db_session,
    admin_auth_header,
    clean_tables,
    monkeypatch,
    was,
    now,
    widens,
):
    """Styling can carry values only the readers of the dataset it was
    written for know, such as a category, so a move that lets anybody else
    read the layer doesn't carry it, even for the owner of both datasets."""
    # A known address, so the public map's share link adds no A074.
    monkeypatch.setattr(settings, "public_app_url", "https://geolens.test")
    admin = await _admin(test_db_session)
    first = await _dataset(test_db_session, admin.id, visibility=was)
    second = await _dataset(test_db_session, admin.id, visibility=now)
    styled = _entry("qgis-map-parks", _layer("parks", dataset_id=str(first), **_SECRET))
    [created] = (await _apply(test_db_session, admin, styled)).maps
    moving = _entry(
        "qgis-map-parks",
        _layer("parks", dataset_id=str(second), opacity=0.5),
        styling="keep",
        **({"visibility": "public"} if now == "public" else {}),
    )

    [checked] = (await _apply(test_db_session, admin, moving, dry_run=True)).maps
    [result] = (await _apply(test_db_session, admin, moving)).maps

    [parks] = await _layers(test_db_session, created.map_id)
    assert parks.dataset_id == second
    for answer in (checked, result):
        # A dry run that makes the map public also warns it reaches more people.
        layer_warnings = [m for m in answer.messages if m.code != "A057"]
        if widens:
            [warning] = layer_warnings
            assert (warning.code, warning.layer) == ("A073", "parks")
            assert "some who can read it can't read the dataset the layer left" in (
                warning.message
            )
        else:
            assert [m for m in layer_warnings if m.severity != "info"] == []
    assert (_SECRET_CATEGORY in str(parks.paint), parks.opacity) == (
        (False, 0.5) if widens else (True, 1.0)
    )
    if now == "public" and widens:
        anonymous = await client.get(f"/maps/{created.map_id}")
        assert anonymous.status_code == 200, anonymous.text
        assert _SECRET_CATEGORY not in anonymous.text


async def _group(session, *members) -> uuid.UUID:
    from app.modules.auth.models import Group, GroupMember

    group = Group(name=f"moves-{uuid.uuid4().hex[:8]}")
    session.add(group)
    await session.flush()
    for member in members:
        session.add(GroupMember(group_id=group.id, user_id=member))
    await session.commit()
    return group.id


async def _share(session, dataset_id, *group_ids) -> None:
    from app.modules.catalog.datasets.domain.models import DatasetGroupGrant

    for group_id in group_ids:
        session.add(DatasetGroupGrant(dataset_id=dataset_id, group_id=group_id))
    await session.commit()


@pytest.mark.parametrize(
    ("was", "now", "wider"),
    [
        (("private",), ("internal",), True),
        (("restricted", "g1"), ("internal",), True),
        (("restricted", "g1"), ("restricted", "g1", "g2"), True),
        (("private",), ("restricted",), True),
        (("internal",), ("public",), True),
        (("private",), ("private", "other-owner"), True),
        (("restricted", "g1", "g2"), ("restricted", "g1"), False),
        (("restricted", "g1"), ("private",), False),
        (("private",), ("private",), False),
        (("internal",), ("restricted", "g1"), False),
        (("public",), ("internal",), False),
        (("public", "draft"), ("internal",), True),
    ],
)
async def test_a_widening_move_is_judged_by_the_sharing_rules_not_todays_accounts(
    client,
    test_db_session,
    admin_auth_header,
    clean_tables,
    monkeypatch,
    was,
    now,
    wider,
):
    """With nobody yet in the gap, as on a server with only admins, a move
    the rules make wider is still wider: the next account or group member
    would read the old dataset's values."""
    from app.modules.catalog import authorization

    async def no_account_in_the_gap(db, pairs, **_):
        return [False] * len(pairs)

    admin = await _admin(test_db_session)
    other, _ = await _person(client, test_db_session, admin_auth_header)
    groups = {"g1": await _group(test_db_session), "g2": await _group(test_db_session)}

    async def made(kind, *rest):
        dataset = await create_dataset(
            test_db_session,
            created_by=other.id if "other-owner" in rest else admin.id,
            visibility=kind,
            record_status="draft" if "draft" in rest else "published",
        )
        await test_db_session.commit()
        await _share(
            test_db_session, dataset.id, *(groups[g] for g in rest if g in groups)
        )
        return dataset.id

    old, new = await made(*was), await made(*now)
    monkeypatch.setattr(authorization, "_audiences_exceeded", no_account_in_the_gap)

    assert await authorization.datasets_beyond_audience(
        test_db_session, [(new, old)]
    ) == [wider]


async def test_an_answer_the_audience_check_cant_give_counts_as_wider(
    test_db_session, clean_tables, monkeypatch
):
    """A dataset gone since the plan read it, or an authority whose audience
    answer can't be trusted, keeps the layer from carrying its styling."""
    from app.modules.catalog import authorization
    from app.platform.extensions import DefaultPermissionExtension

    class _WiderReads(DefaultPermissionExtension):
        def filter_visible(self, *args, **kwargs):
            return super().filter_visible(*args, **kwargs)

    admin = await _admin(test_db_session)
    old = await _dataset(test_db_session, admin.id, visibility="private")
    new = await _dataset(test_db_session, admin.id, visibility="private")
    gone = uuid.uuid4()
    pairs = [(new, old), (gone, old), (new, gone)]

    assert await authorization.datasets_beyond_audience(test_db_session, pairs) == [
        False,
        True,
        True,
    ]
    monkeypatch.setattr(authorization, "get_permission_extension", _WiderReads)
    assert await authorization.datasets_beyond_audience(
        test_db_session, [(new, old)]
    ) == [True]


@pytest.mark.parametrize("changed", [False, True])
async def test_a_sharing_change_between_the_audience_reads_counts_as_wider(
    test_db_session, clean_tables, monkeypatch, changed
):
    """Visibility and grants are read in separate statements, so a change
    committed between them could pair the old visibility with the new
    grants; a row that differs on the second read counts as wider."""
    import dataclasses

    from app.modules.catalog import authorization

    admin = await _admin(test_db_session)
    old = await _dataset(test_db_session, admin.id, visibility="private")
    new = await _dataset(test_db_session, admin.id, visibility="private")
    real = authorization._record_audience_queries
    reads = []

    async def made_public_meanwhile(db, ids):
        rows = await real(db, ids)
        reads.append(rows)
        if changed and len(reads) > 1:
            query, title = rows[new]
            rows = {
                **rows,
                new: (dataclasses.replace(query, visibility="public"), title),
            }
        return rows

    monkeypatch.setattr(
        authorization, "_record_audience_queries", made_public_meanwhile
    )

    assert await authorization.datasets_beyond_audience(
        test_db_session, [(new, old)]
    ) == [changed]
    assert len(reads) == 2


async def test_a_move_into_an_empty_group_is_wider_for_its_later_members(
    client, test_db_session, admin_auth_header, clean_tables
):
    """Restricted to g1, then to g1 and an empty g2: whoever joins g2 later
    reads the new dataset and not the old one."""
    admin = await _admin(test_db_session)
    member, _ = await _person(client, test_db_session, admin_auth_header)
    g1, g2 = await _group(test_db_session, member.id), await _group(test_db_session)
    first = await _dataset(test_db_session, admin.id, visibility="restricted")
    second = await _dataset(test_db_session, admin.id, visibility="restricted")
    await _share(test_db_session, first, g1)
    await _share(test_db_session, second, g1, g2)
    styled = _entry("qgis-map-parks", _layer("parks", dataset_id=str(first), **_SECRET))
    [created] = (await _apply(test_db_session, admin, styled)).maps

    [result] = (
        await _apply(
            test_db_session,
            admin,
            _entry(
                "qgis-map-parks",
                _layer("parks", dataset_id=str(second), opacity=0.5),
                styling="keep",
            ),
        )
    ).maps

    [warning] = result.messages
    assert (warning.code, warning.layer) == ("A073", "parks")
    [parks] = await _layers(test_db_session, created.map_id)
    assert (parks.dataset_id, _SECRET_CATEGORY in str(parks.paint)) == (second, False)


@pytest.mark.parametrize("styling", ["keep", "replace"])
@pytest.mark.parametrize(
    ("dashboard_version", "widget_version"),
    [(2, 2), (1, 99)],
    ids=["newer-dashboard", "unknown-widget"],
)
async def test_a_widening_move_refuses_a_map_whose_dashboard_it_cant_rewrite(
    client,
    test_db_session,
    admin_auth_header,
    clean_tables,
    monkeypatch,
    dashboard_version,
    widget_version,
    styling,
):
    """A dashboard a newer server saved, or a widget this server can't parse,
    stays through a move, since it can't tell which layer the widget names;
    the widget keeps the old dataset's values in its filter."""
    from sqlalchemy import update

    monkeypatch.setattr(settings, "public_app_url", "https://geolens.test")
    admin = await _admin(test_db_session)
    first = await _dataset(test_db_session, admin.id, visibility="internal")
    second = await _dataset(test_db_session, admin.id)
    [created] = (await _apply(test_db_session, admin, _publish(first))).maps
    parks, names = await _layers(test_db_session, created.map_id)
    widget = {
        **_HISTOGRAM,
        "v": widget_version,
        "id": _WIDGET_ID,
        "layer_id": str(parks.id),
        "filter": ["==", ["get", "park_type"], _SECRET_CATEGORY],
    }
    await test_db_session.execute(
        update(Map)
        .where(Map.id == created.map_id)
        .values(dashboard_config={"version": dashboard_version, "widgets": [widget]})
    )
    await test_db_session.commit()
    rows = await _rows(test_db_session, created.map_id)
    entry = _publish(second, styling=styling, visibility="public")

    [checked] = (await _apply(test_db_session, admin, entry, dry_run=True)).maps
    [result] = (await _apply(test_db_session, admin, entry)).maps

    for answer in (checked, result):
        assert answer.action == "error"
        refusals = [m for m in answer.messages if m.code == "A099"]
        assert sorted(m.layer for m in refusals) == ["names", "parks"]
        assert all(
            "dashboard holds widgets this server can't read" in m.message
            for m in refusals
        )
    assert await _rows(test_db_session, created.map_id) == rows
    anonymous = await client.get(f"/maps/{created.map_id}")
    assert _SECRET_CATEGORY not in anonymous.text


async def test_a_publish_key_cant_replace_the_thumbnail_a_move_cleared(
    client, test_db_session, admin_auth_header, clean_tables
):
    """The move clears the old images, which may show the dataset it left;
    a key that couldn't have replaced the thumbnail doesn't store one."""
    admin = await _admin(test_db_session)
    first = await _dataset(test_db_session, admin.id)
    second = await _dataset_of(test_db_session, admin.id)
    [created] = (await _apply(test_db_session, admin, _publish(first))).maps
    response = await client.put(
        f"/maps/{created.map_id}/thumbnail/",
        json={"data_uri": _PNG},
        headers=admin_auth_header,
    )
    assert response.status_code == 204, response.text
    _as_publish_key(test_db_session)

    [result] = (
        await _apply(
            test_db_session,
            admin,
            _publish(second, styling="replace", thumbnail=_PNG),
        )
    ).maps

    assert (result.action, _codes(result)) == ("update", [("A072", "warning", None)])
    assert "publish key" in result.messages[0].message
    assert (await _map_row(test_db_session, created.map_id)).thumbnail_uri is None


async def test_a_layer_hidden_in_geolens_stays_hidden_when_its_move_doesnt_fit(
    client, test_db_session, admin_auth_header, clean_tables
):
    admin = await _admin(test_db_session)
    first = await _dataset(test_db_session, admin.id)
    points = await _dataset_of(test_db_session, admin.id, geometry_type="Point")
    [created] = (await _apply(test_db_session, admin, _publish(first))).maps
    parks, _ = await _layers(test_db_session, created.map_id)
    await _patch_layers(
        client,
        admin_auth_header,
        created.map_id,
        {"updated": [{"id": str(parks.id), "visible": False}]},
    )

    [result] = (
        await _apply(
            test_db_session, admin, _moving(points, first, "replace_if_unedited")
        )
    ).maps

    assert sorted(m.code for m in result.messages) == ["A070", "A073"]
    parks, _ = await _layers(test_db_session, created.map_id)
    assert (parks.dataset_id, parks.opacity, parks.visible) == (points, 0.5, False)


async def test_a_failed_image_check_leaves_the_next_map_free_to_apply(
    client, test_db_session, admin_auth_header, clean_tables, monkeypatch
):
    """The post-commit check of the cleared images runs on the session the
    next map of the request uses, so a failed statement there can't leave
    that session's transaction aborted."""
    from sqlalchemy import text

    from app.modules.catalog.maps import service_crud

    async def aborts(session, _map_id):
        await session.execute(text("SELECT 1 / 0"))

    admin = await _admin(test_db_session)
    first = await _dataset(test_db_session, admin.id)
    second = await _dataset_of(test_db_session, admin.id)
    [created] = (await _apply(test_db_session, admin, _publish(first))).maps
    response = await client.put(
        f"/maps/{created.map_id}/thumbnail/",
        json={"data_uri": _PNG},
        headers=admin_auth_header,
    )
    assert response.status_code == 204, response.text
    monkeypatch.setattr(service_crud, "_live_map_asset_keys", aborts)
    trails = _entry("qgis-map-trails", _layer("trails", dataset_id=str(first)))

    [moved, added] = (
        await _apply(test_db_session, admin, _moving(second, first, "keep"), trails)
    ).maps

    assert (moved.action, added.action) == ("update", "create")
    assert added.messages == []


async def test_a_failed_image_cleanup_after_the_commit_still_reports_the_publish(
    client, test_db_session, admin_auth_header, clean_tables, monkeypatch
):
    async def fails(*_args, **_kwargs):
        raise RuntimeError("storage is down")

    admin = await _admin(test_db_session)
    first = await _dataset(test_db_session, admin.id)
    second = await _dataset_of(test_db_session, admin.id)
    [created] = (await _apply(test_db_session, admin, _publish(first))).maps
    monkeypatch.setattr(manifest_apply, "discard_map_asset_objects", fails)

    [result] = (
        await _apply(test_db_session, admin, _moving(second, first, "keep"))
    ).maps

    assert (result.action, _warnings(result)) == ("update", [])
    parks, _ = await _layers(test_db_session, created.map_id)
    assert parks.dataset_id == second


_ZONE = {"name": "zone", "type": "integer", "source_name": "ZONE"}


@pytest.mark.parametrize(("value", "fits"), [(12, True), (32768, False)])
async def test_a_layer_filter_that_stops_running_where_it_moves_doesnt_fit(
    test_db_session, clean_tables, value, fits
):
    """The viewer drops a filter it can't send for the column's type, so the
    layer and its widgets would read every feature on the new dataset."""
    admin = await _admin(test_db_session)
    first = await _dataset_of(test_db_session, admin.id, columns=[*_COLUMNS, _ZONE])
    second = await _dataset_of(
        test_db_session, admin.id, columns=[*_COLUMNS, _typed(_ZONE, "smallint")]
    )
    zone_filter = ["==", ["get", "zone"], value]
    filtered = _entry(
        "qgis-map-parks", _layer("parks", dataset_id=str(first), filter=zone_filter)
    )
    [created] = (await _apply(test_db_session, admin, filtered)).maps

    [result] = (
        await _apply(
            test_db_session,
            admin,
            _entry(
                "qgis-map-parks",
                _layer("parks", dataset_id=str(second), opacity=0.5),
                styling="keep",
            ),
        )
    ).maps

    [parks] = await _layers(test_db_session, created.map_id)
    assert parks.dataset_id == second
    if fits:
        assert (_warnings(result), parks.filter) == ([], zone_filter)
    else:
        [warning] = result.messages
        assert warning.message.endswith(": the layer's filter can't run on it.")
        assert (parks.filter, parks.opacity) == (None, 0.5)


# A symbol that picks its icon by a column's value.
_CATEGORY_ICONS = {
    "iconImage": "marker",
    "categoryColumn": "ACRES",
    "categories": [{"value": "10", "icon": "star"}],
}
_CIRCLE_ACRES = {"circle-color": ["step", ["get", "ACRES"], "#eeeeee", 10, "#111111"]}


@pytest.mark.parametrize(
    ("fields", "misfit"),
    [
        (
            {"style_config": {"render_mode": "symbol"}, "paint": _CIRCLE_ACRES},
            None,
        ),
        (
            {
                "style_config": {
                    "render_mode": "symbol",
                    "mode": "graduated",
                    "column": "ACRES",
                    "breaks": [10],
                    "colors": ["#eeeeee", "#111111"],
                    "target": "color",
                },
                "paint": _CIRCLE_ACRES,
            },
            None,
        ),
        (
            {
                "style_config": {"render_mode": "heatmap"},
                "label_config": {"column": "ACRES"},
            },
            None,
        ),
        (
            {
                "style_config": {
                    "render_mode": "heatmap",
                    "mode": "graduated",
                    "column": "ACRES",
                    "breaks": [10],
                    "colors": ["#eeeeee", "#111111"],
                    "target": "color",
                },
            },
            None,
        ),
        (
            {
                "style_config": {"render_mode": "heatmap"},
                "paint": {"heatmap-weight": ["get", "ACRES"]},
            },
            "it has no column acres",
        ),
        (
            {
                "style_config": {
                    "render_mode": "heatmap",
                    "symbol": _CATEGORY_ICONS,
                },
            },
            None,
        ),
        (
            {
                "style_config": {
                    "render_mode": "cluster",
                    "builder": {"symbol": _CATEGORY_ICONS},
                },
            },
            None,
        ),
        (
            {
                "style_config": {
                    "render_mode": "symbol",
                    "symbol": _CATEGORY_ICONS,
                },
            },
            "it has no column acres",
        ),
        ({"paint": _CIRCLE_ACRES}, "it has no column acres"),
        ({"popup_config": {"enabled": False, "visible_fields": ["acres"]}}, None),
        (
            {"popup_config": {"enabled": True, "visible_fields": ["acres"]}},
            "it has no column acres",
        ),
    ],
    ids=[
        "symbol",
        "symbol-classification",
        "heatmap-labels",
        "heatmap-classification",
        "heatmap-paint",
        "heatmap-symbol-settings",
        "cluster-symbol-stash",
        "symbol-category",
        "circle",
        "popup-off",
        "popup-on",
    ],
)
async def test_styling_nothing_draws_with_isnt_judged_where_the_layer_moves(
    test_db_session, clean_tables, fields, misfit
):
    """A symbol layer keeps its circle paint and classification, a heatmap
    its classification and labels, any other mode its symbol settings, and a
    disabled popup its fields, only to restore them later; none of them reads
    the dataset."""
    admin = await _admin(test_db_session)
    first = await _dataset_of(
        test_db_session, admin.id, columns=[*_COLUMNS, _ACRES], geometry_type="Point"
    )
    second = await _dataset_of(test_db_session, admin.id, geometry_type="Point")
    styled = _entry("qgis-map-parks", _layer("parks", dataset_id=str(first), **fields))
    [created] = (await _apply(test_db_session, admin, styled)).maps

    [result] = (
        await _apply(
            test_db_session,
            admin,
            _entry(
                "qgis-map-parks",
                _layer("parks", dataset_id=str(second), opacity=0.5),
                styling="keep",
            ),
        )
    ).maps

    [parks] = await _layers(test_db_session, created.map_id)
    assert parks.dataset_id == second
    if misfit is None:
        assert (_warnings(result), parks.opacity) == ([], 1.0)
    else:
        [warning] = result.messages
        assert warning.message.endswith(f": {misfit}.")
        assert parks.opacity == 0.5


@pytest.mark.parametrize(
    ("was_tiles", "now_tiles", "popup", "misfit"),
    [
        (None, None, None, None),
        (None, ["area"], None, None),
        (None, [], None, "its tiles leave out area"),
        (None, ["park_type"], None, "its tiles leave out area"),
        ([], [], None, None),
        (None, ["area"], ["park_name"], "its tiles leave out park_name"),
        (None, ["area"], ["park_name", "off"], None),
    ],
    ids=[
        "default",
        "listed",
        "none",
        "left-out",
        "left-out-before",
        "popup-field",
        "popup-off",
    ],
)
async def test_a_column_the_layer_draws_with_must_be_in_the_new_tiles(
    test_db_session, clean_tables, was_tiles, now_tiles, popup, misfit
):
    """A dataset's tile allowlist holds back every other column, even one
    the styling asks for; the viewer builds a popup from tile properties,
    and a disabled popup reads nothing."""
    from sqlalchemy import update

    from app.modules.catalog.datasets.domain.models import Dataset

    admin = await _admin(test_db_session)
    first = await _dataset_of(test_db_session, admin.id, columns=[*_COLUMNS, _AREA])
    second = await _dataset_of(test_db_session, admin.id, columns=[*_COLUMNS, _AREA])
    for dataset_id, tiles in ((first, was_tiles), (second, now_tiles)):
        await test_db_session.execute(
            update(Dataset).where(Dataset.id == dataset_id).values(tile_columns=tiles)
        )
    await test_db_session.commit()
    popup_config = (
        {
            "popup_config": {
                "enabled": "off" not in popup,
                "visible_fields": [name for name in popup if name != "off"],
            }
        }
        if popup
        else {}
    )
    graduated = _entry(
        "qgis-map-parks",
        _layer("parks", dataset_id=str(first), **_GRADUATED, **popup_config),
    )
    [created] = (await _apply(test_db_session, admin, graduated)).maps

    [result] = (
        await _apply(
            test_db_session,
            admin,
            _entry(
                "qgis-map-parks",
                _layer("parks", dataset_id=str(second), opacity=0.5),
                styling="keep",
            ),
        )
    ).maps

    [parks] = await _layers(test_db_session, created.map_id)
    assert parks.dataset_id == second
    if misfit is None:
        assert (_warnings(result), parks.opacity) == ([], 1.0)
    else:
        [warning] = result.messages
        assert warning.message.endswith(f": {misfit}.")
        assert parks.opacity == 0.5


async def test_a_move_clears_previews_that_may_show_the_dataset_it_left(
    client, test_db_session, admin_auth_header, clean_tables, monkeypatch
):
    """A private map whose layers move from a private dataset to a public one
    and go public must not serve its earlier images to anonymous readers."""
    # A known address, so the public map's share link adds no A074.
    monkeypatch.setattr(settings, "public_app_url", "https://geolens.test")
    admin = await _admin(test_db_session)
    private = await _dataset(test_db_session, admin.id, visibility="private")
    public = await _dataset(test_db_session, admin.id)
    [created] = (await _apply(test_db_session, admin, _publish(private))).maps
    for kind in ("thumbnail", "og-image"):
        response = await client.put(
            f"/maps/{created.map_id}/{kind}/",
            json={"data_uri": _PNG},
            headers=admin_auth_header,
        )
        assert response.status_code == 204, response.text

    [result] = (
        await _apply(
            test_db_session,
            admin,
            _publish(public, styling="keep", visibility="public"),
        )
    ).maps

    # Neither layer's styling, written for the private dataset, is carried.
    assert (result.action, result.visibility, sorted(_warnings(result))) == (
        "update",
        "public",
        [("A073", "warning", "names"), ("A073", "warning", "parks")],
    )
    stored = await _map_row(test_db_session, created.map_id)
    assert (stored.thumbnail_uri, stored.og_image_uri) == (None, None)
    for kind in ("thumbnail", "og-image"):
        anonymous = await client.get(f"/maps/{created.map_id}/{kind}/")
        assert anonymous.status_code == 404, kind


async def test_replace_moves_a_layer_with_the_manifests_styling_as_before(
    test_db_session, clean_tables
):
    admin = await _admin(test_db_session)
    first = await _dataset(test_db_session, admin.id)
    points = await _dataset_of(test_db_session, admin.id, geometry_type="Point")
    [created] = (await _apply(test_db_session, admin, _publish(first))).maps
    rows = await _rows(test_db_session, created.map_id)

    [result] = (
        await _apply(test_db_session, admin, _moving(points, first, "replace"))
    ).maps

    assert (result.styling, _codes(result)) == ("applied", [])
    assert await _rows(test_db_session, created.map_id) == [
        (*row[:3], points if row[1] == "parks" else first) for row in rows
    ]


async def test_a_moved_layer_retires_embed_links_scoped_to_its_old_dataset(
    test_db_session, clean_tables
):
    from app.modules.embed_tokens.models import EmbedToken

    admin = await _admin(test_db_session)
    first = await _dataset(test_db_session, admin.id)
    second = await _dataset(test_db_session, admin.id)
    [created] = (await _apply(test_db_session, admin, _publish(first))).maps
    token = EmbedToken(
        map_id=created.map_id,
        token_hash=hashlib.sha256(b"moved-layer-embed").hexdigest(),
        token_hint="moved",
        scoped_dataset_ids=[str(first)],
        expires_at=datetime.now(UTC) + timedelta(days=1),
        created_by=admin.id,
    )
    test_db_session.add(token)
    await test_db_session.commit()

    [result] = (
        await _apply(test_db_session, admin, _publish(second, styling="keep"))
    ).maps

    assert (result.styling, _warnings(result)) == ("kept", [])
    await test_db_session.refresh(token)
    assert token.is_active is False


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
    # A layer can't move to a dataset the caller can't read.
    assert "A073" not in {code for code, _, _ in _codes(hidden_applied)}


@pytest.mark.parametrize("hidden_side", ["stored", "manifest"])
async def test_replace_under_a_newer_dashboard_answers_alike_for_a_hidden_and_a_missing_dataset(
    client, test_db_session, admin_auth_header, clean_tables, hidden_side
):
    """A dataset the caller can't read answers as one that doesn't exist
    when the dashboard's widgets can't be removed, whichever side names it."""
    from sqlalchemy import update

    admin = await _admin(test_db_session)
    editor, _ = await _person(client, test_db_session, admin_auth_header)
    own = await _dataset(test_db_session, editor.id)
    admins = await _dataset(test_db_session, admin.id)
    stored = admins if hidden_side == "stored" else own
    first = _entry(
        "qgis-map-parks",
        _layer("parks", dataset_id=str(stored)),
        _layer("names", dataset_id=str(own)),
    )
    [created] = (await _apply(test_db_session, editor, first)).maps
    [parks] = [
        layer
        for layer in await _layers(test_db_session, created.map_id)
        if layer.manifest_key == "parks"
    ]
    widget = {**_HISTOGRAM, "v": 2, "id": _WIDGET_ID, "layer_id": str(parks.id)}
    await test_db_session.execute(
        update(Map)
        .where(Map.id == created.map_id)
        .values(dashboard_config={"version": 2, "widgets": [widget]})
    )
    await test_db_session.commit()
    await _hide(test_db_session, admins)
    answers = {}
    for name, parks_dataset in (("hidden", str(admins)), ("missing", _NO_SUCH_DATASET)):
        entry = _entry(
            "qgis-map-parks",
            _layer("parks", dataset_id=parks_dataset),
            _layer("names", dataset_id=str(own)),
            styling="replace",
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
    assert "A099" not in {code for code, _, _ in _codes(hidden_applied)}


async def test_replace_refuses_moving_a_layer_off_a_dataset_the_caller_cant_read(
    client, test_db_session, admin_auth_header, clean_tables
):
    """Under a dashboard whose widgets can't be removed, a move from a
    dataset the caller can't read to one it can widens, and a dry run says so."""
    from sqlalchemy import update

    admin = await _admin(test_db_session)
    editor, _ = await _person(client, test_db_session, admin_auth_header)
    own = await _dataset(test_db_session, editor.id)
    admins = await _dataset(test_db_session, admin.id)
    first = _entry(
        "qgis-map-parks",
        _layer("parks", dataset_id=str(admins)),
        _layer("names", dataset_id=str(own)),
    )
    [created] = (await _apply(test_db_session, editor, first)).maps
    [parks] = [
        layer
        for layer in await _layers(test_db_session, created.map_id)
        if layer.manifest_key == "parks"
    ]
    widget = {**_HISTOGRAM, "v": 2, "id": _WIDGET_ID, "layer_id": str(parks.id)}
    await test_db_session.execute(
        update(Map)
        .where(Map.id == created.map_id)
        .values(dashboard_config={"version": 2, "widgets": [widget]})
    )
    await test_db_session.commit()
    await _hide(test_db_session, admins)
    rows = await _rows(test_db_session, created.map_id)
    entry = _entry(
        "qgis-map-parks",
        _layer("parks", dataset_id=str(own)),
        _layer("names", dataset_id=str(own)),
        styling="replace",
    )

    [checked] = (await _apply(test_db_session, editor, entry, dry_run=True)).maps
    [result] = (await _apply(test_db_session, editor, entry)).maps

    for answer in (checked, result):
        assert answer.action == "error"
        assert [m.layer for m in answer.messages if m.code == "A099"] == ["parks"]
    assert _codes(checked) == _codes(result)
    assert await _rows(test_db_session, created.map_id) == rows


async def test_a_kept_layer_on_a_dataset_the_request_creates_isnt_judged_yet(
    test_db_session, clean_tables
):
    """A dataset the request creates has no geometry or columns to judge the
    layer's styling on until it is published."""
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

    assert _codes(result) == []


@pytest.mark.parametrize("held_by", ["this-request", "earlier-job"])
async def test_a_move_off_a_dataset_still_publishing_waits_for_its_job(
    test_db_session, clean_tables, held_by
):
    """A kept layer's move off a dataset a job is still replacing waits for the job."""
    from sqlalchemy import update

    from app.modules.catalog.datasets.domain.models import Dataset, Record
    from app.platform.jobs.models import IngestJob
    from app.processing.ingest.manifest_maps import run_manifest_maps
    from app.processing.ingest.manifest_schemas import ManifestApplyEntryResult
    from tests.test_manifest_maps_apply import _maps_only
    from tests.test_manifest_maps_dry_run import _local_dataset_entry

    admin = await _admin(test_db_session)
    columns = [*_COLUMNS, _ACRES, _INSPECTED]

    async def made(visibility):
        dataset = await create_dataset(
            test_db_session,
            created_by=admin.id,
            visibility=visibility,
            geometry_type="MultiPolygon",
            column_info=[dict(column) for column in columns],
        )
        await test_db_session.commit()
        return dataset.id

    source, target = await made("private"), await made("public")
    styled = _entry(
        "qgis-map-parks", _layer("parks", dataset_id=str(source), **_SECRET)
    )
    [created] = (await _apply(test_db_session, admin, styled)).maps
    [parks] = await _layers(test_db_session, created.map_id)
    parks_id = str(parks.id)
    widget = {**_HISTOGRAM, "id": _WIDGET_ID, "layer_id": parks_id}
    await test_db_session.execute(
        update(Map)
        .where(Map.id == created.map_id)
        .values(dashboard_config={"version": 1, "widgets": [widget]})
    )
    job = IngestJob(
        dataset_id=source,
        source_filename="parks.fgb",
        created_by=admin.id,
        status="pending",
        user_metadata={"manifest_key": "qgis-source"},
    )
    test_db_session.add(job)
    await test_db_session.commit()
    job_id = job.id
    moving = _entry(
        "qgis-map-parks", _layer("parks", dataset_id=str(target)), styling="keep"
    )
    rows = await _rows(test_db_session, created.map_id)

    if held_by == "this-request":
        request = _maps_only(
            moving,
            datasets=[{**_local_dataset_entry("qgis-source"), "visibility": "public"}],
        )
        results = [
            ManifestApplyEntryResult(
                dataset_key="qgis-source",
                action="update",
                message="m",
                dataset_id=source,
            )
        ]
        [waiting] = await run_manifest_maps(test_db_session, request, admin, results)
    else:
        [checked] = (await _apply(test_db_session, admin, moving, dry_run=True)).maps
        [waiting] = (await _apply(test_db_session, admin, moving)).maps
        assert _codes(checked) == _codes(waiting)

    assert (waiting.action, _codes(waiting)) == (
        "error",
        [("A052", "error", "parks")],
    )
    assert await _rows(test_db_session, created.map_id) == rows
    map_row = await _map_row(test_db_session, created.map_id)
    assert [w["layer_id"] for w in map_row.dashboard_config["widgets"]] == [parks_id]

    # The job publishes the dataset public, and the maps are sent again.
    record_id = select(Dataset.record_id).where(Dataset.id == source)
    await test_db_session.execute(
        update(Record)
        .where(Record.id == record_id.scalar_subquery())
        .values(visibility="public")
    )
    await test_db_session.execute(
        update(IngestJob)
        .where(IngestJob.id == job_id)
        .values(status="complete", completed_at=datetime.now(UTC))
    )
    await test_db_session.commit()
    [moved] = (await _apply(test_db_session, admin, moving)).maps

    assert (moved.action, _warnings(moved)) == ("update", [])
    [parks] = await _layers(test_db_session, created.map_id)
    assert (parks.dataset_id, _SECRET_CATEGORY in str(parks.paint)) == (target, True)
    map_row = await _map_row(test_db_session, created.map_id)
    assert [w["layer_id"] for w in map_row.dashboard_config["widgets"]] == [parks_id]


async def test_a_source_job_finishing_mid_check_is_judged_on_what_it_published(
    test_db_session, clean_tables
):
    """A source whose job finishes while the map is checked is judged on the columns it published."""
    from sqlalchemy import update

    import app.core.db as db_module
    from app.modules.catalog.datasets.domain.models import Dataset
    from app.platform.jobs.in_flight import datasets_with_jobs_in_flight
    from app.platform.jobs.models import IngestJob

    admin = await _admin(test_db_session)

    async def made(kind):
        dataset = await create_dataset(
            test_db_session,
            created_by=admin.id,
            visibility="public",
            geometry_type="MultiPolygon",
            column_info=[*_COLUMNS, _ACRES, _value(kind)],
        )
        await test_db_session.commit()
        return dataset.id

    source, target = await made("integer"), await made("text")
    styled = _entry(
        "qgis-map-parks", _layer("parks", dataset_id=str(source), paint=_MATCH)
    )
    [created] = (await _apply(test_db_session, admin, styled)).maps
    [parks] = await _layers(test_db_session, created.map_id)
    parks_id = str(parks.id)
    widget = {**_HISTOGRAM, "id": _WIDGET_ID, "layer_id": parks_id}
    await test_db_session.execute(
        update(Map)
        .where(Map.id == created.map_id)
        .values(dashboard_config={"version": 1, "widgets": [widget]})
    )
    job = IngestJob(
        dataset_id=source,
        source_filename="parks.fgb",
        created_by=admin.id,
        status="pending",
    )
    test_db_session.add(job)
    await test_db_session.commit()
    job_id = job.id
    published = []

    async def finishing_first(session, dataset_ids):
        ids = set(dataset_ids)
        if source in ids and not published:
            # The job replaces the source's value column with text and
            # commits, in between the apply's own reads.
            async with db_module.async_session() as other:
                await other.execute(
                    update(Dataset)
                    .where(Dataset.id == source)
                    .values(column_info=[*_COLUMNS, _ACRES, _value("text")])
                )
                await other.execute(
                    update(IngestJob)
                    .where(IngestJob.id == job_id)
                    .values(status="complete", completed_at=datetime.now(UTC))
                )
                await other.commit()
            published.append(source)
        return await datasets_with_jobs_in_flight(session, ids)

    moving = _entry(
        "qgis-map-parks",
        _layer("parks", dataset_id=str(target), opacity=0.5),
        styling="keep",
    )
    with patch.object(manifest_apply, "datasets_with_jobs_in_flight", finishing_first):
        [moved] = (await _apply(test_db_session, admin, moving)).maps

    assert published == [source]
    assert (moved.action, _warnings(moved)) == ("update", [])
    [parks] = await _layers(test_db_session, created.map_id)
    assert (parks.dataset_id, parks.opacity) == (target, 1.0)
    map_row = await _map_row(test_db_session, created.map_id)
    assert [w["layer_id"] for w in map_row.dashboard_config["widgets"]] == [parks_id]


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


async def test_a_moved_layer_is_judged_on_the_dataset_it_moves_to(
    client, test_db_session, admin_auth_header, clean_tables, monkeypatch
):
    from sqlalchemy import update

    from app.modules.catalog.datasets.domain.models import Dataset, Record

    # A known address, so the public map's share link adds no A074.
    monkeypatch.setattr(settings, "public_app_url", "https://geolens.test")
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
    # The dataset the layers leave is narrowed after the publish.
    record_id = select(Dataset.record_id).where(Dataset.id == kept_dataset)
    await test_db_session.execute(
        update(Record)
        .where(Record.id == record_id.scalar_subquery())
        .values(visibility="private")
    )
    await test_db_session.commit()

    [result] = (await _apply(test_db_session, admin, _publish(named_now))).maps

    # The layers leave a private dataset for a public one, so their styling
    # isn't carried.
    assert sorted(_codes(result)) == [
        ("A070", "info", None),
        ("A073", "warning", "names"),
        ("A073", "warning", "parks"),
    ]
    assert (result.action, result.visibility) == ("update", "public")
    assert {
        layer.dataset_id for layer in await _layers(test_db_session, created.map_id)
    } == {named_now}


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
        # No earlier publish's block was there to remove.
        assert "removed" not in result.messages[0].message
        assert "kept as they were" in result.messages[0].message
    assert (await _map_row(test_db_session, created.map_id)).notes == full


async def test_full_notes_drop_an_earlier_block_and_keep_the_users_text(
    test_db_session, clean_tables
):
    """With no room for the new block, an earlier publish's block doesn't
    stay behind as a stale one; the user's text is untouched."""
    from sqlalchemy import update

    admin = await _admin(test_db_session)
    dataset_id = await _dataset(test_db_session, admin.id)
    entry = _publish(dataset_id, loss_report=_LOSS)
    [created] = (await _apply(test_db_session, admin, entry)).maps
    block = (await _map_row(test_db_session, created.map_id)).notes.split("\n---\n")[0]
    user = "u" * (NOTES_LIMIT - 10)
    await test_db_session.execute(
        update(Map)
        .where(Map.id == created.map_id)
        .values(notes=f"{block}\n---\n{user}")
    )
    await test_db_session.commit()

    [result] = (await _apply(test_db_session, admin, entry)).maps

    assert _codes(result) == [("A071", "info", None)]
    assert "earlier publish's notes at the top were removed" in (
        result.messages[0].message
    )
    assert (await _map_row(test_db_session, created.map_id)).notes == user


async def test_a_kept_layer_moving_to_a_non_public_dataset_refuses_a_public_map(
    client, test_db_session, admin_auth_header, clean_tables, monkeypatch
):
    # A known address, so the public map's share link adds no A074.
    monkeypatch.setattr(settings, "public_app_url", "https://geolens.test")
    admin = await _admin(test_db_session)
    shown = await _dataset(test_db_session, admin.id)
    discarded = await _dataset(test_db_session, admin.id, visibility="private")
    [created] = (
        await _apply(test_db_session, admin, _publish(shown, visibility="public"))
    ).maps
    await _edit_paint_in_the_builder(
        client, admin_auth_header, test_db_session, created.map_id
    )

    [checked] = (
        await _apply(test_db_session, admin, _publish(discarded), dry_run=True)
    ).maps
    [result] = (await _apply(test_db_session, admin, _publish(discarded))).maps

    for answer in (checked, result):
        assert answer.action == "error"
        assert _codes(answer) == [("A070", "info", None), ("A020", "error", None)]
    assert {
        layer.dataset_id for layer in await _layers(test_db_session, created.map_id)
    } == {shown}


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


async def test_an_older_publishes_block_is_recognised_among_many_recorded_ones(
    test_db_session, clean_tables
):
    from app.modules.catalog.maps.models import MapEditHistoryEvent

    admin = await _admin(test_db_session)
    dataset_id = await _dataset(test_db_session, admin.id)
    [created] = (
        await _apply(test_db_session, admin, _publish(dataset_id, loss_report=_LOSS))
    ).maps
    first_block = (await _map_row(test_db_session, created.map_id)).notes.split(
        "\n---\n"
    )[0]
    await _apply(test_db_session, admin, _publish(dataset_id))
    test_db_session.add_all(
        MapEditHistoryEvent(
            map_id=created.map_id,
            target_type="map",
            action="manifest.publish",
            summary="Published",
            details={"notes_digest": hashlib.sha256(str(n).encode()).hexdigest()},
        )
        for n in range(300)
    )
    map_row = await _map_row(test_db_session, created.map_id)
    map_row.notes = f"{first_block}\n---\nMine"
    await test_db_session.commit()

    await _apply(test_db_session, admin, _publish(dataset_id))

    notes = (await _map_row(test_db_session, created.map_id)).notes
    assert notes.count("Published from") == 1
    assert notes.endswith("\n---\nMine")


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


# ---------------------------------------------------------------------------
# A full layer save
# ---------------------------------------------------------------------------

_SAVED_LAYER_FIELDS = (
    "dataset_id",
    "sort_order",
    "visible",
    "opacity",
    "paint",
    "layout",
    "display_name",
    "filter",
    "label_config",
    "popup_config",
    "style_config",
    "layer_type",
    "show_in_legend",
)


def _as_saved(layer) -> dict:
    return {
        "id": str(layer.id),
        **{f: getattr(layer, f) for f in _SAVED_LAYER_FIELDS},
        "dataset_id": str(layer.dataset_id),
    }


async def _full_layer_save(client, headers, session, map_id, change) -> None:
    """``PUT /maps/{id}`` with the stored layers written back, ``change``
    applied to the list first."""
    layers = [_as_saved(layer) for layer in await _layers(session, map_id)]
    response = await client.put(
        f"/maps/{map_id}", json={"layers": change(layers) or layers}, headers=headers
    )
    assert response.status_code == 200, response.text


async def _republish_after_full_save(
    client, session, headers, change, *, unkeyed: bool = False
):
    admin = await _admin(session)
    dataset_id = await _dataset(session, admin.id)
    [created] = (await _apply(session, admin, _publish(dataset_id))).maps
    if unkeyed:
        # A layer the publish never made, added in GeoLens.
        response = await client.patch(
            f"/maps/{created.map_id}/layers",
            json={"added": [{"dataset_id": str(dataset_id)}]},
            headers=headers,
        )
        assert response.status_code == 200, response.text
    await _full_layer_save(client, headers, session, created.map_id, change)
    [result] = (await _apply(session, admin, _publish(dataset_id))).maps
    return result


async def test_a_full_save_that_sends_the_layers_back_is_not_an_edit(
    client, test_db_session, admin_auth_header, clean_tables
):
    result = await _republish_after_full_save(
        client, test_db_session, admin_auth_header, lambda layers: None
    )

    assert (result.styling, _codes(result)) == ("applied", [])


async def test_a_full_save_that_changes_a_keyed_layers_paint_is_an_edit(
    client, test_db_session, admin_auth_header, clean_tables
):
    def change(layers):
        layers[0]["paint"] = {"fill-color": "#ff0000"}

    result = await _republish_after_full_save(
        client, test_db_session, admin_auth_header, change
    )

    assert (result.styling, _codes(result)) == ("kept", [("A070", "info", None)])


async def test_a_full_save_that_removes_a_keyed_layer_is_an_edit(
    client, test_db_session, admin_auth_header, clean_tables
):
    result = await _republish_after_full_save(
        client, test_db_session, admin_auth_header, lambda layers: layers[:1]
    )

    assert (result.styling, _codes(result)) == ("kept", [("A070", "info", None)])


async def test_a_full_save_that_adds_a_layer_without_a_key_is_not_an_edit(
    client, test_db_session, admin_auth_header, clean_tables
):
    def change(layers):
        return [*layers, {**layers[0], "id": None}]

    result = await _republish_after_full_save(
        client, test_db_session, admin_auth_header, change
    )

    assert (result.styling, _codes(result)) == ("applied", [])


async def test_a_full_save_that_changes_only_an_unkeyed_layer_is_not_an_edit(
    client, test_db_session, admin_auth_header, clean_tables
):
    def change(layers):
        layers[-1]["paint"] = {"fill-color": "#00ff00"}

    result = await _republish_after_full_save(
        client, test_db_session, admin_auth_header, change, unkeyed=True
    )

    assert (result.styling, _codes(result)) == ("applied", [])


async def test_a_full_save_recorded_without_the_detail_still_counts(
    client, test_db_session, admin_auth_header, clean_tables
):
    from app.modules.catalog.maps.service_history import record_map_history_event

    admin = await _admin(test_db_session)
    dataset_id = await _dataset(test_db_session, admin.id)
    [created] = (await _apply(test_db_session, admin, _publish(dataset_id))).maps
    await record_map_history_event(
        test_db_session,
        map_id=created.map_id,
        actor=admin,
        target_type="map",
        target_id=created.map_id,
        action="layer.replace",
        summary="Replaced map layers with 2 layer(s)",
        details={"layer_count": 2},
    )
    await test_db_session.commit()

    [result] = (await _apply(test_db_session, admin, _publish(dataset_id))).maps

    assert (result.styling, _codes(result)) == ("kept", [("A070", "info", None)])
