"""#1207: the presigned reupload door enforces the upload door's contract.

Every regression class from ``test_presigned_content_validation_1202.py``,
ported to this surface. The doors are compared to their OWN sibling — the
reupload direct door — because the taxonomies differ: this surface stamps a
failed-job audit trail before raising a content 422, and refuses ``.vrt`` with
a 400 rather than the upload door's 422.

The helpers under test are shared with the upload door, so these tests exist
to prove this door WIRES them, and wires them in the right order — not to
re-test the helpers themselves.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.modules.catalog.datasets.api import router_reupload
from app.modules.catalog.datasets.domain.models import Dataset, Record
from app.platform.jobs.models import IngestJob


pytestmark = pytest.mark.anyio


_GIF_PAYLOAD = b"GIF89a" + b"\x00" * 512
_VALID_GEOJSON = b'{"type":"FeatureCollection","features":[]}'
# Same LENGTH as the valid payload so the declared-size check cannot reject a
# replay before the one-shot guard does. See the #1202 sibling file.
_SAME_SIZE_GARBAGE = b"X" * len(_VALID_GEOJSON)


class _FakeS3Storage:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.range_reads: list[tuple[str, int, int]] = []
        self.whole_object_reads: list[str] = []
        self.copies: list[tuple[str, str]] = []

    def generate_presigned_put_url(self, key: str, content_type: str) -> str:
        return f"https://s3.invalid/{key}?signed=1"

    async def exists(self, key: str) -> bool:
        return key in self.objects

    async def size(self, key: str) -> int:
        return len(self.objects[key])

    async def copy(self, src_key: str, dst_key: str) -> None:
        self.copies.append((src_key, dst_key))
        self.objects[dst_key] = self.objects[src_key]

    async def get_range(self, key: str, start: int, length: int) -> bytes:
        self.range_reads.append((key, start, length))
        return self.objects[key][start : start + length]

    async def get(self, key: str) -> bytes:
        self.whole_object_reads.append(key)
        return self.objects[key]

    async def get_to_file(self, key: str, dest: Path) -> Path:
        self.whole_object_reads.append(key)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(self.objects[key])
        return dest

    async def delete(self, key: str) -> None:
        self.objects.pop(key, None)


async def _create_dataset(session, *, created_by: uuid.UUID) -> Dataset:
    """Insert a Record + Dataset pair. Mirrors test_reupload.py's helper."""
    record = Record(
        title="Reupload Contract Dataset",
        summary="#1207",
        visibility="public",
        record_status="published",
        record_type="vector_dataset",
        created_by=created_by,
    )
    session.add(record)
    await session.flush()
    dataset = Dataset(
        record_id=record.id,
        table_name=f"ds_{uuid.uuid4().hex[:12]}",
        srid=4326,
        geometry_type="MultiPolygon",
        feature_count=1,
        source_format="geojson",
        source_filename="original.geojson",
        column_info=[{"name": "name", "type": "String"}],
    )
    session.add(dataset)
    await session.commit()
    await session.refresh(dataset)
    return dataset


@pytest.fixture
def both_reupload_doors(monkeypatch, tmp_path):
    """Both reupload doors drivable against one fake bucket.

    The catalog port is pinned to one instance so patches reach the router,
    matching test_reupload.py. `validate_file_content` is deliberately NOT
    mocked — it is the contract under test.
    """
    storage = _FakeS3Storage()
    monkeypatch.setattr(settings, "storage_provider", "s3")
    monkeypatch.setattr(router_reupload, "get_storage", lambda: storage, raising=True)
    monkeypatch.setattr(
        "app.platform.storage.get_storage", lambda: storage, raising=True
    )

    port = router_reupload.get_catalog_port()

    async def _fake_save(file, job_id: str, *, max_size_bytes: int | None = None):
        staging = tmp_path / "staging"
        staging.mkdir(parents=True, exist_ok=True)
        out = staging / f"{job_id}{Path(file.filename or '').suffix or '.bin'}"
        out.write_bytes(await file.read())
        await file.seek(0)
        return out

    mock_task = AsyncMock()
    with (
        patch.object(router_reupload, "get_catalog_port", return_value=port),
        patch.object(port, "save_upload_file", AsyncMock(side_effect=_fake_save)),
        patch.object(port, "reupload_file_task", return_value=mock_task),
    ):
        yield storage


