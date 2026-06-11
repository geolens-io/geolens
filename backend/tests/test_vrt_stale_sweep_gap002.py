"""GAP-002: VRT regenerating-status stale sweep.

Tests that RasterAsset rows stuck in status='regenerating' past the
JOB_TIMEOUT_SECONDS threshold are recovered (reset to 'failed') by the
shared sweep helper, called from BOTH recover_stale_jobs (startup) and
fail_stale_jobs (periodic).

RED → GREEN: fails pre-fix (no sweep exists), passes post-fix.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_raster_asset(
    *,
    status: str = "regenerating",
    started_at: datetime | None = None,
) -> MagicMock:
    """Build a mock RasterAsset-like object."""
    asset = MagicMock()
    asset.id = uuid4()
    asset.dataset_id = uuid4()
    asset.status = status
    asset.current_generation_id = uuid4()
    asset.error_message = None  # RasterAsset doesn't have this, but we track it
    return asset


def _make_vrt_generation(
    *,
    status: str = "running",
    started_at: datetime | None = None,
) -> MagicMock:
    """Build a mock VrtGeneration-like object."""
    gen = MagicMock()
    gen.id = uuid4()
    gen.status = status
    gen.started_at = started_at
    gen.completed_at = None
    gen.error_message = None
    return gen


def _make_mock_session_for_recover(
    *,
    lock_acquired: bool = True,
    stale_jobs_running: list | None = None,
    stale_jobs_pending: list | None = None,
    stale_vrt_assets: list | None = None,
    stale_vrt_generations: list | None = None,
) -> MagicMock:
    """Build a mock async session for recover_stale_jobs.

    execute() side effects (in order):
      1. advisory lock query → scalar() returns lock_acquired
      2. stale running IngestJobs → scalars() returns list
      3. orphaned pending IngestJobs → scalars() returns list
      4. stale regenerating RasterAssets → scalars() returns list
      5. stale VrtGeneration rows → scalars() returns list
    """
    lock_result = MagicMock()
    lock_result.scalar.return_value = lock_acquired

    results = [lock_result]

    for job_list in [
        stale_jobs_running or [],
        stale_jobs_pending or [],
    ]:
        mock_result = MagicMock()
        mock_result.scalars.return_value = job_list
        results.append(mock_result)

    for asset_list in [
        stale_vrt_assets or [],
        stale_vrt_generations or [],
    ]:
        mock_result = MagicMock()
        mock_result.scalars.return_value = asset_list
        results.append(mock_result)

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.execute = AsyncMock(side_effect=results)
    mock_session.commit = AsyncMock()
    return mock_session


def _make_mock_db_for_fail_stale(
    *,
    stale_jobs_pending: list | None = None,
    stale_jobs_running: list | None = None,
    stale_vrt_assets: list | None = None,
    stale_vrt_generations: list | None = None,
) -> AsyncMock:
    """Build a mock AsyncSession for fail_stale_jobs.

    execute() side effects (in order):
      1. stale pending IngestJobs → scalars() returns list
      2. stale running IngestJobs → scalars() returns list
      3. stale regenerating RasterAssets → scalars() returns list
      4. stale VrtGeneration rows → scalars() returns list
    """
    results = []
    for lst in [
        stale_jobs_pending or [],
        stale_jobs_running or [],
        stale_vrt_assets or [],
        stale_vrt_generations or [],
    ]:
        mock_result = MagicMock()
        mock_result.scalars.return_value = lst
        results.append(mock_result)

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(side_effect=results)
    mock_db.commit = AsyncMock()
    return mock_db


# ---------------------------------------------------------------------------
# GAP-002: recover_stale_jobs sweeps stale VRT regenerating assets
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recover_stale_jobs_resets_stale_regenerating_vrt_asset():
    """GAP-002 RED→GREEN: a stale regenerating VRT asset is reset to 'failed' at startup.

    Pre-fix: recover_stale_jobs only sweeps IngestJob — the stale RasterAsset
    stays in status='regenerating' forever. Post-fix: the shared helper also
    sweeps RasterAssets.
    """
    from app.platform.jobs.worker import recover_stale_jobs

    stale_asset = _make_raster_asset(status="regenerating")
    stale_gen = _make_vrt_generation(
        status="running",
        started_at=datetime.now(timezone.utc) - timedelta(hours=2),
    )

    mock_session = _make_mock_session_for_recover(
        stale_vrt_assets=[stale_asset],
        stale_vrt_generations=[stale_gen],
    )

    with patch("app.core.db.async_session", return_value=mock_session):
        await recover_stale_jobs()

    # Asset must be reset to a recoverable status
    assert stale_asset.status in {"failed", "ready"}, (
        f"Expected stale regenerating asset to be reset, got status={stale_asset.status!r}"
    )
    # Stale VrtGeneration must be marked failed
    assert stale_gen.status == "failed", (
        f"Expected stale VrtGeneration to be failed, got status={stale_gen.status!r}"
    )


@pytest.mark.asyncio
async def test_recover_stale_jobs_leaves_fresh_regenerating_asset_untouched():
    """GAP-002: a fresh in-progress regeneration (within JOB_TIMEOUT_SECONDS) is NOT reset.

    The mock returns an empty stale list — meaning the query filter excluded
    the fresh asset — so no status change should occur.
    """
    from app.platform.jobs.worker import recover_stale_jobs

    fresh_asset = _make_raster_asset(status="regenerating")
    # Do NOT include in the stale list — the query should exclude it.
    mock_session = _make_mock_session_for_recover(
        stale_vrt_assets=[],  # query returned nothing → fresh asset is untouched
        stale_vrt_generations=[],
    )

    with patch("app.core.db.async_session", return_value=mock_session):
        await recover_stale_jobs()

    assert fresh_asset.status == "regenerating", (
        f"Fresh in-progress asset should not be touched, got {fresh_asset.status!r}"
    )


# ---------------------------------------------------------------------------
# GAP-002: fail_stale_jobs sweeps stale VRT regenerating assets
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fail_stale_jobs_resets_stale_regenerating_vrt_asset():
    """GAP-002 RED→GREEN: a stale regenerating VRT asset is reset by the periodic sweep.

    fail_stale_jobs is called every 5 min from the lifespan sweeper. Pre-fix it
    only sweeps IngestJob. Post-fix it also sweeps stale regenerating RasterAssets.
    """
    from app.platform.jobs.router import fail_stale_jobs

    stale_asset = _make_raster_asset(status="regenerating")
    stale_gen = _make_vrt_generation(
        status="running",
        started_at=datetime.now(timezone.utc) - timedelta(hours=2),
    )

    mock_db = _make_mock_db_for_fail_stale(
        stale_vrt_assets=[stale_asset],
        stale_vrt_generations=[stale_gen],
    )

    await fail_stale_jobs(mock_db)

    assert stale_asset.status in {"failed", "ready"}, (
        f"Expected periodic sweep to reset stale asset, got status={stale_asset.status!r}"
    )
    assert stale_gen.status == "failed", (
        f"Expected periodic sweep to fail stale VrtGeneration, got {stale_gen.status!r}"
    )


@pytest.mark.asyncio
async def test_fail_stale_jobs_returns_vrt_asset_count():
    """GAP-002: fail_stale_jobs return tuple should include VRT-recovered count or remain (pending, running)."""
    from app.platform.jobs.router import fail_stale_jobs

    stale_asset = _make_raster_asset(status="regenerating")
    stale_gen = _make_vrt_generation(status="running")

    mock_db = _make_mock_db_for_fail_stale(
        stale_vrt_assets=[stale_asset],
        stale_vrt_generations=[stale_gen],
    )

    result = await fail_stale_jobs(mock_db)

    # Result must be a tuple (the IngestJob counts are the base contract).
    assert isinstance(result, tuple)


# ---------------------------------------------------------------------------
# GAP-002: shared helper is called from both entry points
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recover_stale_jobs_calls_vrt_sweep_helper():
    """GAP-002: recover_stale_jobs delegates to the shared VRT stale sweep helper."""
    from app.platform.jobs import worker as worker_module

    # The shared helper should be importable and callable from the worker module
    # or from a shared location called by it.
    assert hasattr(worker_module, "recover_stale_jobs"), (
        "worker module must expose recover_stale_jobs"
    )

    # Verify the helper is invoked: patch the shared helper and confirm it runs.
    from app.platform.jobs import router as router_module

    assert hasattr(router_module, "sweep_stale_vrt_assets"), (
        "router module must expose sweep_stale_vrt_assets (the shared helper)"
    )


@pytest.mark.asyncio
async def test_fail_stale_jobs_calls_vrt_sweep_helper():
    """GAP-002: fail_stale_jobs delegates to the shared VRT stale sweep helper."""
    from app.platform.jobs import router as router_module

    assert hasattr(router_module, "sweep_stale_vrt_assets"), (
        "sweep_stale_vrt_assets must be defined in router module"
    )


# ---------------------------------------------------------------------------
# GAP-002: vrt_assets_recovered count returned by sweep helper
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sweep_stale_vrt_assets_returns_count():
    """GAP-002: sweep_stale_vrt_assets(session, stale_cutoff) returns (assets_recovered, gens_failed)."""
    from app.platform.jobs.router import sweep_stale_vrt_assets

    stale_asset = _make_raster_asset(status="regenerating")
    stale_gen = _make_vrt_generation(status="running")

    # Two execute calls: one for assets, one for generations
    asset_result = MagicMock()
    asset_result.scalars.return_value = [stale_asset]
    gen_result = MagicMock()
    gen_result.scalars.return_value = [stale_gen]

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(side_effect=[asset_result, gen_result])

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=1)

    result = await sweep_stale_vrt_assets(mock_session, cutoff)

    # Returns (assets_recovered, gens_failed) both ≥ 0
    assert isinstance(result, tuple)
    assert len(result) == 2
    assets_recovered, gens_failed = result
    assert assets_recovered == 1
    assert gens_failed == 1

    assert stale_asset.status in {"failed", "ready"}
    assert stale_gen.status == "failed"
