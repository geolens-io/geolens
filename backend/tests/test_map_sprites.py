"""Tests for map sprite and icon helper behavior."""

import asyncio
from contextlib import contextmanager
from io import BytesIO
import struct
import threading
import uuid
import zlib

from PIL import Image
from httpx import AsyncClient
import pytest

from app.core.config import settings
from app.core.db.tenant_session import current_tenant_var
from app.modules.catalog.maps import sprites
from app.modules.catalog.maps.models import MapIconAsset
from app.modules.catalog.maps.sprites import (
    MAX_ICON_BYTES,
    SPRITE_CELL_SIZE,
    _SPRITE_RENDER_BATCH,
    _path_points,
    _placeholder_icon,
    _render_icon,
    build_sprite_index,
    build_sprite_png,
    clear_sprite_cache,
    create_icon_asset,
    get_icon_content,
    list_icons,
    validate_icon_upload,
)


class _ScalarResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _ExecuteResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return _ScalarResult(self._rows)


class FakeSession:
    def __init__(self, rows=None):
        self.rows = rows or []
        self.added = []
        self.execute_count = 0
        self.get_count = 0

    async def execute(self, _stmt):
        self.execute_count += 1
        return _ExecuteResult(self.rows)

    def add(self, obj):
        self.added.append(obj)
        self.rows.append(obj)

    async def flush(self):
        return None

    async def get(self, _model, ident):
        self.get_count += 1
        for row in self.rows:
            if row.id == ident:
                return row
        return None


class FakeStorage:
    def __init__(self):
        self.objects = {}
        self.get_count = 0
        self.in_flight = 0
        self.max_in_flight = 0

    async def put(self, key, data):
        self.objects[key] = data if isinstance(data, bytes) else data.read()
        return key

    async def get(self, key):
        self.get_count += 1
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        # yield, so concurrent callers actually overlap and are counted
        await asyncio.sleep(0)
        self.in_flight -= 1
        return self.objects[key]


def _asset(**overrides):
    return MapIconAsset(
        id=overrides.get("id", uuid.uuid4()),
        name=overrides.get("name", "Bus"),
        slug=overrides.get("slug", "bus"),
        media_type=overrides.get("media_type", "image/svg+xml"),
        storage_key=overrides.get("storage_key", "maps/icons/bus.svg"),
        size_bytes=overrides.get("size_bytes", 42),
        created_by=overrides.get("created_by", uuid.uuid4()),
    )


def _png_bytes() -> bytes:
    out = BytesIO()
    Image.new("RGBA", (1, 1), (255, 0, 0, 255)).save(out, format="PNG")
    return out.getvalue()


def _png_chunk(kind: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + kind
        + data
        + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    )


def _png_header_only(width: int, height: int) -> bytes:
    """A PNG header with no pixel data — PIL reads ``size`` from IHDR alone.

    Lets a test stage absurd dimensions (and the decompression-bomb refusal PIL
    raises from ``Image.open`` for them) without materializing the pixels.
    """
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
        + _png_chunk(b"IEND", b"")
    )


def _real_png_bytes(width: int, height: int) -> bytes:
    """A real, decodable PNG at the given dimensions.

    Grayscale and single-colored, so staging tens of millions of pixels costs a
    few KB on the wire and no measurable time to build — which is the whole
    problem: nothing about the byte count reflects what decoding will cost.
    """
    out = BytesIO()
    Image.new("L", (width, height), 0).save(out, format="PNG")
    return out.getvalue()


def _large_png_bytes(size: int = 4096) -> bytes:
    """A real, decodable PNG whose dimensions are over the cap but whose bytes
    are well under it — the shape the byte cap alone cannot catch. Sizes are
    written out rather than derived from MAX_ICON_DIMENSION so that moving the
    cap has to face these tests."""
    return _real_png_bytes(size, size)


@pytest.fixture(autouse=True)
def _clear_sprite_cache():
    clear_sprite_cache()
    yield
    clear_sprite_cache()


