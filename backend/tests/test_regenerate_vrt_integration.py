"""Integration test for regenerate_vrt task — behavioral anchor for Phase 219.

This test is DELIBERATELY slow and real:
- Generates 2 real GeoTIFFs via rasterio
- Creates real PostGIS rows (Record, Dataset, RasterAsset, VrtGeneration, IngestJob, vrt_source_links)
- Invokes gdalbuildvrt as a subprocess
- Writes the result via a real LocalStorageProvider
- Reads back and asserts on 15 state mutations

Phase 219 extracts 3 helpers from regenerate_vrt. Any drift in behavior will
fail this test — that is the whole point of shipping this phase first.

DO NOT mock subprocess, rasterio, or async_session in this file. Use mocks
ONLY for generate_quicklook (see D-05) and optionally the non-fatal cache
invalidation / embedding deferral calls.
"""

import hashlib
import uuid
from pathlib import Path

import pytest
import rasterio
from sqlalchemy import select, text

# Fixture helpers (D-01: direct cross-test-file import)
from tests.test_raster_ingest import _write_tmp_tif

pytestmark = pytest.mark.asyncio  # strict mode requires explicit marker


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
def local_storage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Create a real LocalStorageProvider rooted at tmp_path / "storage" and
    patch it into app.ingest.tasks.get_storage.

    Also overrides settings.upload_staging_dir so resolve_vrt_source_path
    (called inside regenerate_vrt at tasks.py:2200) resolves source asset_uris
    to paths under the same tmp_path / "storage" root.
    """
    from app.config import settings
    from app.storage.local import LocalStorageProvider

    storage_root = tmp_path / "storage"
    storage_root.mkdir(parents=True, exist_ok=True)

    provider = LocalStorageProvider(base_dir=str(storage_root))

    # Patch the top-level import in app.ingest.tasks — NOT app.storage.get_storage.
    # tasks.py:19 does `from app.storage import get_storage`, rebinding the name
    # inside the tasks module; patching the source module has no effect.
    monkeypatch.setattr("app.ingest.tasks.get_storage", lambda: provider)

    # Override upload_staging_dir so resolve_vrt_source_path (vrt.py:16-26) resolves
    # source asset_uris to files under our storage root. Without this override,
    # gdalbuildvrt gets production paths that do not exist and fails.
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

    # Patch at the ingest.tasks binding, not the source module
    monkeypatch.setattr("app.ingest.tasks.generate_quicklook", _stub)
    return _stub


@pytest.fixture
async def vrt_db_state(
    test_db_session,  # from conftest.py
    source_tifs: dict[str, Path],
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
    from app.datasets.models import Dataset, Record
    from app.jobs.models import IngestJob
    from app.raster.models import RasterAsset

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
    """Full integration test: invoke regenerate_vrt and assert on 15 state mutations.

    This is the behavioral anchor for Phase 219's refactor. Any drift in the
    observable outcome of regenerate_vrt will fail this test — that's the
    whole point of shipping this before Phase 219.

    The 15 assertions cover every DB + storage mutation that regenerate_vrt
    performs in the happy path. See CONTEXT.md D-03 for the enumerated list.
    """
    from app.datasets.models import Record
    from app.ingest.tasks import regenerate_vrt
    from app.jobs.models import IngestJob
    from app.raster.models import RasterAsset, VrtGeneration

    session = test_db_session

    # --- INVOKE ------------------------------------------------------------
    # Call the underlying coroutine via Task.func, bypassing the queue.
    await regenerate_vrt.func(
        job_id=vrt_db_state["job_id"],
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

    # --- ASSERTIONS (the 15 anchor mutations) ------------------------------

    storage = local_storage  # the LocalStorageProvider from the fixture
    vrt_key = vrt_db_state["expected_vrt_key"]

    # [1] Storage write: the VRT key exists after the task.
    assert await storage.exists(vrt_key), (
        f"Expected VRT file to exist at {vrt_key} after regenerate_vrt"
    )

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

    # --- BONUS: Rasterio re-open + bounds sanity check ---------------------
    # (per CONTEXT.md Claude's Discretion + RESEARCH.md recommendation)
    with rasterio.open(str(vrt_abs_path)) as src:
        bounds = src.bounds
        assert bounds.left is not None and bounds.right is not None
        # At least one pixel of extent
        assert bounds.right > bounds.left
        assert bounds.top > bounds.bottom
