"""A COPC point cloud uploads, previews, commits and publishes without GDAL, and a killed
attempt's copy is reaped by the job sweep."""

from __future__ import annotations

import inspect
import io
import uuid
from contextlib import contextmanager, nullcontext
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import boto3
import pytest
from fastapi import HTTPException
from httpx import AsyncClient
from moto import mock_aws
from sqlalchemy import select, text

import app.platform.storage.provider as storage_provider
from app.core.config import settings
from app.core.pointcloud import (
    LAZ_WITHOUT_KIND,
    POINTCLOUD_ASSET_KEY,
    POINTCLOUD_MEDIA_TYPE,
    pointcloud_attempt_key,
    pointcloud_prefix,
)
from app.core.upload_errors import UnsafeUploadError
from app.modules.catalog.datasets.api.router_reupload import (
    _assert_compatible_record_type,
)
from app.modules.catalog.datasets.domain.models import Dataset, Record
from app.platform.jobs.models import UNPUBLISHED_STORAGE_KEYS_FIELD, IngestJob
from app.platform.jobs.sweep import (
    fail_stale_jobs,
    unpublished_storage_keys_from_metadata,
)
from app.platform.storage.s3 import S3StorageProvider
from app.processing.embeddings.tasks import embed_record
from app.processing.ingest import manifest_service
from app.processing.ingest import router as ingest_router
from app.processing.ingest.tasks import ingest_pointcloud, task_app
from app.processing.raster.models import DatasetAsset
from tests.factories import create_user
from tests.pointcloud_files import copc, copc_nodes, scrambled

_CLOUD = copc()
_DECODE_FAILED = "The point cloud's points don't decode as its header describes."


@pytest.fixture
def laz_allowed(monkeypatch) -> None:
    """The doors' allowed list with .laz added, as an operator adds it."""

    async def _allowed(_db):
        return [*settings.allowed_extensions_list, ".laz"]

    monkeypatch.setattr(ingest_router, "get_allowed_extensions_list", _allowed)


@pytest.fixture
async def uploader(
    client: AsyncClient, admin_auth_header: dict, test_db_session, laz_allowed
):
    """An editor on an install that allows .laz, whose datasets and jobs are removed afterwards."""
    headers, user_id = await create_user(client, admin_auth_header, "editor")
    yield headers, uuid.UUID(user_id)
    # A committed pointcloud row blocks the migration tests' downgrades past 0070.
    await test_db_session.rollback()
    for table in ("records", "ingest_jobs"):
        await test_db_session.execute(
            text(f"DELETE FROM catalog.{table} WHERE created_by = :user"),
            {"user": user_id},
        )
    await test_db_session.commit()


@pytest.fixture
def queued(monkeypatch) -> list:
    """Each deferred task and its arguments, instead of the queue."""
    calls: list = []

    async def _defer(task, **kwargs):
        calls.append((task, kwargs))

    monkeypatch.setattr("app.processing.ingest.service.defer_async_with_tenant", _defer)
    monkeypatch.setattr(
        "app.processing.embeddings.helpers.defer_async_with_tenant", _defer
    )
    return calls


def _quota(cap: int):
    return patch(
        "app.modules.quota.service.MAX_STORAGE_BYTES_PER_USER.get",
        new=AsyncMock(return_value=cap),
    )


async def upload(
    client: AsyncClient,
    headers: dict,
    data: bytes = _CLOUD,
    *,
    kind: str | None = "pointcloud",
    filename: str = "site.copc.laz",
):
    return await client.post(
        "/ingest/upload",
        files={"file": (filename, data, "application/octet-stream")},
        data={"kind": kind} if kind else {},
        headers=headers,
    )


async def commit(client: AsyncClient, headers: dict, job_id: str, **fields):
    return await client.post(
        f"/ingest/commit/{job_id}",
        json={"title": "Site", "visibility": "public", **fields},
        headers=headers,
    )


async def run_queued(queued: list) -> None:
    task, kwargs = queued.pop()
    assert task is ingest_pointcloud, f"dispatched {task.name}"
    await task.func(**kwargs)


async def committed_upload(client, headers, data: bytes = _CLOUD) -> str:
    """Upload, preview and commit; returns the job id."""
    uploaded = await upload(client, headers, data)
    assert uploaded.status_code == 201, uploaded.text
    job_id = uploaded.json()["job_id"]
    previewed = await client.post(f"/ingest/preview/{job_id}", headers=headers)
    assert previewed.status_code == 200, previewed.text
    committed = await commit(client, headers, job_id)
    assert committed.status_code == 202, committed.text
    return job_id


