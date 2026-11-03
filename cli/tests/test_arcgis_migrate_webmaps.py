"""`geolens arcgis migrate`: the import_map action against a fake GeoLens."""

# Imported fixtures are used as test arguments, which F811 reads as redefinition.
# ruff: noqa: F811

from __future__ import annotations

import base64
import copy
import json
import secrets
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from geolens_cli import arcgis_migrate as migrate
from geolens_cli import arcgis_migrate_webmaps as webmaps
from geolens_cli.arcgis_migrate_session import StopRun
from geolens_cli.arcgis_migrate_state import ItemState
from geolens_cli.arcgis_portal import PortalClient
from geolens_cli.arcgis_migrate_webmaps import _translatable, match_datasets

from .arcgis_fake import (
    A1,
    A2,
    B1,
    FIXTURES,
    FakePortal,
    item_data_path,
    portal_routes,
)
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


PARCELS_LAYER = "/ExAmPlEoRg0123/arcgis/rest/services/Parcels/FeatureServer/0"
SERVICE_RENDERER = {
    "type": "simple",
    "symbol": {"type": "esriSFS", "style": "esriSFSSolid", "color": [0, 92, 230, 255]},
}


def test_a_layer_the_web_map_leaves_unstyled_takes_its_service_renderer(
    runner, plan_file, geolens, portal
):
    _services(geolens)
    geolens.routes[IMPORT] = (201, _response())
    portal.routes[PARCELS_LAYER] = {
        "id": 0,
        "drawingInfo": {"renderer": SERVICE_RENDERER, "transparency": 25},
    }

    result, _ = _run(runner, plan_file)

    assert result.exit_code == 0, result.output
    [request] = [s.json() for s in _sent(geolens)]
    parcels = request["webmap"]["operationalLayers"][0]
    assert parcels["layerDefinition"]["drawingInfo"] == {
        "renderer": SERVICE_RENDERER,
        "transparency": 25,
    }
    [read] = portal.requests_to(PARCELS_LAYER)
    assert read.headers["x-esri-authorization"].startswith("Bearer ")
    # The other organization's hydrants service is never read.
    assert not [s for s in portal.seen if "OtherOrg" in s.url]


def _styling_ctx(routes: dict[str, Any], trusted: str = "services1.arcgis.com"):
    client = PortalClient(
        "https://examplecounty.maps.arcgis.com",
        opener=FakePortal(routes),
        redact=str,
        token="t",
        sleep=lambda _s: None,
    )
    return SimpleNamespace(
        portal=SimpleNamespace(client=client),
        trusted_hosts=frozenset({trusted}),
        portal_info=None,
        redact=str,
    )


def _styling_webmap() -> dict[str, Any]:
    return json.loads(
        (FIXTURES / "webmap_service_styling.json").read_text(encoding="utf-8")
    )


def _drawing(webmap: dict[str, Any]) -> dict[str, Any]:
    return {
        layer["id"]: layer.get("layerDefinition", {}).get("drawingInfo")
        for layer in webmap["operationalLayers"]
    }


SERVICE = "/ExAmPlEoRg0123/arcgis/rest/services/Conservation/FeatureServer/"
ALL_MATCHED = {f"conservation_{n}": f"ds-{n}" for n in ("18", "9", "6", "0")}


def test_source_styling_fills_only_what_the_web_map_leaves_to_the_service():
    webmap = _styling_webmap()
    authored = copy.deepcopy(webmap["operationalLayers"][0])
    labels = webmap["operationalLayers"][1]["layerDefinition"]["drawingInfo"]
    routes = {
        f"{SERVICE}{n}": {"drawingInfo": {"renderer": {"type": "simple", "n": n}}}
        for n in ("18", "9", "6", "0")
    }
    ctx = _styling_ctx(routes)

    webmaps.fill_source_styling(ctx, webmap, ALL_MATCHED)

    drawing = _drawing(webmap)
    assert webmap["operationalLayers"][0] == authored
    assert drawing["conservation_9"] == {
        **labels,
        "renderer": {"type": "simple", "n": "9"},
    }
    assert drawing["conservation_6"] == {"renderer": {"type": "simple", "n": "6"}}
    assert drawing["conservation_0"] == {"renderer": {"type": "simple", "n": "0"}}
    read = {s.path for s in ctx.portal.client._opener.seen}
    assert f"{SERVICE}18" not in read


def test_a_style_saved_on_the_layer_item_wins_over_the_service():
    saved = {"type": "simple", "from": "item"}
    routes = {
        item_data_path(A1): {
            "layers": [
                {"id": 6, "layerDefinition": {"drawingInfo": {"renderer": saved}}}
            ]
        },
        f"{SERVICE}6": {"drawingInfo": {"renderer": {"type": "simple"}}},
    }
    webmap = _styling_webmap()
    ctx = _styling_ctx(routes)

    webmaps.fill_source_styling(ctx, webmap, {"conservation_6": "ds-6"})

    assert _drawing(webmap)["conservation_6"] == {"renderer": saved}
    assert not ctx.portal.client._opener.requests_to(f"{SERVICE}6")


