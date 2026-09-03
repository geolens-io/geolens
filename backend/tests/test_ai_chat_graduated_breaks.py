"""fix(#1778): AI graduated styling must emit strictly ascending step stops.

From the codebase audit of 2026-08-30: `_build_graduated_style` fed the raw
`quantiles` list from `get_column_stats` straight into a MapLibre `step`
expression. `percentile_cont` does not deduplicate, so a clustered column
produces adjacent equal breaks and MapLibre rejects the expression. The client
cannot catch it: `validateChatPaint` filters paint KEYS by geometry type and
clamps scalar numerics, and never inspects the interior of a server-built
expression. The malformed paint is applied live and saved with the map.

Both frontend siblings dedupe for the styles they build themselves
(`classification.ts` and `DataDrivenStyleEditor.tsx` each do
`[...new Set(breaks)]`), which is what this mirrors on the server side.
"""

from __future__ import annotations

import json

import pytest

from app.processing.ai.chat_styles import _build_graduated_style


class _StubPort:
    """Minimal ProcessingPort stand-in that returns canned column stats."""

    def __init__(self, stats: dict):
        self._stats = stats

    async def get_column_stats(
        self,
        session,
        table_name,
        column_name,
        *,
        class_count=5,
        allowed_tables=None,
    ) -> dict:
        return self._stats


async def _build(quantiles, *, min_val=0.0, max_val=100.0, class_count=5):
    port = _StubPort({"min": min_val, "max": max_val, "quantiles": quantiles})
    return await _build_graduated_style(
        session=None,
        table_name="parks",
        column="area",
        ramp="YlOrRd",
        method="quantile",
        class_count=class_count,
        color_prop="fill-color",
        layer_id="layer-1",
        allowed_tables={"parks"},
        port=port,
    )


def _stops(step_expr: list) -> list[float]:
    """The numeric stops of a MapLibre step expression.

    Layout is ["step", <input>, <color0>, stop1, color1, stop2, color2, ...],
    so the stops are every other element from index 3.
    """
    return step_expr[3::2]


class TestGraduatedBreaksAreStrictlyAscending:
    async def test_duplicate_quantiles_are_collapsed(self):
        # 70% of rows sharing one value collapses three adjacent quantiles.
        result = await _build([0.0, 0.0, 0.0, 42.0])
        assert "error" not in result
        stops = _stops(result["paint"]["fill-color"])
        assert stops == [0.0, 42.0]
        assert stops == sorted(set(stops))

    async def test_unsorted_quantiles_are_ordered(self):
        result = await _build([30.0, 10.0, 20.0])
        stops = _stops(result["paint"]["fill-color"])
        assert stops == [10.0, 20.0, 30.0]

    async def test_every_break_has_its_own_colour(self):
        result = await _build([0.0, 0.0, 0.0, 42.0])
        step_expr = result["paint"]["fill-color"]
        colours = [step_expr[2], *step_expr[4::2]]
        assert len(colours) == len(_stops(step_expr)) + 1
        # The surviving breaks span the ramp instead of crowding its low end.
        assert len(set(colours)) == len(colours)

    async def test_style_config_breaks_match_the_expression(self):
        result = await _build([5.0, 5.0, 9.0])
        entries = result["style_config"]["breaks"]
        assert [e["value"] for e in entries] == _stops(result["paint"]["fill-color"])

    async def test_non_finite_quantiles_are_dropped(self):
        # PostgreSQL sorts NaN as the largest value, so percentile_cont over a
        # double precision column holding one can return it. A NaN stop is not
        # a valid MapLibre step boundary and would make the actions frame
        # unparseable in the browser.
        result = await _build([1.0, float("nan"), 2.0, float("inf")])
        stops = _stops(result["paint"]["fill-color"])
        assert stops == [1.0, 2.0]
        assert json.dumps(result["paint"], allow_nan=False)

    async def test_all_breaks_identical_still_yields_one_stop(self):
        result = await _build([7.0, 7.0, 7.0, 7.0])
        assert _stops(result["paint"]["fill-color"]) == [7.0]

    async def test_no_usable_breaks_returns_an_error(self):
        result = await _build([float("nan"), float("nan")])
        assert "error" in result

    async def test_equal_interval_breaks_are_unaffected(self):
        port = _StubPort({"min": 0.0, "max": 100.0, "quantiles": []})
        result = await _build_graduated_style(
            session=None,
            table_name="parks",
            column="area",
            ramp="YlOrRd",
            method="equal_interval",
            class_count=5,
            color_prop="fill-color",
            layer_id="layer-1",
            allowed_tables={"parks"},
            port=port,
        )
        assert _stops(result["paint"]["fill-color"]) == [20.0, 40.0, 60.0, 80.0]


@pytest.mark.parametrize(
    "quantiles",
    [
        [0.0, 0.0],
        [1.0, 1.0, 1.0, 2.0],
        [3.0, 2.0, 2.0, 1.0],
    ],
)
async def test_step_expression_never_repeats_a_stop(quantiles):
    result = await _build(quantiles)
    stops = _stops(result["paint"]["fill-color"])
    assert len(stops) == len(set(stops))
    assert stops == sorted(stops)