async def publish(client, headers, queued, data: bytes = _CLOUD) -> str:
    """Upload, preview, commit and run the worker; returns the job id."""
    job_id = await committed_upload(client, headers, data)
    await run_queued(queued)
    return job_id


async def load_job(session, job_id) -> IngestJob:
    session.expire_all()
    return (
        await session.execute(select(IngestJob).where(IngestJob.id == job_id))
    ).scalar_one()


async def pointcloud_objects(dataset_id=None) -> list[str]:
    prefix = pointcloud_prefix(dataset_id) if dataset_id else "pointclouds/"
    return sorted(await storage_provider.get_storage().list(prefix))


async def jobs_of(session, user_id) -> list:
    rows = await session.execute(
        select(IngestJob.id).where(IngestJob.created_by == user_id)
    )
    return rows.all()


# --- The published point cloud -------------------------------------------


async def test_a_point_cloud_publishes_its_dataset_pointer_and_object(
    client: AsyncClient, test_db_session, uploader, queued
) -> None:
    """One transaction creates the record, the dataset with its facts, and the pointer."""
    headers, user_id = uploader
    uploaded = await upload(client, headers)
    assert uploaded.status_code == 201, uploaded.text
    job_id = uploaded.json()["job_id"]

    previewed = await client.post(f"/ingest/preview/{job_id}", headers=headers)
    assert previewed.status_code == 200, previewed.text
    preview = previewed.json()
    assert {k: v for k, v in preview.items() if k != "extent_bbox"} == {
        "job_id": job_id,
        "source_filename": "site.copc.laz",
        "point_count": 100,
        "point_format": 6,
        "srid": 26912,
        "vertical_crs": "NAVD88 height",
        "z_min": 1280.0,
        "z_max": 1281.0,
        "size_bytes": len(_CLOUD),
    }
    staged = (await load_job(test_db_session, job_id)).file_path

    committed = await commit(client, headers, job_id)
    assert committed.status_code == 202, committed.text
    await run_queued(queued)

    job = await load_job(test_db_session, job_id)
    assert job.status == "complete", job.error_message
    dataset = (
        await test_db_session.execute(
            select(Dataset).where(Dataset.id == job.dataset_id)
        )
    ).scalar_one()
    record = await test_db_session.get(Record, dataset.record_id)
    assert (record.record_type, record.created_by) == ("pointcloud_dataset", user_id)
    assert (dataset.source_format, dataset.table_name[:11]) == ("copc", "pointcloud_")
    assert (
        dataset.srid,
        dataset.z_min,
        dataset.z_max,
        dataset.pointcloud_point_count,
        dataset.pointcloud_point_format,
        dataset.pointcloud_vertical_crs,
    ) == (26912, 1280.0, 1281.0, 100, 6, "NAVD88 height")
    key = pointcloud_attempt_key(dataset.id, job.attempt_id)
    pointer = (
        await test_db_session.execute(
            select(DatasetAsset).where(
                DatasetAsset.dataset_id == dataset.id,
                DatasetAsset.key == POINTCLOUD_ASSET_KEY,
            )
        )
    ).scalar_one()
    assert (pointer.href, pointer.media_type, pointer.size_bytes) == (
        key,
        POINTCLOUD_MEDIA_TYPE,
        len(_CLOUD),
    )
    assert await pointcloud_objects(dataset.id) == [key]
    assert await storage_provider.get_storage().get(key) == _CLOUD
    assert not Path(staged).exists()

    detail = await client.get(f"/datasets/{dataset.id}", headers=headers)
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["pointcloud"] == {
        "size_bytes": len(_CLOUD),
        "point_count": 100,
        "point_format": 6,
        "vertical_crs": "NAVD88 height",
    }
    assert body["extent_bbox"] == pytest.approx(preview["extent_bbox"], abs=1e-6)
    assert queued == [(embed_record, {"record_id": str(record.id)})]


# --- The doors -----------------------------------------------------------


