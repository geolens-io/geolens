"""The Cambridge showcase section finds its content by title and never builds it twice."""

from __future__ import annotations

import hashlib
import importlib.util
import json

import httpx
import sys
import types
import uuid

import pytest

from app.modules.catalog.maps.schemas_import_arcgis import ArcgisWebmapImportRequest
from tests.repo_paths import repo_root

SCRIPTS = repo_root(__file__) / "scripts"
spec = importlib.util.spec_from_file_location(
    "seed_showcase_for_cambridge", SCRIPTS / "seed-showcase.py"
)
seed = importlib.util.module_from_spec(spec)
spec.loader.exec_module(seed)
cam = seed.cambridge

BINDING_TITLES = [title for title, _ in cam.BINDINGS]
ALL_TITLES = sorted(cam.DATASET_TITLES)


class FakeApi:
    """Just enough of the seeder's Api for the Cambridge builders."""

    username = "showcase"

    def __init__(self):
        self.datasets: dict[str, dict] = {}
        self.maps: dict[str, dict] = {}
        self.collections: dict[str, dict] = {}
        self.created: dict[str, str] = {}
        self.counter = 0
        self.writes: list[str] = []
        self.aggregates: list[dict] = []
        self.coded: dict[str, set[str]] = {}
        self.titles: dict[tuple[str, str], str] = {}
        self.stub_summaries: list = []

    def _id(self, prefix: str) -> str:
        self.counter += 1
        return (
            str(uuid.UUID(int=self.counter))
            if prefix == "ds"
            else f"{prefix}-{self.counter}"
        )

    def _dataset(self, title: str, origin: str = "upload", origin_uri=None) -> str:
        dataset_id = self._id("ds")
        service = dict(cam.BINDINGS).get(title)
        if origin == "service" and origin_uri is None and service:
            origin_uri = cam._source(service)
        filename = (
            cam.STUB_FILENAME if service and origin == "upload" else "file.geojson"
        )
        self.datasets[dataset_id] = {
            "id": dataset_id,
            "record_id": f"rec-{dataset_id}",
            "title": title,
            "origin": origin,
            "origin_uri": origin_uri,
            "source_filename": filename,
            "visibility": "public",
            "summary": None,
            "collections": [],
            "created_at": "2026-11-07T12:00:00Z",
            "keywords": set(),
        }
        self.created[title] = dataset_id
        return dataset_id

    def datasets_by_title(self):
        return {d["title"]: i for i, d in self.datasets.items()}

    def list_own_datasets(self):
        return [{"title": d["title"], "id": i} for i, d in self.datasets.items()]

    def dataset_origin(self, dataset_id):
        return self.datasets[dataset_id]["origin"]

    def get_dataset(self, dataset_id):
        return self.datasets[dataset_id]

    def patch_dataset(self, dataset_id, **fields):
        self.writes.append("patch_dataset")
        self.datasets[dataset_id].update(fields)

    def ingest_geojson(self, name, data, title, summary, timeout=300):
        self.writes.append("ingest")
        dataset_id = self._dataset(title)
        self.datasets[dataset_id]["summary"] = summary
        return dataset_id

    def analysis_materialize(self, source_id, operation, title, timeout=0, **params):
        self.writes.append(f"analysis:{operation}")
        dataset_id = self._dataset(title, origin="postgis")
        self.datasets[dataset_id]["visibility"] = "private"
        return dataset_id

    def existing_keywords(self, record_id):
        return {
            k
            for d in self.datasets.values()
            if d["record_id"] == record_id
            for k in d["keywords"]
        }

    def add_keyword(self, record_id, keyword):
        self.writes.append("add_keyword")
        for d in self.datasets.values():
            if d["record_id"] == record_id:
                d["keywords"].add(keyword)

    def attributes(self, dataset_id):
        return [
            {
                "id": f"{dataset_id}-{name}",
                "field_name": name,
                "title": self.titles.get((dataset_id, name), name),
                "value_labels": {"Y": "Yes"}
                if name in self.coded.get(dataset_id, ())
                else None,
            }
            for name in ("sitetype", "overheadwires", "join_zone_type", "full_addr")
        ]

    def set_attribute_title(self, dataset_id, attr_id, title):
        self.writes.append("attribute_title")
        self.titles[(dataset_id, attr_id.removeprefix(f"{dataset_id}-"))] = title

    def dataset_columns(self, dataset_id):
        return {
            "sitetype",
            "plantdate",
            "diameter",
            "neighborhood",
            "streetname",
            "plantingseason",
            "commonname",
            "scientificname",
            "ownership",
            "overheadwires",
            "join_zone_type",
            "shape_area",
            "full_addr",
            "ml",
            "zone_type",
            "name",
        }

    def list_collections(self):
        return [{"id": i, **c} for i, c in self.collections.items()]

    def create_collection(self, name, description):
        self.writes.append("create_collection")
        collection_id = self._id("col")
        self.collections[collection_id] = {"name": name, "description": description}
        return collection_id

    def update_collection(self, collection_id, **fields):
        self.writes.append("update_collection")
        self.collections[collection_id].update(fields)

    def add_to_collection(self, collection_id, dataset_ids):
        self.writes.append("add_to_collection")
        name = self.collections[collection_id]["name"]
        for dataset_id in dataset_ids:
            self.datasets[dataset_id]["collections"].append(
                {"id": collection_id, "name": name}
            )

    def list_maps(self):
        return {m["name"]: i for i, m in self.maps.items()}

    def create_map(self, name, description):
        self.writes.append("create_map")
        map_id = self._id("map")
        self.maps[map_id] = {
            "id": map_id,
            "name": name,
            "description": description,
            "layers": [],
            "center_lng": None,
        }
        return map_id

    def get_map(self, map_id):
        return self.maps[map_id]

    def add_layer(self, map_id, body):
        self.writes.append("add_layer")
        layer = {"id": self._id("layer"), **body}
        self.maps[map_id]["layers"].append(layer)
        return layer

    def update_layer(self, map_id, body):
        self.writes.append("update_layer")
        layer = next(x for x in self.maps[map_id]["layers"] if x["id"] == body["id"])
        layer.update(body)

    def set_view(self, map_id, **fields):
        self.writes.append("set_view")
        dashboard = fields.pop("dashboard_config", None)
        self.maps[map_id].update(fields)
        if dashboard is not None:
            self.maps[map_id]["dashboard_config"] = {
                "panel": "right",
                "map_hidden": False,
                **{k: v for k, v in dashboard.items() if k != "readable"},
            }
            self.maps[map_id]["dashboard_sent"] = dashboard

    def aggregate(self, dataset_id, **body):
        self.aggregates.append(body)
        low = body["filter"]["args"][0]["args"][1]["timestamp"][:4]
        return {"count": {"2016": 3151, "2021": 5668}[low]}


