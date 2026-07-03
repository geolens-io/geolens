"""Tests for chat narrative answers, error mapping, and empty result handling."""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.processing.ai.chat_service import (
    ERROR_MESSAGES,
    _handle_query_data,
    _execute_chat_tool,
    build_chat_system_prompt,
)
from app.processing.ai.schemas import ChatMapLayer
from app.platform.extensions.defaults import DefaultProcessingPort
from app.platform.sandbox.schemas import SandboxError, SandboxResult


def _make_layer(**overrides) -> ChatMapLayer:
    defaults = {
        "id": "layer-1",
        "name": "Test Layer",
        "dataset_id": "ds-1",
        "dataset_table_name": "data.ds_test",
        "geometry_type": "Point",
        "visible": True,
    }
    defaults.update(overrides)
    return ChatMapLayer(**defaults)


# --- System prompt narrative instructions ---


def test_system_prompt_has_narrative_instructions():
    """build_chat_system_prompt() output includes Query Data Responses section."""
    prompt = build_chat_system_prompt([_make_layer()])
    assert "Query Data Responses" in prompt
    assert "concise" in prompt.lower() or "finding" in prompt.lower()
    # Must not instruct to show raw SQL
    assert "Never show raw SQL" in prompt or "never show raw SQL" in prompt.lower()


def test_system_prompt_fill_opacity_example():
    """Example paint in system prompt uses visible opacity (0.7), not faint (0.3)."""
    prompt = build_chat_system_prompt([_make_layer()])
    assert "fill-opacity" in prompt
    assert '"fill-opacity": 0.7' in prompt
    assert '"fill-opacity": 0.3' not in prompt


def test_system_prompt_has_mention_syntax_hint():
    """System prompt tells the LLM how to resolve @LayerName references."""
    prompt = build_chat_system_prompt([_make_layer()])
    assert "@LayerName" in prompt or "@[Layer Name]" in prompt


# --- Error message mapping ---


def test_error_message_mapping():
    """Each SandboxError category maps to an actionable message."""
    expected_categories = {
        "query_timeout",
        "table_not_accessible",
        "invalid_query",
        "query_failed",
    }
    assert expected_categories == set(ERROR_MESSAGES.keys())
    for cat, msg in ERROR_MESSAGES.items():
        assert isinstance(msg, str)
        assert len(msg) > 10, f"Message for {cat} too short"


# --- Empty result handling ---


@pytest.mark.anyio
async def test_empty_result_handling():
    """When query returns 0 rows, returned dict includes a 'note' field."""
    empty_result = SandboxResult(
        rows=[], columns=["id", "name"], row_count=0, truncated=False
    )

    with (
        patch(
            "app.processing.ai.chat_service.generate_sql",
            new_callable=AsyncMock,
            return_value="SELECT 1",
        ),
        patch(
            "app.processing.ai.chat_service.validate_and_execute",
            new_callable=AsyncMock,
            return_value=empty_result,
        ),
    ):
        fake_user = SimpleNamespace(id=uuid.uuid4(), username="test_user")
        result = await _handle_query_data(
            {"question": "How many parks are there?"},
            AsyncMock(),  # session
            fake_user,
            [_make_layer()],
        )

    assert "note" in result
    assert "no" in result["note"].lower() or "No" in result["note"]


# --- SandboxError uses mapped message ---


@pytest.mark.anyio
async def test_sandbox_error_uses_mapped_message():
    """_execute_chat_tool returns the mapped actionable message for SandboxError."""
    with patch(
        "app.processing.ai.chat_service._handle_query_data",
        new_callable=AsyncMock,
        side_effect=SandboxError("query_timeout", "raw timeout message"),
    ):
        result = await _execute_chat_tool(
            "query_data",
            {"question": "test"},
            AsyncMock(),
            AsyncMock(),
            set(),
            [_make_layer()],
            port=DefaultProcessingPort(),
        )

    assert result["category"] == "query_timeout"
    assert result["error"] == ERROR_MESSAGES["query_timeout"]
    assert result["error"] != "raw timeout message"


# --- query_data port boundary: GeoJSON extraction round-trip ---


@pytest.mark.anyio
async def test_query_data_via_execute_chat_tool_preserves_geojson():
    """End-to-end test: _execute_chat_tool('query_data', ..., port=fake_port) preserves GeoJSON.

    Phase 225 review fix W-05 — closes the test gap where _handle_query_data's
    GeoJSON extraction (chat_service.py:608-611) was never exercised through
    the Port-bearing dispatcher. Asserts that out["geojson"] and out["bbox"]
    survive the _execute_chat_tool routing layer.
    """
    geom_str = '{"type": "Point", "coordinates": [-73.9, 40.7]}'
    geo_result = SandboxResult(
        rows=[["row-1", geom_str]],
        columns=["name", "geom"],
        row_count=1,
        truncated=False,
    )

    fake_port = DefaultProcessingPort()
    fake_user = SimpleNamespace(id=uuid.uuid4(), username="test_user")

    with (
        patch(
            "app.processing.ai.chat_service.generate_sql",
            new_callable=AsyncMock,
            return_value="SELECT name, ST_AsGeoJSON(geom) AS geom FROM data.ds_test",
        ),
        patch(
            "app.processing.ai.chat_service.validate_and_execute",
            new_callable=AsyncMock,
            return_value=geo_result,
        ),
    ):
        result = await _execute_chat_tool(
            "query_data",
            {"question": "Show me the parks"},
            AsyncMock(),  # session
            fake_user,
            set(),
            [_make_layer()],
            port=fake_port,
        )

    # Routing layer must NOT strip geojson/bbox from the inner result
    assert "geojson" in result, (
        "GeoJSON FeatureCollection lost through _execute_chat_tool"
    )
    assert result["geojson"]["type"] == "FeatureCollection"
    assert len(result["geojson"]["features"]) == 1
    assert result["geojson"]["features"][0]["geometry"]["type"] == "Point"

    assert "bbox" in result, "BBox lost through _execute_chat_tool"
    assert result["bbox"] == [-73.9, 40.7, -73.9, 40.7]

    # row_count and truncated should also pass through
    assert result["row_count"] == 1
    assert result["truncated"] is False


