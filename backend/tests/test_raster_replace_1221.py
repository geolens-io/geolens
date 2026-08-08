"""Raster replace / refresh (#1221) and the raster source-object lifecycle (#1210).

Five properties this suite exists to hold:

1. **The door opens for raster and only for raster.** The eligibility gate used
   to refuse `raster_dataset` outright; now it constrains raster datasets to
   raster payloads, and both doors — direct multipart and presigned — reach the
   same function so a non-raster payload gets the same 400 with the same text
   whichever one the client used. That parity is the acceptance criterion; two
   doors with two error taxonomies is what #1202/#1207 had to retrofit twice.

2. **Replace preserves the dataset.** The whole reason the issue exists: today's
   only "refresh" is delete-plus-reimport, which discards the dataset id and
   everything keyed to it. So the id, the record metadata, the grants and the
   map layers are asserted to survive a replace.

3. **Last-known-good is sacred (invariant 10).** A failed conversion must leave
   the previous COG both pointed at AND present, with `last_refreshed_at`
   untouched, so the dataset's map layers keep rendering exactly what they
   rendered before. This is asserted by breaking the conversion after the
   dataset is live, not by inspecting the code path.

4. **The swap is complete.** `asset_uri`/`sha256`/`size_bytes` move together
   with the tile-cache bump, a history row is written, and the superseded COG
   is reaped only after that transaction commits.

5. **ADR-002 Decision 7 in both branches.** The pre-conversion upload is deleted
   after a successful conversion and retained after a failed one, on both the
   first-ingest path (#1210) and the replace path.

Shared-DB hygiene: every test that commits rows removes them in a finally
block, because this suite runs against the shared dev Postgres.
"""

from __future__ import annotations

import io
import uuid
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from fastapi import HTTPException
from rasterio.crs import CRS
from rasterio.io import MemoryFile
from rasterio.transform import from_bounds
from sqlalchemy import delete, select, text

from app.modules.auth.models import Role, User
from app.modules.catalog.datasets.api.router_reupload import (
    _assert_compatible_record_type,
)
from app.modules.catalog.datasets.domain.models import (
    Dataset,
    DatasetGrant,
    Record,
)
from app.modules.catalog.maps.models import Map, MapLayer
from app.platform.jobs.models import IngestJob
from app.platform.refresh.models import DatasetRefreshRun
from app.platform.refresh.service import create_pending_run
from app.platform.storage.local import LocalStorageProvider
from app.processing.ingest.tasks_raster_replace import reupload_raster
from app.processing.raster.cog import sha256_file
from app.processing.raster.models import RasterAsset

pytestmark = pytest.mark.anyio


# ---------------------------------------------------------------------------
# Fixtures & helpers
# ---------------------------------------------------------------------------


def _geotiff_bytes(
    *,
    width: int = 32,
    height: int = 32,
    seed: int = 1221,
    compress: str | None = None,
) -> bytes:
    """A minimal valid single-band GeoTIFF, mirroring the sibling raster suites.

    ``compress`` defaults to None (uncompressed) so a test asking for a
    particular COG compression can tell the source's value apart from the
    converted asset's.
    """
    profile = {
        "driver": "GTiff",
        "dtype": "uint8",
        "width": width,
        "height": height,
        "count": 1,
        "crs": CRS.from_epsg(4326),
        "transform": from_bounds(-180, -90, 180, 90, width, height),
    }
    if compress is not None:
        profile["compress"] = compress
    rng = np.random.default_rng(seed)
    buf = io.BytesIO()
    with MemoryFile() as mem:
        with mem.open(**profile) as ds:
            ds.write(rng.integers(0, 200, (height, width), dtype="uint8"), 1)
        buf.write(mem.read())
    return buf.getvalue()


def _ds(record_type: str):
    """A minimal Dataset stand-in for the pure gate tests."""
    return SimpleNamespace(record=SimpleNamespace(record_type=record_type))


@pytest.fixture
def raster_storage(tmp_path, monkeypatch):
    """A real LocalStorageProvider on a tmp dir, installed on every lookup path.

    Both the task and the reapers resolve ``get_storage`` from
    ``app.platform.storage`` at call time, so one patch covers all of them.
    """
    storage = LocalStorageProvider(str(tmp_path / "objects"))
    monkeypatch.setattr(
        "app.platform.storage.get_storage", lambda: storage, raising=True
    )
    return storage


class _LiveRaster:
    """A committed raster dataset with its COG actually present in storage."""

    def __init__(self, dataset: Dataset, asset: RasterAsset, cog_key: str) -> None:
        self.dataset = dataset
        self.asset = asset
        self.cog_key = cog_key


