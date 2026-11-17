"""The widget instance contract shared by map dashboards and story blocks."""

import copy
import uuid
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel, TypeAdapter, ValidationError

from app.modules.catalog.widgets.schemas import (
    CURRENT_VERSIONS,
    HOST_WIDGET_MODELS,
    UPGRADERS,
    DashboardWidgets,
    StoryBlocks,
    read_stored,
    to_store,
    upgrade,
)

LAYER = str(uuid.uuid4())

SAMPLES: dict[str, dict[str, Any]] = {
    "indicator": {"layer_id": LAYER, "config": {"stat": "sum", "column": "pop"}},
    "bar_chart": {"layer_id": LAYER, "config": {"column": "landuse"}},
    "pie_chart": {"layer_id": LAYER, "config": {"column": "landuse"}},
    "feature_list": {"layer_id": LAYER, "config": {"title_column": "name"}},
    "table": {
        "layer_id": LAYER,
        "config": {"group_column": "landuse", "stats": [{"stat": "count"}]},
    },
    "histogram": {"layer_id": LAYER, "scope": "view", "config": {"column": "pop"}},
    "category_selector": {"layer_id": LAYER, "config": {"column": "landuse"}},
    "markdown": {"config": {"text": "# Chapter one"}},
    "image": {"asset_id": str(uuid.uuid4()), "config": {"alt": "A river"}},
    "gallery": {
        "config": {"images": [{"asset_id": str(uuid.uuid4()), "alt": "A river"}]}
    },
    "carousel": {
        "config": {"images": [{"asset_id": str(uuid.uuid4()), "alt": "A river"}]}
    },
    "button": {"config": {"label": "Read the report", "url": "https://example.com/r"}},
    "separator": {"config": {}},
    "embed": {"config": {"url": "https://media.example.org/c", "title": "A chart"}},
    "video": {"config": {"url": "https://media.example.org/v", "title": "A talk"}},
}


def _widget(kind: str, **overrides: Any) -> dict[str, Any]:
    body = copy.deepcopy(SAMPLES[kind])
    return {"id": str(uuid.uuid4()), "type": kind, "v": 1, **body, **overrides}


def _without(kind: str, key: str) -> dict[str, Any]:
    return {k: v for k, v in _widget(kind).items() if k != key}


def _dashboard(items: list[Any]) -> list[Any]:
    return TypeAdapter(DashboardWidgets).validate_python(items)


def _story(items: list[Any]) -> list[Any]:
    return TypeAdapter(StoryBlocks).validate_python(items)


class TestEveryTypeFollowsTheContract:
    """The backend half of the contribution template: a new type passes these or fails CI."""

    def test_each_host_schema_is_a_union_discriminated_on_type(self) -> None:
        mappings = [
            TypeAdapter(adapter_type).json_schema()["items"]["discriminator"]
            for adapter_type in (DashboardWidgets, StoryBlocks)
        ]
        assert {m["propertyName"] for m in mappings} == {"type"}
        assert {t for m in mappings for t in m["mapping"]} == set(CURRENT_VERSIONS)

    def test_every_instance_and_config_model_forbids_extra_fields(self) -> None:
        for models in HOST_WIDGET_MODELS.values():
            for model in models:
                config = model.model_fields["config"].annotation
                assert model.model_config.get("extra") == "forbid", model
                assert config.model_config.get("extra") == "forbid", config

    def test_every_older_version_has_an_upgrader(self) -> None:
        missing = [
            (kind, v)
            for kind, current in CURRENT_VERSIONS.items()
            for v in range(1, current)
            if (kind, v) not in UPGRADERS
        ]
        assert missing == []

    def test_every_type_has_a_sample_valid_in_its_own_host(self) -> None:
        assert set(SAMPLES) == set(CURRENT_VERSIONS)
        for kind in SAMPLES:
            hosts = []
            for validate in (_dashboard, _story):
                try:
                    validate([_widget(kind)])
                    hosts.append(validate)
                except ValidationError:
                    pass
            # Text is the one type both hosts take.
            assert len(hosts) == (2 if kind == "markdown" else 1), kind


