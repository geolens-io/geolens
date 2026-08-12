"""Integration test for regenerate_vrt task — behavioral anchor for Phase 219.

This test is DELIBERATELY slow and real:
- Generates 2 real GeoTIFFs via rasterio
- Creates real PostGIS rows (Record, Dataset, RasterAsset, VrtGeneration, IngestJob, vrt_source_links)
- Invokes gdalbuildvrt as a subprocess
- Writes the result via a real LocalStorageProvider
- Reads back and asserts on 16 state mutations

Phase 219 extracts 3 helpers from regenerate_vrt. Any drift in behavior will
fail this test — that is the whole point of shipping this phase first.

DO NOT mock subprocess, rasterio, or async_session in this file. Use mocks
ONLY for generate_quicklook (see D-05) and optionally the non-fatal cache
invalidation / embedding deferral calls.
"""

import hashlib
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import rasterio
from sqlalchemy import select, text

# Fixture helpers (D-01: direct cross-test-file import)
from tests.test_raster_ingest import _write_tmp_tif

# NOTE: No `pytestmark = pytest.mark.asyncio`. The project configures
# `anyio_mode = "auto"` alongside `asyncio_mode = "strict"` in
# backend/pyproject.toml:61-67. AnyIO owns async integration fixtures
# (including `client`, `test_db_session`) so pytest-asyncio must NOT
# claim this test — doing so runs fixtures on a different event loop
# than the test body and causes "Future attached to a different loop"
# from asyncpg. Leave the module unmarked; AnyIO will run it.


@pytest.fixture
def source_tifs(tmp_path: Path) -> dict[str, Path]:
    """Write 2 synthetic GeoTIFFs under tmp_path / "storage" / "rasters" / ...

    Returns a dict mapping asset_uri (the relative key stored in RasterAsset)
    to the absolute filesystem path where the TIF was written. The
    LocalStorageProvider in the local_storage fixture reads from the same
    tmp_path / "storage" base dir, so these TIFs are visible both via the
    storage provider (for completeness) AND via resolve_vrt_source_path
    (which is what regenerate_vrt uses).
    """
    storage_root = tmp_path / "storage"
    storage_root.mkdir(parents=True, exist_ok=True)

    sources: dict[str, Path] = {}
    for i in (1, 2):
        asset_uri = f"rasters/src-{i}/source.cog.tif"
        dest = storage_root / asset_uri
        dest.parent.mkdir(parents=True, exist_ok=True)
        # _write_tmp_tif writes to a system temp dir; move to our storage root.
        tmp_tif = _write_tmp_tif(width=64, height=64, bands=1, dtype="uint8")
        try:
            dest.write_bytes(tmp_tif.read_bytes())
        finally:
            tmp_tif.unlink(missing_ok=True)
        sources[asset_uri] = dest

    return sources


@pytest.fixture
async def local_storage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    test_db_session,
):
    """Create a real LocalStorageProvider rooted at tmp_path / "storage" and
    patch it into app.ingest.tasks.get_storage.

    Also overrides settings.upload_staging_dir so resolve_vrt_source_path
    (called inside regenerate_vrt at tasks.py:2200) resolves source asset_uris
    to paths under the same tmp_path / "storage" root.
    """
    from app.core.config import settings
    from app.platform.storage.local import LocalStorageProvider

    # Force the client/test_db_session fixture to run first. It also changes
    # upload_staging_dir, and this fixture must be the last override applied.
    _ = test_db_session

    storage_root = tmp_path / "storage"
    storage_root.mkdir(parents=True, exist_ok=True)

    provider = LocalStorageProvider(base_dir=str(storage_root))

    # Patch the top-level import in tasks_vrt — NOT the re-export in tasks.py.
    # tasks_vrt.py imports get_storage directly; patching tasks.get_storage
    # doesn't affect the binding inside tasks_vrt.
    monkeypatch.setattr("app.processing.ingest.tasks_vrt.get_storage", lambda: provider)

    # Override upload_staging_dir so resolve_vrt_source_path (delegating to
    # resolve_open_path since Phase 1210-02) resolves source asset_uris to files
    # under our storage root. Without this override, gdalbuildvrt gets production
    # paths that do not exist and fails. The settings object at app.core.config is
    # the single source after the Plan 02 delegation (raster_vrt_module.settings
    # was removed; app.core.config.settings is patched here instead).
    monkeypatch.setattr(settings, "upload_staging_dir", str(storage_root))

    return provider


