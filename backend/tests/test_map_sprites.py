"""Tests for map sprite and icon helper behavior."""

from io import BytesIO
import uuid

from PIL import Image
import pytest

from app.modules.catalog.maps.models import MapIconAsset
from app.modules.catalog.maps.sprites import (
    _path_points,
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

    async def execute(self, _stmt):
        return _ExecuteResult(self.rows)

    def add(self, obj):
        self.added.append(obj)
        self.rows.append(obj)

    async def flush(self):
        return None

    async def get(self, _model, ident):
        for row in self.rows:
            if row.id == ident:
                return row
        return None


class FakeStorage:
    def __init__(self):
        self.objects = {}
        self.get_count = 0

    async def put(self, key, data):
        self.objects[key] = data if isinstance(data, bytes) else data.read()
        return key

    async def get(self, key):
        self.get_count += 1
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


# builder-audit STYLE-05: the hand-rolled SVG path parser/rasterizer is a
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
    # builder-audit STYLE-05: cubic (C) + quadratic (Q) commands keep only the
    # final endpoint of each curve. Z closes the subpath back to the start.
    assert _path_points("M2 2 C 4 8 8 8 10 2 Q 14 0 18 6 Z") == [
        [(2.0, 2.0), (10.0, 2.0), (18.0, 6.0), (2.0, 2.0)],
    ]


def test_path_points_collapses_arc_to_endpoint():
    # builder-audit STYLE-05: an elliptical arc (A) collapses to its endpoint;
    # the 7 arc params are consumed but only the final (x, y) is plotted.
    assert _path_points("M4 12 A 8 8 0 0 1 20 12 L 12 20 Z") == [
        [(4.0, 12.0), (20.0, 12.0), (12.0, 20.0), (4.0, 12.0)],
    ]


def test_path_points_relative_curve_collapses_to_endpoint():
    # builder-audit STYLE-05: relative curve commands resolve against the
    # running cursor, still collapsing to the (relative) endpoint.
    assert _path_points("m2 2 c 2 6 6 6 8 0 z") == [
        [(2.0, 2.0), (10.0, 2.0), (2.0, 2.0)],
    ]


def test_render_icon_bezier_matches_straight_line_approximation():
    # builder-audit STYLE-05 golden image: a path with cubic/quadratic curves
    # rasterizes pixel-identical to the same path with the curves replaced by
    # straight lines to their endpoints — proving the curve approximation.
    curved = _render_alpha("M2 2 C 4 8 8 8 10 2 Q 14 0 18 6 Z")
    straight = _render_alpha("M2 2 L 10 2 L 18 6 Z")
    assert curved == straight
    # sanity: something was actually drawn (non-zero alpha channel)
    assert any(curved[3::4])


def test_render_icon_arc_matches_straight_line_approximation():
    # builder-audit STYLE-05 golden image: an elliptical-arc path rasterizes
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
