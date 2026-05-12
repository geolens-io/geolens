"""Sprite-backed icon asset helpers for map symbols."""

from __future__ import annotations

import asyncio
import re
import struct
import uuid
import xml.etree.ElementTree as _stdlib_ET
import zlib
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from xml.etree.ElementTree import Element

from defusedxml import ElementTree
from defusedxml.ElementTree import fromstring, tostring
from PIL import Image, ImageColor, ImageDraw, UnidentifiedImageError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalog.maps.models import MapIconAsset
from app.modules.catalog.maps.schemas import MapIconResponse
from app.platform.storage import get_storage

# SEC-09: register the SVG namespace as the empty prefix so re-serialized SVGs
# emit `<svg xmlns="...">` rather than `<ns0:svg xmlns:ns0="...">`. This keeps
# the active-content denylist (`<script`, `<foreignobject`) effective on the
# canonical bytes — without this, `<script>` would re-serialize to `<ns0:script>`
# and slip past byte-match checks. Registering once at import time is safe;
# stdlib ElementTree namespace registration is process-global.
_stdlib_ET.register_namespace("", "http://www.w3.org/2000/svg")

MAX_ICON_BYTES = 512 * 1024
SUPPORTED_MEDIA_TYPES = {"image/svg+xml": ".svg", "image/png": ".png"}

_SLUG_RE = re.compile(r"[^a-z0-9_-]+")
_SVG_NS_RE = re.compile(r"^\{.*\}")
_PATH_TOKEN_RE = re.compile(
    r"[MmZzLlHhVvCcQqSsTtAa]|[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?"
)
SPRITE_CELL_SIZE = 24


@dataclass(frozen=True)
class BuiltinIcon:
    slug: str
    name: str
    media_type: str
    content: bytes


SpriteIndex = dict[str, dict[str, int | float | bool]]
SpriteSignature = tuple[tuple[str, str, str, int | None], ...]


@dataclass(frozen=True)
class SpriteIndexCache:
    signature: SpriteSignature
    index: SpriteIndex


@dataclass(frozen=True)
class SpritePngCache:
    signature: SpriteSignature
    png: bytes


DEFAULT_ICONS = (
    BuiltinIcon(
        slug="marker",
        name="Marker",
        media_type="image/svg+xml",
        content=b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path fill="#2563eb" d="M12 2a7 7 0 0 0-7 7c0 5.25 7 13 7 13s7-7.75 7-13a7 7 0 0 0-7-7Zm0 9.5A2.5 2.5 0 1 1 12 6a2.5 2.5 0 0 1 0 5.5Z"/></svg>',
    ),
    BuiltinIcon(
        slug="circle-dot",
        name="Circle dot",
        media_type="image/svg+xml",
        content=b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><circle fill="#0f766e" cx="12" cy="12" r="8"/><circle fill="#fff" cx="12" cy="12" r="3"/></svg>',
    ),
    BuiltinIcon(
        slug="arrow-right",
        name="Arrow right",
        media_type="image/svg+xml",
        content=b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path fill="#111827" d="M4 9h10V5l7 7-7 7v-4H4z"/></svg>',
    ),
)

_sprite_cache_lock = asyncio.Lock()
_sprite_index_cache: SpriteIndexCache | None = None
_sprite_png_cache: SpritePngCache | None = None


def clear_sprite_cache() -> None:
    """Clear process-local sprite caches after icon catalog writes."""

    global _sprite_index_cache, _sprite_png_cache
    _sprite_index_cache = None
    _sprite_png_cache = None


def _sprite_signature(icons: list[MapIconResponse]) -> SpriteSignature:
    return tuple(
        (icon.id, icon.sprite_id, icon.media_type, icon.size_bytes) for icon in icons
    )


def _copy_sprite_index(index: SpriteIndex) -> SpriteIndex:
    return {key: dict(value) for key, value in index.items()}


def slugify_icon_name(name: str) -> str:
    stem = Path(name).stem.lower().strip()
    slug = _SLUG_RE.sub("-", stem).strip("-")
    return slug or "icon"


def _media_type_from_upload(filename: str | None, content_type: str | None) -> str:
    normalized = (content_type or "").split(";")[0].strip().lower()
    suffix = Path(filename or "").suffix.lower()
    if normalized in SUPPORTED_MEDIA_TYPES:
        return normalized
    if suffix == ".svg":
        return "image/svg+xml"
    if suffix == ".png":
        return "image/png"
    raise ValueError("Only SVG and PNG icons are supported")


