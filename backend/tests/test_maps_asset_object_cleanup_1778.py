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


async def _objects(prefix: str, map_id: str) -> set[str]:
    """Every stored object under ``prefix`` belonging to this map.

    fix(#1778 round 3): keys carry a random component per write now, so the
    tests read what is stored instead of reconstructing a name. That is also the
    property under test in several of them: exactly one object survives a
    replacement, and it is not the one that was there before.
    """
    # The trailing slash matters: LocalStorageProvider reads a prefix without
    # one as a file-name prefix and globs the parent directory instead.
    listed = await _storage().list(prefix.rstrip("/") + "/")
    return {key for key in listed if map_id in key}


async def _the_object(prefix: str, map_id: str) -> str:
    keys = await _objects(prefix, map_id)
    assert len(keys) == 1, keys
    return next(iter(keys))


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

        thumbnail_key = await _the_object("maps/thumbnails", map_id)
        og_key = await _the_object("maps/og-images", map_id)

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


class TestReupload:
    """A replacement leaves exactly one object behind, whatever the encoding.

    The original finding was the extension flip: the key ended in `.jpg` or
    `.png` after the payload, so a PNG re-upload after a JPEG repointed the
    column and stranded the old object. Keys carry a random component per write
    now (fix(#1778 round 3)), which makes every re-upload a replacement, so the
    same-encoding case is the same case rather than a separate one.
    """

    @pytest.mark.parametrize(
        ("route", "prefix"),
        [("thumbnail", "maps/thumbnails"), ("og-image", "maps/og-images")],
    )
    @pytest.mark.parametrize("second_encoding", ["jpeg", "png"])
    async def test_the_previous_object_is_discarded(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        route: str,
        prefix: str,
        second_encoding: str,
    ) -> None:
        map_id = await _create_map(client, admin_auth_header)
        await client.put(
            f"/maps/{map_id}/{route}/",
            json={"data_uri": _jpeg_data_uri()},
            headers=admin_auth_header,
        )
        first_key = await _the_object(prefix, map_id)

        resp = await client.put(
            f"/maps/{map_id}/{route}/",
            json={
                "data_uri": _jpeg_data_uri()
                if second_encoding == "jpeg"
                else _png_data_uri()
            },
            headers=admin_auth_header,
        )

        assert resp.status_code == 204, resp.text
        second_key = await _the_object(prefix, map_id)
        assert second_key != first_key
        assert not await _storage().exists(first_key)

    async def test_the_served_image_survives_a_replacement(
        self, client: AsyncClient, admin_auth_header: dict
    ) -> None:
        map_id = await _create_map(client, admin_auth_header)
        for data_uri in (_jpeg_data_uri(), _png_data_uri(), _jpeg_data_uri()):
            resp = await client.put(
                f"/maps/{map_id}/thumbnail/",
                json={"data_uri": data_uri},
                headers=admin_auth_header,
            )
            assert resp.status_code == 204, resp.text
            get_resp = await client.get(
                f"/maps/{map_id}/thumbnail/", headers=admin_auth_header
            )
            assert get_resp.status_code == 200, get_resp.text

        assert len(await _objects("maps/thumbnails", map_id)) == 1


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

        assert len(await _objects("maps/thumbnails", map_id)) == 1

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
        assert len(await _objects("maps/og-images", map_id)) == 1


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
        live_key = await _the_object("maps/thumbnails", map_id)

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
        live_key = await _the_object("maps/thumbnails", map_id)
        stale_key = f"maps/thumbnails/{map_id}-stale.png"
        await _storage().put(stale_key, b"stale")

        await discard_map_asset_objects(test_db_session, uuid.UUID(map_id), [stale_key])

        assert not await _storage().exists(stale_key)
        assert await _storage().exists(live_key)

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
        key = await _the_object("maps/thumbnails", map_id)
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


# ---------------------------------------------------------------------------
# fix(#1778 round 3): the window between the survivor re-read and the delete
# ---------------------------------------------------------------------------


