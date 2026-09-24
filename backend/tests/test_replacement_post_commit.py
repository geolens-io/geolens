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
from app.processing.ingest.tasks_postgis_refresh import refresh_postgis
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


async def _file_replacement(
    session: AsyncSession, tmp_path: Path, storage: LocalStorageProvider
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
    upload = tmp_path / "update.geojson"
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

    async def _fake_ogr2ogr(file_path, staging_table, db_conn_str, **kwargs):
        import app.core.db as db_module

        async with db_module.async_session() as staging_session:
            await _create_point_table(staging_session, staging_table, "after")
            await staging_session.commit()

    async def run() -> None:
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
                dataset_id=str(dataset.id),
                file_path=str(upload),
                user_id=str(admin_id),
                attempt_id=str(job.attempt_id),
            )

    async def assert_published() -> None:
        await _assert_live_row(table, "after")
        version = await _fresh_scalar(
            select(Dataset.current_version).where(Dataset.id == dataset.id)
        )
        assert version == 2

    return _Replacement(
        job.id, dataset.id, run, assert_published, upload=upload, live_table=table
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
    session: AsyncSession, tmp_path: Path, storage: LocalStorageProvider
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

    upload = tmp_path / "replacement.tif"
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

    async def run() -> None:
        await reupload_raster.func(
            job_id=str(job.id),
            dataset_id=str(dataset.id),
            file_path=str(upload),
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
        upload=upload,
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
        "catalog cache": "app.processing.ingest.tasks_reupload.invalidate_catalog_cache",
        "tile cache": (
            "app.processing.ingest.tasks_reupload.invalidate_tile_cache_for_table"
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
        "catalog cache": (
            "app.processing.ingest.tasks_raster_swap.invalidate_catalog_cache"
        ),
        "embedding": "app.processing.embeddings.helpers.defer_embedding",
    },
    "postgis": {
        "catalog cache": (
            "app.processing.ingest.tasks_postgis_refresh.invalidate_catalog_cache"
        ),
        "tile cache": (
            "app.processing.ingest.tasks_postgis_refresh"
            ".invalidate_tile_cache_for_table"
        ),
        "embedding": "app.processing.embeddings.helpers.defer_embedding",
    },
    "stac": {
        "catalog cache": (
            "app.processing.ingest.tasks_stac_refresh.invalidate_catalog_cache"
        ),
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

    async def _seed(kind: str) -> _Replacement:
        replacement = await _BUILDERS[kind](test_db_session, tmp_path, storage)
        created.append(replacement)
        return replacement

    yield _seed
    # Data tables outlive the test on the shared database unless dropped here.
    async with db_module.async_session() as cleanup:
        for replacement in created:
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
    """Fail the publishing commit before it lands, then the probe that follows."""

    def __init__(self, job_id: uuid.UUID) -> None:
        self.job_id = job_id
        self.commit_failed = False
        self.probe_failed = False

    @contextmanager
    def installed(self) -> Iterator[None]:
        real_commit = AsyncSession.commit
        real_execute = AsyncSession.execute
        own_status = select(IngestJob.status).where(IngestJob.id == self.job_id)

        async def _commit(session, *args, **kwargs):
            if not self.commit_failed:
                # The publishing transaction is the one that already shows
                # the job complete from inside itself.
                status = (await real_execute(session, own_status)).scalar()
                if status == "complete":
                    self.commit_failed = True
                    raise ConnectionResetError("the connection dropped before COMMIT")
            return await real_commit(session, *args, **kwargs)

        async def _execute(session, statement, *args, **kwargs):
            reads_attempt = "ingest_jobs.attempt_id" in str(statement)
            if self.commit_failed and not self.probe_failed and reads_attempt:
                self.probe_failed = True
                raise ConnectionResetError("the probe could not reach the database")
            return await real_execute(session, statement, *args, **kwargs)

        AsyncSession.commit = _commit
        AsyncSession.execute = _execute
        try:
            yield
        finally:
            AsyncSession.commit = real_commit
            AsyncSession.execute = real_execute


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
async def test_an_indeterminate_publish_keeps_every_raster_object(
    replace, storage, purge: str
) -> None:
    """A commit that may not have landed deletes neither the old raster nor the new one."""
    replacement = await replace("raster")
    indeterminate = _IndeterminatePublish(replacement.job_id)
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

    assert indeterminate.commit_failed and indeterminate.probe_failed
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


async def test_an_indeterminate_publish_skips_the_file_archive(replace) -> None:
    """A commit that may not have landed neither archives the upload nor deletes it."""
    replacement = await replace("file")
    indeterminate = _IndeterminatePublish(replacement.job_id)
    archive = AsyncMock()
    with (
        _quiet_embedding(),
        patch(_STEPS["file"]["archive"], new=archive),
        indeterminate.installed(),
    ):
        await replacement.run()

    assert indeterminate.commit_failed and indeterminate.probe_failed
    archive.assert_not_awaited()
    await _assert_live_row(replacement.live_table, "before")
    assert replacement.upload.exists()


@pytest.mark.parametrize("failure", sorted(_FAILURES))
@pytest.mark.parametrize("kind", sorted(_BUILDERS))
async def test_a_lost_acknowledgement_stands_down_as_published(
    replace, kind: str, failure: str
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
    if replacement.upload is not None:
        assert replacement.upload.exists(), (
            "a publish observed only by the probe must not delete the upload"
        )


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
