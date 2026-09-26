"""A published replacement stays published whatever its post-commit steps do."""

from __future__ import annotations

import asyncio
import io
import uuid
from collections.abc import Awaitable, Callable, Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import numpy as np
import pytest
from rasterio.crs import CRS
from rasterio.io import MemoryFile
from rasterio.transform import from_bounds
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.modules.catalog.datasets.domain.models import Dataset, Record
from app.platform.dataset_origin import (
    build_origin_ref,
    set_dataset_origin,
    set_postgis_origin,
)
from app.platform.jobs.models import IngestJob
from app.platform.refresh.models import DatasetRefreshRun
from app.platform.refresh.service import create_pending_run
from app.platform.storage.local import LocalStorageProvider
from app.processing.ingest.publish_followups import run_owed_publish_followups
from app.processing.ingest.tasks_postgis_refresh import refresh_postgis
from app.processing.ingest.tasks_raster_common import PublishObservation
from app.processing.ingest.tasks_raster_replace import reupload_raster
from app.processing.ingest.tasks_reupload import reupload_file, reupload_service
from app.processing.ingest.tasks_stac_refresh import refresh_stac
from app.processing.raster.models import RasterAsset
from tests.factories import create_dataset, get_user_id

pytestmark = pytest.mark.anyio

_SQUARE = "POLYGON((0 0, 0 1, 1 1, 1 0, 0 0))"
_WFS_BASE = "https://services.example.com/wfs"
_STAC_ITEM = "https://stac.example.com/api/collections/scenes/items/scene-1"
_STAC_ASSET = "https://stac.example.com/tiles/scene.tif"
_STAC_MOVED_ASSET = "https://stac.example.com/v2/tiles/scene.tif"


@dataclass
class _Replacement:
    """One seeded replacement attempt and the checks for its published state."""

    job_id: uuid.UUID
    dataset_id: uuid.UUID
    run: Callable[[], Awaitable[None]]
    assert_published: Callable[[], Awaitable[None]]
    # The uploader's source file, for the paths that receive one.
    upload: Path | None = None
    # Where a presigned completion leaves the upload instead: its frozen copy,
    # then the client's key.
    staged_keys: list[str] = field(default_factory=list)
    live_table: str | None = None
    # Objects the replacement supersedes, for raster.
    prior_keys: list[str] = field(default_factory=list)


async def _fresh_scalar(statement):
    """Read one value on a session of its own, past the test session's cache."""
    import app.core.db as db_module

    async with db_module.async_session() as session:
        return await session.scalar(statement)


async def _seed_job_and_run(
    session: AsyncSession,
    *,
    dataset_id: uuid.UUID,
    created_by: uuid.UUID,
    origin_kind: str,
    **job_fields,
) -> IngestJob:
    job = IngestJob(
        dataset_id=dataset_id, status="pending", created_by=created_by, **job_fields
    )
    session.add(job)
    await session.flush()
    await create_pending_run(
        session,
        dataset_id=dataset_id,
        origin_kind=origin_kind,
        trigger="manual",
        triggered_by=created_by,
        ingest_job_id=job.id,
        feature_count_before=1,
    )
    await session.commit()
    await session.refresh(job)
    return job


async def _stage_in_storage(
    session: AsyncSession, storage: LocalStorageProvider, job: IngestJob, upload: Path
) -> list[str]:
    """Move ``upload`` to where a presigned completion leaves it and bind ``job`` to it."""
    frozen = f"staging/{job.id}/frozen/{upload.name}"
    client_key = f"staging/{job.id}/{upload.name}"
    for key in (frozen, client_key):
        await storage.put(key, upload.read_bytes())
    upload.unlink()
    job.file_path = frozen
    job.user_metadata = {**job.user_metadata, "s3_key": client_key}
    await session.commit()
    return [frozen, client_key]


async def _upload_left(
    replacement: _Replacement, storage: LocalStorageProvider
) -> list[str]:
    """What is left of the replacement's upload, on disk or in storage."""
    left = [key for key in replacement.staged_keys if await storage.exists(key)]
    if replacement.upload is not None and replacement.upload.exists():
        left.append(str(replacement.upload))
    return left


async def _create_point_table(session: AsyncSession, table: str, name: str) -> None:
    await session.execute(
        text(
            f'CREATE TABLE "data"."{table}" '
            "(gid serial PRIMARY KEY, geom geometry(Point, 4326), name text)"
        )
    )
    await session.execute(
        text(
            f'INSERT INTO "data"."{table}" (geom, name) VALUES '
            f"(ST_SetSRID(ST_MakePoint(2.35, 48.85), 4326), '{name}')"
        )
    )


async def _assert_live_row(table: str, name: str) -> None:
    rows = await _fresh_scalar(
        text(f'SELECT array_agg(name ORDER BY gid) FROM "data"."{table}"')
    )
    assert rows == [name], f"the live table holds {rows}, not the replacement"


async def _fake_ogr2ogr(file_path, staging_table, db_conn_str, **kwargs):
    import app.core.db as db_module

    async with db_module.async_session() as staging_session:
        await _create_point_table(staging_session, staging_table, "after")
        await staging_session.commit()