def helpers(api: FakeApi, *, fetch=None):
    """The real seeder helpers over the fake API, with the network ones replaced."""
    ns = types.SimpleNamespace(
        **{name: getattr(seed, name) for name in cam.SEEDER_HELPERS}
    )

    def ingest_service(api_, url, title, timeout=900, **kw):
        api_.writes.append("ingest_service")
        api_.stub_summaries.append(kw.get("stub_summary"))
        dataset_id = api_._dataset(title, origin="service")
        return dataset_id

    ns.ingest_service = ingest_service
    ns.convert_to_service = lambda *a, **k: False
    ns.warn_if_hidden_layers = lambda *a, **k: None
    ns.fetch = fetch or (lambda url: b"")
    return ns


@pytest.fixture
def parcels_file(monkeypatch):
    collection = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"ML": "1-1", "Editor": "ed", "last_edited_user": "x"},
                "geometry": None,
            }
        ],
    }
    raw = json.dumps(collection).encode()
    monkeypatch.setattr(cam, "PARCELS_SHA256", hashlib.sha256(raw).hexdigest())
    return raw


@pytest.fixture
def built(parcels_file):
    api = FakeApi()
    h = helpers(api, fetch=lambda url: parcels_file)
    cam.build_catalog(h, api)
    return api, h


def test_catalog_builds_each_dataset_once_and_a_rerun_writes_nothing(built):
    api, h = built
    assert sorted(d["title"] for d in api.datasets.values()) == ALL_TITLES
    assert api.writes.count("ingest_service") == len(BINDING_TITLES)
    assert api.writes.count("analysis:spatial_join") == 1
    assert api.writes.count("analysis:select_by_location") == 1
    assert len(api.collections) == 1
    assert all(d["visibility"] == "public" for d in api.datasets.values())

    before = len(api.writes)
    cam.build_catalog(h, api)
    assert api.writes[before:] == []


def test_a_binding_whose_service_is_not_read_keeps_its_text_held(parcels_file):
    api = FakeApi()
    h = helpers(api, fetch=lambda url: parcels_file)
    trees = api._dataset(cam.TREES_TITLE, origin="upload")
    api.datasets[trees]["summary"] = cam.STUB_SUMMARY

    cam.build_catalog(h, api)

    assert api.datasets[trees]["summary"] == cam.STUB_SUMMARY


def test_a_failed_binding_withdraws_the_public_stub(parcels_file):
    api = FakeApi()
    h = helpers(api)

    def failing(api_, url, title, timeout=900, **kw):
        dataset_id = api_._dataset(title)
        api_.datasets[dataset_id]["summary"] = "Earthquake data"
        raise RuntimeError("service unreachable")

    h.ingest_service = failing
    with pytest.raises(RuntimeError):
        cam.build_catalog(h, api)

    stub = api.datasets[api.created[cam.TREES_TITLE]]
    assert stub["visibility"] == "private"
    assert stub["summary"] == cam.STUB_SUMMARY


def test_parcels_file_is_pinned_and_loses_editor_columns(parcels_file, monkeypatch):
    h = helpers(FakeApi(), fetch=lambda url: parcels_file)
    out = json.loads(cam.parcels_bytes(h))
    assert out["features"][0]["properties"] == {"ML": "1-1"}

    monkeypatch.setattr(cam, "PARCELS_SHA256", "0" * 64)
    with pytest.raises(RuntimeError, match="changed"):
        cam.parcels_bytes(h)


def test_trees_map_imports_once_and_matches_every_layer(built):
    api, h = built
    bodies = []

    def fake_import(api_, body):
        bodies.append(body)
        if body.get("dry_run"):
            return {
                "loss_report": {"summary": {"popup_media": 1, "popup_expression": 1}}
            }
        map_id = api_.create_map(body["name"], "")
        return {"map": {"id": map_id}}

    original = cam.import_webmap
    cam.import_webmap = fake_import
    try:
        map_id = cam.build_trees_map(h, api)
        assert cam.build_trees_map(h, api) == map_id
    finally:
        cam.import_webmap = original

    imports = [b for b in bodies if not b.get("dry_run")]
    assert len(imports) == 1
    request = ArcgisWebmapImportRequest.model_validate(imports[0])
    layer_ids = {layer["id"] for layer in request.webmap["operationalLayers"]}
    assert set(request.dataset_matches) == layer_ids
    description = api.maps[map_id]["description"]
    assert "popup charts" in description and "computed popup fields" in description
    assert len(description) <= 2000


