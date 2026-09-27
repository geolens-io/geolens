"""A managed raster's download follows the configured provider, not its row.

Every writer tags a managed raster ``local`` whatever the provider, so a row
exactly as a first import or a replacement leaves it has to reach the S3
redirect once the install stores its COGs in a bucket and enables presigned
downloads.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.config import settings
from app.modules.catalog.datasets.domain.models import Dataset
from app.platform.jobs.models import IngestJob
from app.processing.ingest.tasks_raster import ingest_raster
from app.processing.ingest.tasks_raster_replace import reupload_raster
from app.processing.raster.models import RasterAsset
from tests.factories import get_user_id
from tests.test_raster_replace_1221 import (
    _geotiff_bytes,
    _make_live_raster,
    _purge,
    _queue_replace_job,
)
from tests.test_raster_replace_1221 import raster_storage as raster_storage

pytestmark = pytest.mark.anyio


@pytest.fixture
def bucket(monkeypatch):
    """An ``S3StorageProvider`` on a moto bucket, not yet the configured store."""
    import boto3
    from moto import mock_aws

    from app.platform.storage.s3 import S3StorageProvider

    for var in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"):
        monkeypatch.setenv(var, "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    with mock_aws():
        boto3.client("s3", region_name="us-east-1").create_bucket(Bucket="tag-2390")
        yield S3StorageProvider(
            bucket="tag-2390",
            region="us-east-1",
            access_key_id="testing",
            secret_access_key="testing",
        )


async def _serve_from_the_bucket(monkeypatch, local, bucket, key: str) -> None:
    """Hold the COG where an S3 install keeps it, and configure the install so,
    presigned downloads enabled."""
    import app.platform.storage.provider as provider_module

    await bucket.put(key, await local.get(key))
    monkeypatch.setattr(provider_module, "_storage", bucket)
    monkeypatch.setattr(settings, "storage_provider", "s3")
    monkeypatch.setattr(settings, "s3_presigned_downloads", True)


async def _asset(session, dataset_id) -> RasterAsset:
    session.expire_all()
    return await session.scalar(
        select(RasterAsset).where(RasterAsset.dataset_id == dataset_id)
    )


async def test_a_first_import_on_an_s3_install_redirects_its_download(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
    raster_storage,
    bucket,
    tmp_path,
    monkeypatch,
) -> None:
    """The row a first import writes reaches the presigned redirect unedited."""
    admin_id = await get_user_id(test_db_session, "admin")
    source = tmp_path / "first.tif"
    source.write_bytes(_geotiff_bytes(seed=7))
    job = IngestJob(
        source_filename="first.tif",
        file_path=str(source),
        created_by=admin_id,
        status="pending",
        user_metadata={"file_type": "raster", "title": "Storage tag first import"},
    )
    test_db_session.add(job)
    await test_db_session.commit()
    await test_db_session.refresh(job)
    job_id = job.id
    with patch("app.processing.embeddings.helpers.defer_embedding", new=AsyncMock()):
        await ingest_raster.func(
            job_id=str(job_id),
            file_path=str(source),
            user_id=str(admin_id),
            attempt_id=str(job.attempt_id),
        )
    dataset_id = await test_db_session.scalar(
        select(IngestJob.dataset_id).where(IngestJob.id == job_id)
    )
    asset = await _asset(test_db_session, dataset_id)
    record_id = await test_db_session.scalar(
        select(Dataset.record_id).where(Dataset.id == dataset_id)
    )
    try:
        assert asset.storage_backend == "local"
        await _serve_from_the_bucket(
            monkeypatch, raster_storage, bucket, asset.asset_uri
        )

        get = await client.get(
            f"/datasets/{dataset_id}/download/cog",
            headers=admin_auth_header,
            follow_redirects=False,
        )

        assert get.status_code == 302, (
            f"a first import's COG on an S3 install answered {get.status_code}"
        )
        assert asset.asset_uri in get.headers["location"]
        assert (await _asset(test_db_session, dataset_id)).storage_backend == "local"
    finally:
        await _purge(test_db_session, dataset_id=dataset_id, record_id=record_id)


async def test_a_replacement_on_an_s3_install_redirects_its_download(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
    raster_storage,
    bucket,
    tmp_path,
    monkeypatch,
) -> None:
    """The row a replacement writes reaches the presigned redirect unedited."""
    admin_id = await get_user_id(test_db_session, "admin")
    live = await _make_live_raster(test_db_session, raster_storage, created_by=admin_id)
    dataset_id, record_id = live.dataset.id, live.dataset.record_id
    source = tmp_path / f"replacement-{uuid.uuid4().hex[:6]}.tif"
    source.write_bytes(_geotiff_bytes(seed=11))
    job = await _queue_replace_job(
        test_db_session, dataset_id=dataset_id, user_id=admin_id, file_path=str(source)
    )
    try:
        with patch(
            "app.processing.embeddings.helpers.defer_embedding", new=AsyncMock()
        ):
            await reupload_raster.func(
                job_id=str(job.id),
                dataset_id=str(dataset_id),
                file_path=str(source),
                user_id=str(admin_id),
                attempt_id=str(job.attempt_id),
            )
        asset = await _asset(test_db_session, dataset_id)
        assert asset.asset_uri != live.cog_key, "the replacement didn't land"
        assert asset.storage_backend == "local"
        await _serve_from_the_bucket(
            monkeypatch, raster_storage, bucket, asset.asset_uri
        )

        get = await client.get(
            f"/datasets/{dataset_id}/download/cog",
            headers=admin_auth_header,
            follow_redirects=False,
        )

        assert get.status_code == 302, (
            f"a replacement's COG on an S3 install answered {get.status_code}"
        )
        assert asset.asset_uri in get.headers["location"]
    finally:
        await _purge(test_db_session, dataset_id=dataset_id, record_id=record_id)


@pytest.mark.parametrize(
    ("provider", "tag", "is_admin", "asset_uri", "expected"),
    [
        ("s3", "local", True, "rasters/d/cog.tif", "s3://tag-bucket/rasters/d/cog.tif"),
        ("s3", "s3", True, "rasters/d/cog.tif", "s3://tag-bucket/rasters/d/cog.tif"),
        ("s3", "local", False, "rasters/d/cog.tif", None),
        ("s3", "remote", True, "https://example.test/cog.tif", None),
        ("local", "local", True, "rasters/d/cog.tif", None),
        ("azure", "local", True, "rasters/d/cog.tif", None),
        ("s3", "local", True, "/srv/geolens/cog.tif", None),
        ("s3", "local", True, "rasters/../cog.tif", None),
    ],
)
def test_the_admin_s3_uri_follows_the_provider(
    monkeypatch,
    provider: str,
    tag: str,
    is_admin: bool,
    asset_uri: str,
    expected: str | None,
) -> None:
    """Admins see a managed COG's bucket URI on an S3 install, whatever its tag,
    and none for a hand-edited key the storage resolver refuses."""
    from types import SimpleNamespace

    from app.modules.catalog.datasets.domain.helpers import _build_raster_metadata

    monkeypatch.setattr(settings, "storage_provider", provider)
    monkeypatch.setattr(settings, "s3_bucket", "tag-bucket")
    dataset = SimpleNamespace(
        id=uuid.uuid4(),
        record=SimpleNamespace(record_type="raster_dataset"),
        tile_cache_version=None,
        publication_version=None,
    )
    asset = RasterAsset(asset_uri=asset_uri, storage_backend=tag)

    metadata = _build_raster_metadata(dataset, asset, is_admin=is_admin)

    assert metadata.connect.s3_uri == expected
