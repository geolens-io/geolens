"""Story image uploads: identify, bound and re-encode as WebP.

No database or storage access. The format comes from the file's leading
bytes, never its name or declared type, and only PNG, JPEG and WebP open.
Every cap is checked from the header before any pixel is decoded, so a small
file that claims a huge canvas is refused without allocating it.

Decoding is bounded per process. At most ``UPLOAD_SLOTS`` uploads are
handled at once, and each decode reserves its estimated peak memory from
``DECODE_BUDGET_BYTES`` first; either running out answers 503, so nothing
queues. One image at any format's cap fits the budget alone.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from dataclasses import dataclass
from io import BytesIO

from fastapi import HTTPException
from PIL import (
    Image,
    ImageCms,
    ImageOps,
    JpegImagePlugin,
    PngImagePlugin,
    WebPImagePlugin,
)

from app.core.async_io import await_draining

MAX_UPLOAD_BYTES = 50 * 1024 * 1024
MAX_JPEG_SIDE = 15_000
MAX_OUTPUT_SIDE = 2_400
UPLOAD_SLOTS = 2
# Production runs two API workers in 2 GB; this keeps each worker's decoding
# to an eighth of that.
DECODE_BUDGET_BYTES = 256 * 1024 * 1024
RETRY_AFTER_SECONDS = 5
_WEBP_QUALITY = 85

# Peak resident bytes per decoded pixel through decode_story_image, the worst
# measured case of each plus a margin: WebP holds the decoder's canvases
# beside the image, alpha is premultiplied in a full-size copy for resizing,
# and a progressive JPEG keeps every coefficient. A one-pass JPEG decodes at
# a reduced scale and is charged for the pixels it decodes, at most about
# 4,800 a side. test_story_image_memory measures each format at its cap.
BYTES_PER_PIXEL = {"WEBP": 32, "PNG": 20, "JPEG_BUFFERED": 16, "JPEG": 11}
MAX_PIXELS = {"WEBP": 8_000_000, "PNG": 12_000_000, "JPEG_BUFFERED": 16_000_000}

# Constructed directly rather than through Image.open, whose process-wide
# MAX_IMAGE_PIXELS check would refuse a JPEG this module decodes at a reduced
# scale; the caps above replace it.
_OPENERS = {
    "PNG": PngImagePlugin.PngImageFile,
    "JPEG": JpegImagePlugin.JpegImageFile,
    "WEBP": WebPImagePlugin.WebPImageFile,
}

# Sequential frames, Huffman or arithmetic coded.
_SEQUENTIAL_SOF = frozenset({0xC0, 0xC1, 0xC9})
_SOF = frozenset(range(0xC0, 0xD0)) - {0xC4, 0xC8, 0xCC}


@dataclass(frozen=True)
class StoryImage:
    data: bytes
    width: int
    height: int


@dataclass(frozen=True)
class DecodePlan:
    """What the header says: the format, its size, and the memory to reserve."""

    kind: str
    size: tuple[int, int]
    one_pass: bool
    cost: int


_upload_slots = asyncio.Semaphore(UPLOAD_SLOTS)
# Bytes reserved by running decodes. Only the event loop changes it.
_decode_reserved = 0
# Its own threads, so decodes never occupy the default pool that storage
# calls and DNS lookups share.
_decoder = ThreadPoolExecutor(
    max_workers=UPLOAD_SLOTS, thread_name_prefix="story-image"
)


def _refused(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status_code, detail={"code": code, "message": message}
    )


def _busy() -> HTTPException:
    return HTTPException(
        status_code=503,
        detail={
            "code": "story_image_busy",
            "message": "Other images are being processed. Try again shortly.",
        },
        headers={"Retry-After": str(RETRY_AFTER_SECONDS)},
    )


def _too_large(message: str) -> HTTPException:
    return _refused(413, "story_image_too_large", message)


def _unreadable() -> HTTPException:
    return _refused(400, "story_image_unreadable", "The file isn't a readable image.")


@asynccontextmanager
async def upload_slot() -> AsyncIterator[None]:
    """Hold one of the process's upload slots; 503 when none is free."""
    if _upload_slots.locked():
        raise _busy()
    async with _upload_slots:
        yield


