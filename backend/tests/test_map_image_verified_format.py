"""Map image uploads answer from the verified bytes, not the declared type.

The thumbnail and social-card routes share ``store_map_image``: an image
whose header declares dimensions past Pillow's decompression-bomb limit is
an invalid image (400, nothing stored), and the stored extension follows
the format the bytes carry, refusing formats the routes don't serve.
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


@pytest.mark.parametrize(("route", "prefix", "column"), ROUTES)
async def test_png_declared_as_jpeg_is_stored_as_png(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
    route: str,
    prefix: str,
    column: str,
) -> None:
    map_id = await _create_map(client, admin_auth_header)

    resp = await client.put(
        f"/maps/{map_id}/{route}/",
        json={"data_uri": _data_uri("image/jpeg", _image_bytes("PNG"))},
        headers=admin_auth_header,
    )

    assert resp.status_code == 204, resp.text
    key = await _pointer(test_db_session, map_id, column)
    assert key is not None
    assert key.endswith(".png"), key
    assert await _objects(prefix, map_id) == {key}


@pytest.mark.parametrize(("route", "prefix", "column"), ROUTES)
async def test_gif_declared_as_png_answers_400(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
    route: str,
    prefix: str,
    column: str,
) -> None:
    map_id = await _create_map(client, admin_auth_header)

    resp = await client.put(
        f"/maps/{map_id}/{route}/",
        json={"data_uri": _data_uri("image/png", _image_bytes("GIF"))},
        headers=admin_auth_header,
    )

    assert resp.status_code == 400, resp.text
    assert "payload is not a valid image" in resp.json()["detail"]
    assert await _pointer(test_db_session, map_id, column) is None
    assert await _objects(prefix, map_id) == set()
