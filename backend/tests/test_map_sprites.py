"""Tests for map sprite and icon helper behavior."""

from io import BytesIO
import uuid

from PIL import Image
import pytest

from app.modules.catalog.maps.models import MapIconAsset
from app.modules.catalog.maps.sprites import (
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

    assert [icon.slug for icon in icons[:2]] == ["marker", "circle-dot"]
    assert icons[0].builtin is True
    assert icons[2].slug == "bus"
    assert icons[2].url.startswith("/maps/icons/")


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

    assert list(index) == ["marker", "circle-dot", "bus"]
    assert index["bus"] == {
        "x": 48,
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