class TestAClientSendingWhatTheServerCantParseIsRefused:
    @pytest.mark.parametrize(
        "item",
        [
            pytest.param(_widget("histogram", type="timeline"), id="unknown type"),
            pytest.param(_widget("histogram", v=9), id="newer v"),
            pytest.param(_widget("histogram", v=0), id="older v without an upgrader"),
            pytest.param(_widget("image"), id="a story block on a dashboard"),
            pytest.param(
                _widget("markdown", layer_id=LAYER), id="text bound to a layer"
            ),
            pytest.param(
                _widget("markdown", config={"text": "x" * 20_001}),
                id="text over the length cap",
            ),
            pytest.param(_widget("histogram", extra=1), id="extra instance field"),
            pytest.param(
                _widget("histogram", config={"column": "pop", "colour": "red"}),
                id="extra config field",
            ),
            pytest.param(
                _widget("histogram", asset_id=str(uuid.uuid4())),
                id="a binding the type doesn't take",
            ),
            pytest.param(
                _without("histogram", "layer_id"), id="a missing layer binding"
            ),
            pytest.param(_without("histogram", "v"), id="no v"),
            pytest.param(
                _widget("indicator", config={"stat": "sum"}), id="sum with no column"
            ),
            pytest.param(
                _widget("indicator", config={"stat": "count", "column": "pop"}),
                id="count with a column",
            ),
            pytest.param(
                _widget("bar_chart", config={"column": "landuse", "stat": "mean"}),
                id="mean with no stat_column",
            ),
            pytest.param(
                _widget("histogram", config={"column": "pop", "bins": 51}),
                id="too many bins",
            ),
        ],
    )
    def test_dashboard_widget_is_refused(self, item: dict[str, Any]) -> None:
        with pytest.raises(ValidationError):
            _dashboard([item])

    @pytest.mark.parametrize(
        "item",
        [
            pytest.param(_widget("histogram"), id="a dashboard widget in a story"),
            pytest.param(_without("image", "asset_id"), id="an image with no asset"),
            pytest.param(
                _widget("image", config={"alt": "  "}), id="an image with no alt text"
            ),
            pytest.param(
                _widget("image", config={"caption": "River"}),
                id="an image without alt",
            ),
            pytest.param(
                _widget("image", config={"decorative": False}),
                id="an image that isn't decorative, without alt",
            ),
        ],
    )
    def test_story_block_is_refused(self, item: dict[str, Any]) -> None:
        with pytest.raises(ValidationError):
            _story([item])

    def test_a_decorative_image_needs_no_alt_and_stores_without_one(self) -> None:
        item = _widget("image", config={"decorative": True})

        stored = to_store(_story([item]), [])

        assert stored[0]["config"] == {"decorative": True, "caption": None}

    def test_an_image_that_isnt_decorative_stores_the_shape_older_servers_read(
        self,
    ) -> None:
        stored = to_store(_story([_widget("image")]), [])

        assert stored[0]["config"] == {"alt": "A river", "caption": None}

    @pytest.mark.parametrize("kind", ["gallery", "carousel"])
    def test_each_image_of_a_gallery_needs_alt_unless_decorative(
        self, kind: str
    ) -> None:
        asset = str(uuid.uuid4())
        decorative = {"asset_id": asset, "decorative": True}
        stored = to_store(_story([_widget(kind, config={"images": [decorative]})]), [])
        assert stored[0]["config"]["images"][0]["decorative"] is True
        assert "alt" not in stored[0]["config"]["images"][0]

        with pytest.raises(ValidationError):
            _story(
                [_widget(kind, config={"images": [{"asset_id": asset, "alt": " "}]})]
            )
        with pytest.raises(ValidationError):
            _story(
                [
                    _widget(
                        kind,
                        config={
                            "images": [decorative, {"asset_id": asset, "caption": "x"}]
                        },
                    )
                ]
            )

    @pytest.mark.parametrize("kind", ["gallery", "carousel"])
    def test_a_gallery_holds_one_to_twelve_images(self, kind: str) -> None:
        def image() -> dict[str, Any]:
            return {"asset_id": str(uuid.uuid4()), "alt": "A river"}

        assert (
            len(
                _story([_widget(kind, config={"images": [image() for _ in range(12)]})])
            )
            == 1
        )
        for images in ([], [image() for _ in range(13)]):
            with pytest.raises(ValidationError):
                _story([_widget(kind, config={"images": images})])

    def test_a_gallery_image_refuses_unknown_keys(self) -> None:
        image = {"asset_id": str(uuid.uuid4()), "alt": "A river", "href": "x"}
        with pytest.raises(ValidationError):
            _story([_widget("gallery", config={"images": [image]})])

    @pytest.mark.parametrize(
        "url",
        [
            "javascript:alert(1)",
            "JavaScript:alert(1)",
            "data:text/html,<script>alert(1)</script>",
            "javascript://example.com/%0Aalert(1)",
            "data://example.com/text",
            "vbscript:msgbox(1)",
            "file:///etc/passwd",
            "ftp://example.com/a",
            "//example.com/a",
            "/relative/path",
            "example.com",
            "https://",
            "http:///path",
            "https://exa mple.com",
            "https://example.com/\nx",
            "https://user:pass@example.com/a",
            "https://example.com:99999/a",
            "",
        ],
    )
    def test_a_button_url_must_be_http_or_https(self, url: str) -> None:
        item = _widget("button", config={"label": "Go", "url": url})
        with pytest.raises(ValidationError):
            _story([item])

    @pytest.mark.parametrize(
        "url", ["http://example.com", "HTTPS://Example.com/a?b=1#c"]
    )
    def test_a_button_takes_http_and_https(self, url: str) -> None:
        block = _story([_widget("button", config={"label": " Go ", "url": url})])[0]
        assert block.config.url == url
        assert block.config.label == "Go"
        assert block.config.new_tab is False

    @pytest.mark.parametrize(
        "config",
        [
            {"label": "  ", "url": "https://example.com"},
            {"label": "x" * 121, "url": "https://example.com"},
            {"label": "Go", "url": "https://example.com/" + "a" * 2048},
            {"label": "Go", "url": "https://example.com", "new_tab": "yes"},
            {"label": "Go", "url": "https://example.com", "colour": "red"},
        ],
    )
    def test_a_button_config_is_bounded(self, config: dict[str, Any]) -> None:
        with pytest.raises(ValidationError):
            _story([_widget("button", config=config)])

    @pytest.mark.parametrize("config", [{"style": "dots"}, {"text": "x"}])
    def test_a_separator_takes_only_line_or_gap(self, config: dict[str, Any]) -> None:
        with pytest.raises(ValidationError):
            _story([_widget("separator", config=config)])

    def test_a_separator_defaults_to_a_line(self) -> None:
        assert _story([_widget("separator")])[0].config.style == "line"

    def test_duplicate_ids_are_refused(self) -> None:
        first = _widget("histogram")
        with pytest.raises(ValidationError, match="more than once"):
            _dashboard([first, _widget("indicator", id=first["id"])])

    def test_an_unknown_type_in_a_request_body_is_a_422(self) -> None:
        class Body(BaseModel):
            widgets: DashboardWidgets

        app = FastAPI()

        @app.put("/config")
        def put_config(body: Body) -> int:
            return len(body.widgets)

        client = TestClient(app)
        assert (
            client.put("/config", json={"widgets": [_widget("histogram")]}).json() == 1
        )
        response = client.put(
            "/config", json={"widgets": [_widget("histogram", type="timeline")]}
        )
        assert response.status_code == 422