def sniff_format(data: bytes) -> str | None:
    """PNG, JPEG or WEBP from the leading bytes; None for anything else."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "PNG"
    if data.startswith(b"\xff\xd8\xff"):
        return "JPEG"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "WEBP"
    return None


def _png_size(data: bytes) -> tuple[int, int] | None:
    if len(data) < 24 or data[12:16] != b"IHDR":
        return None
    return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")


def _webp_size(data: bytes) -> tuple[int, int] | None:
    """The canvas a WebP header declares. Pillow's opener allocates the
    canvas, so the cap has to be checked before it runs."""
    chunk = data[12:16]
    if chunk == b"VP8 " and len(data) >= 30 and data[23:26] == b"\x9d\x01\x2a":
        return (
            int.from_bytes(data[26:28], "little") & 0x3FFF,
            int.from_bytes(data[28:30], "little") & 0x3FFF,
        )
    if chunk == b"VP8X" and len(data) >= 30:
        return (
            int.from_bytes(data[24:27], "little") + 1,
            int.from_bytes(data[27:30], "little") + 1,
        )
    if chunk == b"VP8L" and len(data) >= 25 and data[20] == 0x2F:
        bits = int.from_bytes(data[21:25], "little")
        return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
    return None


def _jpeg_frame(data: bytes) -> tuple[tuple[int, int], bool] | None:
    """The frame size, and whether libjpeg decodes it in one pass.

    A sequential frame whose first scan carries every component decodes a
    row of blocks at a time. Anything else (progressive, or a first scan with
    fewer components) keeps the whole image's coefficients at full size,
    whatever the output scale. Segments are skipped by their length, as
    libjpeg skips them, so a thumbnail embedded in EXIF isn't read; anything
    unexpected after the frame header counts as not one pass.
    """
    frame = None
    i, end = 2, len(data)
    while i + 9 < end:
        if data[i] != 0xFF:
            break
        marker = data[i + 1]
        if marker == 0xFF:
            i += 1
            continue
        if marker == 0xDA:
            if frame is None:
                return None
            sof, size, components = frame
            return size, sof in _SEQUENTIAL_SOF and data[i + 4] == components
        if marker in _SOF:
            if frame is not None:
                break
            height = int.from_bytes(data[i + 5 : i + 7], "big")
            width = int.from_bytes(data[i + 7 : i + 9], "big")
            frame = (marker, (width, height), data[i + 9])
        elif marker in (0x01, 0xD8, 0xD9) or 0xD0 <= marker <= 0xD7:
            break
        i += 2 + int.from_bytes(data[i + 2 : i + 4], "big")
    return None if frame is None else (frame[1], False)


def _fit(size: tuple[int, int]) -> tuple[int, int]:
    width, height = size
    scale = min(1.0, MAX_OUTPUT_SIDE / max(width, height))
    return max(1, round(width * scale)), max(1, round(height * scale))


def _draft_pixels(size: tuple[int, int]) -> int:
    """The pixels a one-pass JPEG decodes at, as Pillow's draft picks the scale."""
    target = _fit(size)
    ratio = min(size[0] // target[0], size[1] // target[1])
    scale = next((s for s in (8, 4, 2) if ratio >= s), 1)
    return -(-size[0] // scale) * -(-size[1] // scale)


def plan_story_image(data: bytes) -> DecodePlan:
    """Check an upload's format and caps from its header alone.

    Raises ``HTTPException``: 413 over a cap, 415 for anything but PNG, JPEG
    and WebP, 400 for a header that doesn't parse.
    """
    if len(data) > MAX_UPLOAD_BYTES:
        raise _too_large(f"Images can be at most {MAX_UPLOAD_BYTES // 2**20} MB.")
    kind = sniff_format(data)
    if kind is None:
        raise _refused(
            415,
            "story_image_unsupported",
            "Only PNG, JPEG and WebP images can be uploaded.",
        )
    one_pass = False
    if kind == "JPEG":
        size, one_pass = _jpeg_frame(data) or ((0, 0), False)
    else:
        size = (_png_size if kind == "PNG" else _webp_size)(data) or (0, 0)
    if min(size) < 1:
        raise _unreadable()
    if kind == "JPEG" and max(size) > MAX_JPEG_SIDE:
        raise _too_large(
            f"JPEG images can be at most {MAX_JPEG_SIDE:,} pixels on a side."
        )
    if kind == "JPEG" and one_pass:
        cost = BYTES_PER_PIXEL["JPEG"] * _draft_pixels(size)
    else:
        weight = "JPEG_BUFFERED" if kind == "JPEG" else kind
        if size[0] * size[1] > MAX_PIXELS[weight]:
            raise _too_large(
                f"This image has {size[0] * size[1]:,} pixels; the most it can "
                f"have is {MAX_PIXELS[weight]:,}."
            )
        cost = BYTES_PER_PIXEL[weight] * size[0] * size[1]
    return DecodePlan(kind, size, one_pass, cost)


def _to_srgb(image: Image.Image, profile: bytes) -> Image.Image:
    """Convert from the embedded colour profile to sRGB; a profile that doesn't
    load or doesn't fit the pixels leaves them as they are."""
    mode = "RGBA" if image.mode == "RGBA" else "RGB"
    try:
        return ImageCms.profileToProfile(
            image,
            ImageCms.ImageCmsProfile(BytesIO(profile)),
            ImageCms.createProfile("sRGB"),
            outputMode=mode,
        )
    except (ImageCms.PyCMSError, OSError, ValueError, TypeError):
        return image


def _to_webp(image: Image.Image) -> StoryImage:
    profile = image.info.get("icc_profile")
    if image.mode not in ("RGB", "RGBA", "CMYK"):
        converted = image.convert("RGBA" if image.has_transparency_data else "RGB")
        # Free the source's pixels before resizing; the budget charges the peak.
        image.close()
        image = converted
    image.thumbnail((MAX_OUTPUT_SIDE, MAX_OUTPUT_SIDE), Image.Resampling.LANCZOS)
    ImageOps.exif_transpose(image, in_place=True)
    if profile:
        image = _to_srgb(image, profile)
    if image.mode == "CMYK":
        image = image.convert("RGB")
    out = BytesIO()
    # Nothing from the source's info (EXIF, XMP, ICC) is passed on.
    image.save(out, "WEBP", quality=_WEBP_QUALITY)
    return StoryImage(out.getvalue(), image.width, image.height)


def decode_story_image(data: bytes, plan: DecodePlan) -> StoryImage:
    """Re-encode an upload as sRGB WebP at most MAX_OUTPUT_SIDE a side,
    without its metadata and turned upright by its EXIF orientation.

    Blocking. Raises ``HTTPException``.
    """
    try:
        with _OPENERS[plan.kind](BytesIO(data)) as image:
            # The reservation was sized from this module's header read.
            if image.size != plan.size:
                raise _unreadable()
            if plan.one_pass:
                image.draft(None, _fit(image.size))
                if image.size[0] * image.size[1] > _draft_pixels(plan.size):
                    raise _unreadable()
            image.load()
            return _to_webp(image)
    except HTTPException:
        raise
    except Exception as exc:  # broad: Pillow decoders raise many types
        raise _unreadable() from exc


async def prepare_story_image(data: bytes) -> StoryImage:
    """Plan, reserve memory for and decode an upload on the decode threads.

    Raises ``HTTPException``, 503 when the decode budget is spent. A
    cancelled caller waits for its decode to finish, so the reservation
    covers the memory until the thread lets it go.
    """
    global _decode_reserved
    plan = plan_story_image(data)
    if _decode_reserved + plan.cost > DECODE_BUDGET_BYTES:
        raise _busy()
    _decode_reserved += plan.cost
    try:
        loop = asyncio.get_running_loop()
        return await await_draining(
            loop.run_in_executor(_decoder, decode_story_image, data, plan)
        )
    finally:
        _decode_reserved -= plan.cost
