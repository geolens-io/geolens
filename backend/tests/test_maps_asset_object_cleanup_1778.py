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

    fix(round 9): the block point moved from inside ``storage.put`` to inside
    ``lock_map_for_asset_write``. Before round 9 the row lock was taken before
    the PUT, so blocking a request after its bytes landed but before it
    returned from ``put`` was also blocking it before it could reach the lock,
    which is what made ``second`` wait on ``SELECT ... FOR UPDATE`` in that
    window. Round 9 moved the lock to AFTER the PUT specifically so a stalled
    write no longer holds it, so that same block point no longer represents
    "holding the lock". Hooking the lock call itself, calling through to the
    real function so the row lock is genuinely acquired in Postgres and then
    holding the coroutine there, reproduces the same window under the new
    ordering: ``first`` demonstrably holds the lock, not yet committed, while
    ``second``'s own (real, unmocked) ``SELECT ... FOR UPDATE`` genuinely
    blocks against it in the database.
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
        seed_key = await _the_object("maps/thumbnails", map_id)

        import app.modules.catalog.maps.router as router_module

        original_lock = router_module.lock_map_for_asset_write
        lock_acquired = asyncio.Event()
        release_lock = asyncio.Event()

        async def _hooked_lock(db, map_id_arg):
            result = await original_lock(db, map_id_arg)
            if not lock_acquired.is_set():
                lock_acquired.set()
                await release_lock.wait()
            return result

        monkeypatch.setattr(router_module, "lock_map_for_asset_write", _hooked_lock)

        first = asyncio.create_task(
            client.put(
                f"/maps/{map_id}/thumbnail/",
                json={"data_uri": _jpeg_data_uri()},
                headers=admin_auth_header,
            )
        )
        await asyncio.wait_for(lock_acquired.wait(), timeout=10)

        second = asyncio.create_task(
            client.put(
                f"/maps/{map_id}/thumbnail/",
                json={"data_uri": _png_data_uri()},
                headers=admin_auth_header,
            )
        )
        # first holds the row lock, uncommitted; second's own SELECT ... FOR
        # UPDATE genuinely blocks on it in Postgres. The window is generous in
        # the direction that matters: well under the 2s lock_timeout, so a
        # slow machine does not turn this into a false 409 instead of a wait.
        await asyncio.sleep(0.5)
        assert not second.done(), (
            "the second upload was not serialized behind the first"
        )

        release_lock.set()
        first_resp, second_resp = await asyncio.wait_for(
            asyncio.gather(first, second), timeout=30
        )

        assert first_resp.status_code == 204, first_resp.text
        assert second_resp.status_code == 204, second_resp.text

        get_resp = await client.get(
            f"/maps/{map_id}/thumbnail/", headers=admin_auth_header
        )
        assert get_resp.status_code == 200, get_resp.text

        # first acquired the lock first (we waited for it before starting
        # second), so first's write becomes second's previous key, which
        # second re-reads under the lock and reaps. _the_object asserts
        # exactly one object survives: the seed key first reaped and whatever
        # intermediate key second reaped in turn are both gone, neither
        # leaked nor double-deleted, and the row still names something that
        # exists (the GET above already proved that).
        live_key = await _the_object("maps/thumbnails", map_id)
        assert live_key != seed_key

    async def test_the_og_image_handler_is_serialized_the_same_way(
        self, client: AsyncClient, admin_auth_header: dict, monkeypatch
    ) -> None:
        map_id = await _create_map(client, admin_auth_header)
        await client.put(
            f"/maps/{map_id}/og-image/",
            json={"data_uri": _jpeg_data_uri()},
            headers=admin_auth_header,
        )

        import app.modules.catalog.maps.router as router_module

        original_lock = router_module.lock_map_for_asset_write
        lock_acquired = asyncio.Event()
        release_lock = asyncio.Event()

        async def _hooked_lock(db, map_id_arg):
            result = await original_lock(db, map_id_arg)
            if not lock_acquired.is_set():
                lock_acquired.set()
                await release_lock.wait()
            return result

        monkeypatch.setattr(router_module, "lock_map_for_asset_write", _hooked_lock)

        first = asyncio.create_task(
            client.put(
                f"/maps/{map_id}/og-image/",
                json={"data_uri": _jpeg_data_uri()},
                headers=admin_auth_header,
            )
        )
        await asyncio.wait_for(lock_acquired.wait(), timeout=10)

        second = asyncio.create_task(
            client.put(
                f"/maps/{map_id}/og-image/",
                json={"data_uri": _png_data_uri()},
                headers=admin_auth_header,
            )
        )
        await asyncio.sleep(0.5)
        assert not second.done(), "the second OG upload was not serialized"

        release_lock.set()
        first_resp, second_resp = await asyncio.wait_for(
            asyncio.gather(first, second), timeout=30
        )

        assert (first_resp.status_code, second_resp.status_code) == (204, 204)
        get_resp = await client.get(
            f"/maps/{map_id}/og-image/", headers=admin_auth_header
        )
        assert get_resp.status_code == 200, get_resp.text
        assert len(await _objects("maps/og-images", map_id)) == 1