async def _run_file_reupload(
    job: IngestJob, dataset_id: uuid.UUID, admin_id: uuid.UUID, file_path: str
) -> None:
    with ExitStack() as stack:
        stack.enter_context(
            patch(
                "app.processing.ingest.tasks_reupload._validate_upload_file_safety",
                new=AsyncMock(),
            )
        )
        stack.enter_context(
            patch(
                "app.processing.ingest.ogr.run_ogrinfo",
                new=AsyncMock(
                    return_value={
                        "srid": 4326,
                        "geometry_type": "Point",
                        "layer_name": "update",
                        "feature_count": 1,
                        "columns": [{"name": "name", "type": "String"}],
                    }
                ),
            )
        )
        stack.enter_context(
            patch(
                "app.processing.ingest.ogr.run_ogr2ogr",
                new=AsyncMock(side_effect=_fake_ogr2ogr),
            )
        )
        await reupload_file.func(
            job_id=str(job.id),
            dataset_id=str(dataset_id),
            file_path=file_path,
            user_id=str(admin_id),
            attempt_id=str(job.attempt_id),
        )


async def _file_replacement(
    session: AsyncSession,
    tmp_path: Path,
    storage: LocalStorageProvider,
    *,
    in_storage: bool = False,
) -> _Replacement:
    admin_id = await get_user_id(session, "admin")
    table = f"s2file_{uuid.uuid4().hex[:10]}"
    dataset = await create_dataset(
        session,
        created_by=admin_id,
        table_name=table,
        visibility="private",
        record_type="vector_dataset",
        geometry_type="Point",
        feature_count=1,
        source_format="geojson",
        source_filename="original.geojson",
        column_info=[{"name": "name", "type": "character varying"}],
    )
    await _create_point_table(session, table, "before")
    upload = Path(settings.upload_staging_dir) / "update.geojson"
    upload.write_text('{"type":"FeatureCollection","features":[]}')
    job = await _seed_job_and_run(
        session,
        dataset_id=dataset.id,
        created_by=admin_id,
        origin_kind="upload",
        source_filename="update.geojson",
        file_path=str(upload),
        user_metadata={"reupload": True, "dataset_id": str(dataset.id)},
    )
    staged_keys = (
        await _stage_in_storage(session, storage, job, upload) if in_storage else []
    )
    file_path = job.file_path

    async def run() -> None:
        await _run_file_reupload(job, dataset.id, admin_id, file_path)

    async def assert_published() -> None:
        await _assert_live_row(table, "after")
        version = await _fresh_scalar(
            select(Dataset.current_version).where(Dataset.id == dataset.id)
        )
        assert version == 2

    return _Replacement(
        job.id,
        dataset.id,
        run,
        assert_published,
        upload=None if in_storage else upload,
        staged_keys=staged_keys,
        live_table=table,
    )


async def _service_replacement(
    session: AsyncSession, tmp_path: Path, storage: LocalStorageProvider
) -> _Replacement:
    admin_id = await get_user_id(session, "admin")
    table = f"s2svc_{uuid.uuid4().hex[:10]}"
    dataset = await create_dataset(
        session,
        created_by=admin_id,
        table_name=table,
        visibility="private",
        record_type="vector_dataset",
        geometry_type="Point",
        feature_count=1,
        source_format="wfs",
        source_filename="parcels",
        column_info=[{"name": "name", "type": "character varying"}],
    )
    set_dataset_origin(
        dataset,
        "service",
        uri=f"{_WFS_BASE}/topp:parcels",
        service_type="wfs",
        url=_WFS_BASE,
        layer_id="topp:parcels",
    )
    await _create_point_table(session, table, "before")
    job = await _seed_job_and_run(
        session,
        dataset_id=dataset.id,
        created_by=admin_id,
        origin_kind="service",
        source_filename="parcels",
        source_url=_WFS_BASE,
        source_layer="topp:parcels",
        user_metadata={
            "reupload": True,
            "dataset_id": str(dataset.id),
            "service_type": "WFS 2.0.0",
            "layer_id": None,
            "source_type": "service_url",
        },
    )

    async def _fake_service_fetch(
        gdal_source, layer_name, table_name, db_conn_str, service_type, **kwargs
    ):
        import app.core.db as db_module

        async with db_module.async_session() as staging_session:
            await _create_point_table(staging_session, table_name, "after")
            await staging_session.commit()

    async def run() -> None:
        with (
            patch("app.platform.security.validate_url_for_ssrf", new=AsyncMock()),
            patch(
                "app.processing.ingest.ogr.run_ogr2ogr_service",
                new=AsyncMock(side_effect=_fake_service_fetch),
            ),
        ):
            await reupload_service.func(
                job_id=str(job.id),
                dataset_id=str(dataset.id),
                source_url=_WFS_BASE,
                source_layer="topp:parcels",
                user_id=str(admin_id),
                attempt_id=str(job.attempt_id),
            )

    async def assert_published() -> None:
        await _assert_live_row(table, "after")
        version = await _fresh_scalar(
            select(Dataset.current_version).where(Dataset.id == dataset.id)
        )
        assert version == 2

    return _Replacement(job.id, dataset.id, run, assert_published, live_table=table)


