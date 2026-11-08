"""The Matterhorn terrain: the Copernicus fill under the swissALTI3D tiles."""

from __future__ import annotations

import importlib.util

import pytest

from tests.repo_paths import repo_root


SCRIPT = repo_root(__file__) / "scripts" / "seed-showcase.py"
spec = importlib.util.spec_from_file_location("seed_showcase_matterhorn", SCRIPT)
seed = importlib.util.module_from_spec(spec)
spec.loader.exec_module(seed)


class TerrainApi:
    def __init__(self, terrain=None, layers=()):
        self.map = {"terrain_config": terrain, "layers": list(layers)}
        self.members = None
        self.dem = []
        self.added = []
        self.deleted = []
        self.views = []

    def vrt_create(self, members, title, summary):
        self.members = members
        return "job"

    def poll(self, job, timeout=300):
        return {"dataset_id": "terrain"}

    def patch_dataset(self, dataset_id, **fields):
        self.dem.append((dataset_id, fields))

    def get_map(self, _map_id):
        return self.map

    def add_layer(self, _map_id, body):
        self.added.append(body)

    def delete_layer(self, _map_id, layer_id):
        self.deleted.append(layer_id)

    def set_view(self, _map_id, **fields):
        self.views.append(fields)

    def replace_map_layers(self, _map_id, layers, expected_updated_at):
        self.saved = (layers, expected_updated_at)


def test_matterhorn_terrain_puts_the_copernicus_fill_under_the_swiss_tiles(
    monkeypatch,
):
    monkeypatch.setattr(seed, "_copernicus_fill", lambda _api, _titles: "fill")
    api = TerrainApi()
    by_title = {
        seed.SWISSALTI_MOSAIC_TITLE: "swiss",
        "swissALTI3D 2m 2617-1091 (Matterhorn)": "t2",
        "swissALTI3D 2m 2616-1091 (Matterhorn)": "t1",
    }
    assert seed.matterhorn_terrain(api, by_title) == "terrain"
    assert api.members == ["fill", "t1", "t2"]
    assert api.dem == [("terrain", {"is_dem": True})]
    assert by_title[seed.MATTERHORN_TERRAIN_TITLE] == "terrain"


def test_a_map_on_the_swiss_mosaic_moves_to_the_full_terrain_in_place(
    monkeypatch,
):
    monkeypatch.setattr(seed, "matterhorn_terrain", lambda _api, _titles: "terrain")
    relief = {
        "id": "relief",
        "dataset_id": "swiss",
        "display_name": "swissALTI3D relief",
        "sort_order": 4,
        "opacity": 0.8,
        "paint": {"hillshade-exaggeration": 0.5},
    }
    routes = {"id": "routes", "dataset_id": "routes", "display_name": "Peaks"}
    api = TerrainApi(
        {"enabled": True, "source_dataset_id": "swiss", "exaggeration": 1.2},
        [relief, routes],
    )
    api.map["updated_at"] = "t0"
    seed.move_matterhorn_to_full_terrain(
        api, "m", {seed.SWISSALTI_MOSAIC_TITLE: "swiss"}
    )
    assert api.saved == (
        [
            {
                "id": "relief",
                "dataset_id": "terrain",
                "display_name": seed.MATTERHORN_RELIEF_LAYER,
                "sort_order": 4,
                "opacity": 0.8,
                "paint": {"hillshade-exaggeration": 0.5},
            },
            {"id": "routes", "dataset_id": "routes", "display_name": "Peaks"},
        ],
        "t0",
    )
    assert api.added == api.deleted == []
    assert api.views == [
        {
            "terrain_config": {
                "enabled": True,
                "source_dataset_id": "terrain",
                "exaggeration": 1.2,
            }
        }
    ]


def test_a_map_on_another_terrain_is_left_alone(monkeypatch):
    monkeypatch.setattr(seed, "matterhorn_terrain", pytest.fail)
    api = TerrainApi({"enabled": True, "source_dataset_id": "terrain"})
    seed.move_matterhorn_to_full_terrain(
        api, "m", {seed.SWISSALTI_MOSAIC_TITLE: "swiss"}
    )
    assert api.added == api.deleted == api.views == []


def test_partial_swiss_tiles_without_a_mosaic_rerun_the_manifest(monkeypatch):
    monkeypatch.setattr(seed, "fetch_swissalti_tiles", lambda: {})
    with pytest.raises(RuntimeError, match="no swissALTI3D 2m tiles"):
        seed._swissalti_tile_ids(
            object(), {"swissALTI3D 2m 2616-1090 (Matterhorn)": "t"}
        )


def test_a_failed_warp_is_a_builder_error(monkeypatch):
    def missing(*_a, **_kw):
        raise FileNotFoundError("gdalwarp")

    monkeypatch.setattr(seed.subprocess, "run", missing)
    with pytest.raises(RuntimeError, match="gdalwarp could not build"):
        seed._copernicus_fill(object(), {})
