"""Regression coverage for #1202: both ingest doors enforce one content contract.

``POST /ingest/upload`` content-validates the bytes it stages. The presigned
completion endpoint did not — it stamped metadata and committed — so a client
that presigned could land a file the direct door refuses, and preview handed
that unvalidated file to GDAL seconds later.

Every test here drives BOTH doors with the same payload and compares the
outcome, because the bug was never "one door is wrong" but "the two doors
disagree". The refusal cases and the admission cases are both pinned: a fix
that only tightens refusals lets the false-positive half regress silently.
"""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.core.config import settings


pytestmark = pytest.mark.anyio


# A GIF header is binary (null bytes, so the text-content escape hatch does not
# apply) and puremagic names it exactly, which makes the rejection message a
# concrete string both doors must produce character for character.
_GIF_PAYLOAD = b"GIF89a" + b"\x00" * 512
_VALID_GEOJSON = b'{"type":"FeatureCollection","features":[]}'

# Same LENGTH as the valid GeoJSON, deliberately. A replay payload of a
# different size is caught by the declared-size check, which masks the swap
# this file is trying to observe and makes the one-shot test pass for a
# reason that is not the guard. Do not "simplify" this to a different payload.
_SAME_SIZE_GARBAGE = b"X" * len(_VALID_GEOJSON)

# Parquet carries its magic at BOTH ends. Sized past the header window on
# purpose: the completion path reads the first 8192 bytes, so the trailing
# magic can only come from a second, separately ranged read.
_PARQUET_FILLER = b"\x00" * 20_000
_VALID_PARQUET = b"PAR1" + _PARQUET_FILLER + b"PAR1"
_TRUNCATED_PARQUET = b"PAR1" + _PARQUET_FILLER + b"\x00\x00\x00\x00"


class _FakeS3Storage:
    """In-memory stand-in for the S3 provider, keyed like the real one.

    Records every read so a test can assert what the completion path touched
    — the point of the fix is that it validates without downloading the
    object, and only a recording fake can tell those two apart.
    """

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.range_reads: list[tuple[str, int, int]] = []
        self.whole_object_reads: list[str] = []
        self.copies: list[tuple[str, str]] = []
        # Every expiration the doors hand to a signing call (fix(#1235 r3)).
        self.signed_ttls: list[int] = []
        # Multipart state, modelled the way S3 actually behaves: uploaded
        # parts are NOT visible as an object, and the upload id is spent by a
        # successful completion. The retry guard keys off exactly that.
        self.live_upload_ids: dict[str, str] = {}
        self.pending_parts: dict[str, bytes] = {}
        self.multipart_completions: list[tuple[str, str]] = []

    def generate_presigned_put_url(
        self, key: str, content_type: str, expiration: int = 3600
    ) -> str:
        # fix(#1235 review r3): mirrors the provider signature — the doors now
        # pass a deadline-anchored expiration.
        self.signed_ttls.append(expiration)
        return f"https://s3.invalid/{key}?signed=1"

    def initiate_multipart_upload(
        self, key: str, content_type: str = "application/octet-stream"
    ) -> str:
        upload_id = f"upload-{len(self.live_upload_ids) + 1}"
        self.live_upload_ids[key] = upload_id
        return upload_id

    def generate_presigned_part_url(
        self, key: str, upload_id: str, part_number: int, expiration: int = 7200
    ) -> str:
        self.signed_ttls.append(expiration)
        return f"https://s3.invalid/{key}?part={part_number}&upload={upload_id}"

    def complete_multipart_upload(self, key: str, upload_id: str, parts: list) -> None:
        self.multipart_completions.append((key, upload_id))
        if self.live_upload_ids.get(key) != upload_id:
            raise RuntimeError(f"NoSuchUpload: {upload_id} is spent or unknown")
        del self.live_upload_ids[key]
        self.objects[key] = self.pending_parts.pop(key)

    def abort_multipart_upload(self, key: str, upload_id: str) -> None:
        self.live_upload_ids.pop(key, None)
        self.pending_parts.pop(key, None)

    async def exists(self, key: str) -> bool:
        return key in self.objects

    async def size(self, key: str) -> int:
        return len(self.objects[key])

    async def copy(self, src_key: str, dst_key: str) -> None:
        # Server-side on the real provider: the bytes never enter this
        # process, which is why this does not touch whole_object_reads.
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