def test_webmap_popups_leave_staff_columns_out():
    webmap = json.loads(cam.WEBMAP_PATH.read_text())
    for layer in webmap["operationalLayers"]:
        fields = {f["fieldName"].lower() for f in layer["popupInfo"]["fieldInfos"]}
        assert not fields & cam.STAFF_COLUMNS


def test_tree_dashboard_takes_its_reference_from_the_aggregate(built):
    api, h = built
    map_id = cam.seed_tree_dashboard(h, api)

    sent = api.maps[map_id]["dashboard_sent"]
    indicator = next(w for w in sent["widgets"] if w["type"] == "indicator")
    assert indicator["config"]["reference"] == 3151
    assert indicator["config"]["reference_label"] == "2016-2020"
    assert indicator["config"]["higher_is_better"] is True
    assert indicator["config"]["comparison"] == "both"
    assert indicator["v"] == 2
    assert {
        a["filter"]["args"][0]["args"][1]["timestamp"][:4] for a in api.aggregates
    } == {
        "2016",
        "2021",
    }
    layer = next(
        x
        for x in api.maps[map_id]["layers"]
        if x["display_name"] == "Trees planted 2021-2025"
    )
    assert layer["filter"][1][2].startswith("2021-01-01")
    assert indicator["layer_id"] == layer["id"]

    before = len(api.writes)
    cam.seed_tree_dashboard(h, api)
    assert api.writes[before:] == []


def test_planting_chart_starts_at_2008(built):
    api, h = built
    map_id = cam.seed_tree_dashboard(h, api)
    layers = {x["display_name"]: x for x in api.maps[map_id]["layers"]}
    chart = next(
        w
        for w in api.maps[map_id]["dashboard_sent"]["widgets"]
        if w["type"] == "bar_chart"
    )
    assert "since 2008" in chart["title"]
    layer = layers["Trees planted since 2008"]
    assert chart["layer_id"] == layer["id"]
    assert layer["filter"][2].startswith("2008-01-01")


def test_every_dashboard_save_carries_the_readable_list(built):
    api, h = built
    for seeder in (cam.seed_tree_dashboard, cam.seed_land_dashboard):
        map_id = seeder(h, api)
        readable = api.maps[map_id]["dashboard_sent"]["readable"]
        assert {
            "pie_chart:1",
            "table:1",
            "feature_list:1",
            "indicator:2",
            "bar_chart:2",
        } <= set(readable)


def test_land_dashboard_has_no_map_and_reads_whole_layers(built):
    api, h = built
    map_id = cam.seed_land_dashboard(h, api)

    sent = api.maps[map_id]["dashboard_sent"]
    assert sent["map_hidden"] is True
    data_widgets = [w for w in sent["widgets"] if w["type"] != "markdown"]
    assert data_widgets and all(w["scope"] == "layer" for w in data_widgets)
    assert len(api.maps[map_id]["layers"]) == 2


def test_no_widget_reads_a_coded_column_or_a_staff_column(built):
    api, h = built
    columns: set[str] = set()
    for seeder in (cam.seed_tree_dashboard, cam.seed_land_dashboard):
        sent = api.maps[seeder(h, api)]["dashboard_sent"]
        for widget in sent["widgets"]:
            config = widget["config"]
            columns |= {
                v
                for k, v in config.items()
                if k.endswith("column") and isinstance(v, str)
            }
            columns |= {s["column"] for s in config.get("stats", []) if s.get("column")}
    assert columns
    assert not columns & cam.TREE_CODED_COLUMNS
    assert not columns & cam.STAFF_COLUMNS


def test_a_coded_column_is_refused_for_a_widget():
    api = FakeApi()
    api.coded["d"] = {"sitetype"}
    with pytest.raises(RuntimeError, match="coded values"):
        cam._require_uncoded(api, "d", "Trees", ["sitetype"])
    with pytest.raises(RuntimeError, match="coded values"):
        cam._require_uncoded(api, "d", "Trees", ["overheadwires"])


def test_popups_and_visible_fields_leave_staff_columns_out(built):
    api, h = built
    layers = []
    for build in (
        cam.build_parcels_map,
        cam.seed_tree_dashboard,
        cam.seed_land_dashboard,
    ):
        layers += api.maps[build(h, api)]["layers"]
    assert layers
    for layer in layers:
        listed = set(layer["popup_config"].get("visible_fields", []))
        assert not listed & cam.STAFF_COLUMNS


def test_maps_before_the_catalog_report_what_is_missing():
    api = FakeApi()
    h = helpers(api)
    for builder in (
        cam.build_trees_map,
        cam.build_parcels_map,
        cam.seed_tree_dashboard,
        cam.seed_land_dashboard,
    ):
        assert builder(h, api).startswith("(missing: ")
    assert api.writes == []


def test_public_text_names_the_city_without_claiming_endorsement(built):
    api, h = built
    texts = [cam.COLLECTION_DESCRIPTION]
    for builder in (
        cam.build_parcels_map,
        cam.seed_tree_dashboard,
        cam.seed_land_dashboard,
    ):
        texts.append(api.maps[builder(h, api)]["description"])
    texts.append(cam.trees_map_description({"summary": {}}))
    for text in texts:
        assert "does not use or endorse GeoLens" in text
        assert len(text) <= 2000
        assert "real time" not in text.lower() and " live " not in text.lower()
    for name in cam.MAP_NAMES:
        assert name.startswith("Cambridge Open Data:")


def test_seeder_recognises_and_dispatches_the_section(monkeypatch):
    assert cam.DATASET_TITLES <= seed._showcase_dataset_titles()
    assert cam.MAP_NAMES <= seed._showcase_map_names()
    monkeypatch.setattr(sys, "argv", ["seed-showcase.py", "--only", "cambridge-nope"])
    with pytest.raises(SystemExit):
        seed.main()


