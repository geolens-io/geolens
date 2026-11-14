"""A layer-bound dashboard widget's own filter: shape, version, save checks and older clients."""

import uuid

import pytest
from fastapi import HTTPException
from httpx import AsyncClient
from pydantic import TypeAdapter, ValidationError

from app.modules.catalog.maps.dashboard import render_dashboard
from app.modules.catalog.widgets.schemas import DashboardWidget
from tests.factories import create_dataset, get_user_id
from tests.test_map_dashboard_config import (
    _ids,
    _map_with_layers,
    _merge,
    _stored,
    _widget,
)

pytestmark = pytest.mark.anyio

KEEP = ["==", ["get", "kind"], "keep"]
# Each layer-bound type: the version a filter needs, and the one a plain widget keeps.
FILTER_VERSIONS = {
    "indicator": (3, 1),
    "bar_chart": (3, 1),
    "pie_chart": (2, 1),
    "feature_list": (2, 1),
    "table": (2, 1),
    "histogram": (2, 1),
    "category_selector": (2, 1),
}
_adapter = TypeAdapter(DashboardWidget)


@pytest.mark.parametrize("kind", sorted(FILTER_VERSIONS))
def test_a_filter_stores_at_the_filter_version_and_a_plain_widget_is_unchanged(kind):
    filtered_v, plain_v = FILTER_VERSIONS[kind]
    layer = uuid.uuid4()
    plain = _widget(kind, layer)
    filtered = _widget(kind, layer, v=filtered_v, filter=KEEP)

    stored_plain = _adapter.validate_python(plain).model_dump(mode="json")
    stored_filtered = _adapter.validate_python(filtered).model_dump(mode="json")

    assert stored_plain["v"] == plain_v
    assert "filter" not in stored_plain
    assert (stored_filtered["v"], stored_filtered["filter"]) == (filtered_v, KEEP)
    rendered = render_dashboard({"version": 1, "widgets": [stored_filtered]}, [layer])
    assert rendered.model_dump(mode="json")["widgets"][0]["filter"] == KEEP


@pytest.mark.parametrize("kind", sorted(FILTER_VERSIONS))
def test_a_filter_at_an_older_version_is_refused(kind):
    filtered_v, _ = FILTER_VERSIONS[kind]
    with pytest.raises(ValidationError):
        _adapter.validate_python(
            _widget(kind, uuid.uuid4(), v=filtered_v - 1, filter=KEEP)
        )


def test_an_indicator_keeps_its_reference_options_beside_a_filter():
    widget = _widget(
        "indicator",
        uuid.uuid4(),
        v=3,
        filter=KEEP,
        config={"stat": "count", "reference": 4.0},
    )
    stored = _adapter.validate_python(widget).model_dump(mode="json")
    assert (stored["v"], stored["config"]["reference"]) == (3, 4.0)


@pytest.mark.parametrize(
    "bad",
    [
        ["==", ["get", "kind"]],
        "kind == keep",
        ["in", "kind", "keep"],
        ["==", ["get", "kind"], "x" * (64 * 1024)],
    ],
    ids=["arity", "not_a_list", "legacy_in", "too_large"],
)
def test_the_layer_filter_grammar_and_size_cap_apply(bad):
    with pytest.raises(ValidationError):
        _adapter.validate_python(_widget("pie_chart", uuid.uuid4(), v=2, filter=bad))


def test_an_empty_filter_clears_and_a_legacy_comparison_is_normalized():
    layer = uuid.uuid4()
    cleared = _adapter.validate_python(_widget("histogram", layer, v=2, filter=[]))
    legacy = _adapter.validate_python(
        _widget("histogram", layer, v=2, filter=["==", "kind", "keep"])
    )
    assert cleared.model_dump(mode="json")["v"] == 1
    assert "filter" not in cleared.model_dump(mode="json")
    assert legacy.filter == KEEP


