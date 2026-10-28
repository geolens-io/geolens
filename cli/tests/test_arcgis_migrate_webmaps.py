"""`geolens arcgis migrate`: the import_map action against a fake GeoLens."""

# Imported fixtures are used as test arguments, which F811 reads as redefinition.
# ruff: noqa: F811

from __future__ import annotations

import json
import secrets
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from geolens_cli import arcgis_migrate as migrate
from geolens_cli import arcgis_migrate_webmaps as webmaps
from geolens_cli.arcgis_migrate_state import ItemState
from geolens_cli.arcgis_migrate_webmaps import _translatable, match_datasets

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
    geolens.routes["GET /maps/" + MAP_ID] = lambda seen: {
        **_map(),
        # The map keeps the visibility its import asked for.
        "visibility": ([s.json() for s in _sent(geolens)] or [{}])[-1].get(
            "visibility", "private"
        ),
    }


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
            {
                "layerType": "FeatureLayer",
                "id": "l1",
                "itemId": "svc",
                "url": f"{base}/1",
            },
            {
                "layerType": "FeatureLayer",
                "id": "l0",
                "itemId": "svc",
                "url": f"{base}/0?token=x",
            },
            {
                "layerType": "FeatureLayer",
                "id": "other_index",
                "itemId": "solo",
                "url": f"{base}/7",
            },
            {
                "layerType": "FeatureLayer",
                "id": "s3",
                "itemId": "sparse",
                "url": f"{base}/3",
            },
            {
                "layerType": "FeatureLayer",
                "id": "s1",
                "itemId": "sparse",
                "url": f"{base}/1",
            },
            {
                "layerType": "FeatureLayer",
                "id": "bad_url",
                "itemId": "svc",
                "url": "http://[",
            },
            {"layerType": "FeatureLayer", "id": "f", "itemId": "file"},
            {
                "layerType": "FeatureLayer",
                "id": "file0",
                "itemId": "file",
                "url": f"{base}/0",
            },
            {
                "layerType": "FeatureLayer",
                "id": "file1",
                "itemId": "file",
                "url": f"{base}/1",
            },
            {
                "layerType": "FeatureLayer",
                "id": "multi0",
                "itemId": "multi",
                "url": f"{base}/0",
            },
            {
                "layerType": "FeatureLayer",
                "id": "partial0",
                "itemId": "partial",
                "url": f"{base}/0",
            },
            {"layerType": "FeatureLayer", "id": "ambiguous", "itemId": "many"},
            {"layerType": "FeatureLayer", "id": "failed", "itemId": "failed"},
            {"layerType": "FeatureLayer", "id": "unknown", "itemId": "other"},
            {"layerType": "FeatureLayer", "id": "noitem", "url": f"{base}/0"},
            {
                "id": "group",
                "layerType": "GroupLayer",
                "layers": [
                    {
                        "layerType": "FeatureLayer",
                        "id": "inner",
                        "itemId": "svc",
                        "url": f"{base}/0",
                    }
                ],
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
            {
                "layerType": "FeatureLayer",
                "id": "indexed",
                "itemId": "view",
                "url": f"{base}/0",
            },
            {"layerType": "FeatureLayer", "id": "plain", "itemId": "solo_view"},
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
            {"layerType": "FeatureLayer", "id": "dup", "itemId": "other"},
            {
                "layerType": "FeatureLayer",
                "id": "dup",
                "itemId": "svc",
                "url": f"{base}/0",
            },
            {
                "id": "grp",
                "layerType": "GroupLayer",
                "layers": [
                    {
                        "layerType": "FeatureLayer",
                        "id": "first",
                        "itemId": "svc",
                        "url": f"{base}/0",
                    }
                ],
            },
            {"layerType": "FeatureLayer", "id": "first", "itemId": "other"},
        ]
    }

    assert match_datasets(ctx, webmap) == {"first": "ds-0"}


def test_matches_are_capped_at_the_request_limit_not_the_map_limit():
    ctx = SimpleNamespace(
        aliases={},
        items={"svc": _state_item(dataset_ids=["ds"], layer_datasets={"file": "ds"})},
    )
    webmap = {
        "operationalLayers": [
            {"layerType": "FeatureLayer", "id": f"l{n}", "itemId": "svc"}
            for n in range(1500)
        ]
    }

    matches = match_datasets(ctx, webmap)

    assert len(matches) == 1000 and "l999" in matches and "l1000" not in matches