def test_seeder_still_imports_without_the_cambridge_module(
    tmp_path, monkeypatch, capsys
):
    lone = tmp_path / "seed-showcase.py"
    lone.write_text((SCRIPTS / "seed-showcase.py").read_text())
    monkeypatch.delitem(sys.modules, "seed_showcase_cambridge", raising=False)
    monkeypatch.setattr(sys, "path", [p for p in sys.path if p != str(SCRIPTS)])
    lone_spec = importlib.util.spec_from_file_location("seed_showcase_lone", lone)
    lone_seed = importlib.util.module_from_spec(lone_spec)
    lone_spec.loader.exec_module(lone_seed)
    monkeypatch.delitem(sys.modules, "seed_showcase_cambridge", raising=False)

    assert lone_seed.cambridge is None
    assert "unavailable" in capsys.readouterr().err
    assert "Cambridge Street Trees" not in lone_seed._showcase_dataset_titles()
    assert lone_seed._CAMBRIDGE_UNAVAILABLE.startswith("(missing: ")


def test_a_parcels_failure_leaves_the_bindings_already_described(parcels_file):
    api = FakeApi()

    def broken(url):
        raise RuntimeError("download failed")

    h = helpers(api, fetch=broken)
    with pytest.raises(RuntimeError, match="download failed"):
        cam.build_catalog(h, api)

    bound = {t: api.datasets[api.created[t]] for t in BINDING_TITLES}
    for title, dataset in bound.items():
        assert dataset["summary"] == cam.CAMBRIDGE_METADATA[title]["summary"]
        assert dataset["license"] == cam.ONE_LICENSE
    assert len(api.collections) == 1


def test_global_metadata_pass_repairs_a_binding_left_with_the_stub():
    api = FakeApi()
    api.list_own_datasets = lambda: [
        {"title": d["title"], "id": i} for i, d in api.datasets.items()
    ]
    trees = api._dataset(cam.TREES_TITLE, origin="service")
    api.datasets[trees].update(summary="Earthquake data; binding...", license=None)

    assert cam.enrich_existing(api) == []

    spec = cam.CAMBRIDGE_METADATA[cam.TREES_TITLE]
    assert api.datasets[trees]["summary"] == spec["summary"]
    assert api.datasets[trees]["license"] == cam.ONE_LICENSE


def test_a_guarded_update_leaves_cambridge_datasets_alone(monkeypatch):
    calls = []
    monkeypatch.setattr(cam, "enrich_existing", lambda api: calls.append(api) or [])
    api = FakeApi()
    api.list_own_datasets = lambda: []

    seed.enrich_showcase_metadata(api, include_cambridge=False)
    assert calls == []
    seed.enrich_showcase_metadata(api)
    assert calls == [api]


def test_a_stub_from_an_earlier_run_is_withdrawn_by_title(parcels_file):
    api = FakeApi()
    h = helpers(api)
    stub = api._dataset(cam.TREES_TITLE, origin="upload")
    api.datasets[stub]["summary"] = "Earthquake data"

    def failing(*a, **k):
        raise RuntimeError("conversion failed")

    h.convert_to_service = failing
    with pytest.raises(RuntimeError):
        cam.build_catalog(h, api)

    assert api.datasets[stub]["visibility"] == "private"
    assert api.datasets[stub]["summary"] == cam.STUB_SUMMARY


def test_a_dataset_bound_elsewhere_is_reported_and_left_alone(parcels_file, capsys):
    api = FakeApi()
    h = helpers(api)
    other = api._dataset(
        cam.TREES_TITLE,
        origin="service",
        origin_uri="https://example.org/arcgis/rest/services/T/FeatureServer/0",
    )
    api.datasets[other]["summary"] = "someone else's"
    api.list_own_datasets = lambda: [{"title": cam.TREES_TITLE, "id": other}]

    with pytest.raises(RuntimeError, match="nothing was changed"):
        cam.build_catalog(h, api)
    assert cam.enrich_existing(api) == []
    assert cam._datasets(api, (cam.TREES_TITLE,)) is None

    assert api.writes == []
    assert api.datasets[other]["summary"] == "someone else's"
    assert "bound to 'https://example.org" in capsys.readouterr().err


def test_the_prune_report_knows_the_collection_by_a_literal():
    assert seed.CAMBRIDGE_COLLECTION == cam.COLLECTION_NAME


def test_collection_text_describes_only_what_exists(parcels_file):
    api = FakeApi()
    h = helpers(api)
    h.fetch = lambda url: (_ for _ in ()).throw(RuntimeError("download failed"))
    with pytest.raises(RuntimeError):
        cam.build_catalog(h, api)
    partial = next(iter(api.collections.values()))["description"]
    assert "upload" not in partial and "computed" not in partial
    assert "street trees" in partial

    h.fetch = lambda url: parcels_file
    cam.build_catalog(h, api)
    full = next(iter(api.collections.values()))["description"]
    assert full == cam.COLLECTION_DESCRIPTION
    assert "upload pinned" in full and "Two parcel datasets" in full


def test_the_neighborhood_picker_says_what_it_filters(built):
    api, h = built
    sent = api.maps[cam.seed_tree_dashboard(h, api)]["dashboard_sent"]
    picker = next(w for w in sent["widgets"] if w["type"] == "category_selector")
    assert "site-type chart and the trees layer" in picker["title"]
    about = next(w for w in sent["widgets"] if w["type"] == "markdown")
    text = about["config"]["text"]
    assert "site-type chart and the trees layer only" in text
    assert "follow the map view, not the neighborhood" in text


