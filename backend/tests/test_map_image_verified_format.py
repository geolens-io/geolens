"""Map image uploads answer from the verified bytes, not the declared type.

The thumbnail and social-card routes share ``store_map_image``: an image
whose header declares dimensions past Pillow's decompression-bomb limit is
an invalid image (400, nothing stored), as is one whose Pillow parser
raises an error of its own. PNG and JPEG are stored under the extension of
the format the bytes carry; any other format Pillow verifies is still
accepted and keeps the extension its declared media type gives.
"""

from __future__ import annotations

import base64
import struct
import uuid
import zlib
from io import BytesIO

import pytest
from httpx import AsyncClient
from PIL import Image

ROUTES = [
    pytest.param("thumbnail", "maps/thumbnails", "thumbnail_uri", id="thumbnail"),
    pytest.param("og-image", "maps/og-images", "og_image_uri", id="og-image"),
]


def _data_uri(media_type: str, data: bytes) -> str:
    return f"data:{media_type};base64," + base64.b64encode(data).decode("ascii")


def _image_bytes(image_format: str) -> bytes:
    buf = BytesIO()
    Image.new("RGB", (4, 4), color=(10, 20, 30)).save(buf, format=image_format)
    return buf.getvalue()


def _png_declaring(width: int, height: int) -> bytes:
    """A PNG signature and IHDR declaring ``width`` x ``height``, no pixels."""

    def chunk(kind: bytes, body: bytes) -> bytes:
        return (
            struct.pack(">I", len(body))
            + kind
            + body
            + struct.pack(">I", zlib.crc32(kind + body))
        )

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IEND", b"")


def _dds_without_pixel_format_flags() -> bytes:
    """A DDS header whose pixel format names no flags.

    Pillow's DDS opener raises ``NotImplementedError`` on it, which no
    caller of the image check handles.
    """
    header = struct.pack("<7I44x", 124, 0x1007, 8, 8, 0, 0, 0)
    pixel_format = struct.pack("<8I", 32, 0, 0, 0, 0, 0, 0, 0)
    caps = struct.pack("<5I", 0x1000, 0, 0, 0, 0)
    data = b"DDS " + header + pixel_format + caps
    return data + b"\0" * (384 - len(data))


def _mpo_bytes() -> bytes:
    buf = BytesIO()
    frame = Image.new("RGB", (4, 4), color=(10, 20, 30))
    frame.save(buf, format="MPO", save_all=True, append_images=[frame])
    return buf.getvalue()


async def _create_map(client: AsyncClient, headers: dict) -> str:
    resp = await client.post(
        "/maps/",
        json={"name": f"Image format {uuid.uuid4().hex[:6]}"},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _pointer(session, map_id: str, column: str) -> str | None:
    from sqlalchemy import select

    from app.modules.catalog.maps.models import Map

    return (
        await session.execute(
            select(getattr(Map, column)).where(Map.id == uuid.UUID(map_id))
        )
    ).scalar_one()


async def _objects(prefix: str, map_id: str) -> set[str]:
    from app.platform.storage.provider import get_storage

    listed = await get_storage().list(prefix.rstrip("/") + "/")
    return {key for key in listed if map_id in key}


@pytest.mark.parametrize(("route", "prefix", "column"), ROUTES)
async def test_oversized_dimensions_answer_400_and_store_nothing(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
    route: str,
    prefix: str,
    column: str,
) -> None:
    map_id = await _create_map(client, admin_auth_header)
    first = await client.put(
        f"/maps/{map_id}/{route}/",
        json={"data_uri": _data_uri("image/png", _image_bytes("PNG"))},
        headers=admin_auth_header,
    )
    assert first.status_code == 204, first.text
    before = await _pointer(test_db_session, map_id, column)
    stored_before = await _objects(prefix, map_id)

    resp = await client.put(
        f"/maps/{map_id}/{route}/",
        json={"data_uri": _data_uri("image/png", _png_declaring(60_000, 60_000))},
        headers=admin_auth_header,
    )

    assert resp.status_code == 400, resp.text
    assert "payload is not a valid image" in resp.json()["detail"]
    assert await _pointer(test_db_session, map_id, column) == before
    assert await _objects(prefix, map_id) == stored_before


async def _upload(
    client: AsyncClient, headers: dict, map_id: str, route: str, data_uri: str
):
    return await client.put(
        f"/maps/{map_id}/{route}/", json={"data_uri": data_uri}, headers=headers
    )


@pytest.mark.parametrize(("route", "prefix", "column"), ROUTES)
async def test_dds_parser_error_answers_400(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
    route: str,
    prefix: str,
    column: str,
) -> None:
    map_id = await _create_map(client, admin_auth_header)

    resp = await _upload(
        client,
        admin_auth_header,
        map_id,
        route,
        _data_uri("image/png", _dds_without_pixel_format_flags()),
    )

    assert resp.status_code == 400, resp.text
    assert "payload is not a valid image" in resp.json()["detail"]
    assert await _pointer(test_db_session, map_id, column) is None
    assert await _objects(prefix, map_id) == set()


async def _stored_key(
    client: AsyncClient,
    headers: dict,
    session,
    route: str,
    prefix: str,
    column: str,
    data_uri: str,
) -> str:
    map_id = await _create_map(client, headers)
    resp = await _upload(client, headers, map_id, route, data_uri)
    assert resp.status_code == 204, resp.text
    key = await _pointer(session, map_id, column)
    assert key is not None
    assert await _objects(prefix, map_id) == {key}
    return key


@pytest.mark.parametrize(("route", "prefix", "column"), ROUTES)
@pytest.mark.parametrize(
    ("image_format", "declared", "ext"),
    [
        pytest.param("PNG", "image/jpeg", ".png", id="png-declared-jpeg"),
        pytest.param("JPEG", "image/png", ".jpg", id="jpeg-declared-png"),
        pytest.param("MPO", "image/png", ".jpg", id="mpo-declared-png"),
    ],
)
async def test_png_and_jpeg_are_stored_under_their_verified_extension(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
    route: str,
    prefix: str,
    column: str,
    image_format: str,
    declared: str,
    ext: str,
) -> None:
    data = _mpo_bytes() if image_format == "MPO" else _image_bytes(image_format)
    key = await _stored_key(
        client,
        admin_auth_header,
        test_db_session,
        route,
        prefix,
        column,
        _data_uri(declared, data),
    )
    assert key.endswith(ext), key


@pytest.mark.parametrize(("route", "prefix", "column"), ROUTES)
@pytest.mark.parametrize(
    ("declared", "ext"),
    [
        pytest.param("image/gif", ".png", id="declared-gif"),
        pytest.param("image/png", ".png", id="declared-png"),
        pytest.param("image/jpeg", ".jpg", id="declared-jpeg"),
    ],
)
async def test_other_formats_are_accepted_under_the_declared_extension(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
    route: str,
    prefix: str,
    column: str,
    declared: str,
    ext: str,
) -> None:
    key = await _stored_key(
        client,
        admin_auth_header,
        test_db_session,
        route,
        prefix,
        column,
        _data_uri(declared, _image_bytes("GIF")),
    )
    assert key.endswith(ext), key
