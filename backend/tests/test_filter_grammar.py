"""Unit tests for the shared MapLibre filter validator/normalizer.

builder-audit #338 P1-04 (filter grammar), STYLE-01/SPEC-08 (builder alias single
source of truth), and P2-05 (LabelConfig schema). These exercise the schema
contract directly without a DB so the orchestrator's serial suite stays cheap.
"""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from app.modules.catalog.maps.filter_grammar import (
    FilterValidationError,
    validate_filter,
)
from app.modules.catalog.maps.schemas import (
    BUILDER_SNAKE_TO_CAMEL_KEYS,
    LabelConfig,
    MapLayerInput,
    MapLayerPatch,
    _BUILDER_CAMEL_TO_SNAKE_KEYS,
)


# --------------------------------------------------------------------------- #
# P1-04: filter grammar — valid editable subset                               #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "expr",
    [
        ["==", ["get", "status"], "active"],
        ["!=", ["get", "status"], "active"],
        [">", ["get", "population"], 1000],
        ["<=", ["get", "population"], 1000],
        # to-number-wrapped numeric comparison (frontend numeric-safe accessor)
        [">", ["to-number", ["get", "population"], 0], 1000],
        # has / not-exists
        ["has", "name"],
        ["!", ["has", "name"]],
        # in_list / contains / not_in_list
        ["in", ["get", "state"], ["literal", ["CA", "NY"]]],
        ["in", "main", ["get", "name"]],
        ["!", ["in", ["get", "state"], ["literal", ["CA"]]]],
        # is_null full pattern
        ["any", ["!", ["has", "pop"]], ["==", ["get", "pop"], None]],
        # compound all/any
        ["all", [">", ["get", "pop"], 100], ["==", ["get", "state"], "CA"]],
        ["any", ["==", ["get", "a"], 1], ["==", ["get", "b"], 2]],
    ],
)
def test_validate_filter_accepts_editable_subset(expr):
    assert validate_filter(expr) == expr


def test_validate_filter_none_passes_through():
    assert validate_filter(None) is None


def test_validate_filter_empty_array_clears():
    # EDIT-03: [] is not a valid MapLibre filter — treat as clear (None).
    assert validate_filter([]) is None


# --------------------------------------------------------------------------- #
# P1-04: legacy-form normalization                                            #
# --------------------------------------------------------------------------- #


def test_validate_filter_normalizes_legacy_bare_field_comparison():
    assert validate_filter([">", "population", 1000]) == [
        ">",
        ["get", "population"],
        1000,
    ]


def test_validate_filter_normalizes_legacy_form_inside_compound():
    assert validate_filter(["all", [">", "population", 5]]) == [
        "all",
        [">", ["get", "population"], 5],
    ]


def test_validate_filter_preserves_legacy_pseudo_field():
    # $type / $id are renderer pseudo-fields and must NOT become ["get", ...].
    expr = ["==", "$type", "Point"]
    assert validate_filter(expr) == expr


# --------------------------------------------------------------------------- #
# P1-04: rejection of malformed recognized forms                              #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "expr",
    [
        ["=="],  # comparison missing operands
        ["==", ["get", "x"]],  # comparison arity 2
        ["==", ["get", "x"], 1, 2],  # comparison arity 4
        ["!"],  # ! missing operand
        ["!", ["has", "a"], ["has", "b"]],  # ! arity 3
        ["has"],  # has missing field
        ["has", 5],  # has non-string field
        ["in", "state", "CA", "NY"],  # legacy bare-field in
    ],
)
def test_validate_filter_rejects_invalid_arity_and_legacy_in(expr):
    with pytest.raises(FilterValidationError):
        validate_filter(expr)


@pytest.mark.parametrize(
    "value",
    [
        "not a list",
        42,
        [123, ["get", "x"], 1],  # non-string operator
        ["all", ["=="]],  # nested invalid arity bubbles up
    ],
)
def test_validate_filter_rejects_structurally_invalid(value):
    with pytest.raises(FilterValidationError):
        validate_filter(value)