def _geotiff_bytes(*, seed: int) -> bytes:
    profile = {
        "driver": "GTiff",
        "dtype": "uint8",
        "width": 32,
        "height": 32,
        "count": 1,
        "crs": CRS.from_epsg(4326),
        "transform": from_bounds(-180, -90, 180, 90, 32, 32),
    }
    rng = np.random.default_rng(seed)
    with MemoryFile() as mem:
        with mem.open(**profile) as raster:
            raster.write(rng.integers(0, 200, (32, 32), dtype="uint8"), 1)
        return mem.read()


async def _raster_replacement(
    session: AsyncSession,
    tmp_path: Path,
    storage: LocalStorageProvider,
    *,
    in_storage: bool = False,
) -> _Replacement:
    admin_id = await get_user_id(session, "admin")
    record = Record(
        title="Post-commit raster",
        record_type="raster_dataset",
        visibility="private",
        record_status="published",
        created_by=admin_id,
        updated_by=admin_id,
        theme_category=["test"],
    )
    session.add(record)
    await session.flush()
    dataset = Dataset(
        record_id=record.id,
        table_name=f"raster_s2_{record.id.hex[:16]}",
        source_format="geotiff",
        source_filename="original.tif",
        srid=4326,
    )
    session.add(dataset)
    await session.flush()
    base_key = f"rasters/{dataset.id}/originalsha"
    prior_keys = [
        f"{base_key}/source.cog.tif",
        f"{base_key}/quicklook_256.png",
        f"{base_key}/quicklook_512.png",
    ]
    original = _geotiff_bytes(seed=1)
    session.add(
        RasterAsset(
            dataset_id=dataset.id,
            asset_uri=prior_keys[0],
            quicklook_256_uri=prior_keys[1],
            quicklook_512_uri=prior_keys[2],
            sha256="0" * 64,
            size_bytes=len(original),
            driver="GTiff",
            storage_backend="local",
            epsg=4326,
            band_count=1,
            dtype="uint8",
        )
    )
    await session.commit()
    for key, payload in zip(prior_keys, (original, b"ql-256", b"ql-512"), strict=True):
        await storage.put(key, io.BytesIO(payload))

    upload = Path(settings.upload_staging_dir) / "replacement.tif"
    upload.write_bytes(_geotiff_bytes(seed=42))
    job = await _seed_job_and_run(
        session,
        dataset_id=dataset.id,
        created_by=admin_id,
        origin_kind="upload",
        source_filename="replacement.tif",
        file_path=str(upload),
        user_metadata={"reupload": True, "dataset_id": str(dataset.id)},
    )
    staged_keys = (
        await _stage_in_storage(session, storage, job, upload) if in_storage else []
    )
    file_path = job.file_path

    async def run() -> None:
        await reupload_raster.func(
            job_id=str(job.id),
            dataset_id=str(dataset.id),
            file_path=file_path,
            user_id=str(admin_id),
            attempt_id=str(job.attempt_id),
        )

    async def assert_published() -> None:
        import app.core.db as db_module

        async with db_module.async_session() as check:
            asset = await check.scalar(
                select(RasterAsset).where(RasterAsset.dataset_id == dataset.id)
            )
        assert asset.asset_uri != prior_keys[0], "the pointer did not move"
        for key in (asset.asset_uri, asset.quicklook_256_uri, asset.quicklook_512_uri):
            assert await storage.exists(key), f"{key} was reaped after publication"

    return _Replacement(
        job.id,
        dataset.id,
        run,
        assert_published,
        upload=None if in_storage else upload,
        staged_keys=staged_keys,
        prior_keys=prior_keys,
    )


async def _postgis_replacement(
    session: AsyncSession, tmp_path: Path, storage: LocalStorageProvider
) -> _Replacement:
    admin_id = await get_user_id(session, "admin")
    table = f"s2pg_{uuid.uuid4().hex[:10]}"
    await session.execute(
        text(
            f'CREATE TABLE "data"."{table}" (gid serial PRIMARY KEY, name text, '
            "geom geometry(Polygon, 4326), geom_4326 geometry(Polygon, 4326))"
        )
    )
    for name in ("row-0", "row-1"):
        await session.execute(
            text(
                f'INSERT INTO "data"."{table}" (name, geom, geom_4326) VALUES '
                f"('{name}', ST_GeomFromText('{_SQUARE}', 4326), "
                f"ST_GeomFromText('{_SQUARE}', 4326))"
            )
        )
    await session.commit()
    dataset = await create_dataset(
        session,
        created_by=admin_id,
        table_name=table,
        visibility="private",
        geometry_type="POLYGON",
        feature_count=1,
        column_info=[
            {"name": "name", "type": "text", "ordinal_position": 2, "is_nullable": True}
        ],
        source_format=None,
        source_filename=None,
    )
    set_postgis_origin(dataset, table, schema="data")
    await session.commit()
    job = await _seed_job_and_run(
        session, dataset_id=dataset.id, created_by=admin_id, origin_kind="postgis"
    )

    async def run() -> None:
        await refresh_postgis.func(
            job_id=str(job.id),
            dataset_id=str(dataset.id),
            attempt_id=str(job.attempt_id),
        )

    async def assert_published() -> None:
        count = await _fresh_scalar(
            select(Dataset.feature_count).where(Dataset.id == dataset.id)
        )
        assert count == 2, "the re-measured count was not written"

    return _Replacement(job.id, dataset.id, run, assert_published, live_table=table)