def test_validate_icon_upload_accepts_svg_and_rejects_scripts():
    slug, media_type, sanitized = validate_icon_upload(
        "Bus Stop.svg",
        "image/svg+xml",
        b'<svg xmlns="http://www.w3.org/2000/svg"></svg>',
    )

    assert slug == "bus-stop"
    assert media_type == "image/svg+xml"
    # SEC-09: returned content is the defusedxml-canonicalized form
    assert b"<svg" in sanitized
    with pytest.raises(ValueError, match="active content"):
        validate_icon_upload("x.svg", "image/svg+xml", b"<svg><script /></svg>")


def test_validate_icon_upload_accepts_real_png_content():
    slug, media_type, sanitized = validate_icon_upload(
        "marker.png",
        "image/png",
        _png_bytes(),
    )

    assert slug == "marker"
    assert media_type == "image/png"
    # SEC-09: PNG bytes are returned unchanged
    assert sanitized == _png_bytes()


@pytest.mark.anyio
async def test_list_icons_includes_builtins_and_uploaded_assets():
    session = FakeSession(rows=[_asset()])

    icons = await list_icons(session)

    assert [icon.slug for icon in icons[:3]] == ["marker", "circle-dot", "arrow-right"]
    assert icons[0].builtin is True
    assert icons[3].slug == "bus"
    assert icons[3].url.startswith("/maps/icons/")


@pytest.mark.anyio
async def test_create_icon_asset_stores_content(monkeypatch):
    storage = FakeStorage()
    monkeypatch.setattr("app.modules.catalog.maps.sprites.get_storage", lambda: storage)
    session = FakeSession()

    asset = await create_icon_asset(
        session,
        filename="Bus.svg",
        content_type="image/svg+xml",
        content=b"<svg></svg>",
        created_by=uuid.uuid4(),
    )

    assert asset.slug.startswith("bus-")
    assert asset.storage_key in storage.objects
    # SEC-09: storage holds the defusedxml-canonicalized form (self-closing
    # empty element), not the original upload bytes. size_bytes tracks the
    # canonical length to stay consistent with what's stored.
    stored = storage.objects[asset.storage_key]
    assert b"<svg" in stored
    assert asset.size_bytes == len(stored)
    assert session.added == [asset]


@pytest.mark.anyio
async def test_get_icon_content_serves_builtin_and_uploaded(monkeypatch):
    storage = FakeStorage()
    storage.objects["maps/icons/bus.svg"] = b"<svg>bus</svg>"
    monkeypatch.setattr("app.modules.catalog.maps.sprites.get_storage", lambda: storage)
    asset = _asset(storage_key="maps/icons/bus.svg")
    session = FakeSession(rows=[asset])

    builtin_content, builtin_type = await get_icon_content(session, "builtin:marker")
    uploaded_content, uploaded_type = await get_icon_content(session, str(asset.id))

    assert b"<svg" in builtin_content
    assert builtin_type == "image/svg+xml"
    assert uploaded_content == b"<svg>bus</svg>"
    assert uploaded_type == "image/svg+xml"


@pytest.mark.anyio
async def test_sprite_index_and_png_are_stable(monkeypatch):
    storage = FakeStorage()
    storage.objects["maps/icons/bus.png"] = _png_bytes()
    monkeypatch.setattr("app.modules.catalog.maps.sprites.get_storage", lambda: storage)
    session = FakeSession(
        rows=[
            _asset(slug="bus", media_type="image/png", storage_key="maps/icons/bus.png")
        ]
    )

    index = await build_sprite_index(session)
    png = await build_sprite_png(session)

    assert list(index) == ["marker", "circle-dot", "arrow-right", "bus"]
    assert index["arrow-right"]["sdf"] is True
    assert index["bus"] == {
        "x": 72,
        "y": 0,
        "width": 24,
        "height": 24,
        "pixelRatio": 1,
    }
    assert png.startswith(b"\x89PNG\r\n\x1a\n")
    assert len(png) > 100


@pytest.mark.anyio
async def test_sprite_index_endpoint_serves_sdf_as_json_boolean(client: AsyncClient):
    """F3: the served index must keep sdf a JSON boolean, not coerce it to 1.

    The route's return type previously narrowed to
    dict[str, dict[str, int | float]], which Pydantic uses to validate the
    response; bool is a subclass of int, so it silently coerced True to the
    JSON integer 1. MapLibre's sprite spec defines sdf as boolean.
    """
    resp = await client.get("/maps/sprites/geolens.json")
    assert resp.status_code == 200
    assert resp.json()["arrow-right"]["sdf"] is True


