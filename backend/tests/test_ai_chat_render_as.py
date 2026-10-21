"""set_render_as: the chat tool that switches how a layer is drawn."""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.platform.extensions.defaults import DefaultProcessingPort
from app.processing.ai.chat_actions import _collect_chat_action, _execute_chat_tool
from app.processing.ai.schemas import ChatAction, ChatMapLayer
from app.processing.ai.tools import select_chat_tools


def _layer(**overrides) -> ChatMapLayer:
    defaults = {
        "id": "layer-1",
        "name": "Stations",
        "dataset_id": "ds-1",
        "dataset_table_name": "data.ds_stations",
        "geometry_type": "Point",
        "feature_count": 120,
        "column_info": [
            {"name": "name", "type": "text"},
            {"name": "height_m", "type": "double precision"},
        ],
    }
    defaults.update(overrides)
    return ChatMapLayer(**defaults)


async def _run(tool_name: str, tool_input: dict, layers: list[ChatMapLayer]) -> dict:
    return await _execute_chat_tool(
        tool_name,
        tool_input,
        AsyncMock(),
        SimpleNamespace(id=uuid.uuid4(), username="test_user"),
        set(),
        layers,
        port=DefaultProcessingPort(),
    )


@pytest.mark.anyio
async def test_heatmap_switch_then_radius_in_one_turn():
    layers = [_layer()]
    switch_input = {"layer_id": "layer-1", "render_as": "heatmap"}

    switch = await _run("set_render_as", switch_input, layers)
    action = _collect_chat_action("set_render_as", switch_input, switch)
    assert action is not None
    assert ChatAction(**action).render_as == "heatmap"

    style_input = {"layer_id": "layer-1", "paint": {"heatmap-radius": 40}}
    style = await _run("set_style", style_input, layers)
    assert style["paint"] == {"heatmap-radius": 40}
    assert "warnings" not in style


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("render_as", "message"),
    [("heatmap", "heatmap-weight"), ("symbol", "icons"), ("cluster", "aggregate")],
)
async def test_data_driven_style_after_a_switch_explains_itself(render_as, message):
    layers = [_layer()]
    await _run("set_render_as", {"layer_id": "layer-1", "render_as": render_as}, layers)

    style_input = {"layer_id": "layer-1", "mode": "graduated", "column": "height_m"}
    result = await _run("set_data_driven_style", style_input, layers)

    assert message in result["error"]
    assert _collect_chat_action("set_data_driven_style", style_input, result) is None


@pytest.mark.anyio
async def test_paint_on_a_symbol_layer_is_dropped_with_a_warning():
    layers = [_layer()]
    await _run("set_render_as", {"layer_id": "layer-1", "render_as": "symbol"}, layers)

    style_input = {"layer_id": "layer-1", "paint": {"circle-color": "#dc2626"}}
    result = await _run("set_style", style_input, layers)

    assert result["paint"] == {}
    assert result["warnings"] == ["Removed 'circle-color': not valid for symbol layers"]


@pytest.mark.anyio
async def test_leaving_heatmap_clears_the_render_mode():
    layers = [_layer(style_config={"render_mode": "heatmap", "heatmapPaint": {}})]

    await _run("set_render_as", {"layer_id": "layer-1", "render_as": "point"}, layers)

    assert layers[0].style_config == {"heatmapPaint": {}}


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("layer", "tool_input", "message"),
    [
        (
            _layer(geometry_type="MultiPolygon"),
            {"render_as": "heatmap"},
            "fill, stroke, fill-stroke, extrusion-3d",
        ),
        (
            _layer(layer_type="raster_geolens", geometry_type=None),
            {"render_as": "point"},
            "Raster layers",
        ),
        (_layer(feature_count=None), {"render_as": "cluster"}, "feature count"),
        (_layer(layer_type="pointcloud"), {"render_as": "cluster"}, "vector layers"),
        (
            _layer(geometry_type="Polygon"),
            {"render_as": "extrusion-3d", "height_column": "name"},
            "not a numeric column",
        ),
        (
            _layer(
                geometry_type="Polygon", column_info=[{"name": "name", "type": "text"}]
            ),
            {"render_as": "extrusion-3d"},
            "no numeric column",
        ),
        (_layer(), {"render_as": "heatmap", "layer_id": "missing"}, "not on this map"),
    ],
)
async def test_refused_switch_reports_why_and_emits_no_action(
    layer, tool_input, message
):
    tool_input = {"layer_id": "layer-1", **tool_input}
    style_before = layer.style_config

    result = await _run("set_render_as", tool_input, [layer])

    assert message in result["error"]
    assert _collect_chat_action("set_render_as", tool_input, result) is None
    assert layer.style_config == style_before