def frozen_key_absent(storage, job_id: str) -> bool:
    """No `staging/{job}/frozen/...` object exists for this job."""
    return not any(
        key.startswith(f"staging/{job_id}/frozen/") for key in storage.objects
    )


async def _admin_id(session) -> uuid.UUID:
    from app.modules.auth.models import User

    admin = (
        await session.execute(select(User).where(User.username == "admin"))
    ).scalar_one()
    return admin.id


async def _direct_reupload(client, headers, dataset_id, filename, payload):
    return await client.post(
        f"/datasets/{dataset_id}/reupload",
        files={"file": (filename, payload, "application/octet-stream")},
        headers=headers,
    )


async def _presigned_reupload(client, headers, storage, dataset_id, filename, payload):
    resp = await client.post(
        f"/datasets/{dataset_id}/reupload/presigned",
        json={
            "filename": filename,
            "file_size": len(payload),
            "content_type": "application/octet-stream",
        },
        headers=headers,
    )
    assert resp.status_code in (200, 201), resp.text
    body = resp.json()
    storage.objects[body["s3_key"]] = payload
    completion = await client.post(
        f"/datasets/{dataset_id}/reupload/presigned/{body['job_id']}/complete",
        json={},
        headers=headers,
    )
    return completion, body["job_id"], body["s3_key"]


async def test_both_reupload_doors_reject_a_mislabeled_payload_identically(
    client, admin_auth_header, test_db_session, both_reupload_doors
) -> None:
    """The gap this issue exists for: the completion door accepted what its
    own sibling refuses."""
    dataset = await _create_dataset(
        test_db_session, created_by=await _admin_id(test_db_session)
    )

    direct = await _direct_reupload(
        client, admin_auth_header, dataset.id, "update.geojson", _GIF_PAYLOAD
    )
    presigned, _job_id, _key = await _presigned_reupload(
        client,
        admin_auth_header,
        both_reupload_doors,
        dataset.id,
        "update.geojson",
        _GIF_PAYLOAD,
    )

    assert direct.status_code == 422, direct.text
    assert presigned.status_code == direct.status_code, presigned.text
    assert presigned.json()["detail"] == direct.json()["detail"]
    assert "'.gif'" in direct.json()["detail"]


async def test_both_reupload_doors_accept_a_legitimate_payload(
    client, admin_auth_header, test_db_session, both_reupload_doors
) -> None:
    """The admission half — a refusal test alone cannot see over-rejection."""
    dataset = await _create_dataset(
        test_db_session, created_by=await _admin_id(test_db_session)
    )

    direct = await _direct_reupload(
        client, admin_auth_header, dataset.id, "update.geojson", _VALID_GEOJSON
    )
    presigned, _job_id, _key = await _presigned_reupload(
        client,
        admin_auth_header,
        both_reupload_doors,
        dataset.id,
        "update.geojson",
        _VALID_GEOJSON,
    )

    assert direct.status_code == 201, direct.text
    assert presigned.status_code == 200, presigned.text


async def test_a_content_rejection_keeps_this_surface_s_failed_job_trail(
    client, admin_auth_header, test_db_session, both_reupload_doors
) -> None:
    """Surface-local taxonomy, and the reason parity is with the sibling door.

    The direct reupload door commits `status="failed"` plus `error_message`
    before raising its 422 — a provenance test asserts that trail. The
    completion door must do the same, which is the one place this fix
    deliberately diverges from the upload door's behaviour.
    """
    dataset = await _create_dataset(
        test_db_session, created_by=await _admin_id(test_db_session)
    )

    presigned, job_id, _key = await _presigned_reupload(
        client,
        admin_auth_header,
        both_reupload_doors,
        dataset.id,
        "update.geojson",
        _GIF_PAYLOAD,
    )
    assert presigned.status_code == 422, presigned.text

    job = (
        await test_db_session.execute(
            select(IngestJob).where(IngestJob.id == uuid.UUID(job_id))
        )
    ).scalar_one()
    await test_db_session.refresh(job)
    assert job.status == "failed"
    assert "'.gif'" in (job.error_message or "")


async def test_a_rejected_presigned_reupload_removes_both_objects(
    client, admin_auth_header, test_db_session, both_reupload_doors
) -> None:
    dataset = await _create_dataset(
        test_db_session, created_by=await _admin_id(test_db_session)
    )

    presigned, _job_id, staging_key = await _presigned_reupload(
        client,
        admin_auth_header,
        both_reupload_doors,
        dataset.id,
        "update.geojson",
        _GIF_PAYLOAD,
    )

    assert presigned.status_code == 422, presigned.text
    assert both_reupload_doors.objects == {}, both_reupload_doors.objects
    assert staging_key not in both_reupload_doors.objects