class TestCleanupRaceAfterTheLockIsReleased:
    """The row lock ends at the commit, so the cleanup runs unprotected.

    The surviving interleave after round 2: A commits its URI and re-reads the
    row, deciding its old key is dead; A is descheduled before the delete; B
    takes the lock, writes and commits; A's delete lands. While the two keys per
    map were reused, B could only ever write one of the same two names, so A's
    delete could remove the object B had just published and the served image
    answered 404. Keys carry a random component per write now, so a candidate
    can never become live again and the interleave is harmless.
    """

    @pytest.mark.parametrize(
        ("route", "prefix"),
        [("thumbnail", "maps/thumbnails"), ("og-image", "maps/og-images")],
    )
    async def test_a_delete_decided_before_a_concurrent_commit_is_harmless(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        monkeypatch,
        route: str,
        prefix: str,
    ) -> None:
        map_id = await _create_map(client, admin_auth_header)
        # Seed a PNG so the first request's replacement is the other encoding,
        # which is what made the two names collide under the old key shape.
        await client.put(
            f"/maps/{map_id}/{route}/",
            json={"data_uri": _png_data_uri()},
            headers=admin_auth_header,
        )

        storage = _storage()
        original_delete = storage.delete
        delete_decided = asyncio.Event()
        release_delete = asyncio.Event()

        async def _hooked_delete(key: str):
            # The first delete is the one the first request decided on after
            # re-reading the row. Hold it there, which is exactly the window
            # the re-read cannot cover.
            if not delete_decided.is_set():
                delete_decided.set()
                await release_delete.wait()
            return await original_delete(key)

        monkeypatch.setattr(storage, "delete", _hooked_delete)

        first = asyncio.create_task(
            client.put(
                f"/maps/{map_id}/{route}/",
                json={"data_uri": _jpeg_data_uri()},
                headers=admin_auth_header,
            )
        )
        await asyncio.wait_for(delete_decided.wait(), timeout=10)

        # The first request has committed and released the lock, so the second
        # runs to completion here rather than blocking.
        second = await client.put(
            f"/maps/{map_id}/{route}/",
            json={"data_uri": _png_data_uri()},
            headers=admin_auth_header,
        )
        assert second.status_code == 204, second.text

        release_delete.set()
        first_resp = await asyncio.wait_for(first, timeout=30)
        assert first_resp.status_code == 204, first_resp.text

        get_resp = await client.get(
            f"/maps/{map_id}/{route}/", headers=admin_auth_header
        )
        assert get_resp.status_code == 200, get_resp.text
        assert len(await _objects(prefix, map_id)) == 1


class TestAssetKeysAreNeverReused:
    async def test_two_uploads_of_one_encoding_produce_two_keys(
        self, client: AsyncClient, admin_auth_header: dict
    ) -> None:
        map_id = await _create_map(client, admin_auth_header)
        seen = set()
        for _ in range(3):
            await client.put(
                f"/maps/{map_id}/thumbnail/",
                json={"data_uri": _jpeg_data_uri()},
                headers=admin_auth_header,
            )
            seen.add(await _the_object("maps/thumbnails", map_id))

        assert len(seen) == 3

    def test_the_key_keeps_the_extension_last_1778(self) -> None:
        """get_thumbnail picks its media type with endswith('.jpg')."""
        from app.modules.catalog.maps.service import new_map_asset_key

        map_id = uuid.uuid4()
        key = new_map_asset_key("maps/thumbnails", map_id, "jpg")

        assert key.startswith(f"maps/thumbnails/{map_id}-")
        assert key.endswith(".jpg")
        assert key != new_map_asset_key("maps/thumbnails", map_id, "jpg")

    async def test_a_key_stored_in_the_old_unversioned_shape_still_serves(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ) -> None:
        """Rows written before this change hold the key verbatim; nothing was
        migrated, so the read path and the first replacement must both work."""
        from sqlalchemy import update

        from app.modules.catalog.maps.models import Map

        map_id = await _create_map(client, admin_auth_header)
        legacy_key = f"maps/thumbnails/{map_id}.jpg"
        await _storage().put(legacy_key, b"legacy bytes")
        await test_db_session.execute(
            update(Map)
            .where(Map.id == uuid.UUID(map_id))
            .values(thumbnail_uri=legacy_key)
        )
        await test_db_session.commit()

        get_resp = await client.get(
            f"/maps/{map_id}/thumbnail/", headers=admin_auth_header
        )
        assert get_resp.status_code == 200, get_resp.text

        replace = await client.put(
            f"/maps/{map_id}/thumbnail/",
            json={"data_uri": _jpeg_data_uri()},
            headers=admin_auth_header,
        )

        assert replace.status_code == 204, replace.text
        assert not await _storage().exists(legacy_key)
        assert len(await _objects("maps/thumbnails", map_id)) == 1
        served = await client.get(
            f"/maps/{map_id}/thumbnail/", headers=admin_auth_header
        )
        assert served.status_code == 200, served.text


