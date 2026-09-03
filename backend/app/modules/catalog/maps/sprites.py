"""Sprite-backed icon asset helpers for map symbols.

# builder-audit #338 STYLE-05: this module contains a hand-rolled SVG path
# parser (``_path_points``) and rasterizer (``_draw_svg_element``) that turn
# uploaded/built-in SVG icons into a server-side PNG sprite sheet. This is a
# DELIBERATE no-native-dependency tradeoff: it avoids pulling in a native
# Cairo binding (e.g. cairosvg/pycairo) which would complicate the build and
# container image pre-release. The known limitation is that bezier and arc
# path commands (C/S/Q/T/A) are approximated by their endpoint only (see
# ``_path_points``), so curved icons render as polygonal/straight segments in
# the sprite sheet rather than smooth curves. This is acceptable for the small
# 24px sprite cells used here. The approximation behavior is pinned by the
# deterministic golden-image tests in ``backend/tests/test_map_sprites.py``
# (``test_path_points_*`` / ``test_render_icon_*``) so it cannot silently
# regress; do not "fix" the curves without updating those tests.
"""

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

from app.core.async_io import run_in_thread_draining
from app.modules.catalog.maps.models import MapIconAsset
from app.modules.catalog.maps.service import MapAssetPublication
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
# fix(#1428): compressed size says nothing about decoded size — a 9000x9000 PNG
# is ~79 KiB on the wire, inside MAX_ICON_BYTES, and ~320 MB once decoded into a
# 24px cell. Two caps bound that, and they are deliberately different numbers
# because they answer different questions:
#
#   MAX_ICON_DIMENSION is a PRODUCT bound, on what may be uploaded from here on.
#   1024 is far more than a sprite cell (24px, 48 at @2x) can show, so it costs
#   a new icon nothing and holds its decode to ~4 MiB.
#
#   MAX_RENDER_PIXELS is a MEMORY bound, on what is ALREADY stored — where the
#   upload cap gets no say, since those rows predate it. Re-using the upload cap
#   at render would blank icons that draw correctly on maps today, so this one
#   is set by what a single decode may cost instead: 24M px is ~96 MB of RGBA,
#   and decodes are sequential within a batch, so it bounds the peak. Anything
#   plausible (~4900px square, or any shape under that area) still renders its
#   real art; only DoS-scale artifacts degrade to the placeholder.
#
# Area rather than dimensions, because cost tracks area: a 12000x160 strip is
# 1.9M px and cheaper to decode than a 2048 square.
MAX_ICON_DIMENSION = 1024
MAX_RENDER_PIXELS = 24_000_000
SUPPORTED_MEDIA_TYPES = {"image/svg+xml": ".svg", "image/png": ".png"}

_SLUG_RE = re.compile(r"[^a-z0-9_-]+")
_SVG_NS_RE = re.compile(r"^\{.*\}")
_PATH_TOKEN_RE = re.compile(
    r"[MmZzLlHhVvCcQqSsTtAa]|[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?"
)
SPRITE_CELL_SIZE = 24
# fix(#1428 codex r1): how many icons the sheet render holds in flight at once —
# it bounds both the concurrent storage reads and the icon bytes resident while
# they are composited. The catalog has no size limit, so this cannot be "all of
# them": 8 icons at MAX_ICON_BYTES is 4 MiB, and still 8x the serial read it
# replaced.
_SPRITE_RENDER_BATCH = 8


@dataclass(frozen=True)
class BuiltinIcon:
    slug: str
    name: str
    media_type: str
    content: bytes


SpriteIndex = dict[str, dict[str, int | float | bool]]
SpriteSignature = tuple[tuple[str, str, str, int | None], ...]
# One (content, media_type) per catalog icon, positionally aligned; None where
# the icon no longer resolves and the sheet draws a placeholder instead.
IconPayloads = list[tuple[bytes, str] | None]


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
        # fix(#1428): verify() consumes the image object, so read .size first.
        # Image.open is lazy — that costs an IHDR parse and no pixel decode.
        try:
            image = Image.open(BytesIO(content))
            width, height = image.size
            image.verify()
        except Image.DecompressionBombError as exc:
            # PIL raises this from open() on absurd IHDR dimensions. That is an
            # oversized icon, not a corrupt one, and it used to escape as a 500.
            raise ValueError("PNG icon dimensions are too large") from exc
        except (UnidentifiedImageError, OSError, IndexError, SyntaxError) as exc:
            # IndexError: verify() indexes the chunk list on a PNG with no IDAT.
            raise ValueError("PNG icon content is invalid") from exc
        if max(width, height) > MAX_ICON_DIMENSION:
            raise ValueError("PNG icon dimensions are too large")
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