# --------------------------------------------------------------------------- #
# P1-04: opaque unsupported filters are preserved verbatim                    #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "expr",
    [
        ["match", ["get", "x"], "a", True, False],
        ["step", ["get", "x"], 0, 10, 1],
        ["case", [">", ["get", "x"], 1], True, False],
        ["==", ["geometry-type"], "Point"],  # expression operand we don't model
    ],
)
def test_validate_filter_preserves_opaque(expr):
    assert validate_filter(expr) == expr


# --------------------------------------------------------------------------- #
# P1-04: wired into MapLayerInput / MapLayerPatch                             #
# --------------------------------------------------------------------------- #


def _layer_input(**kw):
    return MapLayerInput(dataset_id=uuid.uuid4(), **kw)


def test_map_layer_input_normalizes_filter():
    layer = _layer_input(filter=[">", "pop", 5])
    assert layer.filter == [">", ["get", "pop"], 5]


def test_map_layer_input_empty_filter_clears():
    assert _layer_input(filter=[]).filter is None


def test_map_layer_input_rejects_bad_filter_arity():
    with pytest.raises(ValidationError):
        _layer_input(filter=["==", ["get", "x"]])


def test_map_layer_patch_validates_filter():
    with pytest.raises(ValidationError):
        MapLayerPatch(id=uuid.uuid4(), filter=["!"])


# --------------------------------------------------------------------------- #
# STYLE-01 / SPEC-08: builder alias single source of truth                    #
# --------------------------------------------------------------------------- #


def test_builder_snake_to_camel_is_exact_inverse():
    assert BUILDER_SNAKE_TO_CAMEL_KEYS == {
        snake: camel for camel, snake in _BUILDER_CAMEL_TO_SNAKE_KEYS.items()
    }
    # bijective round-trip
    for camel, snake in _BUILDER_CAMEL_TO_SNAKE_KEYS.items():
        assert BUILDER_SNAKE_TO_CAMEL_KEYS[snake] == camel


def test_builder_inverse_includes_folder_group_keys():
    # The drift the audit flagged: the old hand-written export table lacked
    # folder_group_*; the derived inverse must carry them so export camelCases.
    for snake, camel in (
        ("folder_group_id", "folderGroupId"),
        ("folder_group_name", "folderGroupName"),
        ("folder_group_expanded", "folderGroupExpanded"),
    ):
        assert BUILDER_SNAKE_TO_CAMEL_KEYS[snake] == camel


# --------------------------------------------------------------------------- #
# P2-05: LabelConfig schema                                                   #
# --------------------------------------------------------------------------- #


def test_label_config_accepts_known_fields_and_drops_none():
    lc = LabelConfig.model_validate(
        {"column": "name", "fontSize": 14, "placement": "line"}
    )
    dumped = lc.model_dump()
    assert dumped == {"column": "name", "fontSize": 14, "placement": "line"}
    # None-valued optionals are dropped from the stored shape.
    assert "textColor" not in dumped


def test_label_config_preserves_unknown_forward_compat_keys():
    lc = LabelConfig.model_validate({"column": "name", "futureKnob": 3})
    assert lc.model_dump()["futureKnob"] == 3


def test_label_config_allows_zoom_expression_for_font_size():
    expr = ["interpolate", ["linear"], ["zoom"], 8, 10, 16, 20]
    lc = LabelConfig.model_validate({"column": "name", "fontSize": expr})
    assert lc.model_dump()["fontSize"] == expr


@pytest.mark.parametrize(
    "payload",
    [
        {"column": "name", "haloWidth": 99},  # > 20
        {"column": "name", "placement": "diagonal"},  # bad enum
        {"column": "name", "textAnchor": "sideways"},  # bad enum
        {"column": "name", "minZoom": 30},  # > 24
        {"column": "name", "textOpacity": 5},  # > 1
    ],
)
def test_label_config_rejects_out_of_bounds(payload):
    with pytest.raises(ValidationError):
        LabelConfig.model_validate(payload)


def test_map_layer_input_label_config_validated_and_returns_dict():
    layer = _layer_input(label_config={"column": "name", "fontSize": 14})
    assert isinstance(layer.label_config, dict)
    assert layer.label_config == {"column": "name", "fontSize": 14}


def test_map_layer_input_rejects_bad_label_config():
    with pytest.raises(ValidationError):
        _layer_input(label_config={"column": "name", "placement": "nope"})
