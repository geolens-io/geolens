"""Showcase content polish: legend labels, credits, camera framing, layer names.

Database-free: a fake Api holds map documents the styling pass reads and writes.
"""

from __future__ import annotations

import importlib.util
import io

import pytest

from tests.repo_paths import repo_root

SCRIPT_PATH = repo_root(__file__) / "scripts" / "seed-showcase.py"


def _load_seeder():
    spec = importlib.util.spec_from_file_location("seed_showcase_polish", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


seed = _load_seeder()

QUAKES = "Earthquakes (last 30 days, by magnitude)"
VOLCANOES = "Major eruptions (VEI 4+ or 100+ deaths)"
METEORITES = "Meteorites (amber = seen falling)"
OLD_LEGS = "Category 3+ storm legs (the buffered input)"
OLD_BASIN = "Atlantic basin regions (hatched where no major storm passed within 100 km)"


def _layer(name: str, **fields) -> dict:
    return {
        "id": f"id-{name}",
        "dataset_id": f"ds-{name}",
        "display_name": name,
        **fields,
    }


class StylingApi:
    """Maps as stored; layer updates and view writes land on them."""

    def __init__(self, maps: dict[str, dict]):
        self.maps = {name: {"id": name, **doc} for name, doc in maps.items()}
        self.layer_updates = 0

    def list_maps(self):
        return {name: name for name in self.maps}

    def get_map(self, map_id):
        return self.maps[map_id]

    def datasets_by_title(self):
        return {}

    def set_view(self, map_id, **fields):
        self.maps[map_id].update(fields)

    def update_layer(self, map_id, body):
        self.layer_updates += 1
        layer = next(x for x in self.maps[map_id]["layers"] if x["id"] == body["id"])
        layer.update(body)


def _stored_maps() -> dict[str, dict]:
    quake_style = {"mode": "graduated", "column": "mag"}
    return {
        seed.DASHBOARD_MAP: {
            "center_lng": 0,
            "center_lat": 20,
            "zoom": 1.4,
            "layers": [_layer(QUAKES, paint={}, style_config=None)],
        },
        "Restless Earth": {
            "layers": [
                _layer(QUAKES, style_config=quake_style),
                _layer(VOLCANOES, style_config=None),
            ],
        },
        "Everything That Fell From the Sky": {
            "layers": [_layer(METEORITES, style_config={"column": "fall"})],
        },
        seed.EXPOSURE_MAP: {
            "layers": [
                _layer(OLD_LEGS, paint={"line-color": "#1e293b"}, visible=False),
                _layer(OLD_BASIN, paint={"fill-opacity": 0.22}),
                _layer(
                    seed.EXPOSURE_LAYER_NAME,
                    paint={"fill-outline-color": "#7f1d1d"},
                ),
            ],
        },
        seed.ORBIT_MAP: {
            "layers": [
                _layer("Sentinel-2 - 2026-08-29 (T18TXK)"),
                _layer("Sentinel-2 - 2026-08-29 (T18TWL)"),
                _layer("Sentinel-2 - 2026-09-08"),
            ],
        },
        seed.CITY_SHADE_MAP: {
            "center_lng": -73.9795,
            "center_lat": 40.7261,
            "zoom": 15.4,
            "layers": [],
        },
    }


def _layer_named(api, map_name, name):
    return next(x for x in api.maps[map_name]["layers"] if x["display_name"] == name)


def test_styling_gives_every_legend_a_label_instead_of_a_column_name():
    api = StylingApi(_stored_maps())
    assert seed.apply_showcase_styling(api) == []

    dashboard = _layer_named(api, seed.DASHBOARD_MAP, QUAKES)["style_config"]
    assert (dashboard["column"], dashboard["sizeLabel"]) == ("mag", "Magnitude")
    volcano = _layer_named(api, "Restless Earth", VOLCANOES)["style_config"]
    assert (volcano["column"], volcano["sizeLabel"]) == ("vei", "Explosivity (VEI)")
    quakes = _layer_named(api, "Restless Earth", QUAKES)["style_config"]
    assert quakes["column"] == "mag"
    meteorites = _layer_named(api, "Everything That Fell From the Sky", METEORITES)
    assert meteorites["style_config"] == {
        "column": "fall",
        "colorLabel": "Recovery",
        "sizeLabel": "Mass (kg)",
    }


def test_styling_shortens_the_hurricane_exposure_legend_rows_and_mutes_the_context():
    api = StylingApi(_stored_maps())
    seed.apply_showcase_styling(api)

    legs = _layer_named(api, seed.EXPOSURE_MAP, seed.EXPOSURE_LEGS_NAME)
    basin = _layer_named(api, seed.EXPOSURE_MAP, seed.BASIN_CONTEXT_NAME)
    assert legs["visible"] is True
    exposure = _layer_named(api, seed.EXPOSURE_MAP, seed.EXPOSURE_LAYER_NAME)
    assert exposure["paint"]["fill-outline-color"] == seed.EXPOSURE_OUTLINE_COLOR
    assert legs["paint"]["line-color"] == seed.EXPOSURE_LEGS_PAINT["line-color"]
    assert basin["paint"]["fill-opacity"] < 0.22
    assert not any(
        "buffered input" in x["display_name"] or len(x["display_name"]) > 32
        for x in api.maps[seed.EXPOSURE_MAP]["layers"]
    )


def test_styling_names_orbit_scenes_by_where_they_lie_not_by_tile_code():
    api = StylingApi(_stored_maps())
    seed.apply_showcase_styling(api)
    names = [x["display_name"] for x in api.maps[seed.ORBIT_MAP]["layers"]]
    assert names == [
        "Sentinel-2 - 2026-08-29 (south-east)",
        "Sentinel-2 - 2026-08-29 (north-west)",
        "Sentinel-2 - 2026-09-08",
    ]


def test_styling_reframes_the_dashboard_and_city_in_shade_maps():
    api = StylingApi(_stored_maps())
    seed.apply_showcase_styling(api)
    dashboard = api.maps[seed.DASHBOARD_MAP]
    assert dashboard["center_lng"] == seed.DASHBOARD_CAMERA["center_lng"]
    assert api.maps[seed.CITY_SHADE_MAP]["zoom"] > 15.4


def test_styling_a_second_time_changes_nothing():
    api = StylingApi(_stored_maps())
    seed.apply_showcase_styling(api)
    writes = api.layer_updates
    before = repr(api.maps)
    seed.apply_showcase_styling(api)
    assert (api.layer_updates, repr(api.maps)) == (writes, before)


def test_a_moved_dashboard_camera_is_left_alone():
    stored = _stored_maps()
    stored[seed.DASHBOARD_MAP].update(center_lng=12, zoom=3)
    api = StylingApi(stored)
    seed.apply_showcase_styling(api)
    assert api.maps[seed.DASHBOARD_MAP]["center_lng"] == 12


@pytest.mark.parametrize(
    "title",
    [
        "Manhattan Building Heights",
        "NYC Subway Lines (MTA)",
        "NYC Subway Stations (MTA)",
        "swissALTI3D Matterhorn DEM (2m mosaic)",
        "swissALTI3D 2m tile",
        "Matterhorn Peaks",
        "Matterhorn Climbing Routes",
        "Meteorite Landings (Meteoritical Society)",
        seed.CITY_SHADE_SOURCE,
        seed.CITY_SHADE_RESULT,
        seed.HURDAT2_TRACKS_TITLE,
        seed.HURDAT2_LEGS_TITLE,
    ],
)
def test_showcase_datasets_carry_a_data_credit(title):
    assert seed._metadata_spec(title)["attribution"]


def test_new_york_tile_layers_are_named_by_area():
    item = {"datetime_start": "2026-08-29T15:57:05Z", "id": "S2A_T18TXL_20260829T1_L2A"}
    assert seed._sentinel2_layer_label(item) == "2026-08-29 (north-east)"
    other = {**item, "id": "S2A_T19TCH_20260829T1_L2A"}
    assert seed._sentinel2_layer_label(other) == "2026-08-29 (T19TCH)"


def test_skyline_cameras_stay_within_the_pitch_a_map_allows():
    assert max(c["pitch"] for c in seed.SKYLINE_CAMERAS.values()) <= 60


@pytest.mark.parametrize(
    ("label", "phrase"),
    [
        ("Woolworth Building", "the Woolworth Building"),
        ("a tower completed in 2018", "a tower completed in 2018"),
        ("The Dakota", "The Dakota"),
    ],
)
def test_a_building_name_reads_as_a_noun_phrase(label, phrase):
    assert seed._the(label) == phrase


def test_skyline_photo_captions_are_short_and_the_credit_is_written_once():
    captions = [p["caption"] for p in seed.SKYLINE_PHOTOS]
    assert all(len(c) < 70 for c in captions)
    assert not any("Library of Congress" in c for c in captions)


# --- orbit framing ----------------------------------------------------------

NOMINAL = {"center": [-74.015, 40.725], "zoom": 10.0, "bearing": 0, "pitch": 0}


def _passes(*scenes):
    layers = [{"id": f"l{i}", "dataset_id": f"ds{i}"} for i in range(len(scenes))]
    return {"2026-09-11": layers}, {lay["id"]: b for lay, b in zip(layers, scenes)}


class TilesApi:
    def __init__(self, lit):
        self.lit = lit
        self.requests = 0

    def raster_tile(self, dataset_id, z, x, y):
        from PIL import Image

        self.requests += 1
        west, south, east, north = seed._tile_bbox(z, x, y)
        shade = (40, 90, 60) if self.lit(west, east) else (0, 0, 0)
        out = io.BytesIO()
        Image.new("RGB", (256, 256), shade).save(out, "JPEG")
        return out.getvalue()


def _view(camera):
    return seed._view_bbox(camera, seed._FRAMING_SIZE)


def test_framing_keeps_a_camera_whose_view_the_scenes_fill(monkeypatch):
    monkeypatch.setattr(seed, "_has_pillow", lambda: False)
    passes, bounds = _passes([-76.0, 39.0, -72.0, 42.0])
    camera, visible = seed._orbit_framing(None, passes, bounds, "2026-09-11", NOMINAL)
    assert camera == NOMINAL and visible == {"l0": True}


def test_framing_moves_off_a_scene_edge_that_cuts_the_view(monkeypatch):
    monkeypatch.setattr(seed, "_has_pillow", lambda: False)
    passes, bounds = _passes([-76.0, 39.0, -73.85, 42.0])
    camera, _ = seed._orbit_framing(None, passes, bounds, "2026-09-11", NOMINAL)
    assert camera != NOMINAL
    assert _view(camera)[2] <= -73.85


def test_framing_falls_back_to_the_nominal_camera_when_nothing_fills_the_view(
    monkeypatch, capsys
):
    monkeypatch.setattr(seed, "_has_pillow", lambda: False)
    passes, bounds = _passes([-74.016, 40.7, -74.014, 40.75])
    camera, _ = seed._orbit_framing(None, passes, bounds, "2026-09-11", NOMINAL)
    assert camera == NOMINAL
    assert "fills the view" in capsys.readouterr().out


def test_framing_avoids_empty_pixels_inside_a_scenes_bounds(monkeypatch):
    pytest.importorskip("PIL.Image")
    monkeypatch.setattr(seed, "_has_pillow", lambda: True)
    # The tile's bounds reach far east, but its pixels stop at -73.83.
    passes, bounds = _passes([-76.0, 39.0, -72.0, 42.0])
    api = TilesApi(lambda west, east: east <= -73.828)
    camera, _ = seed._orbit_framing(api, passes, bounds, "2026-09-11", NOMINAL)
    assert camera != NOMINAL
    assert _view(camera)[2] <= -73.828 + 0.02
    assert api.requests > 0


def test_framing_keeps_the_named_pass_in_view(monkeypatch):
    monkeypatch.setattr(seed, "_has_pillow", lambda: False)
    # The newest pass only grazes the nominal view's east edge; an older one
    # covers the west, so a camera moved west would show only the older pass.
    layers = {"2026-09-11": [{"id": "new", "dataset_id": "a"}]}
    layers["2026-08-29"] = [{"id": "old", "dataset_id": "b"}]
    bounds = {"new": [-73.7, 39.0, -70.0, 42.0], "old": [-78.0, 39.0, -73.85, 42.0]}
    camera, visible = seed._orbit_framing(None, layers, bounds, "2026-09-11", NOMINAL)
    assert visible["new"] is True
    assert _view(camera)[2] > -73.7


class PassTilesApi:
    """Tiles lit or black per dataset."""

    def __init__(self, lit_datasets):
        self.lit = lit_datasets

    def raster_tile(self, dataset_id, z, x, y):
        from PIL import Image

        shade = (40, 90, 60) if dataset_id in self.lit else (0, 0, 0)
        out = io.BytesIO()
        Image.new("RGB", (256, 256), shade).save(out, "JPEG")
        return out.getvalue()


def test_framing_needs_imagery_from_the_named_pass(monkeypatch, capsys):
    pytest.importorskip("PIL.Image")
    monkeypatch.setattr(seed, "_has_pillow", lambda: True)
    # The newest pass's bounds cover the view but its pixels there are empty;
    # an older, broader scene is lit everywhere.
    layers = {"2026-09-11": [{"id": "new", "dataset_id": "a"}]}
    layers["2026-08-29"] = [{"id": "old", "dataset_id": "b"}]
    bounds = {"new": [-74.1, 40.6, -73.9, 40.8], "old": [-78.0, 38.0, -70.0, 43.0]}
    camera, _ = seed._orbit_framing(
        PassTilesApi({"b"}), layers, bounds, "2026-09-11", NOMINAL
    )
    assert camera == NOMINAL
    assert "fills the view" in capsys.readouterr().out


def test_framing_keeps_manhattan_on_a_phone_map(monkeypatch):
    monkeypatch.setattr(seed, "_has_pillow", lambda: False)
    # Imagery ends just west of Manhattan, so the nearest view it fills is a
    # closer camera shifted west, which on a phone shows New Jersey with
    # Manhattan off the edge. The nominal camera stands instead.
    passes, bounds = _passes([-74.6, 40.0, -74.03, 41.5])
    camera, _ = seed._orbit_framing(None, passes, bounds, "2026-09-11", NOMINAL)
    assert camera == NOMINAL