def test_dropped_layers_do_not_use_up_the_cap():
    ctx = SimpleNamespace(aliases={}, items={"svc": _state_item(dataset_ids=["ds"])})
    webmap = {
        "operationalLayers": [
            {"layerType": "VectorTileLayer", "id": f"t{n}", "itemId": "svc"}
            for n in range(1200)
        ]
        + [{"layerType": "FeatureLayer", "id": "late", "itemId": "svc"}]
    }

    assert match_datasets(ctx, webmap) == {"late": "ds"}


def test_an_unsupported_layer_does_not_reserve_its_id():
    ctx = SimpleNamespace(
        aliases={},
        items={
            "tiles": _state_item(dataset_ids=["ds-tiles"]),
            "feat": _state_item(dataset_ids=["ds-feat"]),
        },
    )
    webmap = {
        "operationalLayers": [
            {"layerType": "VectorTileLayer", "id": "shared", "itemId": "tiles"},
            {"layerType": "FeatureLayer", "id": "shared", "itemId": "feat"},
        ]
    }

    assert match_datasets(ctx, webmap) == {"shared": "ds-feat"}


_ELIGIBILITY = json.loads(
    (
        Path(__file__).parents[2]
        / "backend/tests/fixtures/arcgis_webmaps/layer_eligibility.json"
    ).read_text()
)


@pytest.mark.parametrize("case", _ELIGIBILITY, ids=lambda case: case["name"])
def test_layer_eligibility_agrees_with_the_server_translator(case):
    assert _translatable(case["layer"]) is case["translated"]


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
                "layers": [
                    None,
                    {"layerType": "FeatureLayer", "id": "a", "itemId": "svc"},
                ],
            },
            None,
            {"layerType": "FeatureLayer", "id": "b", "itemId": "svc"},
        ]
    }

    assert match_datasets(ctx, webmap) == {"a": "ds", "b": "ds"}


def _only_the_map(path) -> None:
    plan = json.loads(path.read_text())
    for item in plan["items"]:
        if item["id"] != B1:
            item["action"] = "skip"
    path.write_text(json.dumps(plan))


@pytest.mark.parametrize("change", ["portal", "old_state", None])
def test_a_migrated_web_map_changed_in_the_portal_is_reported_at_cutover(
    runner, plan_file, geolens, portal, change
):
    _services(geolens)
    geolens.routes[IMPORT] = (201, _response())
    _only_the_map(plan_file)
    token = secrets.token_urlsafe(16)
    result, _ = _migrate(runner, plan_file, "--token", token)
    assert result.exit_code == 0, result.output
    listed = portal.routes[f"content/items/{B1}"]
    assert _state(plan_file)["items"][B1]["portal_modified"] == listed["modified"]
    if change == "portal":
        portal.routes[f"content/items/{B1}"] = {
            **listed,
            "modified": listed["modified"] + 60_000,
        }
    elif change == "old_state":
        path = plan_file.parent / "arcgis-migration-state.json"
        state = json.loads(path.read_text())
        state["items"][B1]["portal_modified"] = None
        path.write_text(json.dumps(state))

    result, payload = _migrate(runner, plan_file, "--token", token, "--cutover")

    assert len(_sent(geolens)) == 1
    if change is None:
        assert result.exit_code == 0, result.output
        assert payload["cutover"]["marked"] is True
        return
    assert result.exit_code == 1
    [reason] = payload["not_up_to_date"][B1]
    assert ("changed in the portal" if change == "portal" else "doesn't record") in (
        reason
    )
    assert payload["cutover"]["refused"] == ["unfinished-items"]


@pytest.mark.parametrize("gone", ["deleted", "no_id"])
def test_a_migrated_map_gone_from_geolens_blocks_cutover(
    runner, plan_file, geolens, gone
):
    _services(geolens)
    geolens.routes[IMPORT] = (201, _response())
    _only_the_map(plan_file)
    token = secrets.token_urlsafe(16)
    _migrate(runner, plan_file, "--token", token)
    if gone == "deleted":
        geolens.routes["GET /maps/" + MAP_ID] = (
            404,
            {"title": "Not Found", "status": 404, "detail": "Map not found"},
        )
    else:
        path = plan_file.parent / "arcgis-migration-state.json"
        state = json.loads(path.read_text())
        state["items"][B1]["map_id"] = None
        path.write_text(json.dumps(state))

    result, payload = _migrate(runner, plan_file, "--token", token, "--cutover")

    assert result.exit_code == 1
    assert payload["not_up_to_date"][B1] == ["the migrated map is gone from GeoLens"]
    assert payload["cutover"]["refused"] == ["unfinished-items"]


