"""Showcase upgrades keep owned content usable across retries."""

from __future__ import annotations

import importlib.util

import pytest

from tests.repo_paths import repo_root


SCRIPT = repo_root(__file__) / "scripts" / "seed-showcase.py"
spec = importlib.util.spec_from_file_location("seed_showcase_121", SCRIPT)
seed = importlib.util.module_from_spec(spec)
spec.loader.exec_module(seed)


class CityApi:
    username = "showcase"

    def __init__(self):
        self.datasets = {
            seed.CITY_SHADE_SOURCE: "source-id",
            seed.CITY_SHADE_WINDOW: "window-id",
            seed.CITY_SHADE_RESULT: "result-id",
        }
        self.map = {
            "id": "city-id",
            "name": seed.CITY_SHADE_MAP,
            "description": seed.MAP_DESCRIPTIONS[seed.CITY_SHADE_MAP],
            "created_by_username": self.username,
            "visibility": "private",
            "center_lng": None,
            "center_lat": None,
            "zoom": None,
            "layers": [],
        }
        self.added = 0
        self.view_updates = 0
        self.dataset_patches = 0

    def list_own_datasets(self):
        return [{"title": title, "id": did} for title, did in self.datasets.items()]

    def list_all_maps(self):
        return [self.map]

    def get_map(self, _):
        return self.map

    def get_dataset(self, _):
        return {
            "visibility": "public",
            "summary": seed.MAP_DESCRIPTIONS[seed.CITY_SHADE_MAP],
        }

    def patch_dataset(self, *_args, **_fields):
        self.dataset_patches += 1

    def dataset_feature_count(self, _):
        return 16_345

    def add_layer(self, _, body):
        self.added += 1
        layer = {"id": f"layer-{self.added}", **body}
        self.map["layers"].append(layer)
        return layer

    def set_view(self, _, **fields):
        self.view_updates += 1
        self.map.update(fields)


def test_city_retry_recovers_partial_map_without_duplicate_layers():
    api = CityApi()

    assert seed.build_city_in_shade(api) == "city-id"
    assert api.map["visibility"] == "public"
    assert {layer["dataset_id"] for layer in api.map["layers"]} == set(
        api.datasets.values()
    )
    assert api.map["center_lng"] == -73.9795
    assert api.added == 3
    assert api.view_updates == 1

    assert seed.build_city_in_shade(api) == "city-id"
    assert api.added == 3
    assert api.view_updates == 1


def test_city_refuses_unexpected_existing_layer_before_adding_anything():
    api = CityApi()
    api.map["layers"].append({"id": "visitor-layer", "display_name": "Unrelated"})

    with pytest.raises(RuntimeError, match="unexpected layer"):
        seed.build_city_in_shade(api)

    assert api.added == 0
    assert api.view_updates == 0


def test_city_refuses_a_same_named_map_with_different_content():
    api = CityApi()
    api.map["description"] = "Someone else's map"

    with pytest.raises(RuntimeError, match="unexpected description"):
        seed.build_city_in_shade(api)

    assert api.added == 0
    assert api.view_updates == 0


def test_existing_client_sample_must_have_the_expected_published_asset():
    class SampleApi:
        def list_own_datasets(self):
            return [{"title": seed.COPC_TITLE, "id": "wrong-id"}]

        def get_dataset(self, _):
            return {
                "record_type": "pointcloud_dataset",
                "visibility": "public",
                "pointcloud": {"url": "/api/other.copc.laz", "size_bytes": 16},
            }

    with pytest.raises(RuntimeError, match="lacks its published pointcloud asset"):
        seed.build_client_sample(
            SampleApi(),
            None,
            seed.COPC_TITLE,
            seed.COPC_SHA256,
            "pointcloud",
            "summary",
        )


class EnrichApi:
    """The list still reports upload while the detail shows the committed conversion."""

    def __init__(self):
        self.patches = []

    def list_own_datasets(self):
        return [{"title": seed.QUAKES_TITLE, "id": "quakes", "origin": "upload"}]

    def dataset_origin(self, _):
        return "service"

    def patch_dataset(self, _dataset_id, **fields):
        self.patches.append(fields)

    def dataset_record_id(self, _):
        return "record"

    def existing_keywords(self, _):
        return set(seed.SHOWCASE_METADATA[seed.QUAKES_TITLE].get("keywords", ()))


def test_enrich_rechecks_a_lagging_list_origin_before_holding_live_metadata():
    api = EnrichApi()
    seed.enrich_showcase_metadata(api)
    gated = seed.SHOWCASE_METADATA[seed.QUAKES_TITLE]["gated"]
    assert api.patches and gated.items() <= api.patches[0].items()


def test_titles_created_this_run_resolve_while_the_listing_lags():
    api = object.__new__(seed.Api)
    api.created = {}
    api.list_own_datasets = lambda: [{"title": "older", "id": "old-id"}]
    api._created(seed.COPC_TITLE, "copc-id")
    assert api.datasets_by_title() == {seed.COPC_TITLE: "copc-id", "older": "old-id"}


STATE_SCRIPT = repo_root(__file__) / "scripts" / "showcase-121-state.py"
state_spec = importlib.util.spec_from_file_location("showcase_121_state", STATE_SCRIPT)
state = importlib.util.module_from_spec(state_spec)
state_spec.loader.exec_module(state)