@pytest.mark.parametrize("door", ["multipart", "presigned"])
async def test_a_default_install_refuses_a_point_cloud(
    client: AsyncClient, admin_auth_header: dict, test_db_session, monkeypatch, door
) -> None:
    """The default allowed list leaves .laz out, so a point cloud gets the usual 400."""
    headers, user_id = await create_user(client, admin_auth_header, "editor")
    monkeypatch.setattr(
        settings, "storage_provider", "s3" if door == "presigned" else "local"
    )
    if door == "multipart":
        resp = await upload(client, headers)
    else:
        resp = await client.post(
            "/ingest/upload/presigned",
            json={
                "filename": "site.copc.laz",
                "file_size": len(_CLOUD),
                "kind": "pointcloud",
            },
            headers=headers,
        )

    assert resp.status_code == 400, resp.text
    detail = resp.json()["detail"]
    assert (detail["code"], detail["extension"]) == ("disallowed_extension", ".laz")
    assert await jobs_of(test_db_session, uuid.UUID(user_id)) == []


@pytest.mark.parametrize("door", ["multipart", "presigned"])
async def test_a_file_that_is_not_laz_is_refused_with_the_conversion_hint(
    client: AsyncClient, test_db_session, uploader, monkeypatch, door
) -> None:
    """A .las sent as a point cloud gets pointcloud_not_copc before any job exists."""
    headers, user_id = uploader
    monkeypatch.setattr(
        settings, "storage_provider", "s3" if door == "presigned" else "local"
    )
    if door == "multipart":
        resp = await upload(client, headers, b"LASF", filename="site.las")
    else:
        resp = await client.post(
            "/ingest/upload/presigned",
            json={"filename": "site.las", "file_size": 4, "kind": "pointcloud"},
            headers=headers,
        )

    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"]["code"] == "pointcloud_not_copc"
    assert "writers.copc" in resp.json()["detail"]["message"]
    assert await jobs_of(test_db_session, user_id) == []


@pytest.mark.parametrize("door", ["multipart", "presigned", "url"])
async def test_a_laz_without_the_point_cloud_kind_is_refused(
    client: AsyncClient, test_db_session, uploader, monkeypatch, door
) -> None:
    """A .laz holds only a point cloud, so no upload door takes one without the kind."""
    headers, user_id = uploader
    monkeypatch.setattr(
        settings, "storage_provider", "s3" if door == "presigned" else "local"
    )
    if door == "multipart":
        resp = await upload(client, headers, kind=None)
    elif door == "presigned":
        resp = await client.post(
            "/ingest/upload/presigned",
            json={"filename": "site.copc.laz", "file_size": len(_CLOUD)},
            headers=headers,
        )
    else:
        resp = await client.post(
            "/ingest/upload/url",
            json={"url": "https://files.example.test/site.copc.laz"},
            headers=headers,
        )

    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"] == {
        "code": "pointcloud_kind_required",
        "message": LAZ_WITHOUT_KIND,
        "file_type": "pointcloud",
    }
    assert await jobs_of(test_db_session, user_id) == []


async def test_a_url_import_takes_no_point_cloud_kind(
    client: AsyncClient, uploader
) -> None:
    """The URL door fetches tilesets only; a point cloud is uploaded."""
    resp = await client.post(
        "/ingest/upload/url",
        json={"url": "https://files.example.test/site.copc.laz", "kind": "pointcloud"},
        headers=uploader[0],
    )

    assert resp.status_code == 422, resp.text


def test_a_replacement_takes_no_laz() -> None:
    """No dataset's data can be replaced by a point cloud."""
    dataset = SimpleNamespace(record=SimpleNamespace(record_type="vector_dataset"))

    with pytest.raises(HTTPException) as refusal:
        _assert_compatible_record_type(dataset, "site.copc.laz")

    assert (refusal.value.status_code, refusal.value.detail) == (400, LAZ_WITHOUT_KIND)


async def test_a_manifest_entry_takes_no_laz(monkeypatch) -> None:
    """A manifest names no kind, so a .laz source is refused before staging."""

    async def _allowed(_db):
        return [".laz"]

    monkeypatch.setattr(manifest_service, "get_allowed_extensions_list", _allowed)
    prepared = SimpleNamespace(source_filename="site.copc.laz")

    with pytest.raises(ValueError, match="kind=pointcloud"):
        await manifest_service._validate_prepared_source(None, prepared)