@pytest.fixture
def quicklook_stub(monkeypatch: pytest.MonkeyPatch):
    """Stub generate_quicklook at the test boundary (D-05).

    Returns fixed bytes regardless of inputs. The real generate_quicklook
    requires PIL/matplotlib and touches rasterio in non-trivial ways; the
    failures are non-fatal inside regenerate_vrt (tasks.py:2228 swallows
    them), so a stub keeps the test deterministic and dependency-light.
    """

    def _stub(vrt_path: str, size: int) -> bytes:
        return b"\x00" * 256  # fixed-size fake PNG bytes

    # Patch at tasks_vrt where regenerate_vrt imports it directly
    monkeypatch.setattr("app.processing.ingest.tasks_vrt.generate_quicklook", _stub)
    return _stub


@pytest.fixture
async def vrt_db_state(
    test_db_session,  # from conftest.py
    source_tifs: dict[str, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> dict:
    """Create all DB rows regenerate_vrt needs to succeed.

    Returns a dict with handles to every row for later assertion lookup:
        {
            "job_id": UUID (str),
            "vrt_dataset_id": UUID (str),
            "vrt_asset_id": UUID,
            "source_dataset_ids": [UUID, UUID],
            "expected_vrt_key": "rasters/vrt-<hex>/source.vrt",
            "vrt_record_id": UUID,
        }

    Mirrors the row shape in backend/app/ingest/tasks.py:1600-1699
    (_create_vrt_dataset_rows), minus distribution rows and source_dataset_ids
    parameter handling.
    """
    from app.modules.catalog.datasets.domain.models import Dataset, Record
    from app.platform.jobs.models import IngestJob
    from app.processing.raster.models import RasterAsset

    # fix(#909): tasks_vrt now late-binds async_session from app.core.db,
    # which the `client` fixture already patches to the test factory — the
    # per-module re-patch this comment used to defend is gone by design.

    session = test_db_session
    source_uris = list(source_tifs.keys())  # ["rasters/src-1/source.cog.tif", ...]
    assert len(source_uris) == 2, "Fixture expects exactly 2 source TIFs"

    # --- Source rasters (x2) ---
    source_datasets: list[Dataset] = []
    for i, uri in enumerate(source_uris, start=1):
        src_record = Record(
            title=f"Integration Source Raster {i}",
            record_type="raster_dataset",
            record_status="published",
            visibility="private",
        )
        session.add(src_record)
        await session.flush()

        src_dataset = Dataset(
            record_id=src_record.id,
            table_name=f"raster_src_{src_record.id.hex[:16]}",
            source_format="geotiff",
            srid=4326,
        )
        session.add(src_dataset)
        await session.flush()

        src_asset = RasterAsset(
            dataset_id=src_dataset.id,
            asset_uri=uri,  # e.g. "rasters/src-1/source.cog.tif"
            storage_backend="local",
            status="ready",
            band_count=1,
            epsg=4326,
            crs_wkt=(
                'GEOGCS["WGS 84",DATUM["WGS_1984",'
                'SPHEROID["WGS 84",6378137,298.257223563]],'
                'PRIMEM["Greenwich",0],'
                'UNIT["degree",0.0174532925199433]]'
            ),
            width=64,
            height=64,
            dtype="uint8",
        )
        session.add(src_asset)
        source_datasets.append(src_dataset)

    await session.flush()

    # --- VRT dataset (x1) ---
    vrt_record = Record(
        title="Integration VRT Dataset",
        record_type="vrt_dataset",
        record_status="published",
        visibility="private",
        spatial_extent=None,  # will be populated by regenerate_vrt (assertion #15)
    )
    session.add(vrt_record)
    await session.flush()

    vrt_dataset = Dataset(
        record_id=vrt_record.id,
        table_name=f"vrt_{vrt_record.id.hex[:16]}",
        source_format=None,  # VRT datasets have no source_format (tasks.py:1648)
        srid=4326,
    )
    session.add(vrt_dataset)
    await session.flush()

    expected_vrt_key = f"rasters/vrt-{vrt_dataset.id.hex[:8]}/source.vrt"
    vrt_asset = RasterAsset(
        dataset_id=vrt_dataset.id,
        asset_uri=expected_vrt_key,  # stays unchanged; task overwrites same key
        quicklook_256_uri=f"rasters/vrt-{vrt_dataset.id.hex[:8]}/quicklook_256.png",
        quicklook_512_uri=f"rasters/vrt-{vrt_dataset.id.hex[:8]}/quicklook_512.png",
        storage_backend="local",
        vrt_type="mosaic",
        resolution_strategy="finest",
        status="regenerating",  # mirrors router pre-state before task runs
        current_generation_id=uuid.uuid4(),  # placeholder; task creates real VrtGeneration row
        driver="VRT",
        # Intentionally DO NOT set sha256/size_bytes/crs_wkt/epsg/band_count/
        # width/height/last_regenerated_at — those are assertions #3-#11 that
        # regenerate_vrt populates.
    )
    session.add(vrt_asset)
    await session.flush()

    # --- vrt_source_links (x2, raw SQL mirroring tasks.py:1687) ---
    await session.execute(
        text(
            "INSERT INTO catalog.vrt_source_links "
            "(vrt_dataset_id, source_dataset_id, position) "
            "VALUES (:vrt_id, :src_id, :pos)"
        ),
        [
            {"vrt_id": str(vrt_dataset.id), "src_id": str(src.id), "pos": idx}
            for idx, src in enumerate(source_datasets)
        ],
    )

    # --- IngestJob (x1) ---
    job = IngestJob(
        status="pending",
        source_filename="regenerate-vrt-integration-test.vrt",
    )
    session.add(job)
    await session.flush()

    # CRITICAL: regenerate_vrt opens its own async_session() at tasks.py:2142 —
    # a separate session that cannot see uncommitted rows from test_db_session.
    # Commit here so the task sees the fixture data. (Research Open Question #2.)
    await session.commit()

    return {
        "job_id": str(job.id),
        "attempt_id": str(job.attempt_id),
        "vrt_dataset_id": str(vrt_dataset.id),
        "vrt_asset_id": vrt_asset.id,
        "source_dataset_ids": [d.id for d in source_datasets],
        "expected_vrt_key": expected_vrt_key,
        "vrt_record_id": vrt_record.id,
    }


async def test_regenerate_vrt_happy_path_end_to_end(
    test_db_session,
    vrt_db_state: dict,
    local_storage,  # fixture wires up storage + settings.upload_staging_dir
    quicklook_stub,  # fixture stubs generate_quicklook
    clean_tables,  # opt-in truncate after test (Research Open Question #1)
):
    """Full integration test: invoke regenerate_vrt and assert on 16 state mutations.

    This is the behavioral anchor for Phase 219's refactor. Any drift in the
    observable outcome of regenerate_vrt will fail this test — that's the
    whole point of shipping this before Phase 219.

    The 15 assertions cover every DB + storage mutation that regenerate_vrt
    performs in the happy path. See CONTEXT.md D-03 for the enumerated list.
    """
    from app.modules.catalog.datasets.domain.models import Dataset, Record
    from app.processing.ingest.tasks import regenerate_vrt
    from app.platform.jobs.models import IngestJob
    from app.processing.raster.models import RasterAsset, VrtGeneration

    session = test_db_session

    # fix(#1329 follow-up): capture the pre-swap version so [17] asserts the
    # bump itself, not a hardcoded absolute.
    pre_version_result = await session.execute(
        select(Dataset.tile_cache_version).where(
            Dataset.id == uuid.UUID(vrt_db_state["vrt_dataset_id"])
        )
    )
    pre_tile_cache_version = pre_version_result.scalar_one()

    # --- INVOKE ------------------------------------------------------------
    # Call the underlying coroutine via Task.func, bypassing the queue.
    await regenerate_vrt.func(
        job_id=vrt_db_state["job_id"],
        attempt_id=vrt_db_state["attempt_id"],
        vrt_dataset_id=vrt_db_state["vrt_dataset_id"],
    )

    # --- REFRESH -----------------------------------------------------------
    # regenerate_vrt commits its own session; our test_db_session is separate.
    # Re-query to get the post-task state.
    vrt_asset_result = await session.execute(
        select(RasterAsset).where(RasterAsset.id == vrt_db_state["vrt_asset_id"])
    )
    vrt_asset = vrt_asset_result.scalar_one()
    await session.refresh(vrt_asset)

    job_result = await session.execute(
        select(IngestJob).where(IngestJob.id == uuid.UUID(vrt_db_state["job_id"]))
    )
    job = job_result.scalar_one()
    await session.refresh(job)

    gen_result = await session.execute(
        select(VrtGeneration).where(
            VrtGeneration.vrt_dataset_id == uuid.UUID(vrt_db_state["vrt_dataset_id"])
        )
    )
    generation = gen_result.scalar_one()

    record_result = await session.execute(
        select(Record).where(Record.id == vrt_db_state["vrt_record_id"])
    )
    vrt_record = record_result.scalar_one()

    vrt_dataset_result = await session.execute(
        select(Dataset).where(Dataset.id == uuid.UUID(vrt_db_state["vrt_dataset_id"]))
    )
    vrt_dataset = vrt_dataset_result.scalar_one()

    # --- ASSERTIONS (the 16 anchor mutations) ------------------------------

    storage = local_storage  # the LocalStorageProvider from the fixture
    old_vrt_key = vrt_db_state["expected_vrt_key"]
    vrt_key = vrt_asset.asset_uri

    # [1] Storage write: regeneration publishes an immutable generation key
    # and reaps the prior live object only after the catalog switch commits.
    assert vrt_key == (
        f"rasters/{vrt_db_state['vrt_dataset_id']}/generations/"
        f"{generation.id}/source.vrt"
    )
    assert await storage.exists(vrt_key), (
        f"Expected VRT file to exist at {vrt_key} after regenerate_vrt"
    )
    assert not await storage.exists(old_vrt_key)

    # [2] Storage read-back: bytes are non-empty AND rasterio can re-open the
    # VRT from disk and read its metadata.
    vrt_bytes = await storage.get(vrt_key)
    assert len(vrt_bytes) > 0
    vrt_abs_path = local_storage.base_dir / vrt_key
    with rasterio.open(str(vrt_abs_path)) as src:
        assert src.count == 1  # single band, matches source
        assert src.crs is not None
        assert src.crs.to_epsg() == 4326

    # [3] vrt_asset.status == "ready"
    assert vrt_asset.status == "ready", (
        f"Expected status='ready', got {vrt_asset.status!r}"
    )

    # [4] vrt_asset.crs_wkt is populated (non-None, WGS84 WKT)
    assert vrt_asset.crs_wkt is not None
    assert "WGS" in vrt_asset.crs_wkt or "4326" in vrt_asset.crs_wkt

    # [5] vrt_asset.epsg == 4326
    assert vrt_asset.epsg == 4326

    # [6] vrt_asset.band_count == 1
    assert vrt_asset.band_count == 1

    # [7] width and height are populated and > 0
    assert vrt_asset.width is not None and vrt_asset.width > 0
    assert vrt_asset.height is not None and vrt_asset.height > 0

    # [8] sha256 is populated, 64 chars, AND matches storage content hash
    assert vrt_asset.sha256 is not None
    assert len(vrt_asset.sha256) == 64  # hex digest
    expected_sha = hashlib.sha256(vrt_bytes).hexdigest()
    assert vrt_asset.sha256 == expected_sha, (
        f"sha256 mismatch: asset={vrt_asset.sha256}, storage={expected_sha}"
    )

    # [9] size_bytes > 0
    assert vrt_asset.size_bytes is not None and vrt_asset.size_bytes > 0

    # [10] last_regenerated_at is populated
    assert vrt_asset.last_regenerated_at is not None

    # [11] current_generation_id is cleared after completion
    assert vrt_asset.current_generation_id is None

    # [12] job.status == "complete"
    assert job.status == "complete", (
        f"Expected job status='complete', got {job.status!r}"
    )

    # [13] job.dataset_id points at the VRT dataset
    assert job.dataset_id == uuid.UUID(vrt_db_state["vrt_dataset_id"])

    # [14] VrtGeneration row has status="completed", duration_seconds > 0,
    # completed_at populated, source_count == 2, triggered_by == "system"
    assert generation.status == "completed"
    assert generation.duration_seconds is not None
    assert generation.duration_seconds > 0
    assert generation.completed_at is not None
    assert generation.source_count == 2
    assert generation.triggered_by == "system"  # default kwarg in regenerate_vrt

    # [15] vrt_record.spatial_extent is populated (the ST_GeomFromText update landed)
    # spatial_extent is a Geometry column; its post-load value is a WKB string or
    # a geoalchemy2 Geometry element. Just assert non-None.
    assert vrt_record.spatial_extent is not None

    # [16] feat(#1267): the owning dataset's last_refreshed_at is stamped in
    # the same transaction as the generation swap, at the generation's own
    # completed_at instant — not a separate now() call.
    assert vrt_dataset.last_refreshed_at is not None
    assert vrt_dataset.last_refreshed_at == generation.completed_at

    # [17] fix(#1329 follow-up): the swap rolls tile_cache_version in the
    # same transaction as the pointer swap, like every other refresh door.
    # The URL `v=` buster and the raster meta cache key both read it, so an
    # unbumped swap leaves pre-swap tiles valid until cache TTLs expire.
    assert vrt_dataset.tile_cache_version == pre_tile_cache_version + 1

    # --- BONUS: Rasterio re-open + bounds sanity check ---------------------
    # (per CONTEXT.md Claude's Discretion + RESEARCH.md recommendation)
    with rasterio.open(str(vrt_abs_path)) as src:
        bounds = src.bounds
        assert bounds.left is not None and bounds.right is not None
        # At least one pixel of extent
        assert bounds.right > bounds.left
        assert bounds.top > bounds.bottom

    # [17] fix(#1327): this delivery staged no member set (the legacy shape
    # this test exercises carries none), so the task built from the live links
    # and applied nothing to them.
    assert generation.staged_source_ids is None
    assert await _linked_source_ids(session, vrt_db_state["vrt_dataset_id"]) == list(
        vrt_db_state["source_dataset_ids"]
    )


# ---------------------------------------------------------------------------
# fix(#1327): staged source-link mutation.
#
# add_vrt_source/remove_vrt_source record the intended member set on the
# VrtGeneration row and leave vrt_source_links alone; regenerate_vrt builds
# from that set and applies it in the same transaction as the artifact swap.
# The invariant these tests pin: vrt_source_links never describes a composition
# the served VRT does not have.
# ---------------------------------------------------------------------------


async def _linked_source_ids(session, vrt_dataset_id) -> list[uuid.UUID]:
    """The VRT's member set as the catalog states it, in position order."""
    result = await session.execute(
        text(
            "SELECT source_dataset_id FROM catalog.vrt_source_links "
            "WHERE vrt_dataset_id = :vrt_id ORDER BY position ASC"
        ),
        {"vrt_id": str(vrt_dataset_id)},
    )
    return [row.source_dataset_id for row in result.fetchall()]


def _clone_source_tif(source_tifs: dict, tmp_path: Path, name: str) -> str:
    """A THIRD TIF on disk, byte-identical to the fixture's first.

    Its own key, not a second reference to an existing one: a build handed the
    same path twice could legitimately collapse it, and these tests count
    sources in the stored VRT to prove which member set the build read.
    """
    origin = next(iter(source_tifs.values()))
    asset_uri = f"rasters/{name}/source.cog.tif"
    dest = tmp_path / "storage" / asset_uri
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(origin.read_bytes())
    return asset_uri


async def _add_extra_source(session, asset_uri: str) -> uuid.UUID:
    """Another ready raster source, NOT linked to any VRT.

    Reuses the fixture's pixel content: these tests are about which members a
    build and an apply agree on, not about pixel values.
    """
    from app.modules.catalog.datasets.domain.models import Dataset, Record
    from app.processing.raster.models import RasterAsset

    record = Record(
        title=f"Staged source {uuid.uuid4().hex[:6]}",
        record_type="raster_dataset",
        record_status="published",
        visibility="private",
    )
    session.add(record)
    await session.flush()
    dataset = Dataset(
        record_id=record.id,
        table_name=f"raster_src_{record.id.hex[:16]}",
        source_format="geotiff",
        srid=4326,
    )
    session.add(dataset)
    await session.flush()
    session.add(
        RasterAsset(
            dataset_id=dataset.id,
            asset_uri=asset_uri,
            storage_backend="local",
            status="ready",
            band_count=1,
            epsg=4326,
            width=64,
            height=64,
            dtype="uint8",
        )
    )
    await session.flush()
    return dataset.id


async def _stage_generation(
    session, vrt_db_state: dict, staged_source_ids
) -> uuid.UUID:
    """A pending generation carrying a staged member set, owned by the asset.

    Mirrors exactly what add_vrt_source/remove_vrt_source commit: the staged
    set on the generation, the asset pointing at it, and vrt_source_links
    untouched.
    """
    from app.processing.raster.models import RasterAsset, VrtGeneration

    generation = VrtGeneration(
        vrt_dataset_id=uuid.UUID(vrt_db_state["vrt_dataset_id"]),
        status="pending",
        started_at=datetime.now(timezone.utc),
        source_count=len(staged_source_ids),
        staged_source_ids=[str(sid) for sid in staged_source_ids],
        triggered_by="test",
    )
    session.add(generation)
    await session.flush()

    asset = (
        await session.execute(
            select(RasterAsset).where(RasterAsset.id == vrt_db_state["vrt_asset_id"])
        )
    ).scalar_one()
    asset.status = "regenerating"
    asset.current_generation_id = generation.id
    await session.commit()
    return generation.id


async def test_staged_set_lands_with_the_artifact_it_describes(
    test_db_session,
    vrt_db_state: dict,
    source_tifs: dict,
    tmp_path: Path,
    local_storage,
    quicklook_stub,
    clean_tables,
):
    """A successful run applies the staged set, and the VRT contains it.

    Three properties that only mean something together: the build read the
    STAGED members (3 sources in the stored XML, not the 2 still linked), the
    link table now equals the staged set in staged order, and built_from — the
    published statement of what the artifact holds — agrees with both.

    Invoked through ``regenerate_vrt_staged``, the task name a staged mutation
    is actually delivered under (fix(#1327 codex P1)), so this exercises the
    production entrypoint rather than the shared body behind it.
    """
    from app.processing.ingest.tasks import regenerate_vrt_staged
    from app.processing.raster.models import RasterAsset, VrtGeneration

    session = test_db_session
    vrt_id = vrt_db_state["vrt_dataset_id"]
    original_ids = list(vrt_db_state["source_dataset_ids"])

    added_id = await _add_extra_source(
        session, _clone_source_tif(source_tifs, tmp_path, "src-3")
    )
    staged = [*original_ids, added_id]
    generation_id = await _stage_generation(session, vrt_db_state, staged)

    # Pre-state: the catalog still describes the VRT actually being served.
    assert await _linked_source_ids(session, vrt_id) == original_ids

    await regenerate_vrt_staged.func(
        job_id=vrt_db_state["job_id"],
        attempt_id=vrt_db_state["attempt_id"],
        vrt_dataset_id=vrt_id,
        generation_id=str(generation_id),
    )

    assert await _linked_source_ids(session, vrt_id) == staged

    vrt_asset = (
        await session.execute(
            select(RasterAsset).where(RasterAsset.id == vrt_db_state["vrt_asset_id"])
        )
    ).scalar_one()
    await session.refresh(vrt_asset)
    assert vrt_asset.status == "ready"
    assert set(vrt_asset.built_from) == {str(sid) for sid in staged}

    generation = (
        await session.execute(
            select(VrtGeneration).where(VrtGeneration.id == generation_id)
        )
    ).scalar_one()
    await session.refresh(generation)
    assert generation.status == "completed"

    # The bytes themselves: the stored VRT references one source per staged
    # member, which is what proves the BUILD used the staged set rather than
    # the links it was about to overwrite.
    vrt_xml = (await local_storage.get(vrt_asset.asset_uri)).decode()
    assert vrt_xml.count("<SourceFilename") == len(staged)


async def test_death_before_swap_leaves_source_links_untouched(
    test_db_session,
    vrt_db_state: dict,
    source_tifs: dict,
    tmp_path: Path,
    local_storage,
    quicklook_stub,
    clean_tables,
    monkeypatch: pytest.MonkeyPatch,
):
    """The whole point of #1327: an attempt that dies changes no membership.

    The build blows up after the generation is claimed — the window that used
    to leave the catalog permanently ahead of the served bytes. Nothing about
    the VRT's stated composition moves.
    """
    from app.processing.ingest.tasks import regenerate_vrt
    from app.processing.raster.models import RasterAsset, VrtGeneration

    session = test_db_session
    vrt_id = vrt_db_state["vrt_dataset_id"]
    original_ids = list(vrt_db_state["source_dataset_ids"])

    added_id = await _add_extra_source(
        session, _clone_source_tif(source_tifs, tmp_path, "src-3")
    )
    staged = [*original_ids, added_id]
    generation_id = await _stage_generation(session, vrt_db_state, staged)

    monkeypatch.setattr(
        "app.processing.ingest.tasks_vrt.build_vrt",
        MagicMock(side_effect=RuntimeError("gdalbuildvrt died mid-attempt")),
    )

    with pytest.raises(RuntimeError):
        await regenerate_vrt.func(
            job_id=vrt_db_state["job_id"],
            attempt_id=vrt_db_state["attempt_id"],
            vrt_dataset_id=vrt_id,
            generation_id=str(generation_id),
        )

    assert await _linked_source_ids(session, vrt_id) == original_ids

    vrt_asset = (
        await session.execute(
            select(RasterAsset).where(RasterAsset.id == vrt_db_state["vrt_asset_id"])
        )
    ).scalar_one()
    await session.refresh(vrt_asset)
    assert vrt_asset.status == "failed"
    assert vrt_asset.current_generation_id is None
    # Nothing was published, so nothing claims the added member.
    assert vrt_asset.built_from is None

    generation = (
        await session.execute(
            select(VrtGeneration).where(VrtGeneration.id == generation_id)
        )
    ).scalar_one()
    await session.refresh(generation)
    assert generation.status == "failed"
    # The intent survives for diagnosis; only a task owning the asset pointer
    # could apply it, and this one no longer does.
    assert generation.staged_source_ids == [str(sid) for sid in staged]


async def test_staged_source_deleted_mid_flight_fails_the_run_cleanly(
    test_db_session,
    vrt_db_state: dict,
    source_tifs: dict,
    tmp_path: Path,
    local_storage,
    quicklook_stub,
    clean_tables,
):
    """Set drift in the other direction: a staged member disappears.

    A LIVE link pins its source (ON DELETE RESTRICT); a staged id does not,
    so the stage->apply window is the one place a member can vanish. The run
    must fail whole rather than publish a mosaic missing a member it claims.
    """
    from app.modules.catalog.datasets.domain.models import Record
    from app.processing.ingest.tasks import regenerate_vrt
    from app.processing.raster.models import RasterAsset

    session = test_db_session
    vrt_id = vrt_db_state["vrt_dataset_id"]
    original_ids = list(vrt_db_state["source_dataset_ids"])

    added_id = await _add_extra_source(
        session, _clone_source_tif(source_tifs, tmp_path, "src-3")
    )
    staged = [*original_ids, added_id]
    generation_id = await _stage_generation(session, vrt_db_state, staged)

    # The staged source goes away before the attempt runs.
    await session.execute(
        text(
            "DELETE FROM catalog.records WHERE id = "
            "(SELECT record_id FROM catalog.datasets WHERE id = :id)"
        ),
        {"id": str(added_id)},
    )
    await session.commit()
    assert (
        await session.execute(select(Record).where(Record.id == added_id))
    ).scalar_one_or_none() is None

    with pytest.raises(ValueError, match="no longer available"):
        await regenerate_vrt.func(
            job_id=vrt_db_state["job_id"],
            attempt_id=vrt_db_state["attempt_id"],
            vrt_dataset_id=vrt_id,
            generation_id=str(generation_id),
        )

    assert await _linked_source_ids(session, vrt_id) == original_ids
    vrt_asset = (
        await session.execute(
            select(RasterAsset).where(RasterAsset.id == vrt_db_state["vrt_asset_id"])
        )
    ).scalar_one()
    await session.refresh(vrt_asset)
    assert vrt_asset.status == "failed"


async def test_null_staged_set_builds_from_live_links_and_applies_nothing(
    test_db_session,
    vrt_db_state: dict,
    source_tifs: dict,
    tmp_path: Path,
    local_storage,
    quicklook_stub,
    clean_tables,
):
    """Backfill semantics: a generation that stages nothing changes nothing.

    A plain regenerate, and every generation queued before the column existed,
    take this path — build from the live links, apply no link change — with an
    unlinked raster sitting right there to prove the build did not wander.
    """
    from app.processing.ingest.tasks import regenerate_vrt
    from app.processing.raster.models import RasterAsset, VrtGeneration

    session = test_db_session
    vrt_id = vrt_db_state["vrt_dataset_id"]
    original_ids = list(vrt_db_state["source_dataset_ids"])

    unlinked_id = await _add_extra_source(
        session, _clone_source_tif(source_tifs, tmp_path, "src-3")
    )

    generation = VrtGeneration(
        vrt_dataset_id=uuid.UUID(vrt_id),
        status="pending",
        started_at=datetime.now(timezone.utc),
        source_count=len(original_ids),
        triggered_by="test",
    )
    session.add(generation)
    await session.flush()
    asset = (
        await session.execute(
            select(RasterAsset).where(RasterAsset.id == vrt_db_state["vrt_asset_id"])
        )
    ).scalar_one()
    asset.current_generation_id = generation.id
    await session.commit()
    generation_id = generation.id

    await regenerate_vrt.func(
        job_id=vrt_db_state["job_id"],
        attempt_id=vrt_db_state["attempt_id"],
        vrt_dataset_id=vrt_id,
        generation_id=str(generation_id),
    )

    assert await _linked_source_ids(session, vrt_id) == original_ids
    await session.refresh(asset)
    assert asset.status == "ready"
    assert set(asset.built_from) == {str(sid) for sid in original_ids}
    assert str(unlinked_id) not in asset.built_from


async def test_applying_a_staged_set_is_idempotent(test_db_session, vrt_db_state: dict):
    """Re-applying the same set is a no-op — what makes a retry safe.

    Also pins the reason apply is an upsert rather than a delete-and-insert:
    a member that survives the change keeps its ``created_at``, so "linked
    since" is not reset by an unrelated add or removal.
    """
    from app.processing.ingest.tasks_vrt import apply_staged_source_links
    from app.processing.raster.models import VrtSourceLink

    session = test_db_session
    vrt_id = uuid.UUID(vrt_db_state["vrt_dataset_id"])
    kept_id, dropped_id = vrt_db_state["source_dataset_ids"]
    added_id = await _add_extra_source(session, "rasters/src-1/source.cog.tif")
    staged = [added_id, kept_id]

    async def _rows():
        result = await session.execute(
            select(VrtSourceLink)
            .where(VrtSourceLink.vrt_dataset_id == vrt_id)
            .order_by(VrtSourceLink.position)
        )
        return list(result.scalars().all())

    before = {row.source_dataset_id: row.created_at for row in await _rows()}

    await apply_staged_source_links(session, vrt_id, staged)
    await session.commit()
    first = await _rows()
    assert [row.source_dataset_id for row in first] == staged
    assert [row.position for row in first] == [0, 1]
    assert dropped_id not in {row.source_dataset_id for row in first}
    kept_row = next(row for row in first if row.source_dataset_id == kept_id)
    assert kept_row.created_at == before[kept_id], (
        "a surviving member must keep its link identity across an apply"
    )

    await apply_staged_source_links(session, vrt_id, staged)
    await session.commit()
    second = await _rows()
    assert [(row.id, row.source_dataset_id, row.position) for row in second] == [
        (row.id, row.source_dataset_id, row.position) for row in first
    ]
