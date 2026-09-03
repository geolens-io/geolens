"""fix(#1778): the layer filter column needs the bounds its siblings carry.

Codebase audit 2026-08-30 (8dc529f17): ``MapLayer.filter`` was the one open
JSONB layer column with no size cap. The cap's own comment enumerates the open
containers by name and every one it names is a dict, so the single open column
that is a list was missed: a 20000-clause filter was accepted and stored 2.5 MB
of JSONB per layer, which every later style export and every builder load
re-serialized.

``filter_grammar._normalize_node`` also recursed with no depth bound, so a
deeply nested filter raised RecursionError. RecursionError is not a ValueError,
so Pydantic does not convert it to a 422 and the layer routes answered 500.
Both doors reach it: POST /maps/import passes ``style_layer["filter"]`` through
untouched, and PUT/PATCH /maps/{id} takes it straight from the client.
"""

import uuid

import pytest
from pydantic import ValidationError

from app.modules.catalog.maps.filter_grammar import (
    FilterValidationError,
    validate_filter,
)
from app.modules.catalog.maps.schemas import MapLayerInput, MapLayerPatch

# The documented bound, spelled out rather than imported so this module still
# collects against a build that has no bound at all and the assertions, not an
# ImportError, are what report.
MAX_FILTER_DEPTH = 32


def _nested(levels: int) -> list:
    """A filter carrying exactly ``levels`` nested arrays."""
    node: list = ["has", "field"]
    for _ in range(levels - 1):
        node = ["all", node]
    return node


def _wide(clauses: int) -> list:
    return ["all"] + [["==", ["get", "f"], "x" * 100] for _ in range(clauses)]


class TestNestingBound:
    def test_the_spelled_out_bound_matches_the_module(self) -> None:
        from app.modules.catalog.maps.filter_grammar import _MAX_FILTER_DEPTH

        assert _MAX_FILTER_DEPTH == MAX_FILTER_DEPTH

    def test_a_filter_at_the_bound_is_accepted(self) -> None:
        assert validate_filter(_nested(MAX_FILTER_DEPTH)) is not None

    def test_one_level_past_the_bound_is_refused(self) -> None:
        with pytest.raises(FilterValidationError):
            validate_filter(_nested(MAX_FILTER_DEPTH + 1))

    def test_a_filter_deep_enough_to_blow_the_stack_is_refused(self) -> None:
        """2000 levels raised RecursionError out of model construction before."""
        with pytest.raises(FilterValidationError):
            validate_filter(_nested(2000))

    def test_the_bound_covers_operators_the_grammar_walks_past(self) -> None:
        """``case`` is opaque to _normalize_node, but json.dumps still descends."""
        node: list = ["case", True, 1, 0]
        for _ in range(2000):
            node = ["case", node, 1, 0]

        with pytest.raises(FilterValidationError):
            validate_filter(node)

    def test_the_bound_covers_dicts_nested_below_the_operator(self) -> None:
        value: object = {"deep": True}
        for _ in range(2000):
            value = {"deep": value}

        with pytest.raises(FilterValidationError):
            validate_filter(["==", ["get", "f"], value])

    def test_a_deep_filter_becomes_a_422_not_a_500(self) -> None:
        with pytest.raises(ValidationError):
            MapLayerInput(dataset_id=uuid.uuid4(), filter=_nested(2000))


class TestSizeBound:
    def test_a_multi_megabyte_filter_is_refused_on_input(self) -> None:
        with pytest.raises(ValidationError) as exc:
            MapLayerInput(dataset_id=uuid.uuid4(), filter=_wide(20000))
        assert "Filter expression too large" in str(exc.value)

    def test_a_multi_megabyte_filter_is_refused_on_patch(self) -> None:
        with pytest.raises(ValidationError):
            MapLayerPatch(id=uuid.uuid4(), filter=_wide(20000))

    def test_an_ordinary_filter_still_round_trips(self) -> None:
        layer = MapLayerInput(
            dataset_id=uuid.uuid4(), filter=["all", ["==", "status", "open"]]
        )

        assert layer.filter == ["all", ["==", ["get", "status"], "open"]]

    def test_the_style_dict_message_is_unchanged(self) -> None:
        """The shared byte check keeps the wording paint/layout callers saw."""
        with pytest.raises(ValidationError) as exc:
            MapLayerInput(dataset_id=uuid.uuid4(), paint={"k": "x" * 100_000})
        assert "Style configuration too large" in str(exc.value)