def _stac_transport(request: httpx.Request) -> httpx.Response:
    if str(request.url) == _STAC_ITEM:
        return httpx.Response(
            200,
            json={
                "type": "Feature",
                "id": "scene-1",
                "collection": "scenes",
                "properties": {"proj:code": "EPSG:32633"},
                "bbox": [10.0, 45.0, 11.0, 46.0],
                "links": [{"rel": "self", "href": _STAC_ITEM}],
                "assets": {
                    "data": {
                        "href": _STAC_MOVED_ASSET,
                        "roles": ["data"],
                        "type": "image/tiff",
                    }
                },
            },
        )
    if str(request.url) == _STAC_MOVED_ASSET:
        return httpx.Response(206)
    return httpx.Response(404)


def _stac_client(timeout=10.0, **_kwargs) -> httpx.AsyncClient:
    async def _handle(request: httpx.Request) -> httpx.Response:
        return _stac_transport(request)

    return httpx.AsyncClient(transport=httpx.MockTransport(_handle), timeout=timeout)


async def _stac_replacement(
    session: AsyncSession, tmp_path: Path, storage: LocalStorageProvider
) -> _Replacement:
    admin_id = await get_user_id(session, "admin")
    dataset = await create_dataset(
        session,
        created_by=admin_id,
        visibility="private",
        source_format="stac",
        source_filename="scene-1",
        srid=4326,
    )
    dataset.record.record_type = "raster_dataset"
    dataset.origin_uri = _STAC_ASSET
    dataset.origin_ref = build_origin_ref(
        "stac",
        asset_href=_STAC_ASSET,
        item_href=_STAC_ITEM,
        item_id="scene-1",
        collection_id="scenes",
        asset_key="data",
    )
    session.add(
        RasterAsset(
            dataset_id=dataset.id,
            asset_uri=_STAC_ASSET,
            storage_backend="remote",
            cog_status="verified",
            epsg=4326,
            ingested_at=datetime.now(timezone.utc) - timedelta(days=30),
        )
    )
    await session.commit()
    job = await _seed_job_and_run(
        session, dataset_id=dataset.id, created_by=admin_id, origin_kind="stac"
    )

    async def run() -> None:
        gate = "app.modules.catalog.sources.stac_resolve_asset_gate"
        with (
            patch(f"{gate}.validate_url_for_ssrf", new=AsyncMock()),
            patch(
                f"{gate}.fetch_cog_info",
                new=AsyncMock(
                    return_value={"band_count": 1, "dtype": "uint16", "nodata": 0}
                ),
            ),
            patch(
                "app.modules.catalog.sources.origin_probe.make_safe_client",
                new=_stac_client,
            ),
        ):
            await refresh_stac.func(
                job_id=str(job.id),
                dataset_id=str(dataset.id),
                attempt_id=str(job.attempt_id),
            )

    async def assert_published() -> None:
        origin_uri = await _fresh_scalar(
            select(Dataset.origin_uri).where(Dataset.id == dataset.id)
        )
        assert origin_uri == _STAC_MOVED_ASSET, "the pointer did not move"

    return _Replacement(job.id, dataset.id, run, assert_published)


_BUILDERS = {
    "file": _file_replacement,
    "service": _service_replacement,
    "raster": _raster_replacement,
    "postgis": _postgis_replacement,
    "stac": _stac_replacement,
}

# Where each path looks up the post-commit steps it runs.
_STEPS = {
    "file": {
        "catalog cache": "app.processing.ingest.publication.invalidate_catalog_cache",
        "tile cache": (
            "app.processing.ingest.publication.invalidate_tile_cache_for_table"
        ),
        "archive": "app.processing.ingest.tasks_reupload._archive_original_file",
        "embedding": "app.processing.embeddings.helpers.defer_embedding",
    },
    "service": {
        "catalog cache": "app.processing.ingest.publication.invalidate_catalog_cache",
        "tile cache": (
            "app.processing.ingest.publication.invalidate_tile_cache_for_table"
        ),
        "embedding": "app.processing.embeddings.helpers.defer_embedding",
    },
    "raster": {
        "catalog cache": "app.processing.ingest.publication.invalidate_catalog_cache",
        "embedding": "app.processing.embeddings.helpers.defer_embedding",
    },
    "postgis": {
        "catalog cache": "app.processing.ingest.publication.invalidate_catalog_cache",
        "tile cache": (
            "app.processing.ingest.publication.invalidate_tile_cache_for_table"
        ),
        "embedding": "app.processing.embeddings.helpers.defer_embedding",
    },
    "stac": {
        "catalog cache": "app.processing.ingest.publication.invalidate_catalog_cache",
    },
}


