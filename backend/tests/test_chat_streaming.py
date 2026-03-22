"""Integration tests for SSE streaming chat endpoint."""

import json
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient


CHAT_BODY = {
    "message": "Make the layer red",
    "map_id": "test-map-id",
    "layers": [
        {
            "id": "layer-1",
            "name": "Test Layer",
            "dataset_id": "ds-1",
            "dataset_table_name": "data.ds_test",
            "geometry_type": "Polygon",
            "visible": True,
        }
    ],
}


async def _mock_stream_tokens(*args, **kwargs):
    """Mock generator yielding token and done events."""
    yield {"type": "token", "text": "Hello "}
    yield {"type": "token", "text": "world"}
    yield {"type": "actions", "actions": []}
    yield {"type": "done", "explanation": "Hello world"}


async def _mock_stream_tools(*args, **kwargs):
    """Mock generator yielding tool progress events."""
    yield {"type": "tool_start", "tool": "set_style", "label": "Changing style..."}
    yield {"type": "tool_result", "tool": "set_style", "success": True}
    yield {
        "type": "actions",
        "actions": [
            {
                "type": "set_style",
                "layer_id": "layer-1",
                "paint": {"fill-color": "#ff0000"},
            }
        ],
    }
    yield {"type": "done", "explanation": "Done"}


def _parse_sse_events(text: str) -> list[dict]:
    """Parse SSE text into list of dicts with 'event' and 'data' keys.

    SSE format from sse-starlette:
        event: token
        data: {"type": "token", "text": "Hello "}

        event: done
        data: {"type": "done", "explanation": "Hello world"}
    """
    events = []
    current_event = None
    current_data_lines: list[str] = []

    # Normalize line endings
    lines = text.replace("\r\n", "\n").split("\n")

    for line in lines:
        if line.startswith("event:"):
            current_event = line.split(":", 1)[1].strip()
        elif line.startswith("data:"):
            current_data_lines.append(line.split(":", 1)[1].strip())
        elif line == "":
            if current_data_lines:
                raw = "\n".join(current_data_lines)
                try:
                    data = json.loads(raw)
                except json.JSONDecodeError:
                    data = raw
                events.append({"event": current_event, "data": data})
                current_event = None
                current_data_lines = []

    # Handle trailing event without final blank line
    if current_data_lines:
        raw = "\n".join(current_data_lines)
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            data = raw
        events.append({"event": current_event, "data": data})

    return events


@pytest.mark.anyio
async def test_stream_returns_sse_events(client: AsyncClient, admin_auth_header: dict):
    with patch("app.ai.router._check_ai_available", new_callable=AsyncMock), \
         patch("app.ai.router._validate_chat_layers", new_callable=AsyncMock, return_value=CHAT_BODY["layers"]), \
         patch("app.ai.router.stream_chat_edit", side_effect=_mock_stream_tokens):
            resp = await client.post(
                "/ai/chat/stream/", json=CHAT_BODY, headers=admin_auth_header
            )

    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers.get("content-type", "")

    events = _parse_sse_events(resp.text)
    event_types = [e["event"] for e in events]
    assert "token" in event_types
    assert "done" in event_types


@pytest.mark.anyio
async def test_non_streaming_fallback(client: AsyncClient, admin_auth_header: dict):
    """Existing /ai/chat/ endpoint still works."""
    from app.ai.schemas import ChatResponse

    mock_result = ChatResponse(explanation="test", actions=[])

    with patch("app.ai.router._check_ai_available", new_callable=AsyncMock), \
         patch("app.ai.router._validate_chat_layers", new_callable=AsyncMock, return_value=CHAT_BODY["layers"]), \
         patch("app.ai.router.chat_edit_map", new_callable=AsyncMock) as mock_chat:
            mock_chat.return_value = mock_result
            resp = await client.post(
                "/ai/chat/", json=CHAT_BODY, headers=admin_auth_header
            )

    assert resp.status_code == 200
    data = resp.json()
    assert "explanation" in data


@pytest.mark.anyio
async def test_tool_progress_events(client: AsyncClient, admin_auth_header: dict):
    with patch("app.ai.router._check_ai_available", new_callable=AsyncMock), \
         patch("app.ai.router._validate_chat_layers", new_callable=AsyncMock, return_value=CHAT_BODY["layers"]), \
         patch("app.ai.router.stream_chat_edit", side_effect=_mock_stream_tools):
            resp = await client.post(
                "/ai/chat/stream/", json=CHAT_BODY, headers=admin_auth_header
            )

    assert resp.status_code == 200
    events = _parse_sse_events(resp.text)

    tool_starts = [e for e in events if e["event"] == "tool_start"]
    assert len(tool_starts) >= 1
    assert "tool" in tool_starts[0]["data"]
    assert "label" in tool_starts[0]["data"]

    tool_results = [e for e in events if e["event"] == "tool_result"]
    assert len(tool_results) >= 1
    assert "tool" in tool_results[0]["data"]
    assert "success" in tool_results[0]["data"]


async def _mock_stream_query_data(*args, **kwargs):
    """Mock generator yielding query_data sub-stage events."""
    yield {"type": "tool_start", "tool": "query_data", "label": "Querying data..."}
    yield {"type": "tool_start", "tool": "query_data", "label": "Generating SQL..."}
    yield {"type": "tool_start", "tool": "query_data", "label": "Running query..."}
    yield {"type": "tool_result", "tool": "query_data", "success": True}
    yield {"type": "token", "text": "Found 5 results"}
    yield {"type": "actions", "actions": []}
    yield {"type": "done", "explanation": "Found 5 results"}


