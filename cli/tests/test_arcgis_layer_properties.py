"""`geolens arcgis migrate`: a report follow-up for each layer property an
import doesn't carry."""

from __future__ import annotations

import json

import pytest

from . import test_arcgis_migrate_layers as layers
from .arcgis_fake import A2
from .test_arcgis_migrate_layers import FakeImport, _layer, _migrate
from .test_arcgis_migrate_refresh import PARCELS, FakeRefresh, _edit_plan, _edit_state

geolens = layers.geolens
quick = layers.quick
plan_file = layers.plan_file


def _follow_ups(runner, plan_file, geolens, **properties) -> list[str]:
    FakeImport(geolens, [_layer(0, "Parcels", **properties)])
    result, _ = _migrate(runner, plan_file, "--only", A2)
    assert result.exit_code == 0, result.output
    report = json.loads((plan_file.parent / "arcgis-migration-report.json").read_text())
    return [f["text"] for f in report["follow_ups"] if f["kind"] == "layer_properties"]


@pytest.mark.parametrize(
    ("properties", "expected"),
    [
        (
            {"time_fields": ["opened", "closed"]},
            "layer Parcels (layer 0): its time settings are not carried over; the fields "
            "arrive as ordinary columns (opened, closed)",
        ),
        (
            {"time_fields": []},
            "layer Parcels (layer 0): its time settings are not carried over; the fields "
            "arrive as ordinary columns",
        ),
        (
            {"subtype_field": "kind"},
            "layer Parcels (layer 0): its subtypes are not carried over; field kind arrives "
            "as a plain column without the type or subtype names",
        ),
        (
            {"has_m": True},
            "layer Parcels (layer 0): its M values are not carried over; the geometries "
            "arrive without them",
        ),
        (
            {"time_only_fields": ["opens_at"]},
            "layer Parcels (layer 0): time-only fields are not carried over as "
            "times; they may arrive as text (opens_at)",
        ),
        (
            {"timestamp_offset_fields": ["seen", "fixed"]},
            "layer Parcels (layer 0): timestamp-offset fields are not carried over with their "
            "offsets; each arrives as the instant without its UTC offset (seen, "
            "fixed)",
        ),
    ],
    ids=["time", "time_unnamed", "subtypes", "m_values", "time_only", "offset"],
)
def test_each_property_the_import_drops_is_a_follow_up(
    runner, plan_file, geolens, properties, expected
):
    assert _follow_ups(runner, plan_file, geolens, **properties) == [expected]


def test_a_layer_with_none_of_them_has_no_follow_up(runner, plan_file, geolens):
    found = _follow_ups(
        runner,
        plan_file,
        geolens,
        time_fields=None,
        subtype_field=None,
        has_m=False,
        time_only_fields=[],
        timestamp_offset_fields=[],
    )

    assert found == []


def test_a_resumed_import_keeps_the_follow_ups(runner, plan_file, geolens):
    service = FakeImport(geolens, [_layer(0, "Parcels", has_m=True)])
    service.job_errors["Parcels"] = "boom"
    _migrate(runner, plan_file, "--only", A2)
    del service.job_errors["Parcels"]

    result, _ = _migrate(runner, plan_file, "--only", A2)

    assert result.exit_code == 0, result.output
    notes = json.loads((plan_file.parent / "arcgis-migration-state.json").read_text())[
        "items"
    ][A2]["notes"]
    assert [n for n in notes if "M values" in n] == [
        "layer Parcels (layer 0): its M values are not carried over; the geometries arrive "
        "without them"
    ]


@pytest.mark.parametrize(
    ("key", "marker"),
    [
        ("time_only_fields", "time-only fields are not carried over"),
        ("timestamp_offset_fields", "timestamp-offset fields are not carried over"),
    ],
)
def test_many_long_field_names_keep_the_loss_marker_in_the_follow_ups(
    runner, plan_file, geolens, key, marker
):
    names = [f"a_very_long_field_name_{i:03d}_" + "x" * 40 for i in range(50)]

    [text] = _follow_ups(runner, plan_file, geolens, **{key: names})

    assert marker in text and "and 42 more" in text and len(text) < 2000
    assert names[0] in text and names[8] not in text


