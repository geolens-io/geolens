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
from app.platform.dataset_origin import set_dataset_origin
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
    # `tasks_common` binds get_storage at module import, so `_archive_original_file`
    # reads THAT name and never sees the patch above. Without this the archive
    # step wrote to the real configured storage during the test — silently, and
    # outside tmp_path.
    monkeypatch.setattr(
        "app.processing.ingest.tasks_common.get_storage", lambda: storage, raising=True
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
        # The worker downloads the staged object to a generated temp name, so
        # this is what decides the archived object's filename.
        job.source_filename = "replacement.tif"
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

            # The staged copy always goes: round 3 moved the retained original
            # out of `staging/` rather than pinning it there, because a
            # permanent artifact under a prefix that means "transient" is
            # reaped by the next purge once a newer job supersedes this one.
            assert not await raster_storage.exists(staging_key), (
                "the staged copy must not survive either way — it is either "
                "redundant or relocated"
            )
            durable = f"originals/{dataset_id}/replacement.tif"
            assert await raster_storage.exists(durable) is source_survives, (
                f"{compression}: a durable original should "
                f"{'exist' if source_survives else 'not exist'} under originals/"
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
            # The gate is two facts now: the COG preserved the samples, OR the
            # original was relocated somewhere durable. Either makes the staged
            # copy redundant; neither alone is enough.
            names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
            assert {"source_preserved_in_cog", "lossy_original_archived"} <= names, (
                f"{module.__name__} reaps the upload without consulting both "
                "whether the COG preserved it and whether it was archived "
                "(ADR-002 Decision 7 / #1290 findings 1 and 2)"
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
            # round-2 finding 3: the two fields answer different questions.
            # `srid` is what the dataset serves; `original_srid` is documented
            # as the SRID of the uploaded file, so it must still report what
            # arrived. Round 1 collapsed both onto the COG read and lost that.
            assert dataset.original_srid == 4326, (
                "original_srid must record the SRID the UPLOAD declared, not "
                "the override the converted COG carries"
            )
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


# ---------------------------------------------------------------------------
# 8. Round-2 review findings (#1290)
# ---------------------------------------------------------------------------


async def _make_stac_origin_raster(session, *, created_by: uuid.UUID) -> _LiveRaster:
    """A raster dataset shaped the way ``stac_import`` leaves one.

    The shape is the finding: a remote backend, an external href for an
    asset_uri, and NO dataset_assets or record_distributions rows at all —
    the import writes the dataset and the raster asset and stops.
    """
    record = Record(
        title="STAC scene",
        summary="imported from a remote catalog",
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
        source_filename=None,
        srid=4326,
    )
    set_dataset_origin(
        dataset,
        "stac",
        uri="https://example.invalid/scenes/abc/data.tif",
        asset_href="https://example.invalid/scenes/abc/data.tif",
        item_href="https://example.invalid/items/abc",
        collection_id="sentinel-2",
    )
    session.add(dataset)
    await session.flush()

    asset = RasterAsset(
        dataset_id=dataset.id,
        asset_uri="https://example.invalid/scenes/abc/data.tif",
        storage_backend="remote",
        cog_status="verified",
        epsg=4326,
        band_count=1,
        dtype="uint8",
    )
    session.add(asset)
    await session.commit()
    return _LiveRaster(dataset, asset, "https://example.invalid/scenes/abc/data.tif")


class TestReplacingAStacOriginRaster:
    """FINDINGS 1 and 2, composed.

    A STAC-imported raster reaches this door like any other raster_dataset, but
    its rows describe a file GeoLens does not own. The swap makes GeoLens the
    owner, and every field that encoded "somebody else owns this" has to move
    with the pointer — otherwise the download endpoint SSRF-validates a managed
    key as a URL, VRT health probes it over HTTP, and the asset rows the swap
    tried to UPDATE never existed to be updated.
    """

    async def test_swap_takes_ownership_and_publishes_every_asset_row(
        self, test_db_session, raster_storage, tmp_path
    ) -> None:
        admin_id = (
            await test_db_session.execute(
                select(User.id).where(User.username == "admin")
            )
        ).scalar_one()
        live = await _make_stac_origin_raster(test_db_session, created_by=admin_id)
        dataset_id = live.dataset.id
        record_id = live.dataset.record_id
        remote_href = live.cog_key

        # Precondition, asserted rather than assumed: this is the shape the
        # finding is about.
        assert (
            await test_db_session.execute(
                text(
                    "SELECT count(*) FROM catalog.dataset_assets WHERE dataset_id = :id"
                ),
                {"id": dataset_id},
            )
        ).scalar_one() == 0

        source = tmp_path / "replacement.tif"
        source.write_bytes(_geotiff_bytes(seed=61))
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
            asset = (
                await test_db_session.execute(
                    select(RasterAsset).where(RasterAsset.dataset_id == dataset_id)
                )
            ).scalar_one()

            # FINDING 1 — ownership moved with the pointer.
            assert asset.asset_uri != remote_href
            assert not asset.asset_uri.startswith("http"), (
                "the swap wrote a managed key; anything still HTTP means the "
                "pointer did not move"
            )
            assert asset.storage_backend == "local", (
                "a managed rasters/ key is still flagged remote — the COG "
                "download endpoint will SSRF-validate it as an external URL "
                "and VRT health will probe it over HTTP (#1290 finding 1)"
            )
            # The managed branch of every consumer is reachable: the key
            # resolves in the storage the rest of the pipeline uses.
            assert await raster_storage.exists(asset.asset_uri)

            # FINDING 2 — all four rows exist and describe the live asset.
            asset_rows = dict(
                (
                    await test_db_session.execute(
                        text(
                            "SELECT key, href FROM catalog.dataset_assets "
                            "WHERE dataset_id = :id"
                        ),
                        {"id": dataset_id},
                    )
                ).all()
            )
            assert asset_rows == {
                "data": asset.asset_uri,
                "thumbnail": asset.quicklook_256_uri,
                "overview": asset.quicklook_512_uri,
            }, (
                "search/STAC advertise no assets for a replaced STAC raster "
                "(#1290 finding 2) — the UPDATEs matched zero rows"
            )
            size_bytes = (
                await test_db_session.execute(
                    text(
                        "SELECT size_bytes FROM catalog.dataset_assets "
                        "WHERE dataset_id = :id AND key = 'data'"
                    ),
                    {"id": dataset_id},
                )
            ).scalar_one()
            assert size_bytes == asset.size_bytes

            distributions = (
                (
                    await test_db_session.execute(
                        text(
                            "SELECT url FROM catalog.record_distributions "
                            "WHERE record_id = :rid AND format = 'geotiff'"
                        ),
                        {"rid": record_id},
                    )
                )
                .scalars()
                .all()
            )
            assert distributions == [asset.asset_uri]

            # The dataset's origin rebinds too — it is an upload now.
            dataset = (
                await test_db_session.execute(
                    select(Dataset).where(Dataset.id == dataset_id)
                )
            ).scalar_one()
            assert dataset.origin_uri is None
            assert (dataset.origin_ref or {}).get("kind") == "upload"
        finally:
            await _purge(test_db_session, dataset_id=dataset_id, record_id=record_id)

    async def test_replacing_an_upload_origin_raster_does_not_duplicate_rows(
        self, test_db_session, raster_storage, tmp_path
    ) -> None:
        """The upsert's other half. An upload-origin dataset already has these
        rows, and two replaces must leave one row per key — not three, and not
        a stale href beside a fresh one."""
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

        try:
            for attempt in range(2):
                source = tmp_path / f"replacement-{attempt}.tif"
                source.write_bytes(_geotiff_bytes(seed=70 + attempt))
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
            rows = (
                await test_db_session.execute(
                    text(
                        "SELECT key, href FROM catalog.dataset_assets "
                        "WHERE dataset_id = :id ORDER BY key"
                    ),
                    {"id": dataset_id},
                )
            ).all()
            assert [r[0] for r in rows] == ["data", "overview", "thumbnail"]
            assert dict(rows)["data"] == asset.asset_uri

            distributions = (
                (
                    await test_db_session.execute(
                        text(
                            "SELECT url FROM catalog.record_distributions "
                            "WHERE record_id = :rid AND format = 'geotiff'"
                        ),
                        {"rid": record_id},
                    )
                )
                .scalars()
                .all()
            )
            assert distributions == [asset.asset_uri], (
                "each replace left its own distribution row behind"
            )
        finally:
            await _purge(test_db_session, dataset_id=dataset_id, record_id=record_id)


class TestLocalStorageHonoursTheRetentionPromise:
    """FINDING 4. `reap_downloaded_staging_source` only governs `staging/`
    object keys, so on a local install the retention promise was kept entirely
    by the unlink — which was unconditional on success. The local staging
    directory is the durable `upload_staging` volume, not scratch, so the fix
    is one policy across both storage shapes rather than a doc caveat."""

    @pytest.mark.parametrize(
        ("compression", "source_survives"),
        [("DEFLATE", False), ("JPEG", True)],
    )
    async def test_local_original_follows_the_same_lossy_gate(
        self,
        test_db_session,
        raster_storage,
        tmp_path,
        compression: str,
        source_survives: bool,
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

        # A local absolute path, which is what save_upload_file returns on a
        # local-storage install — the reaper never sees it, so the unlink is
        # the only thing standing between the operator and a deleted original.
        source = tmp_path / "local-original.tif"
        source.write_bytes(_geotiff_bytes(seed=81))
        job = await _queue_replace_job(
            test_db_session,
            dataset_id=dataset_id,
            user_id=admin_id,
            file_path=str(source),
        )
        job.user_metadata = {
            **(job.user_metadata or {}),
            "compression": compression,
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

            assert not source.exists(), (
                "the staged local copy goes in both cases — it is either "
                "redundant or already relocated"
            )
            durable = f"originals/{dataset_id}/local-original.tif"
            assert await raster_storage.exists(durable) is source_survives, (
                f"{compression}: a durable original should "
                f"{'exist' if source_survives else 'not exist'} under "
                "originals/ — RUNBOOK section 9 promises the same policy on "
                "both storage shapes, and in local mode the provider is rooted "
                "at the same durable volume the staging file lived on"
            )
        finally:
            await _purge(test_db_session, dataset_id=dataset_id, record_id=record_id)

    def test_both_tails_gate_the_local_unlink_too(self) -> None:
        """The object-store reaper and the local unlink are two different
        deletions of the same file, and a gate on only one of them is the
        finding. Structural for the first-ingest tail, for the same reason as
        its sibling above."""
        import ast
        import inspect

        from app.processing.ingest import tasks_raster, tasks_raster_replace

        for module in (tasks_raster, tasks_raster_replace):
            tree = ast.parse(inspect.getsource(module))
            # The unlink branch must test the lossless predicate, not just the
            # terminal status.
            gated = [
                node
                for node in ast.walk(tree)
                if isinstance(node, ast.BoolOp)
                and any(
                    isinstance(v, ast.Name)
                    and v.id in ("source_preserved_in_cog", "lossy_original_archived")
                    for v in ast.walk(node)
                )
            ]
            assert gated, (
                f"{module.__name__} unlinks the local original on success "
                "without consulting whether the COG preserved it (#1290 "
                "round-2 finding 4)"
            )


# ---------------------------------------------------------------------------
# 9. Round-3 review findings (#1290)
# ---------------------------------------------------------------------------


class TestReprojectionCountsAsSampleAltering:
    """FINDING 1. `gdalwarp -t_srs` resamples every pixel onto a new grid, so a
    reprojection under DEFLATE alters samples exactly as JPEG does. Looking
    only at the codec answered the wrong question."""

    def test_a_warp_under_a_lossless_codec_still_alters_samples(self) -> None:
        from app.processing.raster.cog import cog_preserves_source

        assert cog_preserves_source("converted", "DEFLATE") is True
        assert cog_preserves_source("converted", "DEFLATE", reprojected=True) is False

    def test_a_lossy_codec_is_still_lossy_without_a_warp(self) -> None:
        from app.processing.raster.cog import cog_preserves_source

        assert cog_preserves_source("converted", "JPEG", reprojected=False) is False

    def test_verified_still_short_circuits(self) -> None:
        """Nothing ran, so neither axis applies. A warp cannot co-occur:
        `check_and_prepare_cog` treats any assign_crs as a custom option and
        always converts."""
        from app.processing.raster.cog import cog_preserves_source

        assert cog_preserves_source("verified", "JPEG") is True

    async def test_replace_with_srid_override_keeps_the_original(
        self, test_db_session, raster_storage, tmp_path
    ) -> None:
        """End to end: default DEFLATE plus an override. Lossless codec, warped
        pixels — the upload is the only copy of the original samples."""
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

        source = tmp_path / "reprojected.tif"
        source.write_bytes(_geotiff_bytes(seed=91))
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
            assert await raster_storage.exists(
                f"originals/{dataset_id}/reprojected.tif"
            ), (
                "a reprojected replace deleted its only un-resampled copy — "
                "DEFLATE says nothing about a warp (#1290 round-3 finding 1)"
            )
        finally:
            await _purge(test_db_session, dataset_id=dataset_id, record_id=record_id)


class TestRetainedOriginalLivesOutsideThePurgesDomain:
    """FINDING 2. `staging/` means transient and the retention purge is right to
    clean it — it exempts only a dataset's most recent complete job, so a
    retained original from an older job was reaped once the window passed. The
    fix moves the artifact rather than teaching the purge an exemption."""

    async def test_the_kept_original_is_under_originals_not_staging(
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

        job = await _queue_replace_job(
            test_db_session,
            dataset_id=dataset_id,
            user_id=admin_id,
            file_path="placeholder",
        )
        job_id = job.id
        staging_key = f"staging/{job_id}/scene.tif"
        await raster_storage.put(staging_key, io.BytesIO(_geotiff_bytes(seed=95)))
        job.file_path = staging_key
        job.source_filename = "scene.tif"
        job.user_metadata = {**(job.user_metadata or {}), "compression": "JPEG"}
        await test_db_session.commit()

        try:
            await reupload_raster.func(
                job_id=str(job_id),
                dataset_id=str(dataset_id),
                file_path=staging_key,
                user_id=str(admin_id),
                attempt_id=str(job.attempt_id),
            )

            surviving = await raster_storage.list("")
            staged = [k for k in surviving if k.startswith("staging/")]
            assert staged == [], (
                f"a permanent artifact was left under staging/: {staged} — the "
                "retention purge will reap it once a newer job supersedes this "
                "one, and the RUNBOOK calls the copy permanent"
            )
            assert await raster_storage.exists(f"originals/{dataset_id}/scene.tif")
        finally:
            await _purge(test_db_session, dataset_id=dataset_id, record_id=record_id)

    async def test_a_second_lossy_replace_keeps_both_originals(
        self, test_db_session, raster_storage, tmp_path
    ) -> None:
        """The lifecycle question: what happens to the kept original when the
        dataset is replaced again. They coexist, keyed by uploaded filename, so
        a differently-named upload adds and a same-named one overwrites. Both
        are reaped together when the dataset is deleted, because
        `delete_dataset` already cleans the whole `originals/<id>/` prefix."""
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

        try:
            for name in ("first.tif", "second.tif"):
                source = tmp_path / name
                source.write_bytes(_geotiff_bytes(seed=hash(name) % 500))
                job = await _queue_replace_job(
                    test_db_session,
                    dataset_id=dataset_id,
                    user_id=admin_id,
                    file_path=str(source),
                )
                job.user_metadata = {
                    **(job.user_metadata or {}),
                    "compression": "JPEG",
                }
                await test_db_session.commit()
                await reupload_raster.func(
                    job_id=str(job.id),
                    dataset_id=str(dataset_id),
                    file_path=str(source),
                    user_id=str(admin_id),
                    attempt_id=str(job.attempt_id),
                )

            kept = sorted(await raster_storage.list(f"originals/{dataset_id}/"))
            assert [k.rsplit("/", 1)[-1] for k in kept] == ["first.tif", "second.tif"]
        finally:
            await _purge(test_db_session, dataset_id=dataset_id, record_id=record_id)


class TestFirstIngestPersistsTheServedCogToo:
    """FINDING 3. The round-1 CRS fix made first ingest warp declared-CRS
    sources, but its metadata still came from the pre-warp read — the same
    defect the replace tail fixed a round earlier, left behind because that
    dispatch was scoped to replace only."""

    def test_both_tails_persist_cog_derived_metadata(self) -> None:
        """Structural, and deliberately so: this pins the drift CLASS the way
        the shared CRS resolver did. Each tail must read the converted artifact
        and hand THAT to its row builder — a tail that goes back to persisting
        the source read fails here even if its own behaviour tests pass."""
        import ast
        import inspect

        from app.processing.ingest import tasks_raster, tasks_raster_replace

        for module, task_name in (
            (tasks_raster, "ingest_raster"),
            (tasks_raster_replace, "reupload_raster"),
        ):
            tree = ast.parse(inspect.getsource(module))
            # Scoped to the TASK body. `create_raster_dataset` legitimately
            # takes a parameter called `meta` — it receives the COG's metadata
            # and its docstring says so. The drift this pins is in the task,
            # which is the thing that decides WHICH read to hand over.
            task = next(
                node
                for node in ast.walk(tree)
                if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef))
                and node.name == task_name
            )
            names = {node.id for node in ast.walk(task) if isinstance(node, ast.Name)}
            assert "cog_meta" in names, (
                f"{task_name} never reads the converted COG's metadata"
            )
            assert "source_meta" in names, (
                f"{task_name} does not keep a separate source read for "
                "original_srid and the CRS decision"
            )
            # The old undifferentiated name is what the drift looked like.
            assert "meta" not in names, (
                f"{task_name} still carries an undifferentiated `meta` — the "
                "two reads answer different questions and the names have to "
                "say which is which (#1290 round-3 finding 3)"
            )

    async def test_first_ingest_records_the_uploads_srid_separately(
        self, test_db_session, raster_storage, tmp_path, monkeypatch
    ) -> None:
        """Behavioural half, on the field the finding is really about.
        `create_raster_dataset` is the seam both the task and this test go
        through, so this pins what the task hands it."""
        from app.processing.ingest.tasks_raster_common import create_raster_dataset

        admin_id = (
            await test_db_session.execute(
                select(User.id).where(User.username == "admin")
            )
        ).scalar_one()

        cog_meta = {"epsg": 3857, "driver": "GTiff", "dtype": "uint8", "band_count": 1}
        record, dataset, asset = await create_raster_dataset(
            test_db_session,
            meta=cog_meta,
            source_sha256="a" * 64,
            asset_sha256="b" * 64,
            cog_status="converted",
            cog_size=123,
            source_filename="scene.tif",
            created_by=admin_id,
            title="round-3 srid split",
            summary=None,
            visibility="private",
            original_srid=4326,
        )
        await test_db_session.commit()
        try:
            assert dataset.srid == 3857, "srid must describe the served COG"
            assert dataset.original_srid == 4326, (
                "original_srid must describe the upload — first ingest was "
                "storing nothing here while replace stored the source's SRID"
            )
            assert asset.epsg == 3857
        finally:
            await _purge(test_db_session, dataset_id=dataset.id, record_id=record.id)
