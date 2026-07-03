"""Phase 1135 AI-08 carry-forward fix: _collect_chat_action regression pins.

Ensures show_query_result actions emit columns+rows for non-spatial query_data
results so the frontend inline data-analysis card can render. Previously only
spatial results (with geojson) generated an action; non-spatial query results
silently dropped on the floor.

Discovered during Phase 1135 Plan 06 live MCP smoke (SF-MCP-01).
Fix: chat_actions.py _collect_chat_action — emit action for all successful
query_data results, with optional geojson+bbox on spatial path.
"""

from app.processing.ai.chat_actions import _collect_chat_action
from app.processing.ai.schemas import ChatAction


def test_non_spatial_query_emits_show_query_result_with_rows() -> None:
    """AI-08: query_data returning columns+rows (no geometry) MUST emit
    show_query_result so the frontend inline data card can render."""
    result = {
        "columns": ["county_name", "feature_count"],
        "rows": [["Essex", 12], ["Franklin", 8], ["Hamilton", 5]],
        "row_count": 3,
        "truncated": False,
    }
    action = _collect_chat_action(
        "query_data", {"question": "feature count by county"}, result
    )
    assert action is not None, "non-spatial query_data must emit an action"
    assert action["type"] == "show_query_result"
    assert action["columns"] == ["county_name", "feature_count"]
    assert action["rows"] == [["Essex", 12], ["Franklin", 8], ["Hamilton", 5]]
    assert action["row_count"] == 3
    assert action["truncated"] is False
    # No geojson key on non-spatial result
    assert "geojson" not in action
    assert "bbox" not in action


def test_spatial_query_emits_show_query_result_with_geojson_and_rows() -> None:
    """AI-08: spatial query_data results emit both rows AND geojson+bbox so
    the frontend can flyover-zoom the map AND render the inline table."""
    result = {
        "columns": ["geom", "name"],
        "rows": [[{"type": "Point", "coordinates": [-73.9, 40.7]}, "NYC"]],
        "row_count": 1,
        "truncated": False,
        "geojson": {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [-73.9, 40.7]},
                    "properties": {"name": "NYC"},
                }
            ],
        },
        "bbox": [-73.9, 40.7, -73.9, 40.7],
    }
    action = _collect_chat_action("query_data", {"question": "find NYC"}, result)
    assert action is not None
    assert action["type"] == "show_query_result"
    assert "geojson" in action
    assert "bbox" in action
    assert action["columns"] == ["geom", "name"]
    assert action["row_count"] == 1


def test_spatial_query_missing_bbox_does_not_raise_key_error() -> None:
    """fix(#392): if a future caller emits `geojson` without a paired
    `bbox` (the pairing is an unenforced invariant on this plain dict, not
    encoded in any type), _collect_chat_action must degrade gracefully — omit
    both fields from the action — rather than raise an uncaught KeyError
    inside the action-collector callback. (audit WR-03)"""
    result = {
        "columns": ["geom", "name"],
        "rows": [[{"type": "Point", "coordinates": [-73.9, 40.7]}, "NYC"]],
        "row_count": 1,
        "truncated": False,
        "geojson": {"type": "FeatureCollection", "features": []},
        # bbox deliberately absent
    }
    action = _collect_chat_action("query_data", {"question": "find NYC"}, result)
    assert action is not None
    assert action["type"] == "show_query_result"
    assert "geojson" not in action
    assert "bbox" not in action


def test_query_error_emits_no_action() -> None:
    """Errored query_data results MUST NOT emit show_query_result."""
    result = {"error": "syntax error in SQL", "category": "llm_cannot_answer"}
    action = _collect_chat_action("query_data", {"question": "broken"}, result)
    assert action is None


def test_empty_result_still_emits_action_with_zero_rows() -> None:
    """AI-08 empty-state: row_count=0 still emits an action so the frontend
    can show the 'The AI query returned no rows' empty-state card."""
    result = {
        "columns": ["county_name", "feature_count"],
        "rows": [],
        "row_count": 0,
        "truncated": False,
        "note": "No matching results found. The user may want to try different criteria.",
    }
    action = _collect_chat_action(
        "query_data", {"question": "impossible filter"}, result
    )
    assert action is not None, "empty result still emits action for empty-state UI"
    assert action["type"] == "show_query_result"
    assert action["rows"] == []
    assert action["row_count"] == 0


def test_non_query_tool_emits_no_action() -> None:
    """Non-query_data tools that are not in _EDIT_TOOLS emit no action."""
    action = _collect_chat_action("unknown_tool", {}, {"result": "x"})
    assert action is None


def test_chat_action_round_trip_preserves_query_result_fields() -> None:
    """Regression (builder-audit #338 B-001): the inline data-table fields are built
    by _collect_chat_action but were absent from the ChatAction model, so
    ``ChatAction(**a).model_dump(exclude_none=True)`` silently dropped them and
    the frontend data card never rendered."""
    result = {
        "columns": ["name", "count"],
        "rows": [["A", 1], ["B", 2]],
        "row_count": 2,
        "truncated": False,
    }
    action = _collect_chat_action("query_data", {"question": "q"}, result)
    assert action is not None
    dumped = ChatAction(**action).model_dump(exclude_none=True)
    assert dumped["columns"] == ["name", "count"]
    assert dumped["rows"] == [["A", 1], ["B", 2]]
    assert dumped["row_count"] == 2
    assert dumped["truncated"] is False


