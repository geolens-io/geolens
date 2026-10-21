"""Ask AI's ramp colors match the style editor's ``getRampColors``.

``tests/fixtures/ramp_parity.json`` holds the editor's output; the frontend
test ``src/lib/__tests__/color-ramps.parity.test.ts`` reads the same file.
"""

import json
from pathlib import Path

import pytest

from app.processing.ai.chat_constants import _get_ramp_colors

_EXPECTED = json.loads(
    (Path(__file__).parent / "fixtures" / "ramp_parity.json").read_text()
)
_CASES = [
    (ramp, int(count), colors)
    for ramp, by_count in _EXPECTED.items()
    for count, colors in by_count.items()
]


@pytest.mark.parametrize(("ramp", "count", "colors"), _CASES)
def test_ramp_colors_match_the_style_editor(ramp, count, colors):
    assert _get_ramp_colors(ramp, count) == colors
