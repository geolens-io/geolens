"""`geolens arcgis migrate`: web maps with no layer to carry, and map descriptions."""

# Imported fixtures are used as test arguments, which F811 reads as redefinition.
# ruff: noqa: F811

from __future__ import annotations

import secrets
from types import SimpleNamespace
from typing import Any

import pytest

from geolens_cli import arcgis_migrate as migrate
from geolens_cli import arcgis_migrate_webmaps as webmaps
from geolens_cli.arcgis_migrate_export import _map_link
from geolens_cli.arcgis_migrate_state import ItemState

from .arcgis_fake import B1, FakePortal, portal_routes
from .test_arcgis_migrate_layers import (  # noqa: F401  (fixtures)
    _migrate,
    _state,
    dataset_id,
    geolens,
    plan_file,
    quick,
)
from .test_arcgis_migrate_webmaps import (
    IMPORT,
    MAP_ID,
    _only_the_map,
    _response,
    _saved,
    _translated,
    _run,
    _sent,
    _services,
)

TILED = {
    "id": "base_0",
    "layerType": "ArcGISTiledMapServiceLayer",
    "url": "https://tiles.example.com/arcgis/rest/services/Base/MapServer",
}


@pytest.fixture(autouse=True)
def portal(monkeypatch):
    fake = FakePortal(portal_routes())
    monkeypatch.setattr(migrate, "build_opener", lambda: fake)
    return fake


def _server(geolens, version: str = "1.32.0") -> None:
    geolens.routes["GET /health"] = {
        "status": "ok",
        "version": version,
        "providers": {},
    }


def _nothing_to_carry(geolens, **extra) -> dict[str, Any]:
    """The dry run's answer when the translator keeps no layer."""
    response = {**_response(lost=1), "layers": [], **extra}
    geolens.routes[IMPORT] = lambda seen: (
        201,
        response if seen.json().get("dry_run") else _response(),
    )
    return response


def _creates(geolens) -> list[Any]:
    return [s for s in _sent(geolens) if not s.json().get("dry_run")]


def _summary(portal, snippet: str) -> None:
    item = portal.routes[f"content/items/{B1}"]
    portal.routes[f"content/items/{B1}"] = {**item, "snippet": snippet}


def test_a_web_map_with_no_layer_to_carry_is_skipped_without_a_map(
    runner, plan_file, geolens, portal
):
    _services(geolens)
    _nothing_to_carry(geolens)
    key = f"content/items/{B1}/data"
    portal.routes[key] = {**portal.routes[key], "operationalLayers": [TILED]}

    result, _ = _run(runner, plan_file)

    assert result.exit_code == 0, result.output
    assert _creates(geolens) == []
    entry = _state(plan_file)["items"][B1]
    assert entry["status"] == "skipped"
    assert entry["map_id"] is None
    assert any("ArcGISTiledMapServiceLayer" in n for n in entry["notes"])
    assert (plan_file.parent / entry["loss_report_path"]).is_file()


def test_a_translation_that_keeps_no_layer_skips_a_matched_web_map(
    runner, plan_file, geolens
):
    _services(geolens)
    _nothing_to_carry(geolens)

    result, _ = _run(runner, plan_file)

    assert result.exit_code == 0, result.output
    assert _creates(geolens) == []
    assert _state(plan_file)["items"][B1]["status"] == "skipped"


def test_a_rerun_creates_the_map_once_a_layer_can_be_carried(
    runner, plan_file, geolens
):
    _services(geolens)
    _nothing_to_carry(geolens)
    token = secrets.token_urlsafe(16)
    _only_the_map(plan_file)
    _migrate(runner, plan_file, "--token", token)
    entry = _state(plan_file)["items"][B1]
    assert entry["status"] == "skipped"
    first_report = plan_file.parent / entry["loss_report_path"]
    assert first_report.is_file()

    geolens.routes[IMPORT] = (201, _response())
    result, _ = _migrate(runner, plan_file, "--token", token)

    assert result.exit_code == 0, result.output
    assert len(_creates(geolens)) == 1
    entry = _state(plan_file)["items"][B1]
    assert entry["map_id"] == MAP_ID
    # The create lost nothing, so the skipped run's report is gone with its path.
    assert not first_report.exists()
    assert entry["loss_report_path"] is None


def test_the_items_summary_is_sent_as_the_description(
    runner, plan_file, geolens, portal
):
    _services(geolens)
    _server(geolens)
    _summary(portal, "<p>Tax parcels</p>")
    geolens.routes[IMPORT] = (201, _response())

    result, _ = _run(runner, plan_file)

    assert result.exit_code == 0, result.output
    [create] = _creates(geolens)
    assert create.json()["description"] == "Tax parcels"
    assert len([s for s in geolens.seen if s.method == "PUT"]) == 0


