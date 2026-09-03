"""REMED-03 / ingest-audit P2-05: contract pins for ``_job_phase_session``.

The helper centralizes the two-phase session-bracket pattern shared by
``tasks_vector.ingest_file``, ``tasks_vector.ingest_service``, and
``tasks_raster.ingest_raster``. These tests pin the four pieces of behavior
the helper exposes so a future change cannot silently regress them:

1. ``loads_existing_job`` — re-loading by id returns the actual row.
2. ``yields_none_when_job_missing`` — a vanished row yields ``(session, None)``
   and the helper logs a warning rather than raising. Mirrors the existing
   "vanished between phases" semantics used by both worker paths.
3. ``rolls_back_on_exception`` — an uncaught exception inside the ``async
   with`` rolls back the helper's session before re-raising, so partial
   mutations are not durably committed.
4. ``commit_persists_on_normal_exit`` — explicit ``session.commit()`` inside
   the block persists (caller owns the commit decision; the helper does not
   auto-commit on exit).
5. ``require_status`` (fix(#1778 audit r11)) — an optional status predicate
   that joins the attempt fence. Without it, a row the stale sweep already
   failed on a heartbeat timeout, with no retry having rotated the attempt
   token yet, still matched an ``(id, attempt)``-only fence: a worker only
   paused, not dead, could resume and write whatever that phase writes to a
   row already declared terminal. A test at the end of this file also pins
   every current phase-2 call site across the ingest tails to make sure the
   parameter is actually passed where it matters, not just implemented.
"""

from __future__ import annotations

import uuid as _uuid
from pathlib import Path

import pytest
from sqlalchemy import select

from app.platform.jobs.models import IngestJob
from app.processing.ingest.tasks_common import _job_phase_session

from tests.factories import get_user_id

APP = Path(__file__).resolve().parents[1] / "app"


async def _get_admin_id(session):
    return await get_user_id(session, "admin")


async def _create_pending_job(
    test_db_session, *, source_filename: str = "phase_bracket_test.geojson"
) -> _uuid.UUID:
    """Insert + commit a pending IngestJob, returning its id.

    Committing setup matters: the helper opens its OWN session via
    ``app.core.db.async_session`` (which the conftest fixture has already
    patched onto the test database). The helper's session can only ``SELECT``
    rows that the test's setup transaction has already committed.
    """
    admin_id = await _get_admin_id(test_db_session)
    job = IngestJob(
        source_filename=source_filename,
        created_by=admin_id,
        status="pending",
        user_metadata={"title": "Phase Bracket Test", "visibility": "private"},
    )
    test_db_session.add(job)
    await test_db_session.commit()
    await test_db_session.refresh(job)
    return job.id


async def _select_status(test_db_session, job_id: _uuid.UUID) -> str | None:
    """Re-select the job's status in a fresh transaction so post-state is
    visible across session boundaries.
    """
    await test_db_session.rollback()  # discard any uncommitted reads
    result = await test_db_session.execute(
        select(IngestJob).where(IngestJob.id == job_id)
    )
    row = result.scalar_one_or_none()
    return None if row is None else row.status


# ---------------------------------------------------------------------------
# 1. loads_existing_job
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_phase_session_loads_existing_job(test_db_session):
    """``_job_phase_session(job_uuid, phase=...)`` yields the actual row when
    the IngestJob exists in the DB.
    """
    job_id = await _create_pending_job(test_db_session)

    seen_id: _uuid.UUID | None = None
    async with _job_phase_session(job_id, phase="phase1") as (session, loaded):
        assert loaded is not None, "helper should yield the row when it exists"
        seen_id = loaded.id

    assert seen_id == job_id


