"""Tenant ownership regressions for transient ingest storage objects."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
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

    # fix(#1235 review r3): a real created_at, because the presign path now
    # signs against the job's remaining lifetime. A MagicMock here yields
    # int(MagicMock) == 1 and the assertion below would pin a meaningless TTL.
    job = MagicMock(
        id=uuid.uuid4(),
        user_metadata={},
        created_at=datetime.now(timezone.utc),
    )
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
    signed_key, signed_type, signed_ttl = (
        storage.generate_presigned_put_url.call_args.args
    )
    assert (signed_key, signed_type) == (physical, "application/octet-stream")
    # Signed against the job deadline, so very nearly the whole window.
    assert 3595 <= signed_ttl <= 3600, signed_ttl
    assert response.s3_key == physical
    assert job.user_metadata["s3_key"] == logical


@pytest.mark.anyio
async def test_presigned_completion_reads_physical_and_keeps_logical_job_path(
    monkeypatch,
):
    from app.processing.ingest import presigned as presigned_module
    from app.processing.ingest import router
    from app.processing.ingest.schemas import PresignedCompleteRequest

    logical = "staging/job-a/roads.geojson"
    physical = f"tenants/{TENANT_A}/{logical}"
    # fix(#1202 review): completion freezes the upload to an unwritable key
    # first and judges THAT, so the tenant prefix has to survive the derivation.
    frozen_logical = "staging/job-a/frozen/roads.geojson"
    frozen_physical = f"tenants/{TENANT_A}/{frozen_logical}"
    job = MagicMock(
        id=uuid.uuid4(),
        source_filename="roads.geojson",
        # fix(#1202 review): completion is one-shot and keys off file_path, so
        # the mock has to start where create_ingest_job leaves a presigned job
        # — empty — rather than with MagicMock's truthy auto-attribute.
        file_path="",
        user_metadata={
            "presigned": True,
            "s3_key": logical,
            "multipart": False,
            "expected_size": 2,
        },
    )
    db = AsyncMock()
    # fix(#1202 review r5): completion re-fetches the row FOR UPDATE before
    # reading file_path, so the locked fetch has to yield the SAME job the
    # test configured — a bare AsyncMock returns a fresh mock whose truthy
    # file_path trips the one-shot guard.
    db.get = AsyncMock(return_value=job)
    storage = AsyncMock()
    storage.exists.return_value = True
    # fix(#1202): completion content-validates from a ranged read of the
    # physical key, so the fake has to serve bytes rather than a sentinel.
    storage.get_range.return_value = b"{}"
    # The pre-copy size fast path measures the staging object before the
    # freeze, so the fake needs a real integer here.
    storage.size.return_value = 2
    verify = AsyncMock(return_value=2)

    with (
        patch.object(router, "get_job_or_404", AsyncMock(return_value=job)),
        patch.object(router, "get_storage", return_value=storage),
        # fix(#1207): the completion sequence moved into presigned.py so both
        # doors share it, so verify is patched at its new home.
        patch.object(presigned_module, "verify_completed_presigned_upload", verify),
        patch.object(router.UPLOAD_MAX_SIZE_MB, "get", AsyncMock(return_value=10)),
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
    # The snapshot is taken from the physical staging key to the physical
    # frozen key; everything downstream then judges the frozen one.
    assert storage.copy.await_args.args == (physical, frozen_physical)
    assert verify.await_args.kwargs["key"] == frozen_physical
    assert storage.get_range.await_args.args[0] == frozen_physical
    assert job.file_path == frozen_logical
    # The staging object is dropped once the frozen copy is the job's source.
    assert storage.delete.await_args.args == (physical,)


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
    # fix(#1207): completion is one-shot and keys off file_path, so the mock
    # starts where create_ingest_job leaves a presigned job — empty.
    job = MagicMock(id=uuid.uuid4(), user_metadata={}, file_path="")
    db = AsyncMock()
    storage = MagicMock()
    storage.generate_presigned_put_url.return_value = "https://storage.test/put"
    storage.exists = AsyncMock(return_value=True)
    port = MagicMock()
    port.create_ingest_job = AsyncMock(return_value=job)
    # fix(#1207): the reupload door reaches the whole completion sequence
    # through one port method now; it returns the frozen LOGICAL key.
    port.lock_presigned_job = AsyncMock(return_value=job)
    port.should_assemble_multipart = AsyncMock(return_value=False)

    async def _fake_finalize(*, logical_key, **_kwargs):
        from app.processing.ingest.presigned import frozen_staging_key

        return frozen_staging_key(logical_key)

    port.finalize_presigned_object = AsyncMock(side_effect=_fake_finalize)
    # fix(#1235 review r3/r4): a real TTL, for the same reason as above.
    port.require_signable_job_lifetime = MagicMock(return_value=1800)

    # fix(#1235 review r8): the door signs through one port call that computes
    # the expiration inside the signing thread, so this fake has to actually
    # invoke the storage method. A bare MagicMock would put a mock where the
    # URL string belongs and the tenant-key assertion below would never run.
    def _fake_sign(storage_method, _created_at, *args):
        return storage_method(*args, 1800)

    port.sign_url_with_deadline = MagicMock(side_effect=_fake_sign)
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
        patch.object(router_reupload, "check_replacement_quota", AsyncMock()),
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
        physical, "application/octet-stream", 1800
    )
    # fix(#1207): the door no longer probes storage itself — the existence
    # check moved inside finalize_presigned_object, which resolves the tenant
    # namespace from the logical key it is handed (asserted below). What stays
    # this door's job is minting the presign against the PHYSICAL key, above,
    # and the multipart gate, which still receives the physical key.
    assert port.should_assemble_multipart.await_args.args[2] == physical
    # The door hands finalize the LOGICAL key; the helper resolves the tenant
    # namespace itself, which is what keeps the two doors identical here.
    assert port.finalize_presigned_object.await_args.kwargs["logical_key"] == logical
    # fix(#1207): the door binds the FROZEN key, not the client-writable
    # staging one — the whole point of the freeze. Tenant prefix still absent
    # from what is stored, exactly as before.
    assert job.file_path == f"staging/{job.id}/frozen/roads.geojson"


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

    # fix(#1234): five sweep statements now — the pending clause is two, one
    # for unbound rows at 1h and one for bound-but-uncommitted at 24h.
    # feat(#1219): six, with the abandoned-refresh-run sweep after them.
    # fix(#1274 review): seven — the refresh-run sweep is two statements,
    # the legacy-completion recorder before the abandonment cancel.
    # fix(#1322 review round 3): eight — the VRT RasterAsset UPDATE split
    # into two (composition-preserving -> 'ready', composition-changed ->
    # 'failed'). Both .scalars() and .all() are set on every result: the
    # VrtGeneration UPDATE in that same sweep reads via .all(), and this
    # fixture doesn't care which statement lands at which index, only that
    # every accessor the sweep might call returns an empty result.
    # fix(#1709 review r7): nine — the childless-`fanned_out` reconciliation
    # (a fan-out parent whose dispatch died before its first child
    # committed) runs between the running-jobs sweep and the VRT sweep.
    empty_scalars = [MagicMock() for _ in range(9)]
    for result in empty_scalars:
        result.scalars.return_value = []
        result.all.return_value = []
    deleted = MagicMock()
    # fix(#1202 review r5): the purge's RETURNING is (id, file_path,
    # user_metadata) now — it also reaps the presigned staging key, which
    # needs the row's own id to decide ownership. No s3_key here, so this
    # row still contributes exactly one delete.
    deleted.all.return_value = [(uuid.uuid4(), logical, None)]
    survivors = MagicMock()
    survivors.scalars.return_value = []
    # fix(#1746): the terminal-row service-token purge, the last statement
    # inside the transaction. It reads nothing back, so an unconfigured
    # result is enough; it just has to occupy its position.
    token_purge = MagicMock()
    # fix(#1202 review r8): one more SELECT for the post-expiry staging sweep.
    post_expiry = MagicMock()
    post_expiry.all.return_value = []
    db = AsyncMock()
    db.execute = AsyncMock(
        side_effect=[*empty_scalars, deleted, survivors, token_purge, post_expiry]
    )

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