def test_derived_datasets_do_not_name_the_city_as_publisher():
    for title, spec in cam.CAMBRIDGE_METADATA.items():
        derived = title in (cam.PARCELS_ZONED_TITLE, cam.PARCELS_FLOOD_TITLE)
        assert ("source_organization" not in spec) == derived
        assert spec["license"] == cam.ONE_LICENSE
        assert spec["attribution"] == cam.ONE_ATTRIBUTION


def test_a_missing_webmap_file_skips_only_that_builder(built, monkeypatch, tmp_path):
    api, h = built
    monkeypatch.setattr(cam, "WEBMAP_PATH", tmp_path / "absent.json")
    result = cam.build_trees_map(h, api)
    assert result.startswith("(missing: ")
    assert "absent.json" in result


def test_the_parcels_map_needs_the_address_column(built):
    api, h = built
    api.dataset_columns = lambda dataset_id: {"ml"}
    before = len(api.writes)
    with pytest.raises(RuntimeError, match="full_addr"):
        cam.build_parcels_map(h, api)
    assert api.writes[before:] == []


@pytest.mark.parametrize("title", sorted(cam.PARCELS_MAP_COLUMNS))
def test_the_parcels_map_needs_every_column_its_layers_read(built, title):
    api, h = built
    dataset_id = api.datasets_by_title()[title]
    missing = cam.PARCELS_MAP_COLUMNS[title][0]
    full = FakeApi.dataset_columns(api, dataset_id)
    api.dataset_columns = lambda i: full - {missing} if i == dataset_id else full
    with pytest.raises(RuntimeError, match=missing):
        cam.build_parcels_map(h, api)
    assert not api.maps


# --- story and refresh ---------------------------------------------------------


class StoryApi(FakeApi):
    def __init__(self):
        super().__init__()
        self.stories: dict[str, dict] = {}
        self.uploads: list[str] = []
        self.published: list[dict] = []
        self.thumbnail: tuple[bytes, str] | None = (b"thumb", "image/webp")
        self.covers: dict[str, str] = {}
        self.upload_types: list[str] = []

    def aggregate(self, dataset_id, **body):
        flt = body.get("filter")
        if flt and flt.get("op") == "=":
            return {"count": 1000}
        if flt:
            return super().aggregate(dataset_id, **body)
        return {"count": 1234}

    def public_app_url(self):
        return "https://demo.example"

    def list_stories(self):
        return {s["title"]: i for i, s in self.stories.items()}

    def create_story(self, title, summary):
        story_id = self._id("story")
        self.stories[story_id] = {"title": title, "document": {"chapters": []}}
        return story_id

    def story_document(self, story_id):
        return self.stories[story_id]["document"]

    def story_cover_asset(self, story_id):
        return self.covers.get(story_id)

    def map_thumbnail(self, map_id):
        return self.thumbnail

    def upload_story_asset(self, story_id, filename, data, content_type="image/jpeg"):
        self.uploads.append(filename)
        self.upload_types.append(content_type)
        return str(uuid.UUID(int=10_000 + len(self.uploads)))

    def publish_story(self, story_id, title, summary, document, cover_asset_id=None):
        self.stories[story_id]["document"] = json.loads(json.dumps(document))
        self.covers[story_id] = cover_asset_id
        self.published.append({"cover": cover_asset_id, "document": document})


@pytest.fixture
def story_built(parcels_file, monkeypatch):
    api = StoryApi()
    h = helpers(api, fetch=lambda url: parcels_file)
    cam.build_catalog(h, api)

    def fake_import(api_, body):
        if body.get("dry_run"):
            return {"loss_report": {"summary": {}}}
        return {"map": {"id": api_.create_map(body["name"], "")}}

    monkeypatch.setattr(cam, "import_webmap", fake_import)
    for build in (
        cam.build_trees_map,
        cam.build_parcels_map,
        cam.seed_tree_dashboard,
        cam.seed_land_dashboard,
    ):
        build(h, api)
    for doc in api.maps.values():
        doc.update(center_lng=-71.1, center_lat=42.37, zoom=12.9, pitch=0, bearing=0)
    return api, h


def _story_buttons(document):
    return [
        block["config"]
        for chapter in document["chapters"]
        for block in chapter["blocks"]
        if block["type"] == "button"
    ]


def test_story_has_the_planned_chapters_and_reader_settings(story_built):
    api, h = story_built
    cam.seed_cambridge_story(h, api)
    document = api.published[-1]["document"]
    assert document["settings"] == {
        "layout": "floating",
        "panel_position": "left",
        "navigation": True,
        "transition": "glide",
        "theme": "follow",
    }
    assert len(document["chapters"]) == 9
    buttons = _story_buttons(document)
    assert buttons
    for config in buttons:
        assert config["url"].startswith(("https://", "http://"))
    scenes = [c["scene"] for c in document["chapters"] if c.get("scene")]
    assert len(scenes) == 7
    assert {s["map_id"] for s in scenes} <= set(api.maps)


def test_story_carousel_has_three_described_images_and_the_cover(story_built):
    api, h = story_built
    cam.seed_cambridge_story(h, api)
    published = api.published[-1]
    galleries = [
        block
        for chapter in published["document"]["chapters"]
        for block in chapter["blocks"]
        if block["type"] == "carousel"
    ]
    assert len(galleries) == 1
    images = galleries[0]["config"]["images"]
    assert len(images) == 3
    assert all(image["alt"].strip() for image in images)
    assert api.upload_types[:3] == ["image/png"] * 3
    assert published["cover"] not in {image["asset_id"] for image in images}
    assert api.uploads[-1] == "street-trees-map.webp"
    assert api.upload_types[-1] == "image/webp"


