"""GAP-002 / feat(#1267): VRT regenerating-status stale sweep.

Tests that RasterAsset rows stuck in status='regenerating' past the
JOB_TIMEOUT_SECONDS threshold are reconciled by the shared sweep helper,
called from BOTH recover_stale_jobs (startup) and fail_stale_jobs (periodic).

feat(#1267): reconciliation restores the asset to 'ready' (not 'failed') —
the dead attempt never touched the published pointer (asset_uri, sha256,
...), so the VRT is still serving exactly what it served before the attempt
started. Only the attempt's own VrtGeneration row is marked 'failed'.

RED → GREEN: fails pre-fix (no sweep exists), passes post-fix.
"""

from datetime import datetime, timedelta, timezone
import uuid
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool


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
    vrt_dataset_id: uuid.UUID | None = None,
) -> MagicMock:
    """Build a mock VrtGeneration-like object."""
    gen = MagicMock()
    gen.id = uuid4()
    gen.vrt_dataset_id = vrt_dataset_id or uuid4()
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
    stale_vrt_assets_degraded: list | None = None,
    stale_vrt_generations: list | None = None,
) -> MagicMock:
    """Build a mock async session for recover_stale_jobs.

    execute() side effects (in order):
      1. advisory lock query → scalar() returns lock_acquired
      2. stale running IngestJobs → scalars() returns list
      3. orphaned pending IngestJobs → scalars() returns list
      4. stale VrtGeneration UPDATE → all() returns (id, vrt_dataset_id) pairs
      5. composition-preserving RasterAsset UPDATE (-> 'ready') → scalars()
         returns dataset ids for ``stale_vrt_assets``
      6. composition-changed RasterAsset UPDATE (-> 'failed', fix(#1322
         review round 3)) → scalars() returns dataset ids for
         ``stale_vrt_assets_degraded``

    ``stale_vrt_assets`` and ``stale_vrt_assets_degraded`` are mock-level
    routing, not a re-implementation of the SQL discrimination — a test
    picks which of the two UPDATE results an asset's id lands in to state
    which branch it means to exercise. The real discrimination (built_from
    vs vrt_source_links) is proven against a live Postgres database in
    test_ingest_job_attempt_fencing.py and the composition-drift tests below.
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

    gen_result = MagicMock()
    gen_result.all.return_value = [
        (generation.id, generation.vrt_dataset_id)
        for generation in (stale_vrt_generations or [])
    ]
    results.append(gen_result)

    for asset_list in (stale_vrt_assets, stale_vrt_assets_degraded):
        mock_result = MagicMock()
        mock_result.scalars.return_value = [
            asset.dataset_id for asset in (asset_list or [])
        ]
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
    stale_vrt_assets_degraded: list | None = None,
    stale_vrt_generations: list | None = None,
    purge_candidates: list | None = None,
    surviving_paths: list[str] | None = None,
) -> AsyncMock:
    """Build a mock AsyncSession for fail_stale_jobs.

    execute() side effects (in order):
      1. stale UNBOUND pending IngestJobs (1h) → all() returns
         (id, user_metadata, created_by, status) — fix(#1556 review) widened
         this one RETURNING so the sweep can count the rows its CASE settled
         `cancelled` apart from the ones it failed
      2. stale BOUND pending IngestJobs (24h, fix(#1234)) → empty here
      3. stale running IngestJobs → all() returns the same triples
      3. stale VrtGeneration UPDATE → all() returns (id, vrt_dataset_id) pairs
      4. composition-preserving RasterAsset UPDATE (-> 'ready') → scalars()
         returns dataset ids for ``stale_vrt_assets``
      4b. composition-changed RasterAsset UPDATE (-> 'failed', fix(#1322
         review round 3)) → scalars() returns dataset ids for
         ``stale_vrt_assets_degraded``. See the recover-side helper's
         docstring for why this is mock-level routing, not the real SQL.
      4c. abandoned dataset_refresh_runs UPDATE (feat(#1219)) → scalars()
         returns cancelled run ids. Empty in these fixtures; the sweep has
         its own suite in test_dataset_refresh_runs.py.
      5. purge DELETE .. RETURNING (id, file_path, user_metadata) → .all()
         returns those three-tuples. fix(#1202 review r5) widened the
         RETURNING so the purge can also reap a completed presigned job's
         staging key. Callers may still pass (file_path,) one-tuples; they
         are normalized below so each test keeps stating only what it cares
         about.
      6. optional surviving-path SELECT when a deleted row had a file_path
    """
    results = []
    for index, returned_ids in enumerate(
        [
            stale_jobs_pending or [],
            # fix(#1234): the pending sweep is two clauses now — unbound rows at
            # 1h, then rows that bound bytes but never committed at 24h. These
            # fixtures exercise the first, so the second returns nothing.
            [],
            stale_jobs_running or [],
        ]
    ):
        mock_result = MagicMock()
        mock_result.scalars.return_value = returned_ids
        # fix(#1550 review): the three job sweeps RETURN (id, user_metadata,
        # created_by) now — the sweep is the last actor that can close an
        # embedding backfill's audit trail after a hard kill, and it needs the
        # run's own metadata to write a correlated entry. These fixtures carry
        # no backfill marker, so the audit emission is a no-op for them; the
        # shape still has to match or the counts read zero.
        #
        # fix(#1556 review): the UNBOUND half (index 0) carries a fourth column,
        # the status its CASE chose. These fixtures describe rows with no
        # `presigned` marker, so the status the database would have written is
        # `failed` — which is what keeps `pending_failed` reading 1 below.
        if index == 0:
            mock_result.all.return_value = [
                (job_id, None, None, "failed") for job_id in returned_ids
            ]
        else:
            mock_result.all.return_value = [
                (job_id, None, None) for job_id in returned_ids
            ]
        results.append(mock_result)

    # fix(#1709 review r7): the childless-`fanned_out` reconciliation runs
    # between the running-jobs sweep and the VRT sweep — a fan-out parent
    # whose dispatch died before its first child committed. It RETURNs ids
    # and reads them via .scalars(). No such parents in these fixtures, so
    # an empty result keeps each test stating only what it cares about; the
    # clause has its own coverage in test_job_cancel_fan_out.py.
    childless_fanout_result = MagicMock()
    childless_fanout_result.scalars.return_value = []
    results.append(childless_fanout_result)

    # feat(#1267): RETURNING widened to (id, vrt_dataset_id) — the storage
    # cleanup helper needs the pairing, so .all() replaces .scalars() here.
    gen_result = MagicMock()
    gen_result.all.return_value = [
        (generation.id, generation.vrt_dataset_id)
        for generation in (stale_vrt_generations or [])
    ]
    results.append(gen_result)

    for returned_ids in [
        [asset.dataset_id for asset in (stale_vrt_assets or [])],
        [asset.dataset_id for asset in (stale_vrt_assets_degraded or [])],
        # feat(#1219): the refresh-run sweep, between the VRT sweep and the
        # retention purge — TWO statements since fix(#1274 review): the
        # legacy-completion success recorder, then the abandonment cancel.
        # Both empty in these fixtures; the sweep has its own suite in
        # test_dataset_refresh_runs.py.
        [],
        [],
    ]:
        mock_result = MagicMock()
        mock_result.scalars.return_value = returned_ids
        results.append(mock_result)

    normalized_candidates = [
        row if len(row) == 3 else (uuid.uuid4(), row[0], None)
        for row in (purge_candidates or [])
    ]
    delete_result = MagicMock()
    delete_result.all.return_value = normalized_candidates
    results.append(delete_result)

    if any(file_path for (_id, file_path, _um) in normalized_candidates):
        survivors_result = MagicMock()
        survivors_result.scalars.return_value = surviving_paths or []
        results.append(survivors_result)

    # fix(#1202 review r8): the post-expiry presigned-staging sweep issues one
    # more SELECT after the purge. No candidates in these fixtures, so an empty
    # .all() keeps each test stating only what it cares about.
    post_expiry_result = MagicMock()
    post_expiry_result.all.return_value = []
    results.append(post_expiry_result)

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(side_effect=results)
    mock_db.commit = AsyncMock()
    return mock_db


# ---------------------------------------------------------------------------
# GAP-002: recover_stale_jobs sweeps stale VRT regenerating assets
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recover_stale_jobs_resets_stale_regenerating_vrt_asset():
    """GAP-002 RED→GREEN: a stale regenerating VRT asset is reconciled at startup.

    Pre-fix: recover_stale_jobs only sweeps IngestJob — the stale RasterAsset
    stays in status='regenerating' forever. Post-fix: the shared helper also
    sweeps RasterAssets, restoring 'ready' (feat(#1267)).
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
    stale_gen = _make_vrt_generation(
        status="running", vrt_dataset_id=stale_asset.dataset_id
    )
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
    # feat(#1267) / fix(#1322 review): 1 retention key + 3 VRT generation
    # keys, all reaped by _reap_committed_staged_paths AFTER db.commit()
    # succeeded — sweep_stale_vrt_assets itself only resolved the latter 3,
    # never deleting them.
    assert result.storage_objects_reaped == 4
    assert result.staged_paths_skipped == 0
    assert result.staged_cleanup_failures == 0
    assert result.total_cleaned == 2
    assert result.total_affected == 11
    assert not local_file.exists()

    # feat(#1267): the reconciled generation's own storage objects are
    # reaped best-effort alongside the retention-purge key — 3 more calls,
    # one per object regenerate_vrt could have written before the worker
    # died (source.vrt + 2 quicklooks), deleted even though none exist here.
    generation_base = f"rasters/{stale_gen.vrt_dataset_id}/generations/{stale_gen.id}"
    expected_keys = {
        storage_key,
        f"{generation_base}/source.vrt",
        f"{generation_base}/quicklook_256.png",
        f"{generation_base}/quicklook_512.png",
    }
    called_keys = {call.args[0] for call in storage.delete.await_args_list}
    assert called_keys == expected_keys


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


@pytest.mark.asyncio
async def test_fail_stale_jobs_commit_failure_keeps_stale_generation_storage_intact(
    monkeypatch,
):
    """fix(#1322 review): the inverse of the storage-failure test above — a
    reconciliation whose commit fails must leave a dead attempt's generation
    objects UNDELETED. sweep_stale_vrt_assets only resolves the keys; nothing
    may reap them until fail_stale_jobs's own db.commit() (which raises here,
    rolling the generation/asset UPDATEs back) has actually landed. Deleting
    anyway would leave a resumed 'dead' worker publishing to storage keys
    that no longer exist, behind an asset the rollback restored to
    'regenerating'."""
    from app.platform.jobs.router import fail_stale_jobs

    stale_asset = _make_raster_asset(status="regenerating")
    stale_gen = _make_vrt_generation(
        status="running", vrt_dataset_id=stale_asset.dataset_id
    )
    mock_db = _make_mock_db_for_fail_stale(
        stale_vrt_assets=[stale_asset],
        stale_vrt_generations=[stale_gen],
    )
    mock_db.commit.side_effect = RuntimeError("commit failed")
    storage = MagicMock()
    storage.delete = AsyncMock()

    with (
        patch("app.platform.storage.get_storage", return_value=storage),
        pytest.raises(RuntimeError, match="commit failed"),
    ):
        await fail_stale_jobs(mock_db, detailed=True)

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

    # 5 sweeps (the pending clause is two statements since fix(#1234)) + the
    # VRT asset UPDATE split into two (ready / degraded, fix(#1322 review
    # round 3)) + the refresh-run sweep's TWO statements (feat(#1219),
    # fix(#1274 review): legacy-completion recorder then abandonment cancel)
    # + the purge DELETE + the post-expiry staging SELECT.
    # fix(#1709 review r7): +1 — the childless-`fanned_out` reconciliation.
    assert mock_db.execute.await_count == 11
    # Indexes 7-8 are the refresh-run sweep now; the purge shifted to 9.
    # fix(#1709 review r7): +1 — the childless-`fanned_out` reconciliation
    # sits at index 3, between the running-jobs sweep and the VRT sweep.
    purge_stmt = mock_db.execute.await_args_list[9].args[0]
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

    # 5 sweeps (two pending clauses since fix(#1234)) plus the VRT asset
    # UPDATE split into two (ready / degraded, fix(#1322 review round 3))
    # plus the refresh-run sweep's two statements (feat(#1219), fix(#1274
    # review)) and no purge DELETE, plus the post-expiry staging SELECT,
    # which is independent of retention.
    # fix(#1709 review r7): +1 — the childless-`fanned_out` reconciliation.
    assert mock_db.execute.await_count == 10


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
    """GAP-002: sweep_stale_vrt_assets(session, stale_cutoff) returns
    (assets_recovered, gens_failed, storage_keys) — feat(#1267)/fix(#1322
    review) widened the tuple to carry resolved-not-deleted storage keys."""
    from app.platform.jobs.router import sweep_stale_vrt_assets

    stale_asset = _make_raster_asset(status="regenerating")
    stale_gen = _make_vrt_generation(status="running")

    # Three atomic UPDATEs: generation, then the asset split into a
    # composition-preserving branch (-> 'ready') and a composition-changed
    # branch (-> 'failed', fix(#1322 review round 3)).
    gen_result = MagicMock()
    gen_result.all.return_value = [(stale_gen.id, stale_gen.vrt_dataset_id)]
    ready_result = MagicMock()
    ready_result.scalars.return_value = [stale_asset.dataset_id]
    degraded_result = MagicMock()
    degraded_result.scalars.return_value = []

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(
        side_effect=[gen_result, ready_result, degraded_result]
    )

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=1)

    # No tenant context is bound in this unit test, so key RESOLUTION itself
    # (not just deletion — sweep_stale_vrt_assets never deletes anything,
    # fix(#1322 review)) short-circuits to an empty tuple rather than raising.
    # Either way this stays a 3-call contract: resolving/skipping keys is
    # pure Python, never a 4th db.execute().
    with patch("app.core.tenancy.is_multi_tenant", return_value=True):
        result = await sweep_stale_vrt_assets(mock_session, cutoff)

    assert isinstance(result, tuple)
    assert len(result) == 3
    assets_recovered, gens_failed, storage_keys = result
    assert assets_recovered == 1
    assert gens_failed == 1
    assert storage_keys == ()

    statements = [str(call.args[0]) for call in mock_session.execute.await_args_list]
    assert "UPDATE catalog.vrt_generations" in statements[0]
    assert "UPDATE catalog.raster_assets" in statements[1]
    assert "UPDATE catalog.raster_assets" in statements[2]
    assert (
        "vrt_generations.vrt_dataset_id IN (SELECT catalog.datasets.id" in statements[0]
    )
    assert "raster_assets.dataset_id IN (SELECT catalog.datasets.id" in statements[1]
    assert "raster_assets.dataset_id IN (SELECT catalog.datasets.id" in statements[2]


@pytest.mark.asyncio
async def test_sweep_stale_vrt_assets_preserves_single_tenant_sql_shape():
    from app.platform.jobs.router import sweep_stale_vrt_assets

    gen_result = MagicMock()
    gen_result.all.return_value = []
    ready_result = MagicMock()
    ready_result.scalars.return_value = []
    degraded_result = MagicMock()
    degraded_result.scalars.return_value = []
    session = AsyncMock()
    session.execute = AsyncMock(side_effect=[gen_result, ready_result, degraded_result])

    await sweep_stale_vrt_assets(
        session,
        datetime.now(timezone.utc) - timedelta(hours=1),
    )

    statements = [str(call.args[0]) for call in session.execute.await_args_list]
    assert "SELECT catalog.datasets.id" not in statements[0]
    assert "SELECT catalog.datasets.id" not in statements[1]
    assert "SELECT catalog.datasets.id" not in statements[2]


# ---------------------------------------------------------------------------
# feat(#1267): reconciliation restores 'ready', not 'failed', and reaps the
# dead attempt's own generation-scoped storage objects.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sweep_stale_vrt_assets_restores_ready_not_failed():
    """feat(#1267) / fix(#1322 review round 3): the FIRST asset UPDATE
    (composition-preserving) sets status='ready'; the SECOND (composition-
    changed) sets status='failed' — a dead attempt's own VrtGeneration row
    is what unconditionally records the failure, not the asset, UNLESS the
    catalog's declared composition moved out from under it."""
    from app.platform.jobs.router import sweep_stale_vrt_assets

    gen_result = MagicMock()
    gen_result.all.return_value = []
    ready_result = MagicMock()
    ready_result.scalars.return_value = []
    degraded_result = MagicMock()
    degraded_result.scalars.return_value = []
    session = AsyncMock()
    session.execute = AsyncMock(side_effect=[gen_result, ready_result, degraded_result])

    await sweep_stale_vrt_assets(
        session, datetime.now(timezone.utc) - timedelta(hours=1)
    )

    # fix(#1322 review round 4): _PRIOR_ATTEMPT_WAS_READY_SQL legitimately
    # mentions the literal 'failed' in its WHERE-clause comparison (the most
    # recent OTHER generation's status), so "'failed' not anywhere in the
    # statement" is no longer a valid signal — isolate the SET clause (the
    # part before WHERE) and check only that.
    ready_stmt = session.execute.await_args_list[1].args[0]
    ready_sql = str(ready_stmt.compile(compile_kwargs={"literal_binds": True}))
    ready_set_clause = ready_sql.split("WHERE", 1)[0]
    assert (
        "status='ready'" in ready_set_clause or "status = 'ready'" in ready_set_clause
    )
    assert "'failed'" not in ready_set_clause

    degraded_stmt = session.execute.await_args_list[2].args[0]
    degraded_sql = str(degraded_stmt.compile(compile_kwargs={"literal_binds": True}))
    degraded_set_clause = degraded_sql.split("WHERE", 1)[0]
    assert (
        "status='failed'" in degraded_set_clause
        or "status = 'failed'" in degraded_set_clause
    )
    assert "'ready'" not in degraded_set_clause
    # The two branches are mutually exclusive: the 2nd statement's predicate
    # is the exact negation of the 1st's combined composition + prior-ready
    # check.
    assert "NOT (" in degraded_sql
    # Both facts are present in both statements' WHERE clauses (the 2nd
    # negates their conjunction, not just one half).
    for where_sql in (ready_sql, degraded_sql):
        assert "vrt_source_links" in where_sql
        assert "vrt_generations" in where_sql


@pytest.mark.asyncio
async def test_sweep_stale_vrt_assets_resolves_but_never_deletes_storage():
    """fix(#1322 review): sweep_stale_vrt_assets RESOLVES a swept generation's
    immutable object keys (3rd tuple element) but must never call storage
    itself. Deleting before its caller's commit is durable can destroy a
    generation a rolled-back reconciliation still owns — see
    _reap_stale_generation_storage's docstring. No storage patch is installed
    here on purpose: any storage.* call inside the sweep would raise
    (get_storage() is uninitialized in this unit test) and fail the test."""
    from app.platform.jobs.router import sweep_stale_vrt_assets

    stale_gen_id = uuid4()
    stale_dataset_id = uuid4()

    gen_result = MagicMock()
    gen_result.all.return_value = [(stale_gen_id, stale_dataset_id)]
    ready_result = MagicMock()
    ready_result.scalars.return_value = [stale_dataset_id]
    degraded_result = MagicMock()
    degraded_result.scalars.return_value = []
    session = AsyncMock()
    session.execute = AsyncMock(side_effect=[gen_result, ready_result, degraded_result])

    result = await sweep_stale_vrt_assets(
        session, datetime.now(timezone.utc) - timedelta(hours=1)
    )

    base = f"rasters/{stale_dataset_id}/generations/{stale_gen_id}"
    assert result == (
        1,
        1,
        (
            f"{base}/source.vrt",
            f"{base}/quicklook_256.png",
            f"{base}/quicklook_512.png",
        ),
    )


@pytest.mark.asyncio
async def test_sweep_stale_vrt_assets_storage_failure_never_masks_reconciliation():
    """A storage backend that is unreachable must not stop the sweep from
    restoring the asset and failing the generation — key resolution is pure
    Python (no storage call), so reconciliation cannot be masked by it."""
    from app.platform.jobs.router import sweep_stale_vrt_assets

    gen_result = MagicMock()
    gen_result.all.return_value = [(uuid4(), uuid4())]
    ready_result = MagicMock()
    ready_result.scalars.return_value = [uuid4()]
    degraded_result = MagicMock()
    degraded_result.scalars.return_value = []
    session = AsyncMock()
    session.execute = AsyncMock(side_effect=[gen_result, ready_result, degraded_result])

    # No storage patch — get_storage() would raise RuntimeError
    # (uninitialized) if the sweep ever called it, which it must not.
    result = await sweep_stale_vrt_assets(
        session, datetime.now(timezone.utc) - timedelta(hours=1)
    )

    assert result[0] == 1
    assert result[1] == 1
    assert len(result[2]) == 3


# ---------------------------------------------------------------------------
# fix(#1322 review round 3): the discrimination is a STATE comparison
# (built_from vs the live vrt_source_links set), not a timing heuristic —
# these run against a real Postgres database so the actual
# _COMPOSITION_PRESERVED_SQL executes, not a mock standing in for it.
#
# fix(#1327) changed which of these branches real traffic reaches. Source
# add/remove now STAGE their member set on the VrtGeneration row and apply it
# only in the publish transaction, so a dead composition-changing attempt
# leaves vrt_source_links matching built_from and takes the restore branch —
# proven by test_sweep_restores_ready_for_a_dead_staged_mutation below. The
# drift cases that follow it did not go away, they changed owner: they are now
# the shapes the sweep must still refuse to call 'ready' — a row written before
# #1327, or any future writer of the link table outside a publish transaction.
# Keeping them is the point of a guard.
# ---------------------------------------------------------------------------


async def _make_vrt_with_generation(
    test_db_session,
    *,
    admin_id,
    built_from_dataset_ids,
    linked_dataset_ids,
    started_hours_ago: float = 2,
    staged_source_ids=None,
):
    """A VRT dataset with a dead 'regenerating' generation, whose published
    built_from and live vrt_source_links can be set independently — the
    exact fork the composition-preserving check has to tell apart.

    fix(#1327): ``staged_source_ids`` models a dead attempt of the staged
    kind — the member set the attempt intended to publish, recorded on the
    generation, with the link rows still describing what is being served.
    """
    from app.processing.raster.models import RasterAsset, VrtGeneration, VrtSourceLink
    from tests.factories import create_dataset

    vrt_dataset = await create_dataset(test_db_session, created_by=admin_id)
    generation = VrtGeneration(
        vrt_dataset_id=vrt_dataset.id,
        status="running",
        started_at=datetime.now(timezone.utc) - timedelta(hours=started_hours_ago),
        heartbeat_at=datetime.now(timezone.utc) - timedelta(hours=started_hours_ago),
        staged_source_ids=(
            None
            if staged_source_ids is None
            else [str(sid) for sid in staged_source_ids]
        ),
    )
    test_db_session.add(generation)
    await test_db_session.flush()

    asset = RasterAsset(
        dataset_id=vrt_dataset.id,
        asset_uri=f"rasters/{vrt_dataset.id}/source.vrt",
        status="regenerating",
        current_generation_id=generation.id,
        built_from={str(ds_id): "irrelevant" for ds_id in built_from_dataset_ids},
    )
    test_db_session.add(asset)

    for position, source_id in enumerate(linked_dataset_ids):
        test_db_session.add(
            VrtSourceLink(
                vrt_dataset_id=vrt_dataset.id,
                source_dataset_id=source_id,
                position=position,
            )
        )

    await test_db_session.commit()
    return vrt_dataset, generation, asset


async def test_sweep_restores_ready_when_composition_unchanged(test_db_session):
    """A pure dead regenerate (regenerate_vrt_endpoint never touches
    vrt_source_links) restores 'ready' — the existing, correct behavior."""
    from app.platform.jobs.router import sweep_stale_vrt_assets
    from tests.factories import create_dataset, get_user_id

    admin_id = await get_user_id(test_db_session, "admin")
    source = await create_dataset(test_db_session, created_by=admin_id)
    _vrt_dataset, generation, asset = await _make_vrt_with_generation(
        test_db_session,
        admin_id=admin_id,
        built_from_dataset_ids=[source.id],
        linked_dataset_ids=[source.id],
    )

    cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
    assets_recovered, gens_failed, _keys = await sweep_stale_vrt_assets(
        test_db_session, cutoff
    )
    await test_db_session.commit()

    assert (assets_recovered, gens_failed) == (1, 1)
    await test_db_session.refresh(asset)
    await test_db_session.refresh(generation)
    assert asset.status == "ready"
    assert asset.current_generation_id is None
    assert generation.status == "failed"


async def test_sweep_restores_ready_for_a_dead_staged_mutation(test_db_session):
    """fix(#1327): the converted case — a dead source add/remove.

    This is the scenario test_sweep_keeps_failed_when_source_was_added used to
    describe for live traffic: an add whose regeneration died before
    publishing. Staging moved the link write into the publish transaction, so
    the dead attempt left vrt_source_links exactly as built_from describes it
    and there is nothing to be honest ABOUT — the sweep restores 'ready' and
    the VRT keeps serving the composition it always had, with the requested
    addition simply not applied. The generation's staged set survives on the
    failed row; only a task owning the asset pointer could apply it, and this
    sweep just cleared that pointer.
    """
    from app.platform.jobs.router import sweep_stale_vrt_assets
    from tests.factories import create_dataset, get_user_id

    admin_id = await get_user_id(test_db_session, "admin")
    original = await create_dataset(test_db_session, created_by=admin_id)
    requested = await create_dataset(test_db_session, created_by=admin_id)
    _vrt_dataset, generation, asset = await _make_vrt_with_generation(
        test_db_session,
        admin_id=admin_id,
        built_from_dataset_ids=[original.id],  # published VRT: one member
        linked_dataset_ids=[original.id],  # catalog says the same thing
        staged_source_ids=[original.id, requested.id],  # the intent, unapplied
    )

    cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
    assets_recovered, gens_failed, _keys = await sweep_stale_vrt_assets(
        test_db_session, cutoff
    )
    await test_db_session.commit()

    assert (assets_recovered, gens_failed) == (1, 1)
    await test_db_session.refresh(asset)
    await test_db_session.refresh(generation)
    assert asset.status == "ready"
    assert asset.current_generation_id is None
    assert generation.status == "failed"
    assert generation.staged_source_ids == [str(original.id), str(requested.id)]


async def test_sweep_keeps_failed_when_source_was_removed(test_db_session):
    """fix(#1322 review round 3): a link set that shrank without the artifact
    following it. built_from still names the removed source — the published
    VRT still contains it — so restoring 'ready' would hide that the catalog's
    stated composition (1 source) no longer matches what is actually being
    served (2 sources).

    fix(#1327): remove_vrt_source no longer produces this state (it stages the
    post-removal set instead of deleting the link up front), so what this pins
    now is the guard, not the mechanism: a row left drifted by pre-#1327 code
    or any unforeseen writer of the link table still must not be called
    'ready'."""
    from app.platform.jobs.router import sweep_stale_vrt_assets
    from tests.factories import create_dataset, get_user_id

    admin_id = await get_user_id(test_db_session, "admin")
    kept = await create_dataset(test_db_session, created_by=admin_id)
    removed = await create_dataset(test_db_session, created_by=admin_id)
    _vrt_dataset, generation, asset = await _make_vrt_with_generation(
        test_db_session,
        admin_id=admin_id,
        built_from_dataset_ids=[kept.id, removed.id],  # published VRT has both
        linked_dataset_ids=[kept.id],  # catalog link to `removed` already gone
    )

    cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
    assets_recovered, gens_failed, _keys = await sweep_stale_vrt_assets(
        test_db_session, cutoff
    )
    await test_db_session.commit()

    assert (assets_recovered, gens_failed) == (1, 1)
    await test_db_session.refresh(asset)
    await test_db_session.refresh(generation)
    assert asset.status == "failed", (
        "restoring 'ready' here would hide that the served VRT still "
        "contains a source the catalog no longer lists"
    )
    assert asset.current_generation_id is None  # a retry is still triggerable
    assert generation.status == "failed"


async def test_sweep_keeps_failed_when_source_was_added(test_db_session):
    """The mirror case: the catalog claims 2 sources while the published VRT
    (built_from) was only ever assembled from 1. Same drift, opposite
    direction — still not safe to call 'ready'.

    fix(#1327): also no longer produced by add_vrt_source; kept for the same
    reason as its sibling above."""
    from app.platform.jobs.router import sweep_stale_vrt_assets
    from tests.factories import create_dataset, get_user_id

    admin_id = await get_user_id(test_db_session, "admin")
    original = await create_dataset(test_db_session, created_by=admin_id)
    added = await create_dataset(test_db_session, created_by=admin_id)
    _vrt_dataset, generation, asset = await _make_vrt_with_generation(
        test_db_session,
        admin_id=admin_id,
        built_from_dataset_ids=[original.id],  # published VRT has only this
        linked_dataset_ids=[original.id, added.id],  # catalog already claims 2
    )

    cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
    assets_recovered, gens_failed, _keys = await sweep_stale_vrt_assets(
        test_db_session, cutoff
    )
    await test_db_session.commit()

    assert (assets_recovered, gens_failed) == (1, 1)
    await test_db_session.refresh(asset)
    assert asset.status == "failed"
    assert asset.current_generation_id is None


async def test_sweep_keeps_failed_when_built_from_is_null(test_db_session):
    """A legacy pre-#1290 VRT has no built_from at all — the question
    cannot be answered from stored state, so the sweep must not guess
    'ready'. Same conservative branch as a proven mismatch."""
    from app.platform.jobs.router import sweep_stale_vrt_assets
    from app.processing.raster.models import RasterAsset, VrtGeneration
    from tests.factories import create_dataset, get_user_id

    admin_id = await get_user_id(test_db_session, "admin")
    vrt_dataset = await create_dataset(test_db_session, created_by=admin_id)
    generation = VrtGeneration(
        vrt_dataset_id=vrt_dataset.id,
        status="running",
        started_at=datetime.now(timezone.utc) - timedelta(hours=2),
        heartbeat_at=datetime.now(timezone.utc) - timedelta(hours=2),
    )
    test_db_session.add(generation)
    await test_db_session.flush()
    asset = RasterAsset(
        dataset_id=vrt_dataset.id,
        asset_uri=f"rasters/{vrt_dataset.id}/source.vrt",
        status="regenerating",
        current_generation_id=generation.id,
        built_from=None,
    )
    test_db_session.add(asset)
    await test_db_session.commit()

    cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
    await sweep_stale_vrt_assets(test_db_session, cutoff)
    await test_db_session.commit()

    await test_db_session.refresh(asset)
    assert asset.status == "failed"


# ---------------------------------------------------------------------------
# fix(#1322 review round 4): composition-preserving alone is not enough — the
# asset must also have PROVABLY been 'ready' (not 'failed') the instant this
# attempt was allowed to start. regenerate_vrt_endpoint's guard only rejects
# 'regenerating', so a caller may retry an already-'failed' asset; if that
# retry also dies, composition-preserving alone would restore 'ready' and
# erase a real failure the crash had nothing to do with.
# ---------------------------------------------------------------------------


async def test_sweep_keeps_failed_when_prior_attempt_was_failed(test_db_session):
    """The exact scenario from the finding: a genuine regeneration failure
    (generation 1, a real GDAL-style error — NOT this sweep's doing), then a
    user retry (generation 2) that is itself abandoned. Composition is
    unchanged throughout, so the composition check alone would restore
    'ready' — but generation 1's failure was never actually resolved, and
    the sweep must not manufacture a resolution that didn't happen."""
    from app.platform.jobs.router import sweep_stale_vrt_assets
    from app.processing.raster.models import RasterAsset, VrtGeneration, VrtSourceLink
    from tests.factories import create_dataset, get_user_id

    admin_id = await get_user_id(test_db_session, "admin")
    source = await create_dataset(test_db_session, created_by=admin_id)
    vrt_dataset = await create_dataset(test_db_session, created_by=admin_id)

    now = datetime.now(timezone.utc)
    # Generation 1: the ORIGINAL attempt, genuinely failed (e.g. a real GDAL
    # error) — not swept, not abandoned; explicitly terminal already.
    # heartbeat_at is set: fix(#1322 review round 5) — this is what
    # distinguishes a genuine build failure (the task claimed and ran) from
    # an enqueue failure (never reached the worker at all); see
    # test_sweep_restores_ready_when_prior_attempt_never_ran for that case.
    failed_generation = VrtGeneration(
        vrt_dataset_id=vrt_dataset.id,
        status="failed",
        started_at=now - timedelta(hours=5),
        heartbeat_at=now - timedelta(hours=4, minutes=56),
        completed_at=now - timedelta(hours=4, minutes=55),
        error_message="Simulated GDAL failure, unrelated to any crash",
    )
    test_db_session.add(failed_generation)
    await test_db_session.flush()

    # Generation 2: the user's retry (allowed — the endpoint only rejects
    # 'regenerating', not 'failed') — now abandoned by a worker crash.
    retry_generation = VrtGeneration(
        vrt_dataset_id=vrt_dataset.id,
        status="running",
        started_at=now - timedelta(hours=2),
        heartbeat_at=now - timedelta(hours=2),
    )
    test_db_session.add(retry_generation)
    await test_db_session.flush()

    asset = RasterAsset(
        dataset_id=vrt_dataset.id,
        asset_uri=f"rasters/{vrt_dataset.id}/source.vrt",
        status="regenerating",
        current_generation_id=retry_generation.id,
        # Composition unchanged — a pure retry, not a source add/remove.
        built_from={str(source.id): "irrelevant"},
    )
    test_db_session.add(asset)
    test_db_session.add(
        VrtSourceLink(
            vrt_dataset_id=vrt_dataset.id, source_dataset_id=source.id, position=0
        )
    )
    await test_db_session.commit()

    cutoff = now - timedelta(hours=1)
    assets_recovered, gens_failed, _keys = await sweep_stale_vrt_assets(
        test_db_session, cutoff
    )
    await test_db_session.commit()

    assert (assets_recovered, gens_failed) == (1, 1)
    await test_db_session.refresh(asset)
    await test_db_session.refresh(retry_generation)
    assert asset.status == "failed", (
        "restoring 'ready' here would manufacture a resolution generation 1's "
        "real failure never actually got"
    )
    assert asset.current_generation_id is None  # a further retry is still triggerable
    assert retry_generation.status == "failed"
    # generation 1 is untouched — it was already terminal before this sweep ran.
    await test_db_session.refresh(failed_generation)
    assert failed_generation.status == "failed"


async def test_sweep_restores_ready_when_prior_attempt_completed(test_db_session):
    """Companion coverage: a prior attempt that actually SUCCEEDED (not just
    'no prior attempt exists', which the composition-unchanged test above
    already covers) still lets a later dead, composition-preserving attempt
    restore 'ready'."""
    from app.platform.jobs.router import sweep_stale_vrt_assets
    from app.processing.raster.models import RasterAsset, VrtGeneration, VrtSourceLink
    from tests.factories import create_dataset, get_user_id

    admin_id = await get_user_id(test_db_session, "admin")
    source = await create_dataset(test_db_session, created_by=admin_id)
    vrt_dataset = await create_dataset(test_db_session, created_by=admin_id)

    now = datetime.now(timezone.utc)
    completed_generation = VrtGeneration(
        vrt_dataset_id=vrt_dataset.id,
        status="completed",
        started_at=now - timedelta(hours=5),
        heartbeat_at=now - timedelta(hours=4, minutes=56),
        completed_at=now - timedelta(hours=4, minutes=55),
    )
    test_db_session.add(completed_generation)
    await test_db_session.flush()

    dead_generation = VrtGeneration(
        vrt_dataset_id=vrt_dataset.id,
        status="running",
        started_at=now - timedelta(hours=2),
        heartbeat_at=now - timedelta(hours=2),
    )
    test_db_session.add(dead_generation)
    await test_db_session.flush()

    asset = RasterAsset(
        dataset_id=vrt_dataset.id,
        asset_uri=f"rasters/{vrt_dataset.id}/source.vrt",
        status="regenerating",
        current_generation_id=dead_generation.id,
        built_from={str(source.id): "irrelevant"},
    )
    test_db_session.add(asset)
    test_db_session.add(
        VrtSourceLink(
            vrt_dataset_id=vrt_dataset.id, source_dataset_id=source.id, position=0
        )
    )
    await test_db_session.commit()

    cutoff = now - timedelta(hours=1)
    assets_recovered, gens_failed, _keys = await sweep_stale_vrt_assets(
        test_db_session, cutoff
    )
    await test_db_session.commit()

    assert (assets_recovered, gens_failed) == (1, 1)
    await test_db_session.refresh(asset)
    assert asset.status == "ready"
    assert asset.current_generation_id is None


async def test_sweep_restores_ready_when_prior_attempt_never_ran(test_db_session):
    """fix(#1322 review round 5): a generation's status='failed' does not by
    itself mean the asset was not ready. regenerate_vrt_endpoint's own
    orphan-guard rollback marks a just-created generation 'failed' when the
    Procrastinate ENQUEUE itself throws — the task never reached a worker,
    and the SAME rollback reverts the asset to whatever it already was
    (commonly 'ready'). That generation's heartbeat_at is NULL forever: it
    is set in exactly one place, tasks_vrt.regenerate_vrt's Phase-1 claim,
    which an enqueue failure never reaches. A LATER, genuinely-run dead
    attempt must not read that unrelated enqueue failure as proof the
    asset was not ready."""
    from app.platform.jobs.router import sweep_stale_vrt_assets
    from app.processing.raster.models import RasterAsset, VrtGeneration, VrtSourceLink
    from tests.factories import create_dataset, get_user_id

    admin_id = await get_user_id(test_db_session, "admin")
    source = await create_dataset(test_db_session, created_by=admin_id)
    vrt_dataset = await create_dataset(test_db_session, created_by=admin_id)

    now = datetime.now(timezone.utc)
    # The enqueue failure: status='failed', but heartbeat_at was NEVER set —
    # the row was created and immediately failed by the SAME synchronous
    # request, without a worker ever claiming it.
    enqueue_failed_generation = VrtGeneration(
        vrt_dataset_id=vrt_dataset.id,
        status="failed",
        started_at=now - timedelta(hours=5),
        heartbeat_at=None,
        completed_at=now - timedelta(hours=5),
        error_message="Failed to queue VRT regeneration: connection refused",
    )
    test_db_session.add(enqueue_failed_generation)
    await test_db_session.flush()

    # A later attempt that DID actually run (heartbeat_at set) and is now
    # dead — the one being reconciled.
    dead_generation = VrtGeneration(
        vrt_dataset_id=vrt_dataset.id,
        status="running",
        started_at=now - timedelta(hours=2),
        heartbeat_at=now - timedelta(hours=2),
    )
    test_db_session.add(dead_generation)
    await test_db_session.flush()

    asset = RasterAsset(
        dataset_id=vrt_dataset.id,
        asset_uri=f"rasters/{vrt_dataset.id}/source.vrt",
        status="regenerating",
        current_generation_id=dead_generation.id,
        built_from={str(source.id): "irrelevant"},
    )
    test_db_session.add(asset)
    test_db_session.add(
        VrtSourceLink(
            vrt_dataset_id=vrt_dataset.id, source_dataset_id=source.id, position=0
        )
    )
    await test_db_session.commit()

    cutoff = now - timedelta(hours=1)
    assets_recovered, gens_failed, _keys = await sweep_stale_vrt_assets(
        test_db_session, cutoff
    )
    await test_db_session.commit()

    assert (assets_recovered, gens_failed) == (1, 1)
    await test_db_session.refresh(asset)
    assert asset.status == "ready", (
        "an enqueue failure that never reached a worker must not be read "
        "as proof the asset was not ready"
    )
    assert asset.current_generation_id is None
    # The unrelated enqueue-failure row is untouched by this sweep.
    await test_db_session.refresh(enqueue_failed_generation)
    assert enqueue_failed_generation.status == "failed"
    assert enqueue_failed_generation.heartbeat_at is None


# ---------------------------------------------------------------------------
# fix(#1322 review round 6): PROVEN-DEAD FIRST for a 'pending' generation
# specifically. started_at age alone cannot distinguish an orphan from a
# regeneration still legitimately sitting in Procrastinate's queue through a
# sustained worker backlog — queue waits are unbounded, the same reason
# stale_pending_clauses requires no_live_procrastinate_job for IngestJob. A
# 'running' generation's own heartbeat is sufficient proof on its own
# (covered by the existing tests above) and is NOT re-tested here.
# ---------------------------------------------------------------------------


async def _insert_live_procrastinate_job(session, *, generation_id) -> None:
    """A minimal 'todo' procrastinate_jobs row referencing a generation,
    mirroring the INSERT shape test_dataset_refresh_runs.py already uses for
    the identical class of live-job proof."""
    from sqlalchemy import text as sa_text

    await session.execute(sa_text("SET LOCAL search_path TO catalog, public"))
    await session.execute(
        sa_text(
            "INSERT INTO catalog.procrastinate_jobs "
            "(queue_name, task_name, args, status) "
            "VALUES ('raster', 'app.ingest.tasks.regenerate_vrt', "
            "jsonb_build_object('generation_id', CAST(:generation_id AS text)), "
            "'todo')"
        ),
        {"generation_id": str(generation_id)},
    )


async def _insert_legacy_live_procrastinate_job(session, *, vrt_dataset_id) -> None:
    """fix(#1322 review round 6, completed): a pre-upgrade delivery with no
    `generation_id` argument at all — the shape tasks_vrt.regenerate_vrt
    explicitly still accepts by adopting RasterAsset.current_generation_id.
    Carries only `vrt_dataset_id`, matching what such a delivery's args
    actually contain."""
    from sqlalchemy import text as sa_text

    await session.execute(sa_text("SET LOCAL search_path TO catalog, public"))
    await session.execute(
        sa_text(
            "INSERT INTO catalog.procrastinate_jobs "
            "(queue_name, task_name, args, status) "
            "VALUES ('raster', 'app.ingest.tasks.regenerate_vrt', "
            "jsonb_build_object('vrt_dataset_id', CAST(:vrt_dataset_id AS text)), "
            "'todo')"
        ),
        {"vrt_dataset_id": str(vrt_dataset_id)},
    )


async def test_sweep_leaves_pending_generation_alone_while_its_job_is_still_queued(
    test_db_session,
):
    """The exact scenario from the finding: a 'pending' generation with an
    old started_at (a sustained worker backlog, not an orphan) whose task is
    still genuinely queued in Procrastinate. Sweeping it would let the
    queued task's own Phase-1 claim (tasks_vrt.py) fail against a
    generation the sweep already flipped to 'failed', losing a valid
    regeneration that was always going to run."""
    from app.platform.jobs.router import sweep_stale_vrt_assets
    from app.processing.raster.models import RasterAsset, VrtGeneration
    from tests.factories import create_dataset, get_user_id

    admin_id = await get_user_id(test_db_session, "admin")
    vrt_dataset = await create_dataset(test_db_session, created_by=admin_id)

    now = datetime.now(timezone.utc)
    queued_generation = VrtGeneration(
        vrt_dataset_id=vrt_dataset.id,
        status="pending",
        started_at=now - timedelta(hours=2),  # old — a real backlog, not fresh
        heartbeat_at=None,  # never claimed — nothing has run yet
    )
    test_db_session.add(queued_generation)
    await test_db_session.flush()

    asset = RasterAsset(
        dataset_id=vrt_dataset.id,
        asset_uri=f"rasters/{vrt_dataset.id}/source.vrt",
        status="regenerating",
        current_generation_id=queued_generation.id,
        built_from={},
    )
    test_db_session.add(asset)
    await _insert_live_procrastinate_job(
        test_db_session, generation_id=queued_generation.id
    )
    await test_db_session.commit()

    cutoff = now - timedelta(hours=1)
    assets_recovered, gens_failed, _keys = await sweep_stale_vrt_assets(
        test_db_session, cutoff
    )
    await test_db_session.commit()

    assert (assets_recovered, gens_failed) == (0, 0), (
        "a generation whose task is still queued must never be reconciled"
    )
    await test_db_session.refresh(queued_generation)
    await test_db_session.refresh(asset)
    assert queued_generation.status == "pending"
    assert asset.status == "regenerating"
    assert asset.current_generation_id == queued_generation.id


async def test_sweep_reaps_pending_generation_once_its_job_is_proven_gone(
    test_db_session,
):
    """Companion coverage: the same old, never-claimed 'pending' generation
    IS swept once there is no live Procrastinate row for it at all — the
    genuinely-orphaned case (create-then-defer death, or a purged/expired
    queue row) this reconciliation exists to compensate for."""
    from app.platform.jobs.router import sweep_stale_vrt_assets
    from app.processing.raster.models import RasterAsset, VrtGeneration
    from tests.factories import create_dataset, get_user_id

    admin_id = await get_user_id(test_db_session, "admin")
    vrt_dataset = await create_dataset(test_db_session, created_by=admin_id)

    now = datetime.now(timezone.utc)
    orphaned_generation = VrtGeneration(
        vrt_dataset_id=vrt_dataset.id,
        status="pending",
        started_at=now - timedelta(hours=2),
        heartbeat_at=None,
    )
    test_db_session.add(orphaned_generation)
    await test_db_session.flush()

    asset = RasterAsset(
        dataset_id=vrt_dataset.id,
        asset_uri=f"rasters/{vrt_dataset.id}/source.vrt",
        status="regenerating",
        current_generation_id=orphaned_generation.id,
        built_from={},
    )
    test_db_session.add(asset)
    # No procrastinate_jobs row at all — no live job to prove.
    await test_db_session.commit()

    cutoff = now - timedelta(hours=1)
    assets_recovered, gens_failed, _keys = await sweep_stale_vrt_assets(
        test_db_session, cutoff
    )
    await test_db_session.commit()

    assert (assets_recovered, gens_failed) == (1, 1)
    await test_db_session.refresh(orphaned_generation)
    await test_db_session.refresh(asset)
    assert orphaned_generation.status == "failed"
    assert asset.status == "ready"  # built_from={} matches the empty link set
    assert asset.current_generation_id is None


async def test_sweep_leaves_pending_generation_alone_for_a_live_legacy_delivery(
    test_db_session,
):
    """fix(#1322 review round 6, completed): a pre-upgrade delivery queued
    with no `generation_id` argument is still live and will still adopt
    RasterAsset.current_generation_id once it runs (tasks_vrt.regenerate_vrt
    explicitly supports this for rolling-deploy safety). Correlating only by
    `generation_id` would be blind to it and let the sweep reap a generation
    that a live task is about to claim."""
    from app.platform.jobs.router import sweep_stale_vrt_assets
    from app.processing.raster.models import RasterAsset, VrtGeneration
    from tests.factories import create_dataset, get_user_id

    admin_id = await get_user_id(test_db_session, "admin")
    vrt_dataset = await create_dataset(test_db_session, created_by=admin_id)

    now = datetime.now(timezone.utc)
    queued_generation = VrtGeneration(
        vrt_dataset_id=vrt_dataset.id,
        status="pending",
        started_at=now - timedelta(hours=2),
        heartbeat_at=None,
    )
    test_db_session.add(queued_generation)
    await test_db_session.flush()

    asset = RasterAsset(
        dataset_id=vrt_dataset.id,
        asset_uri=f"rasters/{vrt_dataset.id}/source.vrt",
        status="regenerating",
        # This generation is CURRENTLY the asset's pointer — exactly what a
        # live legacy (args-less) delivery for this dataset would adopt.
        current_generation_id=queued_generation.id,
        built_from={},
    )
    test_db_session.add(asset)
    await _insert_legacy_live_procrastinate_job(
        test_db_session, vrt_dataset_id=vrt_dataset.id
    )
    await test_db_session.commit()

    cutoff = now - timedelta(hours=1)
    assets_recovered, gens_failed, _keys = await sweep_stale_vrt_assets(
        test_db_session, cutoff
    )
    await test_db_session.commit()

    assert (assets_recovered, gens_failed) == (0, 0), (
        "a live legacy delivery for this dataset, which will adopt exactly "
        "this generation, must never be reconciled"
    )
    await test_db_session.refresh(queued_generation)
    await test_db_session.refresh(asset)
    assert queued_generation.status == "pending"
    assert asset.status == "regenerating"
    assert asset.current_generation_id == queued_generation.id


async def test_sweep_reaps_pending_generation_when_no_legacy_delivery_is_live(
    test_db_session,
):
    """Companion coverage: a dataset with NO live procrastinate_jobs row at
    all (neither modern nor legacy-shaped) still gets its genuinely-orphaned
    pending generation reaped — the fallback correlation must not make the
    sweep permanently blind."""
    from app.platform.jobs.router import sweep_stale_vrt_assets
    from app.processing.raster.models import RasterAsset, VrtGeneration
    from tests.factories import create_dataset, get_user_id

    admin_id = await get_user_id(test_db_session, "admin")
    vrt_dataset = await create_dataset(test_db_session, created_by=admin_id)

    now = datetime.now(timezone.utc)
    orphaned_generation = VrtGeneration(
        vrt_dataset_id=vrt_dataset.id,
        status="pending",
        started_at=now - timedelta(hours=2),
        heartbeat_at=None,
    )
    test_db_session.add(orphaned_generation)
    await test_db_session.flush()

    asset = RasterAsset(
        dataset_id=vrt_dataset.id,
        asset_uri=f"rasters/{vrt_dataset.id}/source.vrt",
        status="regenerating",
        current_generation_id=orphaned_generation.id,
        built_from={},
    )
    test_db_session.add(asset)
    # No procrastinate_jobs row of any shape.
    await test_db_session.commit()

    cutoff = now - timedelta(hours=1)
    assets_recovered, gens_failed, _keys = await sweep_stale_vrt_assets(
        test_db_session, cutoff
    )
    await test_db_session.commit()

    assert (assets_recovered, gens_failed) == (1, 1)
    await test_db_session.refresh(orphaned_generation)
    await test_db_session.refresh(asset)
    assert orphaned_generation.status == "failed"
    assert asset.status == "ready"
    assert asset.current_generation_id is None


@pytest.mark.rls
async def test_sweep_stale_vrt_assets_cannot_mutate_another_tenant(
    multi_tenant_rls,
):
    """The tenant loop scopes both VRT UPDATEs through RLS-visible datasets."""
    from app.platform.jobs.router import sweep_stale_vrt_assets

    ctx = multi_tenant_rls
    record_a, record_b = uuid4(), uuid4()
    dataset_a, dataset_b = uuid4(), uuid4()
    generation_a, generation_b = uuid4(), uuid4()
    asset_a, asset_b = uuid4(), uuid4()
    cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
    old_started_at = cutoff - timedelta(hours=1)
    engine = create_async_engine(ctx.db_url, poolclass=NullPool)

    try:
        async with engine.begin() as conn:
            await conn.execute(
                sa.text(
                    "GRANT SELECT, UPDATE ON catalog.vrt_generations, "
                    "catalog.raster_assets TO geolens_reader"
                )
            )
            # fix(#1322 review round 3): the composition-preserving check
            # reads vrt_source_links — a real runtime role already has
            # blanket SELECT/INSERT/UPDATE/DELETE on every catalog table
            # (configure-runtime-db-role.sh), so this is this minimal test
            # role catching up, not a production grant gap.
            await conn.execute(
                sa.text("GRANT SELECT ON catalog.vrt_source_links TO geolens_reader")
            )
            # fix(#1322 review round 6): the pending-generation proven-dead
            # check reads catalog.procrastinate_jobs — same "minimal test
            # role catching up" rationale as above; the query text references
            # the table even for these status='running' fixture rows, so
            # Postgres checks the privilege at plan time regardless of which
            # OR-branch actually matches.
            await conn.execute(
                sa.text("GRANT SELECT ON catalog.procrastinate_jobs TO geolens_reader")
            )
            for record_id, dataset_id, tenant_id, suffix in (
                (record_a, dataset_a, ctx.tenant_a, "a"),
                (record_b, dataset_b, ctx.tenant_b, "b"),
            ):
                await conn.execute(
                    sa.text(
                        "INSERT INTO catalog.records "
                        "(id, title, visibility, record_status, record_type, "
                        " tenant_id, created_at, updated_at) "
                        "VALUES (:id, :title, 'private', 'draft', 'vrt_dataset', "
                        " :tenant_id, now(), now())"
                    ),
                    {
                        "id": record_id,
                        "title": f"tenant VRT {suffix}",
                        "tenant_id": tenant_id,
                    },
                )
                await conn.execute(
                    sa.text(
                        "INSERT INTO catalog.datasets "
                        "(id, record_id, table_name, tenant_id) "
                        "VALUES (:id, :record_id, :table_name, :tenant_id)"
                    ),
                    {
                        "id": dataset_id,
                        "record_id": record_id,
                        "table_name": f"tenant_vrt_{suffix}_{uuid4().hex[:8]}",
                        "tenant_id": tenant_id,
                    },
                )

            for generation_id, dataset_id in (
                (generation_a, dataset_a),
                (generation_b, dataset_b),
            ):
                await conn.execute(
                    sa.text(
                        "INSERT INTO catalog.vrt_generations "
                        "(id, vrt_dataset_id, status, started_at, created_at) "
                        "VALUES (:id, :dataset_id, 'running', :started_at, now())"
                    ),
                    {
                        "id": generation_id,
                        "dataset_id": dataset_id,
                        "started_at": old_started_at,
                    },
                )

            for asset_id, dataset_id, generation_id, suffix in (
                (asset_a, dataset_a, generation_a, "a"),
                (asset_b, dataset_b, generation_b, "b"),
            ):
                await conn.execute(
                    sa.text(
                        "INSERT INTO catalog.raster_assets "
                        "(id, dataset_id, asset_uri, storage_backend, status, "
                        " current_generation_id, built_from, created_at) "
                        "VALUES (:id, :dataset_id, :uri, 'local', 'regenerating', "
                        " :generation_id, '{}'::jsonb, now())"
                    ),
                    {
                        "id": asset_id,
                        "dataset_id": dataset_id,
                        "uri": f"/tmp/tenant-{suffix}.vrt",
                        "generation_id": generation_id,
                    },
                )

        async with ctx.tenant_session(ctx.tenant_a) as session:
            # fix(#1322 review): 3rd element is resolved-not-deleted storage
            # keys, tenant-prefixed since ctx.tenant_session binds
            # current_tenant_var for the block — one swept generation, 3 keys.
            sweep_result = await sweep_stale_vrt_assets(session, cutoff)
            assert sweep_result[:2] == (1, 1)
            assert len(sweep_result[2]) == 3

        async with engine.connect() as conn:
            generations = dict(
                (
                    await conn.execute(
                        sa.text(
                            "SELECT id, status FROM catalog.vrt_generations "
                            "WHERE id = ANY(:ids)"
                        ),
                        {"ids": [generation_a, generation_b]},
                    )
                ).all()
            )
            assets = dict(
                (
                    await conn.execute(
                        sa.text(
                            "SELECT id, status FROM catalog.raster_assets "
                            "WHERE id = ANY(:ids)"
                        ),
                        {"ids": [asset_a, asset_b]},
                    )
                ).all()
            )
        assert generations == {generation_a: "failed", generation_b: "running"}
        # feat(#1267): restored to 'ready', not 'failed' — tenant a's asset
        # never had its published pointer touched by the dead attempt, so it
        # keeps serving what it served before regeneration started.
        assert assets == {asset_a: "ready", asset_b: "regenerating"}
    finally:
        async with engine.begin() as conn:
            await conn.execute(
                sa.text("DELETE FROM catalog.records WHERE id = ANY(:ids)"),
                {"ids": [record_a, record_b]},
            )
            await conn.execute(
                sa.text(
                    "REVOKE SELECT, UPDATE ON catalog.vrt_generations, "
                    "catalog.raster_assets FROM geolens_reader"
                )
            )
            await conn.execute(
                sa.text("REVOKE SELECT ON catalog.vrt_source_links FROM geolens_reader")
            )
            await conn.execute(
                sa.text(
                    "REVOKE SELECT ON catalog.procrastinate_jobs FROM geolens_reader"
                )
            )
        await engine.dispose()