# ---------------------------------------------------------------------------
# fix(round 9): a stalled storage write must not hold the map row locked
# ---------------------------------------------------------------------------


class TestAStalledUploadDoesNotBlockOtherWriters:
    """The row lock is taken after the storage write, not before it.

    Review finding: ``lock_map_for_asset_write`` used to run before
    ``storage.put``, held through the commit. A stalled PUT against a
    degraded object-storage backend therefore held the map row locked for as
    long as the PUT took, and every other writer to the same map queued
    behind it with no bound of its own: ``update_map_endpoint`` takes no
    ``lock_timeout``, so its plain UPDATE would wait on Postgres's default
    statement timeout (300s), not the 2s ``lock_map_for_asset_write`` only
    ever bounded for the uploading request's OWN wait for the lock.
    """

    async def test_a_stalled_thumbnail_put_does_not_block_a_concurrent_rename(
        self, client: AsyncClient, admin_auth_header: dict, monkeypatch
    ) -> None:
        import time

        map_id = await _create_map(client, admin_auth_header)

        storage = _storage()
        original_put = storage.put
        put_entered = asyncio.Event()
        release_put = asyncio.Event()

        async def _stalled_put(key: str, data):
            if key.startswith("maps/thumbnails/") and not put_entered.is_set():
                put_entered.set()
                await release_put.wait()
            return await original_put(key, data)

        monkeypatch.setattr(storage, "put", _stalled_put)

        upload = asyncio.create_task(
            client.put(
                f"/maps/{map_id}/thumbnail/",
                json={"data_uri": _jpeg_data_uri()},
                headers=admin_auth_header,
            )
        )
        await asyncio.wait_for(put_entered.wait(), timeout=10)

        # The upload is stuck inside the PUT, which round 9 moved outside the
        # row lock. A plain rename, which takes no lock_timeout of its own and
        # would previously have queued behind the held row lock for as long
        # as the PUT took, must complete right away instead of waiting on it.
        started = time.monotonic()
        rename_resp = await client.put(
            f"/maps/{map_id}",
            json={"name": "renamed-while-upload-stalled"},
            headers=admin_auth_header,
        )
        elapsed = time.monotonic() - started

        assert rename_resp.status_code == 200, rename_resp.text
        assert rename_resp.json()["name"] == "renamed-while-upload-stalled"
        assert elapsed < 2, elapsed

        release_put.set()
        upload_resp = await asyncio.wait_for(upload, timeout=30)
        assert upload_resp.status_code == 204, upload_resp.text

    async def test_a_stalled_og_image_put_does_not_block_a_concurrent_delete(
        self, client: AsyncClient, admin_auth_header: dict, monkeypatch
    ) -> None:
        """Same shape, the other image handler, against delete_map_endpoint.

        ``delete_map_endpoint`` takes ``lock_map_for_asset_write`` itself, so
        this also proves two DIFFERENT requests' calls into the same helper
        do not deadlock or serialize on an unrelated stalled write.
        """
        import time

        map_id = await _create_map(client, admin_auth_header)

        storage = _storage()
        original_put = storage.put
        put_entered = asyncio.Event()
        release_put = asyncio.Event()

        async def _stalled_put(key: str, data):
            if key.startswith("maps/og-images/") and not put_entered.is_set():
                put_entered.set()
                await release_put.wait()
            return await original_put(key, data)

        monkeypatch.setattr(storage, "put", _stalled_put)

        upload = asyncio.create_task(
            client.put(
                f"/maps/{map_id}/og-image/",
                json={"data_uri": _jpeg_data_uri()},
                headers=admin_auth_header,
            )
        )
        await asyncio.wait_for(put_entered.wait(), timeout=10)

        started = time.monotonic()
        delete_resp = await client.delete(f"/maps/{map_id}", headers=admin_auth_header)
        elapsed = time.monotonic() - started

        assert delete_resp.status_code == 204, delete_resp.text
        assert elapsed < 2, elapsed

        release_put.set()
        # The map is gone by the time the stalled PUT's lock acquisition
        # runs, so the upload surfaces that as 404 rather than hanging or
        # succeeding against a row that no longer exists.
        upload_resp = await asyncio.wait_for(upload, timeout=30)
        assert upload_resp.status_code == 404, upload_resp.text


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

    async def test_a_failed_icon_write_removes_the_icon_object(
        self, client: AsyncClient, admin_auth_header: dict, monkeypatch
    ) -> None:
        """The third write-object-then-commit-row site in the package.

        The failure is placed at the flush, which is after the object write and
        before the commit. fix(#1778 round 6): a failure of the COMMIT itself is
        a different case, covered below: its outcome is unknowable, so nothing
        is deleted.
        """
        from PIL import Image

        before = set(await _storage().list("maps/icons/"))

        async def _raise(self, *args, **kwargs):
            raise OSError("the row never landed after the icon was written")

        monkeypatch.setattr(
            "sqlalchemy.ext.asyncio.AsyncSession.flush", _raise, raising=True
        )

        png = BytesIO()
        Image.new("RGB", (8, 8), color=(1, 2, 3)).save(png, format="PNG")
        # A bare OSError is not one of the database errors the app maps to a
        # 5xx, so it comes straight out of the client here.
        with pytest.raises(OSError):
            await client.post(
                "/maps/icons",
                files={"file": ("icon.png", png.getvalue(), "image/png")},
                headers=admin_auth_header,
            )

        assert set(await _storage().list("maps/icons/")) == before

    async def test_a_commit_that_fails_outright_still_keeps_the_object(
        self, client: AsyncClient, admin_auth_header: dict, monkeypatch
    ) -> None:
        """The accepted cost of fix(#1778 round 6), written down.

        Once the commit has been awaited its outcome is unknowable from the
        exception, so a commit that genuinely failed leaves its object behind
        rather than risking one that genuinely landed. This asserts the cost so
        it is a decision rather than a surprise, and so tightening the rule
        later has to come past this test.
        """
        from PIL import Image

        before = set(await _storage().list("maps/icons/"))

        async def _raise(self, *args, **kwargs):
            raise OSError("commit failed, and this exception cannot say whether")

        monkeypatch.setattr(
            "sqlalchemy.ext.asyncio.AsyncSession.commit", _raise, raising=True
        )

        png = BytesIO()
        Image.new("RGB", (8, 8), color=(1, 2, 3)).save(png, format="PNG")
        with pytest.raises(OSError):
            await client.post(
                "/maps/icons",
                files={"file": ("icon.png", png.getvalue(), "image/png")},
                headers=admin_auth_header,
            )

        assert len(set(await _storage().list("maps/icons/")) - before) == 1


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
        if "map_asset_publication" not in names and "publication" not in names
    ]
    assert unguarded == [], unguarded