def test_a_refused_token_on_the_layer_item_stops_the_run_but_a_service_read_does_not():
    webmap = _styling_webmap()
    refused = (498, {"error": {"code": 498}})

    with pytest.raises(StopRun, match="fresh token"):
        webmaps.fill_source_styling(
            _styling_ctx({item_data_path(A1): refused}), webmap, ALL_MATCHED
        )

    before = copy.deepcopy(webmap)
    webmaps.fill_source_styling(
        _styling_ctx({f"{SERVICE}{n}": refused for n in ("18", "9", "6", "0")}),
        webmap,
        ALL_MATCHED,
    )
    assert webmap == before


def test_an_untrusted_or_unreadable_service_leaves_the_layer_unstyled():
    webmap = _styling_webmap()
    before = copy.deepcopy(webmap)
    untrusted = _styling_ctx({f"{SERVICE}6": {"drawingInfo": {}}}, trusted="x")

    webmaps.fill_source_styling(untrusted, webmap, ALL_MATCHED)
    webmaps.fill_source_styling(_styling_ctx({}), webmap, ALL_MATCHED)

    assert webmap == before
    assert not [s for s in untrusted.portal.client._opener.seen if SERVICE in s.path]


def test_a_layer_id_that_is_not_a_string_is_left_alone():
    webmap = _styling_webmap()
    webmap["operationalLayers"][0]["id"] = ["conservation_18"]
    webmap["operationalLayers"][1]["id"] = {"x": 1}

    webmaps.fill_source_styling(_styling_ctx({}), webmap, ALL_MATCHED)


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


