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
            return {"max": 1550.0}
        return {
            "values": [
                {"value": "Gain", "count": 11},
                {"value": "Loss", "count": 7},
                {"value": "No Change", "count": 3},
            ]
        }

    def raster_bounds(self, dataset_id):
        return self.bounds

    def raster_tile(self, dataset_id, z, x, y):
        self.tiles.append((dataset_id, z))
        return self.crop

    def upload_story_asset(self, story_id, filename, data):
        self.uploads += 1
        self.uploaded.append(data)
        return ASSET

    def story_document(self, story_id):
        return self.published[-1][0] if self.published else {}

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
    assert (cameras[3].pitch, cameras[3].bearing) == (70, 120)
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
        ["markdown", "image"],
        ["markdown", "separator"],
        ["markdown"],
        ["markdown"],
        ["markdown", "button"],
        ["markdown", "separator", "button", "button"],
    ]
    manhattan = chapters[4].blocks[1].config.url
    dashboard, hurricanes = (b.config.url for b in chapters[5].blocks[2:])
    assert (
        manhattan == f"https://geolens.example/maps/{api.map_ids[seeder.SKYLINE_MAP]}"
    )
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


def test_image_block_credits_the_scene_and_is_the_cover():
    api = NycFakeApi()
    seeder.seed_nyc_story(api)
    image = _document(api).chapters[0].blocks[1]
    assert str(image.asset_id) == ASSET
    assert image.config.alt
    assert image.config.caption.endswith(
        "Contains modified Copernicus Sentinel data 2026."
    )
    assert api.published[0][1] == ASSET


@pytest.mark.parametrize("zoom", [10, 11, 12])
def test_the_crop_is_the_first_tile_one_scene_covers_whole(zoom):
    api = NycFakeApi()
    x, y = seeder._tile_at(-74.015, 40.725, zoom)
    api.bounds = list(seeder._tile_bbox(zoom, x, y))
    seeder.seed_nyc_story(api)
    assert [z for _, z in api.tiles] == [zoom]


def test_no_covering_scene_refuses_the_story():
    api = NycFakeApi()
    api.bounds = [10.0, 10.0, 11.0, 11.0]
    with pytest.raises(RuntimeError, match="no single newest Sentinel-2 scene"):
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
    assert api.stories_created == 1
    assert api.uploads == 2


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

    assert len(api.tiles) == 16
    base_x, base_y = seeder._tile_at(-74.015, 40.725, 10)
    grid = {(x, y) for x, y, z in api.tiles if z == 12}
    assert grid == {
        (base_x * 4 + c, base_y * 4 + r) for r in range(4) for c in range(4)
    }
    uploaded = api.uploaded[0]
    with Image.open(io.BytesIO(uploaded)) as image:
        assert (image.size, image.format) == ((1024, 1024), "JPEG")