@pytest.mark.parametrize(
    ("data", "code"),
    [
        (copc(info_first=False), "pointcloud_not_copc"),
        (copc(wkt=None), "pointcloud_no_crs"),
        (copc(header_point_count=99), "pointcloud_invalid"),
        (copc(chunk=lambda chunk: bytes(len(chunk))), "pointcloud_decode_failed"),
        (b"SQLite format 3\x00" + bytes(512), "pointcloud_invalid"),
    ],
    ids=["plain-laz", "no-crs", "invalid", "decode", "renamed-database"],
)
async def test_the_upload_door_refuses_a_file_that_fails_a_check(
    client: AsyncClient, test_db_session, uploader, tmp_path, data, code
) -> None:
    """Each refusal is a 422 carrying its code, and the staged file is gone."""
    headers, user_id = uploader

    resp = await upload(client, headers, data)

    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    assert (detail["code"], set(detail)) == (code, {"code", "message"})
    job = (
        await test_db_session.execute(
            select(IngestJob).where(IngestJob.created_by == user_id)
        )
    ).scalar_one()
    assert (job.status, job.file_path) == ("failed", "")
    assert list((tmp_path / "staging").glob("*.laz")) == []


async def test_fan_out_queues_nothing_for_a_point_cloud(
    client: AsyncClient, test_db_session, uploader, queued
) -> None:
    """A point cloud job has no layers, so the fan-out door queues no vector import."""
    headers, _ = uploader
    job_id = (await upload(client, headers)).json()["job_id"]

    resp = await client.post(
        f"/ingest/commit-fan-out/{job_id}",
        json={"layers": [{"layer_name": "site"}]},
        headers=headers,
    )

    assert resp.status_code == 422, resp.text
    assert queued == []
    assert (await load_job(test_db_session, job_id)).status == "pending"


# --- GDAL isolation (Rule 2) ---------------------------------------------


@contextmanager
def _gdal_unreachable(monkeypatch):
    reached: list[str] = []

    async def _subprocess(*args, **kwargs):
        reached.append("a GDAL subprocess")
        raise AssertionError("a GDAL subprocess reached")

    def _rasterio_open(*args, **kwargs):
        reached.append("rasterio.open")
        raise AssertionError("rasterio.open reached")

    monkeypatch.setattr(
        "app.processing.ingest.ogr.asyncio.create_subprocess_exec", _subprocess
    )
    monkeypatch.setattr("rasterio.open", _rasterio_open)
    yield reached


async def test_a_point_cloud_upload_never_reaches_gdal(
    client: AsyncClient, test_db_session, uploader, queued, monkeypatch
) -> None:
    """Upload, preview, commit and publish run without a GDAL process or open."""
    headers, _ = uploader
    with _gdal_unreachable(monkeypatch) as reached:
        job_id = await publish(client, headers, queued)

    assert reached == []
    assert (await load_job(test_db_session, job_id)).status == "complete"


# --- Quota and failure ---------------------------------------------------


async def test_the_worker_refuses_an_overshoot_before_the_copy(
    client: AsyncClient, test_db_session, uploader, queued, monkeypatch
) -> None:
    """Usage that grew after the commit is refused before the file is copied."""
    headers, _ = uploader
    job_id = (await upload(client, headers)).json()["job_id"]
    assert (await commit(client, headers, job_id)).status_code == 202
    stored = AsyncMock()
    monkeypatch.setattr(
        "app.processing.ingest.tasks_pointcloud.store_pointcloud", stored
    )

    with _quota(len(_CLOUD) - 1), pytest.raises(Exception, match="quota exceeded"):
        await run_queued(queued)

    stored.assert_not_called()
    job = await load_job(test_db_session, job_id)
    assert (job.status, job.dataset_id) == ("failed", None)
    assert await pointcloud_objects() == []


async def test_the_size_is_checked_again_at_commit(
    client: AsyncClient, test_db_session, uploader, queued
) -> None:
    """Usage that grew after the upload is caught at commit, before anything is queued."""
    headers, _ = uploader
    job_id = (await upload(client, headers)).json()["job_id"]

    with _quota(len(_CLOUD) - 1):
        resp = await commit(client, headers, job_id)

    assert resp.status_code == 413, resp.text
    assert queued == []
    assert (await load_job(test_db_session, job_id)).status == "pending"


async def test_another_user_cannot_preview_a_point_cloud(
    client: AsyncClient, uploader, admin_auth_header, monkeypatch
) -> None:
    """The job's owner check runs before the file is read."""
    job_id = (await upload(client, uploader[0])).json()["job_id"]
    other, _ = await create_user(client, admin_auth_header, "editor")
    inspected = AsyncMock()
    monkeypatch.setattr(
        "app.processing.ingest.pointcloud.inspect_staged_pointcloud", inspected
    )

    resp = await client.post(f"/ingest/preview/{job_id}", headers=other)

    assert resp.status_code == 403, resp.text
    inspected.assert_not_called()


