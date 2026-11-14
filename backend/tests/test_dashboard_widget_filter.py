"""A layer-bound dashboard widget's own filter: shape, version, save checks and older clients."""

import json
import random
import uuid
from pathlib import Path

import pytest
from fastapi import HTTPException
from httpx import AsyncClient
from pydantic import TypeAdapter, ValidationError
from sqlalchemy import text

from app.modules.catalog.datasets.domain import aggregate
from app.modules.catalog.maps.dashboard import render_dashboard
from app.modules.catalog.maps.dashboard_filters import composed_filter
from app.modules.catalog.maps.filter_grammar import (
    FilterValidationError,
    bounded_filter,
)
from app.modules.catalog.widgets import filter_shapes
from app.modules.catalog.widgets.schemas import DashboardWidget
from tests.test_dataset_aggregate import _dropped
from tests.test_map_dashboard_config import (
    _ids,
    _map_with_layers,
    _merge,
    _stored,
    _widget,
)

pytestmark = pytest.mark.anyio

KEEP = ["==", ["get", "kind"], "keep"]
UUID = "0b7d2f4e-3c1a-4e8b-9f6d-5a2c7e1b9d34"
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


TEXT = {"kind": "text", "pop": "integer"}


def _reason(filter_, types=TEXT, layer_filter=None):
    return composed_filter(bounded_filter(filter_), layer_filter, types)[0]


