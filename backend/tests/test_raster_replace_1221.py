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

import asyncio
import contextlib
import io
import json as _json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest
from fastapi import HTTPException, Request
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

    Most callers resolve ``get_storage`` from ``app.platform.storage`` at call
    time, so one patch would cover them. Two modules bind the name at import
    time instead and need their own patch or they keep reading the real
    process-wide storage singleton (``app.platform.storage.provider._storage``,
    set for the test by the ``client`` fixture to ITS OWN tmp dir, a different
    one than this fixture's) rather than the object this fixture hands back.
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
    # fix(#1813): `tasks_vrt` ALSO binds get_storage at module import (its own
    # `from app.platform.storage import get_storage`, used by `regenerate_vrt`).
    # Without this, every VRT-stamp test that drives a real regeneration
    # (`_run_regeneration`) writes and reaps generation objects against
    # whatever storage the `client` fixture's tmp dir currently is, not this
    # fixture's — silently, since `LocalStorageProvider.delete` no-ops on a
    # missing key and the mismatched writes still succeed. Harmless for these
    # tests' own assertions (they only read `last_regenerated_at`), but it is
    # the same class of import-time-binding gap `tasks_common` already needed
    # patched above, and leaves the seed VRT this fixture wrote never actually
    # reaped. `test_regenerate_vrt_integration.py`'s own `local_storage`
    # fixture documents the identical rule for the identical reason.
    monkeypatch.setattr(
        "app.processing.ingest.tasks_vrt.get_storage", lambda: storage, raising=True
    )
    return storage


async def _archived_names(session, dataset_id) -> list[str]:
    """The uploaded filenames of a dataset's kept originals.

    Read from the counted rows' ``description``, because object keys are pure
    content hashes since #1290 round 8 — the filename left object identity so
    two names for the same bytes could not become two objects.
    """
    rows = (
        (
            await session.execute(
                text(
                    "SELECT description FROM catalog.dataset_assets "
                    "WHERE dataset_id = :id AND key LIKE 'archived_original:%'"
                ),
                {"id": dataset_id},
            )
        )
        .scalars()
        .all()
    )
    return sorted(r for r in rows if r)


async def _archived_originals(storage, dataset_id) -> list[str]:
    """The object keys archived under ``originals/<dataset_id>/``, basenamed."""
    keys = await storage.list(f"originals/{dataset_id}/")
    # Strip exactly a 12-hex-char prefix. A blunt split("-", 1) would also eat
    # the first segment of a hyphenated filename like `local-original.tif`.
    return sorted(re.sub(r"^[0-9a-f]{12}-", "", k.rsplit("/", 1)[-1]) for k in keys)


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


async def _make_vrt_parent(session, storage, *, created_by, member) -> _LiveRaster:
    """A VRT dataset with one member, ready to regenerate.

    Shaped the way `ingest_vrt` leaves one: a vrt_dataset record, a RasterAsset
    whose asset_uri is the VRT object, and a vrt_source_links row.
    """
    from app.processing.raster.models import VrtSourceLink

    record = Record(
        title="Mosaic",
        record_type="vrt_dataset",
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
        source_format=None,
        srid=4326,
    )
    session.add(dataset)
    await session.flush()

    vrt_key = f"rasters/{dataset.id}/vrtsha/source.vrt"
    asset = RasterAsset(
        dataset_id=dataset.id,
        asset_uri=vrt_key,
        storage_backend="local",
        vrt_type="mosaic",
        resolution_strategy="finest",
        status="ready",
        epsg=4326,
        band_count=1,
        dtype="uint8",
        ingested_at=datetime.now(timezone.utc),
    )
    session.add(asset)
    session.add(
        VrtSourceLink(
            vrt_dataset_id=dataset.id,
            source_dataset_id=member.dataset.id,
            position=0,
        )
    )
    await session.commit()
    await storage.put(vrt_key, io.BytesIO(b"<VRTDataset></VRTDataset>"))

    # gdalbuildvrt reads the member through `resolve_vrt_source_path`, which
    # resolves against the staging dir rather than this fixture's provider
    # root — so the member's COG has to exist THERE for a real build to run.
    from pathlib import Path as _P

    from app.processing.ingest.tasks_vrt import resolve_vrt_source_path

    member_path = _P(resolve_vrt_source_path(member.asset.asset_uri, tenant_id=None))
    member_path.parent.mkdir(parents=True, exist_ok=True)
    member_path.write_bytes(_geotiff_bytes(seed=1))
    return _LiveRaster(dataset, asset, vrt_key)


async def _run_regeneration(session, *, parent, user_id) -> None:
    """Drive the real ``regenerate_vrt`` task once, end to end."""
    import uuid as _uuid

    from app.processing.ingest.tasks_vrt import regenerate_vrt
    from app.processing.raster.models import VrtGeneration

    generation_id = _uuid.uuid4()
    job = IngestJob(
        dataset_id=parent.dataset.id,
        source_filename="regen",
        created_by=user_id,
        status="pending",
        user_metadata={"vrt_regenerate": True},
    )
    session.add(job)
    session.add(
        VrtGeneration(
            id=generation_id,
            vrt_dataset_id=parent.dataset.id,
            status="pending",
            started_at=datetime.now(timezone.utc),
        )
    )
    await session.execute(
        text(
            "UPDATE catalog.raster_assets "
            "SET current_generation_id = :gen, status = 'regenerating' "
            "WHERE dataset_id = :id"
        ),
        {"gen": generation_id, "id": parent.dataset.id},
    )
    await session.commit()
    await session.refresh(job)
    await regenerate_vrt.func(
        job_id=str(job.id),
        vrt_dataset_id=str(parent.dataset.id),
        attempt_id=str(job.attempt_id),
        generation_id=str(generation_id),
    )


async def _run_vrt_creation(session, storage, *, member, user_id):
    """Drive the real ``ingest_vrt`` once. Returns (dataset_id, record_id).

    Exercises the CREATION tail, which round 10 found had no snapshot instant
    at all — so a member replaced during the first build was masked exactly as
    it was on regenerate.
    """
    import json as _json
    from pathlib import Path as _P

    from app.processing.ingest.tasks_vrt import ingest_vrt, resolve_vrt_source_path

    # gdalbuildvrt reads through resolve_vrt_source_path, which resolves
    # against the staging dir rather than this fixture's provider root.
    member_path = _P(resolve_vrt_source_path(member.asset.asset_uri, tenant_id=None))
    member_path.parent.mkdir(parents=True, exist_ok=True)
    member_path.write_bytes(_geotiff_bytes(seed=1))

    job = IngestJob(
        source_filename="mosaic.vrt",
        created_by=user_id,
        status="pending",
        user_metadata={"title": "Mosaic", "visibility": "public"},
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)
    await ingest_vrt.func(
        job_id=str(job.id),
        source_dataset_ids=_json.dumps([str(member.dataset.id)]),
        user_id=str(user_id),
        attempt_id=str(job.attempt_id),
        vrt_type="mosaic",
        resolution_strategy="finest",
    )
    row = (
        await session.execute(
            text(
                "SELECT d.id, d.record_id FROM catalog.datasets d "
                "JOIN catalog.records r ON r.id = d.record_id "
                "WHERE r.record_type = 'vrt_dataset' "
                "ORDER BY r.created_at DESC LIMIT 1"
            )
        )
    ).one()
    return row[0], row[1]


async def _purge_vrt(session, *, ids) -> None:
    """``ids`` is (parent_dataset, parent_record, member_dataset, member_record).

    Explicit ids rather than the ORM objects: callers expire the session before
    asserting, and reading an expired attribute lazy-loads, which under AnyIO
    raises MissingGreenlet instead of returning a value.
    """
    from app.processing.raster.models import VrtGeneration, VrtSourceLink

    parent_ds, parent_rec, member_ds, member_rec = ids
    await session.execute(
        delete(VrtSourceLink).where(VrtSourceLink.vrt_dataset_id == parent_ds)
    )
    await session.execute(
        delete(VrtGeneration).where(VrtGeneration.vrt_dataset_id == parent_ds)
    )
    await session.commit()
    await _purge(session, dataset_id=parent_ds, record_id=parent_rec)
    await _purge(session, dataset_id=member_ds, record_id=member_rec)


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


async def _make_owner(session) -> uuid.UUID:
    """Commit a throwaway user and return its id.

    The quota tests measure one identity's usage exactly, and `admin` is shared
    with every other suite running against this database — so they own their
    subject rather than borrowing it.
    """
    from app.modules.auth.models import User as UserModel

    suffix = uuid.uuid4().hex[:8]
    user = UserModel(
        username=f"quota_owner_{suffix}",
        email=f"quota_owner_{suffix}@example.invalid",
        password_hash="x",
    )
    session.add(user)
    await session.commit()
    return user.id


async def _drop_owner(session, user_id: uuid.UUID) -> None:
    """Remove a throwaway user once its datasets are gone.

    Order matters and is the point: `records.created_by` is ON DELETE SET NULL,
    so deleting the user first would orphan the very rows the test is about
    rather than remove them.
    """
    from app.modules.auth.models import User as UserModel

    await session.execute(delete(UserModel).where(UserModel.id == user_id))
    await session.commit()


async def _set_counted_data_bytes(session, dataset_id: uuid.UUID, size: int) -> None:
    """Give a dataset `size` bytes of QUOTA-COUNTED storage.

    The `data` row in `dataset_assets` is what `get_user_quota_usage` sums, so
    this is the only way to make a dataset weigh anything as far as the caps are
    concerned — the RasterAsset's own `size_bytes` is not counted.
    """
    await session.execute(
        text(
            "INSERT INTO catalog.dataset_assets (dataset_id, key, href, size_bytes) "
            "VALUES (:id, 'data', 'x', :size) "
            "ON CONFLICT ON CONSTRAINT uq_dataset_assets_key "
            "DO UPDATE SET size_bytes = EXCLUDED.size_bytes"
        ),
        {"id": dataset_id, "size": size},
    )
    await session.commit()


@contextlib.contextmanager
def _capped(*, storage_cap: int = 0, count_cap: int = 0):
    """Run the block with both quota caps forced (0 is the unlimited default)."""
    with (
        patch(
            "app.modules.quota.service.MAX_STORAGE_BYTES_PER_USER.get",
            new_callable=AsyncMock,
            return_value=storage_cap,
        ),
        patch(
            "app.modules.quota.service.MAX_DATASETS_PER_USER.get",
            new_callable=AsyncMock,
            return_value=count_cap,
        ),
    ):
        yield


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
        """Replace twice with the same bytes.

        The second conversion hashes to what the first one published, and this
        used to make the new object BE the live object: same dataset id, same
        content hash, same three keys. A reap that only asked "what was the
        previous pointer" then deleted the raster the dataset was serving, and
        the filter on both cleanup paths was what made it a no-op.

        fix(#1778 codex r3): the keys carry an attempt segment now, so the two
        attempts cannot name one object at all and the collision this test was
        written for is unreachable. What it pins instead is the pair of
        properties that collision threatened: the published COG is readable
        after the second replace, and the superseded one is gone rather than
        orphaned. The content hash is still shared, which is what keeps this a
        test about identical bytes.
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

            assert keys[0] != keys[1], (
                "attempt fencing must give each attempt its own key — a shared "
                "one is what let the stale-job reaper delete a live raster"
            )
            first_sha, second_sha = (key.split("/")[-2] for key in keys)
            assert first_sha == second_sha, (
                "identical bytes must still hash to one value — otherwise this "
                "test is no longer about an identical re-upload"
            )
            assert await raster_storage.exists(keys[1]), (
                "the live COG was reaped by its own replacement"
            )
            assert not await raster_storage.exists(keys[0]), (
                "the superseded COG must be reaped, not orphaned: with the two "
                "attempts writing distinct keys, the post-swap followups are "
                "the only thing that removes the first one"
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
    import UI offers JPEG and WEBP alongside the lossless four, and under those
    the COG has discarded detail the upload carried, which makes the upload the
    only lossless original that ever existed."""

    @pytest.mark.parametrize(
        "compression", ["DEFLATE", "deflate", "LZW", "ZSTD", "NONE", "LERC", "lerc"]
    )
    def test_lossless_profiles_supersede_the_upload(self, compression: str) -> None:
        from app.processing.raster.cog import cog_preserves_source

        assert cog_preserves_source("converted", compression) is True

    @pytest.mark.parametrize("compression", ["JPEG", "WEBP", "jpeg"])
    def test_lossy_profiles_do_not(self, compression: str) -> None:
        from app.processing.raster.cog import cog_preserves_source

        assert cog_preserves_source("converted", compression) is False

    def test_lerc_is_judged_on_the_error_bound_we_actually_use(self) -> None:
        """fix(#1290 review): LERC was on the lossy side out of caution, and the
        caution was misplaced. LERC only discards precision when it is given an
        error bound, that bound is the GTiff creation option ``MAX_Z_ERROR``,
        its default is 0, and ``convert_to_cog`` passes nothing — so the base
        samples survive the conversion exactly. Charging a LERC upload for a
        second permanent copy (and rejecting large ones whose quota fits one
        copy but not two) was paying for a loss that never happened.
        """
        from app.processing.raster.cog import (
            LOSSLESS_COG_COMPRESSIONS,
            cog_preserves_source,
        )

        assert "LERC" in LOSSLESS_COG_COMPRESSIONS
        assert cog_preserves_source("converted", "LERC") is True
        # The two that genuinely do throw detail away stay put.
        assert "JPEG" not in LOSSLESS_COG_COMPRESSIONS
        assert "WEBP" not in LOSSLESS_COG_COMPRESSIONS

    def test_reprojected_lerc_still_keeps_the_original(self) -> None:
        """The codec is one of two independent ways to lose the source, and
        this change touches only the codec. A warp resamples every pixel
        whatever it is then compressed with.

        fix(#1291) removed the pipeline's only warp, so nothing sets
        ``reprojected`` today — the axis is kept, and kept tested, because a
        deliberate reproject-at-ingest field would have to set it, and a
        predicate whose second input has quietly rotted is how the upload gets
        deleted on the day that field lands.
        """
        from app.processing.raster.cog import cog_preserves_source

        assert cog_preserves_source("converted", "LERC", reprojected=True) is False

    def test_lerc_stays_lossless_only_while_no_error_bound_is_set(self) -> None:
        """LERC's place on the allowlist is conditional on our own argv.

        ``MAX_Z_ERROR`` is what turns LERC lossy, and GDAL's default of 0 is the
        entire reason LERC can sit in ``LOSSLESS_COG_COMPRESSIONS``. A docstring
        saying so is a checklist someone may not read, so the classification is
        bound here to the fact it depends on: add the knob and this fails,
        instead of the pipeline quietly deleting originals it just degraded.

        Non-docstring string literals only — ``cog.py`` names the option in
        prose deliberately, and a text grep would fire on that.
        """
        import ast
        import inspect

        from app.processing.raster import cog

        tree = ast.parse(inspect.getsource(cog))
        docstrings = {
            id(node.body[0].value)
            for node in ast.walk(tree)
            if isinstance(
                node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
            )
            and node.body
            and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)
            and isinstance(node.body[0].value.value, str)
        }
        # f-string pieces are Constants under a JoinedStr, so an interpolated
        # `f"MAX_Z_ERROR={x}"` is caught by the same walk.
        offenders = sorted(
            node.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in docstrings
            and "MAX_Z_ERROR" in node.value
        )
        if "LERC" not in cog.LOSSLESS_COG_COMPRESSIONS:
            return  # LERC is treated as lossy again; the error bound is free.
        assert not offenders, (
            f"cog.py sets a LERC error bound ({', '.join(offenders)}) while LERC is "
            "in LOSSLESS_COG_COMPRESSIONS. Both cannot be true: a nonzero "
            "MAX_Z_ERROR makes the conversion lossy, and the allowlist then "
            "licenses deleting the only faithful copy of the upload. Either leave "
            "the bound at GDAL's default of 0 and pass nothing, or drop LERC from "
            "LOSSLESS_COG_COMPRESSIONS so it archives the original the way JPEG "
            "and WEBP do."
        )

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
            durable = await _archived_names(test_db_session, dataset_id)
            assert (durable == ["replacement.tif"]) is source_survives, (
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
            "app.processing.ingest.tasks_raster_swap.invalidate_catalog_cache",
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
            durable = await _archived_names(test_db_session, dataset_id)
            assert (durable == ["local-original.tif"]) is source_survives, (
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
    only at the codec answered the wrong question.

    fix(#1291) then removed the only warp this pipeline ran: `srid_override`
    assigns a CRS (`gdal_translate -a_srs`) instead of reprojecting to it. The
    finding's REASONING is untouched and still pinned below — a warp is
    sample-altering whatever the codec — but nothing reaches it any more, so
    the end-to-end case moved to `TestCrsAssignmentPreservesTheSamples`.
    """

    def test_a_warp_under_a_lossless_codec_still_alters_samples(self) -> None:
        from app.processing.raster.cog import cog_preserves_source

        assert cog_preserves_source("converted", "DEFLATE") is True
        assert cog_preserves_source("converted", "DEFLATE", reprojected=True) is False

    def test_a_lossy_codec_is_still_lossy_without_a_warp(self) -> None:
        from app.processing.raster.cog import cog_preserves_source

        assert cog_preserves_source("converted", "JPEG", reprojected=False) is False

    def test_verified_still_short_circuits(self) -> None:
        """Nothing ran, so neither axis applies. A conversion cannot co-occur:
        `check_and_prepare_cog` treats any assign_crs as a custom option and
        always converts."""
        from app.processing.raster.cog import cog_preserves_source

        assert cog_preserves_source("verified", "JPEG") is True


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
            assert await _archived_names(test_db_session, dataset_id) == ["scene.tif"]
        finally:
            await _purge(test_db_session, dataset_id=dataset_id, record_id=record_id)

    async def test_a_second_lossy_replace_keeps_both_originals(
        self, test_db_session, raster_storage, tmp_path
    ) -> None:
        """The lifecycle question: what happens to the kept original when the
        dataset is replaced again. Two uploads that differ in CONTENT coexist,
        because the archive's identity is its content hash and nothing else
        (`archived_original_uri`) — the uploaded name rides along on the row's
        description, where no equality depends on it. Both are reaped together
        when the dataset is deleted, because `delete_dataset` already cleans the
        whole `originals/<id>/` prefix.

        fix(#1526): the two payloads were seeded `hash(name) % 500`, and `hash`
        on a str is salted per interpreter, so about one process in 500 drew the
        same seed for both names. Identical bytes are one archive key by design,
        the upsert collapses them into a single row, and the assertion below
        then read `['second.tif']` — an intermittent CI failure landing on
        whatever PR happened to be running, with nothing to do with its diff.
        Fixed seeds, and the precondition asserted rather than assumed.
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

        try:
            # Written up front so the precondition can be checked before either
            # replace runs: a collapse here is a broken test, not a broken
            # product, and it should say so at the top rather than through the
            # final assert.
            #
            # fix(#1537 review): inside the try, not before it. `_make_live_raster`
            # has already committed the record, dataset and asset, and
            # `test_db_session` has no rollback teardown — isolation on this
            # suite is explicit per-test cleanup. So a precondition that fired
            # out there would skip `_purge` and leave those rows in the shared
            # per-worker database, which is this test's own regression leaving
            # residue for somebody else's to trip over.
            sources = []
            for name, seed in (("first.tif", 401), ("second.tif", 402)):
                source = tmp_path / name
                source.write_bytes(_geotiff_bytes(seed=seed))
                sources.append(source)
            assert len({sha256_file(str(s)) for s in sources}) == 2, (
                "precondition: the two uploads must carry different bytes. One "
                "content hash is one archive, so identical payloads would make "
                "the assertion below a statement about the upsert rather than "
                "about two originals coexisting."
            )

            for source in sources:
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

            assert await _archived_names(test_db_session, dataset_id) == [
                "first.tif",
                "second.tif",
            ]
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


# ---------------------------------------------------------------------------
# 10. Round-4 review findings (#1290)
# ---------------------------------------------------------------------------


class TestReplacementReservesItsNetIncrease:
    """FINDING 1. The swap rewrites the quota-counted `dataset_assets.data`
    size, and did it with no reservation — only first ingest took the lock. A
    source that expands into a much larger COG, or a second replace committing
    against the same owner's budget, sailed past the cap."""

    async def test_expansion_reserves_only_the_delta(
        self, test_db_session, raster_storage
    ) -> None:
        from app.processing.ingest.tasks_raster_swap import reserve_replacement_bytes

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
        await test_db_session.execute(
            text(
                "INSERT INTO catalog.dataset_assets "
                "(dataset_id, key, href, size_bytes) "
                "VALUES (:id, 'data', 'x', 400)"
            ),
            {"id": dataset_id},
        )
        await test_db_session.commit()

        reserved: list[int] = []

        async def _spy(session, user_id, incoming_bytes):
            reserved.append(incoming_bytes)

        try:
            with patch("app.modules.quota.service.reserve_storage_bytes", new=_spy):
                # Growing 400 -> 1000 must charge 600, not 1000: the 400 is
                # already in the user's counted total and is being superseded.
                await reserve_replacement_bytes(
                    test_db_session,
                    dataset_id=dataset_id,
                    owner_id=admin_id,
                    new_size=1000,
                )
                assert reserved == [600]

                # Shrinking needs no reservation at all; the live sum
                # self-corrects when the smaller row commits.
                reserved.clear()
                await reserve_replacement_bytes(
                    test_db_session,
                    dataset_id=dataset_id,
                    owner_id=admin_id,
                    new_size=100,
                )
                assert reserved == []
        finally:
            await _purge(test_db_session, dataset_id=dataset_id, record_id=record_id)

    async def test_credit_comes_from_the_counted_row_not_the_raster_asset(
        self, test_db_session, raster_storage
    ) -> None:
        """A STAC-imported dataset has a RasterAsset carrying bytes and NO
        counted `dataset_assets` row. Crediting the asset's bytes would admit
        an upload the quota never had room for."""
        from app.processing.ingest.tasks_raster_swap import reserve_replacement_bytes

        admin_id = (
            await test_db_session.execute(
                select(User.id).where(User.username == "admin")
            )
        ).scalar_one()
        live = await _make_stac_origin_raster(test_db_session, created_by=admin_id)
        dataset_id = live.dataset.id
        record_id = live.dataset.record_id
        await test_db_session.execute(
            text(
                "UPDATE catalog.raster_assets SET size_bytes = 900 "
                "WHERE dataset_id = :id"
            ),
            {"id": dataset_id},
        )
        await test_db_session.commit()

        reserved: list[int] = []

        async def _spy(session, user_id, incoming_bytes):
            reserved.append(incoming_bytes)

        try:
            with patch("app.modules.quota.service.reserve_storage_bytes", new=_spy):
                await reserve_replacement_bytes(
                    test_db_session,
                    dataset_id=dataset_id,
                    owner_id=admin_id,
                    new_size=1000,
                )
            assert reserved == [1000], (
                "the asset's 900 bytes were credited, but the quota never "
                "counted them — a STAC dataset has no data asset row"
            )
        finally:
            await _purge(test_db_session, dataset_id=dataset_id, record_id=record_id)

    async def test_one_owner_replacing_a_second_dataset_cannot_overshoot(
        self, test_db_session, raster_storage, tmp_path
    ) -> None:
        """The concurrency that matters: SAME OWNER, DIFFERENT DATASETS.

        Two replaces of one dataset cannot race (the one-active-run index
        refuses the second at the door), so the exposure is a second dataset
        owned by the same user. Expressed deterministically here — the other
        dataset's bytes are already counted, which is exactly the state a
        concurrent peer would have committed under the advisory lock.
        """
        admin_id = (
            await test_db_session.execute(
                select(User.id).where(User.username == "admin")
            )
        ).scalar_one()
        neighbour = await _make_live_raster(
            test_db_session, raster_storage, created_by=admin_id
        )
        target = await _make_live_raster(
            test_db_session, raster_storage, created_by=admin_id
        )
        # Captured before any expire_all(): reading them off an expired ORM
        # instance lazy-loads, which under AnyIO is MissingGreenlet.
        target_id = target.dataset.id
        target_record_id = target.dataset.record_id
        target_cog_key = target.cog_key
        neighbour_id = neighbour.dataset.id
        neighbour_record_id = neighbour.dataset.record_id
        # The neighbour already consumes the whole budget.
        await test_db_session.execute(
            text(
                "INSERT INTO catalog.dataset_assets "
                "(dataset_id, key, href, size_bytes) "
                "VALUES (:id, 'data', 'x', 100000)"
            ),
            {"id": neighbour_id},
        )
        await test_db_session.commit()

        source = tmp_path / "overshoot.tif"
        source.write_bytes(_geotiff_bytes(seed=131))
        job = await _queue_replace_job(
            test_db_session,
            dataset_id=target_id,
            user_id=admin_id,
            file_path=str(source),
        )
        job_id = job.id

        try:
            with patch(
                "app.modules.quota.service.MAX_STORAGE_BYTES_PER_USER.get",
                new_callable=AsyncMock,
                return_value=100_500,
            ):
                with pytest.raises(Exception, match="[Ss]torage quota"):
                    await reupload_raster.func(
                        job_id=str(job_id),
                        dataset_id=str(target_id),
                        file_path=str(source),
                        user_id=str(admin_id),
                        attempt_id=str(job.attempt_id),
                    )

            test_db_session.expire_all()
            asset = (
                await test_db_session.execute(
                    select(RasterAsset).where(RasterAsset.dataset_id == target_id)
                )
            ).scalar_one()
            assert asset.asset_uri == target_cog_key, (
                "the swap committed past the owner's byte cap"
            )
            assert await raster_storage.exists(target_cog_key)
        finally:
            await _purge(
                test_db_session,
                dataset_id=neighbour_id,
                record_id=neighbour_record_id,
            )
            await _purge(
                test_db_session,
                dataset_id=target_id,
                record_id=target_record_id,
            )


class TestReplacementAdmissionIsNotCreationAdmission:
    """FINDING 2. `check_upload_quota` rejects at `dataset_count >= count_cap`.
    Applied to a replacement that is a feature lockout, not protection: a
    replacement creates no dataset, so an owner sitting at their permitted
    limit could not replace anything they already own."""

    async def test_owner_at_the_dataset_cap_can_still_replace(
        self, client, admin_auth_header, test_db_session, raster_storage
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

        try:
            # A cap of 1 puts this owner AT their limit — they own datasets
            # already, so any creation would be refused.
            with patch(
                "app.modules.quota.service.MAX_DATASETS_PER_USER.get",
                new_callable=AsyncMock,
                return_value=1,
            ):
                resp = await client.post(
                    f"/datasets/{dataset_id}/reupload",
                    files={"file": ("replacement.tif", _geotiff_bytes(), "image/tiff")},
                    headers=admin_auth_header,
                )
            assert resp.status_code == 201, (
                f"an owner at the dataset cap was locked out of replacing a "
                f"dataset they already own: {resp.status_code} {resp.text}"
            )
        finally:
            await test_db_session.execute(
                delete(IngestJob).where(IngestJob.dataset_id == dataset_id)
            )
            await test_db_session.commit()
            await _purge(test_db_session, dataset_id=dataset_id, record_id=record_id)

    async def test_both_doors_share_the_replacement_admission(self) -> None:
        """Door parity, extended from the round-1 error-class test to the
        quota check. The two doors must call the SAME admission function —
        a creation-shaped check on either one restores the lockout."""
        import ast
        import inspect

        from app.modules.catalog.datasets.api import router_reupload

        tree = ast.parse(inspect.getsource(router_reupload))
        called = {
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        assert "check_replacement_quota" in called
        assert "check_upload_quota" not in called, (
            "a reupload door still runs the creation-shaped quota check"
        )
        for handler in ("reupload_dataset", "request_presigned_reupload"):
            fn = next(
                node
                for node in ast.walk(tree)
                if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef))
                and node.name == handler
            )
            names = {
                n.func.id
                for n in ast.walk(fn)
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
            }
            assert "check_replacement_quota" in names, (
                f"{handler} does not run replacement-aware admission"
            )


class TestArchiveCannotDestroyThePreviousOriginal:
    """FINDING 3. Invariant 10, turned on the archive. A lossy replacement
    reusing a filename overwrote `originals/<dataset>/<filename>` BEFORE the
    swap committed, so a failed commit left the old raster live with its
    faithful original replaced by the failed attempt's bytes."""

    async def test_failed_replace_leaves_the_prior_original_intact(
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

        try:
            # fix(#1537 review): inside the cleanup scope. `_make_live_raster`
            # has committed and `test_db_session` has no rollback teardown, so
            # a precondition firing above the `try` would leak those rows into
            # the shared per-worker database.
            first_bytes = _geotiff_bytes(seed=141)
            second_bytes = _geotiff_bytes(seed=142)
            assert first_bytes != second_bytes

            # A successful lossy replace, archiving "scene.tif".
            source = tmp_path / "scene.tif"
            source.write_bytes(first_bytes)
            job = await _queue_replace_job(
                test_db_session,
                dataset_id=dataset_id,
                user_id=admin_id,
                file_path=str(source),
            )
            job.user_metadata = {**(job.user_metadata or {}), "compression": "JPEG"}
            await test_db_session.commit()
            await reupload_raster.func(
                job_id=str(job.id),
                dataset_id=str(dataset_id),
                file_path=str(source),
                user_id=str(admin_id),
                attempt_id=str(job.attempt_id),
            )
            kept = await raster_storage.list(f"originals/{dataset_id}/")
            assert len(kept) == 1
            preserved_key = kept[0]
            assert await raster_storage.get(preserved_key) == first_bytes

            # A second replace, SAME FILENAME, DIFFERENT BYTES, that fails at
            # the commit. The old raster stays live, so its original must too.
            source2 = tmp_path / "again" / "scene.tif"
            source2.parent.mkdir()
            source2.write_bytes(second_bytes)
            job2 = await _queue_replace_job(
                test_db_session,
                dataset_id=dataset_id,
                user_id=admin_id,
                file_path=str(source2),
            )
            job2.user_metadata = {**(job2.user_metadata or {}), "compression": "JPEG"}
            await test_db_session.commit()

            async def _die(*args, **kwargs):
                raise RuntimeError("the swap transaction died after the archive")

            monkeypatch.setattr(
                "app.processing.ingest.tasks_raster_replace.record_refresh_success",
                _die,
                raising=True,
            )
            with pytest.raises(RuntimeError, match="died after the archive"):
                await reupload_raster.func(
                    job_id=str(job2.id),
                    dataset_id=str(dataset_id),
                    file_path=str(source2),
                    user_id=str(admin_id),
                    attempt_id=str(job2.attempt_id),
                )

            assert await raster_storage.get(preserved_key) == first_bytes, (
                "the failed attempt's bytes overwrote the original belonging "
                "to the raster that is STILL LIVE (#1290 round-4 finding 3)"
            )
        finally:
            await _purge(test_db_session, dataset_id=dataset_id, record_id=record_id)

    async def test_identical_bytes_do_not_double(
        self, test_db_session, raster_storage, tmp_path
    ) -> None:
        """The other half of a content-derived key: re-uploading the same file
        collides into an idempotent rewrite rather than accumulating."""
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
        payload = _geotiff_bytes(seed=151)

        try:
            for attempt in range(2):
                source = tmp_path / f"copy{attempt}" / "same.tif"
                source.parent.mkdir()
                source.write_bytes(payload)
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

            kept = await raster_storage.list(f"originals/{dataset_id}/")
            assert len(kept) == 1, f"identical uploads accumulated: {kept}"
        finally:
            await _purge(test_db_session, dataset_id=dataset_id, record_id=record_id)


# ---------------------------------------------------------------------------
# 11. Round-5 review findings (#1290)
# ---------------------------------------------------------------------------


class TestArchivedOriginalsAreCounted:
    """FINDING 1. `originals/` accumulated permanently and the per-user storage
    sum could not see it, so repeated distinct lossy replacements exhausted a
    byte cap with nothing refusing them."""

    async def test_a_lossy_replace_writes_a_counted_row(
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

        source = tmp_path / "kept.tif"
        payload = _geotiff_bytes(seed=161)
        source.write_bytes(payload)
        job = await _queue_replace_job(
            test_db_session,
            dataset_id=dataset_id,
            user_id=admin_id,
            file_path=str(source),
        )
        job.user_metadata = {**(job.user_metadata or {}), "compression": "JPEG"}
        await test_db_session.commit()

        try:
            await reupload_raster.func(
                job_id=str(job.id),
                dataset_id=str(dataset_id),
                file_path=str(source),
                user_id=str(admin_id),
                attempt_id=str(job.attempt_id),
            )

            row = (
                await test_db_session.execute(
                    text(
                        "SELECT href, size_bytes FROM catalog.dataset_assets "
                        "WHERE dataset_id = :id "
                        "AND key LIKE 'archived_original:%'"
                    ),
                    {"id": dataset_id},
                )
            ).one_or_none()
            assert row is not None, (
                "the kept original has no counted row, so per-user storage "
                "cannot see it (#1290 round-5 finding 1)"
            )
            assert row.size_bytes == len(payload)
            assert row.href.startswith(f"originals/{dataset_id}/")

            # And the quota sum now includes those bytes.
            from app.modules.quota.service import get_user_quota_usage

            usage = await get_user_quota_usage(test_db_session, admin_id)
            assert usage.bytes_used >= len(payload)
        finally:
            await _purge(test_db_session, dataset_id=dataset_id, record_id=record_id)

    async def test_the_reserved_delta_includes_the_kept_original(
        self, test_db_session, raster_storage, tmp_path
    ) -> None:
        """The finding, isolated. A cap-refusal test cannot separate the COG's
        bytes from the archive's — the COG alone would trip a tight cap — so
        this asserts the amount actually reserved, which is the only place the
        archive's contribution is visible.
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

        source = tmp_path / "counted.tif"
        payload = _geotiff_bytes(seed=171)
        source.write_bytes(payload)
        job = await _queue_replace_job(
            test_db_session,
            dataset_id=dataset_id,
            user_id=admin_id,
            file_path=str(source),
        )
        job.user_metadata = {**(job.user_metadata or {}), "compression": "JPEG"}
        await test_db_session.commit()

        reserved: list[int] = []

        async def _spy(session, user_id, incoming_bytes):
            reserved.append(incoming_bytes)

        try:
            with patch("app.modules.quota.service.reserve_storage_bytes", new=_spy):
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
            # This dataset had no counted `data` row, so the credit is zero and
            # the reservation is exactly what the replace adds: the COG plus
            # the original it kept.
            assert reserved == [asset.size_bytes + len(payload)], (
                f"reserved {reserved}, expected the COG ({asset.size_bytes}) "
                f"PLUS the kept original ({len(payload)}) — the archived bytes "
                "are not being admitted (#1290 round-5 finding 1)"
            )
        finally:
            await _purge(test_db_session, dataset_id=dataset_id, record_id=record_id)

    def test_the_archived_key_is_never_published_as_a_stac_asset(self) -> None:
        """The blast radius of a new key. `_build_stac_assets` published every
        row it was handed, and on a published S3 deployment `resolve_asset_url`
        turns a row into a live presigned download — so a counted row for the
        kept original would have handed every viewer the HIGHER-fidelity copy
        the operator chose not to serve."""
        from app.modules.catalog.search.service_records import _build_stac_assets
        from app.platform.assets.keys import PUBLIC_ASSET_KEYS

        rows = [
            {
                "key": "data",
                "href": "rasters/x/y/source.cog.tif",
                "media_type": "image/tiff",
                "roles": ["data"],
            },
            {
                "key": "archived_original:a1b2c3d4e5f60718293a4b5c6d7e8f90",
                "href": "originals/x/a1b2c3d4e5f60718293a4b5c6d7e8f90",
                "media_type": "image/tiff",
                "roles": ["archive"],
            },
        ]
        built = _build_stac_assets(
            rows,
            record_status="published",
            storage_backend="s3",
            public_api_url="https://example.invalid",
            storage_provider=SimpleNamespace(
                generate_presigned_get_url=lambda key, **kw: f"https://signed/{key}"
            ),
        )
        assert "data" in built
        assert "archived_original:a1b2c3d4e5f60718293a4b5c6d7e8f90" not in built, (
            "the kept original is advertised as a downloadable STAC asset"
        )
        assert not any(k.startswith("archived_original") for k in PUBLIC_ASSET_KEYS)


class TestRolledBackArchivesDoNotLeakOrClobber:
    """FINDING 2, both halves. A rolled-back replacement's archive must be
    reaped — and a rolled-back replacement whose bytes match an archive an
    EARLIER successful replace already wrote must NOT be."""

    async def test_a_failed_attempts_new_archive_is_reaped(
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

        source = tmp_path / "doomed.tif"
        source.write_bytes(_geotiff_bytes(seed=181))
        job = await _queue_replace_job(
            test_db_session,
            dataset_id=dataset_id,
            user_id=admin_id,
            file_path=str(source),
        )
        job.user_metadata = {**(job.user_metadata or {}), "compression": "JPEG"}
        await test_db_session.commit()

        async def _die(*args, **kwargs):
            raise RuntimeError("commit died after the archive")

        monkeypatch.setattr(
            "app.processing.ingest.tasks_raster_replace.record_refresh_success",
            _die,
            raising=True,
        )
        try:
            with pytest.raises(RuntimeError, match="died after the archive"):
                await reupload_raster.func(
                    job_id=str(job.id),
                    dataset_id=str(dataset_id),
                    file_path=str(source),
                    user_id=str(admin_id),
                    attempt_id=str(job.attempt_id),
                )
            assert await _archived_originals(raster_storage, dataset_id) == [], (
                "a rolled-back replacement left its archive behind with no "
                "counted row — it can never be found or reclaimed"
            )
        finally:
            await _purge(test_db_session, dataset_id=dataset_id, record_id=record_id)

    async def test_a_failed_attempt_cannot_reap_an_earlier_good_archive(
        self, test_db_session, raster_storage, tmp_path, monkeypatch
    ) -> None:
        """THE trap. The key is content-derived, so a failed attempt uploading
        bytes identical to an already-archived original targets the SAME key.
        Reaping it on failure destroys the original of the raster still live."""
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
        payload = _geotiff_bytes(seed=191)

        try:
            # 1. A successful lossy replace archives these exact bytes.
            first = tmp_path / "a" / "scene.tif"
            first.parent.mkdir()
            first.write_bytes(payload)
            job = await _queue_replace_job(
                test_db_session,
                dataset_id=dataset_id,
                user_id=admin_id,
                file_path=str(first),
            )
            job.user_metadata = {**(job.user_metadata or {}), "compression": "JPEG"}
            await test_db_session.commit()
            await reupload_raster.func(
                job_id=str(job.id),
                dataset_id=str(dataset_id),
                file_path=str(first),
                user_id=str(admin_id),
                attempt_id=str(job.attempt_id),
            )
            kept = await raster_storage.list(f"originals/{dataset_id}/")
            assert len(kept) == 1
            good_key = kept[0]

            # 2. A second attempt with the SAME bytes that fails at the commit.
            second = tmp_path / "b" / "scene.tif"
            second.parent.mkdir()
            second.write_bytes(payload)
            job2 = await _queue_replace_job(
                test_db_session,
                dataset_id=dataset_id,
                user_id=admin_id,
                file_path=str(second),
            )
            job2.user_metadata = {
                **(job2.user_metadata or {}),
                "compression": "JPEG",
            }
            await test_db_session.commit()

            async def _die(*args, **kwargs):
                raise RuntimeError("commit died after the archive")

            monkeypatch.setattr(
                "app.processing.ingest.tasks_raster_replace.record_refresh_success",
                _die,
                raising=True,
            )
            with pytest.raises(RuntimeError, match="died after the archive"):
                await reupload_raster.func(
                    job_id=str(job2.id),
                    dataset_id=str(dataset_id),
                    file_path=str(second),
                    user_id=str(admin_id),
                    attempt_id=str(job2.attempt_id),
                )

            assert await raster_storage.exists(good_key), (
                "the failed attempt reaped an archive it did not create — the "
                "original of the raster that is STILL LIVE is gone"
            )
            assert await raster_storage.get(good_key) == payload
        finally:
            await _purge(test_db_session, dataset_id=dataset_id, record_id=record_id)


class TestDoorAdmitsAgainstTheOwner:
    """FINDING 3. Storage belongs to the dataset's owner, and the worker
    reserves against `record.created_by`. Checking the requester let an admin
    replacing someone else's dataset be judged on their own usage with the
    owner's credit subtracted."""

    async def test_admin_replacing_another_users_dataset_uses_the_owner(
        self, client, admin_auth_header, test_db_session, raster_storage
    ) -> None:
        from app.modules.auth.models import User as UserModel

        other = UserModel(
            username=f"owner_{uuid.uuid4().hex[:8]}",
            email=f"owner_{uuid.uuid4().hex[:8]}@example.invalid",
            password_hash="x",
        )
        test_db_session.add(other)
        await test_db_session.flush()
        other_id = other.id
        live = await _make_live_raster(
            test_db_session, raster_storage, created_by=other_id
        )
        dataset_id = live.dataset.id
        record_id = live.dataset.record_id

        seen: list = []

        async def _spy(db, owner_id, incoming_bytes, request, *, dataset_id):
            seen.append(owner_id)

        try:
            with patch(
                "app.modules.catalog.datasets.api.router_reupload."
                "check_replacement_quota",
                new=_spy,
            ):
                resp = await client.post(
                    f"/datasets/{dataset_id}/reupload",
                    files={"file": ("replacement.tif", _geotiff_bytes(), "image/tiff")},
                    headers=admin_auth_header,
                )
            assert resp.status_code == 201, resp.text
            assert seen == [other_id], (
                "the door judged the replacement against the REQUESTER's "
                "storage, not the owner's — the worker reserves against the "
                "owner, so the two can disagree (#1290 round-5 finding 3)"
            )
        finally:
            await test_db_session.execute(
                delete(IngestJob).where(IngestJob.dataset_id == dataset_id)
            )
            await test_db_session.commit()
            await _purge(test_db_session, dataset_id=dataset_id, record_id=record_id)
            await test_db_session.execute(
                delete(UserModel).where(UserModel.id == other_id)
            )
            await test_db_session.commit()


class TestOwnerlessDatasetsAreExemptAtEverySeam:
    """The ownerless-dataset policy (#1293), pinned seam by seam.

    A dataset whose `records.created_by` is NULL is exempt from quota
    accounting everywhere: its bytes and its row count against nobody, and no
    seam substitutes a stand-in identity for it. The policy, and why it beats
    refusing the mutation or billing the instance admin, is stated once in
    `app.modules.quota.service`'s module docstring; these tests hold the
    behaviour to it so that changing the policy has to be deliberate rather
    than a side effect. #998 tracks the ownership adoption that would end it.

    Ownerless is reachable today and not only from pre-0019 legacy rows:
    `catalog.records.created_by` is ON DELETE SET NULL, so hard-deleting a user
    leaves every dataset they created ownerless and still serving.
    """

    async def test_a_null_identity_reads_as_zero_usage(self, test_db_session) -> None:
        """The mechanism the whole policy rests on, at its source.

        `get_user_quota_usage` filters `records.created_by = :user_id`, and
        `= NULL` is never true, so a NULL identity matches no rows at all. Every
        other seam reads its usage through this aggregate, which is why one
        filter delivers the exemption to all of them without an `is None`
        branch anywhere.
        """
        from app.modules.quota.service import get_user_quota_usage

        usage = await get_user_quota_usage(test_db_session, None)
        assert usage.bytes_used == 0
        assert usage.dataset_count == 0

    async def test_an_ownerless_datasets_bytes_are_charged_to_no_user(
        self, test_db_session, raster_storage
    ) -> None:
        """Exempt means charged to NOBODY, not quietly reassigned to someone.

        Two datasets of identical size sit side by side, one owned and one
        orphaned. The owner's usage must come to exactly the owned one — the
        orphan lands neither on the user beside it nor on the NULL identity.
        Asserted through the bulk aggregate as well as the single-user read,
        because the bulk one backs the admin user list and resolves the same
        column by GROUP BY, so a misattribution would surface there first.
        """
        from app.modules.quota.service import (
            get_user_quota_usage,
            get_user_quota_usage_bulk,
        )

        owner_id = await _make_owner(test_db_session)
        orphaned = await _make_live_raster(
            test_db_session, raster_storage, created_by=None
        )
        owned = await _make_live_raster(
            test_db_session, raster_storage, created_by=owner_id
        )
        await _set_counted_data_bytes(test_db_session, orphaned.dataset.id, 5_000_000)
        await _set_counted_data_bytes(test_db_session, owned.dataset.id, 5_000_000)

        try:
            usage = await get_user_quota_usage(test_db_session, owner_id)
            assert usage.bytes_used == 5_000_000, (
                "the orphaned dataset's bytes landed on the user beside it — "
                "the exemption reassigns storage instead of exempting it "
                f"(#1293): {usage.bytes_used}"
            )
            assert usage.dataset_count == 1

            bulk = await get_user_quota_usage_bulk(test_db_session, [owner_id])
            assert bulk[owner_id].bytes_used == 5_000_000, (
                "the admin user list bills the orphan to a user while the "
                "single-user read does not — the two seams disagree"
            )
            assert bulk[owner_id].dataset_count == 1

            assert (await get_user_quota_usage(test_db_session, None)).bytes_used == 0
        finally:
            for live in (orphaned, owned):
                await _purge(
                    test_db_session,
                    dataset_id=live.dataset.id,
                    record_id=live.dataset.record_id,
                )
            await _drop_owner(test_db_session, owner_id)

    async def test_the_door_admits_what_it_would_refuse_for_a_real_owner(
        self, test_db_session, raster_storage
    ) -> None:
        """Door admission, with ownership as the only variable.

        The same two datasets, the same cap, the same replacement — judged once
        while a real user owns them and once after they are orphaned, which is
        the transition an admin deleting that user actually performs. Owned,
        the ballast puts the owner over the cap and the replacement is refused;
        ownerless, the same bytes count against nobody and it is admitted.
        """
        from app.modules.quota.service import check_replacement_quota

        owner_id = await _make_owner(test_db_session)
        target = await _make_live_raster(
            test_db_session, raster_storage, created_by=owner_id
        )
        ballast = await _make_live_raster(
            test_db_session, raster_storage, created_by=owner_id
        )
        await _set_counted_data_bytes(test_db_session, target.dataset.id, 100)
        await _set_counted_data_bytes(test_db_session, ballast.dataset.id, 5_000_000)

        request = MagicMock(spec=Request)

        try:
            with _capped(storage_cap=1_000_000):
                with pytest.raises(HTTPException) as exc_info:
                    await check_replacement_quota(
                        test_db_session,
                        owner_id,
                        100,
                        request,
                        dataset_id=target.dataset.id,
                    )
                assert exc_info.value.status_code == 413

                await test_db_session.execute(
                    text(
                        "UPDATE catalog.records SET created_by = NULL "
                        "WHERE id IN (:a, :b)"
                    ),
                    {"a": target.dataset.record_id, "b": ballast.dataset.record_id},
                )
                await test_db_session.commit()

                await check_replacement_quota(
                    test_db_session,
                    None,
                    100,
                    request,
                    dataset_id=target.dataset.id,
                )
        finally:
            for live in (target, ballast):
                await _purge(
                    test_db_session,
                    dataset_id=live.dataset.id,
                    record_id=live.dataset.record_id,
                )
            await _drop_owner(test_db_session, owner_id)

    async def test_reserve_storage_bytes_accumulates_nothing_for_a_null_owner(
        self, test_db_session, raster_storage
    ) -> None:
        """The publish-time seam, and the one edge the exemption does NOT cover.

        Ownerless bytes never accumulate, so a reservation that fits under the
        cap on its own is admitted no matter how much orphaned storage exists.
        But the recount reading zero is not the same as the seam
        short-circuiting: `incoming_bytes` is still weighed against the cap by
        itself, so a single reservation larger than the whole cap is still
        refused. Pinned because an `if user_id is None: return` would look
        equivalent and is not.
        """
        from app.modules.quota.service import (
            StorageQuotaExceededError,
            reserve_storage_bytes,
        )

        owner_id = await _make_owner(test_db_session)
        orphaned = await _make_live_raster(
            test_db_session, raster_storage, created_by=None
        )
        owned = await _make_live_raster(
            test_db_session, raster_storage, created_by=owner_id
        )
        await _set_counted_data_bytes(test_db_session, orphaned.dataset.id, 5_000_000)
        await _set_counted_data_bytes(test_db_session, owned.dataset.id, 5_000_000)

        try:
            with _capped(storage_cap=1_000_000):
                await reserve_storage_bytes(test_db_session, None, 900_000)

                with pytest.raises(StorageQuotaExceededError):
                    await reserve_storage_bytes(test_db_session, owner_id, 900_000)

                with pytest.raises(StorageQuotaExceededError):
                    await reserve_storage_bytes(test_db_session, None, 1_000_001)
        finally:
            for live in (orphaned, owned):
                await _purge(
                    test_db_session,
                    dataset_id=live.dataset.id,
                    record_id=live.dataset.record_id,
                )
            await _drop_owner(test_db_session, owner_id)

    async def test_reserve_dataset_slot_cannot_refuse_a_null_owner(
        self, test_db_session, raster_storage
    ) -> None:
        """The count seam answers the same way, and cannot refuse at all.

        Zero is below every positive cap, so the count cap has no residual edge
        the way the byte cap does. Not reachable today — every caller creates a
        Record for an authenticated uploader — but pinned so the two caps give
        one answer if an adoption or re-ingest path ever reaches it.
        """
        from app.modules.quota.service import (
            DatasetQuotaExceededError,
            reserve_dataset_slot,
        )

        owner_id = await _make_owner(test_db_session)
        orphaned = await _make_live_raster(
            test_db_session, raster_storage, created_by=None
        )
        owned = await _make_live_raster(
            test_db_session, raster_storage, created_by=owner_id
        )

        try:
            with _capped(count_cap=1):
                await reserve_dataset_slot(test_db_session, None)

                with pytest.raises(DatasetQuotaExceededError):
                    await reserve_dataset_slot(test_db_session, owner_id)
        finally:
            for live in (orphaned, owned):
                await _purge(
                    test_db_session,
                    dataset_id=live.dataset.id,
                    record_id=live.dataset.record_id,
                )
            await _drop_owner(test_db_session, owner_id)

    async def test_the_worker_reserve_hands_a_null_owner_straight_through(
        self, test_db_session, raster_storage
    ) -> None:
        """The worker-side replacement seam substitutes no identity of its own.

        `reserve_replacement_bytes` computes the net increase and delegates the
        cap decision, so it must pass the owner it was given — including None.
        Resolving a fallback here is exactly how the worker would start
        refusing replacements the door already admitted.
        """
        from app.processing.ingest.tasks_raster_swap import reserve_replacement_bytes

        orphaned = await _make_live_raster(
            test_db_session, raster_storage, created_by=None
        )
        dataset_id = orphaned.dataset.id
        await _set_counted_data_bytes(test_db_session, dataset_id, 400)

        seen: list[tuple] = []

        async def _spy(session, user_id, incoming_bytes):
            seen.append((user_id, incoming_bytes))

        try:
            with patch("app.modules.quota.service.reserve_storage_bytes", new=_spy):
                await reserve_replacement_bytes(
                    test_db_session,
                    dataset_id=dataset_id,
                    owner_id=None,
                    new_size=1000,
                )
            assert seen == [(None, 600)], (
                "the worker named an identity the door never used — door and "
                "worker can now disagree about an ownerless replacement (#1293)"
            )
        finally:
            await _purge(
                test_db_session,
                dataset_id=dataset_id,
                record_id=orphaned.dataset.record_id,
            )

    def test_every_replacement_admission_point_bills_the_datasets_owner(self) -> None:
        """Why the exemption reaches all three doors: they resolve one column.

        Structural, because the third admission point is the presigned
        FINALIZER — reached only after a real multipart upload completes, which
        is why it was the one that drifted in #1290 round 8. Each door has to
        bill `dataset.record.created_by`, the nullable column the policy is
        about; a door that resolved the REQUESTER instead would both break the
        owner rule and quietly opt out of the exemption.
        """
        import ast
        import inspect

        from app.modules.catalog.datasets.api import router_reupload
        from app.processing.ingest import presigned

        owner_expr = "dataset.record.created_by"
        billed: list[str] = []
        for node in ast.walk(ast.parse(inspect.getsource(router_reupload))):
            if not isinstance(node, ast.Call):
                continue
            if getattr(node.func, "id", None) == "check_replacement_quota":
                billed.append(ast.unparse(node.args[1]))
            elif getattr(node.func, "attr", None) == "finalize_presigned_object":
                billed.extend(
                    ast.unparse(kw.value) for kw in node.keywords if kw.arg == "user_id"
                )

        assert len(billed) == 3, (
            "expected the two request-time doors plus the completion "
            f"finalizer to bill an identity, found {billed}"
        )
        assert set(billed) == {owner_expr}, (
            f"a replacement admission point bills someone other than the "
            f"dataset owner: {billed}"
        )

        # The finalizer must not re-resolve an identity of its own either: it
        # bills the one the door handed it, nullable and all.
        finalizer_billed = [
            ast.unparse(node.args[1])
            for node in ast.walk(ast.parse(inspect.getsource(presigned)))
            if isinstance(node, ast.Call)
            and getattr(node.func, "id", None) == "check_replacement_quota"
        ]
        assert finalizer_billed == ["user_id"], (
            "the presigned finalizer resolves its own identity instead of "
            f"passing through the owner the door named: {finalizer_billed}"
        )


class TestEveryKeptOriginalIsCounted:
    """The cap's job is bounding a self-hosted operator's storage by policy, so
    every kept original carries its own counted row — not just the newest.
    Counting one would leave the P1's own scenario (repeated distinct lossy
    replacements) accumulating uncounted objects forever."""

    async def test_two_distinct_lossy_replaces_leave_two_counted_rows(
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

        try:
            # fix(#1537 review): inside the cleanup scope, for the same reason
            # as its siblings — the rows are already committed by here and
            # nothing rolls them back if the precondition fires.
            payloads = [_geotiff_bytes(seed=201), _geotiff_bytes(seed=202)]
            assert payloads[0] != payloads[1]

            for i, payload in enumerate(payloads):
                source = tmp_path / f"r{i}" / "scene.tif"
                source.parent.mkdir()
                source.write_bytes(payload)
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

            rows = (
                await test_db_session.execute(
                    text(
                        "SELECT key, size_bytes FROM catalog.dataset_assets "
                        "WHERE dataset_id = :id AND key LIKE 'archived_original:%' "
                        "ORDER BY key"
                    ),
                    {"id": dataset_id},
                )
            ).all()
            assert len(rows) == 2, (
                f"two distinct originals are kept in storage but {len(rows)} "
                "are counted — the superseded one accumulates unbilled"
            )
            assert sorted(r.size_bytes for r in rows) == sorted(
                len(p) for p in payloads
            )

            # Usage reflects BOTH, not just the survivor.
            from app.modules.quota.service import get_user_quota_usage

            usage = await get_user_quota_usage(test_db_session, admin_id)
            assert usage.bytes_used >= sum(len(p) for p in payloads)
        finally:
            await _purge(test_db_session, dataset_id=dataset_id, record_id=record_id)

    async def test_identical_bytes_still_count_once(
        self, test_db_session, raster_storage, tmp_path
    ) -> None:
        """The key is content-derived, so a byte-identical re-upload lands on
        the same row and updates in place. One object, one row, billed once."""
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
        payload = _geotiff_bytes(seed=211)

        try:
            for i in range(2):
                source = tmp_path / f"same{i}" / "scene.tif"
                source.parent.mkdir()
                source.write_bytes(payload)
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

            count = (
                await test_db_session.execute(
                    text(
                        "SELECT count(*) FROM catalog.dataset_assets "
                        "WHERE dataset_id = :id AND key LIKE 'archived_original:%'"
                    ),
                    {"id": dataset_id},
                )
            ).scalar_one()
            assert count == 1, "an identical re-upload was billed twice"
            assert len(await raster_storage.list(f"originals/{dataset_id}/")) == 1
        finally:
            await _purge(test_db_session, dataset_id=dataset_id, record_id=record_id)


# ---------------------------------------------------------------------------
# 12. Round-6 review findings (#1290)
# ---------------------------------------------------------------------------


class TestCreditIsOnlyTheSupersededDataRow:
    """FINDING 1. A replacement supersedes the `data` row and nothing else —
    the archives persist and stay billed. Crediting them too let each
    successive lossy replace reserve roughly nothing while adding another
    permanent object, which is the unbounded growth the counted rows exist to
    stop."""

    async def test_a_second_lossy_replace_is_charged_for_its_own_original(
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

        reserved: list[int] = []

        async def _spy(session, user_id, incoming_bytes):
            reserved.append(incoming_bytes)

        payloads = [_geotiff_bytes(seed=221), _geotiff_bytes(seed=222)]
        try:
            for i, payload in enumerate(payloads):
                source = tmp_path / f"c{i}" / "scene.tif"
                source.parent.mkdir()
                source.write_bytes(payload)
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
                with patch("app.modules.quota.service.reserve_storage_bytes", new=_spy):
                    await reupload_raster.func(
                        job_id=str(job.id),
                        dataset_id=str(dataset_id),
                        file_path=str(source),
                        user_id=str(admin_id),
                        attempt_id=str(job.attempt_id),
                    )

            assert len(reserved) == 2, reserved
            # The second replace supersedes the first COG, so the COG half nets
            # out — but its own original is NEW and must be charged in full.
            # A credit that also subtracted the first original would leave this
            # at or below zero, and the reservation would never fire.
            assert reserved[1] >= len(payloads[1]), (
                f"second replace reserved {reserved[1]} but its kept original "
                f"alone is {len(payloads[1])} bytes — the credit is "
                "subtracting archives a replacement does not supersede "
                "(#1290 round-6 finding 1)"
            )
        finally:
            await _purge(test_db_session, dataset_id=dataset_id, record_id=record_id)

    async def test_the_second_replace_is_refused_when_its_original_will_not_fit(
        self, test_db_session, raster_storage, tmp_path
    ) -> None:
        """The consequence, end to end: a cap that admits the first lossy
        replace must refuse the second, because the second adds a permanent
        object on top of everything the first left behind."""
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
        payloads = [_geotiff_bytes(seed=231), _geotiff_bytes(seed=232)]

        async def _replace(path, payload):
            path.parent.mkdir(exist_ok=True)
            path.write_bytes(payload)
            job = await _queue_replace_job(
                test_db_session,
                dataset_id=dataset_id,
                user_id=admin_id,
                file_path=str(path),
            )
            job.user_metadata = {**(job.user_metadata or {}), "compression": "JPEG"}
            await test_db_session.commit()
            await reupload_raster.func(
                job_id=str(job.id),
                dataset_id=str(dataset_id),
                file_path=str(path),
                user_id=str(admin_id),
                attempt_id=str(job.attempt_id),
            )

        try:
            await _replace(tmp_path / "d0" / "scene.tif", payloads[0])
            test_db_session.expire_all()
            from app.modules.quota.service import get_user_quota_usage

            after_first = await get_user_quota_usage(test_db_session, admin_id)
            # Room for what exists, but not for another kept original.
            cap = after_first.bytes_used + (len(payloads[1]) // 2)

            with patch(
                "app.modules.quota.service.MAX_STORAGE_BYTES_PER_USER.get",
                new_callable=AsyncMock,
                return_value=cap,
            ):
                with pytest.raises(Exception, match="[Ss]torage quota"):
                    await _replace(tmp_path / "d1" / "scene.tif", payloads[1])
        finally:
            await _purge(test_db_session, dataset_id=dataset_id, record_id=record_id)


class TestBothTailsReserveBeforeTheyUpsert:
    """FINDING 2. The reservation adds its argument to a LIVE recount, so it
    has to run before the row it is about to write exists — otherwise the
    recount already holds those bytes and they are charged twice."""

    def test_both_tails_reserve_before_they_upsert(self) -> None:
        """Structural, because the ordering is invisible to any single-tail
        behaviour test that happens to sit below the cap. This is the pin the
        drift class has earned: the swap module states the rule in a docstring
        and the other tail broke it anyway."""
        import ast
        import inspect

        from app.processing.ingest import tasks_raster, tasks_raster_replace

        for module, task_name, reserve_names in (
            (tasks_raster, "ingest_raster", {"reserve_storage_bytes"}),
            (
                tasks_raster_replace,
                "reupload_raster",
                {"reserve_replacement_bytes"},
            ),
        ):
            tree = ast.parse(inspect.getsource(module))
            task = next(
                node
                for node in ast.walk(tree)
                if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef))
                and node.name == task_name
            )
            reserve_lines = [
                node.lineno
                for node in ast.walk(task)
                if isinstance(node, ast.Call)
                and getattr(node.func, "id", None) in reserve_names
            ]
            upsert_lines = [
                node.lineno
                for node in ast.walk(task)
                if isinstance(node, ast.Call)
                and getattr(node.func, "id", None)
                in {"upsert_archived_original_row", "_upsert_managed_asset_rows"}
            ]
            assert reserve_lines, f"{task_name} never reserves"
            assert upsert_lines, f"{task_name} never upserts an asset row"
            assert max(reserve_lines) < min(upsert_lines), (
                f"{task_name} reserves at line {max(reserve_lines)} but upserts "
                f"from {min(upsert_lines)} — the reservation must precede every "
                "asset-row write or the live recount double-counts it "
                "(#1290 round-6 finding 2)"
            )


class TestArchiveKeyIsDerivedFromContentAlone:
    """Round 6 normalized the filename inside the key; round 8 removed the
    filename from the key entirely, which is the stronger form of the same
    property — there is no longer an input that could need normalizing."""

    def test_the_key_ignores_the_filename_completely(self) -> None:
        from app.processing.ingest.tasks_raster_swap import archived_original_uri

        from app.processing.ingest.tasks_raster_swap import ARCHIVE_HASH_CHARS

        key = archived_original_uri("ds-1", source_sha256="a" * 64)
        assert key == "originals/ds-1/" + "a" * ARCHIVE_HASH_CHARS
        # No extension either: the same bytes as .tif and .tiff must not become
        # two objects (#1290 round-8 finding 1).
        assert "." not in key.rsplit("/", 1)[-1]

    def test_the_upload_paths_normalization_still_exists_for_staging(self) -> None:
        """`safe_upload_basename` lost a consumer rather than gaining one — the
        archive no longer touches filenames — but the staging path still needs
        it, so it stays and stays tested."""
        from app.processing.ingest.service import safe_upload_basename

        assert safe_upload_basename("folder/scene.tif") == "scene.tif"
        assert safe_upload_basename("../../etc/passwd") == "passwd"
        assert safe_upload_basename(None) == "upload"

    async def test_a_nested_filename_archives_where_the_row_says_it_did(
        self, test_db_session, raster_storage, tmp_path
    ) -> None:
        """The consequence: the counted row must name an object that exists,
        and cleanup must see the same key."""
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

        source = tmp_path / "scene.tif"
        source.write_bytes(_geotiff_bytes(seed=241))
        job = await _queue_replace_job(
            test_db_session,
            dataset_id=dataset_id,
            user_id=admin_id,
            file_path=str(source),
        )
        # What a client can send: a filename carrying a directory component.
        job.source_filename = "folder/scene.tif"
        job.user_metadata = {**(job.user_metadata or {}), "compression": "JPEG"}
        await test_db_session.commit()

        try:
            await reupload_raster.func(
                job_id=str(job.id),
                dataset_id=str(dataset_id),
                file_path=str(source),
                user_id=str(admin_id),
                attempt_id=str(job.attempt_id),
            )

            href = (
                await test_db_session.execute(
                    text(
                        "SELECT href FROM catalog.dataset_assets "
                        "WHERE dataset_id = :id AND key LIKE 'archived_original:%'"
                    ),
                    {"id": dataset_id},
                )
            ).scalar_one()
            assert await raster_storage.exists(href), (
                f"the counted row points at {href}, which does not exist"
            )
            assert "folder" not in href
            assert "scene" not in href, (
                "the filename leaked into object identity (#1290 round-8 finding 1)"
            )
        finally:
            await _purge(test_db_session, dataset_id=dataset_id, record_id=record_id)


# ---------------------------------------------------------------------------
# 13. Round-7 review findings (#1290)
# ---------------------------------------------------------------------------


class TestInternalAssetKeysNeverReachAnyResponse:
    """FINDING 1. The allowlist guarded the search/STAC serializer only, so
    `GET /datasets/{id}` — which builds its assets straight off the ORM rows —
    leaked the archived original's href, filename and size to any viewer of a
    public dataset. Enumerate the paths, then one boundary they all cross."""

    async def test_dataset_detail_hides_the_archived_original(
        self, client, admin_auth_header, test_db_session, raster_storage
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
        await test_db_session.execute(
            text(
                "INSERT INTO catalog.dataset_assets "
                "(dataset_id, key, href, size_bytes, media_type, title) VALUES "
                "(:id, 'data', 'rasters/x/y/source.cog.tif', 10, 'image/tiff', 'COG'), "
                "(:id, 'archived_original:a1b2c3d4e5f60718293a4b5c6d7e8f90', "
                "'originals/x/a1b2c3d4e5f60718293a4b5c6d7e8f90', 99, 'image/tiff', "
                "'Pre-conversion original')"
            ),
            {"id": dataset_id},
        )
        await test_db_session.commit()

        try:
            resp = await client.get(
                f"/datasets/{dataset_id}", headers=admin_auth_header
            )
            assert resp.status_code == 200, resp.text
            body = resp.text
            assets = resp.json().get("stac_assets") or {}

            leaked = [k for k in assets if k.startswith("archived_original")]
            assert leaked == [], (
                f"GET /datasets/{{id}} published internal asset keys {leaked} "
                "(#1290 round-7 finding 1)"
            )
            # The filename is the part that leaks something about the owner
            # even if the href is unresolvable.
            assert "private-survey.tif" not in body
            assert "data" in assets, "the public asset must still be served"
        finally:
            await _purge(test_db_session, dataset_id=dataset_id, record_id=record_id)

    def test_every_dataset_asset_consumer_crosses_the_boundary(self) -> None:
        """The structural pin, because three paths exist and a fourth is a
        normal thing to add. Any module that fetches DatasetAsset rows must
        either apply the allowlist itself or delegate to the one builder that
        does — nothing may iterate rows into a payload on its own terms."""
        import ast
        from pathlib import Path as _P

        root = _P("app")
        offenders = []
        for path in root.rglob("*.py"):
            src = path.read_text()
            if "get_dataset_assets" not in src and "list_dataset_assets" not in src:
                continue
            # The port itself and its default implementation are the fetch
            # seam, not a serialization path.
            if path.name in {"catalog_port.py", "defaults_catalog_port.py"}:
                continue
            names = {
                node.id
                for node in ast.walk(ast.parse(src))
                if isinstance(node, ast.Name)
            } | {
                node.attr
                for node in ast.walk(ast.parse(src))
                if isinstance(node, ast.Attribute)
            }
            # `build_assets` is the public facade over `_build_stac_assets` and
            # is how a module outside search/ names the delegation — it hands
            # `stac_asset_rows` straight to the private builder and consumes
            # them nowhere else. refactor(stac): the STAC router reached this
            # gate only once its DatasetAsset fetch moved onto the port; before
            # that it hand-rolled `select(DatasetAsset)` and matched neither
            # fetch name, so the guard never looked at it. That blind spot —
            # fetching without naming the seam — is what the docstring above
            # calls "a fourth is a normal thing to add".
            if not names & {
                "is_public_asset_key",
                "_build_stac_assets",
                "build_assets",
            }:
                offenders.append(str(path))
        assert offenders == [], (
            "these modules turn dataset_assets rows into payloads without "
            f"crossing the public-key boundary: {offenders} — add the filter or "
            "route through _build_stac_assets (#1290 round-7 finding 1)"
        )

    def test_the_allowlist_lives_in_one_place(self) -> None:
        from app.platform.assets.keys import PUBLIC_ASSET_KEYS, is_public_asset_key

        assert is_public_asset_key("data") is True
        assert (
            is_public_asset_key("archived_original:a1b2c3d4e5f60718293a4b5c6d7e8f90")
            is False
        )
        assert is_public_asset_key(None) is False
        assert not any(k.startswith("archived_original") for k in PUBLIC_ASSET_KEYS)


class TestIndeterminateProbeNeverArmsTheReap:
    """FINDING 2. Treating a transient `exists()` error as "did not exist" put
    the archive key into the failure-reap set, so a later swap failure deleted
    an archive belonging to an EARLIER SUCCESSFUL replacement."""

    async def test_a_probe_failure_does_not_make_an_archive_reapable(
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
        payload = _geotiff_bytes(seed=251)

        try:
            # 1. A successful lossy replace archives these bytes.
            first = tmp_path / "p1" / "scene.tif"
            first.parent.mkdir()
            first.write_bytes(payload)
            job = await _queue_replace_job(
                test_db_session,
                dataset_id=dataset_id,
                user_id=admin_id,
                file_path=str(first),
            )
            job.user_metadata = {**(job.user_metadata or {}), "compression": "JPEG"}
            await test_db_session.commit()
            await reupload_raster.func(
                job_id=str(job.id),
                dataset_id=str(dataset_id),
                file_path=str(first),
                user_id=str(admin_id),
                attempt_id=str(job.attempt_id),
            )
            kept = await raster_storage.list(f"originals/{dataset_id}/")
            assert len(kept) == 1
            good_key = kept[0]

            # 2. A second attempt with the SAME bytes, whose existence probe
            #    blows up and whose swap then fails.
            second = tmp_path / "p2" / "scene.tif"
            second.parent.mkdir()
            second.write_bytes(payload)
            job2 = await _queue_replace_job(
                test_db_session,
                dataset_id=dataset_id,
                user_id=admin_id,
                file_path=str(second),
            )
            job2.user_metadata = {
                **(job2.user_metadata or {}),
                "compression": "JPEG",
            }
            await test_db_session.commit()

            real_exists = raster_storage.exists

            async def _flaky_exists(key):
                if "originals/" in key:
                    raise RuntimeError("object store had a moment")
                return await real_exists(key)

            monkeypatch.setattr(raster_storage, "exists", _flaky_exists)

            async def _die(*args, **kwargs):
                raise RuntimeError("swap died after the archive")

            monkeypatch.setattr(
                "app.processing.ingest.tasks_raster_replace.record_refresh_success",
                _die,
                raising=True,
            )
            with pytest.raises(RuntimeError, match="died after the archive"):
                await reupload_raster.func(
                    job_id=str(job2.id),
                    dataset_id=str(dataset_id),
                    file_path=str(second),
                    user_id=str(admin_id),
                    attempt_id=str(job2.attempt_id),
                )

            monkeypatch.setattr(raster_storage, "exists", real_exists)
            assert await raster_storage.exists(good_key), (
                "an indeterminate exists() probe armed the failure reap and it "
                "deleted the archive of an earlier SUCCESSFUL replacement — the "
                "last faithful original of a raster still being served "
                "(#1290 round-7 finding 2)"
            )
            assert await raster_storage.get(good_key) == payload
        finally:
            await _purge(test_db_session, dataset_id=dataset_id, record_id=record_id)


# ---------------------------------------------------------------------------
# 14. Round-8 review findings (#1290)
# ---------------------------------------------------------------------------


class TestArchiveIdentityIsContentOnly:
    """FINDING 1. The counted row keyed on content while the object keyed on
    content AND filename, so the two answered "same archive?" differently. Same
    bytes under two names produced one row and two objects: the reservation
    credited the row and charged nothing, the upsert repointed it at the newer
    object, and the older one was orphaned and uncounted — unbounded storage
    past the cap, one rename at a time."""

    async def test_same_bytes_two_filenames_is_one_object_and_one_charge(
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
        payload = _geotiff_bytes(seed=261)

        reserved: list[int] = []

        async def _spy(session, user_id, incoming_bytes):
            reserved.append(incoming_bytes)

        try:
            for name in ("survey-a.tif", "survey-b.tif"):
                source = tmp_path / name
                source.write_bytes(payload)
                job = await _queue_replace_job(
                    test_db_session,
                    dataset_id=dataset_id,
                    user_id=admin_id,
                    file_path=str(source),
                )
                job.source_filename = name
                job.user_metadata = {
                    **(job.user_metadata or {}),
                    "compression": "JPEG",
                }
                await test_db_session.commit()
                with patch("app.modules.quota.service.reserve_storage_bytes", new=_spy):
                    await reupload_raster.func(
                        job_id=str(job.id),
                        dataset_id=str(dataset_id),
                        file_path=str(source),
                        user_id=str(admin_id),
                        attempt_id=str(job.attempt_id),
                    )

            objects = await _archived_originals(raster_storage, dataset_id)
            assert len(objects) == 1, (
                f"identical bytes under two names produced {len(objects)} "
                "objects — the second is orphaned and uncounted "
                "(#1290 round-8 finding 1)"
            )
            rows = (
                await test_db_session.execute(
                    text(
                        "SELECT count(*) FROM catalog.dataset_assets "
                        "WHERE dataset_id = :id AND key LIKE 'archived_original:%'"
                    ),
                    {"id": dataset_id},
                )
            ).scalar_one()
            assert rows == 1, "one archive, one row"

            # Identical bytes reserve NOTHING the second time: same COG hash,
            # same archive key, same sizes, so the delta is zero and the
            # reservation never fires. One call, from the first replace.
            assert len(reserved) == 1, (
                f"reservations {reserved} — the second replace charged for "
                "bytes already billed, which is the identity split showing up "
                "in the arithmetic"
            )
        finally:
            await _purge(test_db_session, dataset_id=dataset_id, record_id=record_id)

    def test_extension_cannot_split_identity_either(self) -> None:
        """`.tif` and `.tiff` over the same bytes would be the same bug with a
        smaller blast radius, which is the worst kind to leave in."""
        from app.processing.ingest.tasks_raster_swap import archived_original_uri

        assert archived_original_uri(
            "ds-1", source_sha256="b" * 64
        ) == archived_original_uri("ds-1", source_sha256="b" * 64)
        assert archived_original_uri("ds-1", source_sha256="b" * 64).endswith(
            "bbbbbbbbbbbb"
        )

    def test_the_operator_can_still_read_the_uploaded_name(self) -> None:
        """Removing the filename from identity must not lose it. It moves to
        the counted row, which is internal, so an operator can read it and no
        equality depends on it."""
        import ast
        import inspect

        from app.processing.ingest import tasks_raster_swap

        src = inspect.getsource(tasks_raster_swap)
        fn = next(
            n
            for n in ast.walk(ast.parse(src))
            if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef))
            and n.name == "upsert_archived_original_row"
        )
        keys = {
            k.value
            for node in ast.walk(fn)
            if isinstance(node, ast.Dict)
            for k in node.keys
            if isinstance(k, ast.Constant)
        }
        assert "description" in keys, (
            "the uploaded filename has nowhere to live now that the key is "
            "content-only (#1290 round-8 finding 1)"
        )


class TestCompletionAdmitsReplacementsAsReplacements:
    """FINDING 2. Completion is the third admission point and it was still
    creation-shaped, so an owner at the dataset-count cap passed the
    request-time door, uploaded the bytes, and was refused at the finalizer."""

    async def test_presigned_completion_admits_an_owner_at_the_dataset_cap(
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
        dataset_id = live.dataset.id
        record_id = live.dataset.record_id

        monkeypatch.setattr(settings, "storage_provider", "s3")
        monkeypatch.setattr(
            "app.modules.catalog.datasets.api.router_reupload.get_storage",
            lambda: raster_storage,
            raising=False,
        )
        # The local provider refuses to presign; the flow under test is the
        # ADMISSION at completion, not the signing, so a stub URL is enough.
        monkeypatch.setattr(
            raster_storage,
            "generate_presigned_put_url",
            lambda key, content_type, expiration=3600: f"https://s3.invalid/{key}",
            raising=False,
        )
        payload = _geotiff_bytes(seed=271)

        try:
            with patch(
                "app.modules.quota.service.MAX_DATASETS_PER_USER.get",
                new_callable=AsyncMock,
                return_value=1,
            ):
                resp = await client.post(
                    f"/datasets/{dataset_id}/reupload/presigned",
                    json={
                        "filename": "replacement.tif",
                        "file_size": len(payload),
                        "content_type": "image/tiff",
                    },
                    headers=admin_auth_header,
                )
                assert resp.status_code == 201, resp.text
                body = resp.json()
                await raster_storage.put(body["s3_key"], io.BytesIO(payload))

                done = await client.post(
                    f"/datasets/{dataset_id}/reupload/presigned/"
                    f"{body['job_id']}/complete",
                    json={},
                    headers=admin_auth_header,
                )
            assert done.status_code == 200, (
                "the request-time door admitted the replacement and the "
                "FINALIZER refused it on the dataset-count cap — the bytes are "
                "already uploaded at that point (#1290 round-8 finding 2): "
                f"{done.status_code} {done.text}"
            )
        finally:
            await test_db_session.execute(
                delete(IngestJob).where(IngestJob.dataset_id == dataset_id)
            )
            await test_db_session.commit()
            await _purge(test_db_session, dataset_id=dataset_id, record_id=record_id)

    def test_no_admission_point_in_a_reupload_flow_is_creation_shaped(self) -> None:
        """The round-3 parity pin walked reupload HANDLERS only, so the
        finalizer sat outside it. Widened to the whole reachable flow: the
        reupload router and the presigned module it delegates completion to.
        Either may call the creation check ONLY behind a branch that also
        offers the replacement one."""
        import ast
        import inspect

        from app.modules.catalog.datasets.api import router_reupload
        from app.processing.ingest import presigned

        # The router must never reach the creation-shaped check at all.
        router_names = {
            node.func.id
            for node in ast.walk(ast.parse(inspect.getsource(router_reupload)))
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        assert "check_upload_quota" not in router_names
        assert "check_replacement_quota" in router_names

        # The finalizer is shared with the create-upload door, so it may keep
        # the creation check — but it must ALSO be able to admit a replacement,
        # and the reupload door must be able to say which it is.
        presigned_src = inspect.getsource(presigned)
        assert "check_replacement_quota" in presigned_src, (
            "the presigned finalizer cannot admit a replacement, so completion "
            "refuses what the door already accepted (#1290 round-8 finding 2)"
        )
        assert "replacing_dataset_id" in presigned_src
        assert "replacing_dataset_id" in inspect.getsource(router_reupload), (
            "the reupload door does not tell the finalizer this is a replacement"
        )


# ---------------------------------------------------------------------------
# 15. Round-9 review finding (#1290)
# ---------------------------------------------------------------------------


class TestVrtStampNamesTheStateItWasBuiltFrom:
    """FINDING. `regenerate_vrt` snapshots member paths, builds (real GDAL
    time), then stamped `last_regenerated_at` at PUBLISH time. A member
    replacement committing inside that window left the stored VRT referencing a
    COG the replacement then reaped — and because the publish-time stamp
    POSTDATES the member's `ingested_at`, the health endpoint reported the
    broken parent as `healthy`. The stale mechanism vouching for exactly the
    state it exists to surface.

    Stamping the snapshot instant collapses the race into the already-handled
    stale case. These tests pin that the stamp names the state the artifact was
    built FROM, and that the health verdict follows.
    """

    async def test_the_stamp_predates_the_build_it_describes(
        self, test_db_session, raster_storage, monkeypatch
    ) -> None:
        """The property, measured. If the stamp is snapshot-time it lands
        BEFORE the build finished; if it is publish-time it lands after. A
        deliberately slow build separates the two instants."""
        import asyncio as _asyncio
        from datetime import datetime, timezone

        from app.processing.ingest import tasks_vrt

        admin_id = (
            await test_db_session.execute(
                select(User.id).where(User.username == "admin")
            )
        ).scalar_one()
        member = await _make_live_raster(
            test_db_session, raster_storage, created_by=admin_id
        )
        parent = await _make_vrt_parent(
            test_db_session, raster_storage, created_by=admin_id, member=member
        )
        # Captured before any expire_all(): reading them off an expired ORM
        # instance lazy-loads, which under AnyIO is MissingGreenlet.
        ids = (
            parent.dataset.id,
            parent.dataset.record_id,
            member.dataset.id,
            member.dataset.record_id,
        )
        build_finished: list[datetime] = []
        real_build = tasks_vrt.build_vrt

        def _slow_build(vrt_type, source_paths, vrt_path, resolution_strategy):
            import time

            time.sleep(0.35)
            result = real_build(vrt_type, source_paths, vrt_path, resolution_strategy)
            build_finished.append(datetime.now(timezone.utc))
            return result

        monkeypatch.setattr(tasks_vrt, "build_vrt", _slow_build, raising=True)

        try:
            await _run_regeneration(test_db_session, parent=parent, user_id=admin_id)
            await _asyncio.sleep(0)
            test_db_session.expire_all()
            stamped = (
                await test_db_session.execute(
                    text(
                        "SELECT last_regenerated_at FROM catalog.raster_assets "
                        "WHERE dataset_id = :id"
                    ),
                    {"id": ids[0]},
                )
            ).scalar_one()

            assert build_finished, "the patched build never ran"
            assert stamped < build_finished[0], (
                f"last_regenerated_at ({stamped}) postdates the build that "
                f"finished at {build_finished[0]} — it names when the write "
                "happened, not the state the VRT was built from, so a member "
                "replaced during the build is masked as healthy "
                "(#1290 round-9 finding)"
            )
        finally:
            await _purge_vrt(test_db_session, ids=ids)

    async def test_a_member_replaced_during_the_build_reads_stale(
        self, client, admin_auth_header, test_db_session, raster_storage, monkeypatch
    ) -> None:
        """The consequence at the health endpoint, which is the discriminator.

        The member's `ingested_at` is placed INSIDE the build window — exactly
        where a replacement committing mid-build would put it. With a
        snapshot-time stamp the parent reports `stale`; with a publish-time
        stamp it reports `healthy` and vouches for a VRT whose source object
        has been reaped.
        """
        from datetime import datetime, timezone

        from app.processing.ingest import tasks_vrt

        admin_id = (
            await test_db_session.execute(
                select(User.id).where(User.username == "admin")
            )
        ).scalar_one()
        member = await _make_live_raster(
            test_db_session, raster_storage, created_by=admin_id
        )
        parent = await _make_vrt_parent(
            test_db_session, raster_storage, created_by=admin_id, member=member
        )
        # Captured before any expire_all(): reading them off an expired ORM
        # instance lazy-loads, which under AnyIO is MissingGreenlet.
        ids = (
            parent.dataset.id,
            parent.dataset.record_id,
            member.dataset.id,
            member.dataset.record_id,
        )
        mid_build: list[datetime] = []
        real_build = tasks_vrt.build_vrt

        def _slow_build(vrt_type, source_paths, vrt_path, resolution_strategy):
            import time

            time.sleep(0.2)
            mid_build.append(datetime.now(timezone.utc))
            time.sleep(0.2)
            return real_build(vrt_type, source_paths, vrt_path, resolution_strategy)

        monkeypatch.setattr(tasks_vrt, "build_vrt", _slow_build, raising=True)

        try:
            await _run_regeneration(test_db_session, parent=parent, user_id=admin_id)
            # The replacement committed mid-build: its ingested_at lands in the
            # window between the snapshot and the publish.
            await test_db_session.execute(
                text(
                    "UPDATE catalog.raster_assets "
                    "SET asset_uri = :uri, ingested_at = :ts "
                    "WHERE dataset_id = :id"
                ),
                {
                    "uri": "rasters/replaced/newsha/source.cog.tif",
                    "ts": mid_build[0],
                    "id": ids[2],
                },
            )
            # The replacement's new COG exists — the member itself is fine.
            # What is broken is the PARENT, whose stored VRT still names the
            # superseded object, and that is what `stale` has to say.
            await raster_storage.put(
                "rasters/replaced/newsha/source.cog.tif", io.BytesIO(b"new")
            )
            await test_db_session.commit()

            resp = await client.get(
                f"/datasets/{ids[0]}/vrt/status/",
                headers=admin_auth_header,
            )
            assert resp.status_code == 200, resp.text
            statuses = [s["status"] for s in resp.json()["source_health"]]
            assert statuses == ["stale"], (
                f"the parent reports {statuses} for a member replaced DURING "
                "its build — the stored VRT references a COG the replacement "
                "reaped, and the health endpoint is vouching for it "
                "(#1290 round-9 finding)"
            )
        finally:
            await _purge_vrt(test_db_session, ids=ids)


# ---------------------------------------------------------------------------
# 16. Round-10 review findings (#1290)
# ---------------------------------------------------------------------------


class TestSnapshotPrecedesTheReadInBothTails:
    """FINDINGS 1 and 2. Round 9 got the stamp's MEANING right and its position
    wrong, and only fixed one tail. Both tails read their members through one
    helper that stamps first, so the ordering cannot drift per-tail."""

    async def test_the_stamp_predates_the_member_read_on_regenerate(
        self, test_db_session, raster_storage, monkeypatch
    ) -> None:
        """FINDING 2. The stamp sat AFTER the member query, so a replacement
        committing in the read→stamp interval left the old URI in the build set
        while `ingested_at` landed EARLIER than the stamp — still healthy,
        still vouching for a broken parent."""
        from app.processing.ingest import tasks_vrt

        admin_id = (
            await test_db_session.execute(
                select(User.id).where(User.username == "admin")
            )
        ).scalar_one()
        member = await _make_live_raster(
            test_db_session, raster_storage, created_by=admin_id
        )
        parent = await _make_vrt_parent(
            test_db_session, raster_storage, created_by=admin_id, member=member
        )
        ids = (
            parent.dataset.id,
            parent.dataset.record_id,
            member.dataset.id,
            member.dataset.record_id,
        )
        read_at: list[datetime] = []
        real_snapshot = tasks_vrt.snapshot_member_sources

        async def _observed(session, dataset_ids, **kw):
            stamp, assets = await real_snapshot(session, dataset_ids, **kw)
            read_at.append(datetime.now(timezone.utc))
            return stamp, assets

        monkeypatch.setattr(
            tasks_vrt, "snapshot_member_sources", _observed, raising=True
        )

        try:
            await _run_regeneration(test_db_session, parent=parent, user_id=admin_id)
            test_db_session.expire_all()
            stamped = (
                await test_db_session.execute(
                    text(
                        "SELECT last_regenerated_at FROM catalog.raster_assets "
                        "WHERE dataset_id = :id"
                    ),
                    {"id": ids[0]},
                )
            ).scalar_one()
            assert read_at, "the member read never ran"
            assert stamped < read_at[0], (
                f"last_regenerated_at ({stamped}) is not earlier than the "
                f"member read ({read_at[0]}) — a replacement committing in "
                "that interval leaves the old URI in the build set while its "
                "ingested_at predates the stamp, and the parent still reports "
                "healthy (#1290 round-10 finding 2)"
            )
        finally:
            await _purge_vrt(test_db_session, ids=ids)

    async def test_a_member_replaced_during_the_initial_build_reads_stale(
        self, client, admin_auth_header, test_db_session, raster_storage, monkeypatch
    ) -> None:
        """FINDING 1. The creation tail had no snapshot at all, so a member
        replaced during the FIRST build was masked the same way — the status
        comparison falls back to the parent's `ingested_at`, stamped at
        publish."""
        from app.processing.ingest import tasks_vrt

        admin_id = (
            await test_db_session.execute(
                select(User.id).where(User.username == "admin")
            )
        ).scalar_one()
        member = await _make_live_raster(
            test_db_session, raster_storage, created_by=admin_id
        )
        mid_build: list[datetime] = []
        real_build = tasks_vrt.build_vrt

        def _slow_build(vrt_type, source_paths, vrt_path, resolution_strategy):
            import time

            time.sleep(0.2)
            mid_build.append(datetime.now(timezone.utc))
            time.sleep(0.2)
            return real_build(vrt_type, source_paths, vrt_path, resolution_strategy)

        monkeypatch.setattr(tasks_vrt, "build_vrt", _slow_build, raising=True)

        parent_ids = await _run_vrt_creation(
            test_db_session, raster_storage, member=member, user_id=admin_id
        )
        ids = (
            parent_ids[0],
            parent_ids[1],
            member.dataset.id,
            member.dataset.record_id,
        )
        try:
            # The replacement committed mid-build.
            await test_db_session.execute(
                text(
                    "UPDATE catalog.raster_assets "
                    "SET asset_uri = :uri, ingested_at = :ts "
                    "WHERE dataset_id = :id"
                ),
                {
                    "uri": "rasters/replaced/newsha/source.cog.tif",
                    "ts": mid_build[0],
                    "id": ids[2],
                },
            )
            # The replacement's new COG exists — the member itself is fine.
            # What is broken is the PARENT, whose stored VRT still names the
            # superseded object, and that is what `stale` has to say.
            await raster_storage.put(
                "rasters/replaced/newsha/source.cog.tif", io.BytesIO(b"new")
            )
            await test_db_session.commit()

            resp = await client.get(
                f"/datasets/{ids[0]}/vrt/status/", headers=admin_auth_header
            )
            assert resp.status_code == 200, resp.text
            statuses = [s["status"] for s in resp.json()["source_health"]]
            assert statuses == ["stale"], (
                f"a freshly CREATED VRT reports {statuses} for a member "
                "replaced during its first build — the creation tail records "
                "no snapshot instant, so the comparison falls back to a "
                "publish-time stamp (#1290 round-10 finding 1)"
            )
        finally:
            await _purge_vrt(test_db_session, ids=ids)

    def test_both_tails_read_members_through_the_one_helper(self) -> None:
        """Secondary to the discriminators, but cheap: neither tail may issue
        its own member query, because that is how the ordering drifted."""
        import ast
        import inspect

        from app.processing.ingest import tasks_vrt

        tree = ast.parse(inspect.getsource(tasks_vrt))
        for task_name in ("ingest_vrt", "regenerate_vrt"):
            fn = next(
                n
                for n in ast.walk(tree)
                if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef))
                and n.name == task_name
            )
            names = {
                n.func.id
                for n in ast.walk(fn)
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
            }
            assert "snapshot_member_sources" in names, (
                f"{task_name} does not read its members through the shared "
                "helper, so its stamp ordering is its own to get wrong "
                "(#1290 round-10)"
            )


class TestArchiveIdentityIsWideEnoughToBeAnIdentity:
    """Round 8 made the truncated hash BE the archive's identity, which is what
    put the truncation width on the security boundary. A deliberate collision
    at 48 bits is a ~2^24 birthday search — minutes on a laptop — and it buys
    the attacker exactly the invariant the key protects: the later archive
    overwrites the earlier object's only faithful original, both collapse into
    one row, and a failed later swap leaves the live raster with its retained
    source already gone."""

    def test_digests_sharing_a_12_char_prefix_get_distinct_identities(self) -> None:
        """The discriminator, stated exactly rather than searched for.

        Both derivations take the digest as a parameter, so the collision the
        old width admitted can be written down directly — a brute-force pair
        would only re-derive what the parameter already lets us say, at the
        cost of ~2^25 hashes and a multi-GB table. The 48-bit prefix is shared;
        everything after it differs.
        """
        from app.processing.ingest.tasks_raster_swap import (
            archived_original_asset_key,
            archived_original_uri,
        )

        a = "abc123def456" + "0" * 52
        b = "abc123def456" + "f" * 52
        assert a[:12] == b[:12] and a != b

        assert archived_original_asset_key(a) != archived_original_asset_key(b), (
            "two different uploads share one accounting row — the later "
            "archive's upsert collapses both and the earlier original is "
            "orphaned (#1290 round-11 finding 1)"
        )
        assert archived_original_uri("ds-1", source_sha256=a) != archived_original_uri(
            "ds-1", source_sha256=b
        ), (
            "two different uploads share one object key — the later archive "
            "overwrites the earlier one's only faithful original"
        )

    def test_the_asset_key_fits_the_column_exactly(self) -> None:
        """18-char prefix + 32-char hash = 50, which is the column. Asserted
        against the model rather than a remembered number, so widening the hash
        again fails here instead of at an INSERT in production."""
        from app.processing.ingest.tasks_raster_swap import (
            ARCHIVE_HASH_CHARS,
            ARCHIVED_ORIGINAL_KEY_PREFIX,
            archived_original_asset_key,
        )
        from app.processing.raster.models import DatasetAsset

        limit = DatasetAsset.__table__.c.key.type.length
        assert len(ARCHIVED_ORIGINAL_KEY_PREFIX) + ARCHIVE_HASH_CHARS <= limit, (
            f"the archive asset key is longer than the {limit}-char column"
        )
        assert len(archived_original_asset_key("a" * 64)) <= limit

    def test_both_derivations_share_one_width(self) -> None:
        """Two widths would be two identities again, which is the thing round 8
        removed."""
        from app.processing.ingest.tasks_raster_swap import (
            ARCHIVE_HASH_CHARS,
            ARCHIVED_ORIGINAL_KEY_PREFIX,
            archived_original_asset_key,
            archived_original_uri,
        )

        digest = "9" * 64
        row_suffix = archived_original_asset_key(digest).removeprefix(
            ARCHIVED_ORIGINAL_KEY_PREFIX
        )
        object_suffix = archived_original_uri("ds-1", source_sha256=digest).rsplit(
            "/", 1
        )[-1]
        assert row_suffix == object_suffix
        assert len(row_suffix) == ARCHIVE_HASH_CHARS


class TestStalenessIsStateNotTime:
    """ROUND 12 FINDING 1. The interleaving no clock can answer: a replacement
    assigns `ingested_at` at T1 inside its transaction and commits at T2; a
    rebuild snapshotting at T_s with T1 < T_s < T2 cannot see the uncommitted
    swap under read-committed, so it builds from the OLD uri — and afterwards
    the member's stamp PRECEDES the parent's, so every timestamp scheme reports
    healthy. Postgres exposes no commit-time stamp from inside a transaction
    (`now()` is txn start, `clock_timestamp()` is statement time), so this is
    not a tuning problem.
    """

    async def test_a_commit_after_the_snapshot_still_reads_stale(
        self, client, admin_auth_header, test_db_session, raster_storage
    ) -> None:
        """Simulated at the visibility layer rather than with two live
        sessions: what the build READ is the old uri (the parent's built_from
        records it), while the member's committed uri is the new one and its
        `ingested_at` is EARLIER than the parent's stamp — the exact
        post-commit state codex's interleaving produces. A timestamp comparison
        calls this healthy; a state comparison cannot.
        """
        admin_id = (
            await test_db_session.execute(
                select(User.id).where(User.username == "admin")
            )
        ).scalar_one()
        member = await _make_live_raster(
            test_db_session, raster_storage, created_by=admin_id
        )
        parent = await _make_vrt_parent(
            test_db_session, raster_storage, created_by=admin_id, member=member
        )
        ids = (
            parent.dataset.id,
            parent.dataset.record_id,
            member.dataset.id,
            member.dataset.record_id,
        )
        old_uri = member.asset.asset_uri
        new_uri = "rasters/replaced/committed-late/source.cog.tif"
        await raster_storage.put(new_uri, io.BytesIO(b"replacement"))

        try:
            # The parent was built from the OLD uri, and its stamp is LATER
            # than the member's — the shape a late commit leaves behind.
            await test_db_session.execute(
                text(
                    "UPDATE catalog.raster_assets SET built_from = CAST(:bf AS jsonb), "
                    "last_regenerated_at = now() WHERE dataset_id = :id"
                ),
                {"bf": _json.dumps({str(ids[2]): old_uri}), "id": ids[0]},
            )
            await test_db_session.execute(
                text(
                    "UPDATE catalog.raster_assets SET asset_uri = :uri, "
                    "ingested_at = now() - interval '1 hour' WHERE dataset_id = :id"
                ),
                {"uri": new_uri, "id": ids[2]},
            )
            await test_db_session.commit()

            resp = await client.get(
                f"/datasets/{ids[0]}/vrt/status/", headers=admin_auth_header
            )
            assert resp.status_code == 200, resp.text
            statuses = [s["status"] for s in resp.json()["source_health"]]
            assert statuses == ["stale"], (
                f"the parent reports {statuses} for a member whose committed "
                "uri differs from what the VRT was built from, but whose "
                "ingested_at predates the parent's stamp — no clock can catch "
                "this, which is why staleness is a state comparison "
                "(#1290 round-12 finding 1)"
            )
        finally:
            await _purge_vrt(test_db_session, ids=ids)

    async def test_a_legacy_vrt_without_built_from_falls_back_to_timestamps(
        self, client, admin_auth_header, test_db_session, raster_storage
    ) -> None:
        """NULL means "built before this column existed". Those rows keep the
        legacy comparison — it is the best answer available for an artifact
        that never recorded its inputs, and it is what every pre-existing VRT
        has."""
        admin_id = (
            await test_db_session.execute(
                select(User.id).where(User.username == "admin")
            )
        ).scalar_one()
        member = await _make_live_raster(
            test_db_session, raster_storage, created_by=admin_id
        )
        parent = await _make_vrt_parent(
            test_db_session, raster_storage, created_by=admin_id, member=member
        )
        ids = (
            parent.dataset.id,
            parent.dataset.record_id,
            member.dataset.id,
            member.dataset.record_id,
        )
        try:
            await test_db_session.execute(
                text(
                    "UPDATE catalog.raster_assets SET built_from = NULL, "
                    "last_regenerated_at = now() - interval '1 hour' "
                    "WHERE dataset_id = :id"
                ),
                {"id": ids[0]},
            )
            await test_db_session.execute(
                text(
                    "UPDATE catalog.raster_assets SET ingested_at = now() "
                    "WHERE dataset_id = :id"
                ),
                {"id": ids[2]},
            )
            await test_db_session.commit()

            resp = await client.get(
                f"/datasets/{ids[0]}/vrt/status/", headers=admin_auth_header
            )
            assert [s["status"] for s in resp.json()["source_health"]] == ["stale"], (
                "a legacy VRT lost its staleness signal when built_from became "
                "authoritative — NULL must fall back, not go quiet"
            )
        finally:
            await _purge_vrt(test_db_session, ids=ids)


class TestArchiveFailureFailsThePublish:
    """ROUND 13 FINDING. The durable archive is a PRECONDITION of a lossy
    publish. An archive-write failure used to return quietly and let the job
    succeed, leaving the only faithful source in job staging where the
    retention purge removes it once a later job supersedes it — a transient
    storage error silently downgrading a dataset-lifetime guarantee to a
    windowed one. That is the exact trade round 7 refused for the same reason.
    """

    async def test_a_lossy_replace_fails_when_the_archive_cannot_be_written(
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
        old_bytes = await raster_storage.get(live.cog_key)

        source = tmp_path / "unarchivable.tif"
        source.write_bytes(_geotiff_bytes(seed=281))
        job = await _queue_replace_job(
            test_db_session,
            dataset_id=dataset_id,
            user_id=admin_id,
            file_path=str(source),
        )
        job.user_metadata = {**(job.user_metadata or {}), "compression": "JPEG"}
        await test_db_session.commit()
        job_id = job.id

        real_put = raster_storage.put

        async def _put_failing_archives(key, data):
            if "originals/" in key:
                raise RuntimeError("object store rejected the archive write")
            return await real_put(key, data)

        monkeypatch.setattr(raster_storage, "put", _put_failing_archives)

        try:
            with pytest.raises(Exception, match="durably archived"):
                await reupload_raster.func(
                    job_id=str(job_id),
                    dataset_id=str(dataset_id),
                    file_path=str(source),
                    user_id=str(admin_id),
                    attempt_id=str(job.attempt_id),
                )

            monkeypatch.setattr(raster_storage, "put", real_put)
            test_db_session.expire_all()
            asset = (
                await test_db_session.execute(
                    select(RasterAsset).where(RasterAsset.dataset_id == dataset_id)
                )
            ).scalar_one()

            # The property that makes failing SAFE: invariant 10 still holds.
            assert asset.asset_uri == live.cog_key, "the swap must not have landed"
            assert await raster_storage.get(live.cog_key) == old_bytes
            # And the uploaded file survives as the failed job's diagnostic copy.
            assert source.exists(), (
                "the source was deleted even though nothing durable holds it"
            )
            failed = (
                await test_db_session.execute(
                    select(IngestJob).where(IngestJob.id == job_id)
                )
            ).scalar_one()
            assert failed.status == "failed"
        finally:
            await _purge(test_db_session, dataset_id=dataset_id, record_id=record_id)

    def test_the_policy_lives_in_the_shared_function_not_the_call_sites(self) -> None:
        """Both tails must inherit the refusal from one place. If either call
        site decided for itself how to surface it, that is the drift class this
        PR has paid for three times."""
        import ast
        import inspect

        from app.processing.ingest import (
            tasks_raster,
            tasks_raster_replace,
            tasks_raster_swap,
        )

        swap_src = inspect.getsource(tasks_raster_swap)
        assert "ArchiveNotDurableError" in swap_src
        raises = [
            n
            for n in ast.walk(ast.parse(swap_src))
            if isinstance(n, ast.Raise)
            and isinstance(getattr(n.exc, "func", None), ast.Name)
            and n.exc.func.id == "ArchiveNotDurableError"
        ]
        assert raises, "the shared archiver does not refuse an undurable archive"

        # Neither tail may re-decide the policy locally.
        for module in (tasks_raster, tasks_raster_replace):
            src = inspect.getsource(module)
            assert "ArchiveNotDurableError" not in src, (
                f"{module.__name__} handles the archive-durability policy "
                "itself instead of inheriting it (#1290 round-13)"
            )


class TestLocalFailurePathsKeepWhatIsDurable:
    """ROUND 14. Both findings are this review's own distinctions —
    durable-vs-scratch, and requested-vs-happened — applied to corners of the
    LOCAL storage shape that never got them."""

    async def test_worker_validation_failure_keeps_the_local_original(
        self, test_db_session, raster_storage, tmp_path, monkeypatch
    ) -> None:
        """FINDING 1. A direct local upload that passes request-time validation
        and fails the WORKER check — canonically `UPLOAD_MAX_SIZE_MB` lowered
        while the job sat queued — used to have its only staged source deleted
        on an exit that records the job as FAILED, leaving nothing to diagnose
        from. The object-storage shape was already right, because what it
        deletes there is a downloaded scratch copy."""
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

        source = tmp_path / "too-big-now.tif"
        source.write_bytes(_geotiff_bytes(seed=291))
        job = await _queue_replace_job(
            test_db_session,
            dataset_id=dataset_id,
            user_id=admin_id,
            file_path=str(source),
        )
        job_id = job.id

        async def _reject(*args, **kwargs):
            raise ValueError("File exceeds the maximum allowed size.")

        monkeypatch.setattr(
            "app.processing.ingest.tasks_raster_replace._validate_upload_file_safety",
            _reject,
            raising=True,
        )

        try:
            await reupload_raster.func(
                job_id=str(job_id),
                dataset_id=str(dataset_id),
                file_path=str(source),
                user_id=str(admin_id),
                attempt_id=str(job.attempt_id),
            )

            assert source.exists(), (
                "the worker deleted the only staged copy of a file whose job "
                "it then recorded as failed — on a local install that is the "
                "durable original, not a scratch copy (#1290 round-14 "
                "finding 1)"
            )
            finished = (
                await test_db_session.execute(
                    select(IngestJob).where(IngestJob.id == job_id)
                )
            ).scalar_one()
            # Not complete: this is a failure path, and the point is that a
            # failure path must not destroy the diagnostic copy.
            assert finished.status != "complete"
        finally:
            await _purge(test_db_session, dataset_id=dataset_id, record_id=record_id)

    async def test_a_cancelled_archive_write_is_still_owned(
        self, test_db_session, raster_storage, tmp_path, monkeypatch
    ) -> None:
        """FINDING 2. `LocalStorageProvider.put` drains its worker thread before
        re-raising `CancelledError`, so a cancelled write can have COMPLETED on
        disk. `CancelledError` is a BaseException, so the old code never
        reported the key and the finished object survived with no quota row.

        The stub below writes and then raises, which IS the documented drain
        semantics rather than a convenience — reproducing the real provider's
        thread drain in-process would test asyncio, not this.
        """
        import asyncio as _asyncio

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

        source = tmp_path / "cancelled.tif"
        source.write_bytes(_geotiff_bytes(seed=292))
        job = await _queue_replace_job(
            test_db_session,
            dataset_id=dataset_id,
            user_id=admin_id,
            file_path=str(source),
        )
        job.user_metadata = {**(job.user_metadata or {}), "compression": "JPEG"}
        await test_db_session.commit()
        job_id = job.id

        real_put = raster_storage.put

        async def _put_then_cancel(key, data):
            result = await real_put(key, data)
            if "originals/" in key:
                # The write COMPLETED; the cancellation arrives after.
                raise _asyncio.CancelledError()
            return result

        monkeypatch.setattr(raster_storage, "put", _put_then_cancel)

        try:
            with pytest.raises(BaseException):
                await reupload_raster.func(
                    job_id=str(job_id),
                    dataset_id=str(dataset_id),
                    file_path=str(source),
                    user_id=str(admin_id),
                    attempt_id=str(job.attempt_id),
                )

            monkeypatch.setattr(raster_storage, "put", real_put)
            leftovers = await _archived_originals(raster_storage, dataset_id)
            assert leftovers == [], (
                f"a completed-but-cancelled archive write survived unowned: "
                f"{leftovers} — no quota row references it and nothing will "
                "ever reap it (#1290 round-14 finding 2)"
            )
        finally:
            await _purge(test_db_session, dataset_id=dataset_id, record_id=record_id)


# ---------------------------------------------------------------------------
# 17. srid_override becomes a CRS assignment (#1291)
# ---------------------------------------------------------------------------


class TestCrsAssignmentPreservesTheSamples:
    """fix(#1291). `srid_override` relabels; it does not resample.

    Inverting a "keep the original" into a "delete it" is the direction that
    costs something when it is wrong, so it is argued rather than asserted:
    `-a_srs` writes a CRS tag while every band passes through the translate, so
    the COG holds the uploaded samples exactly and the upload adds nothing. And
    unlike a warp, the step is reversible from the stored artifact — a caller
    who assigns the wrong EPSG can assign another one over the same untouched
    pixels, with `Dataset.original_srid` still recording what the upload
    declared. The measured half of that claim is
    `test_the_cog_carries_the_uploaded_samples_and_grid` below.
    """

    async def test_replace_with_srid_override_supersedes_the_original(
        self, test_db_session, raster_storage, tmp_path
    ) -> None:
        """End to end: default DEFLATE plus an override. Lossless codec,
        untouched pixels — there is no second copy left to justify."""
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

        source = tmp_path / "relabelled.tif"
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
            assert await _archived_names(test_db_session, dataset_id) == [], (
                "an override archived a second permanent copy of an upload the "
                "COG reproduces byte for byte — assignment resamples nothing "
                "(#1291)"
            )
        finally:
            await _purge(test_db_session, dataset_id=dataset_id, record_id=record_id)

    async def test_the_cog_carries_the_uploaded_samples_and_grid(
        self, test_db_session, raster_storage, tmp_path
    ) -> None:
        """The fact the retention decision above rests on, read off the object
        that was actually published: same shape, same pixels, new CRS label,
        and the same corner coordinates — a warp changes all four."""
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

        # Held in memory because the successful replace deletes the upload —
        # which is the retention change this test underwrites.
        source_bytes = _geotiff_bytes(seed=93)
        source = tmp_path / "relabelled.tif"
        source.write_bytes(source_bytes)
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
            published = await raster_storage.get(asset.asset_uri)

            with MemoryFile(published) as mem, mem.open() as cog:
                cog_bounds = tuple(cog.bounds)
                cog_pixels = cog.read(1)
                cog_epsg = cog.crs.to_epsg()
            with MemoryFile(source_bytes) as mem, mem.open() as src:
                src_bounds = tuple(src.bounds)
                src_pixels = src.read(1)

            assert cog_epsg == 3857
            assert cog_pixels.shape == src_pixels.shape, (
                "the pixel grid was resampled; an assignment must not touch it"
            )
            assert np.array_equal(cog_pixels, src_pixels), (
                "the samples changed under a lossless codec — the conversion "
                "reprojected instead of relabelling (#1291)"
            )
            assert cog_bounds == pytest.approx(src_bounds), (
                f"the corner coordinates moved ({src_bounds} -> {cog_bounds}); "
                "assignment changes what they mean, not what they are"
            )
        finally:
            await _purge(test_db_session, dataset_id=dataset_id, record_id=record_id)

    def test_neither_tail_asks_for_the_reprojected_verdict(self) -> None:
        """The first-ingest tail's half of the same change.

        Structural for the reason #1290 gave when it pinned its sibling this
        way: driving a whole successful first ingest — quota, notifications,
        billing, embeddings — to observe one bit is not worth the runtime, and
        what would actually regress is the keyword coming back with the warp
        long gone, quietly charging every override a second permanent copy.
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
                and getattr(node.func, "id", None) == "cog_preserves_source"
            ]
            assert calls, f"{module.__name__} does not consult the predicate"
            for call in calls:
                assert "reprojected" not in {kw.arg for kw in call.keywords}, (
                    f"{module.__name__} still reports a reprojection to "
                    "cog_preserves_source; nothing in this pipeline reprojects "
                    "since #1291"
                )

    def test_both_tails_persist_the_footprint_of_the_file_they_labelled(
        self,
    ) -> None:
        """Where the footprint comes from, in both tails.

        Under assignment the source and the COG hold the SAME corner numbers,
        so the two reads no longer disagree about any number — only about which
        CRS to read them under. That makes the source read a silently wrong
        answer rather than an obviously wrong one, which is the version of this
        bug that survives review.
        """
        import ast
        import inspect

        from app.processing.ingest import tasks_raster, tasks_raster_replace

        for module, callee, kwarg in (
            (tasks_raster, "create_raster_dataset", "meta"),
            (tasks_raster_replace, "_write_swapped_fields", "cog_meta"),
        ):
            tree = ast.parse(inspect.getsource(module))
            calls = [
                node
                for node in ast.walk(tree)
                if isinstance(node, ast.Call)
                and getattr(node.func, "id", None) == callee
            ]
            assert calls, f"{module.__name__} never calls {callee}"
            for call in calls:
                passed = {kw.arg: kw.value for kw in call.keywords if kw.arg == kwarg}
                assert passed, f"{module.__name__}: {callee} got no {kwarg}="
                assert getattr(passed[kwarg], "id", None) == "cog_meta", (
                    f"{module.__name__}: {callee} was handed "
                    f"{ast.dump(passed[kwarg])} — the catalog's extent must "
                    "come from the converted COG, whose CRS is the assigned one"
                )

    async def test_the_footprint_is_read_in_the_assigned_crs(
        self, test_db_session, raster_storage, tmp_path
    ) -> None:
        """The subtle half, and a real bug class here before (#1290).

        The source spans the whole world in EPSG:4326. Assigned 3857, those
        same numbers describe a 360 m by 180 m patch at the origin, so the
        published extent is sub-degree. Three wrong answers are all excluded by
        one assertion: reading the source's metadata (or a source-CRS reading
        of the COG) gives the whole world, and a warp to 3857 would give the
        whole world back too after the inverse transform.
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

        source = tmp_path / "relabelled.tif"
        source.write_bytes(_geotiff_bytes(seed=97))
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

            west, south, east, north = (
                await test_db_session.execute(
                    text(
                        "SELECT ST_XMin(spatial_extent), ST_YMin(spatial_extent), "
                        "ST_XMax(spatial_extent), ST_YMax(spatial_extent) "
                        "FROM catalog.records WHERE id = :id"
                    ),
                    {"id": record_id},
                )
            ).one()

            # -180..180 read as metres is ~0.0016 degrees of longitude.
            assert east - west < 0.01 and north - south < 0.01, (
                f"the published extent spans {east - west} x {north - south} "
                "degrees: the corner numbers were read under the CRS the "
                "caller replaced, not the one they assigned (#1291)"
            )
            assert abs(west) < 0.01 and abs(south) < 0.01, (
                f"the footprint sits at ({west}, {south}); metres near zero "
                "belong at the origin in WGS84"
            )
        finally:
            await _purge(test_db_session, dataset_id=dataset_id, record_id=record_id)


# ---------------------------------------------------------------------------
# 10. fix(#1778): commit ambiguity on the raster and VRT publish tails
# ---------------------------------------------------------------------------


@contextlib.contextmanager
def _ack_lost_on_publish(job_id: uuid.UUID, *, failure: BaseException):
    """Make the COMMIT that publishes ``job_id`` raise AFTER it has applied.

    The shape production sees when a connection drops or a cancel lands while
    ``COMMIT`` is in flight: PostgreSQL applied the transaction, the
    acknowledgement never arrived. It cannot be produced through a real
    session on demand, so the seam is ``AsyncSession.commit`` itself — run the
    real commit, ask a FRESH session whether the job is now ``complete``, and
    raise if it is. That fires on exactly one commit per task, the publishing
    one, whichever phase block it lives in and without the test counting
    commits.

    The patch is torn down on exit so the test's own session can commit its
    assertions and its purge.
    """
    from sqlalchemy.ext.asyncio import AsyncSession

    real_commit = AsyncSession.commit
    fired: dict[str, int] = {"count": 0}

    async def _commit(self, *args, **kwargs):
        await real_commit(self, *args, **kwargs)
        if fired["count"]:
            return
        from app.core.db import async_session

        async with async_session() as probe:
            status = (
                await probe.execute(
                    select(IngestJob.status).where(IngestJob.id == job_id)
                )
            ).scalar_one_or_none()
        if status == "complete":
            fired["count"] += 1
            raise failure

    AsyncSession.commit = _commit
    try:
        yield fired
    finally:
        AsyncSession.commit = real_commit


class TestPublishCommitLandedProbe:
    """The probe reads the row, and the row is the whole answer.

    ``publish_commit_landed`` is the shared half of the fix: every publish
    tail stamps its job ``complete`` in the SAME transaction as the pointer
    swap, so that one column, read on a fresh session and fenced on the
    attempt, decides whether the objects this attempt wrote are live.
    """

    @staticmethod
    async def _job(session, *, status: str) -> IngestJob:
        admin_id = (
            await session.execute(select(User.id).where(User.username == "admin"))
        ).scalar_one()
        job = IngestJob(
            source_filename="probe.tif",
            created_by=admin_id,
            status=status,
        )
        session.add(job)
        await session.commit()
        await session.refresh(job)
        return job

    async def test_complete_row_for_this_attempt_reads_as_landed(
        self, test_db_session
    ) -> None:
        from app.processing.ingest.tasks_raster_common import publish_commit_landed

        job = await self._job(test_db_session, status="complete")
        try:
            assert (
                await publish_commit_landed(
                    job.id, job.attempt_id, job_id=str(job.id), task="t"
                )
                is True
            )
        finally:
            await test_db_session.execute(
                delete(IngestJob).where(IngestJob.id == job.id)
            )
            await test_db_session.commit()

    @pytest.mark.parametrize("status", ["running", "pending", "failed"])
    async def test_non_complete_row_reads_as_not_landed(
        self, test_db_session, status
    ) -> None:
        from app.processing.ingest.tasks_raster_common import publish_commit_landed

        job = await self._job(test_db_session, status=status)
        try:
            assert (
                await publish_commit_landed(
                    job.id, job.attempt_id, job_id=str(job.id), task="t"
                )
                is False
            ), (
                f"a {status} row means the publishing transaction is not "
                "durable, so the objects this attempt wrote are reapable"
            )
        finally:
            await test_db_session.execute(
                delete(IngestJob).where(IngestJob.id == job.id)
            )
            await test_db_session.commit()

    async def test_a_superseded_attempt_never_reads_its_successors_commit(
        self, test_db_session
    ) -> None:
        """The fence is the attempt token, not the job id."""
        from app.processing.ingest.tasks_raster_common import publish_commit_landed

        job = await self._job(test_db_session, status="complete")
        try:
            assert (
                await publish_commit_landed(
                    job.id, uuid.uuid4(), job_id=str(job.id), task="t"
                )
                is False
            )
        finally:
            await test_db_session.execute(
                delete(IngestJob).where(IngestJob.id == job.id)
            )
            await test_db_session.commit()

    async def test_a_probe_that_cannot_read_stands_down(self, monkeypatch) -> None:
        """#1708's asymmetry: an unreadable probe assumes the swap landed.

        Standing down on a false positive leaves objects an operator can still
        remove; proceeding on a false negative deletes the live raster.
        """
        from app.processing.ingest.tasks_raster_common import publish_commit_landed

        def _no_session(*args, **kwargs):
            raise RuntimeError("the pool is gone too")

        monkeypatch.setattr("app.core.db.async_session", _no_session, raising=True)
        assert (
            await publish_commit_landed(
                uuid.uuid4(), uuid.uuid4(), job_id="j", task="t"
            )
            is True
        )


class TestAckLostCommitDoesNotDeleteThePublishedRaster:
    """fix(#1778): the audit's only irrecoverable data-loss path.

    Every publish tail set its "published" flag on the line AFTER
    ``await session.commit()``, and the terminal cleanup read that flag. A
    commit whose acknowledgement was lost therefore reached the cleanup with
    the flag false, and the cleanup deleted the exact object keys the
    committed row had just been pointed at. The superseded objects are not
    restored — the reaper of the OLD keys never ran — so nothing in the
    product can recover the dataset.

    fix(#1778 codex r1): observing the publish now makes the tail STAND DOWN
    rather than re-raise, so these tasks return normally and no failure write
    runs at all. Gating only the reap left `regenerate_vrt` stamping the
    `completed` VrtGeneration `failed`, which `get_vrt_status` reads as "this
    dataset has no completed generation".
    """

    @staticmethod
    async def _admin(session) -> uuid.UUID:
        return (
            await session.execute(select(User.id).where(User.username == "admin"))
        ).scalar_one()

    @pytest.mark.parametrize(
        "failure",
        [
            ConnectionResetError("the connection dropped inside COMMIT"),
            # #1709 delivers this on demand through `abort=True`, and it is a
            # BaseException the tails' `except Exception` never sees.
            asyncio.CancelledError(),
        ],
        ids=["connection-loss", "cancellation"],
    )
    async def test_replace_keeps_the_cog_the_committed_row_names(
        self, test_db_session, raster_storage, tmp_path, failure
    ) -> None:
        admin_id = await self._admin(test_db_session)
        live = await _make_live_raster(
            test_db_session, raster_storage, created_by=admin_id
        )
        dataset_id = live.dataset.id
        record_id = live.dataset.record_id
        prior_keys = [
            live.cog_key,
            live.asset.quicklook_256_uri,
            live.asset.quicklook_512_uri,
        ]

        source = tmp_path / "replacement.tif"
        source.write_bytes(_geotiff_bytes(seed=91))
        job = await _queue_replace_job(
            test_db_session,
            dataset_id=dataset_id,
            user_id=admin_id,
            file_path=str(source),
        )
        job_id = job.id
        attempt_id = job.attempt_id

        try:
            with _ack_lost_on_publish(job_id, failure=failure) as fired:
                # Returns rather than raising: the swap is durable, so there is
                # no failure for the handler to report (#1778 codex r1).
                await reupload_raster.func(
                    job_id=str(job_id),
                    dataset_id=str(dataset_id),
                    file_path=str(source),
                    user_id=str(admin_id),
                    attempt_id=str(attempt_id),
                )
            assert fired["count"] == 1, "the publishing commit never fired"

            test_db_session.expire_all()
            asset = (
                await test_db_session.execute(
                    select(RasterAsset).where(RasterAsset.dataset_id == dataset_id)
                )
            ).scalar_one()
            assert asset.asset_uri != live.cog_key, (
                "precondition: the swap is durable, so the row names the new COG"
            )
            for key in (
                asset.asset_uri,
                asset.quicklook_256_uri,
                asset.quicklook_512_uri,
            ):
                assert await raster_storage.exists(key), (
                    f"{key} was deleted after the commit that published it. "
                    "The dataset now points at bytes that do not exist and "
                    "nothing in the product can restore them."
                )

            finished = (
                await test_db_session.execute(
                    select(IngestJob).where(IngestJob.id == job_id)
                )
            ).scalar_one()
            assert finished.status == "complete", (
                "the terminal write landed with the swap, and the tail stands "
                "down instead of entering the handler that would report it "
                "failed"
            )
            run = (
                await test_db_session.execute(
                    select(DatasetRefreshRun).where(
                        DatasetRefreshRun.ingest_job_id == job_id
                    )
                )
            ).scalar_one()
            assert run.status == "succeeded", (
                "the refresh history must record what happened, not what the "
                "lost acknowledgement suggested"
            )

            # fix(#1778 codex r2). Standing down from the failure handler is
            # not standing down from the success work: this is the ONLY
            # deletion of the superseded objects, and the committed pointer
            # already names the new ones, so skipping it strands three objects
            # per lost acknowledgement outside quota accounting for the life of
            # the dataset.
            for key in prior_keys:
                assert not await raster_storage.exists(key), (
                    f"the superseded {key} survived the swap. Nothing "
                    "references it and nothing counts it."
                )
        finally:
            await _purge(test_db_session, dataset_id=dataset_id, record_id=record_id)

    async def test_a_probe_that_observes_no_commit_still_reaps(
        self, test_db_session, raster_storage, tmp_path, monkeypatch
    ) -> None:
        """The counterfactual, and the other half of the contract.

        With the probe answering "not committed" — which is what it really
        answers whenever the row is not ``complete`` for this attempt, pinned
        above — the tail must reap exactly as it did before, or GAP-017's
        orphaned bytes come back. It is also the shape the assertions above
        would have had before the fix, which is what makes them load-bearing.
        """
        admin_id = await self._admin(test_db_session)
        live = await _make_live_raster(
            test_db_session, raster_storage, created_by=admin_id
        )
        dataset_id = live.dataset.id
        record_id = live.dataset.record_id

        source = tmp_path / "replacement.tif"
        source.write_bytes(_geotiff_bytes(seed=92))
        job = await _queue_replace_job(
            test_db_session,
            dataset_id=dataset_id,
            user_id=admin_id,
            file_path=str(source),
        )
        job_id = job.id
        attempt_id = job.attempt_id

        async def _observes_nothing(*args, **kwargs) -> bool:
            return False

        monkeypatch.setattr(
            "app.processing.ingest.tasks_raster_replace.publish_commit_landed",
            _observes_nothing,
            raising=True,
        )

        try:
            with _ack_lost_on_publish(job_id, failure=ConnectionResetError("dropped")):
                with pytest.raises(ConnectionResetError):
                    await reupload_raster.func(
                        job_id=str(job_id),
                        dataset_id=str(dataset_id),
                        file_path=str(source),
                        user_id=str(admin_id),
                        attempt_id=str(attempt_id),
                    )

            test_db_session.expire_all()
            asset = (
                await test_db_session.execute(
                    select(RasterAsset).where(RasterAsset.dataset_id == dataset_id)
                )
            ).scalar_one()
            assert not await raster_storage.exists(asset.asset_uri), (
                "with the commit observed as not durable the newly written "
                "keys are orphans, and GAP-017 requires them reaped"
            )
        finally:
            await _purge(test_db_session, dataset_id=dataset_id, record_id=record_id)

    async def test_first_ingest_keeps_the_cog_the_committed_row_names(
        self, test_db_session, raster_storage, tmp_path, monkeypatch
    ) -> None:
        """``ingest_raster``: same tail, and its reap used to key off
        ``final_status``, which the broad handler sets to "failed" even when
        the failure happened after the swap was durable. Its handler also
        emails the operator, so standing down is what stops a durable ingest
        being reported as a failure (#1778 codex r1)."""
        from app.core.config import settings
        from app.platform.notifications import events as events_mod
        from app.processing.ingest.tasks_raster import ingest_raster

        emitted: list = []

        async def _fake_notify(notification):
            emitted.append(notification)

        monkeypatch.setattr(settings, "notify_on_ingest_failed", True, raising=False)
        monkeypatch.setattr(events_mod, "notify", _fake_notify)

        admin_id = await self._admin(test_db_session)
        source = tmp_path / "first.tif"
        source.write_bytes(_geotiff_bytes(seed=93))
        job = IngestJob(
            source_filename="first.tif",
            file_path=str(source),
            created_by=admin_id,
            status="pending",
            user_metadata={"file_type": "raster", "title": "Ack-lost first ingest"},
        )
        test_db_session.add(job)
        await test_db_session.commit()
        await test_db_session.refresh(job)
        job_id = job.id
        attempt_id = job.attempt_id

        dataset_id = record_id = None
        try:
            with _ack_lost_on_publish(
                job_id, failure=ConnectionResetError("dropped")
            ) as fired:
                await ingest_raster.func(
                    job_id=str(job_id),
                    file_path=str(source),
                    user_id=str(admin_id),
                    attempt_id=str(attempt_id),
                )
            assert fired["count"] == 1, "the publishing commit never fired"
            assert [n.event_type for n in emitted] == [], (
                "a durable ingest emailed the operator that it failed"
            )

            test_db_session.expire_all()
            finished = (
                await test_db_session.execute(
                    select(IngestJob).where(IngestJob.id == job_id)
                )
            ).scalar_one()
            assert finished.status == "complete"
            dataset_id = finished.dataset_id
            assert dataset_id is not None, "the publish transaction created the row"
            record_id = (
                await test_db_session.execute(
                    select(Dataset.record_id).where(Dataset.id == dataset_id)
                )
            ).scalar_one()
            asset = (
                await test_db_session.execute(
                    select(RasterAsset).where(RasterAsset.dataset_id == dataset_id)
                )
            ).scalar_one()
            for key in (
                asset.asset_uri,
                asset.quicklook_256_uri,
                asset.quicklook_512_uri,
            ):
                assert await raster_storage.exists(key), (
                    f"{key} was deleted after the commit that published it"
                )
        finally:
            await test_db_session.execute(
                delete(IngestJob).where(IngestJob.id == job_id)
            )
            await test_db_session.commit()
            if dataset_id is not None and record_id is not None:
                await _purge(
                    test_db_session, dataset_id=dataset_id, record_id=record_id
                )

    async def test_vrt_regeneration_keeps_the_generation_it_published(
        self, client, admin_auth_header, test_db_session, raster_storage, monkeypatch
    ) -> None:
        from app.processing.ingest.tasks_vrt import regenerate_vrt
        from app.processing.raster.models import VrtGeneration

        # `regenerate_vrt` binds get_storage at module import, so the fixture's
        # patch of `app.platform.storage.get_storage` never reaches its puts.
        monkeypatch.setattr(
            "app.processing.ingest.tasks_vrt.get_storage",
            lambda: raster_storage,
            raising=True,
        )
        admin_id = await self._admin(test_db_session)
        member = await _make_live_raster(
            test_db_session, raster_storage, created_by=admin_id
        )
        parent = await _make_vrt_parent(
            test_db_session, raster_storage, created_by=admin_id, member=member
        )
        ids = (
            parent.dataset.id,
            parent.dataset.record_id,
            member.dataset.id,
            member.dataset.record_id,
        )
        parent_id = parent.dataset.id
        prior_key = parent.cog_key

        generation_id = uuid.uuid4()
        job = IngestJob(
            dataset_id=parent_id,
            source_filename="regen",
            created_by=admin_id,
            status="pending",
            user_metadata={"vrt_regenerate": True},
        )
        test_db_session.add(job)
        test_db_session.add(
            VrtGeneration(
                id=generation_id,
                vrt_dataset_id=parent_id,
                status="pending",
                started_at=datetime.now(timezone.utc),
            )
        )
        await test_db_session.execute(
            text(
                "UPDATE catalog.raster_assets "
                "SET current_generation_id = :gen, status = 'regenerating' "
                "WHERE dataset_id = :id"
            ),
            {"gen": generation_id, "id": parent_id},
        )
        await test_db_session.commit()
        await test_db_session.refresh(job)
        job_id = job.id
        attempt_id = job.attempt_id

        try:
            with _ack_lost_on_publish(
                job_id, failure=ConnectionResetError("dropped")
            ) as fired:
                await regenerate_vrt.func(
                    job_id=str(job_id),
                    vrt_dataset_id=str(parent_id),
                    attempt_id=str(attempt_id),
                    generation_id=str(generation_id),
                )
            assert fired["count"] == 1, "the publishing commit never fired"

            test_db_session.expire_all()
            asset = (
                await test_db_session.execute(
                    select(RasterAsset).where(RasterAsset.dataset_id == parent_id)
                )
            ).scalar_one()
            assert asset.asset_uri != prior_key, (
                "precondition: the generation swap is durable"
            )
            assert await raster_storage.exists(asset.asset_uri), (
                f"{asset.asset_uri} was deleted after the commit that "
                "published it — the VRT dataset now serves nothing"
            )

            # fix(#1778 codex r2): the superseded generation's object is the
            # mirror obligation. The committed asset already names the new one,
            # so a stand-down that skipped the reap would strand it outside
            # quota accounting.
            assert not await raster_storage.exists(prior_key), (
                f"the superseded {prior_key} survived the generation swap"
            )

            # fix(#1778 codex r1). The reap was only the deletion. The failure
            # handler this tail used to enter also relabelled the history and
            # the asset, and those have readers.
            assert asset.status == "ready", (
                f"the asset is {asset.status!r}: the failure handler ran "
                "against a published generation"
            )
            assert asset.current_generation_id is None, (
                "the publish cleared the pointer and the handler put it back"
            )
            generation = (
                await test_db_session.execute(
                    select(VrtGeneration).where(VrtGeneration.id == generation_id)
                )
            ).scalar_one()
            assert generation.status == "completed", (
                f"the generation reads {generation.status!r} for a build whose "
                "artifact the dataset is serving"
            )
            assert generation.error_message is None, (
                "a completed generation carries no failure reason"
            )

            # The reader codex named: get_vrt_status derives
            # `last_generation_at` from the latest COMPLETED generation, so a
            # falsely failed one erases the regeneration from the UI.
            resp = await client.get(
                f"/datasets/{parent_id}/vrt/status/", headers=admin_auth_header
            )
            assert resp.status_code == 200, resp.text
            assert resp.json()["last_generation_at"] is not None, (
                "the VRT status endpoint reports no completed generation for a "
                "dataset that just published one"
            )
        finally:
            await _purge_vrt(test_db_session, ids=ids)

    async def test_vrt_creation_keeps_the_artifact_it_published(
        self, test_db_session, raster_storage
    ) -> None:
        """``ingest_vrt`` shares the tail even though the audit excerpt stopped
        at the regenerate one: the dataset row and the VRT object become
        visible in the same transaction, so a lost acknowledgement deletes
        exactly what the committed row names."""
        from pathlib import Path as _P

        from app.processing.ingest.tasks_vrt import ingest_vrt, resolve_vrt_source_path

        admin_id = await self._admin(test_db_session)
        member = await _make_live_raster(
            test_db_session, raster_storage, created_by=admin_id
        )
        member_path = _P(
            resolve_vrt_source_path(member.asset.asset_uri, tenant_id=None)
        )
        member_path.parent.mkdir(parents=True, exist_ok=True)
        member_path.write_bytes(_geotiff_bytes(seed=1))
        # Read before the expire_all below: an expired attribute lazy-loads,
        # and under AnyIO that raises MissingGreenlet (see _purge_vrt).
        member_ds = member.dataset.id
        member_rec = member.dataset.record_id

        job = IngestJob(
            source_filename="mosaic.vrt",
            created_by=admin_id,
            status="pending",
            user_metadata={"title": "Ack-lost mosaic", "visibility": "public"},
        )
        test_db_session.add(job)
        await test_db_session.commit()
        await test_db_session.refresh(job)
        job_id = job.id
        attempt_id = job.attempt_id

        vrt_ds = vrt_rec = None
        try:
            with _ack_lost_on_publish(
                job_id, failure=ConnectionResetError("dropped")
            ) as fired:
                await ingest_vrt.func(
                    job_id=str(job_id),
                    source_dataset_ids=_json.dumps([str(member_ds)]),
                    user_id=str(admin_id),
                    attempt_id=str(attempt_id),
                    vrt_type="mosaic",
                    resolution_strategy="finest",
                )
            assert fired["count"] == 1, "the publishing commit never fired"

            test_db_session.expire_all()
            finished = (
                await test_db_session.execute(
                    select(IngestJob).where(IngestJob.id == job_id)
                )
            ).scalar_one()
            assert finished.status == "complete"
            vrt_ds = finished.dataset_id
            assert vrt_ds is not None
            vrt_rec = (
                await test_db_session.execute(
                    select(Dataset.record_id).where(Dataset.id == vrt_ds)
                )
            ).scalar_one()
            asset = (
                await test_db_session.execute(
                    select(RasterAsset).where(RasterAsset.dataset_id == vrt_ds)
                )
            ).scalar_one()
            assert await raster_storage.exists(asset.asset_uri), (
                f"{asset.asset_uri} was deleted after the commit that published it"
            )
            assert asset.status == "ready", (
                f"the asset is {asset.status!r}: the failure handler ran "
                "against a published build"
            )
        finally:
            await test_db_session.execute(
                delete(IngestJob).where(IngestJob.id == job_id)
            )
            await test_db_session.commit()
            if vrt_ds is not None and vrt_rec is not None:
                await _purge_vrt(
                    test_db_session,
                    ids=(vrt_ds, vrt_rec, member_ds, member_rec),
                )
            else:
                await _purge(
                    test_db_session, dataset_id=member_ds, record_id=member_rec
                )

    async def test_a_post_publish_followup_failure_writes_no_failure_row(
        self, client, admin_auth_header, test_db_session, raster_storage, monkeypatch
    ) -> None:
        """fix(#1778 codex r1): the other way into the failure handler.

        The stand-down covers the lost acknowledgement. It cannot cover this:
        the prior-key reap, `invalidate_catalog_cache` and `defer_embedding`
        all run inside the same `try` as the publish, so a Valkey outage
        reaches the handler with the swap already durable. The handler's job
        and asset writes are fenced; its generation write was not, and
        `get_vrt_status` reads exactly that row.
        """
        from app.processing.ingest.tasks_vrt import regenerate_vrt
        from app.processing.raster.models import VrtGeneration

        monkeypatch.setattr(
            "app.processing.ingest.tasks_vrt.get_storage",
            lambda: raster_storage,
            raising=True,
        )
        admin_id = await self._admin(test_db_session)
        member = await _make_live_raster(
            test_db_session, raster_storage, created_by=admin_id
        )
        parent = await _make_vrt_parent(
            test_db_session, raster_storage, created_by=admin_id, member=member
        )
        ids = (
            parent.dataset.id,
            parent.dataset.record_id,
            member.dataset.id,
            member.dataset.record_id,
        )
        parent_id = parent.dataset.id

        generation_id = uuid.uuid4()
        job = IngestJob(
            dataset_id=parent_id,
            source_filename="regen",
            created_by=admin_id,
            status="pending",
            user_metadata={"vrt_regenerate": True},
        )
        test_db_session.add(job)
        test_db_session.add(
            VrtGeneration(
                id=generation_id,
                vrt_dataset_id=parent_id,
                status="pending",
                started_at=datetime.now(timezone.utc),
            )
        )
        await test_db_session.execute(
            text(
                "UPDATE catalog.raster_assets "
                "SET current_generation_id = :gen, status = 'regenerating' "
                "WHERE dataset_id = :id"
            ),
            {"gen": generation_id, "id": parent_id},
        )
        await test_db_session.commit()
        await test_db_session.refresh(job)
        job_id = job.id
        attempt_id = job.attempt_id

        async def _die(*args, **kwargs):
            raise RuntimeError("valkey went away right after the swap")

        # The first await after the publish commit that can fail.
        monkeypatch.setattr(
            "app.processing.ingest.tasks_vrt.invalidate_catalog_cache",
            _die,
            raising=True,
        )

        try:
            await regenerate_vrt.func(
                job_id=str(job_id),
                vrt_dataset_id=str(parent_id),
                attempt_id=str(attempt_id),
                generation_id=str(generation_id),
            )

            test_db_session.expire_all()
            generation = (
                await test_db_session.execute(
                    select(VrtGeneration).where(VrtGeneration.id == generation_id)
                )
            ).scalar_one()
            assert generation.status == "completed", (
                f"the generation reads {generation.status!r} because a cache "
                "purge failed after the swap was durable"
            )
            assert generation.error_message is None
            asset = (
                await test_db_session.execute(
                    select(RasterAsset).where(RasterAsset.dataset_id == parent_id)
                )
            ).scalar_one()
            assert asset.status == "ready"
            assert asset.current_generation_id is None
            finished = (
                await test_db_session.execute(
                    select(IngestJob).where(IngestJob.id == job_id)
                )
            ).scalar_one()
            assert finished.status == "complete"

            resp = await client.get(
                f"/datasets/{parent_id}/vrt/status/", headers=admin_auth_header
            )
            assert resp.status_code == 200, resp.text
            assert resp.json()["last_generation_at"] is not None, (
                "the VRT status endpoint lost the completed generation to a "
                "failed cache purge"
            )
        finally:
            await _purge_vrt(test_db_session, ids=ids)

    def test_every_publish_tail_stands_down_on_an_observed_publish(self) -> None:
        """Structural, because the finding is a SHAPE.

        Two properties per tail, and the second is fix(#1778 codex r1): the
        handler that probes must END the landed branch by returning, not by
        re-raising into a failure handler that writes about a job that
        succeeded, and it must absorb the cancellation it is choosing to stop
        honouring. The orphan reap must still be gated on the name that
        handler assigns rather than on a flag set after the commit returned.

        A fifth tail written the old way, or a revert of any of these four,
        fails here.
        """
        import ast
        import inspect

        from app.processing.ingest import tasks_raster, tasks_raster_replace, tasks_vrt

        def _calls(node, name: str) -> bool:
            return any(
                isinstance(inner, ast.Call) and getattr(inner.func, "id", None) == name
                for inner in ast.walk(node)
            )

        checked = 0
        for module in (tasks_raster, tasks_raster_replace, tasks_vrt):
            tree = ast.parse(inspect.getsource(module))
            for func in ast.walk(tree):
                if not isinstance(func, (ast.AsyncFunctionDef, ast.FunctionDef)):
                    continue
                published: set[str] = set()
                for handler in ast.walk(func):
                    if not isinstance(handler, ast.ExceptHandler):
                        continue
                    if not _calls(handler, "publish_commit_landed"):
                        continue
                    where = f"{module.__name__}.{func.name}"
                    assert any(
                        isinstance(node, ast.Return) for node in ast.walk(handler)
                    ), (
                        f"{where} probes the commit and then re-raises. The "
                        "publish is durable, so the failure handler it enters "
                        "reports a job that succeeded as failed."
                    )
                    assert _calls(handler, "absorb_cancellation"), (
                        f"{where} returns out of a caught BaseException "
                        "without absorbing the cancellation it stops honouring"
                    )
                    published |= {
                        target.id
                        for node in ast.walk(handler)
                        if isinstance(node, ast.Assign)
                        for target in node.targets
                        if isinstance(target, ast.Name)
                    }
                if not published:
                    continue
                for node in ast.walk(func):
                    if not isinstance(node, ast.Try) or not node.finalbody:
                        continue
                    for stmt in node.finalbody:
                        for guard in ast.walk(stmt):
                            if not isinstance(guard, ast.If):
                                continue
                            if not any(
                                _calls(body, "_cleanup_orphaned_storage_keys")
                                for body in guard.body
                            ):
                                continue
                            names = {
                                n.id
                                for n in ast.walk(guard.test)
                                if isinstance(n, ast.Name)
                            }
                            assert names & published, (
                                f"{module.__name__}.{func.name} reaps written "
                                "storage keys behind a guard the commit probe "
                                f"never wrote (guard reads {sorted(names)}, "
                                f"probe assigns {sorted(published)})"
                            )
                            checked += 1
        assert checked == 4, (
            f"expected the four publish tails, walked {checked} — a tail was "
            "added or removed without updating this gate"
        )

    def test_the_generation_failure_write_is_fenced_at_the_statement(self) -> None:
        """fix(#1778 codex r1): the rule stated at the write, not only at the
        caller.

        The handler guard makes this branch unreachable from
        ``regenerate_vrt``'s own paths today, which is exactly why it is
        pinned here rather than by an execution test: the flag is a local, the
        fence is a property of the statement, and a future path into the
        handler must not be able to relabel a generation whose artifact the
        dataset is serving. Its two peers, the ``current_generation_id`` fence
        on the asset and the ``running`` fence on the job, are enforced by the
        database predicate itself.
        """
        import ast
        import inspect

        from app.processing.ingest import tasks_vrt

        tree = ast.parse(inspect.getsource(tasks_vrt))
        writes = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Assign)
            and any(
                isinstance(t, ast.Attribute)
                and t.attr == "status"
                and getattr(t.value, "id", None) == "gen"
                for t in node.targets
            )
        ]
        assert writes, "the generation failure write moved or was renamed"
        fenced = [
            guard
            for guard in ast.walk(tree)
            if isinstance(guard, ast.If)
            and any(write in ast.walk(guard) for write in writes)
            and any(
                isinstance(cmp_node, ast.Compare)
                and any(
                    isinstance(c, ast.Constant) and c.value == "completed"
                    for c in cmp_node.comparators
                )
                for cmp_node in ast.walk(guard.test)
            )
        ]
        assert fenced, (
            "the failure handler stamps VrtGeneration.status without asking "
            "whether the generation already completed, so a published "
            "regeneration can be relabelled failed and get_vrt_status will "
            "report the dataset as having no completed generation"
        )