def validate_icon_upload(
    filename: str | None,
    content_type: str | None,
    content: bytes,
) -> tuple[str, str, bytes]:
    """Validate an icon upload. Returns (slug, media_type, sanitized_content).

    For SVG uploads, ``sanitized_content`` is the defusedxml-re-serialized form
    of the input — this normalizes entity encodings (``&lt;script&gt;`` → text,
    ``&#106;avascript:`` → ``javascript:``) BEFORE the active-content denylist
    runs, defeating attribute-encoding bypasses (SEC-09 / M-71). Callers MUST
    persist ``sanitized_content``, not the original upload bytes.

    For PNG uploads, ``sanitized_content`` is the original bytes unchanged.
    """
    if not content:
        raise ValueError("Icon file is empty")
    if len(content) > MAX_ICON_BYTES:
        raise ValueError("Icon file is too large")
    media_type = _media_type_from_upload(filename, content_type)
    if media_type == "image/png":
        try:
            Image.open(BytesIO(content)).verify()
        except (UnidentifiedImageError, OSError, SyntaxError):
            raise ValueError("PNG icon content is invalid")
    if media_type == "image/svg+xml":
        prefix = content[:512].lower()
        if b"<svg" not in prefix:
            raise ValueError("SVG icon content is invalid")

        # SEC-09 / M-71: re-serialize via defusedxml so entity-encoded payloads
        # like &#106;avascript: in attributes are normalized into canonical
        # bytes BEFORE the denylist matches. The SVG namespace is registered
        # as the empty prefix at module import time so the round-trip emits
        # `<svg xmlns="...">` (and child tags un-prefixed) — required for the
        # denylist below to keep matching `<script`, `<foreignobject`, etc.
        # Note: text content like &lt;script&gt; remains entity-encoded after
        # round-trip — the CSP `default-src 'none'; sandbox` header on the icon
        # GET response (SEC-01) is the second defense layer for that case.
        try:
            root = fromstring(content)
        except Exception as exc:  # broad: lxml fromstring can throw varied parser errors on malformed SVG; map to ValueError
            raise ValueError("SVG icon content is invalid") from exc
        sanitized = tostring(root, encoding="utf-8")

        lower = sanitized.lower()
        if (
            b"<script" in lower
            or b"<foreignobject" in lower
            or b"javascript:" in lower
            or re.search(rb"\son[a-z]+\s*=", lower)
        ):
            raise ValueError("SVG icons cannot contain active content")
        # downstream callers persist the canonical form, not the raw upload
        content = sanitized
    return slugify_icon_name(filename or "icon"), media_type, content


def icon_url(icon_id: str) -> str:
    return f"/maps/icons/{icon_id}/asset"


def _builtin_response(icon: BuiltinIcon) -> MapIconResponse:
    return MapIconResponse(
        id=f"builtin:{icon.slug}",
        name=icon.name,
        slug=icon.slug,
        media_type=icon.media_type,
        url=f"/maps/icons/builtin:{icon.slug}/asset",
        sprite_id=icon.slug,
        size_bytes=len(icon.content),
        builtin=True,
    )


def _asset_response(asset: MapIconAsset) -> MapIconResponse:
    return MapIconResponse(
        id=str(asset.id),
        name=asset.name,
        slug=asset.slug,
        media_type=asset.media_type,
        url=icon_url(str(asset.id)),
        sprite_id=asset.slug,
        size_bytes=asset.size_bytes,
        builtin=False,
    )


async def list_icons(session: AsyncSession) -> list[MapIconResponse]:
    result = await session.execute(select(MapIconAsset).order_by(MapIconAsset.name))
    uploaded = [_asset_response(asset) for asset in result.scalars().all()]
    return [_builtin_response(icon) for icon in DEFAULT_ICONS] + uploaded


