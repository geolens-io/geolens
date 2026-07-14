"""Tenant ownership regressions for transient ingest storage objects."""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from io import BytesIO
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import UploadFile
from starlette.datastructures import Headers

from app.core.config import settings
from app.core.db.tenant_session import current_tenant_var


TENANT_A = "00000000-0000-0000-0000-000000000001"


@contextmanager
def _tenant_mode(monkeypatch, mode: str, tenant_id: str | None):
    monkeypatch.setattr(settings, "geolens_tenancy_mode", mode)
    token = current_tenant_var.set(tenant_id)
    try:
        yield
    finally:
        current_tenant_var.reset(token)


def _upload(filename: str = "roads.geojson") -> UploadFile:
    return UploadFile(
        filename=filename,
        file=BytesIO(b"{}"),
        size=2,
        headers=Headers({"content-type": "application/geo+json"}),
    )


def test_current_storage_key_is_tenant_scoped_and_single_tenant_exact(monkeypatch):
    from app.platform.storage.titiler_url import resolve_current_storage_key

    logical = "staging/job-a/roads.geojson"
    with _tenant_mode(monkeypatch, "multi_tenant", TENANT_A):
        assert resolve_current_storage_key(logical) == f"tenants/{TENANT_A}/{logical}"

    # A stray ContextVar value cannot change legacy single-tenant keys.
    with _tenant_mode(monkeypatch, "single_tenant", TENANT_A):
        assert resolve_current_storage_key(logical) == logical


def test_current_storage_key_fails_closed_without_hosted_context(monkeypatch):
    from app.platform.storage.titiler_url import resolve_current_storage_key

    with _tenant_mode(monkeypatch, "multi_tenant", None):
        with pytest.raises(RuntimeError, match="requires tenant context"):
            resolve_current_storage_key("staging/job-a/roads.geojson")


@pytest.mark.anyio
async def test_multipart_upload_saves_logical_key_but_writes_tenant_key(monkeypatch):
    from app.processing.ingest.service import save_upload_file

    storage = AsyncMock()
    monkeypatch.setattr(settings, "storage_provider", "s3")
    monkeypatch.setattr("app.platform.storage.get_storage", lambda: storage)

    with _tenant_mode(monkeypatch, "multi_tenant", TENANT_A):
        result = await save_upload_file(_upload(), "job-a", max_size_bytes=100)

    logical = "staging/job-a/roads.geojson"
    assert result == logical
    assert storage.put.await_args.args[0] == f"tenants/{TENANT_A}/{logical}"


@pytest.mark.anyio
async def test_multipart_upload_single_tenant_provider_key_is_unchanged(monkeypatch):
    from app.processing.ingest.service import save_upload_file

    storage = AsyncMock()
    monkeypatch.setattr(settings, "storage_provider", "s3")
    monkeypatch.setattr("app.platform.storage.get_storage", lambda: storage)

    with _tenant_mode(monkeypatch, "single_tenant", TENANT_A):
        result = await save_upload_file(_upload(), "job-a", max_size_bytes=100)

    logical = "staging/job-a/roads.geojson"
    assert result == logical
    assert storage.put.await_args.args[0] == logical


@pytest.mark.anyio
async def test_resolve_file_path_reads_tenant_key_despite_relative_path_collision(
    monkeypatch, tmp_path
):
    from app.processing.ingest.service import resolve_file_path

    logical = "staging/job-a/roads.geojson"
    collision = tmp_path / logical
    collision.parent.mkdir(parents=True)
    collision.write_bytes(b"wrong-local-object")
    downloads = tmp_path / "downloads"
    downloads.mkdir()

    storage = AsyncMock()

    async def _download(key: str, destination: Path) -> None:
        assert key == f"tenants/{TENANT_A}/{logical}"
        destination.write_bytes(b"tenant-a-object")

    storage.get_to_file.side_effect = _download
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(settings, "upload_staging_dir", str(downloads))
    monkeypatch.setattr("app.platform.storage.get_storage", lambda: storage)

    with _tenant_mode(monkeypatch, "multi_tenant", TENANT_A):
        resolved = await resolve_file_path(logical, "job-a")

    assert Path(resolved).read_bytes() == b"tenant-a-object"
    assert collision.read_bytes() == b"wrong-local-object"