async def test_a_file_that_changed_since_the_door_is_refused_before_the_copy(
    client: AsyncClient, test_db_session, uploader, queued
) -> None:
    """The worker checks the staged file again and copies nothing it refuses."""
    headers, _ = uploader
    job_id = (await upload(client, headers)).json()["job_id"]
    assert (await commit(client, headers, job_id)).status_code == 202
    staged = Path((await load_job(test_db_session, job_id)).file_path)
    staged.write_bytes(copc(wkt=None))

    with pytest.raises(UnsafeUploadError):
        await run_queued(queued)

    job = await load_job(test_db_session, job_id)
    assert job.status == "failed"
    assert "coordinate reference system" in job.error_message
    assert await pointcloud_objects() == []


# --- Every node, in the worker -------------------------------------------


async def test_a_point_cloud_of_several_nodes_publishes(
    client: AsyncClient, test_db_session, uploader, queued
) -> None:
    """The worker decodes each node of a sound file and publishes it as uploaded."""
    data = copc_nodes()

    job_id = await publish(client, uploader[0], queued, data)

    job = await load_job(test_db_session, job_id)
    assert job.status == "complete", job.error_message
    dataset = await test_db_session.get(Dataset, job.dataset_id)
    key = pointcloud_attempt_key(job.dataset_id, job.attempt_id)
    assert dataset.pointcloud_point_count == 370
    assert await storage_provider.get_storage().get(key) == data


async def test_a_damaged_node_below_the_top_is_refused_before_the_copy(
    client: AsyncClient, test_db_session, uploader, queued
) -> None:
    """The doors pass it on its top node; the worker refuses it before naming or copying a key."""
    job_id = await committed_upload(
        client, uploader[0], copc_nodes(last_chunk=scrambled)
    )
    staged = Path((await load_job(test_db_session, job_id)).file_path)

    with pytest.raises(UnsafeUploadError):
        await run_queued(queued)

    job = await load_job(test_db_session, job_id)
    assert (job.status, job.error_message) == ("failed", _DECODE_FAILED)
    assert UNPUBLISHED_STORAGE_KEYS_FIELD not in job.user_metadata
    assert await pointcloud_objects() == []
    assert staged.exists()


# --- Presigned doors on S3 -----------------------------------------------


@pytest.fixture
def s3_storage(client, monkeypatch):
    """S3 mode against a moto bucket, on every storage lookup."""
    credential = uuid.uuid4().hex
    for name in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"):
        monkeypatch.setenv(name, credential)
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    with mock_aws():
        boto3.client("s3", region_name="us-east-1").create_bucket(Bucket="copc")
        storage = S3StorageProvider(
            bucket="copc",
            region="us-east-1",
            access_key_id=credential,
            secret_access_key=credential,
        )
        monkeypatch.setattr(settings, "storage_provider", "s3")
        monkeypatch.setattr(storage_provider, "_storage", storage)
        yield storage


async def presigned_upload(client, headers, storage, data: bytes = _CLOUD):
    presigned = await client.post(
        "/ingest/upload/presigned",
        json={
            "filename": "site.copc.laz",
            "file_size": len(data),
            "kind": "pointcloud",
        },
        headers=headers,
    )
    assert presigned.status_code == 201, presigned.text
    body = presigned.json()
    # Stands in for the browser's PUT to the presigned URL.
    await storage.put(body["s3_key"], io.BytesIO(data))
    completed = await client.post(
        f"/ingest/upload/presigned/{body['job_id']}/complete", json={}, headers=headers
    )
    return body, completed


async def test_a_presigned_point_cloud_publishes_from_s3(
    client: AsyncClient, test_db_session, uploader, queued, s3_storage
) -> None:
    """The presigned doors read the file in place and the worker copies it within S3."""
    headers, _ = uploader
    body, completed = await presigned_upload(client, headers, s3_storage)
    assert completed.status_code == 200, completed.text
    job_id = body["job_id"]

    previewed = await client.post(f"/ingest/preview/{job_id}", headers=headers)
    assert previewed.status_code == 200, previewed.text
    assert previewed.json()["point_count"] == 100
    assert (await commit(client, headers, job_id)).status_code == 202
    await run_queued(queued)

    job = await load_job(test_db_session, job_id)
    assert job.status == "complete", job.error_message
    key = pointcloud_attempt_key(job.dataset_id, job.attempt_id)
    assert await s3_storage.list(pointcloud_prefix(job.dataset_id)) == [key]
    assert await s3_storage.get(key) == _CLOUD
    assert await s3_storage.list(f"staging/{job_id}/") == []


