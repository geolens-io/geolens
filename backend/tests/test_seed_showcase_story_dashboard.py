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
        self.covers: list[str | None] = []
        self.uploads = 0
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

    def publish_story(self, story_id, title, summary, document, cover_asset_id=None):
        self.published.append(document)
        self.covers.append(cover_asset_id)

    def story_document(self, story_id):
        return self.published[-1] if self.published else {}

    def story_cover_asset(self, story_id):
        return self.covers[-1] if self.covers else None

    def public_app_url(self):
        return "https://geolens.example"

    def upload_story_asset(self, story_id, filename, data):
        self.uploads += 1
        return f"00000000-0000-4000-8000-{self.uploads:012d}"

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


@pytest.fixture(autouse=True)
def pinned_photos(monkeypatch):
    """Every pinned download is the same stand-in file, with its pin to match."""
    pin = hashlib.sha256(PHOTO).hexdigest()
    monkeypatch.setattr(seeder, "fetch", lambda _url: PHOTO)
    monkeypatch.setattr(
        seeder, "HURRICANE_PHOTO", {**seeder.HURRICANE_PHOTO, "sha256": pin}
    )
    monkeypatch.setattr(
        seeder,
        "SKYLINE_PHOTOS",
        [{**photo, "sha256": pin} for photo in seeder.SKYLINE_PHOTOS],
    )