def test_story_cover_falls_back_to_the_first_image_without_a_thumbnail(story_built):
    api, h = story_built
    api.thumbnail = None
    cam.seed_cambridge_story(h, api)
    published = api.published[-1]
    first = next(
        block["config"]["images"][0]["asset_id"]
        for chapter in published["document"]["chapters"]
        for block in chapter["blocks"]
        if block["type"] == "carousel"
    )
    assert published["cover"] == first
    assert len(api.uploads) == 3


def test_story_inventory_chapter_carries_its_run_date(story_built):
    api, h = story_built
    cam.seed_cambridge_story(h, api)
    chapter = api.published[-1]["document"]["chapters"][1]
    text = chapter["blocks"][0]["config"]["text"]
    assert cam.INVENTORY_RUN_DATE in text
    assert "geolens arcgis inventory" in text


def test_story_code_blocks_fit_the_chapter_panel(story_built):
    # A floating chapter panel holds about 48 monospace characters per line.
    api, h = story_built
    cam.seed_cambridge_story(h, api)
    fence = chr(96) * 3
    for chapter in api.published[-1]["document"]["chapters"]:
        for block in chapter["blocks"]:
            if block["type"] != "markdown":
                continue
            parts = block["config"]["text"].split(fence)
            for code in parts[1::2]:
                for line in code.splitlines():
                    assert len(line) <= 48, (chapter["title"], line)


def test_story_figures_come_from_aggregates_and_names_the_city_once(story_built):
    api, h = story_built
    cam.seed_cambridge_story(h, api)
    document = api.published[-1]["document"]
    text = " ".join(
        block["config"]["text"]
        for chapter in document["chapters"]
        for block in chapter["blocks"]
        if block["type"] == "markdown"
    )
    assert "1,234 records, 1,000 of them standing trees" in text
    assert "Every vector dataset is an OGC API Features" in text
    assert "does not use or endorse GeoLens" in text
    assert text.count("does not use or endorse") == 1
    assert " live " not in text.lower()


def test_story_rerun_changes_nothing_and_uploads_once(story_built):
    api, h = story_built
    first = cam.seed_cambridge_story(h, api)
    document = json.dumps(api.published[-1]["document"], sort_keys=True)
    assert cam.seed_cambridge_story(h, api) == first
    assert json.dumps(api.published[-1]["document"], sort_keys=True) == document
    assert len(api.uploads) == 4
    assert len(api.stories) == 1


def test_story_before_the_maps_reports_what_is_missing():
    api = StoryApi()
    h = helpers(api)
    assert cam.seed_cambridge_story(h, api).startswith("(missing: ")
    assert api.stories == {}


def _refresh_fixture(api, h, failing=()):
    quake = "Recent Earthquakes (M2.5+, last 30 days)"
    api._dataset(quake, origin="service")
    refreshed = []

    def refresh(api_, dataset_id, title):
        refreshed.append(title)
        return title not in failing

    h.refresh_and_report = refresh
    h.refresh_quakes = lambda api_: (refreshed.append(quake), 0)[1]
    return quake, refreshed


def test_refresh_services_runs_quakes_then_bindings_with_trees_last(built):
    api, h = built
    quake, refreshed = _refresh_fixture(api, h)
    assert cam.refresh_services(h, api, (quake,)) == 0
    assert refreshed[0] == quake
    assert sorted(refreshed[1:]) == sorted(BINDING_TITLES)
    assert refreshed[-1] == cam.TREES_TITLE


def test_refresh_services_keeps_going_and_fails_when_one_fails(built):
    api, h = built
    quake, refreshed = _refresh_fixture(api, h, failing={cam.ZONING_TITLE})
    assert cam.refresh_services(h, api, (quake,)) == 1
    assert len(refreshed) == 1 + len(BINDING_TITLES)


def test_refresh_services_refuses_a_dataset_that_is_not_service_origin(built):
    api, h = built
    api.datasets[api.created[cam.ZONING_TITLE]]["origin"] = "upload"
    quake, refreshed = _refresh_fixture(api, h)
    assert cam.refresh_services(h, api, (quake,)) == 1
    assert cam.ZONING_TITLE not in refreshed
    assert len(refreshed) == len(BINDING_TITLES)


def test_refresh_services_fails_when_the_quake_refresh_fails(built):
    api, h = built
    quake, refreshed = _refresh_fixture(api, h)
    h.refresh_quakes = lambda api_: 1
    assert cam.refresh_services(h, api, (quake,)) == 1
    assert refreshed[-1] == cam.TREES_TITLE


def test_refresh_services_continues_past_a_transport_error(built):
    api, h = built
    quake, refreshed = _refresh_fixture(api, h)
    real_origin = api.dataset_origin

    def flaky_origin(dataset_id):
        if api.datasets[dataset_id]["title"] == cam.ZONING_TITLE:
            raise httpx.ConnectError("boom")
        return real_origin(dataset_id)

    api.dataset_origin = flaky_origin
    assert cam.refresh_services(h, api, (quake,)) == 1
    assert cam.ZONING_TITLE not in refreshed
    assert refreshed[-1] == cam.TREES_TITLE


def test_refresh_services_also_refreshes_another_owned_service_binding(built):
    api, h = built
    quake, refreshed = _refresh_fixture(api, h)
    api._dataset("Recent Earthquakes - Heatmap source", origin="service")
    assert cam.refresh_services(h, api, (quake,)) == 0
    assert "Recent Earthquakes - Heatmap source" in refreshed
    assert refreshed[-1] == cam.TREES_TITLE


def test_refresh_services_refreshes_two_datasets_under_one_title(built):
    api, h = built
    quake, refreshed = _refresh_fixture(api, h)
    api._dataset(cam.ZONING_TITLE, origin="service")
    assert cam.refresh_services(h, api, (quake,)) == 0
    assert refreshed.count(cam.ZONING_TITLE) == 2
    assert refreshed[-1] == cam.TREES_TITLE