async def test_a_late_reput_cannot_swap_the_validated_bytes(
    client, admin_auth_header, test_db_session, both_reupload_doors
) -> None:
    """The TOCTOU, ported. This door bound the client-writable staging key."""
    dataset = await _create_dataset(
        test_db_session, created_by=await _admin_id(test_db_session)
    )

    presigned, job_id, staging_key = await _presigned_reupload(
        client,
        admin_auth_header,
        both_reupload_doors,
        dataset.id,
        "update.geojson",
        _VALID_GEOJSON,
    )
    assert presigned.status_code == 200, presigned.text

    job = (
        await test_db_session.execute(
            select(IngestJob).where(IngestJob.id == uuid.UUID(job_id))
        )
    ).scalar_one()
    await test_db_session.refresh(job)

    assert job.file_path != staging_key, "still bound to the client-writable key"
    assert job.file_path.endswith("/frozen/update.geojson")

    both_reupload_doors.objects[staging_key] = _GIF_PAYLOAD
    assert both_reupload_doors.objects[job.file_path] == _VALID_GEOJSON


async def test_a_second_reupload_completion_is_refused(
    client, admin_auth_header, test_db_session, both_reupload_doors
) -> None:
    """One-shot, ported. The replay payload matches the original's LENGTH so
    the declared-size check cannot reject it before the guard does."""
    dataset = await _create_dataset(
        test_db_session, created_by=await _admin_id(test_db_session)
    )

    presigned, job_id, staging_key = await _presigned_reupload(
        client,
        admin_auth_header,
        both_reupload_doors,
        dataset.id,
        "update.geojson",
        _VALID_GEOJSON,
    )
    assert presigned.status_code == 200, presigned.text
    job = (
        await test_db_session.execute(
            select(IngestJob).where(IngestJob.id == uuid.UUID(job_id))
        )
    ).scalar_one()
    await test_db_session.refresh(job)
    frozen_key = job.file_path

    both_reupload_doors.objects[staging_key] = _SAME_SIZE_GARBAGE
    replay = await client.post(
        f"/datasets/{dataset.id}/reupload/presigned/{job_id}/complete",
        json={},
        headers=admin_auth_header,
    )

    assert replay.status_code == 400, replay.text
    assert "already completed" in replay.json()["detail"].lower()
    assert both_reupload_doors.objects[frozen_key] == _VALID_GEOJSON


async def test_reupload_completion_does_not_download_the_object(
    client, admin_auth_header, test_db_session, both_reupload_doors
) -> None:
    """Read-width pin, ported — presigned reuploads exist for large files."""
    dataset = await _create_dataset(
        test_db_session, created_by=await _admin_id(test_db_session)
    )

    presigned, _job_id, _key = await _presigned_reupload(
        client,
        admin_auth_header,
        both_reupload_doors,
        dataset.id,
        "update.geojson",
        _VALID_GEOJSON,
    )

    assert presigned.status_code == 200, presigned.text
    assert both_reupload_doors.whole_object_reads == []
    total = sum(length for _k, _s, length in both_reupload_doors.range_reads)
    assert total <= 8192 + 4, both_reupload_doors.range_reads