class TestSave:
    def test_a_refused_filter_is_refused_with_its_reason(self):
        layer = uuid.uuid4()
        widget = _widget("table", layer, v=2, filter=KEEP)

        merged = _merge({"widgets": [widget]}, None, readable={layer})
        with pytest.raises(HTTPException) as exc:
            _merge(
                {"widgets": [widget]},
                None,
                readable={layer},
                refusals={widget["id"]: "filter_invalid"},
            )

        assert merged["widgets"][0]["filter"] == KEEP
        assert exc.value.status_code == 422
        assert exc.value.detail["widgets"] == [
            {"id": widget["id"], "layer_id": str(layer), "reason": "filter_invalid"}
        ]

    @pytest.mark.parametrize(
        ("types", "filter_"),
        [
            ({"pop": "integer"}, KEEP),
            ({}, KEEP),
            (TEXT, ["all", KEEP, ["has", "secret"]]),
            (TEXT, ["!in", "missing", "x"]),
            (TEXT, ["!has", "missing"]),
        ],
        ids=["other_column", "no_columns", "has", "legacy_not_in", "legacy_not_has"],
    )
    def test_a_filter_on_a_column_the_layer_lacks_is_refused(self, types, filter_):
        assert _reason(filter_, types) == "filter_column"

    def test_a_filter_past_the_aggregates_value_limit_is_refused(self):
        def listing(count):
            values = [f"v{i}" for i in range(count)]
            return ["!", ["in", ["get", "kind"], ["literal", values]]]

        assert _reason(listing(1000)) is None
        assert _reason(listing(1001)) == "filter_too_large"

    def test_a_filter_past_the_aggregates_depth_limit_is_refused(self):
        # 64 levels as CQL2; a timestamp literal is written one level deeper.
        filter_ = [
            "!",
            ["in", ["get", "seen"], ["literal", ["2024-01-01T00:00:00+00:00"]]],
        ]
        for i in range(28):
            filter_ = ["all" if i % 2 else "any", ["has", "kind"], filter_]
        types = {"kind": "text", "seen": "text"}

        assert _reason(filter_, types) is None
        timestamp = {**types, "seen": "timestamp with time zone"}
        assert _reason(filter_, timestamp) == "filter_too_large"

    def test_a_filter_past_the_aggregates_length_limit_is_refused(self):
        from app.standards.ogc.filtering import MAX_FEATURE_FILTER_LENGTH

        def text(chars):
            return ["==", ["get", "kind"], "x" * chars]

        around = {"op": "=", "args": [{"property": "kind"}, ""]}
        fits = MAX_FEATURE_FILTER_LENGTH - len(
            json.dumps(around, separators=(",", ":"))
        )
        assert _reason(text(fits)) is None
        assert _reason(text(fits + 1)) == "filter_too_large"

    def test_the_layers_filter_counts_toward_the_limits(self):
        half = ["in", ["get", "kind"], ["literal", [f"v{i}" for i in range(600)]]]

        assert _reason(half) is None
        assert _reason(half, layer_filter=half) == "filter_too_large"
        # A layer filter the viewer can't send is left out, as the viewer does.
        assert (
            _reason(half, layer_filter=["match", ["get", "kind"], "a", True, False])
            is None
        )

    def test_an_older_client_keeps_a_filtered_widget_in_place(self):
        layer = uuid.uuid4()
        plain = _widget("indicator", layer)
        filtered = _merge(
            {"widgets": [_widget("pie_chart", layer, v=2, filter=KEEP)]},
            None,
            readable={layer},
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
    """Saves run the aggregate's own compiler on the filter a widget sends."""

    async def _map(self, client, headers, session, dataset, layer_filter=None):
        await session.execute(
            text(
                f"ALTER TABLE data.{dataset.table_name} ADD COLUMN active boolean,"
                " ADD COLUMN seen date, ADD COLUMN meta jsonb,"
                " ADD COLUMN stamp timestamp with time zone, ADD COLUMN ref uuid"
            )
        )
        columns = [
            {"name": "kind", "type": "text"},
            {"name": "pop", "type": "integer"},
            {"name": "active", "type": "boolean"},
            {"name": "seen", "type": "date"},
            {"name": "meta", "type": "jsonb"},
            {"name": "stamp", "type": "timestamp with time zone"},
            {"name": "ref", "type": "uuid"},
        ]
        await session.execute(
            text(
                "UPDATE catalog.datasets SET column_info = cast(:c AS jsonb)"
                " WHERE id = :id"
            ),
            {"c": json.dumps(columns), "id": dataset.id},
        )
        await session.commit()
        map_id, (layer_id,) = await _map_with_layers(client, headers, dataset)
        if layer_filter is not None:
            resp = await client.patch(
                f"/maps/{map_id}/layers",
                json={"updated": [{"id": layer_id, "filter": layer_filter}]},
                headers=headers,
            )
            assert resp.status_code == 200, resp.text
        return map_id, layer_id

    async def _save(self, client, headers, map_id, widget):
        return await client.put(
            f"/maps/{map_id}",
            json={
                "dashboard_config": {
                    "version": 1,
                    "readable": ["indicator:1", "indicator:2", "indicator:3"],
                    "widgets": [widget],
                }
            },
            headers=headers,
        )

    @pytest.mark.parametrize(
        ("filter_", "reason"),
        [
            (["==", ["get", "pop"], 1], None),
            (["==", ["get", "missing"], 1], "filter_column"),
            ([">", ["get", "active"], True], "filter_invalid"),
            (["==", ["get", "pop"], "abc"], "filter_invalid"),
            (["==", ["get", "seen"], "2024-02-31"], "filter_invalid"),
            (["==", ["get", "meta"], "x"], "filter_invalid"),
            (["==", ["get", "stamp"], "2024-01-01T12:00:00+00:00"], None),
            (["==", ["get", "stamp"], "2024-01-01T12:00:00Z"], "filter_invalid"),
            (["==", ["get", "ref"], UUID], None),
            (["==", ["get", "ref"], UUID.upper()], "filter_invalid"),
        ],
        ids=[
            "fits",
            "missing_column",
            "boolean_order",
            "type_mismatch",
            "invalid_date",
            "jsonb_column",
            "timestamptz_tile_text",
            "timestamptz_z",
            "uuid_lowercase",
            "uuid_uppercase",
        ],
    )
    async def test_a_save_refuses_what_the_aggregate_would(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
        filter_,
        reason,
    ):
        async with _dropped(test_db_session) as dataset:
            map_id, layer_id = await self._map(
                client, admin_auth_header, test_db_session, dataset
            )
            widget = _widget("indicator", layer_id, v=3, filter=filter_)

            resp = await self._save(client, admin_auth_header, map_id, widget)

            if reason is None:
                assert resp.status_code == 200, resp.text
                stored = await _stored(test_db_session, map_id)
                assert (stored["widgets"][0]["filter"], stored["widgets"][0]["v"]) == (
                    filter_,
                    3,
                )
            else:
                assert resp.status_code == 422, resp.text
                assert resp.json()["detail"]["widgets"][0]["reason"] == reason

    @pytest.mark.parametrize(
        "body",
        [
            '["==", ["get", "pop"], 1%s]' % ("0" * 400),
            '["==", ["get", "pop"], -1%s]' % ("0" * 400),
            '["==", ["get", "pop"], NaN]',
            '["==", ["get", "pop"], Infinity]',
            '["in", ["get", "pop"], ["literal", [1, -Infinity]]]',
            '["==", ["get", "kind"], "%s"]' % ("x" * 70_000),
        ],
        ids=["huge", "negative_huge", "nan", "infinity", "listed_infinity", "long"],
    )
    async def test_an_unreadable_number_or_oversized_text_is_a_422(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session, body
    ):
        async with _dropped(test_db_session) as dataset:
            map_id, layer_id = await self._map(
                client, admin_auth_header, test_db_session, dataset
            )
            widget = json.dumps(_widget("indicator", layer_id, v=3, filter=None))
            raw = widget.replace('"filter": null', f'"filter": {body}')
            payload = '{"dashboard_config": {"version": 1, "widgets": [%s]}}' % raw

            resp = await client.put(
                f"/maps/{map_id}",
                content=payload,
                headers={**admin_auth_header, "Content-Type": "application/json"},
            )

            assert resp.status_code == 422, resp.text

    async def test_the_layers_filter_counts_toward_the_size(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        half = ["in", ["get", "kind"], ["literal", [f"v{i}" for i in range(600)]]]
        async with _dropped(test_db_session) as dataset:
            map_id, layer_id = await self._map(
                client, admin_auth_header, test_db_session, dataset, layer_filter=half
            )
            widget = _widget("indicator", layer_id, v=3, filter=half)

            resp = await self._save(client, admin_auth_header, map_id, widget)

            assert resp.status_code == 422, resp.text
            assert resp.json()["detail"]["widgets"][0]["reason"] == "filter_too_large"


_SHAPE_FILE = json.loads(
    (Path(__file__).parent / "fixtures" / "widget_filter_shapes.json").read_text()
)
SHAPES = _SHAPE_FILE["cases"]


@pytest.mark.parametrize("case", SHAPES, ids=[case["name"] for case in SHAPES])
def test_the_shared_shape_cases(case):
    types = _SHAPE_FILE["types"] if case.get("typed") else None
    if case["columns"] is None:
        with pytest.raises(FilterValidationError):
            filter_shapes.widget_filter_cql2(bounded_filter(case["filter"]), types)
        if types is None:
            with pytest.raises(ValidationError):
                _adapter.validate_python(
                    _widget("table", uuid.uuid4(), v=2, filter=case["filter"])
                )
        return
    stored = _adapter.validate_python(
        _widget("table", uuid.uuid4(), v=2, filter=case["filter"])
    )
    read = filter_shapes.widget_filter_cql2(stored.filter, types)
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
    {}, {"a": 1}, [], 10**400, -(10**400), 2**53, -(2**53), 1e300,
    float("nan"), float("inf"), float("-inf"), "x" * 20_000,
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
