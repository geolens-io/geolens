"""`geolens arcgis migrate`: the import_map action against a fake GeoLens."""

from __future__ import annotations

import json
import secrets
from types import SimpleNamespace
from typing import Any

import pytest

from geolens_cli import arcgis_migrate as migrate
from geolens_cli import arcgis_migrate_webmaps as webmaps
from geolens_cli.arcgis_migrate_state import ItemState
from geolens_cli.arcgis_migrate_webmaps import match_datasets

from .arcgis_fake import A1, A2, B1, FakePortal, item_data_path, portal_routes
from .test_arcgis_migrate_layers import (  # noqa: F401  (fixtures)
    NOW,
    OPERATOR,
    FakeImport,
    _layer,
    _migrate,
    _problem,
    _state,
    _write_plan,
    dataset_id,
    geolens,
    plan_file,
    quick,
)

IMPORT = "POST /maps/import/arcgis-webmap/"
MAP_ID = "00000000-0000-0000-0002-000000000001"
LAYER_ID = "00000000-0000-0000-0003-00000000000{}"


def _map(owner: str = OPERATOR) -> dict[str, Any]:
    return {
        "id": MAP_ID,
        "name": "m",
        "description": None,
        "center_lng": 0.0,
        "center_lat": 0.0,
        "zoom": 1.0,
        "bearing": 0.0,
        "pitch": 0.0,
        "basemap_style": "light",
        "show_basemap_labels": True,
        "visibility": "private",
        "created_by": owner,
        "created_at": NOW,
        "updated_at": NOW,
        "layers": [],
        "layer_count": 0,
    }


def _response(*, lost: int = 0, unmatched: list[dict] | None = None) -> dict:
    items = [
        {"path": f"$.p{n}", "kind": "popup_expression", "detail": ""}
        for n in range(lost)
    ]
    return {
        "map": _map(),
        "layers": [],
        "layer_ids": {"parcels_0": LAYER_ID.format(1), "view_0": LAYER_ID.format(2)},
        "loss_report": {"items": items, "summary": {"popup_expression": lost}},
        "unmatched_layers": unmatched or [],
    }


def _services(geolens) -> None:
    FakeImport(geolens, [_layer(0, "Parcels"), _layer(1, "Owners", "Table")])
    geolens.routes["PATCH /maps/" + MAP_ID] = lambda seen: _map(
        seen.json().get("owner_id", OPERATOR)
    )


def _sent(geolens) -> list[Any]:
    return [s for s in geolens.seen if s.url.endswith("/maps/import/arcgis-webmap/")]


@pytest.fixture(autouse=True)
def portal(monkeypatch):
    fake = FakePortal(portal_routes())
    monkeypatch.setattr(migrate, "build_opener", lambda: fake)
    return fake


def _run(runner, plan_file, **kwargs):
    return _migrate(
        runner, plan_file, "--only", B1, "--token", secrets.token_urlsafe(16), **kwargs
    )


def test_a_web_map_is_imported_with_the_datasets_of_its_services(
    runner, plan_file, geolens
):
    _services(geolens)
    geolens.routes[IMPORT] = (201, _response(lost=2))

    result, _ = _run(runner, plan_file)

    assert result.exit_code == 0, result.output
    [request] = [s.json() for s in _sent(geolens)]
    assert request["dataset_matches"] == {
        "parcels_0": dataset_id("Parcels"),
        "view_0": dataset_id("Parcels"),
    }
    assert request["webmap"]["operationalLayers"][0]["id"] == "parcels_0"
    state = _state(plan_file)["items"][B1]
    assert state["status"] == "done"
    assert state["map_id"] == MAP_ID
    assert state["layer_ids"] == {
        "parcels_0": LAYER_ID.format(1),
        "view_0": LAYER_ID.format(2),
    }