async def test_a_failed_reupload_sweeps_its_presigned_staging_object(
    client, admin_auth_header, test_db_session, tmp_path, monkeypatch
) -> None:
    """The gap with NO upload-door equivalent, so nothing could be copied.

    ``reupload_file`` unlinked local files only — it never deleted a storage
    object — and the stale purge is not a backstop here, because a successful
    reupload job is the per-dataset latest-complete row it exempts forever. So
    every reupload staging object lived indefinitely, recreatable through the
    client's unexpired PUT URL.

    Driven to the terminal ``finally`` through the validation failure, the
    cheapest deterministic one: an operator lowering the size cap between
    completion and worker pickup.
    """
    from app.core.persistent_config import UPLOAD_MAX_SIZE_MB
    from app.platform.storage.local import LocalStorageProvider
    from app.processing.ingest.tasks_reupload import reupload_file

    bucket = tmp_path / "bucket"
    bucket.mkdir()
    storage = LocalStorageProvider(str(bucket))
    monkeypatch.setattr(
        "app.platform.storage.get_storage", lambda: storage, raising=True
    )

    source = tmp_path / "update.geojson"
    source.write_bytes(_VALID_GEOJSON)

    admin_id = await _admin_id(test_db_session)
    dataset = await _create_dataset(test_db_session, created_by=admin_id)

    job = IngestJob(
        source_filename="update.geojson",
        dataset_id=dataset.id,
        created_by=admin_id,
        status="pending",
        file_path=str(source),
        user_metadata={"reupload": True, "dataset_id": str(dataset.id)},
    )
    test_db_session.add(job)
    await test_db_session.commit()
    await test_db_session.refresh(job)

    staging_key = f"staging/{job.id}/update.geojson"
    job.user_metadata = {**job.user_metadata, "s3_key": staging_key}
    await test_db_session.commit()

    await storage.put(staging_key, b"the-client-uploaded-bytes")
    assert await storage.exists(staging_key), "precondition: staging object present"

    with patch.object(UPLOAD_MAX_SIZE_MB, "get", AsyncMock(return_value=0)):
        await reupload_file.func(
            job_id=str(job.id),
            dataset_id=str(dataset.id),
            file_path=str(source),
            user_id=str(admin_id),
            attempt_id=str(job.attempt_id),
        )

    await test_db_session.refresh(job)
    assert job.status == "failed", "precondition: took the validation-failure path"
    assert not await storage.exists(staging_key), (
        "the reupload task left its presigned staging object behind; nothing "
        "else reaps it (the stale purge exempts latest-complete)"
    )


async def test_a_pipeline_failure_after_validation_still_sweeps_the_staging_object(
    client, admin_auth_header, test_db_session, tmp_path, monkeypatch
) -> None:
    """fix(#1213 review r1): the broad-except path, not the early return.

    The sibling test above fails inside the early validation block, which sets
    `final_status = "failed"` on its way out. Everything AFTER that block — CRS
    detection, ogr2ogr, staging-table work — unwinds through the broad
    `except Exception`, which wrote status=failed to the DB row but left the
    LOCAL `final_status` at "pending". The terminal-status guard in
    `reap_presigned_staging_object` then returned without deleting anything, so
    on every one of those paths the client-writable staging object survived.

    `reupload_file` is retry=0, so an exception there is terminal — there is no
    later attempt that could need the bytes, and the stale purge exempts this
    surface's latest-complete rows forever. "Survived" means permanently.
    """
    from app.platform.storage.local import LocalStorageProvider
    from app.processing.ingest import tasks_reupload
    from app.processing.ingest.tasks_reupload import reupload_file

    bucket = tmp_path / "bucket"
    bucket.mkdir()
    storage = LocalStorageProvider(str(bucket))
    monkeypatch.setattr(
        "app.platform.storage.get_storage", lambda: storage, raising=True
    )

    source = tmp_path / "update.geojson"
    source.write_bytes(_VALID_GEOJSON)

    admin_id = await _admin_id(test_db_session)
    dataset = await _create_dataset(test_db_session, created_by=admin_id)

    job = IngestJob(
        source_filename="update.geojson",
        dataset_id=dataset.id,
        created_by=admin_id,
        status="pending",
        file_path=str(source),
        user_metadata={"reupload": True, "dataset_id": str(dataset.id)},
    )
    test_db_session.add(job)
    await test_db_session.commit()
    await test_db_session.refresh(job)

    staging_key = f"staging/{job.id}/update.geojson"
    job.user_metadata = {**job.user_metadata, "s3_key": staging_key}
    await test_db_session.commit()

    await storage.put(staging_key, b"the-client-uploaded-bytes")
    assert await storage.exists(staging_key), "precondition: staging object present"

    async def _boom(*_args, **_kwargs):
        raise RuntimeError("ogrinfo blew up after validation")

    # The first phase-2 step, so validation has already passed: the run
    # unwinds through the broad except rather than the early return.
    monkeypatch.setattr(tasks_reupload, "_detect_reupload_crs", _boom)

    with pytest.raises(RuntimeError, match="blew up after validation"):
        await reupload_file.func(
            job_id=str(job.id),
            dataset_id=str(dataset.id),
            file_path=str(source),
            user_id=str(admin_id),
            attempt_id=str(job.attempt_id),
        )

    await test_db_session.refresh(job)
    assert job.status == "failed", "precondition: took the broad-except path"
    assert not await storage.exists(staging_key), (
        "a post-validation pipeline failure left the presigned staging object "
        "behind — the finally reap saw final_status='pending' and skipped it"
    )


