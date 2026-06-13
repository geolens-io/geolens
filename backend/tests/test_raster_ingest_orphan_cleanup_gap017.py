"""GAP-017 regression: raster ingest must not orphan storage assets on crash.

Raster ingest writes COG + quicklook bytes to managed storage BEFORE the
terminal DB commit. The storage key embeds ``dataset.id`` — a flushed-but-
uncommitted UUID. If the commit (or any step after the puts) fails, the dataset
row is rolled back and ``delete_dataset`` never reaps the bytes, leaving them
orphaned under ``rasters/{dataset_id}/`` with no reconcile path.

The fix records each written key and, on the failure path (``final_status !=
"complete"``), reaps exactly those keys via ``_cleanup_orphaned_storage_keys``.

These tests use a real ``LocalStorageProvider`` against a tmp dir so the
delete is genuinely exercised end-to-end.
"""

import io

import pytest

from app.platform.storage.local import LocalStorageProvider
from app.processing.ingest.tasks_raster import _cleanup_orphaned_storage_keys


@pytest.fixture
def storage(tmp_path):
    return LocalStorageProvider(str(tmp_path))


async def test_cleanup_removes_written_keys(storage, monkeypatch):
    """All keys written before a rolled-back commit are deleted."""
    monkeypatch.setattr(
        "app.platform.storage.get_storage", lambda: storage, raising=True
    )

    base = "rasters/0000-dead-beef/abc123"
    keys = [
        f"{base}/source.cog.tif",
        f"{base}/quicklook_256.png",
        f"{base}/quicklook_512.png",
    ]
    for k in keys:
        await storage.put(k, io.BytesIO(b"orphan-bytes"))
    for k in keys:
        assert await storage.exists(k), "precondition: asset written"

    await _cleanup_orphaned_storage_keys(keys, job_id="job-1")

    for k in keys:
        assert not await storage.exists(k), (
            f"GAP-017: orphaned asset {k} must be deleted on the failure path"
        )


async def test_crash_mid_put_cleans_already_written_keys(storage, monkeypatch):
    """Simulate a storage write that raises mid-ingest: the keys written before
    the crash are reaped, mirroring how ingest_raster's finally block calls
    _cleanup_orphaned_storage_keys with the keys recorded so far.
    """
    monkeypatch.setattr(
        "app.platform.storage.get_storage", lambda: storage, raising=True
    )

    base = "rasters/1111-cafe-f00d/def456"
    cog_key = f"{base}/source.cog.tif"
    ql256_key = f"{base}/quicklook_256.png"
    ql512_key = f"{base}/quicklook_512.png"

    written: list[str] = []
    real_put = storage.put

    async def flaky_put(key, data):
        # Crash on the third put (quicklook_512) — exactly the mid-write crash
        # the finding describes.
        if key == ql512_key:
            raise RuntimeError("simulated storage outage mid-ingest")
        result = await real_put(key, data)
        written.append(key)
        return result

    monkeypatch.setattr(storage, "put", flaky_put)

    # Drive the same put sequence ingest_raster uses, recording keys as it goes.
    with pytest.raises(RuntimeError):
        await storage.put(cog_key, io.BytesIO(b"cog"))
        await storage.put(ql256_key, io.BytesIO(b"ql256"))
        await storage.put(ql512_key, io.BytesIO(b"ql512"))  # raises

    # cog + ql256 landed; ql512 never did.
    assert written == [cog_key, ql256_key]
    assert await storage.exists(cog_key)
    assert await storage.exists(ql256_key)
    assert not await storage.exists(ql512_key)

    # The failure path reaps what was written — leaving zero orphans.
    await _cleanup_orphaned_storage_keys(written, job_id="job-2")

    assert not await storage.exists(cog_key)
    assert not await storage.exists(ql256_key)


async def test_cleanup_is_best_effort_on_delete_error(storage, monkeypatch):
    """A delete failure on one key must not abort cleanup of the rest, and must
    not raise (cleanup must never mask the original ingest error).
    """
    monkeypatch.setattr(
        "app.platform.storage.get_storage", lambda: storage, raising=True
    )

    good_key = "rasters/x/y/quicklook_256.png"
    bad_key = "rasters/x/y/source.cog.tif"
    await storage.put(good_key, io.BytesIO(b"ok"))

    real_delete = storage.delete

    async def flaky_delete(key):
        if key == bad_key:
            raise RuntimeError("delete blew up")
        return await real_delete(key)

    monkeypatch.setattr(storage, "delete", flaky_delete)

    # Must not raise despite bad_key delete failing.
    await _cleanup_orphaned_storage_keys([bad_key, good_key], job_id="job-3")

    # good_key was still cleaned even though bad_key's delete raised.
    assert not await storage.exists(good_key)