@pytest.mark.parametrize("damaged", [False, True], ids=["published", "refused"])
async def test_a_stored_point_cloud_is_decoded_from_a_download_that_is_removed(
    client: AsyncClient,
    test_db_session,
    uploader,
    queued,
    s3_storage,
    tmp_path,
    damaged,
) -> None:
    """The worker decodes every node from a local copy of the object, then removes the copy."""
    headers, _ = uploader
    data = copc_nodes(last_chunk=scrambled if damaged else None)
    body, completed = await presigned_upload(client, headers, s3_storage, data)
    assert completed.status_code == 200, completed.text
    job_id = body["job_id"]
    previewed = await client.post(f"/ingest/preview/{job_id}", headers=headers)
    assert previewed.status_code == 200, previewed.text
    assert (await commit(client, headers, job_id)).status_code == 202

    with pytest.raises(UnsafeUploadError) if damaged else nullcontext():
        await run_queued(queued)

    job = await load_job(test_db_session, job_id)
    stored = await s3_storage.list("pointclouds/")
    if damaged:
        assert (job.status, job.error_message, stored) == ("failed", _DECODE_FAILED, [])
    else:
        assert job.status == "complete", job.error_message
        assert stored == [pointcloud_attempt_key(job.dataset_id, job.attempt_id)]
    assert not any((tmp_path / "staging").iterdir())


async def test_a_refused_point_cloud_is_dropped_at_presigned_complete(
    client: AsyncClient, test_db_session, uploader, s3_storage
) -> None:
    """A file that fails a check is a coded 422 at completion, with both objects gone."""
    headers, _ = uploader

    body, completed = await presigned_upload(
        client, headers, s3_storage, copc(header_point_count=99)
    )

    assert completed.status_code == 422, completed.text
    assert completed.json()["detail"]["code"] == "pointcloud_invalid"
    assert await s3_storage.list(f"staging/{body['job_id']}/") == []
    job = await load_job(test_db_session, body["job_id"])
    assert (job.status, job.file_path) == ("pending", "")


# --- Interruption --------------------------------------------------------


class _NoDelete:
    """The configured storage, minus deletes: as after a SIGKILL, no cleanup runs."""

    def __init__(self, storage) -> None:
        self._storage = storage

    def __getattr__(self, name):
        return getattr(self._storage, name)

    async def delete(self, key):
        return None


async def interrupted_attempt(client, headers, queued) -> str:
    """Commit a point cloud whose attempt copies its file and dies before publishing."""
    job_id = (await upload(client, headers)).json()["job_id"]
    assert (await commit(client, headers, job_id)).status_code == 202
    real = storage_provider.get_storage()
    with (
        patch(
            "app.processing.ingest.tasks_pointcloud.create_pointcloud_dataset",
            AsyncMock(side_effect=RuntimeError("worker killed")),
        ),
        patch.object(storage_provider, "_storage", _NoDelete(real)),
        pytest.raises(RuntimeError, match="worker killed"),
    ):
        await run_queued(queued)
    return job_id


async def test_an_interrupted_attempts_copy_is_reaped(
    client: AsyncClient, test_db_session, uploader, queued
) -> None:
    """The key named before the copy licenses reaping it."""
    job_id = await interrupted_attempt(client, uploader[0], queued)
    job = await load_job(test_db_session, job_id)
    (key,) = job.user_metadata[UNPUBLISHED_STORAGE_KEYS_FIELD]
    assert job.status == "failed"
    assert await pointcloud_objects() == [key]

    outcome = await fail_stale_jobs(test_db_session, detailed=True)

    assert await pointcloud_objects() == []
    assert outcome.storage_objects_reaped >= 1
    job = await load_job(test_db_session, job_id)
    assert UNPUBLISHED_STORAGE_KEYS_FIELD not in job.user_metadata