async def test_a_successful_reupload_deletes_the_frozen_object_too(
    client, admin_auth_header, test_db_session, tmp_path, monkeypatch
) -> None:
    """fix(#1213 review r2): the frozen copy is storage too, and it lingered.

    Completion binds the job to `staging/{job}/frozen/...`; the task then
    downloads THAT and ingests. The tail unlinked only the local download and
    swept only the client-writable original, so the frozen object survived — and
    a successful reupload job is its dataset's latest-complete row, which the
    stale purge exempts forever.

    The upload door's tail has always had this block (#430 BA-09); the reupload
    tail shipped without it. Both now call one shared helper.
    """
    from app.platform.storage.local import LocalStorageProvider
    from app.processing.ingest import tasks_reupload
    from app.processing.ingest.tasks_reupload import reupload_file

    bucket = tmp_path / "bucket"
    bucket.mkdir()
    storage = LocalStorageProvider(str(bucket))
    monkeypatch.setattr(
        "app.platform.storage.get_storage", lambda: storage, raising=True
    )

    admin_id = await _admin_id(test_db_session)
    dataset = await _create_dataset(test_db_session, created_by=admin_id)

    job = IngestJob(
        source_filename="update.geojson",
        dataset_id=dataset.id,
        created_by=admin_id,
        status="pending",
        user_metadata={"reupload": True, "dataset_id": str(dataset.id)},
    )
    test_db_session.add(job)
    await test_db_session.commit()
    await test_db_session.refresh(job)

    # Exactly what a completed presigned reupload leaves: bound to the frozen
    # snapshot, with the client-writable original still named in metadata.
    staging_key = f"staging/{job.id}/update.geojson"
    frozen_key = f"staging/{job.id}/frozen/update.geojson"
    job.file_path = frozen_key
    job.user_metadata = {**job.user_metadata, "s3_key": staging_key}
    await test_db_session.commit()

    await storage.put(staging_key, _VALID_GEOJSON)
    await storage.put(frozen_key, _VALID_GEOJSON)

    local_copy = tmp_path / "downloaded.geojson"
    local_copy.write_bytes(_VALID_GEOJSON)

    async def _fake_resolve(path, job_id_arg):
        # Stand in for the S3 download: returns a DIFFERENT local path, which
        # is the signal the tail keys off to know it fetched from storage.
        return str(local_copy)

    monkeypatch.setattr(
        "app.processing.ingest.service.resolve_file_path", _fake_resolve
    )

    async def _boom(*_args, **_kwargs):
        raise RuntimeError("stop after the download")

    monkeypatch.setattr(tasks_reupload, "_detect_reupload_crs", _boom)

    with pytest.raises(RuntimeError, match="stop after the download"):
        await reupload_file.func(
            job_id=str(job.id),
            dataset_id=str(dataset.id),
            file_path=frozen_key,
            user_id=str(admin_id),
            attempt_id=str(job.attempt_id),
        )

    assert not await storage.exists(frozen_key), (
        "the frozen object the job was bound to survived the task; nothing "
        "else reaps it once the job becomes its dataset's latest-complete"
    )
    assert not await storage.exists(staging_key), (
        "the client-writable original should still be swept as well"
    )