@pytest.mark.anyio
async def test_sprite_png_reuses_cache_until_icon_catalog_changes(monkeypatch):
    storage = FakeStorage()
    storage.objects["maps/icons/bus.png"] = _png_bytes()
    monkeypatch.setattr("app.modules.catalog.maps.sprites.get_storage", lambda: storage)
    session = FakeSession(
        rows=[
            _asset(slug="bus", media_type="image/png", storage_key="maps/icons/bus.png")
        ]
    )

    first = await build_sprite_png(session)
    second = await build_sprite_png(session)

    assert second == first
    assert storage.get_count == 1

    storage.objects["maps/icons/train.png"] = _png_bytes()
    session.rows.append(
        _asset(
            slug="train",
            media_type="image/png",
            storage_key="maps/icons/train.png",
        )
    )

    third = await build_sprite_png(session)

    assert third != first
    assert storage.get_count == 3


# builder-audit #338 STYLE-05: the hand-rolled SVG path parser/rasterizer is a
# deliberate no-native-dependency tradeoff that approximates bezier/arc curves
# (C/S/Q/T/A) by their endpoint only. The tests below PIN that approximation so
# it cannot silently regress (or be silently "fixed" without acknowledgement).


def _svg_path(d: str, fill: str = "#2563eb") -> bytes:
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
        f'<path fill="{fill}" d="{d}"/></svg>'
    ).encode()


def _render_alpha(d: str, fill: str = "#2563eb") -> bytes:
    """Raw RGBA pixel bytes of a single-path SVG rendered through the sprite
    rasterizer. Deterministic across Pillow versions (raw pixels, not PNG)."""
    return _render_icon(_svg_path(d, fill), "image/svg+xml", "golden").tobytes()


def test_path_points_collapses_bezier_to_endpoints():
    # builder-audit #338 STYLE-05: cubic (C) + quadratic (Q) commands keep only the
    # final endpoint of each curve. Z closes the subpath back to the start.
    assert _path_points("M2 2 C 4 8 8 8 10 2 Q 14 0 18 6 Z") == [
        [(2.0, 2.0), (10.0, 2.0), (18.0, 6.0), (2.0, 2.0)],
    ]


def test_path_points_collapses_arc_to_endpoint():
    # builder-audit #338 STYLE-05: an elliptical arc (A) collapses to its endpoint;
    # the 7 arc params are consumed but only the final (x, y) is plotted.
    assert _path_points("M4 12 A 8 8 0 0 1 20 12 L 12 20 Z") == [
        [(4.0, 12.0), (20.0, 12.0), (12.0, 20.0), (4.0, 12.0)],
    ]


def test_path_points_relative_curve_collapses_to_endpoint():
    # builder-audit #338 STYLE-05: relative curve commands resolve against the
    # running cursor, still collapsing to the (relative) endpoint.
    assert _path_points("m2 2 c 2 6 6 6 8 0 z") == [
        [(2.0, 2.0), (10.0, 2.0), (2.0, 2.0)],
    ]


def test_render_icon_bezier_matches_straight_line_approximation():
    # builder-audit #338 STYLE-05 golden image: a path with cubic/quadratic curves
    # rasterizes pixel-identical to the same path with the curves replaced by
    # straight lines to their endpoints — proving the curve approximation.
    curved = _render_alpha("M2 2 C 4 8 8 8 10 2 Q 14 0 18 6 Z")
    straight = _render_alpha("M2 2 L 10 2 L 18 6 Z")
    assert curved == straight
    # sanity: something was actually drawn (non-zero alpha channel)
    assert any(curved[3::4])


def test_render_icon_arc_matches_straight_line_approximation():
    # builder-audit #338 STYLE-05 golden image: an elliptical-arc path rasterizes
    # pixel-identical to the same path with the arc replaced by a straight line
    # to its endpoint.
    curved = _render_alpha("M4 12 A 8 8 0 0 1 20 12 L 12 20 Z", fill="#0f766e")
    straight = _render_alpha("M4 12 L 20 12 L 12 20 Z", fill="#0f766e")
    assert curved == straight
    assert any(curved[3::4])