def test_a_migrated_map_given_to_someone_else_blocks_cutover(
    runner, plan_file, geolens
):
    _services(geolens)
    geolens.routes[IMPORT] = (201, _response())
    _only_the_map(plan_file)
    token = secrets.token_urlsafe(16)
    _migrate(runner, plan_file, "--token", token)
    owner = _state(plan_file)["items"][B1]["owner_id"]
    geolens.routes["GET /maps/" + MAP_ID] = _map("00000000-0000-0000-0000-0000000000f9")

    result, payload = _migrate(runner, plan_file, "--token", token, "--cutover")

    assert owner and result.exit_code == 1
    [reason] = payload["not_up_to_date"][B1]
    assert "map's owner changed in GeoLens" in reason


def test_a_migrated_map_shared_differently_than_the_plan_blocks_cutover(
    runner, plan_file, geolens, portal
):
    _services(geolens)
    geolens.routes[IMPORT] = (201, _response())
    _only_the_map(plan_file)
    token = secrets.token_urlsafe(16)
    _migrate(runner, plan_file, "--token", token)
    modified = _state(plan_file)["items"][B1]["portal_modified"]
    plan = json.loads(plan_file.read_text())
    for item in plan["items"]:
        if item["id"] == B1:
            item["target"]["visibility"] = "private"
    plan_file.write_text(json.dumps(plan))
    geolens.routes["GET /maps/" + MAP_ID] = {**_map(), "visibility": "public"}
    before = len(geolens.seen)

    result, payload = _migrate(runner, plan_file, "--token", token, "--cutover")

    assert portal.routes[f"content/items/{B1}"]["modified"] == modified
    assert result.exit_code == 1
    assert payload["not_up_to_date"][B1] == [
        "the plan gives the web map visibility private but the GeoLens map is "
        "public; set it by hand or rerun with the plan matching"
    ]
    assert payload["cutover"]["refused"] == ["unfinished-items"]
    assert not [s for s in geolens.seen[before:] if s.method in ("PATCH", "PUT")]


@pytest.mark.parametrize("recorded", [True, "1790000000000", 1.5])
def test_an_unusable_recorded_map_time_is_reported(
    runner, plan_file, geolens, portal, recorded
):
    _services(geolens)
    geolens.routes[IMPORT] = (201, _response())
    token = secrets.token_urlsafe(16)
    _migrate(runner, plan_file, "--only", B1, "--token", token)
    path = plan_file.parent / "arcgis-migration-state.json"
    state = json.loads(path.read_text())
    state["items"][B1]["portal_modified"] = recorded
    path.write_text(json.dumps(state))

    result, payload = _migrate(runner, plan_file, "--only", B1, "--token", token)

    assert result.exit_code == 1
    assert "doesn't record" in payload["not_up_to_date"][B1][0]


def test_a_group_only_web_map_is_imported_private_then_shared(
    runner, plan_file, geolens
):
    _services(geolens)
    geolens.routes[IMPORT] = (201, _response())
    group = "00000000-0000-0000-0005-000000000002"
    plan = json.loads(plan_file.read_text())
    for item in plan["items"]:
        if item["id"] == B1:
            item["target"]["visibility"] = "restricted"
            item["target"]["groups"] = ["g1"]
    plan["group_map"]["g1"] = {
        "collection": "Planning",
        "visibility": "internal",
        "geolens_group": "Planning",
    }
    plan_file.write_text(json.dumps(plan))
    geolens.routes["GET /admin/groups/"] = {
        "groups": [
            {
                "id": group,
                "name": "Planning",
                "member_count": 0,
                "created_at": NOW,
                "updated_at": NOW,
            }
        ],
        "total": 1,
    }
    shares: list[dict] = []

    def share(seen):
        shares.append(seen.json())
        return {
            "visibility": "restricted",
            "groups": [{"id": group, "name": "Planning"}],
            "shared_dataset_ids": [],
            "hidden_layers": [],
        }

    geolens.routes[f"PUT /maps/{MAP_ID}/groups/"] = share
    geolens.routes[f"GET /admin/groups/{group}/members/"] = {"members": [], "total": 0}

    result, _ = _run(runner, plan_file)

    assert result.exit_code == 0, result.output
    [request] = [s.json() for s in _sent(geolens)]
    assert request["visibility"] == "private"
    # Layers stay as their own items share them, not widened to the group.
    assert shares == [{"group_ids": [group], "confirm": "map_only"}]
    assert _state(plan_file)["items"][B1]["groups"] == {MAP_ID: [group]}