@pytest.mark.parametrize("change", ["old_state", None])
def test_a_web_map_the_state_cant_date_is_reported_at_cutover(
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
    assert "doesn't record" in reason
    assert payload["cutover"]["refused"] == ["unfinished-items"]


EDITED_AT = "2026-10-03T00:00:00Z"
NOTES = "ArcGIS migration notes (2026-10-03)\n- $.p0: popup_expression"


def _translated(dataset: str) -> dict[str, Any]:
    """The dry run's answer for the changed web map: the view layer first, its
    parcels layer second, and a new layer the map didn't have."""
    return {
        "map": None,
        "layers": [
            {"dataset_id": dataset, "sort_order": n, "opacity": 0.5} for n in range(3)
        ],
        "layer_ids": {},
        "layer_sources": ["view_0", "parcels_0", "new_0"],
        "view": {
            "basemap_style": "dark",
            "center_lng": -74.0,
            "center_lat": 40.5,
            "zoom": 9.0,
            # An unrotated web map leaves it unset.
            "bearing": None,
        },
        "notes": NOTES,
        "loss_report": {
            "items": [{"path": "$.p0", "kind": "popup_expression", "detail": ""}],
            "summary": {"popup_expression": 1},
        },
        "unmatched_layers": [],
    }


def _saved(sent: dict[str, Any]) -> dict[str, Any]:
    """The map PUT's answer, its layers given ids where the request named none."""
    layers = [
        {
            "dataset_name": "d",
            "dataset_geometry_type": None,
            "dataset_table_name": "t",
            "dataset_extent_bbox": None,
            "visible": True,
            "paint": {},
            "layout": {},
            **layer,
            "id": layer.get("id") or LAYER_ID.format(9),
        }
        for layer in sent["layers"]
    ]
    return {
        **_map(),
        "updated_at": EDITED_AT,
        "layers": layers,
        "layer_count": len(layers),
    }


def _changed_in_the_portal(runner, plan_file, geolens, portal) -> str:
    """Migrate the web map, then move its portal item's modified time on."""
    _services(geolens)
    geolens.routes[IMPORT] = lambda seen: (
        (201, _translated(dataset_id("Parcels")))
        if seen.json().get("dry_run")
        else (201, _response(lost=2))
    )
    geolens.routes["PUT /maps/" + MAP_ID] = lambda seen: _saved(seen.json())
    _only_the_map(plan_file)
    token = secrets.token_urlsafe(16)
    result, _ = _migrate(runner, plan_file, "--token", token)
    assert result.exit_code == 0, result.output
    listed = portal.routes[f"content/items/{B1}"]
    portal.routes[f"content/items/{B1}"] = {
        **listed,
        "modified": listed["modified"] + 60_000,
    }
    return token


def _puts(geolens) -> list[dict[str, Any]]:
    return [s.json() for s in geolens.seen if s.method == "PUT" and MAP_ID in s.url]


def test_a_web_map_changed_in_the_portal_is_translated_again_into_the_same_map(
    runner, plan_file, geolens, portal
):
    token = _changed_in_the_portal(runner, plan_file, geolens, portal)
    modified = portal.routes[f"content/items/{B1}"]["modified"]

    result, payload = _migrate(runner, plan_file, "--token", token, "--cutover")

    assert result.exit_code == 0, result.output
    assert payload["cutover"]["marked"] is True
    [dry_run] = [s.json() for s in _sent(geolens)][1:]
    assert dry_run["dry_run"] is True
    assert dry_run["webmap"]["operationalLayers"]
    [sent] = _puts(geolens)
    assert sent["expected_updated_at"] == "2026-10-01T00:00:00+00:00"
    assert sent["notes"] == NOTES
    assert (sent["basemap_style"], sent["center_lng"]) == ("dark", -74.0)
    assert sent["bearing"] == 0.0
    assert [layer.get("id") for layer in sent["layers"]] == [
        LAYER_ID.format(2),
        LAYER_ID.format(1),
        None,
    ]
    entry = _state(plan_file)["items"][B1]
    assert entry["map_id"] == MAP_ID
    assert entry["portal_modified"] == modified
    assert entry["map_snapshot"]["updated_at"] == "2026-10-03T00:00:00+00:00"
    assert entry["layer_ids"] == {
        "view_0": LAYER_ID.format(2),
        "parcels_0": LAYER_ID.format(1),
        "new_0": LAYER_ID.format(9),
    }
    assert [n for n in entry["notes"] if "part(s)" in n] == [
        "1 part(s) of the web map were not carried over"
    ]
    loss = json.loads((plan_file.parent / entry["loss_report_path"]).read_text())
    assert loss["loss_report"]["summary"] == {"popup_expression": 1}

    # Nothing changed since: the next run writes nothing.
    result, _ = _migrate(runner, plan_file, "--token", token)
    assert result.exit_code == 0, result.output
    assert len(_puts(geolens)) == 1


def test_a_loss_report_a_rerun_couldnt_write_is_written_by_the_next_one(
    runner, plan_file, geolens, portal, monkeypatch
):
    token = _changed_in_the_portal(runner, plan_file, geolens, portal)
    write = webmaps._write_loss

    def refuse(*args):
        raise webmaps.ItemFailed("writing the loss report failed: disk full")

    monkeypatch.setattr(webmaps, "_write_loss", refuse)
    result, payload = _migrate(runner, plan_file, "--token", token)

    assert result.exit_code == 1
    assert payload["not_up_to_date"][B1] == [
        "writing the loss report failed: disk full; a rerun tries again"
    ]
    assert _state(plan_file)["items"][B1]["pending_loss"] is not None
    monkeypatch.setattr(webmaps, "_write_loss", write)

    result, _ = _migrate(runner, plan_file, "--token", token)

    assert result.exit_code == 0, result.output
    assert len(_puts(geolens)) == 1
    entry = _state(plan_file)["items"][B1]
    assert entry["pending_loss"] is None
    assert [n for n in entry["notes"] if "part(s)" in n] == [
        "1 part(s) of the web map were not carried over"
    ]
    loss = json.loads((plan_file.parent / entry["loss_report_path"]).read_text())
    assert loss["loss_report"]["summary"] == {"popup_expression": 1}


def test_a_lost_view_note_fits_notes_near_their_limit(
    runner, plan_file, geolens, portal
):
    token = _changed_in_the_portal(runner, plan_file, geolens, portal)
    translated = _translated(dataset_id("Parcels"))
    lines = [f"- $.p{n}: popup_expression ({'x' * 80})" for n in range(455)]
    long_notes = "\n".join(["ArcGIS migration notes (2026-10-03)", *lines])
    assert 49_900 < len(long_notes) <= 50_000
    no_view = {"center_lng": None, "center_lat": None, "zoom": None}
    geolens.routes[IMPORT] = (
        201,
        {**translated, "notes": long_notes, "view": {**translated["view"], **no_view}},
    )

    result, _ = _migrate(runner, plan_file, "--token", token)

    assert result.exit_code == 0, result.output
    [sent] = _puts(geolens)
    assert len(sent["notes"]) <= 50_000
    assert sent["notes"].endswith(
        "\n... more entries in the CLI report\n- the web map no longer has an "
        "initial view; the GeoLens map keeps its view"
    )
    assert sent["notes"].startswith("ArcGIS migration notes (2026-10-03)\n- $.p0")


def test_a_saved_layer_is_paired_with_its_source_despite_gaps_in_sort_order(
    runner, plan_file, geolens, portal
):
    token = _changed_in_the_portal(runner, plan_file, geolens, portal)

    def gapped(seen):
        saved = _saved(seen.json())
        # A layer the caller can't read keeps its place, so the rest skip it.
        for position, layer in enumerate(saved["layers"]):
            layer["sort_order"] = 2 * position + 1
        return saved

    geolens.routes["PUT /maps/" + MAP_ID] = gapped

    result, _ = _migrate(runner, plan_file, "--token", token)

    assert result.exit_code == 0, result.output
    assert _state(plan_file)["items"][B1]["layer_ids"] == {
        "view_0": LAYER_ID.format(2),
        "parcels_0": LAYER_ID.format(1),
        "new_0": LAYER_ID.format(9),
    }


def test_a_layer_hidden_from_the_saver_keeps_its_recorded_map_layer(
    runner, plan_file, geolens, portal
):
    token = _changed_in_the_portal(runner, plan_file, geolens, portal)

    def hiding_the_first(seen):
        saved = _saved(seen.json())
        # The view layer's dataset is hidden from the saver: its row stays, in
        # its slot, and the answer leaves it out.
        saved["layers"] = saved["layers"][1:]
        for position, layer in enumerate(saved["layers"], start=1):
            layer["sort_order"] = 2 * position + 1
        return saved

    geolens.routes["PUT /maps/" + MAP_ID] = hiding_the_first

    result, _ = _migrate(runner, plan_file, "--token", token)

    assert result.exit_code == 0, result.output
    assert _state(plan_file)["items"][B1]["layer_ids"] == {
        "view_0": LAYER_ID.format(2),
        "parcels_0": LAYER_ID.format(1),
        "new_0": LAYER_ID.format(9),
    }


@pytest.mark.parametrize("stale", [False, True], ids=["dropped", "stale-id-kept"])
def test_a_layer_removed_and_added_back_in_the_portal_keeps_one_map_layer(
    runner, plan_file, geolens, portal, stale
):
    token = _changed_in_the_portal(runner, plan_file, geolens, portal)
    full = _translated(dataset_id("Parcels"))
    rows = {"parcels_0": LAYER_ID.format(1), "view_0": LAYER_ID.format(2)}
    stored: list[dict[str, Any]] = [
        {"id": i, "dataset_id": dataset_id("Parcels"), "sort_order": n, "opacity": 1}
        for n, i in enumerate(rows.values())
    ]
    made = iter(LAYER_ID.format(n) for n in range(5, 9))
    state = {"updated_at": "2026-10-01T00:00:00Z"}
    read = geolens.routes["GET /maps/" + MAP_ID]

    def get(seen):
        layers = _saved({"layers": stored})["layers"]
        return {**read(seen), "layers": layers, "layer_count": len(layers), **state}

    def put(seen):
        # A replacement: rows named by an existing id are kept, the rest made.
        existing = {row["id"] for row in stored}
        stored[:] = [
            {
                **layer,
                "id": layer["id"] if layer.get("id") in existing else next(made),
            }
            for layer in seen.json()["layers"]
        ]
        state["updated_at"] = f"2026-10-0{len(puts) + 3}T00:00:00Z"
        puts.append(seen.json())
        return get(seen)

    puts: list[dict[str, Any]] = []
    geolens.routes["GET /maps/" + MAP_ID] = get
    geolens.routes["PUT /maps/" + MAP_ID] = put

    def rerun(translated):
        listed = portal.routes[f"content/items/{B1}"]
        portal.routes[f"content/items/{B1}"] = {
            **listed,
            "modified": listed["modified"] + 60_000,
        }
        geolens.routes[IMPORT] = (201, translated)
        result, _ = _migrate(runner, plan_file, "--token", token)
        assert result.exit_code == 0, result.output

    without_view = {
        **full,
        "layers": full["layers"][1:2],
        "layer_sources": ["parcels_0"],
    }
    rerun(without_view)
    assert "view_0" not in _state(plan_file)["items"][B1]["layer_ids"]
    if stale:
        # As an earlier version left it: the deleted row's id still recorded.
        path = plan_file.parent / "arcgis-migration-state.json"
        saved = json.loads(path.read_text())
        saved["items"][B1]["layer_ids"]["view_0"] = LAYER_ID.format(2)
        path.write_text(json.dumps(saved))
    with_view = {
        **full,
        "layers": full["layers"][:2],
        "layer_sources": full["layer_sources"][:2],
    }
    rerun(with_view)
    view_row = _state(plan_file)["items"][B1]["layer_ids"]["view_0"]

    rerun(with_view)

    assert [layer.get("id") for layer in puts[-1]["layers"]] == [
        view_row,
        LAYER_ID.format(1),
    ]
    assert {row["id"] for row in stored} == {view_row, LAYER_ID.format(1)}


def test_a_translation_without_losses_removes_the_earlier_report(
    runner, plan_file, geolens, portal
):
    token = _changed_in_the_portal(runner, plan_file, geolens, portal)
    report = plan_file.parent / _state(plan_file)["items"][B1]["loss_report_path"]
    assert report.exists()
    translated = _translated(dataset_id("Parcels"))
    translated["loss_report"] = {"items": [], "summary": {}}
    geolens.routes[IMPORT] = (201, translated)

    result, _ = _migrate(runner, plan_file, "--token", token)

    assert result.exit_code == 0, result.output
    assert _state(plan_file)["items"][B1]["loss_report_path"] is None
    assert not report.exists()


def test_an_earlier_loss_report_a_rerun_couldnt_remove_is_removed_by_the_next(
    runner, plan_file, geolens, portal, monkeypatch
):
    token = _changed_in_the_portal(runner, plan_file, geolens, portal)
    report = plan_file.parent / _state(plan_file)["items"][B1]["loss_report_path"]
    translated = _translated(dataset_id("Parcels"))
    translated["loss_report"] = {"items": [], "summary": {}}
    geolens.routes[IMPORT] = (201, translated)
    remove = webmaps._remove_loss

    def refuse(*args):
        raise webmaps.ItemFailed("removing the earlier loss report failed: busy")

    monkeypatch.setattr(webmaps, "_remove_loss", refuse)
    result, payload = _migrate(runner, plan_file, "--token", token)

    assert result.exit_code == 1
    assert payload["not_up_to_date"][B1] == [
        "removing the earlier loss report failed: busy; a rerun tries again"
    ]
    assert report.exists()
    monkeypatch.setattr(webmaps, "_remove_loss", remove)

    # The portal is unchanged, so only the pending removal is left to do.
    result, _ = _migrate(runner, plan_file, "--token", token)

    assert result.exit_code == 0, result.output
    assert len(_puts(geolens)) == 1
    assert not report.exists()
    entry = _state(plan_file)["items"][B1]
    assert entry["pending_loss"] is None
    assert not [n for n in entry["notes"] if "part(s)" in n]


def test_a_map_edited_after_a_partial_import_is_never_overwritten(
    runner, plan_file, geolens, portal, monkeypatch
):
    _services(geolens)
    geolens.routes[IMPORT] = lambda seen: (
        (201, _translated(dataset_id("Parcels")))
        if seen.json().get("dry_run")
        else (201, _response(lost=2))
    )
    geolens.routes["PUT /maps/" + MAP_ID] = lambda seen: _saved(seen.json())
    _only_the_map(plan_file)
    token = secrets.token_urlsafe(16)
    write = webmaps._write_loss

    def refuse(*args):
        raise webmaps.ItemFailed("writing the loss report failed: disk full")

    monkeypatch.setattr(webmaps, "_write_loss", refuse)
    assert _migrate(runner, plan_file, "--token", token)[0].exit_code == 1
    entry = _state(plan_file)["items"][B1]
    assert entry["status"] == "failed" and entry["map_id"] == MAP_ID
    imported = entry["map_snapshot"]
    assert imported["updated_at"] == "2026-10-01T00:00:00+00:00"
    monkeypatch.setattr(webmaps, "_write_loss", write)
    # Someone edits the map in GeoLens before the import is retried.
    read = geolens.routes["GET /maps/" + MAP_ID]
    geolens.routes["GET /maps/" + MAP_ID] = lambda seen: {
        **read(seen),
        "updated_at": EDITED_AT,
    }
    _migrate(runner, plan_file, "--token", token)
    assert _state(plan_file)["items"][B1]["map_snapshot"] == imported
    listed = portal.routes[f"content/items/{B1}"]
    portal.routes[f"content/items/{B1}"] = {
        **listed,
        "modified": listed["modified"] + 60_000,
    }

    result, payload = _migrate(runner, plan_file, "--token", token)

    assert result.exit_code == 1
    assert _puts(geolens) == []
    assert len(_sent(geolens)) == 1
    assert _state(plan_file)["items"][B1]["map_snapshot"] == imported


def test_a_layer_whose_dataset_the_account_cant_read_is_left_as_it_is(
    runner, plan_file, geolens, portal
):
    _services(geolens)
    parcels = dataset_id("Parcels")
    unreadable: set[str] = set()

    def translate(seen):
        body = seen.json()
        # GeoLens refuses a match the caller can't read.
        if set(body["dataset_matches"].values()) & unreadable:
            return (404, {"title": "Not Found", "status": 404, "detail": "nope"})
        if not body.get("dry_run"):
            return (201, _response())
        return (201, {**_translated(parcels), "layers": [], "layer_sources": []})

    geolens.routes[IMPORT] = translate
    geolens.routes["PUT /maps/" + MAP_ID] = lambda seen: _saved(seen.json())
    assert _run(runner, plan_file)[0].exit_code == 0
    recorded = _state(plan_file)["items"][B1]["layer_ids"]
    # The dataset now belongs to someone the run's account can't read for.
    unreadable.add(parcels)
    geolens.routes[f"GET /datasets/{parcels}"] = (
        404,
        {"title": "Not Found", "status": 404, "detail": "Dataset not found"},
    )
    listed = portal.routes[f"content/items/{B1}"]
    portal.routes[f"content/items/{B1}"] = {
        **listed,
        "modified": listed["modified"] + 60_000,
    }

    result, payload = _run(runner, plan_file)

    assert result.exit_code == 0, result.output
    assert [s.json()["dataset_matches"] for s in _sent(geolens)][-1] == {}
    [sent] = _puts(geolens)
    assert sent["layers"] == []
    entry = _state(plan_file)["items"][B1]
    assert entry["layer_ids"] == recorded
    assert any(
        n.endswith(": parcels_0, view_0") and "can't read" in n for n in entry["notes"]
    )


def test_a_layer_repointed_to_a_dataset_the_account_cant_read_keeps_its_row(
    runner, plan_file, geolens, portal, monkeypatch
):
    _services(geolens)
    parcels = dataset_id("Parcels")
    elsewhere = "00000000-0000-0000-0009-000000000001"

    def translate(seen):
        body = seen.json()
        if elsewhere in body["dataset_matches"].values():
            return (404, {"title": "Not Found", "status": 404, "detail": "nope"})
        if not body.get("dry_run"):
            return (201, _response())
        view = {"dataset_id": parcels, "sort_order": 0, "opacity": 0.5}
        return (
            201,
            {**_translated(parcels), "layers": [view], "layer_sources": ["view_0"]},
        )

    geolens.routes[IMPORT] = translate
    geolens.routes["PUT /maps/" + MAP_ID] = lambda seen: _saved(seen.json())
    assert _run(runner, plan_file)[0].exit_code == 0
    parcels_row = _state(plan_file)["items"][B1]["layer_ids"]["parcels_0"]
    # Both layers read the parcels dataset in GeoLens.
    stored = _saved(
        {
            "layers": [
                {
                    "id": parcels_row,
                    "dataset_id": parcels,
                    "sort_order": 0,
                    "opacity": 1,
                },
                {
                    "id": LAYER_ID.format(2),
                    "dataset_id": parcels,
                    "sort_order": 1,
                    "opacity": 1,
                },
            ]
        }
    )["layers"]
    read = geolens.routes["GET /maps/" + MAP_ID]
    geolens.routes["GET /maps/" + MAP_ID] = lambda seen: {
        **read(seen),
        "layers": stored,
        "layer_count": len(stored),
    }
    # The portal repoints parcels_0 to a dataset the account can't read.
    real = webmaps.match_datasets
    monkeypatch.setattr(
        webmaps,
        "match_datasets",
        lambda ctx, webmap: {**real(ctx, webmap), "parcels_0": elsewhere},
    )
    geolens.routes[f"GET /datasets/{elsewhere}"] = (
        404,
        {"title": "Not Found", "status": 404, "detail": "Dataset not found"},
    )
    listed = portal.routes[f"content/items/{B1}"]
    portal.routes[f"content/items/{B1}"] = {
        **listed,
        "modified": listed["modified"] + 60_000,
    }

    result, _ = _run(runner, plan_file)

    assert result.exit_code == 0, result.output
    [sent] = _puts(geolens)
    kept = next(layer for layer in sent["layers"] if layer.get("id") == parcels_row)
    assert (kept["dataset_id"], kept["opacity"]) == (parcels, 1)
    assert _state(plan_file)["items"][B1]["layer_ids"]["parcels_0"] == parcels_row


def test_a_web_map_that_lost_its_initial_view_keeps_the_maps_and_says_so(
    runner, plan_file, geolens, portal
):
    token = _changed_in_the_portal(runner, plan_file, geolens, portal)
    translated = _translated(dataset_id("Parcels"))
    no_view = {"center_lng": None, "center_lat": None, "zoom": None}
    geolens.routes[IMPORT] = (
        201,
        {**translated, "view": {**translated["view"], **no_view}},
    )
    note = "the web map no longer has an initial view; the GeoLens map keeps its view"

    result, _ = _migrate(runner, plan_file, "--token", token)

    assert result.exit_code == 0, result.output
    [sent] = _puts(geolens)
    assert sent["notes"] == f"{NOTES}\n- {note}"
    # The map keeps its rotation along with its view.
    assert sent.get("bearing") is None
    assert note in _state(plan_file)["items"][B1]["notes"]

    # The view comes back in the portal: the note goes.
    listed = portal.routes[f"content/items/{B1}"]
    portal.routes[f"content/items/{B1}"] = {
        **listed,
        "modified": listed["modified"] + 60_000,
    }
    geolens.routes[IMPORT] = (201, translated)
    read = geolens.routes["GET /maps/" + MAP_ID]
    geolens.routes["GET /maps/" + MAP_ID] = lambda seen: {
        **read(seen),
        "updated_at": EDITED_AT,
    }
    result, _ = _migrate(runner, plan_file, "--token", token)

    assert result.exit_code == 0, result.output
    assert _puts(geolens)[-1]["notes"] == NOTES
    assert note not in _state(plan_file)["items"][B1]["notes"]


@pytest.mark.parametrize("edit", ["updated_at", "snapshot"])
def test_a_changed_web_map_whose_geolens_map_was_edited_is_reported_not_written(
    runner, plan_file, geolens, portal, edit
):
    token = _changed_in_the_portal(runner, plan_file, geolens, portal)
    if edit == "updated_at":
        read = geolens.routes["GET /maps/" + MAP_ID]
        geolens.routes["GET /maps/" + MAP_ID] = lambda seen: {
            **read(seen),
            "updated_at": EDITED_AT,
        }
    else:
        path = plan_file.parent / "arcgis-migration-state.json"
        state = json.loads(path.read_text())
        state["items"][B1]["map_snapshot"] = None
        path.write_text(json.dumps(state))

    result, payload = _migrate(runner, plan_file, "--token", token)

    assert result.exit_code == 1
    assert _puts(geolens) == []
    assert len(_sent(geolens)) == 1
    [reason] = payload["not_up_to_date"][B1]
    assert (
        "changed in GeoLens since the last run"
        if edit == "updated_at"
        else "doesn't record how this command left"
    ) in reason


def test_a_web_map_save_geolens_refuses_as_stale_is_reported_not_recorded(
    runner, plan_file, geolens, portal
):
    token = _changed_in_the_portal(runner, plan_file, geolens, portal)
    before = _state(plan_file)["items"][B1]
    geolens.routes["PUT /maps/" + MAP_ID] = (
        409,
        {
            "title": "Conflict",
            "status": 409,
            "detail": {"code": "stale_write", "message": "changed"},
        },
    )

    result, payload = _migrate(runner, plan_file, "--token", token)

    assert result.exit_code == 1
    [reason] = payload["not_up_to_date"][B1]
    assert reason == (
        "changed in GeoLens while the web map was translated again; it was left "
        "as it is"
    )
    entry = _state(plan_file)["items"][B1]
    for key in ("map_snapshot", "layer_ids", "portal_modified", "notes"):
        assert entry[key] == before[key]


@pytest.mark.parametrize("answer", ["older", "unpaired", "older_sdk"])
def test_a_translation_the_cli_cant_save_is_reported(
    runner, plan_file, geolens, portal, monkeypatch, answer
):
    token = _changed_in_the_portal(runner, plan_file, geolens, portal)
    translated = _translated(dataset_id("Parcels"))
    if answer == "older":
        for key in ("layer_sources", "view", "notes"):
            del translated[key]
    elif answer == "unpaired":
        translated["layer_sources"] = translated["layer_sources"][:2]
    else:
        # A geolens package from before the model existed.
        monkeypatch.setitem(sys.modules, "geolens.models.arcgis_translated_view", None)
    geolens.routes[IMPORT] = (201, translated)

    result, payload = _migrate(runner, plan_file, "--token", token)

    assert result.exit_code == 1
    assert _puts(geolens) == []
    assert len(_sent(geolens)) == (1 if answer == "older_sdk" else 2)
    assert payload["refreshed"] == [B1]
    [reason] = payload["not_up_to_date"][B1]
    assert "needs GeoLens and the geolens package 1.30 or newer" in reason


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
            "updated_at": NOW,
        }

    geolens.routes[f"PUT /maps/{MAP_ID}/groups/"] = share
    geolens.routes[f"GET /admin/groups/{group}/members/"] = {"members": [], "total": 0}

    result, _ = _run(runner, plan_file)

    assert result.exit_code == 0, result.output
    [request] = [s.json() for s in _sent(geolens)]
    assert request["visibility"] == "private"
    # Layers stay as their own items share them, not widened to the group.
    assert shares == [
        {
            "group_ids": [group],
            "confirm": "map_only",
            # Only as the import left it.
            "expected_updated_at": "2026-10-01T00:00:00+00:00",
        }
    ]
    assert _state(plan_file)["items"][B1]["groups"] == {MAP_ID: [group]}


