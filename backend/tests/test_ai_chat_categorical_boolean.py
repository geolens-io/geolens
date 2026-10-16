"""AI categorical styling on a boolean column must emit valid match labels.

MapLibre rejects boolean match labels ("Branch labels must be numbers or
strings"), so the paint was dropped and the layer stayed unstyled.
"""

from __future__ import annotations

import pytest

from app.processing.ai.chat_styles import _build_categorical_style


class _StubPort:
    def __init__(self, values: list):
        self._values = values

    async def get_distinct_values(self, session, table_name, column, **kwargs):
        return self._values


async def _build(values):
    return await _build_categorical_style(
        session=None,
        table_name="sites",
        column="open",
        ramp="Set2",
        color_prop="circle-color",
        layer_id="layer-1",
        port=_StubPort(values),
    )


@pytest.mark.asyncio
async def test_boolean_column_matches_on_string_labels():
    result = await _build([True, False])
    expr = result["paint"]["circle-color"]
    assert expr[:2] == ["match", ["to-string", ["get", "open"]]]
    labels = expr[2:-1:2]
    assert labels == ["true", "false"]
    assert all(isinstance(label, str) for label in labels)
    assert [c["value"] for c in result["style_config"]["categories"]] == [
        "true",
        "false",
    ]


@pytest.mark.asyncio
async def test_text_and_numeric_columns_keep_native_labels():
    text = (await _build(["a", "b"]))["paint"]["circle-color"]
    assert text[:2] == ["match", ["get", "open"]]
    assert text[2:-1:2] == ["a", "b"]
    numeric = (await _build([1, 2.5]))["paint"]["circle-color"]
    assert numeric[1] == ["get", "open"]
    assert numeric[2:-1:2] == [1, 2.5]