def test_the_note_reads_properties_an_older_sdk_keeps_as_extra_keys():
    from geolens_cli.arcgis_layer_properties import property_notes

    class OldLayerInfo:
        name = "Parcels"
        title = "Parcels"
        additional_properties = {
            "properties_read": True,
            "time_fields": ["opened"],
            "subtype_field": "kind",
            "has_m": True,
            "time_only_fields": ["opens_at"],
            "timestamp_offset_fields": ["seen"],
        }

    assert len(property_notes([OldLayerInfo()])) == 5


def test_a_retry_without_the_layer_metadata_keeps_the_notes_of_a_finished_layer(
    runner, plan_file, geolens
):
    service = FakeImport(
        geolens, [_layer(0, "Parcels", has_m=True), _layer(1, "Owners")]
    )
    service.job_errors["Owners"] = "boom"
    _migrate(runner, plan_file, "--only", A2)
    state_file = plan_file.parent / "arcgis-migration-state.json"
    entry = json.loads(state_file.read_text())["items"][A2]
    assert "M values" in entry["layer_notes"]["0"][0]
    # The retry's optional layer read fails, so the probe no longer says hasM.
    del service.job_errors["Owners"]
    service.layers[0].pop("has_m")

    result, _ = _migrate(runner, plan_file, "--only", A2)

    assert result.exit_code == 0, result.output
    entry = json.loads(state_file.read_text())["items"][A2]
    assert [n for n in entry["notes"] if "M values" in n] == [
        "layer Parcels (layer 0): its M values are not carried over; the "
        "geometries arrive without them"
    ]
    report = json.loads((plan_file.parent / "arcgis-migration-report.json").read_text())
    assert any(
        f["kind"] == "layer_properties" and "M values" in f["text"]
        for f in report["follow_ups"]
    )


def _report(plan_file):
    return json.loads((plan_file.parent / "arcgis-migration-report.json").read_text())


def test_a_committed_job_keeps_its_note_for_a_retry_without_the_metadata(
    runner, plan_file, geolens
):
    service = FakeImport(geolens, [_layer(0, "Parcels", has_m=True)])
    service.job_errors["Parcels"] = "the worker restarted"
    _migrate(runner, plan_file, "--only", A2)
    state = json.loads((plan_file.parent / "arcgis-migration-state.json").read_text())
    entry = state["items"][A2]
    assert entry["layer_jobs"] and "M values" in entry["layer_notes"]["0"][0]
    del service.job_errors["Parcels"]
    service.layers[0].pop("has_m")

    result, _ = _migrate(runner, plan_file, "--only", A2)

    assert result.exit_code == 0, result.output
    assert any(
        f["kind"] == "layer_properties" and "M values" in f["text"]
        for f in _report(plan_file)["follow_ups"]
    )


def test_a_failed_second_layer_does_not_hide_the_first_layers_losses(
    runner, plan_file, geolens
):
    _edit_plan(plan_file, (A2,))
    service = FakeImport(
        geolens,
        [
            _layer(0, "Parcels", has_m=True, has_attachments=False),
            _layer(1, "Owners", has_attachments=False),
        ],
    )
    service.job_errors["Owners"] = "boom"
    _migrate(runner, plan_file, "--only", A2)

    result, payload = _migrate(
        runner, plan_file, "--cutover", "--accept-unfinished-items"
    )

    assert result.exit_code == 1
    assert payload["cutover"]["refused"] == ["layer-property-loss"]
    assert any(
        f["kind"] == "layer_properties" and "M values" in f["text"]
        for f in _report(plan_file)["follow_ups"]
    )


def _notes(plan_file) -> list[str]:
    state = json.loads((plan_file.parent / "arcgis-migration-state.json").read_text())
    return [n for n in state["items"][A2]["notes"] if "could not be read" in n]


_UNREAD = (
    "layer Parcels (layer 0): its time, subtype, M-value and time field settings "
    "could not be read, so what is not carried over is unknown"
)