@pytest.mark.anyio
async def test_query_data_stage_events(client: AsyncClient, admin_auth_header: dict):
    """Sub-stage tool_start events for query_data arrive before tool_result."""
    body = {
        "message": "How many features are in the layer?",
        "map_id": "test-map-id",
        "layers": [
            {
                "id": "layer-1",
                "name": "Test Layer",
                "dataset_id": "ds-1",
                "dataset_table_name": "data.ds_test",
                "geometry_type": "Polygon",
                "visible": True,
            }
        ],
    }

    with patch("app.ai.router._check_ai_available", new_callable=AsyncMock), \
         patch("app.ai.router._validate_chat_layers", new_callable=AsyncMock, return_value=body["layers"]), \
         patch("app.ai.router.stream_chat_edit", side_effect=_mock_stream_query_data):
            resp = await client.post(
                "/ai/chat/stream/", json=body, headers=admin_auth_header
            )

    assert resp.status_code == 200
    events = _parse_sse_events(resp.text)

    # Collect tool_start and tool_result events for query_data
    query_events = [
        e
        for e in events
        if e["data"].get("tool") == "query_data"
        and e["event"] in ("tool_start", "tool_result")
    ]

    # Must have at least 3 tool_start (generic + 2 sub-stages) + 1 tool_result
    tool_start_labels = [
        e["data"]["label"] for e in query_events if e["event"] == "tool_start"
    ]
    assert "Generating SQL..." in tool_start_labels
    assert "Running query..." in tool_start_labels

    # Both sub-stage labels must appear before tool_result
    tool_result_idx = next(
        i for i, e in enumerate(query_events) if e["event"] == "tool_result"
    )
    gen_sql_idx = next(
        i
        for i, e in enumerate(query_events)
        if e["event"] == "tool_start" and e["data"].get("label") == "Generating SQL..."
    )
    run_query_idx = next(
        i
        for i, e in enumerate(query_events)
        if e["event"] == "tool_start" and e["data"].get("label") == "Running query..."
    )
    assert gen_sql_idx < tool_result_idx
    assert run_query_idx < tool_result_idx
    assert gen_sql_idx < run_query_idx


SAMPLE_GEOJSON_FC = {
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [1, 2]},
            "properties": {"id": 1},
        }
    ],
}


async def _mock_stream_query_with_geojson(*args, **kwargs):
    """Mock generator yielding query_data with show_query_result action."""
    yield {"type": "tool_start", "tool": "query_data", "label": "Querying data..."}
    yield {"type": "tool_result", "tool": "query_data", "success": True}
    yield {"type": "token", "text": "Found results with geometry"}
    yield {
        "type": "actions",
        "actions": [
            {
                "type": "show_query_result",
                "geojson": SAMPLE_GEOJSON_FC,
                "bbox": [1.0, 2.0, 1.0, 2.0],
            }
        ],
    }
    yield {"type": "done", "explanation": "Found results with geometry"}


@pytest.mark.anyio
async def test_show_query_result_action_in_stream(
    client: AsyncClient, admin_auth_header: dict
):
    """show_query_result action is included when query_data returns geojson."""
    body = {
        "message": "Show parks near downtown",
        "map_id": "test-map-id",
        "layers": [
            {
                "id": "layer-1",
                "name": "Parks",
                "dataset_id": "ds-1",
                "dataset_table_name": "data.ds_parks",
                "geometry_type": "Polygon",
                "visible": True,
            }
        ],
    }

    with patch("app.ai.router._check_ai_available", new_callable=AsyncMock), \
         patch("app.ai.router._validate_chat_layers", new_callable=AsyncMock, return_value=body["layers"]), \
         patch("app.ai.router.stream_chat_edit", side_effect=_mock_stream_query_with_geojson):
            resp = await client.post(
                "/ai/chat/stream/", json=body, headers=admin_auth_header
            )

    assert resp.status_code == 200
    events = _parse_sse_events(resp.text)

    # Find the actions event
    action_events = [e for e in events if e["event"] == "actions"]
    assert len(action_events) == 1
    actions = action_events[0]["data"]["actions"]
    assert len(actions) == 1
    assert actions[0]["type"] == "show_query_result"
    assert actions[0]["geojson"]["type"] == "FeatureCollection"
    assert "bbox" in actions[0]


@pytest.mark.anyio
async def test_stream_unauthenticated(client: AsyncClient):
    resp = await client.post("/ai/chat/stream/", json=CHAT_BODY)
    assert resp.status_code == 401


@pytest.mark.anyio
async def test_stream_ai_disabled(client: AsyncClient, admin_auth_header: dict):
    from fastapi import HTTPException

    with patch(
        "app.ai.router._check_ai_available", new_callable=AsyncMock
    ) as mock_check:
        mock_check.side_effect = HTTPException(
            status_code=403, detail="AI features are disabled by administrator"
        )
        resp = await client.post(
            "/ai/chat/stream/", json=CHAT_BODY, headers=admin_auth_header
        )

    assert resp.status_code == 403
