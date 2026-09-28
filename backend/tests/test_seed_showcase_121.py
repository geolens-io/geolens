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


class TargetApi:
    user_id = "u"

    def __init__(
        self,
        maps=(),
        titles=None,
        origin="service",
        visibility="public",
        features=32186,
        description="text",
    ):
        names = state.MAP_NAMES - {seed.CITY_SHADE_MAP} if maps == () else maps
        self.maps = {name: f"{name}-id" for name in names}
        self.jobs = 0
        self.titles = titles or {seed.QUAKES_TITLE: "q", seed.QUAKES_HEAT_TITLE: "h"}
        self.origin = origin
        self.visibility = visibility
        self.features = features
        self.description = description

    def list_maps(self):
        return self.maps

    def datasets_by_title(self):
        return self.titles

    def dataset_origin(self, _):
        return self.origin

    def get_map(self, _):
        return {"visibility": self.visibility, "description": self.description}

    def get_dataset(self, _):
        return {"visibility": self.visibility}

    def dataset_feature_count(self, _):
        return self.features

    def list_collections(self):
        return [{"name": "Human World", "description": self.description}]


@pytest.fixture
def job_counts(monkeypatch):
    counts = {"pending": 0, "running": 0}

    def fake_get(_api, path):
        status = path.split("status=")[1].split("&")[0]
        return {"total": counts[status]}

    monkeypatch.setattr(state, "get", fake_get)
    return counts


def test_guarded_update_accepts_a_service_bound_target_without_legacy_rows(job_counts):
    assert state.unrestorable_changes(TargetApi()) == []


def test_guarded_update_waits_for_a_running_job(job_counts):
    job_counts["running"] = 1
    assert state.unrestorable_changes(TargetApi()) == [
        "this account has pending or running jobs"
    ]


@pytest.mark.parametrize(
    "api",
    [
        TargetApi(origin="upload"),
        TargetApi(maps=[*state.MAP_NAMES, seed.HURRICANE_MAP_LEGACY]),
        TargetApi(maps=[seed.CITY_SHADE_MAP]),
        TargetApi(titles={seed.QUAKES_TITLE_LEGACY: "legacy"}),
        TargetApi(maps=[*state.MAP_NAMES], visibility="private"),
        TargetApi(titles={seed.COPC_TITLE: "copc"}, visibility="private"),
        TargetApi(titles={"Matterhorn Peaks": "peaks"}, visibility="private"),
        TargetApi(
            titles={"Meteorite Landings (Meteoritical Society)": "m"}, features=4800
        ),
        TargetApi(description=None),
        TargetApi(description=""),
    ],
)
def test_guarded_update_names_changes_restore_cannot_undo(api, job_counts):
    assert state.unrestorable_changes(api)


