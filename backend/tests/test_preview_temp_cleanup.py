"""Regression coverage for temporary S3 preview download cleanup."""

import asyncio
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from app.platform.jobs.models import IngestJob
from app.core.config import settings
from tests.factories import get_user_id


def _preview_result() -> dict:
    return {
        "columns": [{"name": "name", "type": "String"}],
        "srid": 4326,
        "geometry_type": "Point",
        "feature_count": 1,
        "sample_rows": [{"name": "sample"}],
        "layer_name": "sample",
        "all_layers": None,
    }


async def _create_s3_job(session) -> IngestJob:
    admin_id = await get_user_id(session, "admin")
    job = IngestJob(
        source_filename="preview.geojson",
        file_path=f"staging/{uuid.uuid4()}/preview.geojson",
        created_by=admin_id,
        status="pending",
        user_metadata={"file_type": "vector"},
    )
    session.add(job)
    await session.commit()
    return job


async def test_ordinary_preview_removes_s3_download_after_success(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
    tmp_path,
) -> None:
    job = await _create_s3_job(test_db_session)
    downloaded = tmp_path / "resolved-success.geojson"
    downloaded.write_text('{"type":"FeatureCollection","features":[]}')

    with (
        patch(
            "app.processing.ingest.router.resolve_file_path",
            new=AsyncMock(return_value=str(downloaded)),
        ),
        patch(
            "app.processing.ingest.router.run_ogrinfo_preview",
            new=AsyncMock(return_value=_preview_result()),
        ),
    ):
        response = await client.post(
            f"/ingest/preview/{job.id}", headers=admin_auth_header
        )

    assert response.status_code == 200, response.text
    assert not downloaded.exists()


async def test_ordinary_preview_removes_s3_download_after_failure(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
    tmp_path,
) -> None:
    job = await _create_s3_job(test_db_session)
    downloaded = tmp_path / "resolved-failure.geojson"
    downloaded.write_text("malformed")

    with (
        patch(
            "app.processing.ingest.router.resolve_file_path",
            new=AsyncMock(return_value=str(downloaded)),
        ),
        patch(
            "app.processing.ingest.router.run_ogrinfo_preview",
            new=AsyncMock(side_effect=ValueError("malformed")),
        ),
    ):
        response = await client.post(
            f"/ingest/preview/{job.id}", headers=admin_auth_header
        )

    assert response.status_code == 422
    assert not downloaded.exists()


async def test_resolve_file_path_gives_concurrent_callers_unique_owned_copies(
    monkeypatch, tmp_path
) -> None:
    from app.processing.ingest import service

    storage = AsyncMock()

    async def write_copy(_key, destination):
        destination.write_bytes(b"copy")

    storage.get_to_file.side_effect = write_copy
    monkeypatch.setattr(settings, "upload_staging_dir", str(tmp_path))
    monkeypatch.setattr("app.platform.storage.get_storage", lambda: storage)

    first = await service.resolve_file_path("staging/job/source.geojson", "job")
    second = await service.resolve_file_path("staging/job/source.geojson", "job")

    assert first != second
    assert Path(first).read_bytes() == b"copy"
    assert Path(second).read_bytes() == b"copy"
    Path(first).unlink()
    assert Path(second).exists()


async def test_resolve_file_path_cleans_partial_permanent_failure(
    monkeypatch, tmp_path
) -> None:
    from app.processing.ingest import service

    storage = AsyncMock()

    async def fail_after_partial(_key, destination):
        destination.write_bytes(b"partial")
        raise RuntimeError("access denied")

    storage.get_to_file.side_effect = fail_after_partial
    monkeypatch.setattr(settings, "upload_staging_dir", str(tmp_path))
    monkeypatch.setattr("app.platform.storage.get_storage", lambda: storage)

    with pytest.raises(RuntimeError, match="access denied"):
        await service.resolve_file_path("staging/job/source.geojson", "job")

    assert list(tmp_path.iterdir()) == []


async def test_resolve_file_path_drains_and_cleans_cancelled_download(
    monkeypatch, tmp_path
) -> None:
    """Cancellation waits for provider work before deleting its owned temp path."""
    from app.processing.ingest import service

    storage = AsyncMock()
    download_started = asyncio.Event()
    finish_download = asyncio.Event()

    async def slow_copy(_key, destination):
        destination.write_bytes(b"partial")
        download_started.set()
        await finish_download.wait()
        destination.write_bytes(b"complete")

    storage.get_to_file.side_effect = slow_copy
    monkeypatch.setattr(settings, "upload_staging_dir", str(tmp_path))
    monkeypatch.setattr("app.platform.storage.get_storage", lambda: storage)

    task = asyncio.create_task(
        service.resolve_file_path("staging/job/source.geojson", "job")
    )
    await download_started.wait()
    task.cancel()
    await asyncio.sleep(0)

    # The resolver must still be draining the provider; eager cleanup would
    # race the provider's final write.
    assert not task.done()
    assert list(tmp_path.iterdir())

    finish_download.set()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert list(tmp_path.iterdir()) == []
