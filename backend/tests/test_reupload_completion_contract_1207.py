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
