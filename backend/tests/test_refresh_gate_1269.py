"""Cross-origin refresh integration and security gate (#1269).

ADR-002 Amendment A10's milestone-close acceptance, pruned to shipped scope.
Runs in the ordinary ``backend-test`` job — that job already gates every
PR, so this needs no new CI plumbing.

**Composition, not duplication.** Every checklist row already has (or lands
with its owning PR) a per-suite owner test that proves the row's own
behavior in isolation. This suite owns only what no per-suite test can see:
cross-origin sequencing and whole-system invariants.

1. Lifecycle braids — one per origin family (upload, service, postgis,
   stac), asserting ledger continuity (run rows accumulate, one-active-run
   holds at every step) rather than re-proving per-step behavior.
2. The sentinel-token sweep — one test proving a credential never reaches
   any surface it should not: dispatch args, ``ingest_jobs``,
   ``dataset_refresh_runs`` (including a forced failure's
   ``error_message``), audit rows, and captured structured logs.
3. Third-party projection sweep — one named non-owner and one anonymous
   reader, walked across every read surface the refresh capability touches
   (probe, dispatch refusal, run history, dataset read, ``/versions/``) so
   the Decision 4e / #1316 redaction contract is asserted in one place
   against every surface at once, instead of once per surface.
4. Recovery pair — the stale-run sweep (#1219) and the VRT
   abandoned-generation recovery (#1267), executed in sequence against
   datasets sharing the same database, proving the two sweeps don't
   interfere with each other's rows.

**Sequencing.** #1267 (VRT recovery) has landed and is exercised in group 4.
The stac braid in group 1 is drafted against ``origin/feat/1266-stac-refresh``
(PR #1326) ahead of that PR landing on ``main``, per the assignment's
early-prep signal — it has not been run against the real merged code and is
not part of this suite's own codex loop until it has been.

**Out of scope** (per the design comment): live HTTP to external
STAC/service endpoints (this suite never crosses the ``make_safe_client``
seam without a mocked transport); browser e2e.
"""

from __future__ import annotations

import io
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import numpy as np
import pytest
import structlog
from httpx import AsyncClient
from rasterio.crs import CRS
from rasterio.io import MemoryFile
from rasterio.transform import from_bounds
from sqlalchemy import select, text

from app.modules.audit.models import AuditLog
from app.modules.catalog.collections.models import DatasetVersion
from app.modules.catalog.datasets.api import router_refresh
from app.modules.catalog.datasets.domain.models import Dataset
from app.platform.dataset_origin import (
    build_origin_ref,
    set_dataset_origin,
    set_postgis_origin,
)
from app.platform.jobs.models import IngestJob
from app.platform.jobs.router import sweep_stale_vrt_assets
from app.platform.refresh import credentials as creds
from app.platform.refresh.models import DatasetRefreshRun
from app.platform.refresh.service import (
    ABANDONED_ERROR_CODE,
    ABANDONED_RUN_CUTOFF_SECONDS,
    DatasetBusyError,
    claim_run_for_job,
    create_pending_run,
    record_refresh_failure,
    sweep_abandoned_refresh_runs,
)
from app.processing.ingest import tasks_postgis_refresh
from app.processing.ingest.tasks_postgis_refresh import refresh_postgis
from app.processing.ingest.tasks_raster_replace import reupload_raster
from app.processing.ingest.tasks_reupload import reupload_service
from app.processing.ingest.tasks_stac_refresh import refresh_stac
from app.processing.raster.models import RasterAsset, VrtGeneration
from app.platform.storage.local import LocalStorageProvider
from tests.factories import create_dataset, get_user_id

pytestmark = pytest.mark.anyio


# ---------------------------------------------------------------------------
# Shared fixtures and helpers.
#
# Every helper below is a local, minimal duplicate of a same-named helper in
# a sibling suite (test_postgis_refresh_1265.py, test_service_refresh_1220.py,
# test_raster_replace_1221.py, test_dataset_refresh_runs.py,
# test_vrt_stale_sweep_gap002.py) — the established convention in this test
# tree is that each suite owns its own fixtures rather than sharing them
# through conftest.py, so a change to one suite's needs cannot silently
# ripple into another's.
# ---------------------------------------------------------------------------


_SQUARE = "POLYGON((0 0, 0 1, 1 1, 1 0, 0 0))"
_SEED_COLUMNS = [
    {"name": "name", "type": "text", "ordinal_position": 2, "is_nullable": True}
]


class _FakeCredentialBackend:
    """In-memory stand-in for the Redis-backed credential store.

    Mirrors ``test_service_refresh_1220.py``'s fixture of the same shape —
    the real ``SET NX EX`` / ``GETDEL`` contract is pinned there, not here.
    """

    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    async def put(self, key: str, value: str, ttl_seconds: int) -> None:
        self.store[key] = value

    async def take(self, key: str) -> str | None:
        return self.store.pop(key, None)

    async def renew(self, key: str, ttl_seconds: int) -> bool:
        return key in self.store


@pytest.fixture
def credential_backend():
    """Install a fake credential store for the duration of one test."""
    backend = _FakeCredentialBackend()
    creds.set_credential_backend(backend)
    try:
        yield backend
    finally:
        creds.set_credential_backend(None)


@pytest.fixture
def raster_storage(tmp_path, monkeypatch):
    """A real LocalStorageProvider on a tmp dir, installed on every lookup path."""
    storage = LocalStorageProvider(str(tmp_path / "objects"))
    monkeypatch.setattr(
        "app.platform.storage.get_storage", lambda: storage, raising=True
    )
    monkeypatch.setattr(
        "app.processing.ingest.tasks_common.get_storage", lambda: storage, raising=True
    )
    return storage