async def _load_icon_catalog(
    session: AsyncSession,
) -> tuple[list[MapIconResponse], list[MapIconAsset]]:
    """The icon catalog, as sprite responses plus the uploaded rows behind them.

    fix(#1428 codex r2): the sheet render needs those rows to reach storage, and
    this is the query that already loads all of them. Re-reading them by id cost
    a second query that grew a bind parameter per icon — past 32k uploads that
    is more parameters than the driver accepts, on a route that takes no auth.
    """
    result = await session.execute(select(MapIconAsset).order_by(MapIconAsset.name))
    uploaded = list(result.scalars().all())
    icons = [_builtin_response(icon) for icon in DEFAULT_ICONS]
    icons += [_asset_response(asset) for asset in uploaded]
    return icons, uploaded


async def list_icons(session: AsyncSession) -> list[MapIconResponse]:
    icons, _uploaded = await _load_icon_catalog(session)
    return icons


async def create_icon_asset(
    session: AsyncSession,
    *,
    filename: str | None,
    content_type: str | None,
    content: bytes,
    created_by: uuid.UUID | None,
    publication: MapAssetPublication | None = None,
) -> MapIconAsset:
    """Store one uploaded icon and the row that names it.

    fix(#1778 round 4): ``publication`` is the rollback ledger from
    ``map_asset_publication``. This is the third write-object-then-commit-row
    site in the package, and the one whose commit is not here: the row is only
    flushed below, and the route commits afterwards, so a failure in either step
    would leave the icon bytes behind with no row naming them. The caller opens
    the publication and this function records the key it wrote, because the key
    is derived here and the commit happens there.

    The key recorded is the physical one, which for icons is the logical one:
    they are deliberately global rather than tenant-resolved, for the reasons
    the comment below the slug gives.
    """
    base_slug, media_type, sanitized_content = validate_icon_upload(
        filename, content_type, content
    )
    icon_id = uuid.uuid4()
    extension = SUPPORTED_MEDIA_TYPES[media_type]
    slug = f"{base_slug}-{str(icon_id)[:8]}"
    # fix(#1621): this key is DELIBERATELY global. It stays outside the
    # tenants/<id>/ prefix that maps/thumbnails/ and maps/og-images/ resolve
    # into through resolve_current_storage_key, because the bytes have to
    # follow the rows and the rows are fleet-wide: catalog.map_icon_assets
    # carries no tenant_id, has no RLS policy, appears in no tenant-adoption
    # SQL, and its slug uniqueness is deployment-global (models.py). Every
    # tenant's anonymous sprite request loads that one catalog, and the sheet
    # cache is process-global to match.
    #
    # Resolving this key per tenant writes an icon under the uploader's prefix
    # that no other tenant can read, so the next cold sprite build for any
    # other tenant raises FileNotFoundError and 500s an unauthenticated route.
    # Making icons per-tenant means moving the ROWS first: tenant_id, an RLS
    # policy, per-tenant slug uniqueness, and a per-tenant sheet cache. Until
    # that happens the bytes belong at the bucket root, and
    # test_map_sprites.py::test_icon_storage_keys_stay_global_under_tenant_context
    # fails if anyone reroutes them.
    storage_key = f"maps/icons/{icon_id}{extension}"
    # Persist the sanitized form so the bytes on disk match what validation
    # accepted (SEC-09). For PNG this is the original bytes unchanged.
    await get_storage().put(storage_key, sanitized_content)
    if publication is not None:
        publication.record(storage_key)
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
    # builder-audit #338 STYLE-05: hand-rolled SVG path tokenizer/state machine,
    # deliberately kept dependency-free (no native Cairo). Curve/arc commands
    # (C/S/Q/T/A) are collapsed to their endpoint below — a documented fidelity
    # tradeoff. The exact polyline output is pinned by golden tests in
    # backend/tests/test_map_sprites.py so the approximation cannot drift.
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
            # builder-audit #338 STYLE-05: approximate curves and arcs by their
            # endpoint. This keeps uploaded SVG icons visible without depending
            # on native Cairo bindings (deliberate no-native-dep tradeoff).
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
            source = Image.open(BytesIO(content))
            # fix(#1428 codex r4): .size comes off the header — convert() is what
            # allocates. Refuse in between, so a stored artifact never reaches
            # the decode. This is the gate for everything between the bound and
            # Pillow's own bomb threshold, which sits ~7x higher.
            if source.width * source.height > MAX_RENDER_PIXELS:
                return _placeholder_icon(seed)
            source = source.convert("RGBA")
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
        # fix(#1428): past ~179M px Pillow refuses from open() itself, before
        # the MAX_RENDER_PIXELS check above can measure anything. Degrade that
        # cell too, rather than 500 the whole sprite sheet.
        Image.DecompressionBombError,
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

    icons, uploaded = await _load_icon_catalog(session)
    signature = _sprite_signature(icons)
    if _sprite_png_cache is not None and _sprite_png_cache.signature == signature:
        return _sprite_png_cache.png

    async with _sprite_cache_lock:
        if _sprite_png_cache is not None and _sprite_png_cache.signature == signature:
            return _sprite_png_cache.png
        png = await _render_sprite_png(icons, uploaded)
        _sprite_index_cache = SpriteIndexCache(
            signature=signature,
            index=_build_sprite_index(icons),
        )
        _sprite_png_cache = SpritePngCache(signature=signature, png=png)
        return png


