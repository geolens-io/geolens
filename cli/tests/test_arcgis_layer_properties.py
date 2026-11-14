"""`geolens arcgis migrate`: a report follow-up for each layer property an
import doesn't carry."""

from __future__ import annotations

import json

import pytest

from . import test_arcgis_migrate_layers as layers
from .arcgis_fake import A2
from .test_arcgis_migrate_layers import FakeImport, _layer, _migrate

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