def test_the_loss_report_is_saved_and_listed_in_the_run_report(
    runner, plan_file, geolens
):
    _services(geolens)
    unmatched = [
        {
            "layer_id": "roads_2",
            "title": "County roads",
            "url": "https://x",
            "reason": "no_match",
        }
    ]
    geolens.routes[IMPORT] = (201, _response(lost=2, unmatched=unmatched))

    result, _ = _run(runner, plan_file)

    assert result.exit_code == 0, result.output
    entry = _state(plan_file)["items"][B1]
    assert entry["loss_report_path"] == f"webmap-loss/{B1}.json"
    saved = json.loads((plan_file.parent / entry["loss_report_path"]).read_text())
    assert len(saved["loss_report"]["items"]) == 2
    assert saved["unmatched_layers"][0]["layer_id"] == "roads_2"
    assert any("County roads" in note for note in entry["notes"])
    report = json.loads((plan_file.parent / "arcgis-migration-report.json").read_text())
    assert entry["loss_report_path"] in report["loss_reports"]
    assert any(f["kind"] == "web_map_losses" for f in report["follow_ups"])


def test_a_stored_token_in_the_web_map_is_not_sent(runner, plan_file, geolens):
    _services(geolens)
    geolens.routes[IMPORT] = (201, _response())

    result, _ = _run(runner, plan_file)

    assert result.exit_code == 0, result.output
    assert "stored-in-web-map-not-a-real-token" not in _sent(geolens)[0].body.decode()


def test_a_rerun_keeps_the_map_it_made(runner, plan_file, geolens):
    _services(geolens)
    geolens.routes[IMPORT] = (201, _response())
    _run(runner, plan_file)

    result, _ = _run(runner, plan_file)

    assert result.exit_code == 0, result.output
    assert len(_sent(geolens)) == 1


def test_a_refused_import_fails_the_item(runner, plan_file, geolens):
    _services(geolens)
    geolens.routes[IMPORT] = (
        400,
        _problem(400, "A public map can't contain non-public datasets"),
    )

    result, _ = _run(runner, plan_file)

    assert result.exit_code == 1
    entry = _state(plan_file)["items"][B1]
    assert entry["status"] == "failed"
    assert "non-public" in entry["error"]
    assert entry["map_id"] is None


def _state_item(status: str = "done", **fields: Any) -> ItemState:
    return ItemState(status=status, **fields)


def test_layers_match_the_dataset_of_their_service_layer():
    ctx = SimpleNamespace(
        aliases={},
        items={
            "svc": _state_item(
                layer_datasets={"0": "ds-0", "1": "ds-1"}, dataset_ids=["ds-0", "ds-1"]
            ),
            "file": _state_item(
                layer_datasets={"file": "ds-file"}, dataset_ids=["ds-file"]
            ),
            "multi": _state_item(
                layer_datasets={"layer:A": "ds-a", "layer:B": "ds-b"},
                dataset_ids=["ds-a", "ds-b"],
            ),
            "partial": _state_item(
                layer_datasets={"layer:A": "ds-a"}, dataset_ids=["ds-a"]
            ),
            "sparse": _state_item(
                layer_datasets={"0": "ds-a", "3": "ds-d"}, dataset_ids=["ds-a", "ds-d"]
            ),
            "solo": _state_item(
                layer_datasets={"0": "ds-solo"}, dataset_ids=["ds-solo"]
            ),
            "many": _state_item(dataset_ids=["a", "b"]),
            "failed": _state_item("failed", dataset_ids=["ds-failed"]),
        },
    )
    base = "https://h/arcgis/rest/services/S/FeatureServer"
    webmap = {
        "operationalLayers": [
            {"id": "l1", "itemId": "svc", "url": f"{base}/1"},
            {"id": "l0", "itemId": "svc", "url": f"{base}/0?token=x"},
            {"id": "other_index", "itemId": "solo", "url": f"{base}/7"},
            {"id": "s3", "itemId": "sparse", "url": f"{base}/3"},
            {"id": "s1", "itemId": "sparse", "url": f"{base}/1"},
            {"id": "bad_url", "itemId": "svc", "url": "http://["},
            {"id": "f", "itemId": "file"},
            {"id": "file0", "itemId": "file", "url": f"{base}/0"},
            {"id": "file1", "itemId": "file", "url": f"{base}/1"},
            {"id": "multi0", "itemId": "multi", "url": f"{base}/0"},
            {"id": "partial0", "itemId": "partial", "url": f"{base}/0"},
            {"id": "ambiguous", "itemId": "many"},
            {"id": "failed", "itemId": "failed"},
            {"id": "unknown", "itemId": "other"},
            {"id": "noitem", "url": f"{base}/0"},
            {
                "id": "group",
                "layerType": "GroupLayer",
                "layers": [{"id": "inner", "itemId": "svc", "url": f"{base}/0"}],
            },
        ]
    }

    assert match_datasets(ctx, webmap) == {
        "l1": "ds-1",
        "l0": "ds-0",
        "s3": "ds-d",
        "f": "ds-file",
        "file0": "ds-file",
        "inner": "ds-0",
    }