@pytest.fixture
def storage(tmp_path, monkeypatch) -> LocalStorageProvider:
    """A real local storage provider on a temporary directory."""
    provider = LocalStorageProvider(str(tmp_path / "objects"))
    for target in (
        "app.platform.storage.get_storage",
        "app.processing.ingest.tasks_common.get_storage",
        "app.processing.ingest.tasks_staging.get_storage",
    ):
        monkeypatch.setattr(target, lambda: provider, raising=True)
    return provider


@pytest.fixture
async def replace(test_db_session, tmp_path, storage):
    """Seed one replacement of the requested kind and drop its tables afterwards."""
    import app.core.db as db_module

    created: list[_Replacement] = []

    async def _seed(kind: str, **options) -> _Replacement:
        replacement = await _BUILDERS[kind](
            test_db_session, tmp_path, storage, **options
        )
        created.append(replacement)
        return replacement

    yield _seed
    # Data tables outlive the test on the shared database unless dropped here.
    # The record's delete cascades to the dataset and its runs, so a job or
    # run a test leaves running never reaches a later test's unscoped sweep.
    async with db_module.async_session() as cleanup:
        for replacement in created:
            await cleanup.execute(
                text("DELETE FROM catalog.ingest_jobs WHERE id = :id"),
                {"id": replacement.job_id},
            )
            await cleanup.execute(
                text(
                    "DELETE FROM catalog.records WHERE id = "
                    "(SELECT record_id FROM catalog.datasets WHERE id = :id)"
                ),
                {"id": replacement.dataset_id},
            )
            if replacement.live_table is not None:
                await cleanup.execute(
                    text(
                        f'DROP TABLE IF EXISTS "data"."{replacement.live_table}" '
                        "CASCADE"
                    )
                )
        await cleanup.commit()


async def _assert_settled_published(replacement: _Replacement) -> None:
    status = await _fresh_scalar(
        select(IngestJob.status).where(IngestJob.id == replacement.job_id)
    )
    assert status == "complete"
    run_status = await _fresh_scalar(
        select(DatasetRefreshRun.status).where(
            DatasetRefreshRun.ingest_job_id == replacement.job_id
        )
    )
    assert run_status == "succeeded"
    await replacement.assert_published()


@contextmanager
def _quiet_embedding() -> Iterator[None]:
    with patch("app.processing.embeddings.helpers.defer_embedding", new=AsyncMock()):
        yield


_FAILING_STEPS = [
    (kind, step) for kind, steps in _STEPS.items() for step in sorted(steps)
]


@pytest.mark.parametrize(
    ("kind", "step"), _FAILING_STEPS, ids=[f"{k}-{s}" for k, s in _FAILING_STEPS]
)
async def test_a_failing_post_commit_step_leaves_the_replacement_published(
    replace, kind: str, step: str
) -> None:
    """A post-commit step that raises is logged; the job, run and data stay published."""
    replacement = await replace(kind)
    failing = AsyncMock(side_effect=RuntimeError(f"{step} unavailable"))
    with _quiet_embedding(), patch(_STEPS[kind][step], new=failing):
        await replacement.run()

    assert failing.await_count >= 1, f"the {step} step never ran"
    await _assert_settled_published(replacement)
    if replacement.upload is not None:
        assert not replacement.upload.exists(), (
            "a completed replacement deletes its upload even when a "
            "post-commit step fails"
        )


class _LostAcknowledgement:
    """Make the commit that completes ``job_id`` raise after it has applied."""

    def __init__(self, job_id: uuid.UUID, failure: BaseException) -> None:
        self.job_id = job_id
        self.failure = failure
        self.fired = 0

    @contextmanager
    def installed(self) -> Iterator[None]:
        real_commit = AsyncSession.commit

        async def _commit(session, *args, **kwargs):
            await real_commit(session, *args, **kwargs)
            if self.fired:
                return
            status = await _fresh_scalar(
                select(IngestJob.status).where(IngestJob.id == self.job_id)
            )
            if status == "complete":
                self.fired += 1
                raise self.failure

        AsyncSession.commit = _commit
        try:
            yield
        finally:
            AsyncSession.commit = real_commit


_FAILURES = {
    "connection-loss": lambda: ConnectionResetError("the connection dropped"),
    "cancellation": asyncio.CancelledError,
}