def test_refresh_services_survives_a_quake_refresh_transport_error(built):
    api, h = built
    quake, refreshed = _refresh_fixture(api, h)

    def boom(api_):
        raise httpx.ConnectError("boom")

    h.refresh_quakes = boom
    assert cam.refresh_services(h, api, (quake,)) == 1
    assert refreshed[-1] == cam.TREES_TITLE


def test_seeder_dispatches_refresh_services_to_the_cambridge_module(monkeypatch):
    calls = []

    def fake(namespace, api, quake_titles):
        calls.append(quake_titles)
        return 7

    monkeypatch.setattr(cam, "refresh_services", fake)
    args = types.SimpleNamespace(
        refresh_services=True,
        refresh_quakes=False,
        refresh_hurdat2=False,
        prune_userdata=False,
        story_and_dashboard=False,
    )
    assert seed.run_maintenance_mode(object(), args) == 7
    assert calls == [
        (seed.QUAKES_TITLE, seed.QUAKES_TITLE_LEGACY, seed.QUAKES_HEAT_LEGACY_TITLE)
    ]


def test_hidden_tree_layers_sit_in_one_collapsed_group():
    layers = cam._tree_layers("ds")
    hidden = [x for x in layers if x.get("visible") is False]
    assert len(hidden) == 3
    groups = {json.dumps(x["style_config"]["builder"], sort_keys=True) for x in hidden}
    assert len(groups) == 1
    builder = hidden[0]["style_config"]["builder"]
    assert builder["folder_group_expanded"] is False
    drawn = [x for x in layers if x.get("visible") is not False]
    assert all(
        "folder_group_id" not in (x.get("style_config") or {}).get("builder", {})
        for x in drawn
    )


# --- polish --------------------------------------------------------------------


def _chapter(document, key):
    return next(
        c
        for c in document["chapters"]
        if c["id"] == seed._seed_id("story", "cambridge-" + key)
    )


def test_story_chapters_each_get_their_own_view(story_built):
    api, h = story_built
    cam.seed_cambridge_story(h, api)
    document = api.published[-1]["document"]
    webmap = _chapter(document, "webmap")["scene"]
    assert webmap["camera"]["zoom"] >= 14
    origin = _chapter(document, "origin")["scene"]
    assert webmap["camera"] != origin["camera"]

    flood = _chapter(document, "parcels")["scene"]
    layers = {x["display_name"]: x["id"] for x in api.maps[flood["map_id"]]["layers"]}
    assert flood["layer_visibility"] == {layers["Zoning districts"]: False}
    assert flood["camera"]["center"] == [cam.FLOOD_VIEW[0], cam.FLOOD_VIEW[1]]


def test_story_closing_chapters_sit_on_a_calm_map(story_built):
    api, h = story_built
    cam.seed_cambridge_story(h, api)
    document = api.published[-1]["document"]
    scene = _chapter(document, "clients")["scene"]
    layers = {x["id"]: x["display_name"] for x in api.maps[scene["map_id"]]["layers"]}
    shown = {layers[i] for i, on in scene["layer_visibility"].items() if on}
    assert shown == set(cam.PARCELS_CALM_LAYERS)
    assert set(scene["layer_visibility"]) == set(layers)
    # The chapters after it keep that scene.
    assert _chapter(document, "signed-in")["scene"] is None
    assert _chapter(document, "run")["scene"] is None


def test_story_title_fits_a_chapter_tab_and_the_last_button_names_the_collection(
    story_built,
):
    api, h = story_built
    cam.seed_cambridge_story(h, api)
    assert len(cam.STORY_TITLE) <= 34
    labels = [c["label"] for c in _story_buttons(api.published[-1]["document"])]
    assert labels[-1] == "Browse the Cambridge collection"


@pytest.mark.parametrize("legacy", cam.STORY_TITLES_LEGACY)
def test_story_under_an_old_title_is_renamed_in_place(story_built, legacy):
    api, h = story_built
    old = api.create_story(legacy, cam.STORY_SUMMARY)
    renamed = []
    publish = api.publish_story

    def publish_story(story_id, title, *args, **kwargs):
        renamed.append((story_id, title))
        api.stories[story_id]["title"] = title
        return publish(story_id, title, *args, **kwargs)

    api.publish_story = publish_story
    assert cam.seed_cambridge_story(h, api) == old
    assert renamed == [(old, cam.STORY_TITLE)]
    assert list(api.stories) == [old]


def _png_size(path):
    data = path.read_bytes()
    return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")


def test_gallery_pictures_are_squarish_and_small():
    for name, _, _ in cam.STORY_IMAGES:
        path = cam.ASSETS_DIR / name
        width, height = _png_size(path)
        assert 0.5 <= width / height <= 1.5, name
        assert path.stat().st_size < 60_000, name


def test_a_changed_gallery_picture_is_uploaded_again(
    story_built, tmp_path, monkeypatch
):
    api, h = story_built
    cam.seed_cambridge_story(h, api)
    assert len(api.uploads) == 4
    for name, _, _ in cam.STORY_IMAGES:
        (tmp_path / name).write_bytes((cam.ASSETS_DIR / name).read_bytes() + b"x")
    monkeypatch.setattr(cam, "ASSETS_DIR", tmp_path)
    cam.seed_cambridge_story(h, api)
    assert len(api.uploads) == 7


def test_zoning_colors_are_all_different_and_clear_of_the_flood_layers():
    colors = [color for _, color in cam.ZONE_COLORS]
    assert len(set(colors)) == len(colors)
    assert cam._FLAGGED_RED not in colors and cam._FLOOD_BLUE not in colors
    assert cam._FLAGGED_RED != cam._FLOOD_BLUE