async def create_icon_asset(
    session: AsyncSession,
    *,
    filename: str | None,
    content_type: str | None,
    content: bytes,
    created_by: uuid.UUID | None,
) -> MapIconAsset:
    base_slug, media_type, sanitized_content = validate_icon_upload(
        filename, content_type, content
    )
    icon_id = uuid.uuid4()
    extension = SUPPORTED_MEDIA_TYPES[media_type]
    slug = f"{base_slug}-{str(icon_id)[:8]}"
    storage_key = f"maps/icons/{icon_id}{extension}"
    # Persist the sanitized form so the bytes on disk match what validation
    # accepted (SEC-09). For PNG this is the original bytes unchanged.
    await get_storage().put(storage_key, sanitized_content)
    asset = MapIconAsset(
        id=icon_id,
        name=Path(filename or "Icon").stem or "Icon",
        slug=slug,
        media_type=media_type,
        storage_key=storage_key,
        size_bytes=len(sanitized_content),
        created_by=created_by,
    )
    session.add(asset)
    await session.flush()
    clear_sprite_cache()
    return asset


async def get_icon_content(
    session: AsyncSession,
    icon_id: str,
) -> tuple[bytes, str] | None:
    if icon_id.startswith("builtin:"):
        slug = icon_id.split(":", 1)[1]
        for icon in DEFAULT_ICONS:
            if icon.slug == slug:
                return icon.content, icon.media_type
        return None
    try:
        asset_id = uuid.UUID(icon_id)
    except ValueError:
        return None
    asset = await session.get(MapIconAsset, asset_id)
    if asset is None:
        return None
    return await get_storage().get(asset.storage_key), asset.media_type


def _png_chunk(kind: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + kind
        + data
        + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    )


def _blank_png(width: int, height: int = SPRITE_CELL_SIZE) -> bytes:
    width = max(width, 1)
    raw_rows = b"".join(b"\x00" + (b"\x00\x00\x00\x00" * width) for _ in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
        + _png_chunk(b"IDAT", zlib.compress(raw_rows))
        + _png_chunk(b"IEND", b"")
    )


def _local_name(element: Element) -> str:
    return _SVG_NS_RE.sub("", element.tag).lower()


def _float_attr(element: Element, name: str, default: float = 0) -> float:
    raw = element.attrib.get(name)
    if raw is None:
        return default
    match = re.match(r"[-+]?(?:\d*\.\d+|\d+\.?)", raw.strip())
    return float(match.group(0)) if match else default


def _svg_viewbox(root: Element) -> tuple[float, float, float, float]:
    viewbox = root.attrib.get("viewBox") or root.attrib.get("viewbox")
    if viewbox:
        parts = [float(part) for part in re.split(r"[\s,]+", viewbox.strip()) if part]
        if len(parts) == 4 and parts[2] > 0 and parts[3] > 0:
            return parts[0], parts[1], parts[2], parts[3]
    width = _float_attr(root, "width", SPRITE_CELL_SIZE) or SPRITE_CELL_SIZE
    height = _float_attr(root, "height", SPRITE_CELL_SIZE) or SPRITE_CELL_SIZE
    return 0, 0, width, height


def _parse_color(
    raw: str | None, default: str | None = None
) -> tuple[int, int, int, int] | None:
    value = (raw or default or "").strip()
    if not value or value == "none":
        return None
    if value == "currentColor":
        value = "#111827"
    try:
        rgb = ImageColor.getrgb(value)
    except ValueError:
        return None
    if len(rgb) == 4:
        return rgb
    return (*rgb, 255)


def _style_value(element: Element, key: str) -> str | None:
    if key in element.attrib:
        return element.attrib[key]
    style = element.attrib.get("style", "")
    for part in style.split(";"):
        if ":" not in part:
            continue
        name, value = part.split(":", 1)
        if name.strip() == key:
            return value.strip()
    return None


def _point(
    x: float,
    y: float,
    viewbox: tuple[float, float, float, float],
) -> tuple[float, float]:
    min_x, min_y, width, height = viewbox
    scale = min(SPRITE_CELL_SIZE / width, SPRITE_CELL_SIZE / height)
    offset_x = (SPRITE_CELL_SIZE - width * scale) / 2
    offset_y = (SPRITE_CELL_SIZE - height * scale) / 2
    return ((x - min_x) * scale + offset_x, (y - min_y) * scale + offset_y)