@asynccontextmanager
async def _dispatch_harness():
    """Patch the SSRF probe and every deferred task the refresh door might
    reach for; yield the shared task mock.

    ``task.defer_async.call_args.kwargs`` IS what becomes
    ``procrastinate_jobs.args`` — Procrastinate serializes ``defer_async``'s
    kwargs verbatim into that column, so inspecting the mock's call is
    equivalent to querying the row for a dispatch this harness never lets
    reach the real queue.
    """
    task = MagicMock()
    task.defer_async = AsyncMock(return_value=None)
    port = MagicMock()
    port.refresh_postgis_task.return_value = task
    port.reupload_service_task.return_value = task
    port.refresh_stac_task.return_value = task
    with (
        patch.object(router_refresh, "validate_url_for_ssrf", AsyncMock()),
        patch.object(router_refresh, "get_catalog_port", return_value=port),
    ):
        yield task


async def _run_for(session, dataset_id: uuid.UUID) -> DatasetRefreshRun | None:
    return (
        await session.execute(
            select(DatasetRefreshRun).where(DatasetRefreshRun.dataset_id == dataset_id)
        )
    ).scalar_one_or_none()


async def _runs_ordered(session, dataset_id: uuid.UUID) -> list[DatasetRefreshRun]:
    return list(
        (
            await session.execute(
                select(DatasetRefreshRun)
                .where(DatasetRefreshRun.dataset_id == dataset_id)
                .order_by(DatasetRefreshRun.started_at, DatasetRefreshRun.id)
            )
        ).scalars()
    )


async def _job_for(session, job_id: uuid.UUID) -> IngestJob:
    return (
        await session.execute(select(IngestJob).where(IngestJob.id == job_id))
    ).scalar_one()


# --- Service-origin helpers -------------------------------------------------

_WFS_BASE = "https://services.example.com/wfs"


async def _service_dataset(
    session,
    *,
    created_by: uuid.UUID,
    visibility: str = "public",
    layer_id: str = "topp:parcels",
):
    dataset = await create_dataset(
        session, created_by=created_by, source_format="wfs", visibility=visibility
    )
    enriched = f"{_WFS_BASE}/{layer_id}"
    dataset.source_url = enriched
    set_dataset_origin(
        dataset,
        "service",
        uri=enriched,
        service_type="wfs",
        url=_WFS_BASE,
        layer_id=layer_id,
    )
    await session.commit()
    await session.refresh(dataset)
    return dataset


async def _execute_service(task_kwargs: dict, *, expected_token: str | None) -> None:
    """Drive ``reupload_service`` to a genuine success through its real
    worker entry point (fix(#1330 review) — the prior version of this braid
    called ``record_refresh_success`` directly, so "protected refresh
    succeeds" was never actually exercised end to end).

    Only the outbound boundary is faked: the ogr2ogr subprocess
    (``run_ogr2ogr_service``) and the SSRF check the fixture's fake domain
    would fail for real. Everything downstream — column renaming, geometry
    detection, metadata extraction, the swap, and the run's own
    ``record_refresh_success`` call — runs unmocked against a genuine
    staging table, so the terminal state is produced by the code under
    test. Mirrors ``test_reupload_service.py``'s own success-path recipe,
    trimmed: that suite mocks the metadata pipeline too to pin exact
    values for its own identity-preservation assertions, which this braid
    does not need.

    ``expected_token`` closes the seam one level deeper (fix(#1330 review
    round 6)): the fake used to create the staging table regardless of
    ``token``, so this braid would still pass a world where
    ``reupload_service`` stopped redeeming ``credential_ref`` or forwarded
    ``None``. The fake now refuses to run unless the planted secret
    actually reached this call, so that drift fails loudly instead of
    silently.
    """

    async def _fake_run_ogr2ogr_service(
        gdal_source: str,
        layer_name: str,
        table_name: str,
        db_conn_str: str,
        service_type: str,
        timeout: float = 1800.0,
        token: str | None = None,
        is_non_spatial: bool = False,
        append: bool = False,
        *,
        schema: str,
        on_spawn=None,
    ) -> None:
        if token != expected_token:
            raise AssertionError(
                f"run_ogr2ogr_service received token={token!r}, expected the "
                f"planted secret {expected_token!r} — the credential never "
                "crossed the last boundary"
            )
        if on_spawn is not None:
            on_spawn()
        from app.core.db import async_session as _async_session

        async with _async_session() as fake_session:
            await fake_session.execute(
                text(f'DROP TABLE IF EXISTS "{schema}"."{table_name}"')
            )
            await fake_session.execute(
                text(
                    f'CREATE TABLE "{schema}"."{table_name}" '
                    "(gid serial PRIMARY KEY, name text)"
                )
            )
            await fake_session.commit()

    with (
        patch(
            "app.platform.security.validate_url_for_ssrf",
            new=AsyncMock(),
        ),
        patch(
            "app.processing.ingest.ogr.run_ogr2ogr_service", new_callable=AsyncMock
        ) as mock_run_ogr2ogr_service,
    ):
        mock_run_ogr2ogr_service.side_effect = _fake_run_ogr2ogr_service
        await reupload_service.func(**task_kwargs)


# --- PostGIS-origin helpers --------------------------------------------------


async def _registered_postgis_dataset(session, *, created_by: uuid.UUID) -> Dataset:
    """A dataset bound to a real table, mirroring test_postgis_refresh_1265's
    ``_registered_dataset`` — the physical table is genuinely created, so a
    subsequent DROP TABLE in the same suite exercises the real failure path.
    """
    table_name = f"gate1269_{uuid.uuid4().hex[:12]}"
    await session.execute(
        text(
            f"CREATE TABLE data.{table_name} ("
            "  gid SERIAL PRIMARY KEY,"
            "  name text,"
            "  geom geometry(Polygon, 4326),"
            "  geom_4326 geometry(Polygon, 4326)"
            ")"
        )
    )
    await session.execute(
        text(
            f"INSERT INTO data.{table_name} (name, geom, geom_4326) "
            f"VALUES ('row-0', ST_GeomFromText('{_SQUARE}', 4326), "
            f"ST_GeomFromText('{_SQUARE}', 4326))"
        )
    )
    await session.commit()

    dataset = await create_dataset(
        session,
        created_by=created_by,
        table_name=table_name,
        geometry_type="POLYGON",
        feature_count=1,
        column_info=_SEED_COLUMNS,
        # Registration stores no source_format — a null format is what makes
        # classify_origin say "postgis".
        source_format=None,
        source_filename=None,
    )
    set_postgis_origin(dataset, table_name, schema="data")
    await session.commit()
    await session.refresh(dataset)
    return dataset


