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


def test_non_spatial_query_emits_show_query_result_with_rows() -> None:
    """AI-08: query_data returning columns+rows (no geometry) MUST emit
    show_query_result so the frontend inline data card can render."""
    result = {
        "columns": ["county_name", "feature_count"],
        "rows": [["Essex", 12], ["Franklin", 8], ["Hamilton", 5]],
        "row_count": 3,
        "truncated": False,
    }
    action = _collect_chat_action("query_data", {"question": "feature count by county"}, result)
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
    action = _collect_chat_action("query_data", {"question": "impossible filter"}, result)
    assert action is not None, "empty result still emits action for empty-state UI"
    assert action["type"] == "show_query_result"
    assert action["rows"] == []
    assert action["row_count"] == 0


def test_non_query_tool_emits_no_action() -> None:
    """Non-query_data tools that are not in _EDIT_TOOLS emit no action."""
    action = _collect_chat_action("unknown_tool", {}, {"result": "x"})
    assert action is None
