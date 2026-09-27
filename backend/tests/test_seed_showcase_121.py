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

    with pytest.raises(RuntimeError, match="missing its published pointcloud asset"):
        seed.build_client_sample(
            SampleApi(),
            None,
            seed.COPC_TITLE,
            seed.COPC_SHA256,
            "pointcloud",
            "summary",
        )