@pytest.fixture
def both_doors(monkeypatch, tmp_path):
    """Make both upload doors drivable in one test against one fake bucket.

    The direct door's ``save_upload_file`` writes to ``tmp_path`` (mirroring
    ``test_ingest.py``) so validation sees a real local file; the presigned
    door reads from the in-memory bucket. The allowed-extension list is fixed
    here rather than read from persistent config: the shared per-worker
    database carries whatever earlier tests stored, and these tests are about
    content, not configuration.
    """
    from app.processing.ingest import router

    storage = _FakeS3Storage()
    monkeypatch.setattr(settings, "storage_provider", "s3")
    monkeypatch.setattr(router, "get_storage", lambda: storage, raising=True)
    monkeypatch.setattr(
        "app.platform.storage.get_storage", lambda: storage, raising=True
    )
    monkeypatch.setattr(
        router,
        "_get_allowed_extensions_safely",
        AsyncMock(return_value=[".geojson", ".json", ".parquet", ".tif"]),
    )

    async def _save_to_temp(file, job_id: str, **_) -> Path:
        dest = tmp_path / f"{job_id}_{file.filename}"
        dest.write_bytes(await file.read())
        await file.seek(0)
        return dest

    with patch.object(router, "save_upload_file", AsyncMock(side_effect=_save_to_temp)):
        yield storage


async def _direct_upload(client, headers, filename: str, payload: bytes):
    """Drive ``POST /ingest/upload`` — the door that always validated."""
    return await client.post(
        "/ingest/upload",
        files={"file": (filename, payload, "application/octet-stream")},
        headers=headers,
    )