def test_a_map_without_layers_is_not_imported_again_on_retry(
    runner, plan_file, geolens
):
    _services(geolens)
    response = _response()
    response["layer_ids"] = {}
    geolens.routes[IMPORT] = (201, response)
    patch = "PATCH /maps/" + MAP_ID
    ok = geolens.routes[patch]
    geolens.routes[patch] = (500, _problem(500, "boom"))

    first, _ = _run(runner, plan_file)
    geolens.routes[patch] = ok
    second, _ = _run(runner, plan_file)

    assert first.exit_code == 1 and second.exit_code == 0, second.output
    assert len(_sent(geolens)) == 1
    assert _state(plan_file)["items"][B1]["map_id"] == MAP_ID


def test_a_failed_loss_report_write_is_finished_on_retry(
    runner, plan_file, geolens, monkeypatch
):
    _services(geolens)
    unmatched = [
        {
            "layer_id": "roads_2",
            "title": "County roads",
            "url": "u",
            "reason": "no_match",
        }
    ]
    geolens.routes[IMPORT] = (201, _response(lost=1, unmatched=unmatched))
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
    assert len(_sent(geolens)) == 1
    entry = _state(plan_file)["items"][B1]
    assert entry["loss_report_path"] == f"webmap-loss/{B1}.json"
    assert entry["pending_loss"] is None
    assert any("County roads" in note for note in entry["notes"])
    assert (plan_file.parent / entry["loss_report_path"]).exists()


HILLSHADE = "https://services.arcgisonline.com/arcgis/rest/services/Elevation/World_Hillshade/MapServer"


def test_only_this_maps_basemap_entry_is_sent(runner, plan_file, geolens):
    _services(geolens)
    geolens.routes[IMPORT] = (201, _response())
    plan = json.loads(plan_file.read_text())
    plan["basemap_map"] = {
        f"https://tiles.example.org/{n}": "light" for n in range(150)
    }
    plan["basemap_map"][HILLSHADE] = "dark"
    plan_file.write_text(json.dumps(plan))

    result, _ = _run(runner, plan_file)

    assert result.exit_code == 0, result.output
    [request] = [s.json() for s in _sent(geolens)]
    assert request["basemap_map"] == {HILLSHADE: "dark"}


def test_a_saved_map_resumes_without_a_portal_credential(runner, plan_file, geolens):
    _services(geolens)
    geolens.routes[IMPORT] = (201, _response())
    patch = "PATCH /maps/" + MAP_ID
    ok = geolens.routes[patch]
    geolens.routes[patch] = (500, _problem(500, "boom"))
    first, _ = _run(runner, plan_file)
    geolens.routes[patch] = ok

    second, _ = _migrate(runner, plan_file, "--only", B1)

    assert first.exit_code == 1
    assert second.exit_code == 0, second.output
    assert len(_sent(geolens)) == 1


def test_a_refused_portal_token_stops_the_run(runner, plan_file, geolens, portal):
    _services(geolens)
    geolens.routes[IMPORT] = (201, _response())
    portal.routes[item_data_path(B1)] = (498, {"error": {"code": 498}})

    result, _ = _run(runner, plan_file)

    assert result.exit_code != 0
    entry = _state(plan_file)["items"][B1]
    assert entry["status"] == "failed"
    assert "Rerun with a fresh token" in entry["error"]
    assert _sent(geolens) == []


