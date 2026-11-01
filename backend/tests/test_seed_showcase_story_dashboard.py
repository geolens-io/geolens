"""The showcase story and dashboard seed passes: valid documents, no duplicates.

Database-free: a fake Api records what the passes send, and the payloads are
checked against the server's own request schemas.
"""

from __future__ import annotations

import hashlib
import importlib.util

import pytest

from app.modules.catalog.maps.dashboard import DashboardConfigInput
from app.modules.catalog.stories.schemas import StoryDocumentInput
from tests.repo_paths import repo_root

SCRIPT_PATH = repo_root(__file__) / "scripts" / "seed-showcase.py"


def _load_seeder():
    spec = importlib.util.spec_from_file_location("seed_showcase_story", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


seeder = _load_seeder()

LEGS_LAYER = "11111111-1111-4111-8111-111111111111"


class FakeApi:
    def __init__(self):
        self.maps: dict[str, str] = {
            seeder.HURRICANE_MAP: "map-tracks",
            seeder.EXPOSURE_MAP: "map-exposure",
        }
        self.stories: dict[str, str] = {}
        self.published: list[dict] = []
        self.dashboards: list[dict] = []
        self.views: list[dict] = []
        self.centers: dict[str, float | None] = {}
        self.fail_set_view = False
        self.layers_added = 0
        self.stories_created = 0
        self.maps_created = 0

    def list_maps(self):
        return dict(self.maps)

    def datasets_by_title(self):
        return {
            seeder.HURDAT2_LEGS_TITLE: "ds-legs",
            seeder.EXPOSURE_CHAIN_TITLES[2]: "ds-exposure",
            seeder.QUAKES_TITLE: "ds-quakes",
        }

    def get_map(self, map_id):
        layers = []
        if map_id == "map-exposure":
            layers = [{"id": LEGS_LAYER, "dataset_id": "ds-legs"}]
        if map_id == "map-dashboard" and self.layers_added:
            layers = [
                {
                    "id": "22222222-2222-4222-8222-222222222222",
                    "dataset_id": "ds-quakes",
                }
            ]
        return {
            "id": "00000000-0000-4000-8000-00000000000" + str(len(map_id) % 10),
            "center_lng": self.centers.get(map_id, -72.0),
            "center_lat": 25.0,
            "zoom": 3.2,
            "bearing": None,
            "pitch": 0,
            "layers": layers,
        }

    def aggregate(self, dataset_id, **body):
        op = body["op"]
        if op == "count":
            return {"count": 5}
        if op == "stats":
            return {"min": 1950, "max": 2025}
        if op == "value_counts":
            return {
                "values": [
                    {"value": "Cat 5", "count": 2},
                    {"value": "Cat 3", "count": 3},
                ]
            }
        return {"groups": [{"key": "Florida", "value": 7}]}

    def list_stories(self):
        return dict(self.stories)

    def create_story(self, title, summary):
        self.stories_created += 1
        self.stories[title] = "story-1"
        return "story-1"

    def publish_story(self, story_id, title, summary, document):
        self.published.append(document)

    def create_map(self, name, description):
        self.maps_created += 1
        self.maps[name] = "map-dashboard"
        self.centers["map-dashboard"] = None
        return "map-dashboard"

    def add_layer(self, map_id, body):
        self.layers_added += 1
        return {"id": "22222222-2222-4222-8222-222222222222"}

    def set_view(self, map_id, **fields):
        if self.fail_set_view:
            raise RuntimeError("422 from an older server")
        self.views.append(fields)
        if "center_lng" in fields:
            self.centers[map_id] = fields["center_lng"]
        if "dashboard_config" in fields:
            self.dashboards.append(fields["dashboard_config"])


def test_story_document_is_valid_and_figures_come_from_the_data():
    api = FakeApi()
    seeder.seed_hurricane_story(api)
    document = StoryDocumentInput.model_validate(api.published[0])
    text = " ".join(
        block.config.text for chapter in document.chapters for block in chapter.blocks
    )
    assert "From 1950 to 2025, 5 Atlantic storms" in text
    assert "2 at Category 5, 3 at Category 3" in text
    assert "Florida (7)" in text


def test_story_reruns_update_in_place():
    api = FakeApi()
    seeder.seed_hurricane_story(api)
    seeder.seed_hurricane_story(api)
    assert api.stories_created == 1
    assert api.published[0] == api.published[1]


def test_dashboard_config_is_valid_and_reruns_reuse_map_and_layer():
    api = FakeApi()
    seeder.seed_quake_dashboard(api)
    seeder.seed_quake_dashboard(api)
    assert api.maps_created == 1
    assert api.layers_added == 1
    for config in api.dashboards:
        DashboardConfigInput.model_validate(config)
    assert api.dashboards[0] == api.dashboards[1]


def test_dashboard_camera_is_set_once_even_after_a_failed_first_save():
    api = FakeApi()
    api.fail_set_view = True
    with pytest.raises(RuntimeError):
        seeder.seed_quake_dashboard(api)
    api.fail_set_view = False
    seeder.seed_quake_dashboard(api)
    seeder.seed_quake_dashboard(api)
    assert api.maps_created == 1
    assert [view.get("center_lng") for view in api.views] == [0, None]


@pytest.mark.parametrize("seed", ["seed_hurricane_story", "seed_quake_dashboard"])
def test_seed_refuses_without_its_prerequisites(seed):
    api = FakeApi()
    api.maps.clear()
    api.datasets_by_title = lambda: {}
    with pytest.raises(RuntimeError, match="not seeded"):
        getattr(seeder, seed)(api)


BUILDINGS_LAYER = "44444444-4444-4444-8444-444444444444"
SUBWAY_LAYER = "55555555-5555-4555-8555-555555555555"
PHOTO = b"a pinned skyline photo"
# Two unnamed towers finished the same year share the title "Built 2016".
TALLEST = [
    {"title": "Built 2016", "height_roof": 1400.0},
    {"title": "Built 2016", "height_roof": 1396.0},
    {"title": "Empire State Building", "height_roof": 1250.0},
]


class SkylineFakeApi(FakeApi):
    base = "http://localhost:8001"

    def __init__(self):
        super().__init__()
        self.maps = {seeder.SKYLINE_MAP: "map-manhattan"}
        self.uploads = 0
        self.layer_popup = None
        self.layer_updates: list[dict] = []

    def datasets_by_title(self):
        return {
            seeder.SKYLINE_BUILDINGS_TITLE: "ds-buildings",
            "NYC Subway Stations (MTA)": "ds-stations",
        }

    def get_map(self, map_id):
        doc = super().get_map(map_id)
        if map_id == "map-manhattan":
            doc["layers"] = [
                {"id": BUILDINGS_LAYER, "dataset_id": "ds-buildings"},
                {"id": SUBWAY_LAYER, "dataset_id": "ds-subway"},
            ]
        if map_id == "map-dashboard" and self.layers_added:
            doc["layers"] = [
                {
                    "id": BUILDINGS_LAYER,
                    "dataset_id": "ds-buildings",
                    "popup_config": self.layer_popup,
                }
            ]
        return doc

    def add_layer(self, map_id, body):
        super().add_layer(map_id, body)
        self.layer_popup = body["popup_config"]
        return {"id": BUILDINGS_LAYER}

    def update_layer(self, map_id, body):
        self.layer_updates.append(body)
        self.layer_popup = body["popup_config"]

    def aggregate(self, dataset_id, **body):
        if body["op"] == "value_counts":
            values = {"era": ["Pre-1900", "1900-1929", "2015+"], "ada": ["1"]}
            return {
                "values": [{"value": v, "count": 3} for v in values[body["column"]]]
            }
        if body["op"] == "stats":
            return {"max": 1550.0}
        return super().aggregate(dataset_id, **body)

    def public_app_url(self):
        return "https://geolens.example"

    def rows(self, dataset_id, cql2, sort, limit):
        return sorted(TALLEST, key=lambda row: -row[sort])[:limit]

    def upload_story_asset(self, story_id, filename, data):
        self.uploads += 1
        return "66666666-6666-4666-8666-666666666666"

    def story_document(self, story_id):
        return self.published[-1] if self.published else {}


def test_skyline_story_flies_one_map_and_reruns_reuse_everything(monkeypatch):
    monkeypatch.setattr(seeder, "fetch", lambda _url: PHOTO)
    monkeypatch.setattr(
        seeder, "SKYLINE_PHOTO_SHA256", hashlib.sha256(PHOTO).hexdigest()
    )
    api = SkylineFakeApi()
    for _ in range(2):
        seeder.seed_skyline_dashboard(api)
        seeder.seed_skyline_story(api)

    assert (api.maps_created, api.layers_added, api.stories_created) == (1, 1, 1)
    assert api.uploads == 1
    for config in api.dashboards:
        DashboardConfigInput.model_validate(config)
    first, second = api.published
    assert first == second

    document = StoryDocumentInput.model_validate(first)
    scenes = [chapter.scene for chapter in document.chapters]
    # One map for every chapter is what makes the reader fly instead of remount.
    assert len({scene.map_id for scene in scenes}) == 1
    subway = [
        scene.layer_visibility[seeder.uuid.UUID(SUBWAY_LAYER)] for scene in scenes
    ]
    assert subway == [False, False, False, False, True]
    assert document.chapters[-1].blocks[-1].config.url == (
        "https://geolens.example/maps/map-dashboard"
    )
    text = " ".join(
        block.config.text
        for chapter in document.chapters
        for block in chapter.blocks
        if block.type == "markdown"
    )
    assert "followed by a tower completed in 2016 at 1,396 ft" in text


def test_skyline_dashboard_table_leads_with_the_building():
    fields = ["title", "height_roof", "construction_year", "era"]
    api = SkylineFakeApi()
    seeder.seed_skyline_dashboard(api)
    seeder.seed_skyline_dashboard(api)
    assert api.layer_popup["visible_fields"] == fields
    assert api.layer_updates == []

    # A layer an earlier seed made keeps its other popup settings.
    api.layer_popup = {"enabled": True, "visible_fields": ["construction_year"]}
    seeder.seed_skyline_dashboard(api)
    assert api.layer_updates == [
        {
            "id": BUILDINGS_LAYER,
            "popup_config": {"enabled": True, "visible_fields": fields},
        }
    ]