async def test_the_live_copy_is_never_reaped(
    client: AsyncClient, test_db_session, uploader, queued
) -> None:
    """After a retry publishes, the dead attempt's copy is reaped and the live one kept."""
    headers, _ = uploader
    job_id = await interrupted_attempt(client, headers, queued)
    retried = await client.post(f"/jobs/{job_id}/retry", headers=headers)
    assert retried.status_code == 202, retried.text
    await run_queued(queued)
    job = await load_job(test_db_session, job_id)
    dead, live = job.user_metadata[UNPUBLISHED_STORAGE_KEYS_FIELD]
    assert job.status == "complete", job.error_message
    assert live == pointcloud_attempt_key(job.dataset_id, job.attempt_id)

    await fail_stale_jobs(test_db_session, detailed=True)

    assert await pointcloud_objects() == [live]
    job = await load_job(test_db_session, job_id)
    assert UNPUBLISHED_STORAGE_KEYS_FIELD not in job.user_metadata


@pytest.mark.parametrize(
    "key",
    [
        "pointclouds/",
        f"pointclouds/{uuid.uuid4()}/",
        f"pointclouds/{uuid.uuid4()}/{uuid.uuid4()}/other.laz",
        f"pointclouds/{uuid.uuid4()}/../{uuid.uuid4()}/data.copc.laz",
        f"pointclouds/x/{uuid.uuid4()}/data.copc.laz",
        f"POINTCLOUDS/{uuid.uuid4()}/{uuid.uuid4()}/data.copc.laz",
        f"x{pointcloud_attempt_key(uuid.uuid4(), uuid.uuid4())}",
        f"{pointcloud_attempt_key(uuid.uuid4(), uuid.uuid4())}x",
        f"{pointcloud_attempt_key(uuid.uuid4(), uuid.uuid4())}/",
    ],
    ids=[
        "root",
        "dataset",
        "other-name",
        "dotdot",
        "not-uuid",
        "upper",
        "text-before",
        "text-after",
        "slash-after",
    ],
)
def test_only_an_attempt_shaped_point_cloud_key_is_read_back(key) -> None:
    """Anything but pointclouds/{uuid}/{uuid}/data.copc.laz is dropped before the reap."""
    live = pointcloud_attempt_key(uuid.uuid4(), uuid.uuid4())
    metadata = {UNPUBLISHED_STORAGE_KEYS_FIELD: [key, live]}

    assert unpublished_storage_keys_from_metadata(metadata) == (live,)


async def test_a_killed_running_attempt_is_reaped_once_settled(
    client: AsyncClient, test_db_session
) -> None:
    """A running row past its lease is settled failed, then its copy is reaped."""
    key = pointcloud_attempt_key(uuid.uuid4(), uuid.uuid4())
    await storage_provider.get_storage().put(key, b"LASF")
    stale = datetime.now(timezone.utc) - timedelta(hours=2)
    job = IngestJob(
        file_path="",
        status="running",
        started_at=stale,
        heartbeat_at=stale,
        user_metadata={UNPUBLISHED_STORAGE_KEYS_FIELD: [key]},
    )
    test_db_session.add(job)
    await test_db_session.commit()
    job_id = job.id
    try:
        await fail_stale_jobs(test_db_session, detailed=True)

        assert await pointcloud_objects() == []
        assert (await load_job(test_db_session, job_id)).status == "failed"
    finally:
        await test_db_session.rollback()
        await test_db_session.execute(
            text("DELETE FROM catalog.ingest_jobs WHERE id = :id"), {"id": job_id}
        )
        await test_db_session.commit()


# --- The task contract ---------------------------------------------------


def test_the_point_cloud_task_keeps_its_name_queue_and_arguments() -> None:
    """A queued point cloud job resolves to this task and binds these arguments."""
    task = task_app.tasks["app.processing.ingest.tasks_pointcloud.ingest_pointcloud"]
    signature = inspect.signature(task.func)

    assert task is ingest_pointcloud
    assert (task.queue, task.retry_strategy, task.pass_context) == (
        "raster",
        None,
        False,
    )
    assert [(p.name, p.kind, p.default) for p in signature.parameters.values()] == [
        ("job_id", inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.empty),
        ("file_path", inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.empty),
        ("user_id", inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.empty),
        ("attempt_id", inspect.Parameter.POSITIONAL_OR_KEYWORD, None),
        ("kwargs", inspect.Parameter.VAR_KEYWORD, inspect.Parameter.empty),
    ]
