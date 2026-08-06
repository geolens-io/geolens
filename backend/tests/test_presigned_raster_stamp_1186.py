"""Regression coverage for #1186: presigned uploads must stamp file_type.

Every pre-existing raster test drives the NON-presigned ``POST /ingest/upload``
endpoint, so the presigned path had no coverage at all — and on an S3
deployment that is the only path the frontend uses. ``file_type`` gates three
consumers (preview's raster branch, ``_pick_commit_subclass``, and the raster
dispatch in ``queue_ingest_job``); this file walks a real GeoTIFF through all
three via the presigned endpoints.

The synthetic-GeoTIFF helper mirrors ``test_raster_ingest.py`` /
``test_raster_antimeridian_887.py``, which each carry their own copy.
"""

from __future__ import annotations

import io
from pathlib import Path
from unittest.mock import AsyncMock, patch

import numpy as np
import pytest
from rasterio.crs import CRS
from rasterio.io import MemoryFile
from rasterio.transform import from_bounds
from sqlalchemy import select

from app.core.config import settings
from app.platform.jobs.models import IngestJob


pytestmark = pytest.mark.anyio


def _geotiff_bytes(
    *,
    width: int = 64,
    height: int = 64,
    bands: int = 1,
    crs: CRS | None = CRS.from_epsg(4326),
) -> bytes:
    """Create a minimal valid GeoTIFF in memory and return its bytes."""
    profile = {
        "driver": "GTiff",
        "dtype": "uint8",
        "width": width,
        "height": height,
        "count": bands,
        "transform": from_bounds(-180, -90, 180, 90, width, height),
    }
    if crs is not None:
        profile["crs"] = crs
    rng = np.random.default_rng(1186)
    buf = io.BytesIO()
    with MemoryFile() as mem:
        with mem.open(**profile) as ds:
            for band in range(1, bands + 1):
                ds.write(rng.integers(0, 200, (height, width), dtype="uint8"), band)
        buf.write(mem.read())
    return buf.getvalue()


class _FakeS3Storage:
    """In-memory stand-in for the S3 provider, keyed exactly like the real one.

    Only the methods the presigned request/complete/preview path touches are
    implemented; anything else should raise rather than silently no-op.
    """

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    # -- presign (sync, called through run_in_thread_draining) --------------
    def generate_presigned_put_url(
        self, key: str, content_type: str, expiration: int = 3600
    ) -> str:
        return f"https://s3.invalid/{key}?signed=1"

    # -- completion --------------------------------------------------------
    async def exists(self, key: str) -> bool:
        return key in self.objects

    async def size(self, key: str) -> int:
        return len(self.objects[key])

    async def get_range(self, key: str, start: int, length: int) -> bytes:
        # fix(#1202): completion content-validates from a bounded window.
        return self.objects[key][start : start + length]

    async def copy(self, src_key: str, dst_key: str) -> None:
        # fix(#1202 review): completion freezes the upload before judging it.
        self.objects[dst_key] = self.objects[src_key]

    async def delete(self, key: str) -> None:
        self.objects.pop(key, None)

    # -- preview / ingest download ----------------------------------------
    async def get_to_file(self, key: str, dest: Path) -> Path:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(self.objects[key])
        return dest


