"""A story image decode stays within the memory it reserves.

The decode budget charges each format a measured cost per pixel. If a Pillow
or libwebp change made decoding hungrier, the budget would stop bounding the
process, so each worst case runs at its format's cap in a fresh interpreter
and its peak resident memory is compared with the reservation.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image

from app.modules.catalog.stories import images

resource = pytest.importorskip("resource")

_BACKEND = Path(__file__).resolve().parents[1]

_CHILD = """
import resource, sys
from io import BytesIO
from PIL import Image
from app.modules.catalog.stories.images import decode_story_image, plan_story_image

def peak():
    used = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return used if sys.platform == "darwin" else used * 1024

warm = BytesIO()
Image.new("RGBA", (8, 8)).save(warm, "PNG")
decode_story_image(warm.getvalue(), plan_story_image(warm.getvalue()))
data = open(sys.argv[1], "rb").read()
plan = plan_story_image(data)
base = peak()
decode_story_image(data, plan)
print(peak() - base, plan.cost)
"""


def _side(weight: str) -> int:
    return int(images.MAX_PIXELS[weight] ** 0.5)


# A one-pass JPEG decodes fullest just under twice the output size a side.
_ONE_PASS_SIDE = 2 * images.MAX_OUTPUT_SIDE - 1


@pytest.mark.parametrize(
    ("kind", "side", "mode", "options"),
    [
        pytest.param("WEBP", _side("WEBP"), "RGBA", {"quality": 50}, id="webp"),
        pytest.param(
            "WEBP", _side("WEBP"), "RGBA", {"lossless": True}, id="lossless webp"
        ),
        pytest.param("PNG", _side("PNG"), "RGBA", {}, id="png with alpha"),
        pytest.param("PNG", _side("PNG"), "LA", {}, id="grey png with alpha"),
        pytest.param(
            "JPEG",
            _side("JPEG_BUFFERED"),
            "CMYK",
            {"progressive": True},
            id="progressive cmyk jpeg",
        ),
        pytest.param(
            "JPEG", _ONE_PASS_SIDE, "RGB", {"subsampling": 0}, id="one-pass jpeg"
        ),
    ],
)
def test_a_decode_at_the_cap_stays_within_its_reservation(
    tmp_path, kind, side, mode, options
):
    path = tmp_path / f"cap.{kind.lower()}"
    Image.new(mode, (side, side), (90,) * len(mode)).save(path, kind, **options)

    result = subprocess.run(
        [sys.executable, "-c", _CHILD, str(path)],
        cwd=_BACKEND,
        env={**os.environ, "PYTHONPATH": str(_BACKEND)},
        capture_output=True,
        text=True,
        timeout=120,
        check=True,
    )
    used, reserved = map(int, result.stdout.split())
    # The measurement saw the decode at all.
    assert used > reserved // 4, (used, reserved)
    assert used <= reserved, (used, reserved)