async def _dispatch_postgis(
    client: AsyncClient, headers: dict, dataset_id: uuid.UUID
) -> dict:
    async with _dispatch_harness():
        resp = await client.post(f"/datasets/{dataset_id}/refresh", headers=headers)
    assert resp.status_code == 202, resp.text
    return resp.json()


async def _execute_postgis(session, payload: dict) -> None:
    job = await _job_for(session, uuid.UUID(payload["job_id"]))
    await refresh_postgis.func(
        job_id=payload["job_id"],
        dataset_id=payload["dataset_id"],
        attempt_id=str(job.attempt_id),
    )


# --- STAC-origin helpers -----------------------------------------------------
#
# DRAFTED against origin/feat/1266-stac-refresh (PR #1326), not yet merged as
# of this commit. Mirrors that PR's own test_stac_refresh_1266.py: `_ROOT`/
# `_ITEM`/`_SEARCH`/`_ASSET` naming, `_item_doc`, `_routes`, `stac_transport`,
# `cog_info` and `_stac_dataset` are all shrunk copies of that suite's
# fixtures of the same purpose. That suite owns every resolution-rule test
# (search derivation, asset identification, the withdrawn-vs-removed
# distinction); this only drives the real worker end to end to prove the
# checklist's two STAC rows compose into the same ledger the other three
# origin families do.

_STAC_ROOT = "https://stac.example.com/api"
_STAC_ITEM = f"{_STAC_ROOT}/collections/scenes/items/scene-1"
_STAC_SEARCH = f"{_STAC_ROOT}/search"
_STAC_ASSET = "https://stac.example.com/tiles/scene.tif"
_STAC_MOVED_ASSET = "https://stac.example.com/v2/tiles/scene.tif"


def _stac_item_doc(*, asset_href: str = _STAC_ASSET, asset_key: str = "data") -> dict:
    return {
        "type": "Feature",
        "id": "scene-1",
        "collection": "scenes",
        "properties": {"proj:code": "EPSG:32633"},
        "bbox": [10.0, 45.0, 11.0, 46.0],
        "links": [{"rel": "self", "href": _STAC_ITEM}],
        "assets": {
            asset_key: {
                "href": asset_href,
                "roles": ["data"],
                "type": "image/tiff",
            }
        },
    }


def _stub_stac_resolution_seams(monkeypatch) -> None:
    """The two seams the resolver reaches for directly, not through the
    door: the SSRF check (real DNS resolution against a name nothing
    answers for) and the COG read Titiler would do against a moved asset.
    """
    monkeypatch.setattr(
        "app.modules.catalog.sources.stac_resolve_asset_gate.validate_url_for_ssrf",
        AsyncMock(),
    )
    monkeypatch.setattr(
        "app.modules.catalog.sources.stac_resolve_asset_gate.fetch_cog_info",
        AsyncMock(
            return_value={
                "band_count": 1,
                "dtype": "uint16",
                "nodata": 0,
                "band_info": [{"min": 0, "max": 4095, "mean": 1200}],
            }
        ),
    )


def _install_stac_transport(
    monkeypatch, routes: dict[str, tuple[int, object | None]]
) -> None:
    """Answer each URL from a table; anything unlisted is a 404 (mirrors
    test_stac_refresh_1266's `_routes`). Reinstalled between phases of the
    same test, since each phase asks a different question of the origin.
    """

    def _handler(request: httpx.Request) -> httpx.Response:
        entry = routes.get(str(request.url))
        if entry is None:
            return httpx.Response(404)
        status_code, payload = entry
        return (
            httpx.Response(status_code)
            if payload is None
            else httpx.Response(status_code, json=payload)
        )

    def _factory(timeout=10.0, **_kwargs) -> httpx.AsyncClient:
        async def _handle(request: httpx.Request) -> httpx.Response:
            return _handler(request)

        # fix(#1330 review): no route table this stub serves ever answers a
        # 3xx, so `follow_redirects` is dead weight on a raw AsyncClient —
        # exactly the shape Rule 2's hook flags. Dropped rather than routed
        # through `make_safe_client()`, since there is no redirect for it to
        # revalidate.
        return httpx.AsyncClient(
            transport=httpx.MockTransport(_handle), timeout=timeout
        )

    monkeypatch.setattr(
        "app.modules.catalog.sources.origin_probe.make_safe_client", _factory
    )