async def _load_icon_payloads(
    icons: list[MapIconResponse], assets: dict[str, MapIconAsset]
) -> IconPayloads:
    """Read one batch of icons' bytes, fetching the stored ones concurrently."""
    builtin_icons = {icon.slug: icon for icon in DEFAULT_ICONS}
    payloads: IconPayloads = [None] * len(icons)
    stored: list[tuple[int, MapIconAsset]] = []
    for position, icon in enumerate(icons):
        if icon.builtin:
            builtin = builtin_icons.get(icon.sprite_id)
            if builtin is not None:
                payloads[position] = (builtin.content, builtin.media_type)
            continue
        asset = assets.get(icon.id)
        if asset is not None:
            stored.append((position, asset))

    if stored:
        storage = get_storage()
        # return_exceptions so a failing read cannot leave its siblings running
        # unretrieved; the first failure is re-raised, as the serial loop did.
        blobs = await asyncio.gather(
            *(storage.get(asset.storage_key) for _, asset in stored),
            return_exceptions=True,
        )
        for (position, asset), blob in zip(stored, blobs):
            if isinstance(blob, BaseException):
                raise blob
            payloads[position] = (blob, asset.media_type)
    return payloads


def _paste_icon_cells(
    sheet: Image.Image,
    start: int,
    icons: list[MapIconResponse],
    payloads: IconPayloads,
) -> None:
    """Render one batch of icons into their cells, ``start`` cells in."""
    for offset, (icon, payload) in enumerate(zip(icons, payloads)):
        if payload is None:
            image = _placeholder_icon(icon.sprite_id)
        else:
            image = _render_icon(payload[0], payload[1], icon.sprite_id)
        sheet.alpha_composite(image, ((start + offset) * SPRITE_CELL_SIZE, 0))


def _encode_sprite_png(sheet: Image.Image) -> bytes:
    out = BytesIO()
    sheet.save(out, format="PNG")
    return out.getvalue()


async def _render_sprite_png(
    icons: list[MapIconResponse], uploaded: list[MapIconAsset]
) -> bytes:
    """Composite the sheet. Takes rows, not a session — fix(#1428): every cell is
    drawn in a worker thread, and an ``AsyncSession`` cannot be used from one."""
    if not icons:
        return _blank_png(SPRITE_CELL_SIZE)
    assets = {str(asset.id): asset for asset in uploaded}
    sheet = Image.new(
        "RGBA",
        (len(icons) * SPRITE_CELL_SIZE, SPRITE_CELL_SIZE),
        (0, 0, 0, 0),
    )
    # fix(#1428 codex r1): a batch at a time, so neither the read fan-out nor the
    # bytes held at once scale with the catalog. The whole-catalog gather this
    # replaced retained every blob until the last one landed — up to
    # MAX_ICON_BYTES per uploaded icon, on a route that takes no auth.
    for start in range(0, len(icons), _SPRITE_RENDER_BATCH):
        batch = icons[start : start + _SPRITE_RENDER_BATCH]
        payloads = await _load_icon_payloads(batch, assets)
        # fix(#1428): decode and resample are CPU-bound and scale with the stored
        # icons' pixel count. Off the loop, so one large icon stalls a thread
        # instead of every other request in flight.
        await run_in_thread_draining(_paste_icon_cells, sheet, start, batch, payloads)
    return await run_in_thread_draining(_encode_sprite_png, sheet)