@pytest.mark.anyio
async def test_create_icon_asset_clears_sprite_cache(monkeypatch):
    storage = FakeStorage()
    storage.objects["maps/icons/bus.png"] = _png_bytes()
    monkeypatch.setattr("app.modules.catalog.maps.sprites.get_storage", lambda: storage)
    session = FakeSession(
        rows=[
            _asset(slug="bus", media_type="image/png", storage_key="maps/icons/bus.png")
        ]
    )

    await build_sprite_png(session)
    await create_icon_asset(
        session,
        filename="Train.png",
        content_type="image/png",
        content=_png_bytes(),
        created_by=uuid.uuid4(),
    )
    await build_sprite_png(session)

    assert storage.get_count == 3


# The sprite sheet is rendered by PIL behind an unauthenticated route, so the
# tests below pin the three bounds that keep one uploaded icon from costing the
# whole API: an upload-time dimension cap, a render that degrades instead of
# raising, and I/O that is batched and off the event loop.


def test_validate_icon_upload_rejects_oversized_png_dimensions():
    content = _large_png_bytes()

    # the byte cap passes this file; only a dimension cap stops it
    assert len(content) < MAX_ICON_BYTES
    with pytest.raises(ValueError, match="dimensions"):
        validate_icon_upload("huge.png", "image/png", content)


def test_validate_icon_upload_accepts_png_at_the_dimension_cap():
    content = _large_png_bytes(1024)  # MAX_ICON_DIMENSION

    _slug, media_type, sanitized = validate_icon_upload("ok.png", "image/png", content)

    assert media_type == "image/png"
    assert sanitized == content


def test_validate_icon_upload_rejects_decompression_bomb_png():
    # PIL refuses these from Image.open itself, before any pixel decode; the
    # upload must still land as a 400-shaped ValueError, not an unhandled raise.
    with pytest.raises(ValueError, match="dimensions"):
        validate_icon_upload("bomb.png", "image/png", _png_header_only(14000, 14000))


def test_validate_icon_upload_rejects_png_without_pixel_data():
    # verify() raises IndexError (not OSError) on a PNG with no IDAT chunk.
    with pytest.raises(ValueError, match="invalid"):
        validate_icon_upload("empty.png", "image/png", _png_header_only(64, 64))


def test_render_icon_degrades_decompression_bomb_to_placeholder():
    rendered = _render_icon(_png_header_only(14000, 14000), "image/png", "bus")

    assert rendered.size == (SPRITE_CELL_SIZE, SPRITE_CELL_SIZE)
    assert rendered.tobytes() == _placeholder_icon("bus").tobytes()


# The upload cap only governs icons uploaded from here on. The three tests below
# pin the separate render-side bound that governs what is ALREADY stored: it is
# a memory bound, set high enough that every plausible existing icon still draws
# its real art, and low enough that a DoS-scale artifact never reaches a decode.


def test_render_icon_degrades_a_stored_dos_scale_png_to_placeholder():
    # 9000x9000 is 81M px: under Pillow's own bomb threshold, so nothing stopped
    # it, ~79 KB on the wire, so the byte cap let it in before MAX_ICON_DIMENSION
    # existed — and ~320 MB to decode on an unauthenticated cold render.
    content = _real_png_bytes(9000, 9000)
    assert len(content) < MAX_ICON_BYTES

    rendered = _render_icon(content, "image/png", "bus")

    assert rendered.tobytes() == _placeholder_icon("bus").tobytes()


def test_render_icon_still_draws_a_large_but_plausible_stored_png():
    """An icon stored before the upload cap existed keeps rendering its real art.

    This is the property that makes the render bound a memory bound rather than
    the upload cap applied late: 2048px is over MAX_ICON_DIMENSION, so re-using
    the upload cap here would silently blank it on maps that display it today.
    """
    rendered = _render_icon(_real_png_bytes(2048, 2048), "image/png", "bus")

    assert rendered.tobytes() != _placeholder_icon("bus").tobytes()
    assert rendered.getpixel((12, 12)) == (0, 0, 0, 255)