async def _stac_dataset(session, *, created_by: uuid.UUID) -> Dataset:
    """A STAC dataset with a remote raster asset, mirroring
    test_stac_refresh_1266's `_stac_dataset` fixture.
    """
    dataset = await create_dataset(
        session,
        created_by=created_by,
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
    dataset.source_health = "healthy"
    dataset.last_refreshed_at = datetime.now(timezone.utc) - timedelta(days=30)
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
    await session.refresh(dataset)
    return dataset


async def _dispatch_stac(
    client: AsyncClient, headers: dict, dataset_id: uuid.UUID
) -> dict:
    async with _dispatch_harness():
        resp = await client.post(f"/datasets/{dataset_id}/refresh", headers=headers)
    assert resp.status_code == 202, resp.text
    return resp.json()


async def _execute_stac(session, payload: dict) -> None:
    job = await _job_for(session, uuid.UUID(payload["job_id"]))
    await refresh_stac.func(
        job_id=payload["job_id"],
        dataset_id=payload["dataset_id"],
        attempt_id=str(job.attempt_id),
    )


async def _reload_stac_dataset(dataset_id: uuid.UUID) -> Dataset:
    """A fresh session, independent of the test's. `refresh_stac.func` commits
    from a session the test does not own, so reading the dataset back through
    the test's own (already identity-mapped) session would return the
    pre-refresh cached attributes rather than proving the write landed —
    mirrors test_stac_refresh_1266's `_reload`/`_fresh_session` pair.
    """
    from app.core.db import async_session

    async with async_session() as session:
        return (
            await session.execute(select(Dataset).where(Dataset.id == dataset_id))
        ).scalar_one()


async def _reload_stac_asset(dataset_id: uuid.UUID) -> RasterAsset:
    from app.core.db import async_session

    async with async_session() as session:
        return (
            await session.execute(
                select(RasterAsset).where(RasterAsset.dataset_id == dataset_id)
            )
        ).scalar_one()


async def _stac_extent_wkt(dataset_id: uuid.UUID) -> str | None:
    from app.core.db import async_session

    async with async_session() as session:
        return await session.scalar(
            text(
                "SELECT ST_AsText(ST_Envelope(spatial_extent)) "
                "FROM catalog.records r "
                "JOIN catalog.datasets d ON d.record_id = r.id "
                "WHERE d.id = :dataset_id"
            ),
            {"dataset_id": dataset_id},
        )


# --- Raster/upload-origin helpers -------------------------------------------


def _geotiff_bytes(*, width: int = 32, height: int = 32, seed: int = 1269) -> bytes:
    """A minimal valid single-band GeoTIFF, mirroring the sibling raster suites."""
    profile = {
        "driver": "GTiff",
        "dtype": "uint8",
        "width": width,
        "height": height,
        "count": 1,
        "crs": CRS.from_epsg(4326),
        "transform": from_bounds(-180, -90, 180, 90, width, height),
    }
    rng = np.random.default_rng(seed)
    buf = io.BytesIO()
    with MemoryFile() as mem:
        with mem.open(**profile) as ds:
            ds.write(rng.integers(0, 200, (height, width), dtype="uint8"), 1)
        buf.write(mem.read())
    return buf.getvalue()


class _LiveRaster:
    def __init__(self, dataset, asset, cog_key: str) -> None:
        self.dataset = dataset
        self.asset = asset
        self.cog_key = cog_key


async def _make_live_raster(session, storage, *, created_by: uuid.UUID) -> _LiveRaster:
    """An upload-origin raster dataset with its COG actually present in storage."""
    from app.modules.catalog.datasets.domain.models import Record

    payload = _geotiff_bytes(seed=1)
    record = Record(
        title="Gate Elevation",
        summary="original",
        record_type="raster_dataset",
        visibility="public",
        record_status="published",
        created_by=created_by,
        updated_by=created_by,
        theme_category=["test"],
    )
    session.add(record)
    await session.flush()

    dataset = Dataset(
        record_id=record.id,
        table_name=f"raster_gate_{record.id.hex[:16]}",
        source_format="geotiff",
        source_filename="original.tif",
        srid=4326,
    )
    session.add(dataset)
    await session.flush()

    base_key = f"rasters/{dataset.id}/originalsha"
    cog_key = f"{base_key}/source.cog.tif"
    asset = RasterAsset(
        dataset_id=dataset.id,
        asset_uri=cog_key,
        quicklook_256_uri=f"{base_key}/quicklook_256.png",
        quicklook_512_uri=f"{base_key}/quicklook_512.png",
        sha256="0" * 64,
        size_bytes=len(payload),
        driver="GTiff",
        storage_backend="local",
        epsg=4326,
        band_count=1,
        dtype="uint8",
    )
    session.add(asset)
    await session.commit()

    await storage.put(cog_key, io.BytesIO(payload))
    await storage.put(asset.quicklook_256_uri, io.BytesIO(b"old-ql-256"))
    await storage.put(asset.quicklook_512_uri, io.BytesIO(b"old-ql-512"))
    return _LiveRaster(dataset, asset, cog_key)


async def _queue_replace_job(
    session, *, dataset_id: uuid.UUID, user_id: uuid.UUID, file_path: str
) -> IngestJob:
    job = IngestJob(
        dataset_id=dataset_id,
        source_filename=file_path.rsplit("/", 1)[-1],
        file_path=file_path,
        created_by=user_id,
        status="pending",
        user_metadata={"reupload": True, "dataset_id": str(dataset_id)},
    )
    session.add(job)
    await session.flush()
    await create_pending_run(
        session,
        dataset_id=dataset_id,
        origin_kind="upload",
        trigger="manual",
        triggered_by=user_id,
        ingest_job_id=job.id,
        feature_count_before=None,
    )
    await session.commit()
    await session.refresh(job)
    return job


# --- Recovery-pair helpers ---------------------------------------------------

_WELL_PAST_CUTOFF = ABANDONED_RUN_CUTOFF_SECONDS + 600


async def _seed_abandoned_run(
    session, *, created_by: uuid.UUID
) -> tuple[Dataset, DatasetRefreshRun]:
    """A dataset whose refresh run is genuinely abandoned: bound job already
    failed (no live task), run started well past the cutoff, no live
    Procrastinate row references it. Mirrors test_dataset_refresh_runs.py's
    ``_stale_run`` helper.
    """
    dataset = await create_dataset(
        session, created_by=created_by, name="Gate Abandoned Run DS"
    )
    job = IngestJob(
        dataset_id=dataset.id,
        status="failed",
        source_filename="parcels.gpkg",
        created_by=created_by,
        user_metadata={"reupload": True, "dataset_id": str(dataset.id)},
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)

    run = await create_pending_run(
        session,
        dataset_id=dataset.id,
        origin_kind="upload",
        trigger="manual",
        triggered_by=created_by,
        ingest_job_id=job.id,
        feature_count_before=42,
    )
    run.status = "pending"
    run.started_at = datetime.now(timezone.utc) - timedelta(seconds=_WELL_PAST_CUTOFF)
    await session.commit()
    return dataset, run


async def _seed_abandoned_vrt_generation(session, *, created_by: uuid.UUID):
    """A VRT dataset with one dead 'running' regeneration — composition
    preserved (an empty built_from matches its own empty link set), so the
    sweep's only remaining question is the heartbeat timeout. Mirrors
    test_vrt_stale_sweep_gap002.py's ``_make_vrt_with_generation`` helper.
    """
    vrt_dataset = await create_dataset(
        session, created_by=created_by, name="Gate Abandoned VRT DS"
    )
    now = datetime.now(timezone.utc)
    generation = VrtGeneration(
        vrt_dataset_id=vrt_dataset.id,
        status="running",
        started_at=now - timedelta(hours=2),
        heartbeat_at=now - timedelta(hours=2),
    )
    session.add(generation)
    await session.flush()

    asset = RasterAsset(
        dataset_id=vrt_dataset.id,
        asset_uri=f"rasters/{vrt_dataset.id}/source.vrt",
        status="regenerating",
        current_generation_id=generation.id,
        built_from={},
    )
    session.add(asset)
    await session.commit()
    return vrt_dataset, generation, asset


# ---------------------------------------------------------------------------
# 1. Lifecycle braids — one per origin family.
# ---------------------------------------------------------------------------


class TestLifecycleBraids:
    async def test_upload_family_refuses_refresh_then_replace_succeeds(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
        raster_storage,
        tmp_path,
    ) -> None:
        """upload -> refresh refused (no origin to re-fetch from) -> replace
        succeeds -> a further replace is admitted only once the first is
        terminal. This is the sequencing the checklist's "upload and raster
        replacement... old COG and tiles retained on every failure path" row
        does not itself prove — that row's own retention assertions live in
        test_raster_replace_1221.py; this braid only proves the ledger.
        """
        admin_id = await get_user_id(test_db_session, "admin")
        live = await _make_live_raster(
            test_db_session, raster_storage, created_by=admin_id
        )
        dataset_id = live.dataset.id

        async with _dispatch_harness():
            resp = await client.post(
                f"/datasets/{dataset_id}/refresh", headers=admin_auth_header
            )
        assert resp.status_code == 409, resp.text
        assert resp.json()["detail"]["code"] == "refresh_not_applicable"
        assert resp.json()["detail"]["origin_kind"] == "upload"
        assert await _run_for(test_db_session, dataset_id) is None, (
            "a refused dispatch must never touch the run ledger"
        )

        source = tmp_path / "replacement.tif"
        source.write_bytes(_geotiff_bytes(seed=42))
        job = await _queue_replace_job(
            test_db_session,
            dataset_id=dataset_id,
            user_id=admin_id,
            file_path=str(source),
        )
        await reupload_raster.func(
            job_id=str(job.id),
            dataset_id=str(dataset_id),
            file_path=str(source),
            user_id=str(admin_id),
            attempt_id=str(job.attempt_id),
        )

        runs = await _runs_ordered(test_db_session, dataset_id)
        assert [r.status for r in runs] == ["succeeded"]

        # One-active-run holds: a second reservation is admitted now that the
        # first is terminal, but a THIRD is refused while the second is live.
        second_job = await _queue_replace_job(
            test_db_session,
            dataset_id=dataset_id,
            user_id=admin_id,
            file_path=str(source),
        )
        runs = await _runs_ordered(test_db_session, dataset_id)
        assert [r.status for r in runs] == ["succeeded", "pending"]

        with pytest.raises(DatasetBusyError):
            await create_pending_run(
                test_db_session,
                dataset_id=dataset_id,
                origin_kind="upload",
                trigger="manual",
                triggered_by=admin_id,
                ingest_job_id=second_job.id,
                feature_count_before=None,
            )

    async def test_service_family_protected_refresh_then_origin_change_refuses(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
        credential_backend,
    ) -> None:
        """service import -> protected refresh succeeds -> origin changes
        (rebound to upload) -> refresh is now refused. The rebind proves
        `refresh_not_applicable`'s admission check reads the CURRENT origin,
        not a stale classification, and that a refused attempt never
        pollutes the ledger the first (real) refresh built.
        """
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _service_dataset(test_db_session, created_by=admin_id)

        secret = "tok-" + uuid.uuid4().hex
        async with _dispatch_harness() as task:
            resp = await client.post(
                f"/datasets/{dataset.id}/refresh",
                json={"token": secret},
                headers=admin_auth_header,
            )
        assert resp.status_code == 202, resp.text

        # Drive the real worker to succeed (fix(#1330 review) — "protected
        # refresh succeeds" must be produced by the code under test, not
        # composed via record_refresh_success directly). task_kwargs IS what
        # a live worker would have received off the queue.
        task_kwargs = task.defer_async.call_args.kwargs
        # feat(#1746 B2b) plan D9: what a WFS origin dispatches, and therefore
        # what the worker redeems, is the composed header line.
        await _execute_service(
            task_kwargs, expected_token=f"Authorization: Bearer {secret}"
        )

        runs = await _runs_ordered(test_db_session, dataset.id)
        assert [r.status for r in runs] == ["succeeded"]

        set_dataset_origin(
            dataset,
            "upload",
            uri=None,
            filename="replacement.gpkg",
            file_hash="deadbeef",
        )
        dataset.source_format = "gpkg"
        await test_db_session.commit()

        async with _dispatch_harness() as task:
            resp = await client.post(
                f"/datasets/{dataset.id}/refresh", headers=admin_auth_header
            )
        assert resp.status_code == 409, resp.text
        assert resp.json()["detail"]["code"] == "refresh_not_applicable"
        task.defer_async.assert_not_awaited()

        runs = await _runs_ordered(test_db_session, dataset.id)
        assert [r.status for r in runs] == ["succeeded"], (
            "the refused rebind attempt must not add a second row"
        )

    async def test_postgis_family_register_refresh_drop_fails(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
    ) -> None:
        """register -> refresh succeeds -> table dropped -> refresh fails ->
        a third attempt is still admitted (both prior runs are terminal)."""
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _registered_postgis_dataset(
            test_db_session, created_by=admin_id
        )

        payload = await _dispatch_postgis(client, admin_auth_header, dataset.id)
        await _execute_postgis(test_db_session, payload)
        runs = await _runs_ordered(test_db_session, dataset.id)
        assert [r.status for r in runs] == ["succeeded"]

        payload = await _dispatch_postgis(client, admin_auth_header, dataset.id)
        await test_db_session.execute(text(f"DROP TABLE data.{dataset.table_name}"))
        await test_db_session.commit()
        with pytest.raises(tasks_postgis_refresh.PostgisRefreshError):
            await _execute_postgis(test_db_session, payload)

        runs = await _runs_ordered(test_db_session, dataset.id)
        assert [r.status for r in runs] == ["succeeded", "failed"]

        # one-active-run holds: both prior runs are terminal, so a third
        # reservation is admitted, not refused as dataset_busy.
        third = await _dispatch_postgis(client, admin_auth_header, dataset.id)
        runs = await _runs_ordered(test_db_session, dataset.id)
        assert [r.status for r in runs] == ["succeeded", "failed", "pending"]
        assert third["run_id"] not in {str(r.id) for r in runs[:2]}

    async def test_stac_family_missing_then_moved_pointer_reresolves(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
        monkeypatch,
    ) -> None:
        """The checklist's two STAC rows, walked as one sequence: the stored
        item 404s and the re-search finds nothing (failed run, `missing`,
        every pointer retained — invariant 10, for an origin kind whose
        pointer IS its data) -> the same item resolves again, this time
        naming a moved asset (re-resolved: pointer, the moved object's own
        metadata, its extent and the tile-cache version all move together)
        -> ledger continuity and one-active-run hold at every step, same as
        the other three families. Per-outcome resolution rules (search
        derivation, asset identification, the withdrawn-vs-removed
        distinction) are test_stac_refresh_1266.py's own concern; this only
        proves the sequence composes.
        """
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _stac_dataset(test_db_session, created_by=admin_id)
        before_uri = dataset.origin_uri
        before_version = dataset.tile_cache_version

        _stub_stac_resolution_seams(monkeypatch)

        # -- 1. the stored item is gone, and the re-search finds nothing. --
        _install_stac_transport(
            monkeypatch,
            {_STAC_ITEM: (404, None), _STAC_SEARCH: (200, {"features": []})},
        )
        payload = await _dispatch_stac(client, admin_auth_header, dataset.id)
        with pytest.raises(Exception):
            await _execute_stac(test_db_session, payload)

        runs = await _runs_ordered(test_db_session, dataset.id)
        assert [r.status for r in runs] == ["failed"]
        assert runs[0].error_code == "source_missing"

        reloaded = await _reload_stac_dataset(dataset.id)
        assert reloaded.origin_uri == before_uri
        assert reloaded.origin_ref["asset_href"] == before_uri
        assert reloaded.source_health == "missing"
        assert reloaded.tile_cache_version == before_version

        # -- 2. the same item resolves again, naming a moved asset. The
        # moved href itself must also answer (206, a range-request probe),
        # or the resolver adopts the pointer but reports the asset
        # inaccessible rather than healthy.
        moved_doc = _stac_item_doc(asset_href=_STAC_MOVED_ASSET)
        moved_doc["bbox"] = [30.0, 60.0, 31.0, 61.0]
        _install_stac_transport(
            monkeypatch,
            {_STAC_ITEM: (200, moved_doc), _STAC_MOVED_ASSET: (206, None)},
        )
        payload = await _dispatch_stac(client, admin_auth_header, dataset.id)
        await _execute_stac(test_db_session, payload)

        runs = await _runs_ordered(test_db_session, dataset.id)
        assert [r.status for r in runs] == ["failed", "succeeded"]

        reloaded = await _reload_stac_dataset(dataset.id)
        assert reloaded.origin_uri == _STAC_MOVED_ASSET, "the pointer moved"
        assert reloaded.origin_ref["asset_href"] == _STAC_MOVED_ASSET
        assert reloaded.source_health == "healthy"
        assert reloaded.tile_cache_version != before_version, (
            "a moved asset must bust the tile cache"
        )

        asset = await _reload_stac_asset(dataset.id)
        assert asset.asset_uri == _STAC_MOVED_ASSET
        assert asset.epsg == 32633, "the moved object's own metadata, not the old one's"

        extent = await _stac_extent_wkt(dataset.id)
        assert extent is not None
        assert "30" in extent and "60" in extent, "the moved object's footprint"

        # -- 3. one-active-run holds: both prior runs are terminal, so a
        # third reservation is admitted, not refused as dataset_busy. --
        third = await _dispatch_stac(client, admin_auth_header, dataset.id)
        runs = await _runs_ordered(test_db_session, dataset.id)
        assert [r.status for r in runs] == ["failed", "succeeded", "pending"]
        assert third["run_id"] not in {str(r.id) for r in runs[:2]}


# ---------------------------------------------------------------------------
# 2. The sentinel-token sweep.
# ---------------------------------------------------------------------------


class TestSentinelTokenSweep:
    async def test_sentinel_token_never_leaks_anywhere(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
        credential_backend,
    ) -> None:
        """One token, planted once, swept for everywhere it must never land:
        the dispatch args (what becomes procrastinate_jobs.args), ingest_jobs,
        a forced-failure run's error_message, audit rows, and captured
        structured logs. capture_logs() is required here, not caplog — this
        backend's structlog configuration makes caplog see zero records
        (project convention, pinned by test_logging_conftest_guard.py).
        """
        secret = "sentinel-" + uuid.uuid4().hex
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _service_dataset(test_db_session, created_by=admin_id)

        with structlog.testing.capture_logs() as captured:
            # A dispatch-time queue failure: the credential is already
            # stashed by the time defer_async is reached, so this exercises
            # the orphan-guard's failure path with a real credential_ref in
            # play — the strongest version of "does a forced failure leak
            # it", since nothing here is a happy-path no-op.
            task = MagicMock()
            task.defer_async = AsyncMock(side_effect=RuntimeError("queue unavailable"))
            port = MagicMock()
            port.reupload_service_task.return_value = task
            with (
                patch.object(router_refresh, "validate_url_for_ssrf", AsyncMock()),
                patch.object(router_refresh, "get_catalog_port", return_value=port),
            ):
                resp = await client.post(
                    f"/datasets/{dataset.id}/refresh",
                    json={"token": secret},
                    headers=admin_auth_header,
                )

            assert resp.status_code == 503, resp.text

            # 1. Dispatch args — this IS procrastinate_jobs.args, verbatim.
            kwargs = task.defer_async.call_args.kwargs
            assert secret not in str(kwargs)
            assert "token" not in kwargs
            credential_ref = kwargs["credential_ref"]
            assert credential_ref

            # 2. ingest_jobs — every durable text/JSON column a regression
            # could write the credential into, not just user_metadata
            # (fix(#1330 review): error_message is where a dispatch-failure
            # message would plausibly compose it in).
            job = (
                await test_db_session.execute(
                    select(IngestJob).where(IngestJob.dataset_id == dataset.id)
                )
            ).scalar_one()
            for field in (
                "source_filename",
                "file_path",
                "source_url",
                "source_layer",
                "error_message",
                "user_metadata",
            ):
                assert secret not in str(getattr(job, field)), (
                    f"sentinel leaked into ingest_jobs.{field}"
                )

        # 3. dataset_refresh_runs — the dispatch-failure rollback finalizes
        # the run itself; assert its error_message/error_code never composed
        # the raw token in, even though the failure genuinely happened while
        # a live credential_ref existed for this run.
        run = await _run_for(test_db_session, dataset.id)
        assert run is not None
        assert run.status == "failed"
        assert run.error_code == "dispatch_failed"
        assert secret not in (run.error_message or "")

        # 4. audit rows
        audit_rows = (
            (
                await test_db_session.execute(
                    select(AuditLog).where(
                        AuditLog.resource_id == dataset.id,
                        AuditLog.action.like("refresh.%"),
                    )
                )
            )
            .scalars()
            .all()
        )
        assert audit_rows, "the dispatch/failure pair must leave an audit trail"
        for row in audit_rows:
            assert secret not in str(row.details)

        # 5. captured structured logs, across the whole request.
        for record in captured:
            assert secret not in str(record), (
                f"sentinel leaked into a log event: {record}"
            )


# ---------------------------------------------------------------------------
# 3. Third-party projection sweep.
# ---------------------------------------------------------------------------


class TestThirdPartyProjectionSweep:
    @pytest.mark.parametrize("reader", ["named", "anonymous"])
    async def test_every_read_surface_redacts_the_same_way(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        viewer_auth_header: dict,
        test_db_session,
        reader: str,
    ) -> None:
        """A named non-owner and an anonymous caller, walked across every
        surface the refresh capability touches. One dataset, one seeded
        history, so a redaction gap on any single surface fails this test
        rather than only the suite that happens to cover that one surface.
        """
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _service_dataset(
            test_db_session, created_by=admin_id, visibility="public"
        )
        dataset.origin_uri = f"{_WFS_BASE}/topp:parcels"
        dataset.last_refreshed_at = datetime(2026, 8, 1, tzinfo=timezone.utc)
        dataset.last_checked_at = datetime(2026, 8, 1, tzinfo=timezone.utc)
        dataset.source_health = "healthy"
        await test_db_session.commit()

        # Seed one failed run with every redactable field populated.
        job = IngestJob(
            dataset_id=dataset.id,
            status="failed",
            source_filename="parcels.gpkg",
            created_by=admin_id,
        )
        test_db_session.add(job)
        await test_db_session.commit()
        await test_db_session.refresh(job)
        await create_pending_run(
            test_db_session,
            dataset_id=dataset.id,
            origin_kind="service",
            trigger="manual",
            triggered_by=admin_id,
            ingest_job_id=job.id,
            feature_count_before=42,
        )
        await test_db_session.commit()
        await claim_run_for_job(test_db_session, job.id)
        await test_db_session.commit()
        await record_refresh_failure(
            test_db_session,
            ingest_job_id=job.id,
            error_code="service_refresh_failed",
            error_message="the origin timed out",
            contacted_origin=False,
        )
        await test_db_session.commit()

        # A version row too, for the /versions/ leg.
        version = DatasetVersion(
            dataset_id=dataset.id,
            version_number=1,
            source_filename="parcels.gpkg",
            source_format="wfs",
            feature_count=100,
            srid=4326,
            geometry_type="MultiPolygon",
            file_hash="sha256:deadbeef",
            uploaded_by=admin_id,
        )
        test_db_session.add(version)
        await test_db_session.commit()

        headers: dict = {} if reader == "anonymous" else viewer_auth_header

        # -- 1. probe: source-health is owner-or-admin, not visibility-gated --
        probe_resp = await client.post(
            f"/datasets/{dataset.id}/source-health/", headers=headers
        )
        if reader == "anonymous":
            assert probe_resp.status_code == 401, probe_resp.text
        else:
            assert probe_resp.status_code == 403, probe_resp.text

        # -- 2. refresh dispatch: same ownership gate --
        dispatch_resp = await client.post(
            f"/datasets/{dataset.id}/refresh", headers=headers
        )
        assert dispatch_resp.status_code in (401, 403), dispatch_resp.text
        # The refused dispatch must not have touched the ledger this test seeded.
        runs = await _runs_ordered(test_db_session, dataset.id)
        assert [r.status for r in runs] == ["failed"]

        # -- 3. run history: readable (public dataset), redacted (Decision 4e) --
        history_resp = await client.get(
            f"/datasets/{dataset.id}/refresh-runs", headers=headers
        )
        assert history_resp.status_code == 200, history_resp.text
        row = history_resp.json()["runs"][0]
        assert row["status"] == "failed"
        assert row["started_at"] is not None
        assert row["feature_count_before"] == 42
        for field in (
            "triggered_by",
            "triggered_by_username",
            "error_code",
            "error_message",
            "schema_diff",
        ):
            assert row[field] is None, f"{field} leaked to a {reader} reader"

        # -- 4. dataset read: origin pointers redacted, capability summary survives (#1316) --
        read_resp = await client.get(f"/datasets/{dataset.id}", headers=headers)
        assert read_resp.status_code == 200, read_resp.text
        body = read_resp.json()
        assert body["origin_uri"] is None, f"origin_uri leaked to a {reader} reader"
        assert body["origin_ref"] is None, f"origin_ref leaked to a {reader} reader"
        assert body["origin"] == "service"
        assert body["source_health"] == "healthy"
        assert body["last_refreshed_at"] is not None
        assert body["last_checked_at"] is not None

        # -- 5. /versions/: file_hash/uploaded_by redacted, timeline survives (#1316) --
        versions_resp = await client.get(
            f"/datasets/{dataset.id}/versions/", headers=headers
        )
        assert versions_resp.status_code == 200, versions_resp.text
        version_row = versions_resp.json()["versions"][0]
        assert version_row["file_hash"] is None, (
            f"file_hash leaked to a {reader} reader"
        )
        assert version_row["uploaded_by"] is None, (
            f"uploaded_by leaked to a {reader} reader"
        )
        assert version_row["source_filename"] == "parcels.gpkg"
        assert version_row["feature_count"] == 100


# ---------------------------------------------------------------------------
# 4. Recovery pair.
# ---------------------------------------------------------------------------


class TestRecoveryPair:
    async def test_stale_run_sweep_and_vrt_recovery_do_not_interfere(
        self, test_db_session
    ) -> None:
        """The stale-run sweep (#1219) and the VRT abandoned-generation
        recovery (#1267) run in sequence against datasets sharing the same
        database. Neither is a per-suite concern here — this proves only
        that running them back to back (as the periodic sweeper actually
        does, one after the other in fail_stale_jobs) reconciles both
        datasets correctly, with no cross-contamination between them.

        STAC re-resolution (#1266, PR #1326 in flight) is a candidate for a
        third leg of this pair once it lands — not added yet, per this
        suite's own sequencing note.
        """
        admin_id = await get_user_id(test_db_session, "admin")

        refresh_dataset, abandoned_run = await _seed_abandoned_run(
            test_db_session, created_by=admin_id
        )
        vrt_dataset, generation, vrt_asset = await _seed_abandoned_vrt_generation(
            test_db_session, created_by=admin_id
        )

        # Control rows: each dataset also carries a healthy row that belongs
        # to the OTHER sweep's domain, so "the other dataset's rows are
        # untouched" is a real assertion rather than one that would pass
        # vacuously against rows that never existed (fix(#1330 review)).
        control_asset = RasterAsset(
            dataset_id=refresh_dataset.id,
            asset_uri=f"rasters/{refresh_dataset.id}/control.tif",
            status="ready",
        )
        test_db_session.add(control_asset)

        vrt_control_job = IngestJob(
            dataset_id=vrt_dataset.id,
            status="pending",
            source_filename="vrt-control.tif",
            created_by=admin_id,
        )
        test_db_session.add(vrt_control_job)
        await test_db_session.commit()
        await test_db_session.refresh(vrt_control_job)
        control_run = await create_pending_run(
            test_db_session,
            dataset_id=vrt_dataset.id,
            origin_kind="raster",
            trigger="manual",
            triggered_by=admin_id,
            ingest_job_id=vrt_control_job.id,
            feature_count_before=None,
        )
        await test_db_session.commit()

        now = datetime.now(timezone.utc)
        vrt_cutoff = now - timedelta(hours=1)

        # fix(#1330 review): fail_stale_jobs runs the VRT sweep before the
        # run sweep on purpose — the run sweep depends on job-failure facts
        # the earlier sweeps establish. Call them in that same order so this
        # test actually exercises the sequence operators run, not its mirror.
        (
            vrt_assets_recovered,
            vrt_generations_failed,
            _storage_keys,
        ) = await sweep_stale_vrt_assets(test_db_session, vrt_cutoff)
        cancelled_count = await sweep_abandoned_refresh_runs(test_db_session, now)
        await test_db_session.commit()

        # -- the refresh-run half reconciled --
        assert cancelled_count >= 1
        await test_db_session.refresh(abandoned_run)
        assert abandoned_run.status == "cancelled"
        assert abandoned_run.error_code == ABANDONED_ERROR_CODE

        # -- the VRT half reconciled, independently --
        assert (vrt_assets_recovered, vrt_generations_failed) == (1, 1)
        await test_db_session.refresh(generation)
        await test_db_session.refresh(vrt_asset)
        assert generation.status == "failed"
        assert vrt_asset.status == "ready", (
            "the dead attempt never touched the published pointer, so the "
            "VRT keeps serving what it served before"
        )
        assert vrt_asset.current_generation_id is None

        # -- no cross-contamination: each control row belongs to the OTHER
        # sweep's domain and survives both sweeps untouched, so this proves
        # non-interference against rows that actually exist rather than
        # against an absence that was never at risk.
        await test_db_session.refresh(control_asset)
        assert control_asset.status == "ready", (
            "the VRT sweep must never touch a healthy raster asset on the "
            "refresh-run dataset"
        )

        await test_db_session.refresh(control_run)
        assert control_run.status == "pending", (
            "the run sweep must never cancel a non-stale run on the VRT dataset"
        )
        assert control_run.error_code is None

        vrt_dataset_run = await _run_for(test_db_session, vrt_dataset.id)
        assert vrt_dataset_run is not None
        assert vrt_dataset_run.id == control_run.id
