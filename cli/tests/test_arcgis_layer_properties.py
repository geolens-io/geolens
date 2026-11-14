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
            "layer Parcels: its time settings on opened, closed are not carried "
            "over; the fields arrive as ordinary columns",
        ),
        (
            {"time_fields": []},
            "layer Parcels: its time settings are not carried over; the fields "
            "arrive as ordinary columns",
        ),
        (
            {"subtype_field": "kind"},
            "layer Parcels: its subtypes are not carried over; field kind arrives "
            "as a plain column without the subtype names",
        ),
        (
            {"has_m": True},
            "layer Parcels: its M values are not carried over; the geometries "
            "arrive without them",
        ),
        (
            {"time_only_fields": ["opens_at"]},
            "layer Parcels: time-only field(s) opens_at are not carried over as "
            "times; they arrive as text",
        ),
        (
            {"timestamp_offset_fields": ["seen", "fixed"]},
            "layer Parcels: timestamp-offset field(s) seen, fixed are not carried "
            "over with their offsets; each arrives as the instant without its UTC "
            "offset",
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
        "layer Parcels: its M values are not carried over; the geometries arrive "
        "without them"
    ]