# ---------------------------------------------------------------------------
# 2. yields_none_when_job_missing
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_phase_session_yields_none_when_job_missing(client):
    """A missing row yields ``(session, None)`` rather than raising.

    Mirrors the existing "Ingest job vanished between phases" / "Ingest job
    not found" pattern that all four call sites depend on for early-return.

    Full-suite event-loop binding (v1039): this test exercises
    ``_job_phase_session`` against the PRODUCTION ``app.core.db.async_session``
    factory (no ``test_db_session`` is passed), so it is subject to the same
    loop-binding hazard documented on
    ``test_job_phase_session_none_branch_rolls_back_on_exception`` below. The
    ``client`` fixture pins that factory to THIS test's loop, preventing a prior
    test's defunct loop from surfacing ``RuntimeError: Task got Future attached
    to a different loop`` under CI's Python 3.13 xdist scheduling (the
    isolation-only flake exposed when v1039 added ~30 test files and shifted
    worker distribution). See the TD-06 note on the sibling test.
    """
    missing_id = _uuid.uuid4()

    seen_job: object = "sentinel"  # initialize to a value we can detect untouched
    seen_session = None
    async with _job_phase_session(missing_id, phase="phase2") as (session, job):
        seen_session = session
        seen_job = job
        # The body still runs — the caller is expected to check `job is None`
        # and early-return. The helper itself does NOT raise.

    assert seen_job is None
    assert seen_session is not None, (
        "session must still be yielded so callers can decide what to do"
    )


@pytest.mark.anyio
async def test_job_phase_session_none_branch_rolls_back_on_exception(client):
    """WR-02: an exception raised inside the ``async with`` block when job is
    None triggers ``session.rollback()`` before re-raising.

    The None branch previously yielded bare (outside the try/except guard) so
    any exception from a caller using the bare session would propagate without
    an explicit rollback. This pins the corrected behaviour: the helper wraps
    the None-job yield in the same try/except as the found-job branch.

    Full-suite event-loop binding fix (Plan 1081-03 / TD-06):
    The helper resolves ``app.core.db.async_session`` via a lazy from-import
    inside its function body (tasks_common.py:215). In isolation, that
    factory is the production singleton — fresh connection bound to the
    current per-function anyio loop, all good. In full-suite mode, a prior
    test has already exercised the production factory under a DIFFERENT
    event loop, leaving the engine's pool / asyncpg connections bound to
    a now-defunct loop. When the helper's ``session.rollback()`` fires
    inside the broad-except at line 232 (justified by Plan 1080-01), asyncpg
    raises ``RuntimeError: Task got Future attached to a different loop``.
    Requesting the ``client`` fixture pulls the conftest monkey-patch at
    conftest.py:368-369 (``db_module.async_session = test_session_factory``)
    which rebinds the factory to a fresh per-function engine for the
    duration of THIS test, so the helper's session is loop-clean. The
    fixture body is unused in this test (no HTTP requests); we only need
    its side effect.
    """
    missing_id = _uuid.uuid4()

    with pytest.raises(RuntimeError, match="none-branch exception"):
        async with _job_phase_session(missing_id, phase="phase_none_test") as (
            session,
            job,
        ):
            assert job is None
            raise RuntimeError("none-branch exception")

    # If we reach here, the exception propagated correctly (was re-raised).
    # The session rollback is internal to the helper — we pin that the
    # exception is NOT swallowed (i.e., the ``raise`` inside ``except``
    # works as expected).


# ---------------------------------------------------------------------------
# 3. rolls_back_on_exception
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_phase_session_rolls_back_on_exception(test_db_session):
    """An uncaught exception inside the ``async with`` triggers a rollback
    of the helper's session before re-raising.

    Pin: a partial mutation (``status = "running"``) inside the block, then a
    RuntimeError, must NOT persist. The job's status on a fresh re-query must
    still be ``"pending"`` (its insert value).
    """
    job_id = await _create_pending_job(test_db_session)
    assert await _select_status(test_db_session, job_id) == "pending"

    with pytest.raises(RuntimeError, match="simulated phase failure"):
        async with _job_phase_session(job_id, phase="phase1") as (session, job):
            assert job is not None
            job.status = "running"
            # NB: no explicit commit — the rollback test depends on the
            # mutation being staged in the helper's session, then discarded
            # by the helper's `await session.rollback()` on exception.
            raise RuntimeError("simulated phase failure")

    # The mutation must have been rolled back by the helper, NOT committed.
    assert await _select_status(test_db_session, job_id) == "pending"