# --- add_layer: dataset_name resolution end-to-end (builder-audit #338 B-002) ---


@pytest.mark.anyio
async def test_add_layer_resolves_dataset_name_end_to_end():
    """builder-audit #338 B-002: an add_layer action must carry the dataset's display
    title so the staging chip shows a human name, not the raw UUID.

    Earlier the field was added to the ChatAction model + read by the frontend,
    but never populated server-side (the add_layer tool input only has
    dataset_id and _collect_chat_action fell through to {type, **tool_input}).
    This exercises the full path: _execute_chat_tool resolves the title via
    port.get_dataset(...).record.title, and _collect_chat_action propagates it.
    """
    from app.processing.ai.chat_actions import _collect_chat_action

    ds_id = str(uuid.uuid4())
    fake_dataset = SimpleNamespace(record=SimpleNamespace(title="Adirondack Trails"))
    fake_port = DefaultProcessingPort()

    with patch.object(
        fake_port, "get_dataset", new_callable=AsyncMock, return_value=fake_dataset
    ):
        result = await _execute_chat_tool(
            "add_layer",
            {"dataset_id": ds_id},
            AsyncMock(),  # session
            SimpleNamespace(id=uuid.uuid4(), username="test_user"),
            set(),
            [_make_layer()],
            port=fake_port,
        )

    assert result["dataset_name"] == "Adirondack Trails", (
        "_execute_chat_tool must resolve the dataset title onto the result"
    )

    action = _collect_chat_action("add_layer", {"dataset_id": ds_id}, result)
    assert action is not None
    assert action["type"] == "add_layer"
    assert action["dataset_id"] == ds_id
    assert action["dataset_name"] == "Adirondack Trails", (
        "_collect_chat_action must propagate the resolved name to the chip"
    )


# --- fix(#392): set_style heatmap-radius tweak survives validation (audit WR-01) ---


@pytest.mark.anyio
async def test_set_style_heatmap_radius_survives_execute_chat_tool_end_to_end():
    """A set_style call tuning heatmap-radius on an already-heatmap-rendered
    layer must not be silently stripped by geometry-type-only validation.

    The layer's dataset_geometry_type is Point (as it virtually always is for
    heatmap layers) — before the render_mode fix, validate_paint_with_feedback
    would filter heatmap-radius out as invalid-for-circle. set_style is the
    only AI tool capable of tuning heatmap-radius/opacity/intensity, so this
    silently defeated "make the heatmap wider" requests.
    """
    from app.processing.ai.chat_actions import _collect_chat_action

    heatmap_layer = _make_layer(
        geometry_type="Point",
        style_config={"render_mode": "heatmap"},
    )
    tool_input = {"layer_id": "layer-1", "paint": {"heatmap-radius": 40}}

    result = await _execute_chat_tool(
        "set_style",
        tool_input,
        AsyncMock(),  # session
        SimpleNamespace(id=uuid.uuid4(), username="test_user"),
        set(),
        [heatmap_layer],
        port=DefaultProcessingPort(),
    )

    assert result.get("paint") == {"heatmap-radius": 40}, (
        "heatmap-radius must survive render-mode-aware validation, not be "
        "stripped as invalid-for-circle"
    )

    action = _collect_chat_action("set_style", tool_input, result)
    assert action is not None
    assert action["paint"] == {"heatmap-radius": 40}


@pytest.mark.anyio
async def test_add_layer_name_lookup_failure_is_non_fatal():
    """B-002 hardening: a dataset-name lookup failure must NOT block the add —
    the action still flows with dataset_id and simply omits dataset_name."""
    from app.processing.ai.chat_actions import _collect_chat_action

    ds_id = str(uuid.uuid4())
    fake_port = DefaultProcessingPort()

    with patch.object(
        fake_port,
        "get_dataset",
        new_callable=AsyncMock,
        side_effect=RuntimeError("db down"),
    ):
        result = await _execute_chat_tool(
            "add_layer",
            {"dataset_id": ds_id},
            AsyncMock(),
            SimpleNamespace(id=uuid.uuid4(), username="test_user"),
            set(),
            [_make_layer()],
            port=fake_port,
        )

    assert result["status"] == "ok"
    assert result["dataset_id"] == ds_id
    assert "dataset_name" not in result
    action = _collect_chat_action("add_layer", {"dataset_id": ds_id}, result)
    assert action["type"] == "add_layer"
    assert "dataset_name" not in action
