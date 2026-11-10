"""Image verification for map uploads runs off the event loop.

``verify_image_bytes`` is the small check the map thumbnail and social-card
uploads share: it runs Pillow's ``Image.verify()`` on the story decode
threads, so a large upload never blocks the event loop.
"""

from __future__ import annotations

import threading
from io import BytesIO

import pytest
from PIL import Image, UnidentifiedImageError

from app.modules.catalog.stories import images


def _png_bytes() -> bytes:
    buf = BytesIO()
    Image.new("RGB", (4, 4), color=(0, 0, 0)).save(buf, format="PNG")
    return buf.getvalue()


def _jpeg_bytes() -> bytes:
    buf = BytesIO()
    Image.new("RGB", (4, 4), color=(128, 64, 32)).save(buf, format="JPEG")
    return buf.getvalue()


async def test_verify_image_bytes_accepts_png_and_jpeg() -> None:
    await images.verify_image_bytes(_png_bytes())
    await images.verify_image_bytes(_jpeg_bytes())


async def test_verify_image_bytes_rejects_random_bytes() -> None:
    with pytest.raises((UnidentifiedImageError, OSError, SyntaxError, ValueError)):
        await images.verify_image_bytes(b"this is not an image" * 20)


async def test_verify_image_bytes_rejects_truncated_image() -> None:
    with pytest.raises((UnidentifiedImageError, OSError, SyntaxError, ValueError)):
        await images.verify_image_bytes(_png_bytes()[:10])
    with pytest.raises((UnidentifiedImageError, OSError, SyntaxError, ValueError)):
        await images.verify_image_bytes(_jpeg_bytes()[:20])


async def test_verify_image_bytes_runs_off_the_event_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The blocking Pillow call runs on a decode thread, not the loop thread."""
    seen_threads: set[int] = set()
    original = images._verify_image

    def _recording(data: bytes) -> None:
        seen_threads.add(threading.get_ident())
        original(data)

    monkeypatch.setattr(images, "_verify_image", _recording)
    await images.verify_image_bytes(_png_bytes())
    assert seen_threads, "verify did not run"
    assert threading.get_ident() not in seen_threads
