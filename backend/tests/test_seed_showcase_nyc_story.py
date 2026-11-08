"""The New York showcase story seed: valid document, names resolved, rerun in place.

Database-free: a fake Api records what the pass sends, and the payload is
checked against the server's own request schema.
"""

from __future__ import annotations

import importlib.util
import inspect
import re
import uuid

import pytest

from app.modules.catalog.stories.schemas import StoryDocumentInput
from tests.repo_paths import repo_root

SCRIPT_PATH = repo_root(__file__) / "scripts" / "seed-showcase.py"


def _load_seeder():
    spec = importlib.util.spec_from_file_location("seed_showcase_nyc", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


seeder = _load_seeder()


@pytest.fixture(autouse=True)
def single_tile(monkeypatch):
    """The fake tiles are not images, so the stitch stays off unless a test asks."""
    monkeypatch.setattr(seeder, "_has_pillow", lambda: False)


ASSET = "77777777-7777-4777-8777-777777777777"
CROP = b"a rendered tile"


def _layer(name: str, dataset: str) -> dict:
    return {"id": str(uuid.uuid4()), "dataset_id": dataset, "display_name": name}


class NycFakeApi:
    def __init__(self, orbit_dates=("2026-09-11", "2026-09-11", "2026-09-04")):
        self.map_ids = {
            name: str(uuid.uuid4())
            for name in (
                seeder.ORBIT_MAP,
                seeder.SKYLINE_MAP,
                seeder.CITY_SHADE_MAP,
                seeder.DASHBOARD_MAP,
            )
        }
        self.docs = {
            self.map_ids[seeder.ORBIT_MAP]: {
                "id": self.map_ids[seeder.ORBIT_MAP],
                "center_lng": -74.015,
                "center_lat": 40.725,
                "zoom": 11.1,
                "layers": [
                    _layer(f"Sentinel-2 - {day} (T18T{i})", f"ds-scene-{i}")
                    for i, day in enumerate(orbit_dates)
                ],
            },
            self.map_ids[seeder.SKYLINE_MAP]: {
                "id": self.map_ids[seeder.SKYLINE_MAP],
                "center_lng": -73.98,
                "center_lat": 40.754,
                "zoom": 14.4,
                "layers": [
                    _layer("Buildings (3D height, colored by era)", "ds-buildings"),
                    _layer("Subway (official MTA colors)", "ds-lines"),
                    _layer("Stations (green = ADA accessible)", "ds-stations"),
                ],
            },
            self.map_ids[seeder.CITY_SHADE_MAP]: {
                "id": self.map_ids[seeder.CITY_SHADE_MAP],
                "center_lng": -73.9795,
                "center_lat": 40.7261,
                "zoom": 15.4,
                "layers": [
                    _layer("Canopy change in the study window", "ds-canopy"),
                    _layer("Rectangular study window", "ds-window"),
                    _layer("East Village source subset", "ds-source"),
                ],
            },
        }
        self.stories = {seeder.STORY_TITLE: str(uuid.uuid4())}
        self.published: list[tuple[dict, str | None]] = []
        self.stories_created = 0
        self.uploads = 0
        self.uploaded: list[bytes] = []
        self.crop = CROP
        self.max_roof = 1550.0
        self.tiles: list[tuple] = []
        self.bounds = [-75.0, 40.0, -73.0, 42.0]

    def list_maps(self):
        return dict(self.map_ids)

    def datasets_by_title(self):
        return {
            seeder.SKYLINE_BUILDINGS_TITLE: "ds-buildings",
            "NYC Subway Stations (MTA)": "ds-stations",
            seeder.CITY_SHADE_RESULT: "ds-canopy",
        }

    def get_map(self, map_id):
        return self.docs[map_id]

    def list_stories(self):
        return dict(self.stories)

    def create_story(self, title, summary):
        self.stories_created += 1
        self.stories[title] = str(uuid.uuid4())
        return self.stories[title]

    def public_app_url(self):
        return "https://geolens.example"

    def aggregate(self, dataset_id, **body):
        if body["op"] == "count":
            return {"count": 1234}
        if body["op"] == "stats":
            return {"max": self.max_roof}
        return {
            "values": [
                {"value": "Gain", "count": 11},
                {"value": "Loss", "count": 7},
                {"value": "No Change", "count": 3},
            ]
        }

    def raster_bounds(self, dataset_id):
        if isinstance(self.bounds, dict):
            return self.bounds[dataset_id]
        return self.bounds

    def raster_tile(self, dataset_id, z, x, y):
        self.tiles.append((dataset_id, z))
        return self.crop

    def upload_story_asset(self, story_id, filename, data):
        self.uploads += 1
        self.uploaded.append(data)
        return ASSET

    def story_cover_asset(self, story_id):
        return self.published[-1][1] if self.published else None

    def publish_story(self, story_id, title, summary, document, cover_asset_id=None):
        self.published.append((document, cover_asset_id))


def _document(api: NycFakeApi) -> StoryDocumentInput:
    return StoryDocumentInput.model_validate(api.published[-1][0])


def _visible(chapter) -> dict[str, bool]:
    return {str(k): v for k, v in chapter.scene.layer_visibility.items()}


def _ids(api: NycFakeApi, map_name: str, *names: str) -> list[str]:
    layers = {
        lay["display_name"]: lay["id"]
        for lay in api.docs[api.map_ids[map_name]]["layers"]
    }
    return [layers[name] for name in names]


def test_story_has_six_chapters_with_their_transitions_and_cameras():
    api = NycFakeApi()
    seeder.seed_nyc_story(api)
    chapters = _document(api).chapters

    assert [c.title for c in chapters] == [
        "From orbit",
        "A week earlier",
        "The skyline",
        "Turn the city",
        "What runs beneath",
        "Down to the trees",
    ]
    assert [c.scene.transition for c in chapters] == [
        "fly",
        "glide",
        "fly",
        "glide",
        "fly",
        "fly",
    ]
    cameras = [c.scene.camera for c in chapters]
    assert cameras[0] == cameras[1]
    assert (cameras[0].zoom, cameras[0].center) == (10.0, (-74.015, 40.725))
    assert (cameras[2].pitch, cameras[2].bearing) == (60, -28)
    assert (cameras[3].pitch, cameras[3].bearing) == (60, 120)
    assert cameras[4].pitch == 45
    assert (cameras[5].center, cameras[5].zoom) == ((-73.9795, 40.7261), 15.4)


def test_chapters_switch_the_named_layers():
    api = NycFakeApi()
    seeder.seed_nyc_story(api)
    chapters = _document(api).chapters
    orbit = api.docs[api.map_ids[seeder.ORBIT_MAP]]["layers"]
    newest = {lay["id"] for lay in orbit if "2026-09-11" in lay["display_name"]}
    earlier = {lay["id"] for lay in orbit if "2026-09-04" in lay["display_name"]}

    assert {k for k, v in _visible(chapters[0]).items() if v} == newest
    assert {k for k, v in _visible(chapters[1]).items() if v} == earlier
    assert set(_visible(chapters[1])) == {lay["id"] for lay in orbit}

    buildings, subway, stations = _ids(
        api,
        seeder.SKYLINE_MAP,
        "Buildings (3D height, colored by era)",
        "Subway (official MTA colors)",
        "Stations (green = ADA accessible)",
    )
    for chapter in chapters[2:4]:
        assert _visible(chapter) == {buildings: True, subway: False, stations: False}
    assert _visible(chapters[4]) == {buildings: False, subway: True, stations: True}
    assert set(_visible(chapters[5]).values()) == {True}
    assert len(_visible(chapters[5])) == 3


def test_chapters_carry_their_blocks_and_link_targets_found_by_name():
    api = NycFakeApi()
    seeder.seed_nyc_story(api)
    chapters = _document(api).chapters
    kinds = [[b.type for b in c.blocks] for c in chapters]
    assert kinds == [
        ["markdown"],
        ["markdown", "separator"],
        ["markdown"],
        ["markdown"],
        ["markdown", "button"],
        ["markdown", "button", "separator", "button", "button"],
    ]
    manhattan = chapters[4].blocks[1].config.url
    shade, dashboard, hurricanes = (
        b.config.url for b in chapters[5].blocks if b.type == "button"
    )
    assert (
        manhattan == f"https://geolens.example/maps/{api.map_ids[seeder.SKYLINE_MAP]}"
    )
    assert shade == f"https://geolens.example/maps/{api.map_ids[seeder.CITY_SHADE_MAP]}"
    assert (
        dashboard == f"https://geolens.example/maps/{api.map_ids[seeder.DASHBOARD_MAP]}"
    )
    assert hurricanes == (
        f"https://geolens.example/stories/{api.stories[seeder.STORY_TITLE]}"
    )
    assert [str(c.scene.map_id) for c in chapters] == [
        api.map_ids[seeder.ORBIT_MAP],
        api.map_ids[seeder.ORBIT_MAP],
        api.map_ids[seeder.SKYLINE_MAP],
        api.map_ids[seeder.SKYLINE_MAP],
        api.map_ids[seeder.SKYLINE_MAP],
        api.map_ids[seeder.CITY_SHADE_MAP],
    ]


def test_seeder_hard_codes_no_ids():
    source = inspect.getsource(seeder.seed_nyc_story)
    assert not re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-", source)


def test_the_crop_is_the_cover_and_is_not_repeated_inline():
    api = NycFakeApi()
    seeder.seed_nyc_story(api)
    document = _document(api)
    assert api.published[0][1] == ASSET
    assert not [b for c in document.chapters for b in c.blocks if b.type == "image"]
    assert "Contains modified Copernicus Sentinel data" in (
        document.chapters[0].blocks[0].config.text
    )


def test_story_shows_the_chapter_navigation_bar():
    api = NycFakeApi()
    seeder.seed_nyc_story(api)
    assert _document(api).settings.navigation is True


@pytest.mark.parametrize("zoom", [10, 11, 12, 13, 14])
def test_the_crop_is_the_first_tile_one_scene_covers_whole(zoom):
    api = NycFakeApi()
    x, y = seeder._tile_at(-74.015, 40.725, zoom)
    api.bounds = list(seeder._tile_bbox(zoom, x, y))
    seeder.seed_nyc_story(api)
    assert [z for _, z in api.tiles] == [zoom]


def test_no_covering_scene_refuses_the_story():
    api = NycFakeApi()
    api.bounds = [10.0, 10.0, 11.0, 11.0]
    with pytest.raises(RuntimeError, match="no single Sentinel-2 scene"):
        seeder.seed_nyc_story(api)
    assert api.published == []


def test_rerun_updates_the_one_story_and_reuses_the_image():
    api = NycFakeApi()
    seeder.seed_nyc_story(api)
    seeder.seed_nyc_story(api)
    assert api.stories_created == 1
    assert api.uploads == 1
    assert api.published[0] == api.published[1]

    api.crop = b"a newer scene"
    seeder.seed_nyc_story(api)
    assert api.uploads == 1
    assert api.tiles == [("ds-scene-0", 10)]


def test_earlier_pass_title_follows_the_real_gap():
    api = NycFakeApi(orbit_dates=("2026-09-11", "2026-09-06"))
    seeder.seed_nyc_story(api)
    chapter = _document(api).chapters[1]
    assert chapter.title == "An earlier pass"
    assert "5 days" in chapter.blocks[0].config.text


def test_one_acquisition_date_refuses_the_story():
    api = NycFakeApi(orbit_dates=("2026-09-11", "2026-09-11"))
    with pytest.raises(RuntimeError, match="at least two dates"):
        seeder.seed_nyc_story(api)


def test_missing_prerequisites_refuse_the_story():
    api = NycFakeApi()
    del api.stories[seeder.STORY_TITLE]
    with pytest.raises(RuntimeError, match="seed those first"):
        seeder.seed_nyc_story(api)
    assert api.published == []


def test_single_tile_image_is_logged_as_low_resolution(capsys):
    api = NycFakeApi()
    seeder.seed_nyc_story(api)
    assert "single 256 px tile (low" in capsys.readouterr().out
    assert len(api.tiles) == 1


def test_stitched_image_is_the_sixteen_tiles_two_zooms_down(monkeypatch):
    Image = pytest.importorskip("PIL.Image")
    import io

    monkeypatch.setattr(seeder, "_has_pillow", lambda: True)
    api = NycFakeApi()

    def solid(dataset_id, z, x, y):
        api.tiles.append((x, y, z))
        out = io.BytesIO()
        Image.new("RGB", (256, 256), (20, 90, 160)).save(out, "PNG")
        return out.getvalue()

    api.raster_tile = solid
    seeder.seed_nyc_story(api)

    stitched = [(x, y) for x, y, z in api.tiles if z == 12]
    assert len(stitched) == 16
    base_x, base_y = seeder._tile_at(-74.015, 40.725, 10)
    grid = set(stitched)
    assert grid == {
        (base_x * 4 + c, base_y * 4 + r) for r in range(4) for c in range(4)
    }
    uploaded = api.uploaded[0]
    with Image.open(io.BytesIO(uploaded)) as image:
        assert (image.size, image.format) == ((1024, 1024), "JPEG")


def _without_orbit_map(api):
    del api.map_ids[seeder.ORBIT_MAP]


def test_default_seed_skips_the_story_when_an_input_is_absent(capsys):
    api = NycFakeApi()
    _without_orbit_map(api)
    result = seeder.seed_nyc_story_if_ready(api)
    assert result.startswith("(missing: ") and seeder.ORBIT_MAP in result
    assert api.published == []
    line = seeder._builder_outcome_line("nyc-story", result)
    assert line is not None and "skipped" in line and seeder.ORBIT_MAP in line


def test_story_and_dashboard_run_continues_past_the_missing_input(monkeypatch, capsys):
    for name in (
        "set_attribute_titles",
        "seed_hurricane_story",
        "seed_quake_dashboard",
        "seed_skyline_dashboard",
        "seed_skyline_story",
    ):
        monkeypatch.setattr(seeder, name, lambda api, *a, **k: None)
    api = NycFakeApi()
    _without_orbit_map(api)
    assert seeder.run_story_and_dashboard(api) == 0
    assert "skipped, not built yet" in capsys.readouterr().out
    assert api.published == []


def test_ready_inputs_build_the_story_through_the_default_path():
    api = NycFakeApi()
    assert seeder.seed_nyc_story_if_ready(api) not in (None, "")
    assert len(api.published) == 1


def test_only_nyc_story_still_raises_when_an_input_is_absent():
    api = NycFakeApi()
    _without_orbit_map(api)
    with pytest.raises(RuntimeError, match=r"missing map .*seed those first"):
        seeder.seed_nyc_story(api)


def _wide(west=-75.0, east=-72.0):
    return [west, 40.0, east, 42.0]


def test_crop_scene_is_the_newest_one_that_covers_the_tile():
    api = NycFakeApi(orbit_dates=("2026-09-11", "2026-09-04", "2026-08-28"))
    api.bounds = {
        "ds-scene-0": [-73.5, 40.5, -73.0, 41.0],
        "ds-scene-1": _wide(),
        "ds-scene-2": _wide(),
    }
    seeder.seed_nyc_story(api)
    chapters = _document(api).chapters
    assert {dataset for dataset, _ in api.tiles} == {"ds-scene-1"}
    assert "2026-09-04" in chapters[0].blocks[0].config.text
    assert "2026-08-28" in chapters[1].blocks[0].config.text
    assert chapters[1].title == "A week earlier"


def test_chapters_follow_the_view_while_the_crop_comes_from_the_covering_scene():
    """The only scene covering the crop is the oldest; a newer tile meets the view."""
    api = NycFakeApi(orbit_dates=("2026-09-11", "2026-08-29"))
    api.bounds = {
        "ds-scene-0": [-73.9, 40.5, -73.0, 41.0],
        "ds-scene-1": _wide(),
    }
    seeder.seed_nyc_story(api)
    first, second = _document(api).chapters[:2]
    assert "saw it on 2026-09-11" in first.blocks[0].config.text
    assert "2026-08-29" in second.blocks[0].config.text
    assert {dataset for dataset, _ in api.tiles} == {"ds-scene-1"}


def test_a_view_spanning_two_tiles_keeps_both_visible_in_both_chapters():
    api = NycFakeApi(orbit_dates=("2026-09-11", "2026-09-04"))
    api.bounds = {
        "ds-scene-0": _wide(east=-74.0),
        "ds-scene-1": _wide(west=-74.0),
    }
    seeder.seed_nyc_story(api)
    first, second = _document(api).chapters[:2]
    assert first.scene.camera == second.scene.camera
    assert set(_visible(first).values()) == {True}
    assert set(_visible(second).values()) == {True}
    assert len(_visible(first)) == 2


def test_a_layer_outside_the_view_is_hidden():
    api = NycFakeApi(orbit_dates=("2026-09-11", "2026-09-04", "2026-08-28"))
    api.bounds = {
        "ds-scene-0": _wide(),
        "ds-scene-1": _wide(),
        "ds-scene-2": [10.0, 10.0, 11.0, 11.0],
    }
    seeder.seed_nyc_story(api)
    far = api.docs[api.map_ids[seeder.ORBIT_MAP]]["layers"][2]["id"]
    assert _visible(_document(api).chapters[0])[far] is False


def test_an_unparseable_date_is_skipped_with_a_log_line(capsys):
    api = NycFakeApi(orbit_dates=("2026-09-11", "2026-13-45", "2026-09-04"))
    skipped = api.docs[api.map_ids[seeder.ORBIT_MAP]]["layers"][1]["id"]
    seeder.seed_nyc_story(api)
    assert _visible(_document(api).chapters[0])[skipped] is False
    assert "not a calendar date" in capsys.readouterr().out


def test_rejected_orbit_layers_are_switched_off_in_every_orbit_chapter():
    api = NycFakeApi(orbit_dates=("2026-09-11", "2026-09-04", "2026-13-45"))
    layers = api.docs[api.map_ids[seeder.ORBIT_MAP]]["layers"]
    invalid = layers[2]["id"]
    nameless = _layer("x", "ds-nameless")
    nameless["display_name"] = None
    other = _layer("Roads", "ds-roads")
    layers.extend([nameless, other])
    seeder.seed_nyc_story(api)
    for chapter in _document(api).chapters[:2]:
        visible = _visible(chapter)
        for rejected in (invalid, nameless["id"], other["id"]):
            assert visible[rejected] is False


@pytest.mark.parametrize("zoom", [13, 14])
def test_deep_crops_skip_the_stitch(monkeypatch, zoom):
    monkeypatch.setattr(seeder, "_has_pillow", lambda: True)
    api = NycFakeApi()
    x, y = seeder._tile_at(-74.015, 40.725, zoom)
    api.bounds = list(seeder._tile_bbox(zoom, x, y))
    seeder.seed_nyc_story(api)
    assert [z for _, z in api.tiles] == [zoom]


def test_counts_come_from_the_datasets_the_scenes_display():
    api = NycFakeApi()
    seen = []
    plain = api.aggregate
    api.aggregate = lambda dataset_id, **body: (
        seen.append(dataset_id) or plain(dataset_id, **body)
    )
    api.datasets_by_title = lambda: {
        seeder.SKYLINE_BUILDINGS_TITLE: "ds-stale-buildings",
        "NYC Subway Stations (MTA)": "ds-stale-stations",
        seeder.CITY_SHADE_RESULT: "ds-stale-canopy",
    }
    seeder.seed_nyc_story(api)
    assert set(seen) == {"ds-buildings", "ds-stations", "ds-canopy"}


def test_chapter_text_separates_the_map_layers_from_the_stored_crop():
    api = NycFakeApi()
    seeder.seed_nyc_story(api)
    text = _document(api).chapters[0].blocks[0].config.text
    assert "On the map, the satellite layers" in text
    assert "stored crop" in text


@pytest.mark.parametrize("bad", [None, "", "nan", "abc", float("inf"), True])
def test_a_bad_roof_height_stops_the_seed_before_anything_is_created(bad):
    api = NycFakeApi()
    api.max_roof = bad
    for seed in (seeder.seed_nyc_story, seeder.seed_nyc_story_if_ready):
        with pytest.raises(RuntimeError, match="the tallest roof"):
            seed(api)
    assert (api.stories_created, api.uploads, api.published) == (0, 0, [])


def test_the_story_run_reports_a_bad_roof_height_as_a_failure(monkeypatch):
    for name in (
        "set_attribute_titles",
        "seed_hurricane_story",
        "seed_quake_dashboard",
        "seed_skyline_dashboard",
        "seed_skyline_story",
    ):
        monkeypatch.setattr(seeder, name, lambda api, *a, **k: None)
    api = NycFakeApi()
    api.max_roof = None
    assert seeder.run_story_and_dashboard(api) == 1
    assert api.stories_created == 0


def test_an_exact_numeric_string_roof_height_is_read():
    api = NycFakeApi()
    api.max_roof = "1550.5"
    seeder.seed_nyc_story(api)
    text = _document(api).chapters[2].blocks[0].config.text
    assert "up to 1,550 ft" in text or "up to 1,551 ft" in text


def test_a_single_date_in_view_publishes_one_orbit_chapter(capsys):
    api = NycFakeApi(orbit_dates=("2026-09-11", "2026-09-04"))
    api.bounds = {
        "ds-scene-0": [-73.5, 40.5, -73.0, 41.0],
        "ds-scene-1": _wide(),
    }
    seeder.seed_nyc_story(api)
    chapters = _document(api).chapters
    assert [c.title for c in chapters][:2] == ["From orbit", "The skyline"]
    assert len(chapters) == 5
    assert "Only the 2026-09-04 pass meets this view" in (
        chapters[0].blocks[0].config.text
    )
    assert "no earlier-pass chapter" in capsys.readouterr().out


def test_a_fallback_scene_filling_a_narrow_strip_stays_visible():
    """The strip between two preferred scenes falls between sample positions."""
    api = NycFakeApi(orbit_dates=("2026-09-11", "2026-09-11", "2026-09-04"))
    api.bounds = {
        "ds-scene-0": _wide(east=-73.85),
        "ds-scene-1": _wide(west=-73.80),
        "ds-scene-2": _wide(),
    }
    seeder.seed_nyc_story(api)
    first = _visible(_document(api).chapters[0])
    fallback = api.docs[api.map_ids[seeder.ORBIT_MAP]]["layers"][2]["id"]
    assert first[fallback] is True


def test_a_fallback_scene_inside_the_preferred_coverage_is_hidden():
    api = NycFakeApi(orbit_dates=("2026-09-11", "2026-09-04"))
    seeder.seed_nyc_story(api)
    first = _visible(_document(api).chapters[0])
    assert list(first.values()) == [True, False]


def test_a_newer_scene_never_draws_over_the_chapters_date():
    """Two scenes overlap and each reaches beyond the other inside the view."""
    api = NycFakeApi(orbit_dates=("2026-09-11", "2026-09-04"))
    api.bounds = {
        "ds-scene-0": [-75.0, 40.0, -73.9, 42.0],
        "ds-scene-1": [-74.1, 40.0, -73.0, 42.0],
    }
    seeder.seed_nyc_story(api)
    newer, older = (
        lay["id"] for lay in api.docs[api.map_ids[seeder.ORBIT_MAP]]["layers"]
    )
    first, second = _document(api).chapters[:2]
    assert (_visible(first)[newer], _visible(first)[older]) == (True, True)
    assert (_visible(second)[newer], _visible(second)[older]) == (False, True)