class TestStoredWidgetsTheServerCantParseSurviveASave:
    """A downgraded server reads, and a client saves, without deleting anything."""

    def test_a_downgrade_then_save_writes_every_stored_item_back_unchanged(
        self,
    ) -> None:
        first, last = [
            w.model_dump(mode="json")
            for w in _dashboard([_widget("indicator"), _widget("bar_chart")])
        ]
        from_a_newer_release = [
            _widget("histogram", type="time_series", config={"column": "t"}),
            _widget("histogram", v=9, config={"column": "pop", "bins": "auto"}),
        ]
        # Valid once, refused by a tightened cap, and not an object at all.
        damaged = [_widget("histogram", config={"column": "pop", "bins": 500}), "?"]
        stored = [first, *from_a_newer_release, last, *damaged]
        before = copy.deepcopy(stored)

        read = read_stored(stored, "dashboard")
        response = [w.model_dump(mode="json") for w in read.widgets]
        assert [w["id"] for w in response] == [first["id"], last["id"]]

        # The client re-sends exactly what it was given.
        saved = to_store(_dashboard(response), read.unreadable)

        assert saved == before
        # Counterfactual: storing the client's list alone drops four items.
        assert len(to_store(_dashboard(response), [])) == 2
        assert stored == before

    @pytest.mark.parametrize(
        ("stored", "sent", "expected"),
        [
            pytest.param("aXbc", "cb", "Xcb", id="anchor deleted, others reordered"),
            pytest.param("abXc", "cab", "cabX", id="anchor moved to the end"),
            pytest.param("abXc", "ca", "caX", id="nearest anchor deleted"),
            pytest.param("XaYb", "ba", "XbaY", id="one at the start, one anchored"),
            pytest.param("aXYb", "ba", "baXY", id="two on one anchor keep their order"),
            pytest.param("abX", "", "X", id="everything visible deleted"),
        ],
    )
    def test_kept_items_follow_the_visible_widget_stored_before_them(
        self, stored: str, sent: str, expected: str
    ) -> None:
        """Each letter is a widget: lower case visible, upper case unparseable."""
        widgets = {
            name: _widget("histogram", type="time_series")
            if name.isupper()
            else _dashboard([_widget("histogram")])[0].model_dump(mode="json")
            for name in stored
        }
        read = read_stored([widgets[name] for name in stored], "dashboard")

        saved = to_store(_dashboard([widgets[name] for name in sent]), read.unreadable)

        assert saved == [widgets[name] for name in expected]

    def test_a_sent_instance_replaces_a_kept_one_with_the_same_id(self) -> None:
        unknown = _widget("histogram", v=9)
        read = read_stored([unknown], "dashboard")
        replacement = _widget("histogram", id=unknown["id"])

        saved = to_store(_dashboard([replacement]), read.unreadable)

        assert saved == [_dashboard([replacement])[0].model_dump(mode="json")]

    def test_nothing_stored_reads_as_empty(self) -> None:
        assert read_stored(None, "story") == ([], [])


