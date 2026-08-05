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

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from app.core.config import settings


pytestmark = pytest.mark.anyio


# A GIF header is binary (null bytes, so the text-content escape hatch does not
# apply) and puremagic names it exactly, which makes the rejection message a
# concrete string both doors must produce character for character.
_GIF_PAYLOAD = b"GIF89a" + b"\x00" * 512
_VALID_GEOJSON = b'{"type":"FeatureCollection","features":[]}'

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

    def generate_presigned_put_url(self, key: str, content_type: str) -> str:
        return f"https://s3.invalid/{key}?signed=1"

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
