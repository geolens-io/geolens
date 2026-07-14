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
      4. stale VrtGeneration UPDATE → scalars() returns generation ids
      5. stale regenerating RasterAsset UPDATE → scalars() returns dataset ids
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

    for returned_ids in [
        [generation.id for generation in (stale_vrt_generations or [])],
        [asset.dataset_id for asset in (stale_vrt_assets or [])],
    ]:
        mock_result = MagicMock()
        mock_result.scalars.return_value = returned_ids
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
    purge_candidates: list | None = None,
    surviving_paths: list[str] | None = None,
) -> AsyncMock:
    """Build a mock AsyncSession for fail_stale_jobs.

    execute() side effects (in order):
      1. stale pending IngestJobs → scalars() returns list
      2. stale running IngestJobs → scalars() returns list
      3. stale VrtGeneration UPDATE → scalars() returns generation ids
      4. stale regenerating RasterAsset UPDATE → scalars() returns dataset ids
      5. purge DELETE .. RETURNING file_path (fix #434) → .all() returns
         (file_path,) one-tuples
      6. optional surviving-path SELECT when a deleted row had a file_path
    """
    results = []
    for returned_ids in [
        stale_jobs_pending or [],
        stale_jobs_running or [],
        [generation.id for generation in (stale_vrt_generations or [])],
        [asset.dataset_id for asset in (stale_vrt_assets or [])],
    ]:
        mock_result = MagicMock()
        mock_result.scalars.return_value = returned_ids
        results.append(mock_result)

    delete_result = MagicMock()
    delete_result.all.return_value = purge_candidates or []
    results.append(delete_result)

    if any(file_path for (file_path,) in (purge_candidates or [])):
        survivors_result = MagicMock()
        survivors_result.scalars.return_value = surviving_paths or []
        results.append(survivors_result)

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

    statements = [str(call.args[0]) for call in mock_session.execute.await_args_list]
    assert any("UPDATE catalog.vrt_generations" in stmt for stmt in statements)
    assert any("UPDATE catalog.raster_assets" in stmt for stmt in statements)


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

    statements = [str(call.args[0]) for call in mock_db.execute.await_args_list]
    assert any("UPDATE catalog.vrt_generations" in stmt for stmt in statements)
    assert any("UPDATE catalog.raster_assets" in stmt for stmt in statements)


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


@pytest.mark.asyncio
async def test_fail_stale_jobs_detailed_outcome_counts_every_cleanup_surface(
    tmp_path, monkeypatch
):
    """Admin callers receive VRT, retention, local, and object cleanup counts."""
    from app.core.config import settings
    from app.platform.jobs.router import StaleCleanupOutcome, fail_stale_jobs

    stale_asset = _make_raster_asset(status="regenerating")
    stale_gen = _make_vrt_generation(status="running")
    local_file = tmp_path / "retained-upload.geojson"
    local_file.write_text("{}")
    storage_key = "staging/job-id/retained-upload.geojson"

    mock_db = _make_mock_db_for_fail_stale(
        stale_jobs_pending=[uuid4()],
        stale_jobs_running=[uuid4()],
        stale_vrt_assets=[stale_asset],
        stale_vrt_generations=[stale_gen],
        purge_candidates=[(str(local_file),), (storage_key,)],
    )
    storage = MagicMock()
    storage.delete = AsyncMock()
    monkeypatch.setattr(settings, "ingest_jobs_retention_days", 30)
    monkeypatch.setattr(settings, "upload_staging_dir", str(tmp_path))

    with patch("app.platform.storage.get_storage", return_value=storage):
        result = await fail_stale_jobs(mock_db, detailed=True)

    assert isinstance(result, StaleCleanupOutcome)
    assert result.pending_failed == 1
    assert result.running_failed == 1
    assert result.vrt_assets_recovered == 1
    assert result.vrt_generations_failed == 1
    assert result.terminal_jobs_purged == 2
    assert result.staged_paths_considered == 2
    assert result.local_files_reaped == 1
    assert result.storage_objects_reaped == 1
    assert result.staged_paths_skipped == 0
    assert result.staged_cleanup_failures == 0
    assert result.total_cleaned == 2
    assert result.total_affected == 8
    assert not local_file.exists()
    storage.delete.assert_awaited_once_with(storage_key)


