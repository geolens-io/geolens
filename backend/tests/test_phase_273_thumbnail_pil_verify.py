"""SEC-12: Map thumbnail upload validates payload via PIL.Image.verify().

Pins the v13.13 closure of L-65. Without the gate, an authenticated user
with edit_metadata permission could upload arbitrary bytes labeled
data:image/png and have them served back as image/png by the GET
endpoint — a stored-content tampering primitive.

The test mirrors the existing TestMapThumbnail style in test_maps.py — it
creates a real map via the API using the shared admin_auth_header fixture
and then exercises PUT /maps/{id}/thumbnail/ end-to-end. We deliberately
do not use a mock-only path here because the gate is a request-handler
concern and the regression we are pinning is "garbage bytes are
persisted".
"""

import base64
import uuid
from io import BytesIO

import pytest
from httpx import AsyncClient
from PIL import Image


async def _create_map(client: AsyncClient, headers: dict) -> dict:
    """Create a map via the API (mirrors test_maps.py:_create_map)."""
    resp = await client.post(
        "/maps/",
        json={"name": f"PIL Verify {uuid.uuid4().hex[:6]}"},
        headers=headers,
    )
    assert resp.status_code == 201, f"Create map failed: {resp.text}"
    return resp.json()


def _png_data_uri(width: int = 16, height: int = 16) -> str:
    """Generate a valid PNG data URI for tests."""
    img = Image.new("RGB", (width, height), color=(100, 150, 200))
    buf = BytesIO()
    img.save(buf, format="PNG")
    encoded = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def _jpeg_data_uri(width: int = 16, height: int = 16) -> str:
    img = Image.new("RGB", (width, height), color=(100, 150, 200))
    buf = BytesIO()
    img.save(buf, format="JPEG")
    encoded = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/jpeg;base64,{encoded}"


def _garbage_data_uri() -> str:
    """A data URI with random bytes that do NOT parse as any image."""
    encoded = base64.b64encode(b"\x00" * 1024).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def _truncated_png_data_uri() -> str:
    """A PNG header followed by garbage — first 8 bytes parse, rest is junk."""
    truncated = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64  # valid magic, junk after
    encoded = base64.b64encode(truncated).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def _zeros_payload_data_uri() -> str:
    """100KB of zero bytes labeled image/png — well-formed base64, not an image."""
    encoded = base64.b64encode(b"\x00" * 50_000).decode("ascii")
    return f"data:image/png;base64,{encoded}"


@pytest.mark.anyio
async def test_valid_png_thumbnail_accepted(
    client: AsyncClient, admin_auth_header: dict
):
    """Happy path: a real PNG → 204 No Content."""
    created = await _create_map(client, admin_auth_header)
    map_id = created["id"]

    resp = await client.put(
        f"/maps/{map_id}/thumbnail/",
        json={"data_uri": _png_data_uri()},
        headers=admin_auth_header,
    )
    assert resp.status_code == 204


@pytest.mark.anyio
async def test_valid_jpeg_thumbnail_accepted(
    client: AsyncClient, admin_auth_header: dict
):
    """Happy path: a real JPEG → 204 No Content."""
    created = await _create_map(client, admin_auth_header)
    map_id = created["id"]

    resp = await client.put(
        f"/maps/{map_id}/thumbnail/",
        json={"data_uri": _jpeg_data_uri()},
        headers=admin_auth_header,
    )
    assert resp.status_code == 204


@pytest.mark.anyio
async def test_garbage_payload_rejected(client: AsyncClient, admin_auth_header: dict):
    """Random bytes labeled image/png → 400 with 'not a valid image' detail."""
    created = await _create_map(client, admin_auth_header)
    map_id = created["id"]

    resp = await client.put(
        f"/maps/{map_id}/thumbnail/",
        json={"data_uri": _garbage_data_uri()},
        headers=admin_auth_header,
    )
    assert resp.status_code == 400
    detail = resp.json()["detail"].lower()
    assert "not a valid image" in detail or "invalid" in detail


@pytest.mark.anyio
async def test_zeros_payload_rejected(client: AsyncClient, admin_auth_header: dict):
    """50KB of zeros labeled image/png → 400 (bigger garbage payload)."""
    created = await _create_map(client, admin_auth_header)
    map_id = created["id"]

    resp = await client.put(
        f"/maps/{map_id}/thumbnail/",
        json={"data_uri": _zeros_payload_data_uri()},
        headers=admin_auth_header,
    )
    assert resp.status_code == 400


@pytest.mark.anyio
async def test_truncated_png_rejected(client: AsyncClient, admin_auth_header: dict):
    """A PNG header + garbage payload → 400."""
    created = await _create_map(client, admin_auth_header)
    map_id = created["id"]

    resp = await client.put(
        f"/maps/{map_id}/thumbnail/",
        json={"data_uri": _truncated_png_data_uri()},
        headers=admin_auth_header,
    )
    assert resp.status_code == 400


@pytest.mark.anyio
async def test_storage_not_touched_on_rejection(
    client: AsyncClient, admin_auth_header: dict, monkeypatch
):
    """When PIL rejects, storage.put is never called.

    Storage is resolved lazily via app.platform.storage.provider.get_storage
    inside the handler; we patch that callable to a recording stub and
    assert .put is not called when the payload is invalid.
    """
    created = await _create_map(client, admin_auth_header)
    map_id = created["id"]

    put_calls: list[tuple[str, bytes]] = []

    class _RecordingStorage:
        async def put(self, key: str, data: bytes) -> None:
            put_calls.append((key, data))

        async def get(self, key: str) -> bytes:  # pragma: no cover
            raise FileNotFoundError(key)

    def _factory():
        return _RecordingStorage()

    # Patch the symbol the handler will resolve at call time. The handler
    # imports `from app.platform.storage.provider import get_storage` inside
    # the function body, so we replace the attribute on that module.
    import app.platform.storage.provider as storage_provider

    monkeypatch.setattr(storage_provider, "get_storage", _factory)

    resp = await client.put(
        f"/maps/{map_id}/thumbnail/",
        json={"data_uri": _garbage_data_uri()},
        headers=admin_auth_header,
    )
    assert resp.status_code == 400
    assert put_calls == [], (
        f"storage.put MUST NOT be called on PIL rejection; got {len(put_calls)} call(s)"
    )
