"""Tests for chat narrative answers, error mapping, and empty result handling."""

from unittest.mock import AsyncMock, patch

import pytest

from app.processing.ai.chat_service import (
    ERROR_MESSAGES,
    _handle_query_data,
    _execute_chat_tool,
    build_chat_system_prompt,
)
from app.processing.ai.schemas import ChatMapLayer
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
        result = await _handle_query_data(
            {"question": "How many parks are there?"},
            AsyncMock(),  # session
            AsyncMock(),  # user
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
        )

    assert result["category"] == "query_timeout"
    assert result["error"] == ERROR_MESSAGES["query_timeout"]
    assert result["error"] != "raw timeout message"
