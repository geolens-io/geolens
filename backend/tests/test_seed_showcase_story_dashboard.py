"""The showcase story and dashboard seed passes: valid documents, no duplicates.

Database-free: a fake Api records what the passes send, and the payloads are
checked against the server's own request schemas.
"""

from __future__ import annotations

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
            "center_lng": -72.0,
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
        return "map-dashboard"

    def add_layer(self, map_id, body):
        self.layers_added += 1
        return {"id": "22222222-2222-4222-8222-222222222222"}

    def set_view(self, map_id, **fields):
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


@pytest.mark.parametrize("seed", ["seed_hurricane_story", "seed_quake_dashboard"])
def test_seed_refuses_without_its_prerequisites(seed):
    api = FakeApi()
    api.maps.clear()
    api.datasets_by_title = lambda: {}
    with pytest.raises(RuntimeError, match="not seeded"):
        getattr(seeder, seed)(api)
