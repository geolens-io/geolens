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


def _unsupported_web_map(portal) -> None:
    key = f"content/items/{B1}/data"
    portal.routes[key] = {**portal.routes[key], "operationalLayers": [TILED]}


def _creates(geolens) -> list[Any]:
    return [s for s in _sent(geolens) if not s.json().get("dry_run")]


def _descriptions(geolens) -> list[str]:
    return [
        body["description"]
        for s in geolens.seen
        if s.method == "PUT" and MAP_ID in s.url
        if "description" in (body := s.json())
    ]


def test_a_web_map_with_no_layer_to_carry_is_skipped_without_a_map(
    runner, plan_file, geolens, portal
):
    _services(geolens)
    _unsupported_web_map(portal)
    geolens.routes[IMPORT] = (201, _response(lost=1))

    result, _ = _run(runner, plan_file)

    assert result.exit_code == 0, result.output
    assert _creates(geolens) == []
    entry = _state(plan_file)["items"][B1]
    assert entry["status"] == "skipped"
    assert entry["map_id"] is None
    assert any("ArcGISTiledMapServiceLayer" in n for n in entry["notes"])
    assert (plan_file.parent / entry["loss_report_path"]).is_file()


def test_a_rerun_creates_the_map_once_a_layer_can_be_carried(
    runner, plan_file, geolens, portal, monkeypatch
):
    _services(geolens)
    _unsupported_web_map(portal)
    geolens.routes[IMPORT] = (201, _response())
    token = secrets.token_urlsafe(16)
    _only_the_map(plan_file)
    _migrate(runner, plan_file, "--token", token)
    assert _state(plan_file)["items"][B1]["status"] == "skipped"

    monkeypatch.setattr(
        webmaps, "match_datasets", lambda ctx, webmap: {"p": dataset_id("Parcels")}
    )
    result, _ = _migrate(runner, plan_file, "--token", token)

    assert result.exit_code == 0, result.output
    assert len(_creates(geolens)) == 1
    assert _state(plan_file)["items"][B1]["map_id"] == MAP_ID


def test_the_items_summary_becomes_the_description_once(
    runner, plan_file, geolens, portal, monkeypatch
):
    _services(geolens)
    item = portal.routes[f"content/items/{B1}"]
    portal.routes[f"content/items/{B1}"] = {**item, "snippet": "<p>Tax parcels</p>"}
    geolens.routes[IMPORT] = (201, _response())
    geolens.routes["PUT /maps/" + MAP_ID] = lambda seen: {
        **webmaps_map(),
        "updated_at": "2026-10-02T00:00:00Z",
    }
    monkeypatch.setattr(
        webmaps, "match_datasets", lambda ctx, webmap: {"p": dataset_id("Parcels")}
    )
    token = secrets.token_urlsafe(16)
    _only_the_map(plan_file)

    _migrate(runner, plan_file, "--token", token)
    portal.routes[f"content/items/{B1}"] = {
        **portal.routes[f"content/items/{B1}"],
        "snippet": "Changed in the portal",
    }
    _migrate(runner, plan_file, "--token", token)

    assert _descriptions(geolens) == ["Tax parcels"]
    snapshot = _state(plan_file)["items"][B1]["map_snapshot"]
    assert snapshot["updated_at"].startswith("2026-10-02")


def webmaps_map() -> dict[str, Any]:
    from .test_arcgis_migrate_webmaps import _map

    return _map()


def test_an_empty_map_an_earlier_run_made_is_left_and_reported(
    runner, plan_file, geolens, portal, monkeypatch
):
    _services(geolens)
    monkeypatch.setattr(
        webmaps, "match_datasets", lambda ctx, webmap: {"p": dataset_id("Parcels")}
    )
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
    assert len(_sent(geolens)) == 1
    assert not [s for s in geolens.seen if s.method == "DELETE"]


def test_a_story_links_a_skipped_map_to_its_portal_item():
    ctx = SimpleNamespace(
        items={B1: ItemState(status="skipped")}, portal_root="https://example.com"
    )

    assert _map_link(ctx, B1) == f"https://example.com/home/item.html?id={B1}"
