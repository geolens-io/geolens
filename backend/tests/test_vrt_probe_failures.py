"""VRT creation and regeneration when a probe child fails.

The seam check asks the probe child whether the built VRT's SRS is in
degrees. A child that times out or fails must fail the build: the correction
it would have gated may be needed, and a VRT published without it can sit a
world away from its pixels. The quicklooks render one size per child, so a
failed 512 px render keeps the 256 px one, as rendering in-process did.

The real child runs for every other read. The builds use the real
gdalbuildvrt and local storage from ``test_regenerate_vrt_integration``.
"""

import json
import sys
import uuid

import pytest
from sqlalchemy import func, select

from app.processing.raster import probe
from tests.factories import get_user_id
from tests.test_regenerate_vrt_integration import (  # noqa: F401 -- fixtures
    local_storage,
    quicklook_stub,
    source_tifs,
    vrt_db_state,
)

_STALL = "import time; time.sleep(8)"
_FAIL = "import sys; print('{}'); sys.exit(1)"


def _fail_op(monkeypatch, failing, script: str = _FAIL) -> None:
    """Make the child fail for the ops ``failing(op, args)`` names."""
    real = probe._command

    def _command(op, *args):
        if failing(op, args):
            return [sys.executable, "-c", script]
        return real(op, *args)

    monkeypatch.setattr(probe, "_command", _command)


def _crs_probe_fails(monkeypatch, how: str) -> None:
    if how == "stalls":
        monkeypatch.setattr(probe, "CRS_FACTS_TIMEOUT_SECONDS", 1)
    _fail_op(
        monkeypatch,
        lambda op, _args: op == "crs-facts",
        _STALL if how == "stalls" else _FAIL,
    )


def _large_quicklook_fails(monkeypatch) -> None:
    _fail_op(
        monkeypatch,
        lambda op, args: op == "quicklooks" or (op == "quicklook" and args[1] == "512"),
    )


async def _vrt_count(session) -> int:
    from app.modules.catalog.datasets.domain.models import Record

    return await session.scalar(
        select(func.count()).where(Record.record_type == "vrt_dataset")
    )


async def _create_vrt(session, state: dict, storage, monkeypatch) -> None:
    from app.processing.ingest.tasks_vrt import ingest_vrt

    # Creation imports get_storage at call time rather than at module level.
    monkeypatch.setattr("app.platform.storage.get_storage", lambda: storage)

    await ingest_vrt.func(
        job_id=state["job_id"],
        user_id=str(await get_user_id(session, "admin")),
        source_dataset_ids=json.dumps([str(i) for i in state["source_dataset_ids"]]),
        vrt_type="mosaic",
        resolution_strategy="finest",
        attempt_id=state["attempt_id"],
    )


async def _refreshed(session, model, row_id):
    row = (await session.execute(select(model).where(model.id == row_id))).scalar_one()
    await session.refresh(row)
    return row


@pytest.mark.parametrize("how", ["fails", "stalls"])
async def test_a_failed_crs_probe_fails_regeneration_and_publishes_nothing(
    test_db_session,
    vrt_db_state,  # noqa: F811
    local_storage,  # noqa: F811
    quicklook_stub,  # noqa: F811
    clean_tables,
    monkeypatch,
    how,
):
    from app.platform.jobs.models import IngestJob
    from app.processing.ingest.tasks import regenerate_vrt
    from app.processing.raster.models import RasterAsset

    _crs_probe_fails(monkeypatch, how)

    with pytest.raises(probe.RasterProbeError):
        await regenerate_vrt.func(
            job_id=vrt_db_state["job_id"],
            attempt_id=vrt_db_state["attempt_id"],
            vrt_dataset_id=vrt_db_state["vrt_dataset_id"],
        )

    asset = await _refreshed(test_db_session, RasterAsset, vrt_db_state["vrt_asset_id"])
    assert asset.asset_uri == vrt_db_state["expected_vrt_key"]
    assert asset.status == "failed"
    generations = local_storage.base_dir / "rasters" / vrt_db_state["vrt_dataset_id"]
    assert not list(generations.rglob("*.vrt"))
    job = await _refreshed(
        test_db_session, IngestJob, uuid.UUID(vrt_db_state["job_id"])
    )
    assert job.status == "failed"


@pytest.mark.parametrize("how", ["fails", "stalls"])
async def test_a_failed_crs_probe_fails_creation_and_publishes_nothing(
    test_db_session,
    vrt_db_state,  # noqa: F811
    local_storage,  # noqa: F811
    quicklook_stub,  # noqa: F811
    clean_tables,
    monkeypatch,
    how,
):
    from app.platform.jobs.models import IngestJob

    before = await _vrt_count(test_db_session)
    _crs_probe_fails(monkeypatch, how)

    with pytest.raises(probe.RasterProbeError):
        await _create_vrt(test_db_session, vrt_db_state, local_storage, monkeypatch)

    assert await _vrt_count(test_db_session) == before
    assert not list(local_storage.base_dir.rglob("*.vrt"))
    job = await _refreshed(
        test_db_session, IngestJob, uuid.UUID(vrt_db_state["job_id"])
    )
    assert job.status == "failed"
    assert job.dataset_id is None


async def test_a_failed_large_quicklook_keeps_the_small_one_on_regeneration(
    test_db_session,
    vrt_db_state,  # noqa: F811
    local_storage,  # noqa: F811
    clean_tables,
    monkeypatch,
):
    from app.processing.ingest.tasks import regenerate_vrt
    from app.processing.raster.models import RasterAsset

    before = await _refreshed(
        test_db_session, RasterAsset, vrt_db_state["vrt_asset_id"]
    )
    old_small, old_large = before.quicklook_256_uri, before.quicklook_512_uri
    _large_quicklook_fails(monkeypatch)

    await regenerate_vrt.func(
        job_id=vrt_db_state["job_id"],
        attempt_id=vrt_db_state["attempt_id"],
        vrt_dataset_id=vrt_db_state["vrt_dataset_id"],
    )

    asset = await _refreshed(test_db_session, RasterAsset, vrt_db_state["vrt_asset_id"])
    assert asset.status == "ready"
    assert asset.quicklook_256_uri != old_small
    assert await local_storage.exists(asset.quicklook_256_uri)
    assert asset.quicklook_512_uri == old_large


async def test_a_failed_large_quicklook_keeps_the_small_one_on_creation(
    test_db_session,
    vrt_db_state,  # noqa: F811
    local_storage,  # noqa: F811
    clean_tables,
    monkeypatch,
):
    from app.platform.jobs.models import IngestJob
    from app.processing.raster.models import RasterAsset

    _large_quicklook_fails(monkeypatch)

    await _create_vrt(test_db_session, vrt_db_state, local_storage, monkeypatch)

    job = await _refreshed(
        test_db_session, IngestJob, uuid.UUID(vrt_db_state["job_id"])
    )
    assert job.status == "complete"
    asset = (
        await test_db_session.execute(
            select(RasterAsset).where(RasterAsset.dataset_id == job.dataset_id)
        )
    ).scalar_one()
    assert asset.quicklook_256_uri is not None
    assert await local_storage.exists(asset.quicklook_256_uri)
    assert asset.quicklook_512_uri is None
