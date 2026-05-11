from __future__ import annotations

import importlib.util
import json
from pathlib import Path

_MODULE_PATH = Path(__file__).with_name("fixture_schema.py")
_SPEC = importlib.util.spec_from_file_location("demo_fixture_schema", _MODULE_PATH)
assert _SPEC is not None
assert _SPEC.loader is not None
_fixture_schema = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_fixture_schema)

_APPLY_MODULE_PATH = Path(__file__).with_name("apply_fixture.py")
_APPLY_SPEC = importlib.util.spec_from_file_location(
    "demo_apply_fixture", _APPLY_MODULE_PATH
)
assert _APPLY_SPEC is not None
assert _APPLY_SPEC.loader is not None
_apply_fixture = importlib.util.module_from_spec(_APPLY_SPEC)
_APPLY_SPEC.loader.exec_module(_apply_fixture)

resolve_fixture = _fixture_schema.resolve_fixture
strip_for_fixture = _fixture_schema.strip_for_fixture
fixture_thumbnail_data_uri = _apply_fixture._fixture_thumbnail_data_uri


def test_resolve_fixture_translates_portable_terrain_config() -> None:
    dem_id = "11111111-1111-1111-1111-111111111111"
    fixture = {
        "_meta": {"theme": "When the Land Speaks"},
        "name": "Grand Canyon: Land in 3D",
        "terrain_config": {
            "enabled": True,
            "_source_stem": "grand_canyon_dem",
            "_source_ext": ".tif",
            "exaggeration": 1.5,
        },
        "layers": [
            {
                "_stem": "grand_canyon_dem",
                "_ext": ".tif",
                "sort_order": 0,
                "layer_type": "raster_geolens",
            }
        ],
    }

    resolved = resolve_fixture(fixture, {"grand_canyon_dem.tif": dem_id})

    assert resolved["terrain_config"] == {
        "enabled": True,
        "source_dataset_id": dem_id,
        "exaggeration": 1.5,
    }


def test_resolve_fixture_strips_fixture_only_thumbnail_metadata() -> None:
    dataset_id = "22222222-2222-2222-2222-222222222222"
    fixture = {
        "_meta": {"theme": "When the Land Speaks"},
        "_thumbnail": "thumbnails/example.jpg",
        "name": "Marketing-ready map",
        "layers": [
            {
                "_stem": "example",
                "_ext": ".geojson",
                "sort_order": 0,
                "layer_type": "vector_geolens",
            }
        ],
    }

    resolved = resolve_fixture(fixture, {"example.geojson": dataset_id})

    assert "_thumbnail" not in resolved
    assert resolved["layers"][0]["dataset_id"] == dataset_id


def test_strip_for_fixture_translates_live_terrain_config() -> None:
    dem_id = "11111111-1111-1111-1111-111111111111"
    map_response = {
        "id": "map-id",
        "name": "Grand Canyon: Land in 3D",
        "terrain_config": {
            "enabled": True,
            "source_dataset_id": dem_id,
            "exaggeration": 1.5,
        },
        "layers": [
            {
                "dataset_id": dem_id,
                "sort_order": 0,
                "layer_type": "raster_geolens",
            }
        ],
    }

    fixture = strip_for_fixture(
        map_response,
        {dem_id: ("grand_canyon_dem", ".tif")},
        theme="When the Land Speaks",
    )

    assert fixture["terrain_config"] == {
        "enabled": True,
        "_source_stem": "grand_canyon_dem",
        "_source_ext": ".tif",
        "exaggeration": 1.5,
    }


def test_committed_3d_demo_fixtures_keep_terrain_and_extrusion_hooks() -> None:
    fixtures_dir = Path(__file__).parents[1] / "fixtures" / "maps"
    grand_canyon = json.loads((fixtures_dir / "1-grand-canyon.json").read_text())
    nyc_zoning = json.loads((fixtures_dir / "1-nyc-zoning.json").read_text())
    wildfire = json.loads((fixtures_dir / "2-wildfires.json").read_text())
    earthquakes = json.loads((fixtures_dir / "2-earthquakes.json").read_text())

    assert grand_canyon["terrain_config"] == {
        "enabled": True,
        "_source_stem": "grand_canyon_dem",
        "_source_ext": ".tif",
        "exaggeration": 4.6,
    }
    assert grand_canyon["center_lng"] == -112.34
    assert grand_canyon["center_lat"] == 36.2
    assert grand_canyon["zoom"] == 11.85
    assert grand_canyon["bearing"] == -48.0
    assert grand_canyon["pitch"] == 76.0
    assert grand_canyon["basemap_style"] == "openstreetmap"
    assert grand_canyon["layers"][0]["display_name"] == "Terrain mesh"
    assert grand_canyon["layers"][0]["visible"] is False
    assert grand_canyon["layers"][0]["show_in_legend"] is False
    assert grand_canyon["layers"][0]["style_config"]["render_mode"] == "hillshade"
    assert grand_canyon["terrain_config"]["exaggeration"] == 4.6
    assert grand_canyon["layers"][0]["paint"]["hillshade-exaggeration"] == 1.0
    assert grand_canyon["layers"][1]["display_name"] == "Canyon wall relief"
    assert grand_canyon["layers"][1]["visible"] is True
    assert grand_canyon["layers"][1]["opacity"] == 1.0
    assert grand_canyon["layers"][1]["show_in_legend"] is True
    assert grand_canyon["layers"][1]["paint"]["raster-contrast"] == 0.85
    assert nyc_zoning["layers"][0]["style_config"]["builder"] == {
        "heightColumn": "height",
        "heightScale": 1.8,
        "extrusionMinZoom": 13.2,
        "extrusionOpacity": 0.96,
        "outlineColor": "#07111f",
        "outlineWidth": 0.28,
    }
    assert wildfire["layers"][0]["style_config"]["builder"] == {
        "outlineColor": "#ffcf66",
        "outlineWidth": 0.25,
    }
    assert "_outline-color" not in wildfire["layers"][0]["paint"]
    assert "_outline-width" not in wildfire["layers"][0]["paint"]
    assert earthquakes["layers"][0]["style_config"]["sizes"] == [4, 8, 14, 22, 30]
    assert earthquakes["layers"][0]["style_config"]["sizeLabel"] == "Magnitude"
    assert earthquakes["layers"][0]["style_config"]["colorLabel"] == "Depth (km)"


def test_committed_map_fixtures_ship_local_marketing_thumbnails() -> None:
    fixtures_dir = Path(__file__).parents[1] / "fixtures" / "maps"

    for fixture_path in sorted(fixtures_dir.glob("*.json")):
        fixture = json.loads(fixture_path.read_text())
        thumbnail_ref = fixture.get("_thumbnail")

        assert isinstance(thumbnail_ref, str), fixture_path.name
        thumbnail_path = fixtures_dir / thumbnail_ref
        assert thumbnail_path.is_file(), thumbnail_ref

        data_uri = fixture_thumbnail_data_uri(fixture_path, fixture)
        assert data_uri is not None
        assert data_uri.startswith("data:image/jpeg;base64,")
        assert len(data_uri) < 100_000
