"""builder-audit #338 P1-13: AI set_filter actions are validated against the full
shared MapLibre filter grammar (filter_grammar.validate_filter), not just
``["get", ...]`` column refs.

These tests exercise ``_validate_actions`` directly. With no ``add_layer``
actions present the function makes zero DB calls (the batched RBAC lookup
returns early), so these are pure-function unit tests — session/user/port are
unused and passed as ``None``.

Required cases (per the audit acceptance): valid expression filters, invalid
legacy examples, nonexistent columns, empty clear, and compound filters.
"""

import pytest

from app.processing.ai.chat_validation import _validate_actions
from app.processing.ai.schemas import ChatAction, ChatMapLayer

_LAYER_ID = "11111111-1111-1111-1111-111111111111"


def _layer() -> ChatMapLayer:
    """A layer whose column_info advertises population/state/status columns."""
    return ChatMapLayer(
        id=_LAYER_ID,
        name="Counties",
        dataset_id="22222222-2222-2222-2222-222222222222",
        dataset_table_name="data.counties",
        geometry_type="Polygon",
        column_info=[
            {"name": "population", "type": "integer"},
            {"name": "state", "type": "text"},
            {"name": "status", "type": "text"},
        ],
    )


def _set_filter(expression) -> ChatAction:
    return ChatAction(type="set_filter", layer_id=_LAYER_ID, expression=expression)


async def _run(action: ChatAction):
    """Validate a single set_filter action; return (validated, dropped)."""
    return await _validate_actions(
        [action], [_layer()], session=None, user=None, port=None
    )


@pytest.mark.anyio
async def test_valid_expression_filter_accepted():
    validated, dropped = await _run(_set_filter(["==", ["get", "status"], "active"]))
    assert dropped == []
    assert len(validated) == 1
    assert validated[0].expression == ["==", ["get", "status"], "active"]


@pytest.mark.anyio
async def test_compound_expression_filter_accepted():
    expr = [
        "all",
        [">", ["get", "population"], 50000],
        ["==", ["get", "state"], "CA"],
    ]
    validated, dropped = await _run(_set_filter(expr))
    assert dropped == []
    assert len(validated) == 1
    assert validated[0].expression == expr


@pytest.mark.anyio
async def test_legacy_bare_field_comparison_normalized_to_get_form():
    """A legacy ``[op, "field", value]`` comparison on a KNOWN column is
    normalized to expression form rather than rejected (filter_grammar
    contract), so saved state stays runtime-valid."""
    validated, dropped = await _run(_set_filter(["all", [">", "population", 1000000]]))
    assert dropped == []
    assert len(validated) == 1
    # Normalized: bare "population" -> ["get", "population"].
    assert validated[0].expression == ["all", [">", ["get", "population"], 1000000]]


@pytest.mark.anyio
async def test_invalid_legacy_in_form_rejected():
    """The deprecated bare-field ``in`` form is a recognized-but-invalid grammar
    shape — it must be dropped before reaching the client."""
    validated, dropped = await _run(_set_filter(["in", "state", "CA", "NY"]))
    assert validated == []
    assert len(dropped) == 1
    assert "invalid filter expression" in dropped[0]


@pytest.mark.anyio
async def test_nonexistent_column_rejected():
    validated, dropped = await _run(_set_filter(["==", ["get", "nonexistent_col"], 1]))
    assert validated == []
    assert len(dropped) == 1
    assert "invalid column refs" in dropped[0]


@pytest.mark.anyio
async def test_legacy_form_with_nonexistent_column_rejected():
    """A legacy bare-field comparison normalizes, then fails column validation
    because the referenced column does not exist — covers the legacy+invalid
    case the old ``["get"]``-only extractor missed."""
    validated, dropped = await _run(_set_filter([">", "ghost_column", 5]))
    assert validated == []
    assert len(dropped) == 1
    assert "invalid column refs" in dropped[0]


@pytest.mark.anyio
async def test_empty_array_clears_filter():
    """An empty array normalizes to a clear (expression -> None) and is kept."""
    validated, dropped = await _run(_set_filter([]))
    assert dropped == []
    assert len(validated) == 1
    assert validated[0].expression is None


@pytest.mark.anyio
async def test_null_expression_clear_accepted():
    """``expression=None`` is an explicit clear and passes through untouched."""
    validated, dropped = await _run(_set_filter(None))
    assert dropped == []
    assert len(validated) == 1
    assert validated[0].expression is None


@pytest.mark.anyio
async def test_malformed_arity_rejected():
    """A recognized comparison with wrong arity is dropped (grammar error)."""
    validated, dropped = await _run(_set_filter(["==", ["get", "status"]]))
    assert validated == []
    assert len(dropped) == 1
    assert "invalid filter expression" in dropped[0]
