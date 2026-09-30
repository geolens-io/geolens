"""Task-ending source disposal across filesystem and storage-backed uploads."""

import asyncio
from pathlib import Path

import pytest

from app.platform.storage.local import LocalStorageProvider
from app.processing.ingest.publication import PublicationCommit
from app.processing.ingest.uploaded_source import UploadedSource

pytestmark = pytest.mark.anyio

_FROZEN = "staging/job-1/frozen/source.bin"
_CLIENT = "staging/job-1/source.bin"
_PUBLICATIONS = [None, *PublicationCommit]


@pytest.fixture
async def uploaded(tmp_path, monkeypatch):
    storage = LocalStorageProvider(str(tmp_path / "objects"))
    monkeypatch.setattr("app.platform.storage.get_storage", lambda: storage)
    await storage.put(_FROZEN, b"original")
    await storage.put(_CLIENT, b"client-writable")
    local = tmp_path / "source.bin"
    local.write_bytes(b"original")
    return storage, local


def _source(local, *, downloaded=True, shared=False):
    return UploadedSource(
        job_id="job-1",
        original_path=_FROZEN if downloaded else str(local),
        local_path=str(local),
        owned_presigned_key=None if shared else _CLIENT,
        shared=shared,
    )


@pytest.mark.parametrize("status", ["complete", "failed", "pending"])
@pytest.mark.parametrize("archived", [False, True])
@pytest.mark.parametrize("shared", [False, True])
@pytest.mark.parametrize("downloaded", [False, True])
async def test_import_preserves_shared_retryable_and_unarchived_input(
    uploaded, status, archived, shared, downloaded
):
    storage, local = uploaded
    source = _source(local, downloaded=downloaded, shared=shared)

    await source.release_import(final_status=status, archive_confirmed=archived)

    unlinked = downloaded or (not shared and status == "complete" and archived)
    assert local.exists() is not unlinked
    frozen_reaped = downloaded and not shared and status == "complete" and archived
    assert await storage.exists(_FROZEN) is not frozen_reaped
    client_reaped = not shared and status in ("complete", "failed")
    assert await storage.exists(_CLIENT) is not client_reaped


@pytest.mark.parametrize("publication", _PUBLICATIONS)
@pytest.mark.parametrize("failed", [False, True])
@pytest.mark.parametrize("refused", [False, True])
@pytest.mark.parametrize("downloaded", [False, True])
async def test_file_replacement_leaves_published_input_to_archive_followups(
    uploaded, publication, failed, refused, downloaded
):
    storage, local = uploaded
    source = _source(local, downloaded=downloaded)

    await source.release_file_replacement(
        publication=publication, failed=failed, refused=refused
    )

    acknowledged = publication is PublicationCommit.ACKNOWLEDGED
    failed_cleanup = failed and not acknowledged
    assert local.exists() is not (downloaded or refused)
    assert await storage.exists(_FROZEN) is not (downloaded and failed_cleanup)
    assert await storage.exists(_CLIENT) is not (acknowledged or failed_cleanup)


@pytest.mark.parametrize("publication", _PUBLICATIONS)
@pytest.mark.parametrize("failed", [False, True])
@pytest.mark.parametrize("preserved", [False, True])
@pytest.mark.parametrize("downloaded", [False, True])
async def test_raster_replacement_requires_acknowledged_preservation_to_dispose_input(
    uploaded, publication, failed, preserved, downloaded
):
    storage, local = uploaded
    source = _source(local, downloaded=downloaded)

    await source.release_raster_replacement(
        publication=publication, failed=failed, original_preserved=preserved
    )

    acknowledged = publication is PublicationCommit.ACKNOWLEDGED
    assert local.exists() is not (downloaded or (acknowledged and preserved))
    assert await storage.exists(_FROZEN) is not (
        downloaded and acknowledged and preserved
    )
    assert await storage.exists(_CLIENT) is not (acknowledged or failed)


async def test_an_import_keeps_its_only_local_original_when_the_archive_failed(
    uploaded,
):
    _, local = uploaded

    await _source(local, downloaded=False).release_import(
        final_status="complete", archive_confirmed=False
    )

    assert local.read_bytes() == b"original"


@pytest.mark.parametrize(
    "failure", [RuntimeError("provider unavailable"), asyncio.CancelledError()]
)
async def test_a_failed_frozen_delete_still_disposes_the_presigned_key(
    uploaded, monkeypatch, failure
):
    storage, local = uploaded
    delete = storage.delete

    async def fail_frozen(key):
        if key == _FROZEN:
            raise failure
        await delete(key)

    monkeypatch.setattr(storage, "delete", fail_frozen)

    await _source(local).release_import(final_status="complete", archive_confirmed=True)

    assert not local.exists()
    assert await storage.exists(_FROZEN)
    assert not await storage.exists(_CLIENT)


async def test_a_failed_local_unlink_still_disposes_both_storage_objects(
    uploaded, monkeypatch
):
    storage, local = uploaded
    unlink = Path.unlink

    def fail_local(path, *args, **kwargs):
        if path == local:
            raise OSError("local file unavailable")
        return unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_local)

    await _source(local).release_import(final_status="complete", archive_confirmed=True)

    assert local.exists()
    assert not await storage.exists(_FROZEN)
    assert not await storage.exists(_CLIENT)


async def test_a_failed_presigned_delete_cannot_fail_a_published_import(
    uploaded, monkeypatch
):
    storage, local = uploaded
    delete = storage.delete

    async def fail_client(key):
        if key == _CLIENT:
            raise RuntimeError("provider unavailable")
        await delete(key)

    monkeypatch.setattr(storage, "delete", fail_client)

    await _source(local).release_import(final_status="complete", archive_confirmed=True)

    assert not local.exists()
    assert not await storage.exists(_FROZEN)
    assert await storage.exists(_CLIENT)


async def test_raster_disposes_the_client_key_before_a_slow_frozen_delete(
    uploaded, monkeypatch
):
    storage, local = uploaded
    delete = storage.delete
    deleting_frozen = asyncio.Event()
    release_frozen = asyncio.Event()

    async def block_frozen(key):
        if key == _FROZEN:
            deleting_frozen.set()
            await release_frozen.wait()
        await delete(key)

    monkeypatch.setattr(storage, "delete", block_frozen)
    task = asyncio.create_task(
        _source(local).release_raster_replacement(
            publication=PublicationCommit.ACKNOWLEDGED,
            failed=False,
            original_preserved=True,
        )
    )
    try:
        await asyncio.wait_for(deleting_frozen.wait(), timeout=3)
        assert not await storage.exists(_CLIENT)
    finally:
        release_frozen.set()
        await task

    assert not await storage.exists(_FROZEN)