def test_a_new_maps_first_group_is_taken_as_the_imports_own_change(
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
    geolens.routes[f"GET /admin/groups/{group}/members/"] = {"members": [], "total": 0}
    shared = {}
    read = geolens.routes["GET /maps/" + MAP_ID]

    def share(seen):
        # A private map's first group makes it restricted, which moves its
        # timestamp.
        shared["at"] = EDITED_AT
        return {
            "visibility": "restricted",
            "groups": [{"id": group, "name": "Planning"}],
            "shared_dataset_ids": [],
            "hidden_layers": [],
            "updated_at": EDITED_AT,
        }

    geolens.routes[f"PUT /maps/{MAP_ID}/groups/"] = share
    geolens.routes["GET /maps/" + MAP_ID] = lambda seen: {
        **read(seen),
        **({"updated_at": shared["at"], "visibility": "restricted"} if shared else {}),
    }

    result, _ = _run(runner, plan_file)

    assert result.exit_code == 0, result.output
    assert _state(plan_file)["items"][B1]["status"] == "done"
    # The map is handed over as the share left it.
    [handover] = [
        s.json() for s in geolens.seen if s.method == "PATCH" and MAP_ID in s.url
    ]
    assert handover["expected_updated_at"] == "2026-10-03T00:00:00+00:00"


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
        return {
            **held,
            "shared_dataset_ids": [],
            "hidden_layers": [],
            "updated_at": NOW,
        }

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


THUMBNAIL = "thumbnail/ago_downloaded.png"
THUMBNAIL_PUT = f"PUT /maps/{MAP_ID}/thumbnail/"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def _thumbnail(portal, image: Any = PNG, path: Any = THUMBNAIL) -> None:
    item = f"content/items/{B1}"
    portal.routes[item] = {**portal.routes[item], "thumbnail": path}
    portal.routes[f"{item}/info/{THUMBNAIL}"] = (
        (200, image) if isinstance(image, bytes) else image
    )


def _uploads(geolens) -> list[str]:
    return [
        s.json()["data_uri"]
        for s in geolens.seen
        if s.method == "PUT" and s.url.endswith("/thumbnail/")
    ]


def _thumbnail_notes(plan_file) -> list[str]:
    notes = _state(plan_file)["items"][B1]["notes"]
    return [note for note in notes if "thumbnail" in note]


def test_a_new_map_gets_the_web_maps_thumbnail(runner, plan_file, geolens, portal):
    _services(geolens)
    geolens.routes[IMPORT] = (201, _response())
    geolens.routes[THUMBNAIL_PUT] = (204, None)
    _thumbnail(portal)

    result, _ = _run(runner, plan_file)

    assert result.exit_code == 0, result.output
    assert _uploads(geolens) == [
        "data:image/png;base64," + base64.b64encode(PNG).decode()
    ]
    [read] = portal.requests_to(f"content/items/{B1}/info/{THUMBNAIL}")
    assert read.headers.get("x-esri-authorization", "").startswith("Bearer ")
    assert _thumbnail_notes(plan_file) == []


def test_a_rerun_gives_a_migrated_map_the_thumbnail_it_lacks_and_keeps_one_it_has(
    runner, plan_file, geolens, portal
):
    _services(geolens)
    geolens.routes[IMPORT] = (201, _response())
    geolens.routes[THUMBNAIL_PUT] = (204, None)
    _run(runner, plan_file)
    assert _uploads(geolens) == []
    assert _thumbnail_notes(plan_file) == [
        "the web map's thumbnail was not carried over: the web map has none"
    ]

    _thumbnail(portal)
    result, _ = _run(runner, plan_file)

    assert result.exit_code == 0, result.output
    assert len(_uploads(geolens)) == 1
    assert _thumbnail_notes(plan_file) == []

    shown = geolens.routes["GET /maps/" + MAP_ID]
    geolens.routes["GET /maps/" + MAP_ID] = lambda seen: {
        **shown(seen),
        "thumbnail_url": f"/maps/{MAP_ID}/thumbnail/",
    }
    result, _ = _run(runner, plan_file)

    assert result.exit_code == 0, result.output
    assert len(_uploads(geolens)) == 1


@pytest.mark.parametrize(
    ("image", "path", "reason"),
    [
        (PNG, "thumbnail/../../community/self", "its path can't be read"),
        (b"\xff\xd8\xff" + b"\x00" * 80_000, THUMBNAIL, "larger than"),
        (b"GIF89a" + b"\x00" * 64, THUMBNAIL, "not a PNG or JPEG"),
        ((404, {"error": {"code": 404}}), THUMBNAIL, "reading it failed"),
    ],
)
def test_a_thumbnail_that_cant_be_read_is_reported_and_the_map_kept(
    runner, plan_file, geolens, portal, image, path, reason
):
    _services(geolens)
    geolens.routes[IMPORT] = (201, _response())
    geolens.routes[THUMBNAIL_PUT] = (204, None)
    _thumbnail(portal, image, path)

    result, _ = _run(runner, plan_file)

    assert result.exit_code == 0, result.output
    assert _state(plan_file)["items"][B1]["status"] == "done"
    [note] = _thumbnail_notes(plan_file)
    assert reason in note
    assert _uploads(geolens) == []


def test_a_refused_thumbnail_upload_is_reported_and_the_map_kept(
    runner, plan_file, geolens, portal
):
    _services(geolens)
    geolens.routes[IMPORT] = (201, _response())
    geolens.routes[THUMBNAIL_PUT] = (400, _problem(400, "not an image"))
    _thumbnail(portal)

    result, _ = _run(runner, plan_file)

    assert result.exit_code == 0, result.output
    assert _state(plan_file)["items"][B1]["status"] == "done"
    [note] = _thumbnail_notes(plan_file)
    assert "uploading it failed" in note


def test_a_rerun_drops_a_thumbnail_note_once_the_map_has_a_thumbnail(
    runner, plan_file, geolens, portal
):
    _services(geolens)
    geolens.routes[IMPORT] = (201, _response())
    geolens.routes[THUMBNAIL_PUT] = (400, _problem(400, "not an image"))
    _thumbnail(portal)
    _run(runner, plan_file)
    assert _thumbnail_notes(plan_file)
    shown = geolens.routes["GET /maps/" + MAP_ID]
    geolens.routes["GET /maps/" + MAP_ID] = lambda seen: {
        **shown(seen),
        "thumbnail_url": f"/maps/{MAP_ID}/thumbnail/",
    }

    result, _ = _run(runner, plan_file)

    assert result.exit_code == 0, result.output
    assert _thumbnail_notes(plan_file) == []


@pytest.mark.parametrize(
    "failure", [httpx.ConnectError("refused"), httpx.ReadTimeout("slow")]
)
def test_a_thumbnail_upload_lost_on_the_network_is_reported_and_the_run_goes_on(
    runner, plan_file, geolens, portal, failure
):
    _services(geolens)
    geolens.routes[IMPORT] = (201, _response())

    def lost(seen):
        raise failure

    geolens.routes[THUMBNAIL_PUT] = lost
    _thumbnail(portal)

    result, _ = _run(runner, plan_file)

    assert result.exit_code == 0, result.output
    entry = _state(plan_file)["items"][B1]
    assert entry["status"] == "done"
    assert entry["owner_id"] == OPERATOR
    [note] = _thumbnail_notes(plan_file)
    assert "uploading it failed on the network" in note


def test_a_thumbnail_download_lost_on_the_network_is_reported(
    runner, plan_file, geolens, portal
):
    _services(geolens)
    geolens.routes[IMPORT] = (201, _response())
    geolens.routes[THUMBNAIL_PUT] = (204, None)
    _thumbnail(portal, ConnectionResetError("reset"))

    result, _ = _run(runner, plan_file)

    assert result.exit_code == 0, result.output
    assert _state(plan_file)["items"][B1]["status"] == "done"
    [note] = _thumbnail_notes(plan_file)
    assert "reading it failed" in note
    assert _uploads(geolens) == []


def test_a_dry_run_promises_no_thumbnail_whose_path_it_cant_read(
    runner, tmp_path, geolens, portal
):
    path = "thumbnail/../../community/self"
    plan_file = _write_plan(tmp_path, rows={B1: {"thumbnail": path}})
    _services(geolens)

    result, payload = _migrate(runner, plan_file, "--only", B1, "--dry-run")

    assert result.exit_code == 0, result.output
    [row] = [row for row in payload["items"] if row["id"] == B1]
    assert not any("thumbnail" in note for note in row["notes"])


def test_a_dry_run_says_it_would_upload_the_thumbnail(
    runner, tmp_path, geolens, portal
):
    plan_file = _write_plan(tmp_path, rows={B1: {"thumbnail": THUMBNAIL}})
    _services(geolens)

    result, payload = _migrate(runner, plan_file, "--only", B1, "--dry-run")

    assert result.exit_code == 0, result.output
    [row] = [row for row in payload["items"] if row["id"] == B1]
    assert row["notes"] == [
        "would upload the web map's thumbnail to the new GeoLens map"
    ]
    assert _uploads(geolens) == []
    assert not portal.seen