def _verify(name, extra_name, collections=None, datasets=None):
    saved = {
        "base_url": "b",
        "owner": "o",
        "owner_id": "oid",
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


def _client_collection(owner="oid", members=("copc",)):
    return {"Client Connections": {"created_by": owner, "dataset_ids": list(members)}}


def test_restore_removes_a_new_client_collection_only_when_it_holds_samples():
    _verify("Restless Earth", None, _client_collection())
    with pytest.raises(RuntimeError, match="not the seed's own"):
        _verify("Restless Earth", None, _client_collection(members=("copc", "visitor")))


def test_restore_keeps_a_client_collection_another_account_created():
    with pytest.raises(RuntimeError, match="not the seed's own"):
        _verify("Restless Earth", None, _client_collection(owner="visitor"))


def test_restore_accepts_matterhorn_overlay_repair_only_on_matterhorn():
    _verify("The Matterhorn in 3D", "Peaks")
    with pytest.raises(RuntimeError, match="unexpected new layer"):
        _verify("Restless Earth", "Peaks")


class SnapshotApi:
    base = "b"
    username = "o"
    user_id = "oid"

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


class LayerApi:
    def __init__(self):
        self.updates = []

    def update_layer(self, map_id, body):
        self.updates.append(body)


def test_restyle_updates_the_layer_in_place_with_its_whole_body():
    api = LayerApi()
    layer = {
        "id": "old",
        "dataset_id": "ds",
        "display_name": "Subway",
        "style_config": {"builder": {"mode": "simple"}},
    }
    seed._restyle_layer(api, "m", layer, fields={"show_in_legend": False})
    assert api.updates == [
        {
            "id": "old",
            "dataset_id": "ds",
            "display_name": "Subway",
            "style_config": {"builder": {"mode": "simple"}},
            "show_in_legend": False,
        }
    ]


def test_restore_names_a_field_the_target_did_not_take():
    item = {"fields": {"description": None}, "layers": {}}
    saved = {"maps": {"m": item}, "datasets": {}, "collections": {}}
    after = {
        "maps": {"m": {"fields": {"description": "seeded"}, "layers": {}}},
        "datasets": {},
        "collections": {},
    }
    assert state.unrestored(saved, after) == ["map m"]
    assert state.unrestored(saved, saved) == []


def test_restore_reports_new_content_left_public():
    saved = {"maps": {}, "datasets": {}, "collections": {}}
    after = {
        "maps": {},
        "datasets": {seed.COPC_TITLE: {"fields": {"visibility": "public"}}},
        "collections": {"Client Connections": {}},
    }
    assert state.unrestored(saved, after) == [
        f"new dataset {seed.COPC_TITLE} is public",
        "new collection Client Connections",
    ]


class CameraApi:
    def __init__(self, cameras):
        self.cameras = cameras

    def list_maps(self):
        return {name: name for name in self.cameras}

    def get_map(self, name):
        return self.cameras[name]


@pytest.mark.parametrize("key", ["expected", "wanted"])
def test_guarded_preflight_accepts_a_known_camera(key):
    api = CameraApi({name: fix[key] for name, fix in seed.MAP_VIEW_FIXES.items()})
    assert seed.view_baseline_problems(api) == []


def test_guarded_preflight_refuses_an_unknown_camera_before_writing():
    moved = {"center_lng": 0.0, "center_lat": 0.0, "zoom": 3.0}
    api = CameraApi({name: moved for name in seed.MAP_VIEW_FIXES})
    assert len(seed.view_baseline_problems(api)) == len(seed.MAP_VIEW_FIXES)


class UnstylableApi:
    def list_maps(self):
        return {"Restless Earth": "restless"}

    def get_map(self, _):
        raise seed.httpx.TimeoutException("lost response")


def test_styling_reports_a_map_it_could_not_style():
    assert seed.apply_showcase_styling(UnstylableApi()) == ["Restless Earth"]


class UnwritableMetadataApi(EnrichApi):
    def patch_dataset(self, _dataset_id, **_fields):
        raise seed.httpx.TimeoutException("lost response")


def test_enrich_reports_a_dataset_it_could_not_write():
    assert seed.enrich_showcase_metadata(UnwritableMetadataApi()) == [seed.QUAKES_TITLE]


class Page:
    def __init__(self, body):
        self.body = body

    def raise_for_status(self):
        pass

    def json(self):
        return self.body


def test_collections_are_read_past_the_first_page():
    api = object.__new__(seed.Api)
    api.base, api.h = "b", {}
    pages = {0: [{"name": "a"}] * 200, 200: [{"name": "Human World"}]}
    api.client = type(
        "C",
        (),
        {
            "get": lambda self, url, headers: Page(
                {"collections": pages[int(url.split("skip=")[1])], "total": 201}
            )
        },
    )()
    assert api.list_collections()[-1] == {"name": "Human World"}


class PartialRoutesApi:
    def __init__(self):
        self.added = []

    def get_map(self, _):
        names = ["Climbing routes (OSM)", *self.added]
        return {"layers": [{"display_name": name} for name in names]}

    def add_layer(self, _map_id, body):
        self.added.append(body["display_name"])


def test_matterhorn_repair_adds_the_missing_half_of_a_route_pair(monkeypatch):
    fc = {"type": "FeatureCollection", "features": [{"type": "Feature"}]}
    monkeypatch.setattr(seed, "fetch_osm_overlays", lambda _bbox: (fc, fc))
    api = PartialRoutesApi()
    by_title = {"Matterhorn Climbing Routes": "routes", "Matterhorn Peaks": "peaks"}
    seed.ensure_matterhorn_overlays(api, "m", by_title)
    assert api.added == ["Route casing", "Peaks"]
