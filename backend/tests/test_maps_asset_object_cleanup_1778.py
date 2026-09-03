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

import asyncio
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


# ---------------------------------------------------------------------------
# fix(#1778 round 2): overlapping replacements of one map's asset
# ---------------------------------------------------------------------------


class TestOverlappingReplacements:
    """Two uploads of one map in different encodings must not race each other.

    The losing interleave, before the row lock: A writes its `.jpg` object, B
    reads `.jpg` as the previous key, commits its URI at `.png` and deletes
    `.jpg`, then A commits its URI at `.jpg`, pointing the row at the object B
    just deleted. Both answer 204 and the thumbnail endpoint answers 404.
    """

    async def test_the_second_upload_waits_and_both_end_consistent(
        self, client: AsyncClient, admin_auth_header: dict, monkeypatch
    ) -> None:
        map_id = await _create_map(client, admin_auth_header)
        # Seed the stored key the reported interleave starts from.
        await client.put(
            f"/maps/{map_id}/thumbnail/",
            json={"data_uri": _jpeg_data_uri()},
            headers=admin_auth_header,
        )

        storage = _storage()
        original_put = storage.put
        first_write_done = asyncio.Event()
        release_first = asyncio.Event()

        async def _hooked_put(key: str, data):
            result = await original_put(key, data)
            # Block AFTER the bytes land, which is where the reported race
            # opens: the object exists, the URI is not committed yet.
            if key.endswith(".jpg") and not first_write_done.is_set():
                first_write_done.set()
                await release_first.wait()
            return result

        monkeypatch.setattr(storage, "put", _hooked_put)

        first = asyncio.create_task(
            client.put(
                f"/maps/{map_id}/thumbnail/",
                json={"data_uri": _jpeg_data_uri()},
                headers=admin_auth_header,
            )
        )
        await asyncio.wait_for(first_write_done.wait(), timeout=10)

        second = asyncio.create_task(
            client.put(
                f"/maps/{map_id}/thumbnail/",
                json={"data_uri": _png_data_uri()},
                headers=admin_auth_header,
            )
        )
        # The second request reaches SELECT ... FOR UPDATE and stops there. The
        # window is generous in the direction that matters: without the lock the
        # second request runs an in-process put, update, commit and delete, all
        # local, so a slow machine does not turn this into a false failure.
        await asyncio.sleep(0.5)
        assert not second.done(), (
            "the second upload was not serialized behind the first"
        )

        release_first.set()
        first_resp, second_resp = await asyncio.wait_for(
            asyncio.gather(first, second), timeout=30
        )

        assert first_resp.status_code == 204, first_resp.text
        assert second_resp.status_code == 204, second_resp.text

        get_resp = await client.get(
            f"/maps/{map_id}/thumbnail/", headers=admin_auth_header
        )
        assert get_resp.status_code == 200, get_resp.text

        assert await storage.exists(f"maps/thumbnails/{map_id}.png")
        assert not await storage.exists(f"maps/thumbnails/{map_id}.jpg")

    async def test_the_og_image_handler_is_serialized_the_same_way(
        self, client: AsyncClient, admin_auth_header: dict, monkeypatch
    ) -> None:
        map_id = await _create_map(client, admin_auth_header)
        await client.put(
            f"/maps/{map_id}/og-image/",
            json={"data_uri": _jpeg_data_uri()},
            headers=admin_auth_header,
        )

        storage = _storage()
        original_put = storage.put
        first_write_done = asyncio.Event()
        release_first = asyncio.Event()

        async def _hooked_put(key: str, data):
            result = await original_put(key, data)
            if key.endswith(".jpg") and not first_write_done.is_set():
                first_write_done.set()
                await release_first.wait()
            return result

        monkeypatch.setattr(storage, "put", _hooked_put)

        first = asyncio.create_task(
            client.put(
                f"/maps/{map_id}/og-image/",
                json={"data_uri": _jpeg_data_uri()},
                headers=admin_auth_header,
            )
        )
        await asyncio.wait_for(first_write_done.wait(), timeout=10)

        second = asyncio.create_task(
            client.put(
                f"/maps/{map_id}/og-image/",
                json={"data_uri": _png_data_uri()},
                headers=admin_auth_header,
            )
        )
        await asyncio.sleep(0.5)
        assert not second.done(), "the second OG upload was not serialized"

        release_first.set()
        first_resp, second_resp = await asyncio.wait_for(
            asyncio.gather(first, second), timeout=30
        )

        assert (first_resp.status_code, second_resp.status_code) == (204, 204)
        get_resp = await client.get(
            f"/maps/{map_id}/og-image/", headers=admin_auth_header
        )
        assert get_resp.status_code == 200, get_resp.text
        assert await storage.exists(f"maps/og-images/{map_id}.png")
        assert not await storage.exists(f"maps/og-images/{map_id}.jpg")