@pytest.mark.anyio
async def test_resolve_file_path_preserves_operator_owned_manifest_key(
    monkeypatch, tmp_path
):
    from app.processing.ingest.service import resolve_file_path

    physical_manifest_key = "operator-seeds/roads.geojson"
    storage = AsyncMock()

    async def _download(key: str, destination: Path) -> None:
        assert key == physical_manifest_key
        destination.write_bytes(b"manifest-object")

    storage.get_to_file.side_effect = _download
    monkeypatch.setattr(settings, "upload_staging_dir", str(tmp_path))
    monkeypatch.setattr("app.platform.storage.get_storage", lambda: storage)

    with _tenant_mode(monkeypatch, "multi_tenant", TENANT_A):
        resolved = await resolve_file_path(physical_manifest_key, "manifest-job")

    assert Path(resolved).read_bytes() == b"manifest-object"


@pytest.mark.anyio
async def test_presigned_upload_uses_physical_key_and_persists_logical_key(monkeypatch):
    from app.processing.ingest import router
    from app.processing.ingest.schemas import PresignedUploadRequest

    job = MagicMock(id=uuid.uuid4(), user_metadata={})
    db = AsyncMock()
    storage = MagicMock()
    storage.generate_presigned_put_url.return_value = "https://storage.test/put"
    monkeypatch.setattr(settings, "storage_provider", "s3")
    monkeypatch.setattr(settings, "presigned_multipart_threshold_mb", 100)

    with (
        patch.object(
            router,
            "_get_allowed_extensions_safely",
            AsyncMock(return_value=[".geojson"]),
        ),
        patch.object(router.UPLOAD_MAX_SIZE_MB, "get", AsyncMock(return_value=10)),
        patch.object(router, "check_upload_quota", AsyncMock()),
        patch.object(router, "create_ingest_job", AsyncMock(return_value=job)),
        patch.object(router, "get_storage", return_value=storage),
        _tenant_mode(monkeypatch, "multi_tenant", TENANT_A),
    ):
        response = await router.request_presigned_upload(
            PresignedUploadRequest(filename="roads.geojson", file_size=2),
            MagicMock(),
            MagicMock(id=uuid.uuid4()),
            db,
        )

    logical = f"staging/{job.id}/roads.geojson"
    physical = f"tenants/{TENANT_A}/{logical}"
    storage.generate_presigned_put_url.assert_called_once_with(
        physical, "application/octet-stream"
    )
    assert response.s3_key == physical
    assert job.user_metadata["s3_key"] == logical


@pytest.mark.anyio
async def test_presigned_completion_reads_physical_and_keeps_logical_job_path(
    monkeypatch,
):
    from app.processing.ingest import router
    from app.processing.ingest.schemas import PresignedCompleteRequest

    logical = "staging/job-a/roads.geojson"
    physical = f"tenants/{TENANT_A}/{logical}"
    job = MagicMock(
        id=uuid.uuid4(),
        user_metadata={
            "presigned": True,
            "s3_key": logical,
            "multipart": False,
            "expected_size": 2,
        },
    )
    db = AsyncMock()
    storage = AsyncMock()
    storage.exists.return_value = True
    verify = AsyncMock(return_value=2)

    with (
        patch.object(router, "get_job_or_404", AsyncMock(return_value=job)),
        patch.object(router, "get_storage", return_value=storage),
        patch.object(router, "verify_completed_presigned_upload", verify),
        _tenant_mode(monkeypatch, "multi_tenant", TENANT_A),
    ):
        await router.complete_presigned_upload(
            job.id,
            PresignedCompleteRequest(),
            MagicMock(),
            MagicMock(id=uuid.uuid4()),
            db,
        )

    storage.exists.assert_awaited_once_with(physical)
    assert verify.await_args.kwargs["key"] == physical
    assert job.file_path == logical