def test_render_bound_counts_pixels_not_dimensions():
    # 12000x160 is 1.9M px — wider than any dimension cap would allow, and
    # cheaper to decode than the 2048 square above. Cost tracks area, so the
    # bound does too.
    rendered = _render_icon(_real_png_bytes(12000, 160), "image/png", "bus")

    assert rendered.tobytes() != _placeholder_icon("bus").tobytes()
    assert any(rendered.tobytes()[3::4])


@pytest.mark.anyio
async def test_sprite_png_renders_when_a_stored_icon_is_oversized(monkeypatch):
    """An icon stored before the dimension cap existed cannot 500 the sheet."""
    storage = FakeStorage()
    storage.objects["maps/icons/bomb.png"] = _png_header_only(14000, 14000)
    monkeypatch.setattr("app.modules.catalog.maps.sprites.get_storage", lambda: storage)
    session = FakeSession(
        rows=[
            _asset(
                slug="bomb",
                media_type="image/png",
                storage_key="maps/icons/bomb.png",
            )
        ]
    )

    png = await build_sprite_png(session)

    assert png.startswith(b"\x89PNG\r\n\x1a\n")
    assert Image.open(BytesIO(png)).size == (4 * SPRITE_CELL_SIZE, SPRITE_CELL_SIZE)


@pytest.mark.anyio
async def test_sprite_png_loads_the_icon_catalog_in_one_query(monkeypatch):
    storage = FakeStorage()
    rows = []
    for slug in ("bus", "train", "tram"):
        storage.objects[f"maps/icons/{slug}.png"] = _png_bytes()
        rows.append(
            _asset(
                slug=slug,
                media_type="image/png",
                storage_key=f"maps/icons/{slug}.png",
            )
        )
    monkeypatch.setattr("app.modules.catalog.maps.sprites.get_storage", lambda: storage)
    session = FakeSession(rows=rows)

    await build_sprite_png(session)

    # fix(#1428 codex r2): the listing query and nothing else — no per-icon
    # session.get(), and no second lookup binding one parameter per icon
    assert session.execute_count == 1
    assert session.get_count == 0
    assert storage.get_count == 3


@pytest.mark.anyio
async def test_sprite_png_composites_off_the_event_loop(monkeypatch):
    """PIL decode/resample/encode must not run on the event loop thread."""
    storage = FakeStorage()
    storage.objects["maps/icons/bus.png"] = _png_bytes()
    monkeypatch.setattr("app.modules.catalog.maps.sprites.get_storage", lambda: storage)
    session = FakeSession(
        rows=[
            _asset(slug="bus", media_type="image/png", storage_key="maps/icons/bus.png")
        ]
    )
    render_threads = []

    def _recorded(name):
        original = getattr(sprites, name)

        def _record(*args):
            render_threads.append(threading.current_thread())
            return original(*args)

        return _record

    for name in ("_paste_icon_cells", "_encode_sprite_png"):
        monkeypatch.setattr(sprites, name, _recorded(name))

    await build_sprite_png(session)

    # both the per-cell render and the sheet encode, off the main thread
    assert len(render_threads) == 2
    assert threading.main_thread() not in render_threads


@pytest.mark.anyio
async def test_sprite_png_bounds_icon_reads_in_flight(monkeypatch):
    """A large catalog must not fan out one storage read per icon at once.

    fix(#1428 codex r1): the reads and the icon bytes they return are both held
    a batch at a time — an unbounded gather retained up to MAX_ICON_BYTES per
    uploaded icon before the first cell was drawn.
    """
    storage = FakeStorage()
    rows = []
    for index in range(_SPRITE_RENDER_BATCH * 3):
        key = f"maps/icons/icon-{index}.png"
        storage.objects[key] = _png_bytes()
        rows.append(
            _asset(slug=f"icon-{index}", media_type="image/png", storage_key=key)
        )
    monkeypatch.setattr("app.modules.catalog.maps.sprites.get_storage", lambda: storage)
    session = FakeSession(rows=rows)

    await build_sprite_png(session)

    assert storage.get_count == _SPRITE_RENDER_BATCH * 3
    assert storage.max_in_flight <= _SPRITE_RENDER_BATCH
    # still a fan-out, not a serial read
    assert storage.max_in_flight > 1