class TestSave:
    def test_a_filter_on_the_layers_columns_is_stored(self):
        layer = uuid.uuid4()
        widget = _widget("pie_chart", layer, v=2, filter=KEEP)

        merged = _merge(
            {"widgets": [widget]},
            None,
            readable={layer},
            columns={layer: ["kind", "pop"]},
        )

        assert merged["widgets"][0]["filter"] == KEEP

    @pytest.mark.parametrize(
        ("columns", "filter_"),
        [
            (["pop"], KEEP),
            ([], KEEP),
            (["kind"], ["all", KEEP, ["has", "secret"]]),
        ],
        ids=["other_column", "no_columns", "has_operator"],
    )
    def test_a_filter_on_a_column_the_layer_lacks_is_refused(self, columns, filter_):
        layer = uuid.uuid4()
        widget = _widget("table", layer, v=2, filter=filter_)

        with pytest.raises(HTTPException) as exc:
            _merge(
                {"widgets": [widget]},
                None,
                readable={layer},
                columns={layer: columns},
            )

        assert exc.value.status_code == 422
        assert exc.value.detail["widgets"] == [
            {"id": widget["id"], "layer_id": str(layer), "reason": "filter_column"}
        ]

    @pytest.mark.parametrize(
        "filter_",
        [
            ["in", ["get", "kind"], ["literal", ["get", "park"]]],
            ["!", ["in", ["get", "kind"], ["literal", ["has", "park"]]]],
            [
                "all",
                ["in", ["get", "kind"], ["literal", ["has", "x", "y"]]],
                ["any", ["!", ["in", ["get", "kind"], ["literal", ["get", "z"]]]]],
            ],
        ],
        ids=["in_get", "not_in_has", "nested"],
    )
    def test_values_in_a_literal_list_are_not_read_as_columns(self, filter_):
        layer = uuid.uuid4()
        widget = _widget("table", layer, v=2, filter=filter_)

        merged = _merge(
            {"widgets": [widget]}, None, readable={layer}, columns={layer: ["kind"]}
        )

        assert merged["widgets"][0]["filter"] == filter_

    @pytest.mark.parametrize(
        "filter_",
        [
            ["!in", "missing", "x"],
            ["!has", "missing"],
            ["none", ["!has", "missing"]],
            ["none", ["==", "missing", 1]],
            ["all", ["==", ["get", "kind"], "a"], ["!has", "missing"]],
            ["in", "x", ["get", "missing"]],
        ],
        ids=["not_in", "not_has", "none", "none_compare", "mixed", "contains"],
    )
    def test_a_legacy_spelling_on_a_missing_column_is_refused(self, filter_):
        layer = uuid.uuid4()
        widget = _widget("table", layer, v=2, filter=filter_)

        with pytest.raises(HTTPException) as exc:
            _merge(
                {"widgets": [widget]}, None, readable={layer}, columns={layer: ["kind"]}
            )

        assert exc.value.detail["widgets"][0]["reason"] == "filter_column"

    @pytest.mark.parametrize(
        "filter_",
        [
            ["==", ["get", ["concat", "ki", "nd"]], "a"],
            ["has", "kind", ["properties"]],
            ["==", ["at", 0, ["properties"]], "a"],
            ["!has", ["get", "kind"]],
        ],
        ids=["computed_get", "has_on_object", "properties", "computed_not_has"],
    )
    def test_a_filter_whose_columns_are_computed_is_refused(self, filter_):
        with pytest.raises(ValidationError):
            _adapter.validate_python(
                _widget("table", uuid.uuid4(), v=2, filter=filter_)
            )

    def test_a_filter_listing_more_values_than_the_aggregate_binds_is_refused(self):
        layer = uuid.uuid4()

        def listing(count):
            values = [f"v{i}" for i in range(count)]
            members = ["in", ["get", "kind"], ["literal", values]]
            return _widget("table", layer, v=2, filter=members)

        fits = _merge(
            {"widgets": [listing(1000)]},
            None,
            readable={layer},
            columns={layer: ["kind"]},
        )
        with pytest.raises(HTTPException) as exc:
            _merge(
                {"widgets": [listing(1001)]},
                None,
                readable={layer},
                columns={layer: ["kind"]},
            )

        assert len(fits["widgets"]) == 1
        assert exc.value.detail["widgets"][0]["reason"] == "filter_too_large"

    def test_an_older_client_keeps_a_filtered_widget_in_place(self):
        layer = uuid.uuid4()
        plain = _widget("indicator", layer)
        filtered = _merge(
            {"widgets": [_widget("pie_chart", layer, v=2, filter=KEEP)]},
            None,
            readable={layer},
            columns={layer: ["kind"]},
        )["widgets"][0]
        stored = {"version": 1, "widgets": [plain, filtered]}
        reads = [
            "indicator:1",
            "indicator:2",
            "pie_chart:1",
            "bar_chart:1",
            "bar_chart:2",
        ]

        for sent in ({"widgets": [plain]}, {"readable": reads, "widgets": [plain]}):
            merged = _merge(sent, stored, readable={layer})
            assert _ids(merged["widgets"]) == _ids([plain, filtered])
            assert merged["widgets"][1] == filtered

        cleared = _merge(
            {"readable": [*reads, "pie_chart:2"], "widgets": [plain]},
            stored,
            readable={layer},
        )
        assert _ids(cleared["widgets"]) == [plain["id"]]


class TestSaveThroughTheApi:
    async def test_a_filter_saves_on_the_datasets_columns_and_is_refused_otherwise(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await create_dataset(
            test_db_session,
            created_by=admin_id,
            column_info=[{"name": "kind", "type": "text"}],
        )
        map_id, (layer_id,) = await _map_with_layers(client, admin_auth_header, dataset)
        widget = _widget("indicator", layer_id, v=3, filter=KEEP)

        saved = await client.put(
            f"/maps/{map_id}",
            json={"dashboard_config": {"version": 1, "widgets": [widget]}},
            headers=admin_auth_header,
        )
        refused = await client.put(
            f"/maps/{map_id}",
            json={
                "dashboard_config": {
                    "version": 1,
                    "readable": ["indicator:1", "indicator:2", "indicator:3"],
                    "widgets": [{**widget, "filter": ["==", ["get", "pop"], 1]}],
                }
            },
            headers=admin_auth_header,
        )

        assert saved.status_code == 200, saved.text
        assert saved.json()["dashboard_config"]["widgets"][0]["filter"] == KEEP
        assert refused.status_code == 422, refused.text
        assert refused.json()["detail"]["widgets"][0]["reason"] == "filter_column"
        stored = await _stored(test_db_session, map_id)
        assert stored["widgets"][0]["filter"] == KEEP
        assert stored["widgets"][0]["v"] == 3


@pytest.mark.parametrize(
    ("expression", "kept"),
    [
        (["in", ["get", "kind"], ["literal", ["get", "park"]]], True),
        (["!has", "missing"], False),
        (["==", ["get", ["concat", "ki", "nd"]], "a"], False),
    ],
    ids=["literal_values", "legacy_missing", "computed"],
)
def test_ai_filters_use_the_same_column_reading(expression, kept):
    from app.processing.ai.chat_validation import _validate_filter_columns
    from app.processing.ai.schemas import ChatMapLayer

    layer = ChatMapLayer(
        id="l1",
        name="Trees",
        dataset_id="d1",
        dataset_table_name="trees",
        column_info=[{"name": "kind", "type": "text"}],
    )

    assert (_validate_filter_columns(expression, layer) is not None) is kept