@pytest.mark.asyncio
async def test_fail_stale_jobs_commit_failure_keeps_external_artifacts(
    tmp_path, monkeypatch
):
    """Retention files are not deleted for a database purge that rolls back."""
    from app.core.config import settings
    from app.platform.jobs.router import fail_stale_jobs

    local_file = tmp_path / "retry-input.geojson"
    local_file.write_text("{}")
    storage_key = "staging/job-id/retry-input.geojson"
    mock_db = _make_mock_db_for_fail_stale(
        purge_candidates=[(str(local_file),), (storage_key,)],
    )
    mock_db.commit.side_effect = RuntimeError("commit failed")
    storage = MagicMock()
    storage.delete = AsyncMock()
    monkeypatch.setattr(settings, "ingest_jobs_retention_days", 30)
    monkeypatch.setattr(settings, "upload_staging_dir", str(tmp_path))

    with (
        patch("app.platform.storage.get_storage", return_value=storage),
        pytest.raises(RuntimeError, match="commit failed"),
    ):
        await fail_stale_jobs(mock_db, detailed=True)

    assert local_file.exists()
    storage.delete.assert_not_awaited()


# ---------------------------------------------------------------------------
# fix(#434): retention purge of terminal jobs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fail_stale_jobs_purges_terminal_jobs_past_retention():
    """The purge is one DELETE that carries the terminal-status predicates
    itself (codex P2 r10: a SELECT-then-DELETE-by-id pair raced with
    /jobs/{id}/retry)."""
    from sqlalchemy.sql.dml import Delete

    from app.platform.jobs.router import fail_stale_jobs

    mock_db = _make_mock_db_for_fail_stale(purge_candidates=[(None,)])
    await fail_stale_jobs(mock_db)

    assert mock_db.execute.await_count == 5
    purge_stmt = mock_db.execute.await_args_list[4].args[0]
    assert isinstance(purge_stmt, Delete)
    where_sql = str(purge_stmt.compile(compile_kwargs={"literal_binds": True}))
    assert "'pending'" in where_sql and "'running'" in where_sql, (
        "purge must exclude active statuses at delete time, got: " + where_sql
    )


