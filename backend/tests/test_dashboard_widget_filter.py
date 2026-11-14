"""A layer-bound dashboard widget's own filter: shape, version, save checks and older clients."""

import json
import random
import uuid
from pathlib import Path

import pytest
from fastapi import HTTPException
from httpx import AsyncClient
from pydantic import TypeAdapter, ValidationError

from app.modules.catalog.datasets.domain import aggregate
from app.modules.catalog.maps.dashboard import render_dashboard
from app.modules.catalog.maps.filter_grammar import (
    FilterValidationError,
    bounded_filter,
)
from app.modules.catalog.widgets import filter_shapes
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

    def test_a_legacy_spelling_on_a_column_the_layer_lacks_is_refused(self):
        layer = uuid.uuid4()
        for filter_ in (["!in", "missing", "x"], ["!has", "missing"]):
            widget = _widget("table", layer, v=2, filter=filter_)
            with pytest.raises(HTTPException) as exc:
                _merge(
                    {"widgets": [widget]},
                    None,
                    readable={layer},
                    columns={layer: ["kind"]},
                )
            assert exc.value.detail["widgets"][0]["reason"] == "filter_column"

    def test_a_filter_past_the_aggregates_bind_limit_is_refused(self):
        layer = uuid.uuid4()

        def listing(count):
            values = [f"v{i}" for i in range(count)]
            members = ["!", ["in", ["get", "kind"], ["literal", values]]]
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

    def test_a_filter_past_the_aggregates_depth_limit_is_refused(self):
        layer = uuid.uuid4()
        # 64 levels as CQL2; a timestamp literal is written one level deeper.
        filter_ = ["!", ["in", ["get", "seen"], ["literal", ["2024-01-01"]]]]
        for i in range(28):
            filter_ = ["all" if i % 2 else "any", ["has", "kind"], filter_]
        widget = _widget("table", layer, v=2, filter=filter_)
        columns = {"kind": "text", "seen": "text"}

        fits = _merge(
            {"widgets": [widget]}, None, readable={layer}, columns={layer: columns}
        )
        with pytest.raises(HTTPException) as exc:
            _merge(
                {"widgets": [widget]},
                None,
                readable={layer},
                columns={layer: {**columns, "seen": "timestamp with time zone"}},
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


SHAPES = json.loads(
    (Path(__file__).parent / "fixtures" / "widget_filter_shapes.json").read_text()
)


@pytest.mark.parametrize("case", SHAPES, ids=[case["name"] for case in SHAPES])
def test_the_shared_shape_cases(case):
    widget = _widget("table", uuid.uuid4(), v=2, filter=case["filter"])
    if case["columns"] is None:
        with pytest.raises(ValidationError):
            _adapter.validate_python(widget)
        return
    stored = _adapter.validate_python(widget)
    read = filter_shapes.widget_filter_cql2(stored.filter)
    assert sorted(read.columns) == case["columns"]
    assert (read.cql2, read.values, read.depth) == (
        case["cql2"],
        case["values"],
        case["depth"],
    )


def test_the_depth_limit_is_the_aggregates():
    assert filter_shapes.MAX_CQL2_DEPTH == aggregate._MAX_FILTER_DEPTH


_FUZZ_TOKENS = [
    "all", "any", "!", "in", "!in", "has", "!has", "none", "get", "literal",
    "==", "!=", "<", ">=", "to-number", "typeof", "match", "case", "properties",
    "$type", "$id", "kind", "null", "number", None, True, 0, -1e12, 1e12, 3.5, "",
    {}, {"a": 1}, [],
]  # fmt: skip


def _fuzz_node(rng: random.Random, depth: int):
    if depth > 6 or rng.random() < 0.3:
        return rng.choice(_FUZZ_TOKENS)
    return [_fuzz_node(rng, depth + 1) for _ in range(rng.randint(0, 4))]


def test_malformed_filters_are_only_ever_refused_as_filter_errors():
    rng = random.Random(3688)
    for _ in range(5000):
        tail = _fuzz_node(rng, 1)
        candidate = [
            rng.choice(_FUZZ_TOKENS),
            *(tail if isinstance(tail, list) else [tail]),
        ]
        if rng.random() < 0.5:
            candidate = _fuzz_node(rng, 0)
        try:
            filter_shapes.widget_filter_cql2(candidate)
        except FilterValidationError:
            pass
        try:
            normalized = bounded_filter(candidate)
        except FilterValidationError:
            continue
        try:
            filter_shapes.widget_filter_cql2(normalized, {"kind": "date"})
        except FilterValidationError:
            pass
        widget = _widget("table", uuid.uuid4(), v=2, filter=candidate)
        try:
            _adapter.validate_python(widget)
        except ValidationError:
            pass