async def test_a_failed_job_cannot_be_completed_by_a_late_reput(
    client, admin_auth_header, test_db_session, both_reupload_doors
) -> None:
    """fix(#1213 review r3): the second one-shot fact — terminal status.

    A content refusal stamps `status="failed"` with `file_path` still empty, so
    a guard that checks only `file_path` lets the client re-PUT and complete
    again. That call used to 200 and bind a frozen object, while preview and
    commit refused the row for being already processed: the 200 is a lie, the
    recovery path is dead, and the frozen object is unowned — no task tail runs
    for a job nothing was deferred for.
    """
    dataset = await _create_dataset(
        test_db_session, created_by=await _admin_id(test_db_session)
    )

    refused, job_id, staging_key = await _presigned_reupload(
        client,
        admin_auth_header,
        both_reupload_doors,
        dataset.id,
        "update.geojson",
        _GIF_PAYLOAD,
    )
    assert refused.status_code == 422, refused.text

    job = (
        await test_db_session.execute(
            select(IngestJob).where(IngestJob.id == uuid.UUID(job_id))
        )
    ).scalar_one()
    await test_db_session.refresh(job)
    assert job.status == "failed", "precondition: the refusal stamped the trail"
    assert not job.file_path, "precondition: nothing was bound"

    # The refused attempt legitimately froze before validation rejected it and
    # then deleted both objects, so baseline the copy log rather than assuming
    # it is empty — the claim is that the RETRY creates nothing new.
    copies_before = len(both_reupload_doors.copies)

    # The client re-PUTs good bytes through its still-valid URL and retries.
    both_reupload_doors.objects[staging_key] = _VALID_GEOJSON
    retry = await client.post(
        f"/datasets/{dataset.id}/reupload/presigned/{job_id}/complete",
        json={},
        headers=admin_auth_header,
    )

    assert retry.status_code == 400, retry.text
    assert "already failed" in retry.json()["detail"].lower()
    assert "start the reupload again" in retry.json()["detail"].lower()

    await test_db_session.refresh(job)
    assert not job.file_path, "a failed job must not end up bound"
    assert len(both_reupload_doors.copies) == copies_before, (
        "no frozen object may be created for a job no task will ever run"
    )
    # The client's own re-PUT object survives, and should: the guard refuses
    # before the handler touches storage, so nothing here ever owned those
    # bytes. The post-expiry sweep reaps them once the PUT URL is dead — the
    # job carries `s3_key` and is terminal, which is exactly that pass's
    # candidate set.
    assert staging_key in both_reupload_doors.objects
    assert frozen_key_absent(both_reupload_doors, job_id)


async def test_a_failed_download_still_sweeps_the_frozen_object(
    client, admin_auth_header, test_db_session, tmp_path, monkeypatch
) -> None:
    """fix(#1213 review r4): the reaper keyed off the wrong signal.

    It required `file_path != original_file_path` — the path rewrite
    `resolve_file_path` performs when it downloads. That conflates "was
    downloaded" with "came from storage", and a download that RAISES is where
    the two come apart: no rewrite happened, the equality held, and the reaper
    skipped. An S3 timeout therefore left the frozen snapshot behind on a job
    that is terminally failed and, on this surface, not even retryable.

    The `staging/` prefix is the real signal and is what the guard uses now.
    """
    from app.platform.storage.local import LocalStorageProvider
    from app.processing.ingest.tasks_reupload import reupload_file

    bucket = tmp_path / "bucket"
    bucket.mkdir()
    storage = LocalStorageProvider(str(bucket))
    monkeypatch.setattr(
        "app.platform.storage.get_storage", lambda: storage, raising=True
    )

    admin_id = await _admin_id(test_db_session)
    dataset = await _create_dataset(test_db_session, created_by=admin_id)

    job = IngestJob(
        source_filename="update.geojson",
        dataset_id=dataset.id,
        created_by=admin_id,
        status="pending",
        user_metadata={"reupload": True, "dataset_id": str(dataset.id)},
    )
    test_db_session.add(job)
    await test_db_session.commit()
    await test_db_session.refresh(job)

    staging_key = f"staging/{job.id}/update.geojson"
    frozen_key = f"staging/{job.id}/frozen/update.geojson"
    job.file_path = frozen_key
    job.user_metadata = {**job.user_metadata, "s3_key": staging_key}
    await test_db_session.commit()

    await storage.put(staging_key, _VALID_GEOJSON)
    await storage.put(frozen_key, _VALID_GEOJSON)

    async def _download_explodes(path, job_id_arg=None):
        raise RuntimeError("S3 timed out fetching the source")

    monkeypatch.setattr(
        "app.processing.ingest.service.resolve_file_path", _download_explodes
    )

    with pytest.raises(RuntimeError, match="S3 timed out"):
        await reupload_file.func(
            job_id=str(job.id),
            dataset_id=str(dataset.id),
            file_path=frozen_key,
            user_id=str(admin_id),
            attempt_id=str(job.attempt_id),
        )

    await test_db_session.refresh(job)
    assert job.status == "failed", "precondition: the run is terminal"
    assert not await storage.exists(frozen_key), (
        "a download failure left the frozen snapshot behind — the reaper keyed "
        "off the path rewrite, which never happens when the download raises"
    )
    assert not await storage.exists(staging_key), (
        "and the client-writable original should still be swept"
    )
