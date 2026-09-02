"""fix(#1778): a deleted map must not leave its thumbnail and OG image behind.

Codebase audit 2026-08-30 (8dc529f17): ``delete_map`` dropped the row and
nothing anywhere called ``storage.delete`` for a ``maps/`` key, so both images
survived forever. Nothing in the backend enumerates the ``maps/`` prefix, so the
orphan was undiscoverable rather than merely unreclaimed. The same omission
stranded the previous object whenever a re-upload flipped the extension, since
the key ends in ``.jpg`` or ``.png`` depending on the payload's encoding.

The delete is deliberately best effort and runs after the commit: a storage
backend that is refusing calls must not stop an owner deleting their map.
"""

import base64
import uuid
from io import BytesIO

import pytest
from httpx import AsyncClient


def _jpeg_data_uri() -> str:
    from PIL import Image

    img = Image.new("RGB", (4, 4), color=(128, 64, 32))
    buf = BytesIO()
    img.save(buf, format="JPEG")
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def _png_data_uri() -> str:
    from PIL import Image

    img = Image.new("RGB", (4, 4), color=(0, 0, 0))
    buf = BytesIO()
    img.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


async def _create_map(client: AsyncClient, headers: dict) -> str:
    resp = await client.post(
        "/maps/",
        json={"name": f"Asset cleanup {uuid.uuid4().hex[:6]}", "description": ""},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _storage():
    from app.platform.storage.provider import get_storage

    return get_storage()


class TestDeletedMapAssets:
    async def test_delete_removes_both_stored_objects(
        self, client: AsyncClient, admin_auth_header: dict
    ) -> None:
        map_id = await _create_map(client, admin_auth_header)
        assert (
            await client.put(
                f"/maps/{map_id}/thumbnail/",
                json={"data_uri": _jpeg_data_uri()},
                headers=admin_auth_header,
            )
        ).status_code == 204
        assert (
            await client.put(
                f"/maps/{map_id}/og-image/",
                json={"data_uri": _jpeg_data_uri()},
                headers=admin_auth_header,
            )
        ).status_code == 204

        thumbnail_key = f"maps/thumbnails/{map_id}.jpg"
        og_key = f"maps/og-images/{map_id}.jpg"
        assert await _storage().exists(thumbnail_key)
        assert await _storage().exists(og_key)

        resp = await client.delete(f"/maps/{map_id}", headers=admin_auth_header)
        assert resp.status_code == 204, resp.text

        assert not await _storage().exists(thumbnail_key)
        assert not await _storage().exists(og_key)

    async def test_delete_of_a_map_with_no_images_still_succeeds(
        self, client: AsyncClient, admin_auth_header: dict
    ) -> None:
        map_id = await _create_map(client, admin_auth_header)

        resp = await client.delete(f"/maps/{map_id}", headers=admin_auth_header)

        assert resp.status_code == 204, resp.text

    async def test_a_failing_storage_backend_does_not_fail_the_delete(
        self, client: AsyncClient, admin_auth_header: dict, monkeypatch
    ) -> None:
        map_id = await _create_map(client, admin_auth_header)
        await client.put(
            f"/maps/{map_id}/thumbnail/",
            json={"data_uri": _jpeg_data_uri()},
            headers=admin_auth_header,
        )

        async def _boom(key: str) -> None:
            raise OSError("storage backend unavailable")

        monkeypatch.setattr(_storage(), "delete", _boom)

        resp = await client.delete(f"/maps/{map_id}", headers=admin_auth_header)

        assert resp.status_code == 204, resp.text
        gone = await client.get(f"/maps/{map_id}", headers=admin_auth_header)
        assert gone.status_code == 404


class TestReuploadInAnotherEncoding:
    @pytest.mark.parametrize(
        ("route", "prefix"),
        [("thumbnail", "maps/thumbnails"), ("og-image", "maps/og-images")],
    )
    async def test_the_stranded_key_is_discarded(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        route: str,
        prefix: str,
    ) -> None:
        map_id = await _create_map(client, admin_auth_header)
        await client.put(
            f"/maps/{map_id}/{route}/",
            json={"data_uri": _jpeg_data_uri()},
            headers=admin_auth_header,
        )
        assert await _storage().exists(f"{prefix}/{map_id}.jpg")

        resp = await client.put(
            f"/maps/{map_id}/{route}/",
            json={"data_uri": _png_data_uri()},
            headers=admin_auth_header,
        )

        assert resp.status_code == 204, resp.text
        assert await _storage().exists(f"{prefix}/{map_id}.png")
        assert not await _storage().exists(f"{prefix}/{map_id}.jpg")

    async def test_re_uploading_the_same_encoding_keeps_the_object(
        self, client: AsyncClient, admin_auth_header: dict
    ) -> None:
        """The new bytes land on the same key, so nothing may be deleted after."""
        map_id = await _create_map(client, admin_auth_header)
        for _ in range(2):
            resp = await client.put(
                f"/maps/{map_id}/thumbnail/",
                json={"data_uri": _jpeg_data_uri()},
                headers=admin_auth_header,
            )
            assert resp.status_code == 204, resp.text

        assert await _storage().exists(f"maps/thumbnails/{map_id}.jpg")