@pytest.mark.parametrize(
    ("first", "expected"),
    [("Planning", ["planning", "other"]), ("", ["other"])],
    ids=["portal-adds-a-group", "private-map-gets-its-first-group"],
)
def test_a_rerun_shares_a_migrated_map_with_a_group_the_portal_added(
    runner, plan_file, geolens, first, expected
):
    _services(geolens)
    geolens.routes[IMPORT] = (201, _response())
    planning = "00000000-0000-0000-0005-000000000002"
    other = "00000000-0000-0000-0005-000000000003"
    plan = json.loads(plan_file.read_text())
    for item in plan["items"]:
        if item["id"] == B1:
            item["target"]["visibility"] = "restricted"
            item["target"]["groups"] = ["g1"]
    plan["group_map"]["g1"] = {
        "collection": "Planning",
        "visibility": "internal",
        "geolens_group": first,
    }
    plan["group_map"]["g2"] = {
        "collection": "Other",
        "visibility": "internal",
        "geolens_group": "Other",
    }
    plan_file.write_text(json.dumps(plan))
    geolens.routes["GET /admin/groups/"] = {
        "groups": [
            {
                "id": g,
                "name": name,
                "member_count": 0,
                "created_at": NOW,
                "updated_at": NOW,
            }
            for g, name in ((planning, "Planning"), (other, "Other"))
        ],
        "total": 2,
    }
    for g in (planning, other):
        geolens.routes[f"GET /admin/groups/{g}/members/"] = {"members": [], "total": 0}
    held: dict[str, Any] = {"visibility": "private", "groups": []}

    def share(seen):
        ids = seen.json()["group_ids"]
        held.update(
            visibility="restricted" if ids else "private",
            groups=[{"id": g, "name": g} for g in ids],
        )
        return {**held, "shared_dataset_ids": [], "hidden_layers": []}

    geolens.routes[f"PUT /maps/{MAP_ID}/groups/"] = share
    geolens.routes["GET /maps/" + MAP_ID] = lambda seen: {**_map(), **held}
    token = secrets.token_urlsafe(16)
    assert _migrate(runner, plan_file, "--only", B1, "--token", token)[0].exit_code == 0
    for item in plan["items"]:
        if item["id"] == B1:
            item["target"]["groups"] = ["g1", "g2"]
    plan_file.write_text(json.dumps(plan))

    result, payload = _migrate(runner, plan_file, "--only", B1, "--token", token)

    assert result.exit_code == 0, result.output
    assert payload["not_up_to_date"] == {}
    ids = sorted({"planning": planning, "other": other}[g] for g in expected)
    assert held["visibility"] == "restricted"
    assert [g["id"] for g in held["groups"]] == ids
    assert _state(plan_file)["items"][B1]["groups"] == {MAP_ID: ids}


def test_only_a_web_map_imports_an_exported_service_whose_action_became_an_import(
    runner, plan_file, geolens
):
    def set_action(action: str) -> None:
        plan = json.loads(plan_file.read_text())
        for item in plan["items"]:
            if item["id"] in (A1, A2):
                item["action"] = action
        plan_file.write_text(json.dumps(plan))

    _services(geolens)
    geolens.routes[IMPORT] = (201, _response())
    set_action("export_only")
    token = secrets.token_urlsafe(16)
    exported, _ = _migrate(
        runner, plan_file, "--only", A1, "--only", A2, "--token", token
    )
    assert exported.exit_code == 0, exported.output
    set_action("import_layers")
    seen = len(geolens.seen)

    result, _ = _run(runner, plan_file)

    assert result.exit_code == 0, result.output
    urls = [s.url for s in geolens.seen[seen:]]
    probe = next(n for n, url in enumerate(urls) if url.endswith("/services/probe/"))
    assert probe < next(n for n, url in enumerate(urls) if url.endswith(IMPORT[5:]))
    [request] = [s.json() for s in _sent(geolens)]
    assert request["dataset_matches"] == {
        "parcels_0": dataset_id("Parcels"),
        "view_0": dataset_id("Parcels"),
    }