def _path_points(path_data: str) -> list[list[tuple[float, float]]]:
    tokens = _PATH_TOKEN_RE.findall(path_data.replace(",", " "))
    paths: list[list[tuple[float, float]]] = []
    current: list[tuple[float, float]] = []
    cmd = ""
    index = 0
    x = y = start_x = start_y = 0.0

    def is_cmd(value: str) -> bool:
        return len(value) == 1 and value.isalpha()

    def number() -> float:
        nonlocal index
        value = float(tokens[index])
        index += 1
        return value

    def add_point(px: float, py: float) -> None:
        nonlocal x, y
        x, y = px, py
        current.append((x, y))

    while index < len(tokens):
        if is_cmd(tokens[index]):
            cmd = tokens[index]
            index += 1
        if not cmd:
            break
        absolute = cmd.isupper()
        op = cmd.upper()
        if op == "M":
            if current:
                paths.append(current)
            current = []
            x1, y1 = number(), number()
            if not absolute:
                x1 += x
                y1 += y
            add_point(x1, y1)
            start_x, start_y = x, y
            cmd = "L" if absolute else "l"
        elif op == "L":
            x1, y1 = number(), number()
            add_point(x1 if absolute else x + x1, y1 if absolute else y + y1)
        elif op == "H":
            x1 = number()
            add_point(x1 if absolute else x + x1, y)
        elif op == "V":
            y1 = number()
            add_point(x, y1 if absolute else y + y1)
        elif op in {"C", "S", "Q", "T", "A"}:
            # Approximate curves and arcs by their endpoint. This keeps uploaded
            # SVG icons visible without depending on native Cairo bindings.
            needed = {"C": 6, "S": 4, "Q": 4, "T": 2, "A": 7}[op]
            values = [number() for _ in range(needed)]
            x1, y1 = values[-2], values[-1]
            add_point(x1 if absolute else x + x1, y1 if absolute else y + y1)
        elif op == "Z":
            if current:
                current.append((start_x, start_y))
                paths.append(current)
            current = []
        else:
            break
    if current:
        paths.append(current)
    return paths


def _draw_svg_element(
    draw: ImageDraw.ImageDraw,
    element: Element,
    viewbox: tuple[float, float, float, float],
    inherited_fill: str | None = "#111827",
) -> None:
    name = _local_name(element)
    fill_raw = _style_value(element, "fill") or inherited_fill
    stroke_raw = _style_value(element, "stroke")
    fill = _parse_color(fill_raw)
    stroke = _parse_color(stroke_raw)
    stroke_width = max(_float_attr(element, "stroke-width", 1), 1)

    if name == "circle":
        cx = _float_attr(element, "cx")
        cy = _float_attr(element, "cy")
        radius = _float_attr(element, "r")
        x0, y0 = _point(cx - radius, cy - radius, viewbox)
        x1, y1 = _point(cx + radius, cy + radius, viewbox)
        draw.ellipse(
            (x0, y0, x1, y1), fill=fill, outline=stroke, width=int(stroke_width)
        )
    elif name in {"rect", "svg"} and name != "svg":
        x0 = _float_attr(element, "x")
        y0 = _float_attr(element, "y")
        x1 = x0 + _float_attr(element, "width")
        y1 = y0 + _float_attr(element, "height")
        draw.rectangle(
            (*_point(x0, y0, viewbox), *_point(x1, y1, viewbox)),
            fill=fill,
            outline=stroke,
            width=int(stroke_width),
        )
    elif name in {"polygon", "polyline"}:
        raw_points = element.attrib.get("points", "")
        nums = [float(part) for part in re.split(r"[\s,]+", raw_points.strip()) if part]
        points = [
            _point(nums[i], nums[i + 1], viewbox) for i in range(0, len(nums) - 1, 2)
        ]
        if len(points) >= 2:
            if name == "polygon":
                draw.polygon(points, fill=fill)
            if stroke:
                draw.line(
                    points + ([points[0]] if name == "polygon" else []),
                    fill=stroke,
                    width=int(stroke_width),
                    joint="curve",
                )
    elif name == "line":
        x1 = _float_attr(element, "x1")
        y1 = _float_attr(element, "y1")
        x2 = _float_attr(element, "x2")
        y2 = _float_attr(element, "y2")
        draw.line(
            (_point(x1, y1, viewbox), _point(x2, y2, viewbox)),
            fill=stroke or fill,
            width=int(stroke_width),
        )
    elif name == "path":
        for path in _path_points(element.attrib.get("d", "")):
            points = [_point(px, py, viewbox) for px, py in path]
            if len(points) >= 3 and fill:
                draw.polygon(points, fill=fill)
            if len(points) >= 2 and stroke:
                draw.line(points, fill=stroke, width=int(stroke_width), joint="curve")

    next_fill = _style_value(element, "fill") or inherited_fill
    for child in element:
        _draw_svg_element(draw, child, viewbox, next_fill)


