# SPDX-License-Identifier: Apache-2.0
"""Registration self-checks for the MCP server module (test #827, mock tier).

DB-less: asserts the FastMCP instance in server.py registers exactly the
advertised read-only tools with the argument schemas agents rely on, and that
the decorated functions stay plain callables (the live-contract tier in
test_live_contract.py invokes them as normal functions).
"""

from __future__ import annotations

import asyncio

import pytest

from geolens_mcp import server
from geolens_mcp.client import ConfigError

# name -> (required args, all advertised args). A drift here is a breaking
# change for every configured MCP client, so the sets are pinned exactly.
EXPECTED_TOOLS = {
    "search_datasets": ({"query"}, {"query", "limit", "offset"}),
    "get_dataset_schema": ({"dataset_id"}, {"dataset_id"}),
    "get_features": ({"dataset_id"}, {"dataset_id", "limit", "offset", "bbox"}),
    "list_maps": (set(), {"search", "limit", "offset"}),
    "get_map": ({"map_id"}, {"map_id"}),
    # feat(#565): sandboxed read-only SQL. restrict_tables is REQUIRED — the
    # backend refuses an unscoped query, so the schema must say so too.
    "query": ({"sql", "restrict_tables"}, {"sql", "restrict_tables", "row_limit"}),
}


def _tools():
    return asyncio.run(server.mcp.list_tools())


def test_registers_exactly_the_advertised_tools():
    assert {t.name for t in _tools()} == set(EXPECTED_TOOLS)


def test_tool_argument_schemas_match_contract():
    for tool in _tools():
        required, props = EXPECTED_TOOLS[tool.name]
        assert set(tool.inputSchema.get("required") or []) == required, tool.name
        assert set(tool.inputSchema.get("properties") or {}) == props, tool.name


def test_every_tool_has_a_description():
    # Descriptions are the agent-facing docs — an empty one ships a mystery tool.
    for tool in _tools():
        assert tool.description and tool.description.strip(), tool.name


def test_dataset_tool_descriptions_explain_source_trust_contract():
    descriptions = {tool.name: tool.description for tool in _tools()}

    search = descriptions["search_datasets"]
    assert "source_origin" in search
    assert "overdue" in search
    assert "null" in search
    assert "get_dataset_schema" in search

    detail = descriptions["get_dataset_schema"]
    assert "inaccessible" in detail
    assert "last_checked_at" in detail
    assert "last_refreshed_at" in detail
    assert "Raw provider URLs" in detail


def test_tool_functions_stay_plain_callables():
    # The live tier (and any direct import) calls these as normal functions; an
    # MCP SDK upgrade whose decorator returns a wrapper would break that quietly.
    for name in EXPECTED_TOOLS:
        assert callable(getattr(server, name)), name


def test_tools_require_config_only_when_invoked(monkeypatch):
    # Importing/listing must never need GEOLENS_INSTANCE — only invocation does.
    monkeypatch.delenv("GEOLENS_INSTANCE", raising=False)
    monkeypatch.setattr(server, "_api", None)
    assert {t.name for t in _tools()} == set(EXPECTED_TOOLS)
    with pytest.raises(ConfigError):
        server.list_maps()