class _IndeterminatePublish:
    """Fail the publishing commit before it lands, leaving its transaction open.

    The probe, asking once, then reads the transaction in progress, or, with
    ``probe_fails``, cannot read it at all.
    """

    def __init__(self, job_id: uuid.UUID, *, probe_fails: bool = False) -> None:
        self.job_id = job_id
        self.probe_fails = probe_fails
        self.commit_failed = False
        self.probe_failed = False

    @contextmanager
    def installed(self) -> Iterator[None]:
        real_commit = AsyncSession.commit
        real_scalar = AsyncSession.scalar
        own_status = select(IngestJob.status).where(IngestJob.id == self.job_id)

        async def _commit(session, *args, **kwargs):
            if not self.commit_failed:
                # The publishing transaction is the one that already shows
                # the job complete from inside itself.
                status = (await session.execute(own_status)).scalar()
                if status == "complete":
                    self.commit_failed = True
                    raise ConnectionResetError("the connection dropped before COMMIT")
            return await real_commit(session, *args, **kwargs)

        async def _scalar(session, statement, *args, **kwargs):
            asks_outcome = "pg_xact_status" in str(statement)
            if self.probe_fails and self.commit_failed and asks_outcome:
                self.probe_failed = True
                raise ConnectionResetError("the probe could not reach the database")
            return await real_scalar(session, statement, *args, **kwargs)

        AsyncSession.commit = _commit
        AsyncSession.scalar = _scalar
        try:
            with patch(
                "app.processing.ingest.tasks_raster_common.PUBLISH_PROBE_RETRIES", 0
            ):
                yield
        finally:
            AsyncSession.commit = real_commit
            AsyncSession.scalar = real_scalar


def _stored_keys(storage: LocalStorageProvider, dataset_id: uuid.UUID) -> set[str]:
    root = Path(storage.base_dir)
    return {
        str(path.relative_to(root))
        for path in (root / "rasters" / str(dataset_id)).rglob("*")
        if path.is_file()
    }


@pytest.mark.parametrize("publish", ["acknowledged", "observed"])
async def test_a_confirmed_publish_reaps_the_superseded_raster(
    replace, storage, publish: str
) -> None:
    """A confirmed publish reaps the superseded COG and quicklooks, even when the cache purge fails."""
    replacement = await replace("raster")
    lost = _LostAcknowledgement(replacement.job_id, ConnectionResetError("dropped"))
    with (
        _quiet_embedding(),
        patch(
            _STEPS["raster"]["catalog cache"],
            new=AsyncMock(side_effect=RuntimeError("valkey unavailable")),
        ),
        lost.installed() if publish == "observed" else ExitStack(),
    ):
        await replacement.run()

    for key in replacement.prior_keys:
        assert not await storage.exists(key), f"the superseded {key} survived"


@pytest.mark.parametrize("purge", ["failing", "working"])
@pytest.mark.parametrize("probe_fails", [False, True], ids=["in-progress", "no-probe"])
async def test_an_indeterminate_publish_keeps_every_raster_object(
    replace, storage, purge: str, probe_fails: bool
) -> None:
    """A commit that may not have landed deletes neither the old raster nor the new one."""
    replacement = await replace("raster")
    indeterminate = _IndeterminatePublish(replacement.job_id, probe_fails=probe_fails)
    purge_step = (
        AsyncMock(side_effect=RuntimeError("valkey unavailable"))
        if purge == "failing"
        else AsyncMock()
    )
    with (
        _quiet_embedding(),
        patch(_STEPS["raster"]["catalog cache"], new=purge_step),
        indeterminate.installed(),
    ):
        await replacement.run()
    await run_owed_publish_followups()

    assert indeterminate.commit_failed
    assert indeterminate.probe_failed is probe_fails
    assert replacement.upload.exists(), (
        "the upload went though the publish never landed"
    )
    live_uri = await _fresh_scalar(
        select(RasterAsset.asset_uri).where(
            RasterAsset.dataset_id == replacement.dataset_id
        )
    )
    assert live_uri == replacement.prior_keys[0], "the swap did not roll back"
    stored = _stored_keys(storage, replacement.dataset_id)
    assert set(replacement.prior_keys) <= stored, "the live raster was reaped"
    assert len(stored - set(replacement.prior_keys)) == 3, (
        "the objects this attempt wrote were reaped"
    )


@pytest.mark.parametrize("probe_fails", [False, True], ids=["in-progress", "no-probe"])
async def test_an_indeterminate_publish_skips_the_file_archive(
    replace, storage, probe_fails: bool
) -> None:
    """A commit that may not have landed neither archives the upload nor deletes it, nor does the sweep."""
    replacement = await replace("file")
    indeterminate = _IndeterminatePublish(replacement.job_id, probe_fails=probe_fails)
    archive = AsyncMock()
    with (
        _quiet_embedding(),
        patch(_STEPS["file"]["archive"], new=archive),
        indeterminate.installed(),
    ):
        await replacement.run()
    await run_owed_publish_followups()

    assert indeterminate.commit_failed
    assert indeterminate.probe_failed is probe_fails
    archive.assert_not_awaited()
    assert await storage.list(f"originals/{replacement.dataset_id}/") == []
    await _assert_live_row(replacement.live_table, "before")
    assert replacement.upload.exists()


@pytest.mark.parametrize("failure", sorted(_FAILURES))
@pytest.mark.parametrize("kind", sorted(_BUILDERS))
async def test_a_lost_acknowledgement_stands_down_as_published(
    replace, storage, kind: str, failure: str
) -> None:
    """A commit that lands but loses its acknowledgement settles as published."""
    replacement = await replace(kind)
    lost = _LostAcknowledgement(replacement.job_id, _FAILURES[failure]())
    purge = AsyncMock()
    with (
        _quiet_embedding(),
        patch(_STEPS[kind]["catalog cache"], new=purge),
        lost.installed(),
    ):
        try:
            await replacement.run()
        except asyncio.CancelledError:
            pytest.fail("the cancellation escaped a published replacement")

    assert lost.fired == 1, "the publishing commit never ran"
    await _assert_settled_published(replacement)
    assert purge.await_count >= 1, "the post-commit steps were skipped"
    assert await _upload_left(replacement, storage) == [], (
        "the upload outlived a publish the probe saw land"
    )