@pytest.mark.parametrize("flag", [False, None], ids=["unread", "older_server"])
def test_layer_properties_that_were_not_read_are_an_unknown_note_cutover_asks_about(
    runner, plan_file, geolens, flag
):
    _edit_plan(plan_file, (A2,))
    layer = _layer(0, "Parcels", has_attachments=False)
    if flag is None:
        del layer["properties_read"]
    else:
        layer["properties_read"] = flag
    FakeImport(geolens, [layer])

    result, payload = _migrate(runner, plan_file, "--cutover")

    assert result.exit_code == 1
    assert payload["cutover"]["refused"] == ["layer-property-loss"]
    assert _notes(plan_file) == [_UNREAD]


def test_a_read_layer_with_no_properties_has_no_note(runner, plan_file, geolens):
    FakeImport(geolens, [_layer(0, "Parcels", properties_read=True)])
    _migrate(runner, plan_file, "--only", A2)

    assert _notes(plan_file) == []


def test_a_rerun_that_reads_the_properties_replaces_the_unknown_note(
    runner, plan_file, geolens
):
    service = FakeImport(geolens, [_layer(0, "Parcels", properties_read=False)])
    _migrate(runner, plan_file, "--only", A2)
    _migrate(runner, plan_file, "--only", A2)
    assert _notes(plan_file) == [_UNREAD]
    service.layers[0].update(properties_read=True, has_m=True)
    FakeRefresh(geolens, service).allow(PARCELS)

    _migrate(runner, plan_file, "--only", A2)

    state = json.loads((plan_file.parent / "arcgis-migration-state.json").read_text())
    notes = state["items"][A2]["notes"]
    assert _notes(plan_file) == []
    assert [n for n in notes if "M values" in n]
    assert state["items"][A2]["layer_notes"]["0"] == [n for n in notes if "layer " in n]


def test_an_older_sdk_model_keeps_the_flag_as_an_extra_key():
    from geolens_cli.arcgis_layer_properties import property_notes

    class OldLayerInfo:
        name = "Parcels"
        title = "Parcels"
        layer_id = 0
        additional_properties = {"properties_read": True}

    assert property_notes([OldLayerInfo()]) == []


def _stored(plan_file) -> dict:
    state = json.loads((plan_file.parent / "arcgis-migration-state.json").read_text())
    return state["items"][A2]


@pytest.mark.parametrize("flag", [False, None, "absent"])
@pytest.mark.parametrize("title", ["Renamed", "R" * 2100], ids=["renamed", "truncated"])
def test_a_renamed_layer_read_later_drops_its_unknown_note(
    runner, plan_file, geolens, flag, title
):
    _edit_plan(plan_file, (A2,))
    layer = _layer(0, "Parcels", has_attachments=False)
    if flag == "absent":
        del layer["properties_read"]
    else:
        layer["properties_read"] = flag
    service = FakeImport(geolens, [layer])
    _migrate(runner, plan_file, "--only", A2)
    assert len(_notes(plan_file)) == 1
    service.layers[0].update(title=title, name=title, properties_read=True)
    FakeRefresh(geolens, service).allow(PARCELS)

    result, payload = _migrate(runner, plan_file, "--cutover")

    assert result.exit_code == 0, result.output
    assert payload["cutover"]["marked"] is True
    assert _notes(plan_file) == []
    assert _stored(plan_file)["layer_notes"]["0"] == []


def test_a_resumed_pass_saved_before_layer_notes_existed_is_unknown(
    runner, plan_file, geolens
):
    _edit_plan(plan_file, (A2,))
    FakeImport(geolens, [_layer(0, "Parcels", has_attachments=False)])
    _migrate(runner, plan_file, "--only", A2)
    _edit_state(plan_file, A2, layer_notes={}, notes=[], status="pending")

    result, payload = _migrate(runner, plan_file, "--cutover")

    assert result.exit_code == 1
    assert payload["cutover"]["refused"] == ["layer-property-loss"]
    assert _notes(plan_file) == [_UNREAD]