@pytest.mark.anyio
async def test_presigned_reupload_round_trip_uses_tenant_provider_key(monkeypatch):
    from app.modules.catalog.datasets.api import router_reupload
    from app.processing.ingest.schemas import (
        PresignedCompleteRequest,
        PresignedUploadRequest,
    )

    dataset_id = uuid.uuid4()
    user = MagicMock(id=uuid.uuid4())
    dataset = MagicMock(id=dataset_id)
    job = MagicMock(id=uuid.uuid4(), user_metadata={})
    db = AsyncMock()
    storage = MagicMock()
    storage.generate_presigned_put_url.return_value = "https://storage.test/put"
    storage.exists = AsyncMock(return_value=True)
    port = MagicMock()
    port.create_ingest_job = AsyncMock(return_value=job)
    port.verify_completed_presigned_upload = AsyncMock(return_value=2)
    monkeypatch.setattr(settings, "storage_provider", "s3")
    monkeypatch.setattr(settings, "presigned_multipart_threshold_mb", 100)

    with (
        patch.object(router_reupload, "get_dataset", AsyncMock(return_value=dataset)),
        patch.object(router_reupload, "check_dataset_write_access", AsyncMock()),
        patch.object(router_reupload, "_assert_compatible_record_type"),
        patch.object(
            router_reupload,
            "get_allowed_extensions_list",
            AsyncMock(return_value=[".geojson"]),
        ),
        patch.object(
            router_reupload.UPLOAD_MAX_SIZE_MB, "get", AsyncMock(return_value=10)
        ),
        patch.object(router_reupload, "check_upload_quota", AsyncMock()),
        patch.object(router_reupload, "get_catalog_port", return_value=port),
        patch.object(router_reupload, "get_storage", return_value=storage),
        _tenant_mode(monkeypatch, "multi_tenant", TENANT_A),
    ):
        response = await router_reupload.request_presigned_reupload(
            dataset_id,
            PresignedUploadRequest(filename="roads.geojson", file_size=2),
            MagicMock(),
            user,
            db,
        )
        logical = f"staging/{job.id}/roads.geojson"
        physical = f"tenants/{TENANT_A}/{logical}"
        assert response.s3_key == physical
        assert job.user_metadata["s3_key"] == logical

        port.create_ingest_job.reset_mock()
        with patch.object(
            router_reupload,
            "_get_bound_reupload_job_or_404",
            AsyncMock(return_value=job),
        ):
            await router_reupload.complete_presigned_reupload(
                dataset_id,
                job.id,
                PresignedCompleteRequest(),
                MagicMock(),
                user,
                db,
            )

    storage.generate_presigned_put_url.assert_called_once_with(
        physical, "application/octet-stream"
    )
    storage.exists.assert_awaited_once_with(physical)
    assert port.verify_completed_presigned_upload.await_args.kwargs["key"] == physical
    assert job.file_path == logical


@pytest.mark.anyio
async def test_cleanup_and_retention_reaper_delete_only_tenant_key(
    monkeypatch, tmp_path
):
    from app.platform.jobs.router import fail_stale_jobs
    from app.processing.ingest import router

    logical = "staging/job-a/roads.geojson"
    physical = f"tenants/{TENANT_A}/{logical}"
    storage = AsyncMock()
    monkeypatch.setattr("app.platform.storage.get_storage", lambda: storage)
    monkeypatch.setattr(router, "get_storage", lambda: storage)

    with _tenant_mode(monkeypatch, "multi_tenant", TENANT_A):
        await router._cleanup_saved_upload(logical, "job-a")
    storage.delete.assert_awaited_once_with(physical)

    storage.reset_mock()
    collision = tmp_path / logical
    collision.parent.mkdir(parents=True)
    collision.write_bytes(b"not-owned-by-reaper")
    staging_root = tmp_path / "configured-staging"
    staging_root.mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(settings, "upload_staging_dir", str(staging_root))
    monkeypatch.setattr(settings, "ingest_jobs_retention_days", 1)

    empty_scalars = [MagicMock() for _ in range(4)]
    for result in empty_scalars:
        result.scalars.return_value = []
    deleted = MagicMock()
    deleted.all.return_value = [(logical,)]
    survivors = MagicMock()
    survivors.scalars.return_value = []
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[*empty_scalars, deleted, survivors])

    with _tenant_mode(monkeypatch, "multi_tenant", TENANT_A):
        await fail_stale_jobs(db)

    storage.delete.assert_awaited_once_with(physical)
    assert collision.read_bytes() == b"not-owned-by-reaper"


@pytest.mark.anyio
async def test_hosted_storage_writes_fail_before_provider_call_without_context(
    monkeypatch,
):
    from app.processing.ingest.service import save_upload_file

    storage = AsyncMock()
    monkeypatch.setattr(settings, "storage_provider", "s3")
    monkeypatch.setattr("app.platform.storage.get_storage", lambda: storage)

    with _tenant_mode(monkeypatch, "multi_tenant", None):
        with pytest.raises(RuntimeError, match="requires tenant context"):
            await save_upload_file(_upload(), "job-a", max_size_bytes=100)

    storage.put.assert_not_called()
    storage.delete.assert_not_called()