async def _upload_bytes(replacement: _Replacement, storage) -> bytes:
    if replacement.upload is not None:
        return replacement.upload.read_bytes()
    return await storage.get(replacement.staged_keys[0])


async def _archived(replacement: _Replacement, storage) -> list[bytes]:
    """The originals archived under the replacement's dataset."""
    keys = await storage.list(f"originals/{replacement.dataset_id}/")
    return [await storage.get(key) for key in keys]


@pytest.mark.parametrize("in_storage", [False, True], ids=["local", "storage"])
@pytest.mark.parametrize("kind", ["file", "raster"])
async def test_a_publish_the_probe_saw_land_archives_then_deletes_the_upload(
    replace, storage, kind: str, in_storage: bool
) -> None:
    """A landed publish whose acknowledgement was lost leaves no upload, and a file upload archived."""
    replacement = await replace(kind, in_storage=in_storage)
    uploaded = await _upload_bytes(replacement, storage)
    lost = _LostAcknowledgement(replacement.job_id, ConnectionResetError("dropped"))
    with _quiet_embedding(), lost.installed():
        await replacement.run()

    assert lost.fired == 1, "the publishing commit never ran"
    await _assert_settled_published(replacement)
    assert await _upload_left(replacement, storage) == []
    if kind == "file":
        assert await _archived(replacement, storage) == [uploaded]


@pytest.mark.parametrize("in_storage", [False, True], ids=["local", "storage"])
@pytest.mark.parametrize("kind", ["file", "raster"])
async def test_a_publish_that_landed_unseen_is_cleaned_up_by_the_sweep(
    replace, storage, kind: str, in_storage: bool
) -> None:
    """An upload kept while the outcome was unknown goes once the sweep sees the publish, a file one archived first."""
    replacement = await replace(kind, in_storage=in_storage)
    uploaded = await _upload_bytes(replacement, storage)
    lost = _LostAcknowledgement(replacement.job_id, ConnectionResetError("dropped"))
    with (
        _quiet_embedding(),
        patch(
            "app.processing.ingest.publication.observe_publish_commit",
            new=AsyncMock(return_value=PublishObservation.UNKNOWN),
        ),
        # The claim that would see the commit too early to run.
        patch("app.processing.ingest.publication.run_publish_followups", AsyncMock()),
        lost.installed(),
    ):
        await replacement.run()

    assert lost.fired == 1, "the publishing commit never ran"
    kept = replacement.staged_keys or [str(replacement.upload)]
    assert await _upload_left(replacement, storage) == kept, (
        "the upload went while the outcome was unknown"
    )
    assert await _archived(replacement, storage) == []

    await run_owed_publish_followups()
    assert await _upload_left(replacement, storage) == []
    if kind == "file":
        assert await _archived(replacement, storage) == [uploaded], (
            "the upload went without its original being archived"
        )


async def _archives(replacement: _Replacement, storage) -> dict[str, bytes]:
    """Every original archived under the replacement's dataset, by key."""
    keys = await storage.list(f"originals/{replacement.dataset_id}/")
    return {key: await storage.get(key) for key in keys}


@contextmanager
def _landed_unseen(job_id: uuid.UUID) -> Iterator[None]:
    """A publish that lands while the task can tell neither that nor its end."""
    lost = _LostAcknowledgement(job_id, ConnectionResetError("dropped"))
    with (
        _quiet_embedding(),
        patch(
            "app.processing.ingest.publication.observe_publish_commit",
            new=AsyncMock(return_value=PublishObservation.UNKNOWN),
        ),
        patch("app.processing.ingest.publication.run_publish_followups", AsyncMock()),
        lost.installed(),
    ):
        yield


async def test_an_earlier_archive_under_the_uploads_filename_is_not_taken_for_it(
    replace, storage
) -> None:
    """The sweep archives a publish's own upload, whatever an earlier version left under its filename."""
    replacement = await replace("file")
    uploaded = replacement.upload.read_bytes()
    earlier = f"originals/{replacement.dataset_id}/{replacement.upload.name}"
    await storage.put(earlier, b"an earlier version")
    with _landed_unseen(replacement.job_id):
        await replacement.run()

    await run_owed_publish_followups()
    assert await _upload_left(replacement, storage) == []
    archives = await _archives(replacement, storage)
    assert archives.pop(earlier) == b"an earlier version"
    assert list(archives.values()) == [uploaded], (
        "the upload went without its own original archived"
    )