def test_chat_action_round_trip_preserves_add_layer_dataset_name() -> None:
    """Regression (builder-audit #338 B-002): add_layer carried dataset_name but the
    ChatAction model dropped it, so staging chips showed the raw UUID."""
    action = {"type": "add_layer", "dataset_id": "ds-1", "dataset_name": "Parks"}
    dumped = ChatAction(**action).model_dump(exclude_none=True)
    assert dumped["dataset_name"] == "Parks"


def test_set_style_emits_backend_validated_paint_not_raw_tool_input() -> None:
    """fix(#392): _execute_chat_tool computes validated/clamped
    paint into `result` (it lives there because `tool_input` was reassigned to
    `next_input` and returned), but _collect_chat_action previously re-emitted
    the raw `tool_input['paint']` fn_args unchanged. The emitted action's paint
    must reflect the validated `result` value, not the raw invalid/unclamped
    one the model produced. (audit B-002/CH-02)"""
    raw_tool_input = {
        "layer_id": "layer-1",
        # Raw AI output: circle-radius is invalid for a fill layer and would be
        # dropped by validation; fill-opacity is out-of-bounds and would be clamped.
        "paint": {"circle-radius": 40, "fill-opacity": 5.0},
    }
    # `result` as _execute_chat_tool actually returns it: validated/clamped paint,
    # with the invalid prop dropped and the out-of-bounds prop clamped to 1.0.
    result = {"status": "ok", "layer_id": "layer-1", "paint": {"fill-opacity": 1.0}}

    action = _collect_chat_action("set_style", raw_tool_input, result)

    assert action is not None
    assert action["type"] == "set_style"
    assert action["paint"] == {"fill-opacity": 1.0}, (
        "emitted paint must be the validated result value, not the raw tool_input"
    )


def test_set_style_emits_backend_validated_clear_paint_not_raw_tool_input() -> None:
    """Companion to the paint pin above: clear_paint must also prefer the
    validated `result` list over the raw `tool_input` clear_paint."""
    raw_tool_input = {
        "layer_id": "layer-1",
        # Raw AI output includes a clear-paint entry invalid for the layer's
        # geometry — validation would drop it.
        "clear_paint": ["circle-radius", "fill-color"],
    }
    result = {
        "status": "ok",
        "layer_id": "layer-1",
        "clear_paint": ["fill-color"],
    }

    action = _collect_chat_action("set_style", raw_tool_input, result)

    assert action is not None
    assert action["clear_paint"] == ["fill-color"], (
        "emitted clear_paint must be the validated result value, not raw tool_input"
    )


def test_set_style_without_validation_falls_back_to_tool_input_unchanged() -> None:
    """When set_style had no paint/clear_paint (the _execute_chat_tool validation
    branch is skipped entirely), `result` carries no paint/clear_paint keys, so
    behavior is unchanged — the action is built from tool_input as before."""
    raw_tool_input = {"layer_id": "layer-1"}
    result = {"status": "ok", "layer_id": "layer-1"}

    action = _collect_chat_action("set_style", raw_tool_input, result)

    assert action is not None
    assert action["type"] == "set_style"
    assert action["layer_id"] == "layer-1"
    assert "paint" not in action
    assert "clear_paint" not in action


# ---------------------------------------------------------------------------
# fix(#394) CH-02: set_label validation
# ---------------------------------------------------------------------------


def test_set_label_error_result_emits_no_action() -> None:
    """A column-validation error from _execute_chat_tool must not still emit
    a label action built from the raw tool input."""
    action = _collect_chat_action(
        "set_label",
        {"layer_id": "l1", "column": "nope"},
        {"error": "Column 'nope' does not exist on this layer."},
    )
    assert action is None


def test_set_label_invalid_text_color_falls_back_to_default() -> None:
    from app.processing.ai.chat_actions import _build_label_action

    action = _build_label_action(
        {"layer_id": "l1", "column": "name", "text_color": {"r": 1}}
    )
    assert action["label_config"]["textColor"] == "#333333"

    action = _build_label_action(
        {"layer_id": "l1", "column": "name", "text_color": "#zzzzzz;"}
    )
    assert action["label_config"]["textColor"] == "#333333"


def test_set_label_valid_text_colors_pass_through() -> None:
    from app.processing.ai.chat_actions import _build_label_action

    for color in ("#ff0000", "rebeccapurple", "rgb(1, 2, 3)", "hsla(10, 5%, 5%, 0.4)"):
        action = _build_label_action(
            {"layer_id": "l1", "column": "name", "text_color": color}
        )
        assert action["label_config"]["textColor"] == color