class TestCleanupRefusesALiveKey:
    """The second half of the fix, independent of the lock.

    A row lock cannot outlive the commit that releases it, so a request whose
    cleanup was queued before another request committed can arrive holding a key
    that is live again. The helper re-reads the committed row and leaves it.
    """

    async def test_a_key_the_row_still_points_at_is_not_deleted(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ) -> None:
        from app.modules.catalog.maps.service import discard_map_asset_objects

        map_id = await _create_map(client, admin_auth_header)
        await client.put(
            f"/maps/{map_id}/thumbnail/",
            json={"data_uri": _jpeg_data_uri()},
            headers=admin_auth_header,
        )
        live_key = f"maps/thumbnails/{map_id}.jpg"
        assert await _storage().exists(live_key)

        await discard_map_asset_objects(test_db_session, uuid.UUID(map_id), [live_key])

        assert await _storage().exists(live_key)
        get_resp = await client.get(
            f"/maps/{map_id}/thumbnail/", headers=admin_auth_header
        )
        assert get_resp.status_code == 200

    async def test_a_key_the_row_no_longer_points_at_is_deleted(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ) -> None:
        from app.modules.catalog.maps.service import discard_map_asset_objects

        map_id = await _create_map(client, admin_auth_header)
        await client.put(
            f"/maps/{map_id}/thumbnail/",
            json={"data_uri": _jpeg_data_uri()},
            headers=admin_auth_header,
        )
        stale_key = f"maps/thumbnails/{map_id}.png"
        await _storage().put(stale_key, b"stale")

        await discard_map_asset_objects(test_db_session, uuid.UUID(map_id), [stale_key])

        assert not await _storage().exists(stale_key)
        assert await _storage().exists(f"maps/thumbnails/{map_id}.jpg")

    async def test_every_key_of_a_deleted_map_is_deletable(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ) -> None:
        """No row means nothing references the objects, so the guard allows it."""
        from app.modules.catalog.maps.service import discard_map_asset_objects

        map_id = await _create_map(client, admin_auth_header)
        await client.put(
            f"/maps/{map_id}/thumbnail/",
            json={"data_uri": _jpeg_data_uri()},
            headers=admin_auth_header,
        )
        key = f"maps/thumbnails/{map_id}.jpg"
        await client.delete(f"/maps/{map_id}", headers=admin_auth_header)
        await _storage().put(key, b"recreated by hand")

        await discard_map_asset_objects(test_db_session, uuid.UUID(map_id), [key])

        assert not await _storage().exists(key)


def test_every_cleanup_caller_takes_the_row_lock_1778() -> None:
    """Enumerate the callers so a fourth cannot skip the locked path.

    Walks the maps package and requires every function that calls
    ``discard_map_asset_objects`` to also call ``lock_map_for_asset_write``.
    """
    import ast
    from pathlib import Path

    package = Path(__file__).resolve().parents[1] / "app/modules/catalog/maps"
    callers: dict[str, set[str]] = {}
    for path in sorted(package.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            names = {
                child.func.id
                for child in ast.walk(node)
                if isinstance(child, ast.Call) and isinstance(child.func, ast.Name)
            }
            if "discard_map_asset_objects" in names:
                callers[f"{path.name}::{node.name}"] = names

    assert set(callers) == {
        "router.py::delete_map_endpoint",
        "router.py::upload_thumbnail",
        "router.py::upload_og_image",
    }, sorted(callers)
    unlocked = [
        where
        for where, names in callers.items()
        if "lock_map_for_asset_write" not in names
    ]
    assert unlocked == [], unlocked