def test_flagged_parcels_are_outlined_in_their_own_color(built):
    api, h = built
    layers = {
        x["display_name"]: x for x in api.maps[cam.build_parcels_map(h, api)]["layers"]
    }
    flagged = layers["Parcels touching the 1% floodplain"]
    plain = layers["FEMA 1% annual-chance floodplain"]
    assert flagged["style_config"]["builder"]["outline_color"] == cam._FLAGGED_RED
    assert plain["paint"]["fill-color"] == cam._FLOOD_BLUE


def test_land_dashboard_rows_fill_a_five_column_page_grid(built):
    api, h = built
    widgets = api.maps[cam.seed_land_dashboard(h, api)]["dashboard_sent"]["widgets"]
    wide = {"bar_chart", "pie_chart", "histogram", "table", "feature_list"}
    row = 0
    for widget in widgets:
        row += 2 if widget["type"] in wide else 1
        assert row <= 5
        row %= 5
    assert row == 0
    pies = [w for w in widgets if w["type"] == "pie_chart"]
    assert pies and all(w["config"]["limit"] == 6 for w in pies)


def test_proposed_planting_sites_have_a_legend_entry(built):
    api, h = built
    layers = api.maps[cam.seed_tree_dashboard(h, api)]["layers"]
    proposed = next(x for x in layers if x["display_name"] == "Proposed planting sites")
    assert proposed["show_in_legend"] is True


def test_tree_dashboard_charts_the_most_common_species(built):
    api, h = built
    widgets = api.maps[cam.seed_tree_dashboard(h, api)]["dashboard_sent"]["widgets"]
    titles = [w["title"] for w in widgets]
    species = next(w for w in widgets if w["title"].startswith("Most common species"))
    assert species["type"] == "bar_chart"
    assert species["config"] == {"column": "commonname", "stat": "count", "limit": 10}
    assert titles.index(species["title"]) == titles.index("Trees by site type") + 1


def test_zoning_colors_follow_parcel_counts_not_district_polygons():
    codes = [code for code, _ in cam.ZONE_COLORS]
    assert len(codes) == 12
    assert {"CAM-6", "MAS-12"} <= set(codes)
    assert not {"IA-1", "C-3B", "C-2A"} & set(codes)


_ZONE_IDS = {
    title: f"ds-{i}"
    for i, title in enumerate(
        (
            cam.ADDRESSES_TITLE,
            cam.NEIGHBORHOODS_TITLE,
            cam.ZONING_TITLE,
            cam.FLOOD_TITLE,
            cam.PARCELS_ZONED_TITLE,
            cam.PARCELS_FLOOD_TITLE,
        )
    )
}


def test_the_calm_story_scene_draws_only_layers_the_legend_lists():
    layers = {x["display_name"]: x for x in cam._parcels_map_layers(_ZONE_IDS)}
    for name in cam.PARCELS_CALM_LAYERS:
        assert layers[name]["show_in_legend"] is True


def test_the_zoning_legend_follows_the_parcel_ranking():
    layers = {x["display_name"]: x for x in cam._parcels_map_layers(_ZONE_IDS)}
    values = [
        entry["value"]
        for entry in layers["Zoning districts"]["style_config"]["categories"]
    ]
    assert values[: len(cam.ZONE_COLORS)] == [code for code, _ in cam.ZONE_COLORS]


def test_a_cambridge_stub_gets_the_neutral_summary(parcels_file):
    api = FakeApi()
    h = helpers(api, fetch=lambda url: parcels_file)
    cam.build_catalog(h, api)
    assert set(api.stub_summaries) == {cam.STUB_SUMMARY}


def test_the_seeder_stub_summary_is_a_default_the_caller_can_replace():
    import inspect

    default = inspect.signature(seed.ingest_service).parameters["stub_summary"].default
    assert default == seed._SERVICE_STUB_SUMMARY


def test_a_map_only_run_refuses_a_binding_still_a_stub():
    api = FakeApi()
    api._dataset(cam.TREES_TITLE, origin="upload")
    assert cam._datasets(api, (cam.TREES_TITLE,)) is None


def test_enrich_continues_past_a_transport_error(built, monkeypatch):
    api, h = built
    real = cam._apply_metadata
    seen = []

    def flaky(api_, dataset_id, title):
        seen.append(title)
        if len(seen) == 1:
            raise httpx.ConnectError("boom")
        return real(api_, dataset_id, title)

    monkeypatch.setattr(cam, "_apply_metadata", flaky)
    failed = cam.enrich_existing(api)
    assert failed == [seen[0]]
    assert len(seen) > 1


@pytest.mark.parametrize("missing", ["sitetype", "commonname", "diameter", "plantdate"])
def test_the_trees_map_needs_its_style_and_popup_columns(built, missing):
    api, h = built
    full = FakeApi.dataset_columns(api, None)
    api.dataset_columns = lambda i: full - {missing}
    with pytest.raises(RuntimeError, match=missing):
        cam.build_trees_map(h, api)
    assert cam.TREES_MAP not in api.list_maps()


@pytest.mark.parametrize("title", [cam.PARCELS_ZONED_TITLE, cam.PARCELS_FLOOD_TITLE])
def test_the_land_dashboard_needs_ml_on_both_parcel_datasets(built, title):
    api, h = built
    dataset_id = api.datasets_by_title()[title]
    full = FakeApi.dataset_columns(api, dataset_id)
    api.dataset_columns = lambda i: full - {"ml"} if i == dataset_id else full
    with pytest.raises(RuntimeError, match="ml"):
        cam.seed_land_dashboard(h, api)
