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
    "histogram": {"layer_id": LAYER, "scope": "view", "config": {"column": "pop"}},
    "category_selector": {"layer_id": LAYER, "config": {"column": "landuse"}},
    "markdown": {"config": {"text": "# Chapter one"}},
    "image": {"asset_id": str(uuid.uuid4()), "config": {"alt": "A river"}},
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
            pytest.param(_widget("histogram", v=2), id="newer v"),
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
            _widget("histogram", v=2, config={"column": "pop", "bins": "auto"}),
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
        unknown = _widget("histogram", v=2)
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
