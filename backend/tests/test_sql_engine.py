"""Tests for SQL schema context builder and SQL generation prompt."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.processing.ai.chat_service import (
    _handle_query_data,
    _execute_chat_tool,
    build_chat_system_prompt,
)
from app.processing.ai.constants import tool_label
from app.processing.ai.schemas import ChatMapLayer
from app.processing.ai.tools import CHAT_TOOLS_ANTHROPIC
from app.processing.ai.sql_generator import (
    build_sql_schema_context,
    build_sql_generation_prompt,
)
from app.platform.extensions.defaults import DefaultProcessingPort
from app.platform.sandbox.schemas import SandboxError, SandboxResult

_default_port = DefaultProcessingPort()


def _make_layer(
    *,
    table_name: str = "cities",
    geometry_type: str | None = "POINT",
    column_info: list[dict] | None = None,
) -> ChatMapLayer:
    """Helper to create a ChatMapLayer for testing."""
    return ChatMapLayer(
        id="layer-1",
        name="Cities",
        dataset_id="ds-1",
        dataset_table_name=table_name,
        geometry_type=geometry_type,
        column_info=column_info,
    )


class TestSchemaContext:
    """Tests for build_sql_schema_context()."""

    def test_single_layer_produces_ddl_with_data_prefix(self):
        layer = _make_layer(
            column_info=[
                {"name": "ogc_fid", "type": "integer"},
                {"name": "name", "type": "text"},
            ],
        )
        result = build_sql_schema_context([layer])
        assert "CREATE TABLE data.cities" in result

    def test_column_info_items_appear_in_ddl(self):
        layer = _make_layer(
            column_info=[
                {"name": "ogc_fid", "type": "integer"},
                {"name": "name", "type": "text"},
                {"name": "population", "type": "bigint"},
            ],
        )
        result = build_sql_schema_context([layer])
        assert "ogc_fid integer" in result
        assert "name text" in result
        assert "population bigint" in result

    def test_geometry_type_appears_as_comment(self):
        layer = _make_layer(geometry_type="POINT")
        result = build_sql_schema_context([layer])
        assert "Geometry: POINT" in result
        assert "geom_4326" in result

    def test_truncation_at_50_columns(self):
        cols = [{"name": f"col_{i}", "type": "text"} for i in range(60)]
        layer = _make_layer(column_info=cols)
        result = build_sql_schema_context([layer])
        # First 50 should be present
        assert "col_0 text" in result
        assert "col_49 text" in result
        # Column 50+ should NOT be present individually
        assert "col_50 text" not in result
        # Truncation message should appear
        assert "-- ... and 10 more columns" in result

    def test_no_geometry_omits_geom_column(self):
        layer = _make_layer(
            geometry_type=None,
            column_info=[{"name": "id", "type": "integer"}],
        )
        result = build_sql_schema_context([layer])
        assert "geom_4326" not in result
        assert "-- No geometry column" in result

    def test_multiple_layers_produce_multiple_ddl_blocks(self):
        layer1 = _make_layer(
            table_name="cities",
            column_info=[{"name": "name", "type": "text"}],
        )
        layer2 = ChatMapLayer(
            id="layer-2",
            name="Countries",
            dataset_id="ds-2",
            dataset_table_name="countries",
            geometry_type="MULTIPOLYGON",
            column_info=[{"name": "name", "type": "text"}],
        )
        result = build_sql_schema_context([layer1, layer2])
        assert "CREATE TABLE data.cities" in result
        assert "CREATE TABLE data.countries" in result
        # Separated by blank lines
        assert "\n\n" in result

    def test_empty_column_info_none(self):
        layer = _make_layer(column_info=None)
        result = build_sql_schema_context([layer])
        assert "CREATE TABLE data.cities" in result

    def test_empty_column_info_empty_list(self):
        layer = _make_layer(column_info=[])
        result = build_sql_schema_context([layer])
        assert "CREATE TABLE data.cities" in result


class TestSqlPrompt:
    """Tests for build_sql_generation_prompt()."""

    def setup_method(self):
        self.schema = "CREATE TABLE data.cities (\n  name text\n);"
        self.prompt = build_sql_generation_prompt(
            question="How many cities per country?",
            schema_context=self.schema,
        )

    def test_includes_all_8_postgis_functions(self):
        required = [
            "ST_Intersects",
            "ST_Contains",
            "ST_Within",
            "ST_Buffer",
            "ST_Area",
            "ST_Distance",
            "ST_Union",
            "ST_Centroid",
        ]
        for fn in required:
            assert fn in self.prompt, f"Missing PostGIS function: {fn}"

    def test_includes_geography_cast(self):
        assert "::geography" in self.prompt

    def test_includes_spatial_join_group_by_example(self):
        assert "GROUP BY" in self.prompt
        assert "ST_Intersects" in self.prompt

    def test_includes_user_question(self):
        assert "How many cities per country?" in self.prompt

    def test_includes_schema_context(self):
        assert self.schema in self.prompt

    def test_instructs_data_schema_prefix(self):
        assert "data." in self.prompt

    def test_instructs_geom_4326_column(self):
        assert "geom_4326" in self.prompt

    def test_includes_unit_conversion_factors(self):
        assert "4046.8564224" in self.prompt  # sq meters to acres
        assert "1609.344" in self.prompt  # meters to miles
        assert "acres" in self.prompt.lower()

    def test_includes_area_example_query(self):
        assert "total_acres" in self.prompt
        assert "ST_Area" in self.prompt

    def test_instructs_human_friendly_units(self):
        assert "human-friendly units" in self.prompt


# ------------------------------------------------------------------
# Tests for query_data tool integration (Plan 02)
# ------------------------------------------------------------------


def _mock_user():
    user = MagicMock()
    user.id = "user-1"
    return user


class TestQueryDataTool:
    """Tests for _handle_query_data and its integration in _execute_chat_tool."""

    @pytest.mark.asyncio
    @patch(
        "app.processing.ai.chat_service.validate_and_execute", new_callable=AsyncMock
    )
    @patch("app.processing.ai.chat_service.generate_sql", new_callable=AsyncMock)
    async def test_handle_returns_structured_result(self, mock_gen, mock_exec):
        mock_gen.return_value = "SELECT count(*) FROM data.cities"
        mock_exec.return_value = SandboxResult(
            rows=[[42]], columns=["count"], row_count=1, truncated=False
        )
        layers = [_make_layer(column_info=[{"name": "name", "type": "text"}])]
        result = await _handle_query_data(
            {"question": "How many cities?"}, AsyncMock(), _mock_user(), layers
        )
        assert result["columns"] == ["count"]
        assert result["rows"] == [[42]]
        assert result["row_count"] == 1
        assert result["truncated"] is False

    @pytest.mark.asyncio
    @patch(
        "app.processing.ai.chat_service.validate_and_execute", new_callable=AsyncMock
    )
    @patch("app.processing.ai.chat_service.generate_sql", new_callable=AsyncMock)
    async def test_rows_truncated_to_50(self, mock_gen, mock_exec):
        mock_gen.return_value = "SELECT * FROM data.cities"
        mock_exec.return_value = SandboxResult(
            rows=[[i] for i in range(100)],
            columns=["id"],
            row_count=100,
            truncated=False,
        )
        layers = [_make_layer()]
        result = await _handle_query_data(
            {"question": "All cities"}, AsyncMock(), _mock_user(), layers
        )
        assert len(result["rows"]) == 50
        assert result["row_count"] == 100

    @pytest.mark.asyncio
    @patch(
        "app.processing.ai.chat_service.validate_and_execute", new_callable=AsyncMock
    )
    @patch("app.processing.ai.chat_service.generate_sql", new_callable=AsyncMock)
    async def test_sandbox_error_returns_error_dict(self, mock_gen, mock_exec):
        mock_gen.return_value = "DROP TABLE cities"
        mock_exec.side_effect = SandboxError("invalid_query", "Only SELECT allowed")
        result = await _execute_chat_tool(
            "query_data",
            {"question": "drop it"},
            AsyncMock(),
            _mock_user(),
            set(),
            [_make_layer()],
            port=_default_port,
        )
        assert (
            result["error"]
            == "I couldn't generate a valid query for that. Try rephrasing your question."
        )
        assert result["category"] == "invalid_query"

    @pytest.mark.asyncio
    @patch("app.processing.ai.chat_service.generate_sql", new_callable=AsyncMock)
    async def test_llm_failure_returns_generic_error(self, mock_gen):
        mock_gen.side_effect = RuntimeError("LLM unreachable")
        result = await _execute_chat_tool(
            "query_data",
            {"question": "anything"},
            AsyncMock(),
            _mock_user(),
            set(),
            [_make_layer()],
            port=_default_port,
        )
        assert result["error"] == "Could not generate or execute query"

    @pytest.mark.asyncio
    @patch(
        "app.processing.ai.chat_service.validate_and_execute", new_callable=AsyncMock
    )
    @patch("app.processing.ai.chat_service.generate_sql", new_callable=AsyncMock)
    async def test_execute_chat_tool_dispatches_query_data(self, mock_gen, mock_exec):
        mock_gen.return_value = "SELECT 1"
        mock_exec.return_value = SandboxResult(
            rows=[[1]], columns=["col"], row_count=1, truncated=False
        )
        result = await _execute_chat_tool(
            "query_data",
            {"question": "test"},
            AsyncMock(),
            _mock_user(),
            set(),
            [_make_layer()],
            port=_default_port,
        )
        assert "columns" in result
        assert "rows" in result


class TestToolDefinitions:
    """Tests for query_data in tool definition lists."""

    def test_query_data_in_anthropic_tools(self):
        tool = next(
            (t for t in CHAT_TOOLS_ANTHROPIC if t["name"] == "query_data"), None
        )
        assert tool is not None
        assert "description" in tool
        assert "input_schema" in tool
        assert "question" in tool["input_schema"]["properties"]

    def test_query_data_in_openai_tools(self):
        # Phase 226 D-08: CHAT_TOOLS_OPENAI removed (callers pass Anthropic shape;
        # provider converts internally). Derive OpenAI format algorithmically.
        chat_tools_openai = [
            {"type": "function", "function": {"name": t["name"], "description": t["description"], "parameters": t["input_schema"]}}
            for t in CHAT_TOOLS_ANTHROPIC
        ]
        tool = next(
            (t for t in chat_tools_openai if t["function"]["name"] == "query_data"),
            None,
        )
        assert tool is not None
        assert tool["type"] == "function"


class TestSystemPromptQueryData:
    """Tests for query_data routing guidance in system prompt."""

    def test_system_prompt_includes_query_data_guidance(self):
        layer = _make_layer(column_info=[{"name": "name", "type": "text"}])
        prompt = build_chat_system_prompt([layer])
        assert "query_data" in prompt
        assert "QUESTION" in prompt
        assert "CHANGE" in prompt


class TestToolLabel:
    """Tests for tool_label() which maps tool names to UI labels."""

    @pytest.mark.parametrize(
        "tool_name,expected",
        [
            ("query_data", "Querying data..."),
            ("search_datasets", "Searching datasets..."),
            ("set_filter", "Applying filter..."),
            ("set_style", "Changing style..."),
            ("set_data_driven_style", "Building data-driven style..."),
            ("set_label", "Configuring labels..."),
            ("toggle_visibility", "Toggling visibility..."),
            ("remove_layer", "Removing layer..."),
            ("add_layer", "Adding layer..."),
            ("set_opacity", "Adjusting opacity..."),
            ("get_dataset_details", "Fetching dataset details..."),
        ],
    )
    def test_known_tool_label(self, tool_name: str, expected: str):
        """Every registered tool has its canonical label."""
        assert tool_label(tool_name) == expected

    def test_unknown_tool_falls_back_to_running_template(self):
        """Unknown tools return a generic 'Running X...' label."""
        assert tool_label("something_new") == "Running something_new..."
        assert tool_label("") == "Running ..."