# ---------------------------------------------------------------------------
# 4. commit_persists_on_normal_exit
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_phase_session_commit_persists_on_normal_exit(test_db_session):
    """When the caller explicitly commits inside the block, the mutation
    persists across session boundaries.

    Pin: the helper does NOT silently swallow commits or roll them back on
    normal exit. Caller owns the commit decision (this is the contract that
    lets the existing worker code do "load → mark running → commit → keep
    mutating → commit again" inside a single phase block).
    """
    job_id = await _create_pending_job(test_db_session)
    assert await _select_status(test_db_session, job_id) == "pending"

    async with _job_phase_session(job_id, phase="phase1") as (session, job):
        assert job is not None
        job.status = "running"
        await session.commit()

    assert await _select_status(test_db_session, job_id) == "running"


# ---------------------------------------------------------------------------
# 5. require_status (fix(#1778 audit r11))
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_phase_session_require_status_admits_a_matching_row(test_db_session):
    """``require_status="running"`` admits a row whose status already
    matches, the same as the default (no status filter) admits any status."""
    job_id = await _create_pending_job(test_db_session)
    async with _job_phase_session(job_id, phase="phase1") as (session, job):
        job.status = "running"
        await session.commit()

    async with _job_phase_session(job_id, phase="phase2", require_status="running") as (
        session,
        job,
    ):
        assert job is not None
        assert job.status == "running"


@pytest.mark.anyio
async def test_phase_session_require_status_refuses_a_terminal_row(test_db_session):
    """The pin for the finding itself. A row the stale sweep already failed,
    with its attempt token UNCHANGED because no retry has rotated it yet,
    must not be admitted to a phase requiring ``"running"`` -- an
    ``(id, attempt)``-only fence still matches such a row, which is exactly
    the gap a worker only paused, not dead, could resume through and go on
    to write whatever that phase writes.
    """
    job_id = await _create_pending_job(test_db_session)
    async with _job_phase_session(job_id, phase="phase1") as (session, job):
        attempt_id = job.attempt_id
        job.status = "running"
        await session.commit()

    # The stale sweep: fails the row WITHOUT rotating attempt_id, exactly
    # what a heartbeat-timeout failure does before any retry exists.
    async with _job_phase_session(job_id, phase="phase1") as (session, job):
        job.status = "failed"
        await session.commit()

    async with _job_phase_session(
        job_id,
        phase="phase2",
        attempt_id=attempt_id,
        require_status="running",
    ) as (session, job):
        assert job is None, (
            "a row the sweep already failed must not be admitted to a "
            "phase requiring status == 'running', even under the same "
            "attempt token"
        )

    # The counterfactual, inline: without require_status, the exact same
    # (id, attempt) fence still admits the failed row.
    async with _job_phase_session(job_id, phase="phase2", attempt_id=attempt_id) as (
        session,
        job,
    ):
        assert job is not None
        assert job.status == "failed"


# ---------------------------------------------------------------------------
# Every phase-2 site is wired, not just the helper
# ---------------------------------------------------------------------------


def test_every_phase2_site_requires_running() -> None:
    """fix(#1778 audit r11): the mechanism above is only as good as its
    callers. Enumerated across the four sites that go through
    ``_job_phase_session`` and the two in ``tasks_vrt.py`` that predate the
    helper and match the fence by hand, so a future phase-2 site cannot be
    added without answering this too.
    """
    # (relative path, needle, minimum occurrences)
    expectations = [
        ("processing/ingest/tasks_raster.py", 'require_status="running"', 1),
        ("processing/ingest/tasks_raster_replace.py", 'require_status="running"', 1),
        ("processing/ingest/tasks_vector.py", 'require_status="running"', 2),
        ("processing/ingest/tasks_vrt.py", 'IngestJob.status == "running"', 2),
    ]
    for rel, needle, minimum in expectations:
        source = (APP / rel).read_text()
        count = source.count(needle)
        assert count >= minimum, (rel, needle, "expected", minimum, "got", count)