def test_a_server_without_description_support_gets_none_and_a_note(
    runner, plan_file, geolens, portal
):
    _services(geolens)
    _server(geolens, "1.31.0")
    _summary(portal, "Tax parcels")
    geolens.routes[IMPORT] = (201, _response())

    result, _ = _run(runner, plan_file)

    assert result.exit_code == 0, result.output
    [create] = _creates(geolens)
    assert "description" not in create.json()
    notes = _state(plan_file)["items"][B1]["notes"]
    assert any("needs GeoLens 1.32 or newer" in n for n in notes)


def test_a_summary_holding_the_runs_credential_is_not_sent(
    runner, plan_file, geolens, portal
):
    _services(geolens)
    _server(geolens)
    token = secrets.token_urlsafe(16)
    # The credential sits across the 2,000-character cut.
    _summary(portal, "x" * 1995 + token)
    geolens.routes[IMPORT] = (201, _response())

    result, _ = _migrate(runner, plan_file, "--only", B1, "--token", token)

    assert result.exit_code == 0, result.output
    [create] = _creates(geolens)
    assert "description" not in create.json()
    notes = _state(plan_file)["items"][B1]["notes"]
    assert any("holds this run's ArcGIS credential" in n for n in notes)


def test_an_empty_map_an_earlier_run_made_is_left_and_reported(
    runner, plan_file, geolens
):
    _services(geolens)
    response = _response()
    response["layer_ids"] = {}
    geolens.routes[IMPORT] = (201, response)
    token = secrets.token_urlsafe(16)
    _only_the_map(plan_file)
    _migrate(runner, plan_file, "--token", token)

    result, _ = _migrate(runner, plan_file, "--token", token)

    assert result.exit_code == 0, result.output
    entry = _state(plan_file)["items"][B1]
    assert entry["status"] == "done" and entry["map_id"] == MAP_ID
    assert webmaps._EMPTY_MAP_NOTE in entry["notes"]
    assert len(_creates(geolens)) == 1
    assert not [s for s in geolens.seen if s.method == "DELETE"]


def test_an_empty_map_that_gains_layers_loses_its_empty_note(
    runner, plan_file, geolens, portal
):
    _services(geolens)
    response = _response()
    response["layer_ids"] = {}
    geolens.routes[IMPORT] = lambda seen: (
        201,
        _translated(dataset_id("Parcels")) if seen.json().get("dry_run") else response,
    )
    geolens.routes["PUT /maps/" + MAP_ID] = lambda seen: _saved(seen.json())
    token = secrets.token_urlsafe(16)
    _only_the_map(plan_file)
    _migrate(runner, plan_file, "--token", token)
    listed = portal.routes[f"content/items/{B1}"]
    portal.routes[f"content/items/{B1}"] = {
        **listed,
        "modified": listed["modified"] + 60_000,
    }

    result, _ = _migrate(runner, plan_file, "--token", token)

    assert result.exit_code == 0, result.output
    assert [s for s in geolens.seen if s.method == "PUT"]
    assert webmaps._EMPTY_MAP_NOTE not in _state(plan_file)["items"][B1]["notes"]


def test_an_unreadable_item_is_told_apart_from_one_with_no_summary(
    runner, plan_file, geolens, portal
):
    _services(geolens)
    _server(geolens)
    geolens.routes[IMPORT] = (201, _response())
    portal.routes[f"content/items/{B1}"] = (503, {"error": {"code": 503}})

    result, _ = _run(runner, plan_file)

    assert result.exit_code == 0, result.output
    assert len(_creates(geolens)) == 1
    entry = _state(plan_file)["items"][B1]
    assert any("metadata could not be read" in n for n in entry["notes"])
    report = (plan_file.parent / "arcgis-migration-report.json").read_text()
    assert "metadata could not be read" in report


def test_a_note_survives_a_loss_report_write_that_failed(
    runner, plan_file, geolens, portal, monkeypatch
):
    _services(geolens)
    _server(geolens, "1.31.0")
    _summary(portal, "Tax parcels")
    geolens.routes[IMPORT] = (201, _response(lost=1))
    real = webmaps._report.write_private

    def broken(path, data):
        if webmaps.LOSS_DIRNAME in str(path):
            raise OSError(28, "No space left on device")
        real(path, data)

    monkeypatch.setattr(webmaps._report, "write_private", broken)
    first, _ = _run(runner, plan_file)
    monkeypatch.setattr(webmaps._report, "write_private", real)
    second, _ = _run(runner, plan_file)

    assert first.exit_code == 1 and second.exit_code == 0, second.output
    notes = _state(plan_file)["items"][B1]["notes"]
    assert len([n for n in notes if "needs GeoLens 1.32" in n]) == 1


def test_a_story_links_a_skipped_map_to_its_portal_item():
    ctx = SimpleNamespace(
        items={B1: ItemState(status="skipped")}, portal_root="https://example.com"
    )

    assert _map_link(ctx, B1) == f"https://example.com/home/item.html?id={B1}"
