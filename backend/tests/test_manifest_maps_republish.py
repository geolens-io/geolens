"""Manifest version 2 maps on republish: the styling policy, notes and thumbnail.

Requirements: the docker database must be running with migrations applied.
"""

from __future__ import annotations

import ast
import hashlib
from pathlib import Path

import pytest
from sqlalchemy import select

from app.modules.catalog.maps import manifest_republish
from app.modules.catalog.maps.manifest_republish import (
    NOTES_LIMIT,
    OTHER_HISTORY_ACTIONS,
    STYLING_EDIT_ACTIONS,
    managed_notes,
    styling_applies,
)
from app.modules.catalog.maps.models import Map
from app.modules.catalog.maps.schemas import MapUpdate
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


async def _builder_save(client, headers, session, map_id, **changes) -> None:
    """A metadata save as the builder sends it: every setting, changed or not."""
    map_obj = await _map_row(session, map_id)
    payload = {
        "name": map_obj.name,
        "description": map_obj.description,
        "notes": map_obj.notes,
        "basemap_style": map_obj.basemap_style,
        "show_basemap_labels": map_obj.show_basemap_labels,
        "basemap_config": map_obj.basemap_config,
        "terrain_config": map_obj.terrain_config,
        "center_lng": map_obj.center_lng,
        "center_lat": map_obj.center_lat,
        "zoom": map_obj.zoom,
        "bearing": map_obj.bearing,
        "pitch": map_obj.pitch,
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
        ({"basemap_style": "openfreemap-dark"}, "kept"),
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
    [created] = (await _apply(test_db_session, admin, _publish(dataset_id))).maps
    await _builder_save(
        client, admin_auth_header, test_db_session, created.map_id, **changes
    )

    [result] = (await _apply(test_db_session, admin, _publish(dataset_id))).maps

    assert result.styling == styling
    assert _codes(result) == ([("A070", "info", None)] if styling == "kept" else [])


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


# ---------------------------------------------------------------------------
# Notes
# ---------------------------------------------------------------------------


def test_the_notes_limit_is_the_maps():
    assert MapUpdate.model_fields["notes"].metadata[-1].max_length == NOTES_LIMIT


_BLOCK = "Published from old\nold: loss"
_WRITTEN = hashlib.sha256(_BLOCK.encode()).hexdigest()


def test_the_block_last_written_is_replaced_and_the_users_text_kept():
    existing = f"{_BLOCK}\n---\nMy notes\n---\nstill mine"

    notes = managed_notes(existing, ["Published from new", "a: b"], _WRITTEN)

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
    notes = managed_notes(existing, ["P"], written)

    assert notes.text == f"P\n---\n{existing}"


def test_a_block_saved_back_with_windows_line_endings_is_still_ours():
    existing = _BLOCK.replace("\n", "\r\n") + "\r\n---\r\nMine\r\n"

    assert managed_notes(existing, ["P"], _WRITTEN).text == "P\n---\nMine\r\n"


def test_a_block_the_builder_trimmed_is_still_ours():
    assert managed_notes(f"{_BLOCK}\n---", ["P"], _WRITTEN).text == "P\n---\n"


def test_a_long_loss_report_is_cut_and_the_users_text_kept_whole():
    user = "u" * 30_000
    lines = ["Published", *(f"layers[{i}]: kind (detail)" for i in range(5_000))]

    notes = managed_notes(f"{_BLOCK}\n---\n{user}", lines, _WRITTEN).text

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

    notes = managed_notes(user, [line, "a: loss"], None)

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
    assert _codes(bad) == [("A099", "warning", None)]
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
    assert _codes(second) == [("A099", "warning", None)]
    assert "publish key" in second.messages[0].message
    assert await test_db_session.scalar(select(Map.thumbnail_uri)) is not None


def test_the_thumbnail_goes_through_the_upload_service():
    source = Path(manifest_republish.__file__).read_text()
    assert 'store_map_image(session, map_id, data_uri, "thumbnail", user)' in source


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

    assert _codes(result) == [("A070", "info", None), ("A020", "error", None)]


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
    print("DEBUG", [(layer.manifest_key, layer.sort_order) for layer in stored])
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
        assert (result.action, _codes(result)) == ("update", [("A099", "info", None)])
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
    assert _codes(result) == [("A070", "info", None)]


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