def test_a_basemap_url_with_a_query_finds_the_plans_entry(
    runner, plan_file, geolens, portal
):
    _services(geolens)
    geolens.routes[IMPORT] = (201, _response())
    data = json.loads(json.dumps(portal.routes[item_data_path(B1)]))
    layer = data["baseMap"]["baseMapLayers"][0]
    layer["url"] = HILLSHADE + "?cacheKey=abc"
    portal.routes[item_data_path(B1)] = data
    plan = json.loads(plan_file.read_text())
    plan["basemap_map"] = {HILLSHADE: "dark"}
    plan_file.write_text(json.dumps(plan))

    result, _ = _run(runner, plan_file)

    assert result.exit_code == 0, result.output
    [request] = [s.json() for s in _sent(geolens)]
    sent_url = request["webmap"]["baseMap"]["baseMapLayers"][0]["url"]
    assert request["basemap_map"] == {sent_url: "dark"}


def test_a_layer_of_a_skipped_view_is_not_guessed_from_its_parents_layers(
    runner, plan_file, geolens
):
    _services(geolens)
    geolens.routes[IMPORT] = (201, _response())
    plan = json.loads(plan_file.read_text())
    for item in plan["items"]:
        if item["id"] == A2:
            item["action"] = "skip"
            item["alias_of"] = A1
    plan_file.write_text(json.dumps(plan))

    result, _ = _run(runner, plan_file)

    assert result.exit_code == 0, result.output
    [request] = [s.json() for s in _sent(geolens)]
    assert "view_0" not in request["dataset_matches"]


def test_a_views_layer_index_is_never_read_as_the_parents():
    ctx = SimpleNamespace(
        aliases={"view": "parent", "solo_view": "solo"},
        items={
            "parent": _state_item(
                layer_datasets={"0": "ds-0", "3": "ds-3"}, dataset_ids=["ds-0", "ds-3"]
            ),
            "solo": _state_item(dataset_ids=["ds-solo"]),
        },
    )
    base = "https://h/arcgis/rest/services/V/FeatureServer"
    webmap = {
        "operationalLayers": [
            {"id": "indexed", "itemId": "view", "url": f"{base}/0"},
            {"id": "plain", "itemId": "solo_view"},
        ]
    }

    assert match_datasets(ctx, webmap) == {"plain": "ds-solo"}


def test_the_first_layer_of_a_duplicate_id_keeps_the_match():
    ctx = SimpleNamespace(
        aliases={},
        items={"svc": _state_item(layer_datasets={"0": "ds-0"}, dataset_ids=["ds-0"])},
    )
    base = "https://h/arcgis/rest/services/S/FeatureServer"
    webmap = {
        "operationalLayers": [
            {"id": "dup", "itemId": "other"},
            {"id": "dup", "itemId": "svc", "url": f"{base}/0"},
            {
                "id": "grp",
                "layerType": "GroupLayer",
                "layers": [{"id": "first", "itemId": "svc", "url": f"{base}/0"}],
            },
            {"id": "first", "itemId": "other"},
        ]
    }

    assert match_datasets(ctx, webmap) == {"first": "ds-0"}


def test_matches_stop_at_the_server_layer_cap():
    ctx = SimpleNamespace(
        aliases={},
        items={"svc": _state_item(dataset_ids=["ds"], layer_datasets={"file": "ds"})},
    )
    webmap = {
        "operationalLayers": [{"id": f"l{n}", "itemId": "svc"} for n in range(1500)]
    }

    matches = match_datasets(ctx, webmap)

    assert len(matches) == 200 and "l199" in matches and "l200" not in matches


def test_a_null_layer_does_not_end_its_group():
    ctx = SimpleNamespace(
        aliases={},
        items={"svc": _state_item(dataset_ids=["ds"])},
    )
    webmap = {
        "operationalLayers": [
            {
                "id": "g",
                "layerType": "GroupLayer",
                "layers": [None, {"id": "a", "itemId": "svc"}],
            },
            None,
            {"id": "b", "itemId": "svc"},
        ]
    }

    assert match_datasets(ctx, webmap) == {"a": "ds", "b": "ds"}