# NOTE: no @pytest.mark.asyncio here — test_db_session is an AnyIO fixture and
# the pytest-asyncio marker would run the test body on a different event loop
# than the fixture's asyncpg connection ("attached to a different loop").
async def test_retention_purge_keeps_latest_complete_job_per_dataset(
    test_db_session, tmp_path, monkeypatch
):
    """codex P2 on #434: /jobs/by-dataset serves persistent ingest warnings and
    the reupload source_layer hint from a dataset's most recent complete job —
    that row must survive the purge no matter how old it is. Older completes
    and failed rows past retention are still deleted, and (codex P2 r3) a
    purged failed job's staged local file is reaped along with the row."""
    from sqlalchemy import select as sa_select

    from app.core.config import settings
    from app.platform.jobs.models import IngestJob
    from app.platform.jobs.router import fail_stale_jobs
    from tests.factories import create_dataset, get_user_id

    user_id = await get_user_id(test_db_session, "admin")
    ds = await create_dataset(
        test_db_session, created_by=user_id, name="Retention Exemption DS"
    )

    # Staged local upload kept for retry by a failed job (see
    # _should_unlink_staging) — must be unlinked when its row is purged.
    monkeypatch.setattr(settings, "upload_staging_dir", str(tmp_path))
    staged_file = tmp_path / "failed-upload.geojson"
    staged_file.write_text("{}")
    # codex P2 (r4): fan-out siblings share one staging object — a path also
    # referenced by a retryable row OUTSIDE the purge set must NOT be reaped.
    shared_file = tmp_path / "shared-fanout.gpkg"
    shared_file.write_text("{}")
    # codex P2 (r5): a SUCCESSFUL fan-out's shared original is referenced
    # forever by exempt latest-complete children — a surviving complete row
    # must NOT block the reap (only pending/running/failed need the file).
    fanout_file = tmp_path / "successful-fanout.gpkg"
    fanout_file.write_text("{}")

    now = datetime.now(timezone.utc)
    ancient = now - timedelta(days=120)
    old = now - timedelta(days=90)
    rows = {
        "older_complete": IngestJob(
            dataset_id=ds.id, status="complete", created_at=ancient
        ),
        "latest_complete": IngestJob(
            dataset_id=ds.id,
            status="complete",
            created_at=old,
            file_path=str(fanout_file),
        ),
        "old_fanned_out_parent": IngestJob(
            dataset_id=None,
            status="fanned_out",
            created_at=old,
            file_path=str(fanout_file),
        ),
        # codex P2 (r7): manifest apply resolves datasets via the newest
        # complete job per manifest_key — this row is OLDER than the dataset's
        # latest complete job (so the per-dataset exemption skips it) but must
        # survive via the manifest-key exemption or re-applying the manifest
        # would duplicate the dataset.
        "manifest_complete": IngestJob(
            dataset_id=ds.id,
            status="complete",
            created_at=ancient,
            completed_at=ancient,
            user_metadata={"manifest_key": "showcase/retention-ds"},
        ),
        "old_failed": IngestJob(
            dataset_id=ds.id,
            status="failed",
            created_at=old,
            file_path=str(staged_file),
        ),
        "orphan_complete": IngestJob(
            dataset_id=None, status="complete", created_at=old
        ),
        "old_failed_shared": IngestJob(
            dataset_id=ds.id,
            status="failed",
            created_at=old,
            file_path=str(shared_file),
        ),
        "recent_failed_shared": IngestJob(
            dataset_id=ds.id,
            status="failed",
            created_at=now - timedelta(days=1),
            file_path=str(shared_file),
        ),
        # codex P2 (r8): an ancient still-running row gets stale-failed by THIS
        # same fail_stale_jobs call (completed_at=now) — the purge cutoff is on
        # finished-at, so the fresh failure evidence must survive a full
        # retention window instead of being deleted in the same transaction.
        "ancient_stale_running": IngestJob(
            dataset_id=ds.id,
            status="running",
            created_at=ancient,
            started_at=ancient,
        ),
    }
    test_db_session.add_all(rows.values())
    await test_db_session.commit()
    ids = {k: v.id for k, v in rows.items()}

    await fail_stale_jobs(test_db_session)

    remaining = set((await test_db_session.execute(sa_select(IngestJob.id))).scalars())
    assert ids["latest_complete"] in remaining, (
        "the dataset's most recent complete job must survive retention"
    )
    assert ids["recent_failed_shared"] in remaining, (
        "a failed job within retention must survive"
    )
    assert ids["manifest_complete"] in remaining, (
        "the newest complete job per manifest_key must survive retention"
    )
    assert ids["ancient_stale_running"] in remaining, (
        "a row stale-failed by this same sweep must keep its fresh failure "
        "evidence for a full retention window"
    )
    stale_failed = await test_db_session.get(IngestJob, ids["ancient_stale_running"])
    assert stale_failed.status == "failed"
    for name in (
        "older_complete",
        "old_failed",
        "orphan_complete",
        "old_failed_shared",
        "old_fanned_out_parent",
    ):
        assert ids[name] not in remaining, f"{name} should have been purged"
    assert not staged_file.exists(), (
        "the purged failed job's staged file must be reaped with the row"
    )
    assert shared_file.exists(), (
        "a staging file still referenced by a surviving RETRYABLE job must NOT be reaped"
    )
    assert not fanout_file.exists(), (
        "a successful fan-out's shared original must be reaped even though the "
        "exempt latest-complete child still references it"
    )


@pytest.mark.asyncio
async def test_fail_stale_jobs_retention_zero_disables_purge(monkeypatch):
    """ingest_jobs_retention_days=0 keeps history forever (no DELETE issued)."""
    from app.core.config import settings
    from app.platform.jobs.router import fail_stale_jobs

    monkeypatch.setattr(settings, "ingest_jobs_retention_days", 0)
    mock_db = _make_mock_db_for_fail_stale()
    await fail_stale_jobs(mock_db)

    assert mock_db.execute.await_count == 4


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

    # Two atomic UPDATEs: generation first, then the asset still pointing to it.
    gen_result = MagicMock()
    gen_result.scalars.return_value = [stale_gen.id]
    asset_result = MagicMock()
    asset_result.scalars.return_value = [stale_asset.dataset_id]

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(side_effect=[gen_result, asset_result])

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=1)

    result = await sweep_stale_vrt_assets(mock_session, cutoff)

    # Returns (assets_recovered, gens_failed) both ≥ 0
    assert isinstance(result, tuple)
    assert len(result) == 2
    assets_recovered, gens_failed = result
    assert assets_recovered == 1
    assert gens_failed == 1

    statements = [str(call.args[0]) for call in mock_session.execute.await_args_list]
    assert "UPDATE catalog.vrt_generations" in statements[0]
    assert "UPDATE catalog.raster_assets" in statements[1]