def _layer(dataset_id, name, opacity=1.0):
    return {
        "dataset_id": dataset_id,
        "fields": {"display_name": name, "opacity": opacity},
    }


def test_restore_follows_a_layer_the_seed_replaced_under_a_new_id():
    saved = {"maps": {"m": {"layers": {"old": _layer("ds", "Subway", 1.0)}}}}
    current = {"maps": {"m": {"layers": {"new": _layer("ds", "Subway", 0.4)}}}}
    state.rebind_replaced_layers(saved, current)
    assert saved["maps"]["m"]["layers"] == {"new": _layer("ds", "Subway", 1.0)}


def test_restore_does_not_guess_between_two_replacement_candidates():
    saved = {"maps": {"m": {"layers": {"old": _layer("ds", "Subway")}}}}
    current = {
        "maps": {
            "m": {"layers": {"a": _layer("ds", "Subway"), "b": _layer("ds", "Subway")}}
        }
    }
    state.rebind_replaced_layers(saved, current)
    assert list(saved["maps"]["m"]["layers"]) == ["old"]


class TargetApi:
    def __init__(self, maps=(), titles=None, origin="service"):
        self.maps = {name: f"{name}-id" for name in maps}
        self.titles = titles or {seed.QUAKES_TITLE: "q", seed.QUAKES_HEAT_TITLE: "h"}
        self.origin = origin

    def list_maps(self):
        return self.maps

    def datasets_by_title(self):
        return self.titles

    def dataset_origin(self, _):
        return self.origin


def test_guarded_update_accepts_a_service_bound_target_without_legacy_rows():
    assert state.unrestorable_changes(TargetApi()) == []


@pytest.mark.parametrize(
    "api",
    [
        TargetApi(origin="upload"),
        TargetApi(maps=[seed.HURRICANE_MAP_LEGACY]),
        TargetApi(titles={seed.QUAKES_TITLE_LEGACY: "legacy"}),
    ],
)
def test_guarded_update_names_changes_restore_cannot_undo(api):
    assert state.unrestorable_changes(api)


def _verify(name, extra_name, collections=None, datasets=None):
    saved = {
        "base_url": "b",
        "owner": "o",
        "maps": {name: {"id": "m", "created_by": "o", "layers": {}}},
        "datasets": {seed.COPC_TITLE: {"id": "copc", "created_by": "o"}},
        "collections": {},
    }
    current = {
        "maps": {
            name: {
                "id": "m",
                "created_by": "o",
                "layers": {"new": _layer("ds", extra_name)} if extra_name else {},
            }
        },
        "datasets": {
            seed.COPC_TITLE: {"id": "copc", "created_by": "o"},
            **(datasets or {}),
        },
        "collections": collections or {},
    }
    api = type("A", (), {"base": "b", "username": "o"})()
    state.verify_restorable(api, saved, current)


def test_restore_removes_a_new_client_collection_only_when_it_holds_samples():
    _verify("Restless Earth", None, {"Client Connections": {"dataset_ids": ["copc"]}})
    with pytest.raises(RuntimeError, match="unexpected members"):
        _verify(
            "Restless Earth",
            None,
            {"Client Connections": {"dataset_ids": ["copc", "visitor"]}},
        )


def test_restore_accepts_matterhorn_overlay_repair_only_on_matterhorn():
    _verify("The Matterhorn in 3D", "Peaks")
    with pytest.raises(RuntimeError, match="unexpected new layer"):
        _verify("Restless Earth", "Peaks")


class SnapshotApi:
    base = "b"
    username = "o"

    def list_all_maps(self):
        return []

    def list_own_datasets(self):
        return [{"title": "Sentinel-2 TCI S2A_T18TXL_20260918", "id": "scene"}]

    def get_dataset(self, dataset_id):
        return {"id": dataset_id, "created_by": "o", "record_id": "r"}

    def list_collections(self):
        return []


def test_snapshot_captures_datasets_the_seed_patches_by_title_prefix(monkeypatch):
    monkeypatch.setattr(state, "get", lambda _api, _path: {"keywords": []})
    captured = state.snapshot(SnapshotApi())["datasets"]
    assert list(captured) == ["Sentinel-2 TCI S2A_T18TXL_20260918"]


class SwapApi:
    def __init__(self, landed):
        self.landed = landed
        self.swaps = []

    def swap_layer(self, map_id, layer_id, body):
        self.swaps.append((layer_id, body))
        raise seed.httpx.TimeoutException("lost response")

    def get_map(self, _):
        return {"layers": [] if self.landed else [{"id": "old"}]}


@pytest.mark.parametrize("landed", [True, False])
def test_restyle_swaps_in_one_request_and_trusts_the_map_after_a_lost_reply(landed):
    api = SwapApi(landed)
    layer = {"id": "old", "dataset_id": "ds", "display_name": "Subway"}
    if landed:
        seed._restyle_layer(api, "m", layer, fields={"show_in_legend": False})
    else:
        with pytest.raises(seed.httpx.TimeoutException):
            seed._restyle_layer(api, "m", layer, fields={"show_in_legend": False})
    assert api.swaps == [
        ("old", {"dataset_id": "ds", "display_name": "Subway", "show_in_legend": False})
    ]