async def _presigned_upload(
    client, headers, storage: _FakeS3Storage, filename: str, payload: bytes
):
    """Drive request-presigned → (client PUTs to S3) → complete.

    Returns the completion response, the job id, and the staging key the
    client holds a PUT URL for. Tests run single-tenant, so logical and
    physical keys are identical and either may be used against the fake.
    """
    resp = await client.post(
        "/ingest/upload/presigned",
        json={
            "filename": filename,
            "file_size": len(payload),
            "content_type": "application/octet-stream",
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()

    # Stand in for the browser's direct PUT to the presigned URL.
    storage.objects[body["s3_key"]] = payload

    completion = await client.post(
        f"/ingest/upload/presigned/{body['job_id']}/complete",
        json={},
        headers=headers,
    )
    return completion, body["job_id"], body["s3_key"]


async def _job_file_path(test_db_session, job_id: str) -> str:
    from sqlalchemy import select

    from app.platform.jobs.models import IngestJob

    job = (
        await test_db_session.execute(select(IngestJob).where(IngestJob.id == job_id))
    ).scalar_one()
    await test_db_session.refresh(job)
    return job.file_path


async def test_both_doors_reject_a_mislabeled_payload_identically(
    client, admin_auth_header, both_doors
) -> None:
    """The bug: a GIF named .geojson was refused at one door and accepted at the other.

    Asserting the details are EQUAL, not merely both-4xx, is the taxonomy
    requirement — a client sees one contract regardless of which door it used.
    """
    direct = await _direct_upload(
        client, admin_auth_header, "roads.geojson", _GIF_PAYLOAD
    )
    presigned, _job_id, _staging = await _presigned_upload(
        client, admin_auth_header, both_doors, "roads.geojson", _GIF_PAYLOAD
    )

    assert direct.status_code == 422, direct.text
    assert presigned.status_code == direct.status_code, presigned.text
    assert presigned.json()["detail"] == direct.json()["detail"]
    assert "'.gif'" in direct.json()["detail"]


async def test_both_doors_accept_a_legitimate_payload(
    client, admin_auth_header, both_doors
) -> None:
    """The other direction. A refusal test alone cannot see over-rejection."""
    direct = await _direct_upload(
        client, admin_auth_header, "roads.geojson", _VALID_GEOJSON
    )
    presigned, _job_id, _staging = await _presigned_upload(
        client, admin_auth_header, both_doors, "roads.geojson", _VALID_GEOJSON
    )

    assert direct.status_code == 201, direct.text
    assert presigned.status_code == 200, presigned.text


async def test_both_doors_reject_a_truncated_parquet_identically(
    client, admin_auth_header, both_doors
) -> None:
    """Parquet's footer magic lives past the header window.

    A completion check that only read a prefix would accept this file while
    the direct door refuses it — the asymmetry in miniature, one layer down.
    """
    direct = await _direct_upload(
        client, admin_auth_header, "cells.parquet", _TRUNCATED_PARQUET
    )
    presigned, _job_id, _staging = await _presigned_upload(
        client, admin_auth_header, both_doors, "cells.parquet", _TRUNCATED_PARQUET
    )

    assert direct.status_code == 422, direct.text
    assert presigned.status_code == direct.status_code, presigned.text
    assert presigned.json()["detail"] == direct.json()["detail"]
    assert "PAR1" in direct.json()["detail"]

    # The footer can only have come from a read anchored to the end.
    size = len(_TRUNCATED_PARQUET)
    assert any(start == size - 4 for _key, start, _length in both_doors.range_reads), (
        both_doors.range_reads
    )


async def test_both_doors_accept_a_valid_parquet_larger_than_the_header_window(
    client, admin_auth_header, both_doors
) -> None:
    """The admission half of the parquet rule, at a size that needs the tail read."""
    direct = await _direct_upload(
        client, admin_auth_header, "cells.parquet", _VALID_PARQUET
    )
    presigned, _job_id, _staging = await _presigned_upload(
        client, admin_auth_header, both_doors, "cells.parquet", _VALID_PARQUET
    )

    assert direct.status_code == 201, direct.text
    assert presigned.status_code == 200, presigned.text


async def test_rejected_presigned_upload_removes_both_objects(
    client, admin_auth_header, both_doors
) -> None:
    """A refused upload must not leave the bytes sitting in the bucket.

    BOTH objects, because there are two after the freeze. Leaving the staging
    one would hand the client back exactly the bytes we just refused, still
    addressable through the PUT URL it holds.
    """
    presigned, _job_id, staging_key = await _presigned_upload(
        client, admin_auth_header, both_doors, "roads.geojson", _GIF_PAYLOAD
    )

    assert presigned.status_code == 422, presigned.text
    assert both_doors.objects == {}, both_doors.objects
    assert staging_key not in both_doors.objects


async def test_completion_validates_without_downloading_the_object(
    client, admin_auth_header, both_doors
) -> None:
    """Presigned uploads exist for the multi-GB case.

    #1186 removed a whole-object download from this endpoint for exactly that
    reason; re-adding the content check must not put one back. Pinning the
    read WIDTH is what keeps the fix affordable — a future edit that reaches
    for ``get()`` would still pass every assertion above.
    """
    presigned, _job_id, _staging = await _presigned_upload(
        client, admin_auth_header, both_doors, "cells.parquet", _VALID_PARQUET
    )

    assert presigned.status_code == 200, presigned.text
    assert both_doors.whole_object_reads == []
    total_bytes = sum(length for _key, _start, length in both_doors.range_reads)
    assert total_bytes <= 8192 + 4, both_doors.range_reads


async def test_completion_binds_the_job_to_a_frozen_key_and_drops_staging(
    client, admin_auth_header, test_db_session, both_doors
) -> None:
    """The key layout the TOCTOU fix rests on.

    The job's source must be a key no presign endpoint ever minted a URL for,
    and it must still live under ``staging/`` — every staging reaper in the
    codebase keys off that prefix, so a frozen copy outside it would leak.
    """
    presigned, job_id, staging_key = await _presigned_upload(
        client, admin_auth_header, both_doors, "roads.geojson", _VALID_GEOJSON
    )
    assert presigned.status_code == 200, presigned.text

    file_path = await _job_file_path(test_db_session, job_id)

    assert file_path != staging_key
    assert file_path.startswith("staging/")
    assert file_path.endswith("/roads.geojson")
    assert both_doors.copies == [(staging_key, file_path)]
    assert file_path in both_doors.objects
    assert staging_key not in both_doors.objects


async def test_a_late_reput_to_the_staging_key_cannot_swap_validated_bytes(
    client, admin_auth_header, test_db_session, both_doors
) -> None:
    """The P1: presigned PUT URLs outlive completion.

    They stay valid until expiry (an hour by default) and a PUT to an existing
    key REPLACES the object, so validating the key the client can still write
    to proves nothing about what preview later hands to GDAL. Completion
    snapshots the bytes first and binds the job to the snapshot, so the
    re-PUT below lands somewhere nothing reads.
    """
    presigned, job_id, staging_key = await _presigned_upload(
        client, admin_auth_header, both_doors, "roads.geojson", _VALID_GEOJSON
    )
    assert presigned.status_code == 200, presigned.text

    file_path = await _job_file_path(test_db_session, job_id)

    # The client re-PUTs garbage through the URL it still holds, after the
    # completion call has already returned 200.
    both_doors.objects[staging_key] = _GIF_PAYLOAD

    assert both_doors.objects[file_path] == _VALID_GEOJSON


async def test_a_second_completion_is_refused_and_cannot_replace_the_bytes(
    client, admin_auth_header, test_db_session, both_doors
) -> None:
    """Completion is one-shot.

    The re-PUT above is only harmless while nothing re-runs the freeze. A
    second ``/complete`` would copy the staging key — which the client can
    still write — straight over the bytes the first call accepted. Refusing
    it is the guard; the byte assertion is what the guard is FOR.

    The replay payload matches the original's LENGTH so the declared-size
    check cannot reject it first. With a different size this test passes
    against a build that has no guard at all.
    """
    presigned, job_id, staging_key = await _presigned_upload(
        client, admin_auth_header, both_doors, "roads.geojson", _VALID_GEOJSON
    )
    assert presigned.status_code == 200, presigned.text
    file_path = await _job_file_path(test_db_session, job_id)

    # Re-PUT garbage, then try to get the server to re-freeze it.
    both_doors.objects[staging_key] = _SAME_SIZE_GARBAGE
    replay = await client.post(
        f"/ingest/upload/presigned/{job_id}/complete",
        json={},
        headers=admin_auth_header,
    )

    assert replay.status_code == 400, replay.text
    assert "already completed" in replay.json()["detail"].lower()
    assert both_doors.objects[file_path] == _VALID_GEOJSON
    assert both_doors.copies == [(staging_key, file_path)]


async def test_completion_can_still_be_retried_after_a_transient_failure(
    client, admin_auth_header, test_db_session, both_doors
) -> None:
    """The other direction of the one-shot rule, and the reason it keys off
    ``file_path`` rather than a "completion attempted" flag.

    A completion that died in the storage layer leaves the job unbound, and
    the client must be able to retry without re-uploading. Pinning this is
    what stops the guard from being tightened into a rule that strands
    every interrupted upload.
    """
    resp = await client.post(
        "/ingest/upload/presigned",
        json={
            "filename": "roads.geojson",
            "file_size": len(_VALID_GEOJSON),
            "content_type": "application/octet-stream",
        },
        headers=admin_auth_header,
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    both_doors.objects[body["s3_key"]] = _VALID_GEOJSON

    async def _boom(src_key: str, dst_key: str) -> None:
        raise RuntimeError("storage hiccup during freeze")

    with patch.object(both_doors, "copy", _boom):
        failed = await client.post(
            f"/ingest/upload/presigned/{body['job_id']}/complete",
            json={},
            headers=admin_auth_header,
        )
    assert failed.status_code == 502, failed.text
    # The staging object survives a transient failure — that is the whole
    # point of not deleting it there.
    assert body["s3_key"] in both_doors.objects

    retried = await client.post(
        f"/ingest/upload/presigned/{body['job_id']}/complete",
        json={},
        headers=admin_auth_header,
    )

    assert retried.status_code == 200, retried.text
    file_path = await _job_file_path(test_db_session, body["job_id"])
    assert both_doors.objects[file_path] == _VALID_GEOJSON


async def test_an_oversize_object_is_refused_without_being_copied(
    client, admin_auth_header, both_doors
) -> None:
    """The pre-copy fast path: do not move gigabytes just to reject them.

    Presigned PUT URLs do not bind Content-Length, so the object can exceed
    the declared size. Asserting NO copy was recorded is the whole test —
    a rejection alone would pass with the wasteful copy still happening.
    """
    from app.processing.ingest import router

    resp = await client.post(
        "/ingest/upload/presigned",
        json={
            "filename": "roads.geojson",
            "file_size": len(_VALID_GEOJSON),
            "content_type": "application/octet-stream",
        },
        headers=admin_auth_header,
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()

    # The client PUTs far more than it declared. 1 MB against a 0-MB cap.
    both_doors.objects[body["s3_key"]] = b"\x00" * (1024 * 1024)

    with patch.object(router.UPLOAD_MAX_SIZE_MB, "get", AsyncMock(return_value=0)):
        completion = await client.post(
            f"/ingest/upload/presigned/{body['job_id']}/complete",
            json={},
            headers=admin_auth_header,
        )

    assert completion.status_code == 422, completion.text
    assert "exceeds the maximum allowed" in completion.json()["detail"]
    assert both_doors.copies == [], both_doors.copies
    assert both_doors.objects == {}, both_doors.objects


# Big enough to cross the multipart threshold the fixture lowers to 1 MB, and
# still plain text so content validation passes on its first 8192 bytes.
_LARGE_GEOJSON = _VALID_GEOJSON + b" " * (2 * 1024 * 1024)


async def _request_multipart_presign(client, headers, filename: str, payload: bytes):
    resp = await client.post(
        "/ingest/upload/presigned",
        json={
            "filename": filename,
            "file_size": len(payload),
            "content_type": "application/octet-stream",
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["upload_id"], "expected a multipart presign, got a single PUT"
    return body


async def test_multipart_retry_after_a_failed_freeze_does_not_reuse_a_spent_upload_id(
    client, admin_auth_header, test_db_session, both_doors, monkeypatch
) -> None:
    """The retry this endpoint's 502 promises has to actually work for multipart.

    CompleteMultipartUpload consumes the upload id and materializes the
    object. A completion that got past assembly and then died at the freeze
    left the job unbound with the id already spent, so every retry called
    complete again and was refused by the provider. The fake models both
    facts, so a regression here fails rather than passing quietly.
    """
    monkeypatch.setattr(settings, "presigned_multipart_threshold_mb", 1)

    body = await _request_multipart_presign(
        client, admin_auth_header, "roads.geojson", _LARGE_GEOJSON
    )
    # The client uploads its parts: present, but not yet an object.
    both_doors.pending_parts[body["s3_key"]] = _LARGE_GEOJSON
    assert body["s3_key"] not in both_doors.objects

    real_copy = both_doors.copy
    freeze_calls = {"n": 0}

    async def _fail_first_freeze(src_key: str, dst_key: str) -> None:
        freeze_calls["n"] += 1
        if freeze_calls["n"] == 1:
            raise RuntimeError("storage hiccup during freeze")
        await real_copy(src_key, dst_key)

    parts = [{"etag": "etag-1", "part_number": 1}]
    with patch.object(both_doors, "copy", _fail_first_freeze):
        failed = await client.post(
            f"/ingest/upload/presigned/{body['job_id']}/complete",
            json={"parts": parts},
            headers=admin_auth_header,
        )
    assert failed.status_code == 502, failed.text
    # Assembly succeeded before the freeze died, so the object is there.
    assert body["s3_key"] in both_doors.objects

    # The retry sends no parts — it has nothing left to resend.
    retried = await client.post(
        f"/ingest/upload/presigned/{body['job_id']}/complete",
        json={},
        headers=admin_auth_header,
    )

    assert retried.status_code == 200, retried.text
    assert len(both_doors.multipart_completions) == 1, both_doors.multipart_completions
    file_path = await _job_file_path(test_db_session, body["job_id"])
    assert file_path.endswith("/frozen/roads.geojson")
    assert both_doors.objects[file_path] == _LARGE_GEOJSON


async def test_a_failed_commit_leaves_both_objects_so_the_retry_can_proceed(
    client, admin_auth_header, test_db_session, both_doors
) -> None:
    """Deleting staging before the commit stranded the client.

    A rolled-back commit unsets file_path, so the job still needs the staging
    object — but it had already been deleted, and the retry could only report
    "File not found in S3 after upload" while the frozen copy orphaned.
    """
    from fastapi import HTTPException
    from sqlalchemy.ext.asyncio import AsyncSession

    resp = await client.post(
        "/ingest/upload/presigned",
        json={
            "filename": "roads.geojson",
            "file_size": len(_VALID_GEOJSON),
            "content_type": "application/octet-stream",
        },
        headers=admin_auth_header,
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    both_doors.objects[body["s3_key"]] = _VALID_GEOJSON

    real_commit = AsyncSession.commit
    commits = {"n": 0}

    async def _fail_first_commit(self) -> None:
        commits["n"] += 1
        if commits["n"] == 1:
            await self.rollback()
            # HTTPException rather than a raw error ONLY to keep the test
            # fast: an unhandled exception here sends the middleware stack
            # into rendering a full traceback with locals, which costs 44
            # seconds per run. What this test asserts is the ORDERING — that
            # an exception at the commit leaves the staging object alone —
            # and that is identical whichever exception type unwinds it.
            raise HTTPException(status_code=503, detail="commit failed")
        await real_commit(self)

    with patch.object(AsyncSession, "commit", _fail_first_commit):
        failed = await client.post(
            f"/ingest/upload/presigned/{body['job_id']}/complete",
            json={},
            headers=admin_auth_header,
        )

    assert failed.status_code == 503, failed.text
    # It really was the handler's commit that failed, not an earlier one.
    assert commits["n"] == 1
    # Both objects survive: the retry needs the staging bytes to re-freeze,
    # and the frozen copy proves the run got all the way past the freeze.
    assert body["s3_key"] in both_doors.objects
    assert any(dst in both_doors.objects for _src, dst in both_doors.copies)
    assert await _job_file_path(test_db_session, body["job_id"]) in ("", None)

    retried = await client.post(
        f"/ingest/upload/presigned/{body['job_id']}/complete",
        json={},
        headers=admin_auth_header,
    )

    assert retried.status_code == 200, retried.text
    file_path = await _job_file_path(test_db_session, body["job_id"])
    assert both_doors.objects[file_path] == _VALID_GEOJSON
    assert body["s3_key"] not in both_doors.objects


async def test_completion_locks_the_job_row_before_reading_file_path(
    client, admin_auth_header, both_doors
) -> None:
    """Pin the serialization mechanism, since the race itself is not
    deterministically testable through the ASGI client.

    The one-shot guard was an unlocked read: two overlapping completions both
    saw an empty ``file_path``, derived the SAME frozen key, and raced — the
    loser's refusal path deletes both objects while the winner commits a
    ``file_path`` pointing at one of them. What makes that impossible is the
    row lock, so this asserts the lock reaches the DATABASE rather than that
    the call was written with the right keyword. A `db.get` on an object
    already in the identity map can return the cached instance without
    emitting SQL at all, and that failure mode is invisible to a spy on the
    call arguments.
    """
    from sqlalchemy import event
    from sqlalchemy.engine import Engine

    statements: list[str] = []

    def _record(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(Engine, "before_cursor_execute", _record)
    try:
        presigned, _job_id, _staging = await _presigned_upload(
            client, admin_auth_header, both_doors, "roads.geojson", _VALID_GEOJSON
        )
    finally:
        event.remove(Engine, "before_cursor_execute", _record)

    assert presigned.status_code == 200, presigned.text
    locking = [s for s in statements if "FOR UPDATE" in s.upper()]
    assert locking, (
        "completion issued no FOR UPDATE; the one-shot guard is an unlocked "
        f"read again. ingest_jobs statements seen: "
        f"{[s for s in statements if 'ingest_jobs' in s][:5]}"
    )
    assert any("ingest_jobs" in s for s in locking), locking


async def test_the_locked_refetch_reads_the_committed_file_path(
    test_db_session,
) -> None:
    """fix(#1202 review r9): the lock must INFORM, not just serialize.

    The r5 pin proves a `FOR UPDATE` statement reaches the database. It does
    NOT prove the handler then reads the committed value: SQLAlchemy does not
    overwrite already-loaded attributes on an identity-map instance unless
    told to, and the handler's authz fetch loads the row BEFORE the competing
    request commits. If the locked re-fetch returned the cached `file_path`,
    the one-shot guard would pass on a job that was already completed — the
    lock would serialize and race identically.

    Two sessions, no interleaving needed: session 1 loads the row (the authz
    fetch), a separate session commits a binding (the winning request), then
    session 1 does exactly what the handler does and we read the attribute.
    """
    from sqlalchemy import select, update

    from app.core import db as db_module
    from app.modules.auth.models import User
    from app.platform.jobs.models import IngestJob
    from app.processing.ingest.router import lock_presigned_job

    admin = (
        await test_db_session.execute(select(User).where(User.username == "admin"))
    ).scalar_one()
    job = IngestJob(
        source_filename="roads.geojson",
        created_by=admin.id,
        status="pending",
        file_path="",
        user_metadata={"presigned": True},
    )
    test_db_session.add(job)
    await test_db_session.commit()
    await test_db_session.refresh(job)
    job_id = job.id
    bound_path = f"staging/{job_id}/frozen/roads.geojson"

    async with db_module.async_session() as request_session:
        # The unlocked authz fetch, exactly as get_job_or_404 does it.
        loaded = (
            await request_session.execute(
                select(IngestJob).where(IngestJob.id == job_id)
            )
        ).scalar_one()
        assert loaded.file_path == "", "precondition: unbound when first read"

        # The winning request commits its binding on another connection.
        async with db_module.async_session() as other_session:
            await other_session.execute(
                update(IngestJob)
                .where(IngestJob.id == job_id)
                .values(file_path=bound_path)
            )
            await other_session.commit()

        # The handler's OWN helper, not a copy of it — a local
        # reimplementation would keep passing if the handler dropped
        # populate_existing, which is exactly the regression this guards.
        relocked = await lock_presigned_job(request_session, job_id)

    assert relocked.file_path == bound_path, (
        "the locked re-fetch returned a STALE file_path — the one-shot guard "
        "would pass on an already-completed job, so the lock serializes "
        "without informing"
    )


async def test_a_failed_job_cannot_be_completed_by_a_late_reput(
    client, admin_auth_header, test_db_session, both_doors
) -> None:
    """fix(#1213 review r3): the second one-shot fact, on this door too.

    The upload door never stamps `failed` itself, so it reaches this state by
    a different route: the stale-pending reaper marks an abandoned presigned
    job failed after an hour — the same hour its PUT URL stays valid, so the
    windows overlap. A guard checking only `file_path` then lets a late
    completion 200 and bind a frozen object to a job no task will ever run for,
    which nothing reaps: the task tails never fire, and the post-expiry sweep
    covers only the client's key, not the frozen one.
    """
    from sqlalchemy import select, update

    from app.platform.jobs.models import IngestJob

    resp = await client.post(
        "/ingest/upload/presigned",
        json={
            "filename": "roads.geojson",
            "file_size": len(_VALID_GEOJSON),
            "content_type": "application/octet-stream",
        },
        headers=admin_auth_header,
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    both_doors.objects[body["s3_key"]] = _VALID_GEOJSON

    # What the stale-pending reaper leaves behind: terminal, still unbound.
    await test_db_session.execute(
        update(IngestJob)
        .where(IngestJob.id == body["job_id"])
        .values(
            status="failed",
            error_message="Stale: pending for over 1 hour (never queued)",
        )
    )
    await test_db_session.commit()

    completion = await client.post(
        f"/ingest/upload/presigned/{body['job_id']}/complete",
        json={},
        headers=admin_auth_header,
    )

    assert completion.status_code == 400, completion.text
    assert "already failed" in completion.json()["detail"].lower()
    assert "start a new upload" in completion.json()["detail"].lower()

    job = (
        await test_db_session.execute(
            select(IngestJob).where(IngestJob.id == body["job_id"])
        )
    ).scalar_one()
    await test_db_session.refresh(job)
    assert not job.file_path, "a failed job must not end up bound"
    assert both_doors.copies == [], (
        "no frozen object may be created for a job no task will ever run"
    )


class TestFinalizeCleanupContract:
    """fix(#1213 review r5): the two failure-path holes, at the helper.

    Driven against `finalize_presigned_object` directly rather than through a
    door, because both are about which objects survive which exit — the
    postconditions its docstring promises — and neither depends on routing.
    """

    @staticmethod
    def _storage_with(objects: dict) -> _FakeS3Storage:
        storage = _FakeS3Storage()
        storage.objects.update(objects)
        return storage

    async def test_a_pre_copy_refusal_also_drops_a_prior_frozen_copy(
        self, test_db_session, monkeypatch
    ) -> None:
        """Attempt 1 froze and then lost its commit — by design both objects
        stay so the retry can re-copy. If the retry trips the size gate, the
        earlier frozen copy is unbound, unreferenced and unreaped."""
        from app.core.persistent_config import UPLOAD_MAX_SIZE_MB
        from app.processing.ingest.presigned import finalize_presigned_object

        job_id = uuid.uuid4()
        staging_key = f"staging/{job_id}/roads.geojson"
        frozen_key = f"staging/{job_id}/frozen/roads.geojson"
        storage = self._storage_with(
            {staging_key: b"\x00" * 4096, frozen_key: _VALID_GEOJSON}
        )

        with patch.object(UPLOAD_MAX_SIZE_MB, "get", AsyncMock(return_value=0)):
            with pytest.raises(HTTPException) as exc:
                await finalize_presigned_object(
                    db=test_db_session,
                    storage=storage,
                    job_id=job_id,
                    logical_key=staging_key,
                    expected_size=4096,
                    filename="roads.geojson",
                    user_id=uuid.uuid4(),
                    request=MagicMock(),
                )

        assert exc.value.status_code == 422
        assert "exceeds the maximum allowed" in str(exc.value.detail)
        assert staging_key not in storage.objects
        assert frozen_key not in storage.objects, (
            "the frozen copy from the earlier attempt survived a pre-copy "
            "refusal — nothing else reaps it once the job is terminal"
        )

    async def test_a_cancelled_first_delete_still_drops_the_staging_object(
        self, test_db_session, monkeypatch
    ) -> None:
        """A rejection deletes BOTH objects in sequence. A CancelledError
        escaping the first would leave the staging object alive — handing the
        client back the bytes just refused, which is the hole the rejection
        block exists to close. v1.8.0's `_cleanup_saved_upload` swallowed
        BaseException for exactly this (KISS-N9); the extraction lost it.
        """
        from app.processing.ingest.presigned import finalize_presigned_object

        job_id = uuid.uuid4()
        staging_key = f"staging/{job_id}/roads.geojson"
        storage = self._storage_with({staging_key: _GIF_PAYLOAD})

        real_delete = storage.delete
        calls = {"n": 0}

        async def _cancel_first_delete(key: str) -> None:
            calls["n"] += 1
            if calls["n"] == 1:
                raise asyncio.CancelledError()
            await real_delete(key)

        # Patched on the instance so the real `_cleanup_presigned_object`
        # runs — a stand-in for the helper would not exercise its except
        # clause, which is the thing under test.
        monkeypatch.setattr(storage, "delete", _cancel_first_delete)

        with pytest.raises(HTTPException) as exc:
            await finalize_presigned_object(
                db=test_db_session,
                storage=storage,
                job_id=job_id,
                logical_key=staging_key,
                expected_size=len(_GIF_PAYLOAD),
                filename="roads.geojson",
                user_id=uuid.uuid4(),
                request=MagicMock(),
            )

        assert exc.value.status_code == 422
        assert calls["n"] >= 2, "the second delete never ran"
        assert staging_key not in storage.objects, (
            "a cancellation during the frozen delete left the refused staging "
            "bytes addressable through the client's still-valid PUT URL"
        )


async def test_a_cancel_during_assembly_leaves_the_retry_a_way_back(
    client, admin_auth_header, test_db_session, both_doors, monkeypatch
) -> None:
    """fix(#1233): the cancel branch used to delete the assembled object.

    CompleteMultipartUpload has already consumed the upload id by then, and the
    object's presence is the ONLY record that assembly succeeded — it is what
    `should_assemble_multipart` reads to let a retry skip re-assembly (#1202
    r3). Deleting it sent the client's natural retry back into assembly with a
    spent id, which 502s forever with no way back.

    A cancellation is not a rejection of the bytes, so the fix is to drain and
    re-raise only.
    """
    from app.processing.ingest import router as ingest_router

    monkeypatch.setattr(settings, "presigned_multipart_threshold_mb", 1)
    payload = _VALID_GEOJSON + b" " * (2 * 1024 * 1024)

    resp = await client.post(
        "/ingest/upload/presigned",
        json={
            "filename": "roads.geojson",
            "file_size": len(payload),
            "content_type": "application/octet-stream",
        },
        headers=admin_auth_header,
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["upload_id"], "precondition: this is a multipart presign"
    both_doors.pending_parts[body["s3_key"]] = payload

    # Assembly succeeds, THEN the request is cancelled — the exact interleaving
    # the branch exists for. capture_cancel returns the result plus the cancel.
    real_capture = ingest_router.run_in_thread_draining_capture_cancel
    fired = {"n": 0}

    async def _assemble_then_cancel(fn, *args):
        result, _cancel = await real_capture(fn, *args)
        fired["n"] += 1
        if fired["n"] == 1:
            return result, asyncio.CancelledError()
        return result, None

    parts = [{"etag": "etag-1", "part_number": 1}]
    with patch.object(
        ingest_router, "run_in_thread_draining_capture_cancel", _assemble_then_cancel
    ):
        # A cancellation inside the app surfaces through httpx as a
        # transport-level error rather than CancelledError, because the handler
        # never returns a response. The exception type is harness detail; the
        # claim under test is what the cancelled attempt LEFT BEHIND.
        with contextlib.suppress(BaseException):
            await client.post(
                f"/ingest/upload/presigned/{body['job_id']}/complete",
                json={"parts": parts},
                headers=admin_auth_header,
            )
    assert fired["n"] == 1, "precondition: the cancel branch actually ran"

    # The assembled object must survive: it is the retry's only way past
    # assembly, and the upload id it would otherwise re-present is spent.
    assert body["s3_key"] in both_doors.objects, (
        "the cancel branch destroyed the assembly record; the retry below can "
        "only re-assemble with a consumed upload id"
    )

    retried = await client.post(
        f"/ingest/upload/presigned/{body['job_id']}/complete",
        json={},
        headers=admin_auth_header,
    )

    assert retried.status_code == 200, retried.text
    assert len(both_doors.multipart_completions) == 1, both_doors.multipart_completions


@pytest.mark.parametrize("multipart", [False, True], ids=["put-url", "part-urls"])
async def test_the_door_signs_urls_against_the_job_deadline(
    client, admin_auth_header, both_doors, monkeypatch, multipart
) -> None:
    """fix(#1235 review r3): both URL kinds, through the real door.

    The helper's arithmetic is unit-tested in test_stale_pending_reaper.py;
    this pins that the door actually PASSES it, for the single-PUT and the
    part-loop sites alike. Without it the provider default (3600 / 7200)
    arrives instead, anchored to signing time.
    """
    from app.core.config import settings

    monkeypatch.setattr(settings, "pending_job_timeout_seconds", 900)
    if multipart:
        monkeypatch.setattr(settings, "presigned_multipart_threshold_mb", 1)
        payload_size = 3 * 1024 * 1024
    else:
        payload_size = len(_VALID_GEOJSON)

    resp = await client.post(
        "/ingest/upload/presigned",
        json={
            "filename": "roads.geojson",
            "file_size": payload_size,
            "content_type": "application/octet-stream",
        },
        headers=admin_auth_header,
    )

    assert resp.status_code == 201, resp.text
    assert both_doors.signed_ttls, "no signature recorded"
    # The job was created moments ago, so every URL should carry very nearly
    # the whole 900s window — and crucially NOT the 3600/7200 provider default.
    for ttl in both_doors.signed_ttls:
        assert 890 <= ttl <= 900, both_doors.signed_ttls