class TestTheLockedReadIsNotStale:
    async def test_it_sees_what_committed_while_this_request_waited(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ) -> None:
        """The point of taking the lock is to read what the winner committed.

        Every caller has already loaded the map through ``get_map`` for its 404
        and ownership check, so a ``select(Map)`` here would come back from the
        session's identity map carrying the attributes it was loaded with, and
        the previous key would be the one from before the wait. Found by the
        overlapping-upload test above once keys stopped being reused: the second
        request deleted the seed object and left the first request's behind.
        """
        from app.modules.catalog.maps.service import get_map, lock_map_for_asset_write

        map_id = await _create_map(client, admin_auth_header)
        await client.put(
            f"/maps/{map_id}/thumbnail/",
            json={"data_uri": _jpeg_data_uri()},
            headers=admin_auth_header,
        )
        # Load it into this session's identity map, the way every caller does.
        loaded = await get_map(test_db_session, uuid.UUID(map_id))
        assert loaded is not None
        stale_key = loaded.thumbnail_uri

        # Another request replaces the image and commits.
        await client.put(
            f"/maps/{map_id}/thumbnail/",
            json={"data_uri": _png_data_uri()},
            headers=admin_auth_header,
        )
        fresh_key = await _the_object("maps/thumbnails", map_id)
        assert fresh_key != stale_key

        locked = await lock_map_for_asset_write(test_db_session, uuid.UUID(map_id))

        assert locked.thumbnail_uri == fresh_key
        await test_db_session.rollback()


# ---------------------------------------------------------------------------
# fix(#1778 round 4): the cleanup's own failures stay inside it
# ---------------------------------------------------------------------------


def _break_liveness_read(monkeypatch) -> None:
    """Make the post-commit liveness query raise, the way a blip would."""

    async def _raise(session, map_id):
        raise OSError("connection reset while re-reading the map row")

    monkeypatch.setattr(
        "app.modules.catalog.maps.service_crud._live_map_asset_keys", _raise
    )


class TestALiveNessReadFailureIsNotTheRequestsProblem:
    """The read happens after the caller committed, so it cannot fail the call.

    It is part of the best-effort cleanup, not part of the outcome. Letting it
    escape turned a durable delete or upload into a 500 and invited a retry of
    something that had already happened.
    """

    async def test_delete_still_answers_204_and_deletes_nothing(
        self, client: AsyncClient, admin_auth_header: dict, monkeypatch
    ) -> None:
        map_id = await _create_map(client, admin_auth_header)
        await client.put(
            f"/maps/{map_id}/thumbnail/",
            json={"data_uri": _jpeg_data_uri()},
            headers=admin_auth_header,
        )
        key = await _the_object("maps/thumbnails", map_id)
        _break_liveness_read(monkeypatch)

        resp = await client.delete(f"/maps/{map_id}", headers=admin_auth_header)

        assert resp.status_code == 204, resp.text
        # The row delete committed; only the tidying was skipped.
        assert (
            await client.get(f"/maps/{map_id}", headers=admin_auth_header)
        ).status_code == 404
        assert await _storage().exists(key)

    @pytest.mark.parametrize(
        ("route", "prefix"),
        [("thumbnail", "maps/thumbnails"), ("og-image", "maps/og-images")],
    )
    async def test_an_upload_still_answers_204_and_deletes_nothing(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        monkeypatch,
        route: str,
        prefix: str,
    ) -> None:
        map_id = await _create_map(client, admin_auth_header)
        await client.put(
            f"/maps/{map_id}/{route}/",
            json={"data_uri": _jpeg_data_uri()},
            headers=admin_auth_header,
        )
        first_key = await _the_object(prefix, map_id)
        _break_liveness_read(monkeypatch)

        resp = await client.put(
            f"/maps/{map_id}/{route}/",
            json={"data_uri": _png_data_uri()},
            headers=admin_auth_header,
        )

        assert resp.status_code == 204, resp.text
        # The replacement committed and serves; the old object was left alone
        # rather than deleted on a read that could not be trusted.
        served = await client.get(f"/maps/{map_id}/{route}/", headers=admin_auth_header)
        assert served.status_code == 200, served.text
        assert await _storage().exists(first_key)
        assert len(await _objects(prefix, map_id)) == 2

    async def test_the_helper_itself_never_raises(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session, monkeypatch
    ) -> None:
        from app.modules.catalog.maps.service import discard_map_asset_objects

        map_id = await _create_map(client, admin_auth_header)
        _break_liveness_read(monkeypatch)

        await discard_map_asset_objects(
            test_db_session, uuid.UUID(map_id), ["maps/thumbnails/whatever.jpg"]
        )


# ---------------------------------------------------------------------------
# fix(#1778 round 4): an object whose row never commits is rolled back
# ---------------------------------------------------------------------------