async def _presigned_upload_geotiff(
    client,
    headers: dict,
    storage: _FakeS3Storage,
    *,
    filename: str = "dem.tif",
) -> str:
    """Run request-presigned → (client PUTs to S3) → complete. Returns job id."""
    payload = _geotiff_bytes()

    resp = await client.post(
        "/ingest/upload/presigned",
        json={
            "filename": filename,
            "file_size": len(payload),
            "content_type": "image/tiff",
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    job_id = body["job_id"]

    # Stand in for the browser's direct PUT to the presigned URL.
    storage.objects[body["s3_key"]] = payload

    resp = await client.post(
        f"/ingest/upload/presigned/{job_id}/complete",
        json={},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    return job_id


@pytest.fixture
def s3_mode(monkeypatch):
    """Put the app in S3 mode with an in-memory provider on every lookup path."""
    storage = _FakeS3Storage()
    monkeypatch.setattr(settings, "storage_provider", "s3")
    # The router holds a module-level import; resolve_file_path imports from
    # app.platform.storage at call time. Both have to see the fake.
    monkeypatch.setattr(
        "app.processing.ingest.router.get_storage", lambda: storage, raising=True
    )
    monkeypatch.setattr(
        "app.platform.storage.get_storage", lambda: storage, raising=True
    )
    return storage


async def test_presigned_upload_stamps_raster_file_type(
    client, admin_auth_header, test_db_session, s3_mode
) -> None:
    """The stamp itself: complete_presigned_upload must set file_type=raster.

    This is the assertion the fix exists for — the three consumers below all
    read this one key.
    """
    job_id = await _presigned_upload_geotiff(client, admin_auth_header, s3_mode)

    job = (
        await test_db_session.execute(select(IngestJob).where(IngestJob.id == job_id))
    ).scalar_one()
    assert job.user_metadata["file_type"] == "raster"
    # The presign bookkeeping must survive the stamp.
    assert job.user_metadata["presigned"] is True
    assert job.user_metadata["s3_key"].endswith("dem.tif")


async def test_presigned_upload_previews_as_raster(
    client, admin_auth_header, s3_mode
) -> None:
    """Consumer 1 — preview. The reported symptom was a 422 from ogrinfo."""
    job_id = await _presigned_upload_geotiff(client, admin_auth_header, s3_mode)

    resp = await client.post(f"/ingest/preview/{job_id}", headers=admin_auth_header)

    assert resp.status_code == 200, resp.text
    data = resp.json()
    # RasterPreviewResponse fields — a vector PreviewResponse has none of them.
    assert data["band_count"] == 1
    assert data["width"] == 64
    assert data["height"] == 64
    assert data["crs_epsg"] == 4326
    assert "is_cog_compliant" in data


async def test_presigned_upload_commits_and_dispatches_as_raster(
    client, admin_auth_header, test_db_session, s3_mode
) -> None:
    """Consumers 2 and 3 — commit-body parsing and worker dispatch.

    ``compression``/``resampling`` exist only on RasterCommitRequest, so their
    survival proves the body parsed as raster; the deferred task proves the
    dispatch branch.
    """
    from app.processing.ingest.tasks import ingest_raster

    job_id = await _presigned_upload_geotiff(client, admin_auth_header, s3_mode)

    defer = AsyncMock()
    with patch("app.processing.ingest.service.defer_async_with_tenant", defer):
        resp = await client.post(
            f"/ingest/commit/{job_id}",
            json={
                "title": "Elevation",
                "compression": "LZW",
                "resampling": "bilinear",
            },
            headers=admin_auth_header,
        )

    assert resp.status_code == 202, resp.text
    defer.assert_awaited_once()
    deferred_task = defer.await_args.args[0]
    assert deferred_task is ingest_raster, f"dispatched {deferred_task.name}"

    job = (
        await test_db_session.execute(select(IngestJob).where(IngestJob.id == job_id))
    ).scalar_one()
    assert job.user_metadata["compression"] == "LZW"
    assert job.user_metadata["resampling"] == "bilinear"


async def test_ingest_raster_derives_crs_missing_without_the_upload_stamp(
    client, admin_auth_header, test_db_session, tmp_path
) -> None:
    """The worker half of the fix.

    ``crs_missing`` used to come from ``user_metadata``, written only by the
    non-presigned upload endpoint. A presigned job therefore arrives without
    it — and it gates whether ``srid_override`` is handed to the COG
    conversion, so a CRS-less raster would have been converted with the
    override silently dropped. The task derives it from the raster now, so a
    job with no stamp at all still gets the actionable error.
    """
    from app.modules.auth.models import User
    from app.processing.ingest.tasks_raster import ingest_raster

    raster = tmp_path / "nocrs.tif"
    raster.write_bytes(_geotiff_bytes(crs=None))

    admin = (
        await test_db_session.execute(select(User).where(User.username == "admin"))
    ).scalar_one()

    job = IngestJob(
        source_filename="nocrs.tif",
        file_path=str(raster),
        created_by=admin.id,
        status="pending",
        # Exactly what the presigned path leaves behind: the raster
        # discriminator and no crs_missing key.
        user_metadata={"file_type": "raster", "presigned": True},
    )
    test_db_session.add(job)
    await test_db_session.commit()
    await test_db_session.refresh(job)

    with pytest.raises(ValueError, match="Provide a CRS override"):
        await ingest_raster.func(
            job_id=str(job.id),
            file_path=str(raster),
            user_id=str(admin.id),
            attempt_id=str(job.attempt_id),
        )


async def test_presigned_vector_upload_is_not_stamped_raster(
    client, admin_auth_header, test_db_session, s3_mode
) -> None:
    """The other direction: the stamp keys off the filename, so vectors are
    left alone and keep defaulting to the ogrinfo path."""
    resp = await client.post(
        "/ingest/upload/presigned",
        json={
            "filename": "roads.geojson",
            "file_size": 2,
            "content_type": "application/geo+json",
        },
        headers=admin_auth_header,
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    s3_mode.objects[body["s3_key"]] = b"{}"

    resp = await client.post(
        f"/ingest/upload/presigned/{body['job_id']}/complete",
        json={},
        headers=admin_auth_header,
    )
    assert resp.status_code == 200, resp.text

    job = (
        await test_db_session.execute(
            select(IngestJob).where(IngestJob.id == body["job_id"])
        )
    ).scalar_one()
    assert "file_type" not in job.user_metadata