def _placeholder_icon(seed: str) -> Image.Image:
    image = Image.new("RGBA", (SPRITE_CELL_SIZE, SPRITE_CELL_SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    color = "#" + f"{abs(hash(seed)) & 0xFFFFFF:06x}"
    draw.rounded_rectangle((3, 3, 21, 21), radius=5, fill=color)
    return image


def _render_icon(content: bytes, media_type: str, seed: str) -> Image.Image:
    try:
        if media_type == "image/png":
            source = Image.open(BytesIO(content)).convert("RGBA")
        else:
            root = ElementTree.fromstring(content)
            source = Image.new(
                "RGBA", (SPRITE_CELL_SIZE, SPRITE_CELL_SIZE), (0, 0, 0, 0)
            )
            draw = ImageDraw.Draw(source)
            _draw_svg_element(draw, root, _svg_viewbox(root))
    except (
        ElementTree.ParseError,
        UnidentifiedImageError,
        OSError,
        ValueError,
        IndexError,
        SyntaxError,
    ):
        return _placeholder_icon(seed)

    source.thumbnail((SPRITE_CELL_SIZE, SPRITE_CELL_SIZE), Image.Resampling.LANCZOS)
    cell = Image.new("RGBA", (SPRITE_CELL_SIZE, SPRITE_CELL_SIZE), (0, 0, 0, 0))
    cell.alpha_composite(
        source,
        (
            (SPRITE_CELL_SIZE - source.width) // 2,
            (SPRITE_CELL_SIZE - source.height) // 2,
        ),
    )
    return cell


async def build_sprite_index(
    session: AsyncSession,
) -> SpriteIndex:
    global _sprite_index_cache

    icons = await list_icons(session)
    signature = _sprite_signature(icons)
    if _sprite_index_cache is not None and _sprite_index_cache.signature == signature:
        return _copy_sprite_index(_sprite_index_cache.index)

    async with _sprite_cache_lock:
        if (
            _sprite_index_cache is not None
            and _sprite_index_cache.signature == signature
        ):
            return _copy_sprite_index(_sprite_index_cache.index)
        index = _build_sprite_index(icons)
        _sprite_index_cache = SpriteIndexCache(
            signature=signature,
            index=_copy_sprite_index(index),
        )
        return index


def _build_sprite_index(icons: list[MapIconResponse]) -> SpriteIndex:
    index: SpriteIndex = {}
    for offset, icon in enumerate(icons):
        entry: dict[str, int | float | bool] = {
            "x": offset * SPRITE_CELL_SIZE,
            "y": 0,
            "width": SPRITE_CELL_SIZE,
            "height": SPRITE_CELL_SIZE,
            "pixelRatio": 1,
        }
        if icon.builtin and icon.sprite_id == "arrow-right":
            entry["sdf"] = True
        index[icon.sprite_id] = entry
    return index


async def build_sprite_png(session: AsyncSession) -> bytes:
    global _sprite_index_cache, _sprite_png_cache

    icons = await list_icons(session)
    signature = _sprite_signature(icons)
    if _sprite_png_cache is not None and _sprite_png_cache.signature == signature:
        return _sprite_png_cache.png

    async with _sprite_cache_lock:
        if _sprite_png_cache is not None and _sprite_png_cache.signature == signature:
            return _sprite_png_cache.png
        png = await _render_sprite_png(session, icons)
        _sprite_index_cache = SpriteIndexCache(
            signature=signature,
            index=_build_sprite_index(icons),
        )
        _sprite_png_cache = SpritePngCache(signature=signature, png=png)
        return png


async def _render_sprite_png(
    session: AsyncSession, icons: list[MapIconResponse]
) -> bytes:
    if not icons:
        return _blank_png(SPRITE_CELL_SIZE)
    sheet = Image.new(
        "RGBA",
        (len(icons) * SPRITE_CELL_SIZE, SPRITE_CELL_SIZE),
        (0, 0, 0, 0),
    )
    for index, icon in enumerate(icons):
        content = await get_icon_content(session, icon.id)
        if content is None:
            image = _placeholder_icon(icon.sprite_id)
        else:
            image = _render_icon(content[0], content[1], icon.sprite_id)
        sheet.alpha_composite(image, (index * SPRITE_CELL_SIZE, 0))
    out = BytesIO()
    sheet.save(out, format="PNG")
    return out.getvalue()