class TestAFailedPublishLeavesNoObject:
    """`storage.put` succeeded, the row that names it did not.

    Keys are never reused now, so without this every retry of a failing capture
    added another undiscoverable object under `maps/`.
    """

    @pytest.mark.parametrize(
        ("route", "prefix"),
        [("thumbnail", "maps/thumbnails"), ("og-image", "maps/og-images")],
    )
    async def test_a_failing_capture_removes_the_object_it_wrote(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        monkeypatch,
        route: str,
        prefix: str,
    ) -> None:
        map_id = await _create_map(client, admin_auth_header)

        async def _raise(db, map_id_arg, **columns):
            raise OSError("commit failed after the object was written")

        monkeypatch.setattr(
            "app.modules.catalog.maps.router._record_image_capture", _raise
        )

        with pytest.raises(OSError):
            await client.put(
                f"/maps/{map_id}/{route}/",
                json={"data_uri": _jpeg_data_uri()},
                headers=admin_auth_header,
            )

        assert await _objects(prefix, map_id) == set()

    async def test_every_retry_of_a_failing_capture_still_leaves_nothing(
        self, client: AsyncClient, admin_auth_header: dict, monkeypatch
    ) -> None:
        map_id = await _create_map(client, admin_auth_header)

        async def _raise(db, map_id_arg, **columns):
            raise OSError("commit failed after the object was written")

        monkeypatch.setattr(
            "app.modules.catalog.maps.router._record_image_capture", _raise
        )

        for _ in range(3):
            with pytest.raises(OSError):
                await client.put(
                    f"/maps/{map_id}/thumbnail/",
                    json={"data_uri": _jpeg_data_uri()},
                    headers=admin_auth_header,
                )

        assert await _objects("maps/thumbnails", map_id) == set()

    async def test_a_previously_stored_image_survives_a_failed_replacement(
        self, client: AsyncClient, admin_auth_header: dict, monkeypatch
    ) -> None:
        """The rollback removes the new key, never the one still on the row."""
        map_id = await _create_map(client, admin_auth_header)
        await client.put(
            f"/maps/{map_id}/thumbnail/",
            json={"data_uri": _jpeg_data_uri()},
            headers=admin_auth_header,
        )
        stored = await _the_object("maps/thumbnails", map_id)

        async def _raise(db, map_id_arg, **columns):
            raise OSError("commit failed after the object was written")

        monkeypatch.setattr(
            "app.modules.catalog.maps.router._record_image_capture", _raise
        )
        with pytest.raises(OSError):
            await client.put(
                f"/maps/{map_id}/thumbnail/",
                json={"data_uri": _png_data_uri()},
                headers=admin_auth_header,
            )

        assert await _objects("maps/thumbnails", map_id) == {stored}
        served = await client.get(
            f"/maps/{map_id}/thumbnail/", headers=admin_auth_header
        )
        assert served.status_code == 200

    async def test_a_failed_icon_commit_removes_the_icon_object(
        self, client: AsyncClient, admin_auth_header: dict, monkeypatch
    ) -> None:
        """The third write-object-then-commit-row site in the package."""
        before = set(await _storage().list("maps/icons/"))

        async def _raise(self):
            raise OSError("commit failed after the icon was written")

        monkeypatch.setattr(
            "sqlalchemy.ext.asyncio.AsyncSession.commit", _raise, raising=True
        )

        png = BytesIO()
        from PIL import Image

        Image.new("RGB", (8, 8), color=(1, 2, 3)).save(png, format="PNG")
        with pytest.raises(OSError):
            await client.post(
                "/maps/icons",
                files={"file": ("icon.png", png.getvalue(), "image/png")},
                headers=admin_auth_header,
            )

        assert set(await _storage().list("maps/icons/")) == before


def test_every_object_write_in_the_maps_package_is_published_1778() -> None:
    """Enumerate the write-object-then-commit-row sites.

    The reviewer asked for the sweep to be explicit rather than assumed. Walks
    the package for calls to a storage provider's ``put`` and requires the
    enclosing function either to open a publication or to record into one it was
    handed, so a fourth writer cannot appear without a rollback path.
    """
    import ast
    from pathlib import Path

    package = Path(__file__).resolve().parents[1] / "app/modules/catalog/maps"
    writers: dict[str, set[str]] = {}
    for path in sorted(package.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            # The body only: `@router.put(...)` is a Call to an attribute
            # named `put` too, and every route decorated with it would
            # otherwise read as an object write.
            body = [child for stmt in node.body for child in ast.walk(stmt)]
            puts = any(
                isinstance(child, ast.Call)
                and isinstance(child.func, ast.Attribute)
                and child.func.attr == "put"
                for child in body
            )
            if not puts:
                continue
            names = {child.id for child in body if isinstance(child, ast.Name)} | {
                child.arg for child in ast.walk(node.args) if isinstance(child, ast.arg)
            }
            writers[f"{path.name}::{node.name}"] = names

    assert set(writers) == {
        "router.py::upload_thumbnail",
        "router.py::upload_og_image",
        "sprites.py::create_icon_asset",
    }, sorted(writers)
    unguarded = [
        where
        for where, names in writers.items()
        if "map_asset_publication" not in names and "published" not in names
    ]
    assert unguarded == [], unguarded