async def _make_live_raster(session, storage, *, created_by: uuid.UUID) -> _LiveRaster:
    """Insert a published raster dataset and write its COG to storage.

    Deliberately built row-by-row rather than by running ``ingest_raster``: the
    tests below need a KNOWN previous asset (its key, its bytes, its hash) so
    that "the old one is still there" is an assertion about specific bytes
    rather than about whatever the ingest happened to produce.
    """
    payload = _geotiff_bytes(seed=1)
    record = Record(
        title="Elevation",
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
        table_name=f"raster_{record.id.hex[:16]}",
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
    """Everything the commit door writes, so the worker sees a real reservation.

    The run row matters: ``record_refresh_success`` / ``record_refresh_failure``
    are no-ops without one, so a suite that skipped it would assert nothing
    about history while looking like it did.
    """
    job = IngestJob(
        dataset_id=dataset_id,
        source_filename=Path(file_path).name,
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


async def _purge(session, *, dataset_id: uuid.UUID, record_id: uuid.UUID) -> None:
    """Remove everything these tests committed to the shared database."""
    await session.execute(
        delete(DatasetRefreshRun).where(DatasetRefreshRun.dataset_id == dataset_id)
    )
    await session.execute(delete(IngestJob).where(IngestJob.dataset_id == dataset_id))
    await session.execute(
        text("DELETE FROM catalog.audit_logs WHERE resource_id = :rid"),
        {"rid": dataset_id},
    )
    await session.execute(delete(Dataset).where(Dataset.id == dataset_id))
    await session.execute(delete(Record).where(Record.id == record_id))
    await session.commit()


# ---------------------------------------------------------------------------
# 1. The eligibility gate, and door parity
# ---------------------------------------------------------------------------


class TestEligibilityGate:
    def test_raster_dataset_accepts_a_raster_payload(self) -> None:
        """The refusal #1221 removed. Both spellings, both cases."""
        _assert_compatible_record_type(_ds("raster_dataset"), "dem.tif")
        _assert_compatible_record_type(_ds("raster_dataset"), "dem.TIFF")

    def test_raster_dataset_still_refuses_a_service_refresh(self) -> None:
        """Nothing fetches a GeoTIFF from a feature service."""
        with pytest.raises(HTTPException) as exc:
            _assert_compatible_record_type(
                _ds("raster_dataset"), None, service_type="WFS 2.0.0"
            )
        assert exc.value.status_code == 400
        assert "remote service" in exc.value.detail.lower()

    def test_vrt_dataset_is_still_refused(self) -> None:
        """A VRT is defined by its membership, so relaxing raster must not
        relax the sibling branch that shares the same handler."""
        with pytest.raises(HTTPException) as exc:
            _assert_compatible_record_type(_ds("vrt_dataset"), "member.tif")
        assert exc.value.status_code == 400

    @pytest.mark.parametrize(
        "filename", ["places.geojson", "roads.gpkg", "table.csv", "sheet.xlsx"]
    )
    def test_non_raster_payloads_share_one_error_class(self, filename: str) -> None:
        """Both doors call this one function — the direct door with
        ``file.filename`` and the presigned door with ``request.filename`` —
        so proving the rejection here proves it for both, which is exactly the
        property the issue asks for ("both doors reject a non-raster payload
        with the same error class")."""
        with pytest.raises(HTTPException) as exc:
            _assert_compatible_record_type(_ds("raster_dataset"), filename)
        assert exc.value.status_code == 400
        assert "cross-record-type" in exc.value.detail.lower()


class TestDoorParity:
    """The HTTP halves of the parity claim, one request per door."""

    async def test_direct_and_presigned_doors_agree_on_a_non_raster_payload(
        self, client, admin_auth_header, test_db_session, raster_storage, monkeypatch
    ) -> None:
        from app.core.config import settings

        admin_id = (
            await test_db_session.execute(
                select(User.id).where(User.username == "admin")
            )
        ).scalar_one()
        live = await _make_live_raster(
            test_db_session, raster_storage, created_by=admin_id
        )
        try:
            direct = await client.post(
                f"/datasets/{live.dataset.id}/reupload",
                files={
                    "file": (
                        "places.geojson",
                        b'{"type":"FeatureCollection","features":[]}',
                        "application/json",
                    )
                },
                headers=admin_auth_header,
            )

            monkeypatch.setattr(settings, "storage_provider", "s3")
            monkeypatch.setattr(
                "app.modules.catalog.datasets.api.router_reupload.get_storage",
                lambda: raster_storage,
                raising=False,
            )
            presigned = await client.post(
                f"/datasets/{live.dataset.id}/reupload/presigned",
                json={
                    "filename": "places.geojson",
                    "file_size": 42,
                    "content_type": "application/json",
                },
                headers=admin_auth_header,
            )

            assert direct.status_code == 400, direct.text
            assert presigned.status_code == 400, presigned.text
            assert direct.json()["detail"] == presigned.json()["detail"]
            # Both must refuse for the RIGHT reason. Before #1221 both doors
            # also agreed — on "raster reupload is not supported" — so asserting
            # only that they match would have passed against the closed door
            # and proved nothing about the open one.
            assert "cross-record-type" in direct.json()["detail"].lower()
        finally:
            await _purge(
                test_db_session,
                dataset_id=live.dataset.id,
                record_id=live.dataset.record_id,
            )

    async def test_schema_preview_refuses_raster_instead_of_failing_in_ogrinfo(
        self, client, admin_auth_header, test_db_session, raster_storage, tmp_path
    ) -> None:
        """A raster has no attribute schema. Without the guard the endpoint
        runs ogrinfo on a GeoTIFF and reports a broken upload."""
        admin_id = (
            await test_db_session.execute(
                select(User.id).where(User.username == "admin")
            )
        ).scalar_one()
        live = await _make_live_raster(
            test_db_session, raster_storage, created_by=admin_id
        )
        source = tmp_path / "replacement.tif"
        source.write_bytes(_geotiff_bytes(seed=2))
        job = await _queue_replace_job(
            test_db_session,
            dataset_id=live.dataset.id,
            user_id=admin_id,
            file_path=str(source),
        )
        try:
            resp = await client.post(
                f"/datasets/{live.dataset.id}/reupload/{job.id}/preview",
                headers=admin_auth_header,
            )
            assert resp.status_code == 400, resp.text
            assert "no schema to preview" in resp.json()["detail"].lower()
        finally:
            await _purge(
                test_db_session,
                dataset_id=live.dataset.id,
                record_id=live.dataset.record_id,
            )


# ---------------------------------------------------------------------------
# 2-4. The swap itself
# ---------------------------------------------------------------------------


class TestSuccessfulReplace:
    async def test_replace_swaps_the_asset_and_preserves_the_dataset(
        self, test_db_session, raster_storage, tmp_path
    ) -> None:
        """The issue's acceptance criteria, in one pass over a real replace.

        Preservation is asserted against rows that a delete-and-reimport
        implementation would destroy: the dataset id itself, the record
        metadata, a grant, and a map layer.
        """
        admin_id = (
            await test_db_session.execute(
                select(User.id).where(User.username == "admin")
            )
        ).scalar_one()
        role_id = (await test_db_session.execute(select(Role.id).limit(1))).scalar_one()
        live = await _make_live_raster(
            test_db_session, raster_storage, created_by=admin_id
        )
        dataset_id = live.dataset.id
        record_id = live.dataset.record_id
        old_cog_key = live.cog_key
        old_tile_version = live.dataset.tile_cache_version
        old_version = live.dataset.current_version

        test_db_session.add(DatasetGrant(dataset_id=dataset_id, role_id=role_id))
        map_row = Map(
            name="Replace test map", created_by=admin_id, visibility="private"
        )
        test_db_session.add(map_row)
        await test_db_session.flush()
        layer = MapLayer(
            map_id=map_row.id, dataset_id=dataset_id, layer_type="raster_geolens"
        )
        test_db_session.add(layer)
        await test_db_session.commit()
        layer_id = layer.id
        map_id = map_row.id

        source = tmp_path / "replacement.tif"
        source.write_bytes(_geotiff_bytes(seed=99))
        source_hash = sha256_file(str(source))
        job = await _queue_replace_job(
            test_db_session,
            dataset_id=dataset_id,
            user_id=admin_id,
            file_path=str(source),
        )
        job_id = job.id

        try:
            await reupload_raster.func(
                job_id=str(job_id),
                dataset_id=str(dataset_id),
                file_path=str(source),
                user_id=str(admin_id),
                attempt_id=str(job.attempt_id),
            )

            test_db_session.expire_all()
            dataset = (
                await test_db_session.execute(
                    select(Dataset).where(Dataset.id == dataset_id)
                )
            ).scalar_one()
            asset = (
                await test_db_session.execute(
                    select(RasterAsset).where(RasterAsset.dataset_id == dataset_id)
                )
            ).scalar_one()

            # -- the swap ------------------------------------------------
            assert asset.asset_uri != old_cog_key, "asset_uri did not move"
            assert asset.sha256 not in (None, "0" * 64)
            assert asset.size_bytes == await raster_storage.size(asset.asset_uri)
            assert asset.source_sha256 == source_hash
            assert await raster_storage.exists(asset.asset_uri)
            assert not await raster_storage.exists(old_cog_key), (
                "the superseded COG must be reaped once the swap has committed"
            )

            # -- cache invalidation and freshness ------------------------
            assert dataset.tile_cache_version == old_tile_version + 1
            assert dataset.current_version == old_version + 1
            assert dataset.last_refreshed_at is not None
            assert dataset.source_filename == "replacement.tif"
            assert (dataset.origin_ref or {}).get("file_hash") == source_hash

            # -- history -------------------------------------------------
            run = (
                await test_db_session.execute(
                    select(DatasetRefreshRun).where(
                        DatasetRefreshRun.ingest_job_id == job_id
                    )
                )
            ).scalar_one()
            assert run.status == "succeeded"
            assert run.dataset_version_id is not None

            # -- preservation --------------------------------------------
            record = (
                await test_db_session.execute(
                    select(Record).where(Record.id == record_id)
                )
            ).scalar_one()
            assert record.title == "Elevation"
            assert (
                await test_db_session.execute(
                    select(DatasetGrant).where(DatasetGrant.dataset_id == dataset_id)
                )
            ).scalar_one() is not None
            surviving_layer = (
                await test_db_session.execute(
                    select(MapLayer).where(MapLayer.id == layer_id)
                )
            ).scalar_one()
            assert surviving_layer.dataset_id == dataset_id
        finally:
            await test_db_session.execute(
                delete(MapLayer).where(MapLayer.map_id == map_id)
            )
            await test_db_session.execute(delete(Map).where(Map.id == map_id))
            await test_db_session.commit()
            await _purge(test_db_session, dataset_id=dataset_id, record_id=record_id)


class TestFailedReplaceKeepsServing:
    async def test_failed_conversion_leaves_the_old_asset_serving(
        self, test_db_session, raster_storage, tmp_path, monkeypatch
    ) -> None:
        """Invariant 10. The conversion is broken AFTER the dataset is live, so
        this exercises the real failure ordering rather than a mocked one."""
        admin_id = (
            await test_db_session.execute(
                select(User.id).where(User.username == "admin")
            )
        ).scalar_one()
        live = await _make_live_raster(
            test_db_session, raster_storage, created_by=admin_id
        )
        dataset_id = live.dataset.id
        record_id = live.dataset.record_id
        old_cog_key = live.cog_key
        old_bytes = await raster_storage.get(old_cog_key)
        old_tile_version = live.dataset.tile_cache_version
        old_refreshed = live.dataset.last_refreshed_at

        source = tmp_path / "replacement.tif"
        source.write_bytes(_geotiff_bytes(seed=7))
        job = await _queue_replace_job(
            test_db_session,
            dataset_id=dataset_id,
            user_id=admin_id,
            file_path=str(source),
        )
        job_id = job.id

        def _explode(*args, **kwargs):
            raise RuntimeError("gdal_translate died")

        monkeypatch.setattr(
            "app.processing.ingest.tasks_raster_replace.check_and_prepare_cog",
            _explode,
            raising=True,
        )

        try:
            with pytest.raises(RuntimeError, match="gdal_translate died"):
                await reupload_raster.func(
                    job_id=str(job_id),
                    dataset_id=str(dataset_id),
                    file_path=str(source),
                    user_id=str(admin_id),
                    attempt_id=str(job.attempt_id),
                )

            test_db_session.expire_all()
            dataset = (
                await test_db_session.execute(
                    select(Dataset).where(Dataset.id == dataset_id)
                )
            ).scalar_one()
            asset = (
                await test_db_session.execute(
                    select(RasterAsset).where(RasterAsset.dataset_id == dataset_id)
                )
            ).scalar_one()

            assert asset.asset_uri == old_cog_key, "the pointer must not have moved"
            assert asset.sha256 == "0" * 64
            assert await raster_storage.exists(old_cog_key), (
                "the previous COG must still be present — it is what tiles serve"
            )
            assert await raster_storage.get(old_cog_key) == old_bytes
            assert dataset.tile_cache_version == old_tile_version
            assert dataset.last_refreshed_at == old_refreshed

            run = (
                await test_db_session.execute(
                    select(DatasetRefreshRun).where(
                        DatasetRefreshRun.ingest_job_id == job_id
                    )
                )
            ).scalar_one()
            assert run.status == "failed"
            assert run.error_code == "raster_refresh_failed"

            failed_job = (
                await test_db_session.execute(
                    select(IngestJob).where(IngestJob.id == job_id)
                )
            ).scalar_one()
            assert failed_job.status == "failed"
        finally:
            await _purge(test_db_session, dataset_id=dataset_id, record_id=record_id)

    async def test_failure_after_the_puts_keeps_the_old_asset_and_reaps_the_new(
        self, test_db_session, raster_storage, tmp_path, monkeypatch
    ) -> None:
        """The window the sibling test above cannot reach.

        A conversion that dies never writes anything, so its cleanup has
        nothing to filter. The dangerous window is the one AFTER the new
        objects are in storage and BEFORE the transaction that points at them
        commits: there the cleanup runs with the live asset's keys in scope,
        and reaping without filtering would delete the raster the dataset is
        still serving. Failing inside the phase-2 transaction is what puts the
        task in that window.
        """
        admin_id = (
            await test_db_session.execute(
                select(User.id).where(User.username == "admin")
            )
        ).scalar_one()
        live = await _make_live_raster(
            test_db_session, raster_storage, created_by=admin_id
        )
        dataset_id = live.dataset.id
        record_id = live.dataset.record_id
        old_bytes = await raster_storage.get(live.cog_key)

        source = tmp_path / "replacement.tif"
        source.write_bytes(_geotiff_bytes(seed=11))
        job = await _queue_replace_job(
            test_db_session,
            dataset_id=dataset_id,
            user_id=admin_id,
            file_path=str(source),
        )
        job_id = job.id

        async def _die(*args, **kwargs):
            raise RuntimeError("the swap transaction died after the puts")

        monkeypatch.setattr(
            "app.processing.ingest.tasks_raster_replace.record_refresh_success",
            _die,
            raising=True,
        )

        try:
            with pytest.raises(RuntimeError, match="died after the puts"):
                await reupload_raster.func(
                    job_id=str(job_id),
                    dataset_id=str(dataset_id),
                    file_path=str(source),
                    user_id=str(admin_id),
                    attempt_id=str(job.attempt_id),
                )

            test_db_session.expire_all()
            asset = (
                await test_db_session.execute(
                    select(RasterAsset).where(RasterAsset.dataset_id == dataset_id)
                )
            ).scalar_one()

            assert asset.asset_uri == live.cog_key, "the pointer must not have moved"
            assert await raster_storage.get(live.cog_key) == old_bytes, (
                "invariant 10: the previous COG must survive a failure that "
                "happened after the replacement bytes were already written"
            )
            # And the orphans it did write are gone — the whole point of
            # tracking the written keys separately.
            written = [
                key
                for key in await raster_storage.list(f"rasters/{dataset_id}/")
                if key != live.cog_key
                and key != asset.quicklook_256_uri
                and key != asset.quicklook_512_uri
            ]
            assert written == [], f"orphaned objects left behind: {written}"
        finally:
            await _purge(test_db_session, dataset_id=dataset_id, record_id=record_id)

    async def test_unreadable_cog_is_refused_before_the_pointer_moves(
        self, test_db_session, raster_storage, tmp_path, monkeypatch
    ) -> None:
        """A conversion that "succeeds" into an unreadable file must not
        publish. This is the case exit-code checking alone cannot catch, and
        it is why the readability verification is an explicit step."""
        admin_id = (
            await test_db_session.execute(
                select(User.id).where(User.username == "admin")
            )
        ).scalar_one()
        live = await _make_live_raster(
            test_db_session, raster_storage, created_by=admin_id
        )
        dataset_id = live.dataset.id
        record_id = live.dataset.record_id

        source = tmp_path / "replacement.tif"
        source.write_bytes(_geotiff_bytes(seed=8))
        job = await _queue_replace_job(
            test_db_session,
            dataset_id=dataset_id,
            user_id=admin_id,
            file_path=str(source),
        )
        job_id = job.id

        def _write_garbage(file_path, output_dir, **kwargs):
            out = Path(output_dir) / "source.cog.tif"
            out.write_bytes(b"not a tiff at all")
            return str(out), "converted"

        monkeypatch.setattr(
            "app.processing.ingest.tasks_raster_replace.check_and_prepare_cog",
            _write_garbage,
            raising=True,
        )

        try:
            with pytest.raises(Exception, match="could not be read back"):
                await reupload_raster.func(
                    job_id=str(job_id),
                    dataset_id=str(dataset_id),
                    file_path=str(source),
                    user_id=str(admin_id),
                    attempt_id=str(job.attempt_id),
                )

            test_db_session.expire_all()
            asset = (
                await test_db_session.execute(
                    select(RasterAsset).where(RasterAsset.dataset_id == dataset_id)
                )
            ).scalar_one()
            assert asset.asset_uri == live.cog_key
            assert await raster_storage.exists(live.cog_key)
        finally:
            await _purge(test_db_session, dataset_id=dataset_id, record_id=record_id)


# ---------------------------------------------------------------------------
# 5. ADR-002 Decision 7 — the pre-conversion source object
# ---------------------------------------------------------------------------


class TestSourceObjectLifecycle:
    """#1210 / Decision 7, asserted through the shared reaper both raster tails
    call. The reaper's contract is the whole decision: delete the staged source
    on success, retain it on failure for the operator to diagnose with."""

    async def test_successful_conversion_deletes_the_staged_source(
        self, raster_storage
    ) -> None:
        from app.processing.ingest.tasks_common import reap_downloaded_staging_source

        key = "staging/job-1221-a/dem.tif"
        await raster_storage.put(key, io.BytesIO(_geotiff_bytes()))

        await reap_downloaded_staging_source(
            "job-1221-a",
            original_file_path=key,
            final_status="complete",
            failed_source_replayable=True,
        )

        assert not await raster_storage.exists(key), (
            "Decision 7: the pre-conversion upload is deleted once the COG exists"
        )

    async def test_failed_conversion_retains_the_staged_source(
        self, raster_storage
    ) -> None:
        from app.processing.ingest.tasks_common import reap_downloaded_staging_source

        key = "staging/job-1221-b/dem.tif"
        await raster_storage.put(key, io.BytesIO(_geotiff_bytes()))

        await reap_downloaded_staging_source(
            "job-1221-b",
            original_file_path=key,
            final_status="failed",
            failed_source_replayable=True,
        )

        assert await raster_storage.exists(key), (
            "Decision 7's exception: a failed conversion leaves the operator "
            "their only diagnostic copy, bounded by the retention purge"
        )

    def test_both_raster_tails_retain_on_failure(self) -> None:
        """The wiring, not the reaper. ``failed_source_replayable`` has no
        default precisely so each surface has to state which it is, and a tail
        that passed False would silently delete the diagnostic copy Decision 7
        promises. Read off the source because the alternative — driving a whole
        failed ingest per tail — proves the same one bit far more slowly.
        """
        import ast
        import inspect

        from app.processing.ingest import tasks_raster, tasks_raster_replace

        for module in (tasks_raster, tasks_raster_replace):
            tree = ast.parse(inspect.getsource(module))
            calls = [
                node
                for node in ast.walk(tree)
                if isinstance(node, ast.Call)
                and getattr(node.func, "id", None) == "reap_downloaded_staging_source"
            ]
            assert calls, f"{module.__name__} never reaps its staged source (#1210)"
            for call in calls:
                flag = next(
                    kw.value
                    for kw in call.keywords
                    if kw.arg == "failed_source_replayable"
                )
                assert flag.value is True, (
                    f"{module.__name__} deletes its source on failure; ADR-002 "
                    "Decision 7 requires retaining it"
                )


class TestIdempotentReplace:
    async def test_replacing_with_the_identical_file_keeps_the_asset_readable(
        self, test_db_session, raster_storage, tmp_path
    ) -> None:
        """Replace twice with the same bytes. The second conversion hashes to
        the key the first one published, so the new object IS the live object —
        and a reap that only asked "what was the previous pointer" would delete
        the raster the dataset is serving. The filter on both cleanup paths is
        what makes this a no-op instead."""
        admin_id = (
            await test_db_session.execute(
                select(User.id).where(User.username == "admin")
            )
        ).scalar_one()
        live = await _make_live_raster(
            test_db_session, raster_storage, created_by=admin_id
        )
        dataset_id = live.dataset.id
        record_id = live.dataset.record_id

        payload = _geotiff_bytes(seed=1234)

        try:
            keys = []
            for attempt in range(2):
                # A fresh copy per attempt with identical bytes: a successful
                # replace consumes its local staging file, exactly as the
                # vector reupload tail does.
                source = tmp_path / f"same-{attempt}.tif"
                source.write_bytes(payload)
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
                test_db_session.expire_all()
                asset = (
                    await test_db_session.execute(
                        select(RasterAsset).where(RasterAsset.dataset_id == dataset_id)
                    )
                ).scalar_one()
                keys.append(asset.asset_uri)

            assert keys[0] == keys[1], (
                "identical bytes must hash to one key — otherwise this test is "
                "no longer exercising the collision it exists for"
            )
            assert await raster_storage.exists(keys[1]), (
                "the live COG was reaped by its own replacement"
            )
        finally:
            await _purge(test_db_session, dataset_id=dataset_id, record_id=record_id)


# ---------------------------------------------------------------------------
# 6. The parent VRT's view of a replaced member
# ---------------------------------------------------------------------------


class TestVrtMemberStaleness:
    """A replaced member leaves the parent's stored VRT naming a COG that was
    reaped. The member itself probes healthy — `storage.exists` is asked about
    its NEW pointer — so without a distinct state the parent looks fine while
    its mosaic is broken. Surfacing only; the fix is a regenerate."""

    async def test_member_replaced_after_the_last_build_reads_stale(
        self, client, admin_auth_header, test_db_session, raster_storage
    ) -> None:
        from datetime import datetime, timedelta, timezone

        from app.processing.raster.models import VrtSourceLink

        admin_id = (
            await test_db_session.execute(
                select(User.id).where(User.username == "admin")
            )
        ).scalar_one()
        built_at = datetime.now(timezone.utc) - timedelta(hours=1)

        member = await _make_live_raster(
            test_db_session, raster_storage, created_by=admin_id
        )
        parent = await _make_live_raster(
            test_db_session, raster_storage, created_by=admin_id
        )
        parent_record = (
            await test_db_session.execute(
                select(Record).where(Record.id == parent.dataset.record_id)
            )
        ).scalar_one()
        parent_record.record_type = "vrt_dataset"
        parent_asset = (
            await test_db_session.execute(
                select(RasterAsset).where(RasterAsset.dataset_id == parent.dataset.id)
            )
        ).scalar_one()
        parent_asset.last_regenerated_at = built_at
        test_db_session.add(
            VrtSourceLink(
                vrt_dataset_id=parent.dataset.id,
                source_dataset_id=member.dataset.id,
                position=0,
            )
        )
        await test_db_session.commit()

        parent_id = parent.dataset.id
        parent_record_id = parent.dataset.record_id
        member_id = member.dataset.id
        member_record_id = member.dataset.record_id

        try:
            # The member predates the build: nothing to report.
            await test_db_session.execute(
                text(
                    "UPDATE catalog.raster_assets SET ingested_at = :ts "
                    "WHERE dataset_id = :id"
                ),
                {"ts": built_at - timedelta(minutes=5), "id": member_id},
            )
            await test_db_session.commit()

            resp = await client.get(
                f"/datasets/{parent_id}/vrt/status/", headers=admin_auth_header
            )
            assert resp.status_code == 200, resp.text
            assert [s["status"] for s in resp.json()["source_health"]] == ["healthy"]

            # Now the member's raster is replaced — this is exactly what
            # reupload_raster stamps when it swaps the pointer.
            await test_db_session.execute(
                text(
                    "UPDATE catalog.raster_assets SET ingested_at = :ts "
                    "WHERE dataset_id = :id"
                ),
                {"ts": built_at + timedelta(minutes=5), "id": member_id},
            )
            await test_db_session.commit()

            resp = await client.get(
                f"/datasets/{parent_id}/vrt/status/", headers=admin_auth_header
            )
            assert resp.status_code == 200, resp.text
            assert [s["status"] for s in resp.json()["source_health"]] == ["stale"]
        finally:
            await test_db_session.execute(
                delete(VrtSourceLink).where(VrtSourceLink.vrt_dataset_id == parent_id)
            )
            await test_db_session.commit()
            await _purge(
                test_db_session, dataset_id=parent_id, record_id=parent_record_id
            )
            await _purge(
                test_db_session, dataset_id=member_id, record_id=member_record_id
            )


# ---------------------------------------------------------------------------
# 7. Round-1 review findings (#1290)
# ---------------------------------------------------------------------------


class TestLossyConversionRetainsSource:
    """FINDING 1. Decision 7 licenses deleting the upload because "conversion is
    lossless" — a claim about the profile that ran, not about conversion. The
    import UI offers JPEG, WEBP and LERC alongside the lossless three, and under
    those the COG has discarded detail the upload carried, which makes the
    upload the only lossless original that ever existed."""

    @pytest.mark.parametrize(
        "compression", ["DEFLATE", "deflate", "LZW", "ZSTD", "NONE"]
    )
    def test_lossless_profiles_supersede_the_upload(self, compression: str) -> None:
        from app.processing.raster.cog import cog_preserves_source

        assert cog_preserves_source("converted", compression) is True

    @pytest.mark.parametrize("compression", ["JPEG", "WEBP", "LERC", "jpeg"])
    def test_lossy_profiles_do_not(self, compression: str) -> None:
        from app.processing.raster.cog import cog_preserves_source

        assert cog_preserves_source("converted", compression) is False

    def test_unrecognised_profile_is_treated_as_lossy(self) -> None:
        """The allowlist's direction is the point: `compression` reaches the
        worker off the request with no server-side vocabulary check, so an
        unknown value must fall on the side that keeps the original."""
        from app.processing.raster.cog import cog_preserves_source

        assert cog_preserves_source("converted", "SOME_FUTURE_CODEC") is False
        assert cog_preserves_source("converted", None) is False

    def test_a_verified_cog_supersedes_it_whatever_the_codec(self) -> None:
        """Nothing was converted, so the stored bytes ARE the uploaded bytes —
        there is nothing left to lose by dropping the staged copy."""
        from app.processing.raster.cog import cog_preserves_source

        assert cog_preserves_source("verified", "JPEG") is True

    @pytest.mark.parametrize(
        ("compression", "source_survives"),
        [("DEFLATE", False), ("JPEG", True)],
    )
    async def test_replace_end_to_end_honours_the_profile(
        self,
        test_db_session,
        raster_storage,
        compression: str,
        source_survives: bool,
    ) -> None:
        """The wiring, driven through the real task.

        The staged source has to be a ``staging/`` STORAGE key, not a local
        path — that prefix is what the reaper acts on, so a local-file test
        could not observe this at all.
        """
        admin_id = (
            await test_db_session.execute(
                select(User.id).where(User.username == "admin")
            )
        ).scalar_one()
        live = await _make_live_raster(
            test_db_session, raster_storage, created_by=admin_id
        )
        dataset_id = live.dataset.id
        record_id = live.dataset.record_id

        job = await _queue_replace_job(
            test_db_session,
            dataset_id=dataset_id,
            user_id=admin_id,
            file_path="placeholder",
        )
        job_id = job.id
        staging_key = f"staging/{job_id}/replacement.tif"
        await raster_storage.put(staging_key, io.BytesIO(_geotiff_bytes(seed=21)))
        job.file_path = staging_key
        job.user_metadata = {
            **(job.user_metadata or {}),
            "compression": compression,
        }
        await test_db_session.commit()

        try:
            await reupload_raster.func(
                job_id=str(job_id),
                dataset_id=str(dataset_id),
                file_path=staging_key,
                user_id=str(admin_id),
                attempt_id=str(job.attempt_id),
            )

            test_db_session.expire_all()
            asset = (
                await test_db_session.execute(
                    select(RasterAsset).where(RasterAsset.dataset_id == dataset_id)
                )
            ).scalar_one()
            assert asset.asset_uri != live.cog_key, "precondition: the swap ran"

            assert await raster_storage.exists(staging_key) is source_survives, (
                f"{compression}: staged source should "
                f"{'survive' if source_survives else 'be deleted'}"
            )
        finally:
            await _purge(test_db_session, dataset_id=dataset_id, record_id=record_id)

    def test_both_raster_tails_gate_the_delete_on_the_profile(self) -> None:
        """Both tails route the decision through the one shared predicate.

        The end-to-end test above covers the replace tail. Driving a whole
        successful first ingest (quota, notifications, billing, embeddings)
        to assert the same one bit is not worth its runtime, so the wiring is
        pinned structurally — what would actually regress is someone deleting
        the guard, and that is exactly what this sees.
        """
        import ast
        import inspect

        from app.processing.ingest import tasks_raster, tasks_raster_replace

        for module in (tasks_raster, tasks_raster_replace):
            src = inspect.getsource(module)
            assert "cog_preserves_source(" in src, (
                f"{module.__name__} does not consult the lossless predicate"
            )
            tree = ast.parse(src)
            reaps = [
                node
                for node in ast.walk(tree)
                if isinstance(node, ast.Call)
                and getattr(node.func, "id", None) == "reap_downloaded_staging_source"
            ]
            assert reaps, f"{module.__name__} never reaps its staged source"
            guarded = [
                node
                for node in ast.walk(tree)
                if isinstance(node, ast.If)
                and isinstance(node.test, ast.Name)
                and node.test.id == "source_preserved_in_cog"
            ]
            assert guarded, (
                f"{module.__name__} reaps the upload without gating on whether "
                "the COG preserved it (ADR-002 Decision 7 / #1290 finding 1)"
            )


class TestPostCommitFailureCannotUnpublish:
    """FINDING 2. The mirror image of the post-put window: an error in the
    optional work AFTER the swap committed used to flip final_status to failed,
    and the finally then reaped every newly written key — leaving the committed
    RasterAsset pointing at a COG that no longer existed."""

    async def test_post_commit_failure_leaves_the_replacement_published(
        self, test_db_session, raster_storage, tmp_path, monkeypatch
    ) -> None:
        admin_id = (
            await test_db_session.execute(
                select(User.id).where(User.username == "admin")
            )
        ).scalar_one()
        live = await _make_live_raster(
            test_db_session, raster_storage, created_by=admin_id
        )
        dataset_id = live.dataset.id
        record_id = live.dataset.record_id

        source = tmp_path / "replacement.tif"
        source.write_bytes(_geotiff_bytes(seed=31))
        job = await _queue_replace_job(
            test_db_session,
            dataset_id=dataset_id,
            user_id=admin_id,
            file_path=str(source),
        )
        job_id = job.id

        async def _die(*args, **kwargs):
            raise RuntimeError("valkey went away right after the swap")

        # The first thing the post-commit block does. A transient failure here
        # says nothing about the swap, which is already durable.
        monkeypatch.setattr(
            "app.processing.ingest.tasks_raster_replace.invalidate_catalog_cache",
            _die,
            raising=True,
        )

        try:
            # Must not raise: the replace succeeded, and reporting it as a
            # failed job would be the second bug in this finding.
            await reupload_raster.func(
                job_id=str(job_id),
                dataset_id=str(dataset_id),
                file_path=str(source),
                user_id=str(admin_id),
                attempt_id=str(job.attempt_id),
            )

            test_db_session.expire_all()
            asset = (
                await test_db_session.execute(
                    select(RasterAsset).where(RasterAsset.dataset_id == dataset_id)
                )
            ).scalar_one()

            assert asset.asset_uri != live.cog_key, "the swap must stand"
            for key in (
                asset.asset_uri,
                asset.quicklook_256_uri,
                asset.quicklook_512_uri,
            ):
                assert await raster_storage.exists(key), (
                    f"{key} was reaped after the swap committed — the dataset "
                    "now points at bytes that do not exist"
                )
            assert await raster_storage.size(asset.asset_uri) == asset.size_bytes

            run = (
                await test_db_session.execute(
                    select(DatasetRefreshRun).where(
                        DatasetRefreshRun.ingest_job_id == job_id
                    )
                )
            ).scalar_one()
            assert run.status == "succeeded"

            finished_job = (
                await test_db_session.execute(
                    select(IngestJob).where(IngestJob.id == job_id)
                )
            ).scalar_one()
            assert finished_job.status == "complete"
        finally:
            await _purge(test_db_session, dataset_id=dataset_id, record_id=record_id)


class TestPersistedMetadataDescribesTheServedCog:
    """FINDING 3 and 4, and their composition.

    Conversion changes compression always, nodata under an override, and the
    CRS and footprint under srid_override — so metadata read from the
    pre-conversion source described a file the dataset does not serve.
    """

    async def test_compression_and_nodata_come_from_the_converted_cog(
        self, test_db_session, raster_storage, tmp_path
    ) -> None:
        admin_id = (
            await test_db_session.execute(
                select(User.id).where(User.username == "admin")
            )
        ).scalar_one()
        live = await _make_live_raster(
            test_db_session, raster_storage, created_by=admin_id
        )
        dataset_id = live.dataset.id
        record_id = live.dataset.record_id

        # The source is written with no compression and no nodata; the request
        # asks for LZW and a nodata value, so both differ after conversion.
        source = tmp_path / "replacement.tif"
        source.write_bytes(_geotiff_bytes(seed=41, compress=None))
        job = await _queue_replace_job(
            test_db_session,
            dataset_id=dataset_id,
            user_id=admin_id,
            file_path=str(source),
        )
        job.user_metadata = {
            **(job.user_metadata or {}),
            "compression": "LZW",
            "nodata_override": 7,
        }
        await test_db_session.commit()
        job_id = job.id

        try:
            await reupload_raster.func(
                job_id=str(job_id),
                dataset_id=str(dataset_id),
                file_path=str(source),
                user_id=str(admin_id),
                attempt_id=str(job.attempt_id),
            )

            test_db_session.expire_all()
            asset = (
                await test_db_session.execute(
                    select(RasterAsset).where(RasterAsset.dataset_id == dataset_id)
                )
            ).scalar_one()

            assert (asset.compression or "").upper() == "LZW", (
                "the catalog reports the source's compression, not the COG's"
            )
            assert asset.nodata is not None and float(asset.nodata) == 7.0, (
                "the catalog reports the source's nodata, not the COG's"
            )
        finally:
            await _purge(test_db_session, dataset_id=dataset_id, record_id=record_id)

    async def test_srid_override_applies_when_the_source_declares_a_crs(
        self, test_db_session, raster_storage, tmp_path
    ) -> None:
        """FINDING 4 and 3 composed. The override must reach the conversion
        even though the source declares a CRS, AND the persisted EPSG must be
        the one the converted COG actually carries — which is only the same
        answer if both fixes are in place."""
        admin_id = (
            await test_db_session.execute(
                select(User.id).where(User.username == "admin")
            )
        ).scalar_one()
        live = await _make_live_raster(
            test_db_session, raster_storage, created_by=admin_id
        )
        dataset_id = live.dataset.id
        record_id = live.dataset.record_id

        source = tmp_path / "replacement.tif"
        source.write_bytes(_geotiff_bytes(seed=51))  # declares EPSG:4326
        job = await _queue_replace_job(
            test_db_session,
            dataset_id=dataset_id,
            user_id=admin_id,
            file_path=str(source),
        )
        job.user_metadata = {**(job.user_metadata or {}), "srid_override": 3857}
        await test_db_session.commit()
        job_id = job.id

        try:
            await reupload_raster.func(
                job_id=str(job_id),
                dataset_id=str(dataset_id),
                file_path=str(source),
                user_id=str(admin_id),
                attempt_id=str(job.attempt_id),
            )

            test_db_session.expire_all()
            asset = (
                await test_db_session.execute(
                    select(RasterAsset).where(RasterAsset.dataset_id == dataset_id)
                )
            ).scalar_one()
            dataset = (
                await test_db_session.execute(
                    select(Dataset).where(Dataset.id == dataset_id)
                )
            ).scalar_one()

            assert asset.epsg == 3857, (
                "srid_override was dropped because the source declared a CRS "
                "(#1290 finding 4), or the persisted CRS came from the source "
                "rather than the converted COG (finding 3)"
            )
            assert dataset.srid == 3857
        finally:
            await _purge(test_db_session, dataset_id=dataset_id, record_id=record_id)


class TestCrsAssignmentContract:
    """FINDING 4's contract, pinned in one place so the two tails cannot answer
    it differently — the drift pattern #1277 paid for three rounds running."""

    def test_override_wins_over_a_declared_crs(self) -> None:
        from app.processing.raster.cog import resolve_crs_assignment

        assert resolve_crs_assignment(crs_wkt="GEOGCS[...]", srid_override=3857) == 3857

    def test_override_applies_when_the_source_declares_nothing(self) -> None:
        from app.processing.raster.cog import resolve_crs_assignment

        assert resolve_crs_assignment(crs_wkt=None, srid_override=3857) == 3857

    def test_no_override_and_a_declared_crs_keeps_the_source(self) -> None:
        from app.processing.raster.cog import resolve_crs_assignment

        assert resolve_crs_assignment(crs_wkt="GEOGCS[...]", srid_override=None) is None

    def test_no_crs_and_no_override_is_the_one_refusal(self) -> None:
        from app.processing.raster.cog import resolve_crs_assignment

        with pytest.raises(ValueError, match="Provide a CRS override"):
            resolve_crs_assignment(crs_wkt=None, srid_override=None)

    def test_both_raster_tails_use_the_shared_resolver(self) -> None:
        import ast
        import inspect

        from app.processing.ingest import tasks_raster, tasks_raster_replace

        for module in (tasks_raster, tasks_raster_replace):
            src = inspect.getsource(module)
            assert "resolve_crs_assignment(" in src, (
                f"{module.__name__} resolves srid_override on its own"
            )
            # AST, not text: tasks_raster's #1186 comment quotes the old
            # `user_metadata["crs_missing"]` stamp by name, and that history is
            # worth keeping. What must be gone is the local predicate.
            names = {
                node.id
                for node in ast.walk(ast.parse(src))
                if isinstance(node, ast.Name)
            }
            assert "crs_missing" not in names, (
                f"{module.__name__} still computes its own crs_missing "
                "predicate instead of deferring to the shared resolver"
            )