@pytest.mark.anyio
async def test_extrusion_accepts_a_numeric_height_column():
    tool_input = {
        "layer_id": "layer-1",
        "render_as": "extrusion-3d",
        "height_column": "height_m",
    }
    result = await _run("set_render_as", tool_input, [_layer(geometry_type="Polygon")])

    action = _collect_chat_action("set_render_as", tool_input, result)
    assert action is not None
    assert action["height_column"] == "height_m"


@pytest.mark.anyio
async def test_extrusion_without_a_column_names_the_first_numeric_one():
    layer = _layer(
        geometry_type="Polygon",
        column_info=[
            {"name": "elapsed", "type": "interval"},
            {"name": "height_m", "type": "double precision"},
        ],
    )
    tool_input = {"layer_id": "layer-1", "render_as": "extrusion-3d"}

    result = await _run("set_render_as", tool_input, [layer])

    action = _collect_chat_action("set_render_as", tool_input, result)
    assert action is not None
    assert action["height_column"] == "height_m"


@pytest.mark.anyio
async def test_extrusion_by_a_text_column_is_replaced_with_a_numeric_one():
    layer = _layer(
        geometry_type="Polygon",
        style_config={"builder": {"heightColumn": "name"}},
    )
    tool_input = {"layer_id": "layer-1", "render_as": "extrusion-3d"}

    result = await _run("set_render_as", tool_input, [layer])

    assert result["height_column"] == "height_m"


def test_view_only_callers_cannot_switch_render_type():
    assert "set_render_as" in {t["name"] for t in select_chat_tools(can_edit=True)}
    assert "set_render_as" not in {t["name"] for t in select_chat_tools(can_edit=False)}


@pytest.mark.anyio
@pytest.mark.parametrize("mode", ["categorical", "graduated"])
async def test_data_driven_fill_colour_on_an_outline_only_polygon_is_refused(mode):
    layers = [
        _layer(
            geometry_type="Polygon",
            style_config={"builder": {"fillDisabled": True, "strokeDisabled": False}},
        )
    ]
    style_input = {"layer_id": "layer-1", "mode": mode, "column": "height_m"}

    result = await _run("set_data_driven_style", style_input, layers)

    assert "outline only" in result["error"]
    assert _collect_chat_action("set_data_driven_style", style_input, result) is None


@pytest.mark.anyio
async def test_switching_to_outline_only_in_a_turn_blocks_a_fill_colour_after_it():
    layers = [_layer(geometry_type="Polygon")]
    await _run("set_render_as", {"layer_id": "layer-1", "render_as": "stroke"}, layers)

    style_input = {"layer_id": "layer-1", "mode": "graduated", "column": "height_m"}
    result = await _run("set_data_driven_style", style_input, layers)

    assert "outline only" in result["error"]


@pytest.mark.anyio
async def test_switching_from_outline_only_to_fill_lifts_the_block():
    layers = [
        _layer(
            geometry_type="Polygon",
            style_config={"builder": {"fillDisabled": True, "strokeDisabled": False}},
        )
    ]
    await _run("set_render_as", {"layer_id": "layer-1", "render_as": "fill"}, layers)

    builder = layers[0].style_config["builder"]
    assert builder["fillDisabled"] is False
    assert builder["strokeDisabled"] is True


@pytest.mark.anyio
async def test_extrusion_paint_the_3d_layer_never_reads_is_dropped_with_a_hint():
    layers = [
        _layer(
            geometry_type="Polygon",
            style_config={"builder": {"heightColumn": "height_m"}},
        )
    ]
    style_input = {
        "layer_id": "layer-1",
        "paint": {"fill-extrusion-opacity": 0.5, "fill-color": "#dc2626"},
    }

    result = await _run("set_style", style_input, layers)

    assert result["paint"] == {"fill-color": "#dc2626"}
    assert "fill-color" in result["warnings"][0]
    assert "style editor" in result["warnings"][0]