async def test_a_superseded_publish_never_overwrites_the_live_versions_archive(
    replace, storage, test_db_session
) -> None:
    """An upload whose publish was superseded is cleaned up without touching the newer version's archive."""
    import app.core.db as db_module

    first = await replace("file")
    with _landed_unseen(first.job_id):
        await first.run()

    # A second replacement of the same dataset, under the same filename.
    admin_id = await get_user_id(test_db_session, "admin")
    second_upload = Path(settings.upload_staging_dir) / "second" / first.upload.name
    second_upload.parent.mkdir()
    second_upload.write_text('{"type":"FeatureCollection","features":[],"v":2}')
    second_bytes = second_upload.read_bytes()
    second = await _seed_job_and_run(
        test_db_session,
        dataset_id=first.dataset_id,
        created_by=admin_id,
        origin_kind="upload",
        source_filename=first.upload.name,
        file_path=str(second_upload),
        user_metadata={"reupload": True, "dataset_id": str(first.dataset_id)},
    )
    try:
        with _quiet_embedding():
            await _run_file_reupload(
                second, first.dataset_id, admin_id, str(second_upload)
            )
        live_archive = await _archives(first, storage)
        assert list(live_archive.values()) == [second_bytes]

        await run_owed_publish_followups()
        assert await _upload_left(first, storage) == []
        for key, content in live_archive.items():
            assert await storage.get(key) == content, (
                "a superseded upload overwrote the live version's archive"
            )
    finally:
        async with db_module.async_session() as session:
            await session.execute(
                text("DELETE FROM catalog.ingest_jobs WHERE id = :id"),
                {"id": second.id},
            )
            await session.commit()


async def test_an_archive_the_sweep_cannot_write_keeps_the_upload(
    replace, storage, monkeypatch
) -> None:
    """A file upload whose original can't be archived stays, and the job says the archive failed."""
    replacement = await replace("file")
    lost = _LostAcknowledgement(replacement.job_id, ConnectionResetError("dropped"))
    with (
        _quiet_embedding(),
        patch(
            "app.processing.ingest.publication.observe_publish_commit",
            new=AsyncMock(return_value=PublishObservation.UNKNOWN),
        ),
        patch("app.processing.ingest.publication.run_publish_followups", AsyncMock()),
        lost.installed(),
    ):
        await replacement.run()

    real_put = storage.put

    async def _put(key, data):
        if key.startswith("originals/"):
            raise OSError("the object store refused the write")
        return await real_put(key, data)

    monkeypatch.setattr(storage, "put", _put)
    await run_owed_publish_followups()

    assert replacement.upload.exists(), "the upload went though nothing archived it"
    metadata = await _fresh_scalar(
        select(IngestJob.user_metadata).where(IngestJob.id == replacement.job_id)
    )
    assert metadata.get("archive_failed") is True


async def test_a_lossy_raster_whose_original_was_not_archived_keeps_its_upload(
    replace, monkeypatch
) -> None:
    """A lossy replacement the archive did not keep leaves its upload, the only faithful copy."""

    async def _not_archived(*args, **kwargs):
        return False, None, 0, None

    monkeypatch.setattr(
        "app.processing.ingest.tasks_raster_replace.archive_lossy_original",
        _not_archived,
    )
    import app.core.db as db_module

    replacement = await replace("raster")
    async with db_module.async_session() as session:
        await session.execute(
            text(
                "UPDATE catalog.ingest_jobs SET user_metadata = user_metadata "
                '|| \'{"compression": "JPEG"}\'::jsonb WHERE id = :id'
            ),
            {"id": replacement.job_id},
        )
        await session.commit()
    lost = _LostAcknowledgement(replacement.job_id, ConnectionResetError("dropped"))
    with _quiet_embedding(), lost.installed():
        await replacement.run()
    await run_owed_publish_followups()

    assert lost.fired == 1, "the publishing commit never ran"
    await _assert_settled_published(replacement)
    assert replacement.upload.exists(), "the only faithful copy of a lossy upload went"


@pytest.mark.parametrize("kind", sorted(_BUILDERS))
async def test_a_cancel_after_the_publishing_commit_keeps_the_publication(
    replace, kind: str
) -> None:
    """A cancel that lands in the post-commit steps leaves the replacement published."""
    replacement = await replace(kind)
    purging = asyncio.Event()

    async def _stall(*args, **kwargs):
        purging.set()
        await asyncio.sleep(30)

    with (
        _quiet_embedding(),
        patch("app.processing.ingest.publication.invalidate_catalog_cache", new=_stall),
    ):
        task = asyncio.create_task(replacement.run())
        await asyncio.wait_for(purging.wait(), timeout=20)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    await _assert_settled_published(replacement)


@pytest.mark.parametrize("kind", ["file", "service", "postgis"])
async def test_a_vector_replacement_purges_its_tiles_after_the_commit(
    replace, kind: str
) -> None:
    """The live table's tile purge runs once, after the job is durably complete."""
    replacement = await replace(kind)
    seen: list[tuple[str, str | None]] = []

    async def _record(table_name: str) -> None:
        status = await _fresh_scalar(
            select(IngestJob.status).where(IngestJob.id == replacement.job_id)
        )
        seen.append((table_name, status))

    with _quiet_embedding(), patch(_STEPS[kind]["tile cache"], new=_record):
        await replacement.run()

    assert seen == [(replacement.live_table, "complete")]