def test_story_document_is_valid_and_figures_come_from_the_data():
    api = FakeApi()
    seeder.seed_hurricane_story(api)
    document = StoryDocumentInput.model_validate(api.published[0])
    text = " ".join(
        block.config.text
        for chapter in document.chapters
        for block in chapter.blocks
        if block.type == "markdown"
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
    assert [view.get("center_lng") for view in api.views] == [
        seeder.DASHBOARD_CAMERA["center_lng"],
        None,
    ]


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


def test_skyline_story_flies_one_map_and_reruns_reuse_everything():
    api = SkylineFakeApi()
    for _ in range(2):
        seeder.seed_skyline_dashboard(api)
        seeder.seed_skyline_story(api)

    assert (api.maps_created, api.layers_added, api.stories_created) == (1, 1, 1)
    assert api.uploads == len(seeder.SKYLINE_PHOTOS)
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
    api.layer_popup = {"enabled": False, "visible_fields": ["construction_year"]}
    seeder.seed_skyline_dashboard(api)
    assert api.layer_updates[-1]["popup_config"]["enabled"] is False
    assert api.layer_updates[-1]["popup_config"]["visible_fields"] == fields

    # A layer saved without a popup still gets the fields the API requires.
    api.layer_popup = None
    seeder.seed_skyline_dashboard(api)
    assert api.layer_updates[-1]["popup_config"]["enabled"] is True
    assert api.layer_updates[-1]["popup_config"]["visible_fields"] == fields
    assert len(api.layer_updates) == 2


def _widget_types(config):
    return [widget["type"] for widget in config["widgets"]]


def test_quake_dashboard_shows_the_newer_widgets():
    api = FakeApi()
    seeder.seed_quake_dashboard(api)
    config = api.dashboards[0]
    widgets = {widget["id"]: widget for widget in config["widgets"]}
    by_title = {widget["title"]: widget for widget in widgets.values()}
    daily = by_title["Earthquakes per week"]["config"]
    assert (daily["mode"], daily["date_bucket"]) == ("date", "week")
    assert "feature_list" in _widget_types(config)
    strongest = by_title["Strongest earthquake in view (magnitude)"]["config"]
    assert strongest["reference"] == 6.0
    assert strongest["higher_is_better"] is False
    assert strongest["comparison"] == "value"


def test_skyline_dashboard_uses_a_bottom_panel_pie_table_and_reference():
    api = SkylineFakeApi()
    seeder.seed_skyline_dashboard(api)
    config = api.dashboards[0]
    DashboardConfigInput.model_validate(config)
    assert config["panel"] == "bottom"
    assert {"pie_chart", "table"} <= set(_widget_types(config))
    tallest = next(w for w in config["widgets"] if w["title"].startswith("Tallest"))
    assert tallest["config"]["reference"] == 1239


def test_hurricane_story_sets_reader_settings_and_a_cover():
    api = FakeApi()
    seeder.seed_hurricane_story(api)
    document = StoryDocumentInput.model_validate(api.published[0])
    settings = document.settings
    assert (settings.layout, settings.panel_position) == ("floating", "left")
    assert (settings.navigation, settings.transition) == (True, "glide")
    assert not [b for c in document.chapters for b in c.blocks if b.type == "image"]
    assert api.covers[0]
    cover_credit = document.chapters[0].blocks[0].config.text
    assert "NASA" in cover_credit and "arrows" not in cover_credit
    seeder.seed_hurricane_story(api)
    assert api.uploads == 1
    assert api.covers[1] == api.covers[0]


def test_hurricane_story_ends_with_buttons_to_both_maps():
    api = FakeApi()
    seeder.seed_hurricane_story(api)
    last = StoryDocumentInput.model_validate(api.published[0]).chapters[-1]
    assert [b.config.url for b in last.blocks if b.type == "button"] == [
        "https://geolens.example/maps/map-tracks",
        "https://geolens.example/maps/map-exposure",
    ]


def test_skyline_story_gallery_holds_three_described_photos():
    api = SkylineFakeApi()
    seeder.seed_skyline_dashboard(api)
    seeder.seed_skyline_story(api)
    document = StoryDocumentInput.model_validate(api.published[0])
    assert document.settings.navigation is True
    gallery = next(
        block
        for chapter in document.chapters
        for block in chapter.blocks
        if block.type == "gallery"
    )
    assert len(gallery.config.images) == 3
    assert all(image.alt and image.caption for image in gallery.config.images)
    assert document.chapters[-1].scene.transition == "cut"
    assert api.covers[0] == str(gallery.config.images[0].asset_id)


def test_dashboards_declare_every_widget_kind_they_send_as_readable():
    # Without it a rerun is refused: the server sets aside stored widgets of
    # kinds the saving client does not say it reads.
    quakes, skyline = FakeApi(), SkylineFakeApi()
    seeder.seed_quake_dashboard(quakes)
    seeder.seed_skyline_dashboard(skyline)
    for config in (quakes.dashboards[0], skyline.dashboards[0]):
        sent = {f"{w['type']}:{w['v']}" for w in config["widgets"]}
        assert sent <= set(config["readable"])


def _gallery(document):
    return next(
        block
        for chapter in document["chapters"]
        for block in chapter["blocks"]
        if block["type"] == "gallery"
    )


def test_reordered_gallery_is_put_back_in_pinned_order_without_uploads():
    api = SkylineFakeApi()
    seeder.seed_skyline_dashboard(api)
    seeder.seed_skyline_story(api)
    uploads = api.uploads
    images = _gallery(api.published[-1])["config"]["images"]
    images.reverse()
    seeder.seed_skyline_story(api)
    again = _gallery(api.published[-1])["config"]["images"]
    assert [i["caption"] for i in again] == [
        p["caption"] for p in seeder.SKYLINE_PHOTOS
    ]
    assert [i["asset_id"] for i in again] == [i["asset_id"] for i in reversed(images)]
    assert api.uploads == uploads


def test_replaced_gallery_image_is_uploaded_again_and_unchanged_is_a_no_op():
    api = SkylineFakeApi()
    seeder.seed_skyline_dashboard(api)
    seeder.seed_skyline_story(api)
    seeder.seed_skyline_story(api)
    assert api.uploads == len(seeder.SKYLINE_PHOTOS)
    assert api.published[-1] == api.published[-2]
    _gallery(api.published[-1])["config"]["images"][1]["caption"] = "someone else's"
    seeder.seed_skyline_story(api)
    assert api.uploads == len(seeder.SKYLINE_PHOTOS) + 1
    restored = _gallery(api.published[-1])["config"]["images"][1]
    assert restored["caption"] == seeder.SKYLINE_PHOTOS[1]["caption"]


def test_photos_are_uploaded_under_filenames_that_name_them():
    names = [p["filename"] for p in seeder.SKYLINE_PHOTOS]
    assert len(set(names)) == len(names)
    assert all("8b162" in n for n in names)
    assert "iss067e382116" in seeder.HURRICANE_PHOTO["filename"]


def _skyline_text_with_57th(modern, old):
    class SteinwayApi(SkylineFakeApi):
        def rows(self, dataset_id, cql2, sort, limit):
            bbox = cql2["args"][1]["args"][1]["bbox"]
            eras = cql2["args"][0]["args"][1]
            if bbox == seeder.SKYLINE_57TH_BBOX and "2015+" in eras:
                return modern
            if bbox == seeder.SKYLINE_57TH_BBOX and "1900-1929" in eras:
                return old
            return super().rows(dataset_id, cql2, sort, limit)

    api = SteinwayApi()
    seeder.seed_skyline_dashboard(api)
    seeder.seed_skyline_story(api)
    document = StoryDocumentInput.model_validate(api.published[-1])
    return " ".join(
        block.config.text
        for chapter in document.chapters
        for block in chapter.blocks
        if block.type == "markdown"
    )


MODERN_57TH = [
    {"title": "Built 2020", "height_roof": 1550.0},
    {"title": "Built 2016", "height_roof": 1396.0},
]


def test_skyline_story_names_the_supertall_recorded_with_a_1924_year():
    text = _skyline_text_with_57th(
        MODERN_57TH, [{"title": "Built 1924", "height_roof": 1428.0}]
    )
    assert "The tallest is a tower completed in 2020, with a roof at 1,550 ft" in text
    assert (
        "The second tallest is 111 West 57th Street (Steinway Tower) at 1,428 ft"
        in text
    )
    assert "After it comes a tower completed in 2016 at 1,396 ft" in text


@pytest.mark.parametrize("height", [1600.0, 1300.0])
def test_skyline_story_ranks_a_1924_tower_only_between_the_two_tallest(height):
    text = _skyline_text_with_57th(
        MODERN_57TH, [{"title": "Built 1924", "height_roof": height}]
    )
    assert "Steinway" not in text
    assert "It is followed by a tower completed in 2016 at 1,396 ft" in text


def test_hurricane_coasts_chapter_frames_the_regions_it_names():
    api = FakeApi()
    seeder.seed_hurricane_story(api)
    chapter = api.published[0]["chapters"][1]
    center = chapter["scene"]["camera"]["center"]
    # Louisiana at -93 and Quintana Roo at -86.7 to Florida's east coast at -80.
    assert -93 < center[0] < -80
    assert 18 < center[1] < 31
    assert chapter["scene"]["camera"]["zoom"] <= 4.2


def test_skyline_story_ends_on_links_to_the_map_and_the_dashboard():
    api = SkylineFakeApi()
    seeder.seed_skyline_dashboard(api)
    seeder.seed_skyline_story(api)
    document = StoryDocumentInput.model_validate(api.published[-1])
    last = document.chapters[-1].blocks
    assert last[0].type == "markdown"
    urls = [block.config.url for block in last if block.type == "button"]
    assert urls == [
        "https://geolens.example/maps/map-manhattan",
        "https://geolens.example/maps/map-dashboard",
    ]


def test_matterhorn_text_names_the_copernicus_terrain_past_the_swiss_border():
    notes = seeder.MAP_LEGEND_AND_NOTES["The Matterhorn in 3D"][1]
    for text in (seeder.MAP_DESCRIPTIONS["The Matterhorn in 3D"], notes):
        assert "Swiss border" in text and "Copernicus" in text


def test_quake_codes_get_reader_labels_once():
    class LabelApi:
        def __init__(self):
            self.attrs = {
                f: {"id": f"a-{f}", "field_name": f, "title": f, "value_labels": None}
                for f in ("magtype", "net")
            }
            self.writes = []

        def datasets_by_title(self):
            return {seeder.QUAKES_TITLE: "ds-quakes"}

        def attributes(self, dataset_id):
            return list(self.attrs.values())

        def set_attribute_title(self, dataset_id, attr_id, title):
            pass

        def set_attribute_value_labels(self, dataset_id, attr_id, labels):
            self.writes.append(attr_id)
            for attr in self.attrs.values():
                if attr["id"] == attr_id:
                    attr["value_labels"] = labels

    api = LabelApi()
    seeder.set_attribute_titles(api)
    assert api.attrs["magtype"]["value_labels"]["mww"] == "Moment, W-phase (Mww)"
    assert api.attrs["net"]["value_labels"]["us"] == "USGS NEIC"
    assert len(api.writes) == 2
    seeder.set_attribute_titles(api)
    assert len(api.writes) == 2


def test_skyline_dashboard_has_no_roof_height_histogram():
    api = SkylineFakeApi()
    seeder.seed_skyline_dashboard(api)
    kinds = {w["type"] for w in api.dashboards[-1]["widgets"]}
    assert "histogram" not in kinds