@pytest.mark.anyio
async def test_sprite_png_route_serves_the_sheet(client: AsyncClient):
    resp = await client.get("/maps/sprites/geolens.png")

    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/png"
    assert resp.headers["cache-control"] == "public, max-age=3600"
    sheet = Image.open(BytesIO(resp.content))
    assert sheet.height == SPRITE_CELL_SIZE
    # one cell per catalog icon, the three built-ins at minimum
    assert sheet.width >= 3 * SPRITE_CELL_SIZE
    assert sheet.width % SPRITE_CELL_SIZE == 0


@pytest.mark.anyio
async def test_sprite_png_2x_route_serves_the_sheet(client: AsyncClient):
    resp = await client.get("/maps/sprites/geolens@2x.png")

    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/png"
    assert Image.open(BytesIO(resp.content)).height == SPRITE_CELL_SIZE


@pytest.mark.anyio
async def test_icon_upload_route_rejects_oversized_dimensions(
    client: AsyncClient, admin_auth_header: dict[str, str]
):
    resp = await client.post(
        "/maps/icons",
        headers=admin_auth_header,
        files={"file": ("huge.png", _large_png_bytes(), "image/png")},
    )

    assert resp.status_code == 400
    assert "dimensions" in resp.json()["detail"]


# fix(#1621): the icon catalog is deployment-global, so the icon BYTES have to
# be too. catalog.map_icon_assets carries no tenant_id and no RLS policy, and
# every tenant's anonymous sprite request loads the same rows, so routing the
# keys through resolve_current_storage_key (the way maps/thumbnails/ and
# maps/og-images/ are routed) would write each icon under its uploader's prefix
# where no other tenant could read it. The next cold sprite build for any other
# tenant would then raise FileNotFoundError and 500 an unauthenticated route.
# These pin the global key so that change fails here instead of in production.
TENANT_ICONS = "00000000-0000-0000-0000-000000001621"


@contextmanager
def _tenant_mode(monkeypatch, mode: str, tenant_id: str | None):
    monkeypatch.setattr(settings, "geolens_tenancy_mode", mode)
    token = current_tenant_var.set(tenant_id)
    try:
        yield
    finally:
        current_tenant_var.reset(token)


@pytest.mark.anyio
async def test_icon_storage_keys_stay_global_under_tenant_context(monkeypatch):
    """Upload, single read, and sheet build all use the unprefixed key.

    Staging the bytes at the global key and nowhere else is what makes the read
    assertions bite: a tenant-resolved lookup would ask FakeStorage for
    tenants/<id>/maps/icons/... and raise instead of returning the icon.
    """
    storage = FakeStorage()
    monkeypatch.setattr("app.modules.catalog.maps.sprites.get_storage", lambda: storage)
    session = FakeSession()

    with _tenant_mode(monkeypatch, "multi_tenant", TENANT_ICONS):
        asset = await create_icon_asset(
            session,
            filename="Bus.svg",
            content_type="image/svg+xml",
            content=b"<svg></svg>",
            created_by=uuid.uuid4(),
        )

        assert asset.storage_key == f"maps/icons/{asset.id}.svg"
        assert list(storage.objects) == [asset.storage_key]

        content, media_type = await get_icon_content(session, str(asset.id))
        assert b"<svg" in content
        assert media_type == "image/svg+xml"

        png = await build_sprite_png(session)
        assert png.startswith(b"\x89PNG\r\n\x1a\n")


def test_map_icon_assets_has_no_tenant_column():
    """The schema fact the global storage key depends on.

    If a tenant_id column ever lands on this table, the icon catalog stops
    being fleet-wide and the storage keys can (and should) move under
    tenants/<id>/ with it. Revisit the comment in create_icon_asset and the
    RUNBOOK prefix inventory at the same time.
    """
    assert "tenant_id" not in MapIconAsset.__table__.columns