class TestOlderInstancesUpgradeOnReadAndOnWrite:
    @pytest.fixture
    def histogram_v0(self, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
        """A hypothetical v0 histogram that named its bin count ``buckets``."""

        def v0_to_v1(raw: dict[str, Any]) -> dict[str, Any]:
            raw["config"]["bins"] = raw["config"].pop("buckets")
            return raw

        monkeypatch.setitem(UPGRADERS, ("histogram", 0), v0_to_v1)
        return _widget("histogram", v=0, config={"column": "pop", "buckets": 7})

    def test_read_returns_the_current_shape_and_leaves_the_stored_item_alone(
        self, histogram_v0: dict[str, Any]
    ) -> None:
        before = copy.deepcopy(histogram_v0)

        read = read_stored([histogram_v0], "dashboard")

        assert read.unreadable == []
        assert read.widgets[0].v == 1
        assert read.widgets[0].config.bins == 7
        assert histogram_v0 == before

    def test_a_client_sending_an_old_version_is_stored_current(
        self, histogram_v0: dict[str, Any]
    ) -> None:
        saved = to_store(_dashboard([histogram_v0]), [])

        assert saved[0]["v"] == 1
        assert saved[0]["config"] == {"column": "pop", "bins": 7}

    def test_a_stored_item_whose_upgrader_raises_is_set_aside(
        self, histogram_v0: dict[str, Any]
    ) -> None:
        del histogram_v0["config"]["buckets"]
        before = copy.deepcopy(histogram_v0)

        read = read_stored([histogram_v0], "dashboard")

        assert read.widgets == []
        assert [item.raw for item in read.unreadable] == [before]

    @pytest.mark.parametrize("host", ["dashboard", "story"])
    def test_a_stored_item_whose_type_is_not_a_string_is_set_aside(
        self, host: str
    ) -> None:
        stored = [{"type": [], "v": 1}, {"type": {"a": 1}, "v": 1}]

        read = read_stored(copy.deepcopy(stored), host)

        assert read.widgets == []
        assert [item.raw for item in read.unreadable] == stored

    def test_a_sent_item_whose_upgrader_raises_is_a_validation_error(
        self, histogram_v0: dict[str, Any]
    ) -> None:
        del histogram_v0["config"]["buckets"]

        with pytest.raises(ValidationError, match="could not be upgraded"):
            _dashboard([histogram_v0])

    def test_an_upgrade_that_fails_validation_keeps_the_original(
        self, histogram_v0: dict[str, Any]
    ) -> None:
        histogram_v0["config"]["buckets"] = 500
        before = copy.deepcopy(histogram_v0)

        read = read_stored([histogram_v0], "dashboard")

        assert [item.raw for item in read.unreadable] == [before]
        assert to_store([], read.unreadable) == [before]

    def test_the_upgrade_walks_every_step(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def rename(old: str, new: str) -> Any:
            return lambda raw: {new if k == old else k: v for k, v in raw.items()}

        monkeypatch.setitem(CURRENT_VERSIONS, "markdown", 3)
        monkeypatch.setitem(UPGRADERS, ("markdown", 1), rename("text", "body"))
        monkeypatch.setitem(UPGRADERS, ("markdown", 2), rename("body", "text"))

        upgraded = upgrade({"type": "markdown", "v": 1, "text": "hi"})

        assert upgraded == {"type": "markdown", "v": 3, "text": "hi"}


def _bar(**config: Any) -> dict[str, Any]:
    return _widget("bar_chart", config=config)


class TestBarChartModes:
    def test_a_category_chart_gets_the_defaults_and_stays_valid(self) -> None:
        (widget,) = _dashboard([_widget("bar_chart")])
        config = widget.config
        assert (config.mode, config.sort, config.fields) == ("category", "desc", [])
        assert config.use_layer_colors is True
        assert config.date_bucket is None

    @pytest.mark.parametrize(
        "config",
        [
            {"mode": "category", "column": "landuse", "use_layer_colors": False},
            {
                "mode": "by_feature",
                "label_column": "name",
                "value_column": "pop",
                "sort": "asc",
            },
            {"mode": "by_fields", "fields": ["a", "b"], "stat": "mean"},
            {"mode": "date", "column": "built", "date_bucket": "month"},
        ],
    )
    def test_each_mode_accepts_its_own_fields(self, config: dict[str, Any]) -> None:
        (widget,) = _dashboard([_bar(**config)])
        assert widget.config.mode == config["mode"]

    @pytest.mark.parametrize(
        ("config", "message"),
        [
            ({"mode": "category"}, "column is required when mode is category"),
            ({"mode": "date", "column": "d"}, "date_bucket is required"),
            (
                {"mode": "date", "date_bucket": "day"},
                "column is required when mode is date",
            ),
            ({"mode": "by_feature", "label_column": "n"}, "value_column are required"),
            ({"mode": "by_fields"}, "fields is required when mode is by_fields"),
            (
                {"mode": "by_fields", "fields": ["a", "a"]},
                "fields must not repeat a name",
            ),
            (
                {"mode": "by_fields", "fields": [f"f{i}" for i in range(21)]},
                "at most 20",
            ),
            (
                {"mode": "category", "column": "c", "fields": ["a"]},
                "fields does not apply when mode is category",
            ),
            (
                {"mode": "category", "column": "c", "date_bucket": "day"},
                "date_bucket does not apply when mode is category",
            ),
            (
                {"mode": "category", "column": "c", "sort": "asc"},
                "sort does not apply when mode is category",
            ),
            (
                {
                    "mode": "date",
                    "column": "c",
                    "date_bucket": "day",
                    "use_layer_colors": False,
                },
                "use_layer_colors does not apply when mode is date",
            ),
            (
                {
                    "mode": "by_feature",
                    "column": "c",
                    "label_column": "n",
                    "value_column": "v",
                },
                "column does not apply when mode is by_feature",
            ),
            (
                {
                    "mode": "date",
                    "column": "c",
                    "date_bucket": "day",
                    "label_column": "n",
                },
                "label_column does not apply when mode is date",
            ),
            (
                {"mode": "date", "column": "c", "date_bucket": "week", "stat": "sum"},
                "stat_column is required unless stat is count",
            ),
            (
                {
                    "mode": "by_fields",
                    "fields": ["a"],
                    "stat": "sum",
                    "stat_column": "x",
                },
                "stat_column does not apply when mode is by_fields",
            ),
            ({"mode": "weekly", "column": "c"}, "mode"),
        ],
    )
    def test_a_mode_refuses_missing_and_foreign_fields(
        self, config: dict[str, Any], message: str
    ) -> None:
        with pytest.raises(ValidationError, match=message):
            _dashboard([_bar(**config)])


class TestNewWidgetKinds:
    @pytest.mark.parametrize("kind", ["pie_chart", "feature_list", "table"])
    def test_defaults_fill_in_and_round_trip(self, kind: str) -> None:
        (widget,) = _dashboard([_widget(kind)])
        dumped = widget.model_dump(mode="json")
        assert _dashboard([dumped])[0].model_dump(mode="json") == dumped

    def test_pie_and_list_and_table_defaults(self) -> None:
        pie, fl, table = _dashboard(
            [_widget("pie_chart"), _widget("feature_list"), _widget("table")]
        )
        assert (pie.config.limit, pie.config.use_layer_colors) == (10, True)
        assert (fl.config.sort, fl.config.page_size) == ("asc", 25)
        assert fl.config.subtitle_column is None and fl.config.sort_column is None
        assert (table.config.sort_by, table.config.sort, table.config.limit) == (
            None,
            "desc",
            10,
        )

    @pytest.mark.parametrize(
        ("kind", "config", "message"),
        [
            ("pie_chart", {"column": "c", "limit": 51}, "limit"),
            ("pie_chart", {"column": "c", "stat": "sum"}, "stat_column is required"),
            ("feature_list", {"title_column": "n", "page_size": 9}, "page_size"),
            ("feature_list", {"title_column": "n", "page_size": 101}, "page_size"),
            ("feature_list", {}, "title_column"),
            ("table", {"group_column": "g", "stats": []}, "stats"),
            (
                "table",
                {"group_column": "g", "stats": [{"stat": "count"}] * 6},
                "stats",
            ),
            (
                "table",
                {"group_column": "g", "stats": [{"stat": "sum"}]},
                "column is required unless stat is count",
            ),
            (
                "table",
                {"group_column": "g", "stats": [{"stat": "count", "column": "x"}]},
                "column must be null when stat is count",
            ),
            (
                "table",
                {"group_column": "g", "stats": [{"stat": "count"}], "sort_by": 1},
                "sort_by must be an index into stats",
            ),
            (
                "table",
                {"group_column": "g", "stats": [{"stat": "count"}], "sort_by": -1},
                "sort_by must be an index into stats",
            ),
        ],
    )
    def test_refusals(self, kind: str, config: dict[str, Any], message: str) -> None:
        with pytest.raises(ValidationError, match=message):
            _dashboard([_widget(kind, config=config)])

    def test_a_table_sorts_by_a_stat_index(self) -> None:
        config = {
            "group_column": "g",
            "stats": [{"stat": "count"}, {"stat": "sum", "column": "pop"}],
            "sort_by": 1,
        }
        (widget,) = _dashboard([_widget("table", config=config)])
        assert widget.config.sort_by == 1


class TestBarChartVersions:
    def test_a_plain_category_chart_stays_v1_even_when_sent_as_v2(self) -> None:
        (widget,) = _dashboard([_widget("bar_chart", v=2)])
        assert widget.v == 1

    @pytest.mark.parametrize(
        "config",
        [
            {"column": "c", "use_layer_colors": False},
            {"mode": "date", "column": "c", "date_bucket": "year"},
        ],
    )
    def test_a_chart_with_new_options_is_v2_however_it_is_sent(
        self, config: dict[str, Any]
    ) -> None:
        for sent in (1, 2):
            (widget,) = _dashboard([_widget("bar_chart", v=sent, config=config)])
            assert widget.v == 2
            assert widget.model_dump(mode="json")["v"] == 2

    def test_a_stored_v1_chart_reads_back_unchanged(self) -> None:
        stored = _widget("bar_chart")
        stored["config"] = {
            "column": "c",
            "stat": "count",
            "stat_column": None,
            "limit": 10,
        }
        read = read_stored([stored], "dashboard").widgets[0].model_dump(mode="json")
        assert read["v"] == 1
        assert read["config"] == stored["config"]


def _indicator(v: int = 2, **config: Any) -> dict[str, Any]:
    return _widget("indicator", v=v, config={"stat": "count", **config})


class TestIndicatorReference:
    def test_a_v2_indicator_round_trips_its_reference_options(self) -> None:
        config = {
            "stat": "count",
            "reference": 120.5,
            "reference_label": "Target",
            "higher_is_better": False,
            "comparison": "percent",
        }
        (widget,) = _dashboard(
            [_indicator(**{k: v for k, v in config.items() if k != "stat"})]
        )
        dumped = widget.model_dump(mode="json")
        assert dumped["v"] == 2
        assert dumped["config"] == {**config, "column": None}

    def test_defaults_are_left_out_so_a_plain_indicator_keeps_its_shape(self) -> None:
        (widget,) = _dashboard([_indicator(reference=0)])
        assert widget.model_dump(mode="json")["config"] == {
            "stat": "count",
            "column": None,
            "reference": 0.0,
        }
        (plain,) = _dashboard([_widget("indicator")])
        assert set(plain.model_dump(mode="json")["config"]) == {"stat", "column"}

    @pytest.mark.parametrize(
        "config",
        [
            {"reference": 5},
            {"reference_label": "Target", "reference": 5},
            {"higher_is_better": False},
            {"comparison": "value"},
        ],
    )
    def test_v1_refuses_every_reference_option(self, config: dict[str, Any]) -> None:
        with pytest.raises(ValidationError):
            _dashboard([_indicator(v=1, **config)])

    def test_v1_with_a_reference_is_refused_and_v2_without_one_reads_as_v1(
        self,
    ) -> None:
        (widget,) = _dashboard([_indicator(reference=3)])
        assert widget.v == 2
        (plain,) = _dashboard([_indicator()])
        assert plain.v == 1

    def test_a_label_without_a_reference_is_refused(self) -> None:
        with pytest.raises(ValidationError):
            _dashboard([_indicator(reference_label="Target")])

    @pytest.mark.parametrize(
        "config",
        [
            {"reference": float("nan")},
            {"reference": float("inf")},
            {"reference": "12"},
            {"reference": True},
            {"reference": 1, "reference_label": "x" * 41},
            {"reference": 1, "comparison": "ratio"},
        ],
    )
    def test_malformed_reference_options_are_refused(
        self, config: dict[str, Any]
    ) -> None:
        with pytest.raises(ValidationError):
            _dashboard([_indicator(**config)])

    def test_a_stored_v1_indicator_reads_back_unchanged(self) -> None:
        stored = _widget("indicator")
        read = read_stored([stored], "dashboard").widgets[0].model_dump(mode="json")
        assert read["v"] == 1
        assert read["config"] == {"stat": "sum", "column": "pop"}