def test_every_object_write_records_before_putting_1778() -> None:
    """fix(#1778 round 7): the ledger entry precedes the write it covers.

    Object storage can durably accept a PUT and still fail the client with a
    timeout or a dropped connection, so a raise from the write says nothing
    about whether the bytes landed. Recording afterwards left the ledger empty
    for exactly that case, and since keys are never reused the object was
    unreferenced and unreclaimable, one more per retry. Recording first is free:
    the rollback either deletes what this request wrote or no-ops on a key
    nothing wrote.
    """
    import ast
    from pathlib import Path

    package = Path(__file__).resolve().parents[1] / "app/modules/catalog/maps"
    writers: dict[str, tuple[int, int]] = {}
    for path in sorted(package.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            body = [child for stmt in node.body for child in ast.walk(stmt)]
            puts = [
                child.lineno
                for child in body
                if isinstance(child, ast.Call)
                and isinstance(child.func, ast.Attribute)
                and child.func.attr == "put"
            ]
            if not puts:
                continue
            records = [
                child.lineno
                for child in body
                if isinstance(child, ast.Call)
                and isinstance(child.func, ast.Attribute)
                and child.func.attr == "record"
            ]
            writers[f"{path.name}::{node.name}"] = (
                min(records) if records else -1,
                min(puts),
            )

    assert set(writers) == {
        "router.py::upload_thumbnail",
        "router.py::upload_og_image",
        "sprites.py::create_icon_asset",
    }, sorted(writers)
    offenders = [
        where
        for where, (record_line, put_line) in writers.items()
        if record_line < 0 or record_line > put_line
    ]
    assert offenders == [], offenders


def test_every_publication_settles_at_the_commit_1778() -> None:
    """fix(#1778 round 5): the rollback boundary is the commit, not the block.

    Keying the rollback on "did the block raise" is not the same question as
    "did the row commit": the icon route's ``session.refresh`` ran after a
    successful commit and inside the scope, so a failure there deleted an object
    the committed row referenced. ``settled()`` moves the boundary onto the
    commit, and this walks the package to require it as the LAST statement of
    every publication block, so nothing can be appended below it later.
    """
    import ast
    from pathlib import Path

    package = Path(__file__).resolve().parents[1] / "app/modules/catalog/maps"
    blocks = 0
    offenders: list[str] = []
    for path in sorted(package.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.AsyncWith):
                continue
            opens = any(
                isinstance(item.context_expr, ast.Call)
                and isinstance(item.context_expr.func, ast.Name)
                and item.context_expr.func.id == "map_asset_publication"
                for item in node.items
            )
            if not opens:
                continue
            blocks += 1
            if not _calls(node.body[-1], "settled"):
                offenders.append(f"{path.name}:{node.lineno} does not settle last")

    assert blocks == 3, blocks
    assert offenders == [], offenders


def _calls(statement, attribute: str) -> bool:
    """True when ``statement`` is a bare call to ``<something>.<attribute>()``."""
    import ast

    if not isinstance(statement, ast.Expr):
        return False
    call = statement.value
    return (
        isinstance(call, ast.Call)
        and isinstance(call.func, ast.Attribute)
        and call.func.attr == attribute
    )


def _awaits_commit(statement) -> bool:
    import ast

    if not isinstance(statement, ast.Expr) or not isinstance(
        statement.value, ast.Await
    ):
        return False
    call = statement.value.value
    return (
        isinstance(call, ast.Call)
        and isinstance(call.func, ast.Attribute)
        and call.func.attr == "commit"
    )


def test_every_publication_marks_before_committing_1778() -> None:
    """fix(#1778 round 6): an indeterminate commit outcome deletes nothing.

    A connection lost between PostgreSQL making the commit durable and the
    acknowledgement arriving raises out of the await for a transaction that DID
    commit, so the exception path would delete an object the committed row
    references. ``committing()`` immediately before the await is what makes that
    case non-destructive, and this requires the three statements to sit in that
    order in every publication block: mark, commit, settle.
    """
    import ast
    from pathlib import Path

    package = Path(__file__).resolve().parents[1] / "app/modules/catalog/maps"
    commits = 0
    offenders: list[str] = []
    for path in sorted(package.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.AsyncWith):
                continue
            if not any(
                isinstance(item.context_expr, ast.Call)
                and isinstance(item.context_expr.func, ast.Name)
                and item.context_expr.func.id == "map_asset_publication"
                for item in node.items
            ):
                continue
            where = f"{path.name}:{node.lineno}"
            committing = [
                index
                for index, statement in enumerate(node.body)
                if _awaits_commit(statement)
            ]
            if len(committing) != 1:
                offenders.append(f"{where} has {len(committing)} commits, expected 1")
                continue
            commits += 1
            index = committing[0]
            if index == 0 or not _calls(node.body[index - 1], "committing"):
                offenders.append(f"{where} does not mark immediately before its commit")
            if index + 1 >= len(node.body) or not _calls(
                node.body[index + 1], "settled"
            ):
                offenders.append(
                    f"{where} does not settle immediately after its commit"
                )

    assert commits == 3, commits
    assert offenders == [], offenders


# ---------------------------------------------------------------------------
# fix(#1778 round 5): a failure after the commit must not roll anything back
# ---------------------------------------------------------------------------


class TestAFailureAfterTheCommitKeepsTheObject:
    """Once the row is committed the object is referenced, not pending.

    The rollback used to be keyed on whether the block raised, which is not the
    same question as whether the row committed. The icon route's
    `session.refresh` runs after a successful commit, so a failure there deleted
    an icon the committed row named.
    """

    async def test_a_refresh_that_raises_after_the_icon_commit_keeps_the_object(
        self, client: AsyncClient, admin_auth_header: dict, monkeypatch, test_db_session
    ) -> None:
        from sqlalchemy import delete, select

        from PIL import Image

        from app.modules.catalog.maps.models import MapIconAsset
        from app.modules.catalog.maps.sprites import clear_sprite_cache

        before = set(await _storage().list("maps/icons/"))

        async def _raise(self, *args, **kwargs):
            raise OSError("refresh failed after the row committed")

        monkeypatch.setattr(
            "sqlalchemy.ext.asyncio.AsyncSession.refresh", _raise, raising=True
        )

        png = BytesIO()
        Image.new("RGB", (8, 8), color=(4, 5, 6)).save(png, format="PNG")
        try:
            with pytest.raises(OSError):
                await client.post(
                    "/maps/icons",
                    files={"file": ("icon.png", png.getvalue(), "image/png")},
                    headers=admin_auth_header,
                )

            added = set(await _storage().list("maps/icons/")) - before
            assert len(added) == 1, added
        finally:
            # The row DID commit, which is the whole point, and icon rows are
            # deployment-global with no per-test cleanup. The storage provider is
            # per-test, so a row surviving into another test points the sprite
            # build at bytes under a tmp_path that no longer exists and the PNG
            # route raises FileNotFoundError. Take the row back out here.
            monkeypatch.undo()
            keys = [
                key for key in await _storage().list("maps/icons/") if key not in before
            ]
            if keys:
                await test_db_session.execute(
                    delete(MapIconAsset).where(MapIconAsset.storage_key.in_(keys))
                )
                await test_db_session.commit()
            clear_sprite_cache()
            assert (
                await test_db_session.execute(
                    select(MapIconAsset.id).where(MapIconAsset.storage_key.in_(keys))
                )
            ).first() is None

    async def test_a_settled_publication_rolls_nothing_back(self) -> None:
        """The unit shape of the same rule, without a route in the way."""
        from app.modules.catalog.maps.service import map_asset_publication

        deleted: list[str] = []

        class _Storage:
            async def delete(self, key: str) -> None:
                deleted.append(key)

        import app.platform.storage.provider as provider_module

        original = provider_module._storage
        provider_module._storage = _Storage()
        try:
            with pytest.raises(RuntimeError):
                async with map_asset_publication() as publication:
                    publication.record("maps/thumbnails/settled.jpg")
                    publication.settled()
                    raise RuntimeError("anything after the commit")
        finally:
            provider_module._storage = original

        assert deleted == []

    async def test_an_unsettled_publication_still_rolls_back(self) -> None:
        from app.modules.catalog.maps.service import map_asset_publication

        deleted: list[str] = []

        class _Storage:
            async def delete(self, key: str) -> None:
                deleted.append(key)

        import app.platform.storage.provider as provider_module

        original = provider_module._storage
        provider_module._storage = _Storage()
        try:
            with pytest.raises(RuntimeError):
                async with map_asset_publication() as publication:
                    publication.record("maps/thumbnails/pending.jpg")
                    raise RuntimeError("the row never committed")
        finally:
            provider_module._storage = original

        assert deleted == ["maps/thumbnails/pending.jpg"]


# ---------------------------------------------------------------------------
# fix(#1778 round 6): an indeterminate commit outcome deletes nothing
# ---------------------------------------------------------------------------


def _lose_the_ack_after_committing(monkeypatch):
    """Commit for real, then raise as if the connection died before the ack.

    The shape that matters: PostgreSQL has made the transaction durable and a
    second session can see it, and the await still raises. Keying the rollback
    on "did the block raise" deletes an object the committed row references.
    """
    from sqlalchemy.exc import OperationalError
    from sqlalchemy.ext.asyncio import AsyncSession

    original_commit = AsyncSession.commit

    async def _commit_then_lose_the_ack(self, *args, **kwargs):
        await original_commit(self, *args, **kwargs)
        raise OperationalError(
            "COMMIT", {}, Exception("connection reset before the acknowledgement")
        )

    monkeypatch.setattr(AsyncSession, "commit", _commit_then_lose_the_ack)
    return OperationalError


class TestAnIndeterminateCommitKeepsTheObject:
    @pytest.mark.parametrize(
        ("route", "prefix", "column"),
        [
            ("thumbnail", "maps/thumbnails", "thumbnail_uri"),
            ("og-image", "maps/og-images", "og_image_uri"),
        ],
    )
    async def test_an_image_the_row_committed_is_not_deleted(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        monkeypatch,
        test_db_session,
        route: str,
        prefix: str,
        column: str,
    ) -> None:
        from sqlalchemy import select

        from app.modules.catalog.maps.models import Map

        map_id = await _create_map(client, admin_auth_header)
        _lose_the_ack_after_committing(monkeypatch)

        # The app maps a lost connection to a 5xx rather than letting it out, so
        # the caller is told the upload failed for a row that did commit. That
        # is exactly why the object must not be deleted on the way out.
        resp = await client.put(
            f"/maps/{map_id}/{route}/",
            json={"data_uri": _jpeg_data_uri()},
            headers=admin_auth_header,
        )
        assert resp.status_code >= 500, resp.status_code

        monkeypatch.undo()
        # A second session: the row really is committed, which is what makes
        # deleting the object it names the wrong move.
        committed = (
            await test_db_session.execute(
                select(getattr(Map, column)).where(Map.id == uuid.UUID(map_id))
            )
        ).scalar_one()
        assert committed is not None
        assert await _storage().exists(committed)
        assert await _objects(prefix, map_id) == {committed}

        served = await client.get(f"/maps/{map_id}/{route}/", headers=admin_auth_header)
        assert served.status_code == 200, served.text

    async def test_an_icon_the_row_committed_is_not_deleted(
        self, client: AsyncClient, admin_auth_header: dict, monkeypatch, test_db_session
    ) -> None:
        from sqlalchemy import delete, select

        from PIL import Image

        from app.modules.catalog.maps.models import MapIconAsset
        from app.modules.catalog.maps.sprites import clear_sprite_cache

        before = set(await _storage().list("maps/icons/"))
        _lose_the_ack_after_committing(monkeypatch)

        png = BytesIO()
        Image.new("RGB", (8, 8), color=(7, 8, 9)).save(png, format="PNG")
        try:
            resp = await client.post(
                "/maps/icons",
                files={"file": ("icon.png", png.getvalue(), "image/png")},
                headers=admin_auth_header,
            )
            assert resp.status_code >= 500, resp.status_code

            monkeypatch.undo()
            added = set(await _storage().list("maps/icons/")) - before
            assert len(added) == 1, added
            key = added.pop()
            committed = (
                await test_db_session.execute(
                    select(MapIconAsset.id).where(MapIconAsset.storage_key == key)
                )
            ).scalar_one_or_none()
            assert committed is not None
            assert await _storage().exists(key)
        finally:
            monkeypatch.undo()
            keys = [k for k in await _storage().list("maps/icons/") if k not in before]
            if keys:
                await test_db_session.execute(
                    delete(MapIconAsset).where(MapIconAsset.storage_key.in_(keys))
                )
                await test_db_session.commit()
            clear_sprite_cache()

    async def test_a_marked_publication_rolls_nothing_back(self) -> None:
        """The unit shape: after the mark, an exception says nothing."""
        from app.modules.catalog.maps.service import map_asset_publication

        deleted: list[str] = []

        class _Storage:
            async def delete(self, key: str) -> None:
                deleted.append(key)

        import app.platform.storage.provider as provider_module

        original = provider_module._storage
        provider_module._storage = _Storage()
        try:
            with pytest.raises(RuntimeError):
                async with map_asset_publication() as publication:
                    publication.record("maps/thumbnails/in-flight.jpg")
                    publication.committing()
                    raise RuntimeError("the commit outcome never came back")
        finally:
            provider_module._storage = original

        assert deleted == []

    async def test_settling_restores_the_ordinary_rollback(self) -> None:
        """A later write in the same scope is not covered by an earlier mark."""
        from app.modules.catalog.maps.service import map_asset_publication

        deleted: list[str] = []

        class _Storage:
            async def delete(self, key: str) -> None:
                deleted.append(key)

        import app.platform.storage.provider as provider_module

        original = provider_module._storage
        provider_module._storage = _Storage()
        try:
            with pytest.raises(RuntimeError):
                async with map_asset_publication() as publication:
                    publication.committing()
                    publication.settled()
                    publication.record("maps/thumbnails/after-settling.jpg")
                    raise RuntimeError("a second write that never committed")
        finally:
            provider_module._storage = original

        assert deleted == ["maps/thumbnails/after-settling.jpg"]


# ---------------------------------------------------------------------------
# fix(#1778 round 7): a write whose outcome is ambiguous is still rolled back
# ---------------------------------------------------------------------------


def _put_then_fail_the_client(monkeypatch):
    """Write the object for real, then raise as object storage timing out.

    S3 and MinIO can durably accept a PUT and still fail the client with a
    timeout or a dropped connection. Recording the key only after the write
    returned left the ledger empty for exactly that case, so the object was
    never referenced by a row and never cleaned up, one more per retry.
    """
    storage = _storage()
    original_put = storage.put

    async def _put_then_raise(key: str, data):
        await original_put(key, data)
        raise TimeoutError("the object landed, the acknowledgement did not")

    monkeypatch.setattr(storage, "put", _put_then_raise)


class TestAnAmbiguousWriteIsRolledBack:
    @pytest.mark.parametrize(
        ("route", "prefix"),
        [("thumbnail", "maps/thumbnails"), ("og-image", "maps/og-images")],
    )
    async def test_the_object_is_deleted_even_though_the_put_raised(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        monkeypatch,
        route: str,
        prefix: str,
    ) -> None:
        map_id = await _create_map(client, admin_auth_header)
        _put_then_fail_the_client(monkeypatch)

        resp = await client.put(
            f"/maps/{map_id}/{route}/",
            json={"data_uri": _jpeg_data_uri()},
            headers=admin_auth_header,
        )

        assert resp.status_code == 502, resp.text
        assert await _objects(prefix, map_id) == set()

    async def test_every_retry_of_an_ambiguous_write_leaves_nothing(
        self, client: AsyncClient, admin_auth_header: dict, monkeypatch
    ) -> None:
        """The leak compounded because the keys are never reused."""
        map_id = await _create_map(client, admin_auth_header)
        _put_then_fail_the_client(monkeypatch)

        for _ in range(3):
            resp = await client.put(
                f"/maps/{map_id}/thumbnail/",
                json={"data_uri": _jpeg_data_uri()},
                headers=admin_auth_header,
            )
            assert resp.status_code == 502, resp.text

        assert await _objects("maps/thumbnails", map_id) == set()

    async def test_the_icon_object_is_deleted_too(
        self, client: AsyncClient, admin_auth_header: dict, monkeypatch
    ) -> None:
        from PIL import Image

        before = set(await _storage().list("maps/icons/"))
        _put_then_fail_the_client(monkeypatch)

        png = BytesIO()
        Image.new("RGB", (8, 8), color=(3, 2, 1)).save(png, format="PNG")
        with pytest.raises(TimeoutError):
            await client.post(
                "/maps/icons",
                files={"file": ("icon.png", png.getvalue(), "image/png")},
                headers=admin_auth_header,
            )

        assert set(await _storage().list("maps/icons/")) == before

    async def test_a_stored_image_survives_an_ambiguous_replacement(
        self, client: AsyncClient, admin_auth_header: dict, monkeypatch
    ) -> None:
        """The rollback removes the new key only, never the one on the row."""
        map_id = await _create_map(client, admin_auth_header)
        await client.put(
            f"/maps/{map_id}/thumbnail/",
            json={"data_uri": _jpeg_data_uri()},
            headers=admin_auth_header,
        )
        stored = await _the_object("maps/thumbnails", map_id)

        _put_then_fail_the_client(monkeypatch)
        resp = await client.put(
            f"/maps/{map_id}/thumbnail/",
            json={"data_uri": _png_data_uri()},
            headers=admin_auth_header,
        )

        assert resp.status_code == 502, resp.text
        assert await _objects("maps/thumbnails", map_id) == {stored}
        served = await client.get(
            f"/maps/{map_id}/thumbnail/", headers=admin_auth_header
        )
        assert served.status_code == 200, served.text

    async def test_deleting_a_key_that_was_never_written_is_a_no_op(
        self, client: AsyncClient
    ) -> None:
        """What makes recording before the write free, asserted on the provider."""
        await _storage().delete(f"maps/thumbnails/{uuid.uuid4()}-never-written.jpg")


# ---------------------------------------------------------------------------
# fix(audit finding, round 8): a contended map row fails fast, not slow
# ---------------------------------------------------------------------------


class TestLockMapForAssetWriteFailsFast:
    """``lock_map_for_asset_write`` bounds its wait with ``SET LOCAL lock_timeout``.

    Before this fix the row lock had no engine-side timeout: it was held from
    before the ``storage.put`` through the caller's commit, and the S3
    provider's connect/read timeouts plus its adaptive retries can run to
    roughly a minute on a degraded backend (``app/platform/storage/s3.py``).
    Every other writer to the same map queued behind that with no bound. A
    genuinely contended row (held here from a second, real database session,
    not mocked) must now fail with 409 within a couple of seconds rather than
    hang.
    """

    async def test_a_contended_map_row_returns_409_quickly(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
    ) -> None:
        import time

        from sqlalchemy import select

        from app.modules.catalog.maps.models import Map

        map_id = await _create_map(client, admin_auth_header)

        # A second, real session holds the row lock the app's request needs.
        # No commit/rollback until the assertions below are done with it.
        await test_db_session.execute(
            select(Map.id).where(Map.id == uuid.UUID(map_id)).with_for_update()
        )
        try:
            started = time.monotonic()
            resp = await client.put(
                f"/maps/{map_id}/thumbnail/",
                json={"data_uri": _jpeg_data_uri()},
                headers=admin_auth_header,
            )
            elapsed = time.monotonic() - started

            assert resp.status_code == 409, resp.text
            assert resp.json()["detail"]["code"] == "map_asset_write_locked"
            # lock_timeout is '2s'; generous slack for CI scheduling noise, but
            # nowhere near the ~190s an unbounded wait against a degraded
            # storage backend could reach.
            assert elapsed < 5, elapsed
        finally:
            await test_db_session.rollback()

        # The lock released with the second session's rollback; the same
        # request now succeeds instead of racing a lock that no longer exists.
        resp = await client.put(
            f"/maps/{map_id}/thumbnail/",
            json={"data_uri": _jpeg_data_uri()},
            headers=admin_auth_header,
        )
        assert resp.status_code == 204, resp.text

    async def test_the_icon_route_holds_no_per_map_lock(self) -> None:
        """The finding does not apply to icons: confirmed, not assumed.

        Icons are deliberately global (fix(#1621), see ``sprites.py``) and
        ``create_icon_asset`` never calls ``lock_map_for_asset_write`` or takes
        any ``with_for_update()`` of its own. There is no per-map row for an
        icon upload to contend on, so it has nothing to bound.
        """
        import ast
        import inspect

        from app.modules.catalog.maps import sprites as sprites_module

        source = inspect.getsource(sprites_module.create_icon_asset)
        tree = ast.parse(source)
        calls = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        assert "with_for_update" not in calls
        assert "lock_map_for_asset_write" not in source
