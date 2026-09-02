"""fix(#1744): every door that dispatches an ``IngestJob`` stamps the marker.

``abandoned_upload`` in ``jobs/sweep.py`` reads the ABSENCE of
``user_metadata["commit_attempted_at"]`` as "nothing was ever dispatched for
this row", and settles it ``cancelled`` instead of ``failed``. That reading is
only sound while every dispatch really does stamp it: a door that reached the
queue without stamping would have its own genuine failures reported as
abandoned uploads, and ``/jobs/{id}/retry`` accepts ``failed`` only, so the
misreport would take the job's only recovery path away.

The design answer was one choke point rather than a stamp per door. These tests
pin that the choke point is still the only way through, in both directions:

1. no ``defer_async_with_tenant(job_id=...)`` call reaches the queue outside a
   function that goes through ``defer_with_orphan_guard``;
2. every ``defer_with_orphan_guard`` call names the row it is dispatching;
3. the guard stamps before it defers, and the stamp is committed.

Source-walking, so it fails on a door that is added rather than on a door that
happens to be exercised. The behavioural half lives in
``test_stale_pending_reaper.py``.
"""

from __future__ import annotations

import ast
import pathlib

import pytest
from sqlalchemy.exc import OperationalError, PendingRollbackError

from app.platform.jobs.sweep import is_abandoned_upload

BACKEND_ROOT = pathlib.Path(__file__).resolve().parents[1]
APP_ROOT = BACKEND_ROOT / "app"

GUARD = "defer_with_orphan_guard"
DEFER = "defer_async_with_tenant"
STAMP = "stamp_commit_attempted"


def _called_name(node: ast.Call) -> str | None:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _parsed_modules() -> list[tuple[pathlib.Path, ast.Module]]:
    return [
        (path, ast.parse(path.read_text(encoding="utf-8")))
        for path in sorted(APP_ROOT.rglob("*.py"))
    ]


def _parent_map(tree: ast.Module) -> dict[ast.AST, ast.AST]:
    parents: dict[ast.AST, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node
    return parents


def _guard_calls() -> list[tuple[pathlib.Path, ast.Call]]:
    found: list[tuple[pathlib.Path, ast.Call]] = []
    for path, tree in _parsed_modules():
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and _called_name(node) == GUARD:
                found.append((path, node))
    return found


def test_no_ingest_job_dispatch_bypasses_the_guard() -> None:
    """The choke point is the only route to the queue.

    A ``job_id`` argument is what makes a deferred task an ``IngestJob``
    dispatch: the worker loads that row and settles it. Every such call has to
    sit inside a function that also runs the guard, because the guard is where
    the marker is written and nowhere else writes it.

    The two ``embed_record`` defers pass ``record_id`` and settle no ingest
    row, so they are outside this rule by construction rather than by
    exemption.
    """
    unguarded: list[str] = []
    dispatch_count = 0

    for path, tree in _parsed_modules():
        parents = _parent_map(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or _called_name(node) != DEFER:
                continue
            if not any(kw.arg == "job_id" for kw in node.keywords):
                continue
            dispatch_count += 1
            guarded = False
            current: ast.AST = node
            while current in parents:
                current = parents[current]
                if not isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                guarded = guarded or any(
                    isinstance(sub, ast.Call) and _called_name(sub) == GUARD
                    for sub in ast.walk(current)
                )
            if not guarded:
                unguarded.append(f"{path}:{node.lineno}")

    assert dispatch_count >= 17, (
        "the walk found fewer ingest dispatches than the codebase has; the "
        f"call shape this test recognizes has probably changed ({dispatch_count} found)"
    )
    assert not unguarded, (
        "these sites dispatch an IngestJob without going through "
        f"{GUARD}, so nothing stamps commit_attempted_at on the row and the "
        "stale sweep will report their genuine failures as abandoned "
        "uploads:\n" + "\n".join(unguarded)
    )


def test_every_guard_call_names_the_row_it_dispatches() -> None:
    """``job=`` is required, and required is not the same as passed.

    A missing keyword is a TypeError at runtime, which only shows up on a path
    a test actually walks. This is the whole census, so a door added without it
    fails here rather than in production on the one branch nobody exercised.
    """
    missing = [
        f"{path}:{node.lineno}"
        for path, node in _guard_calls()
        if not any(kw.arg == "job" for kw in node.keywords)
    ]
    assert not missing, (
        f"these {GUARD} calls do not name the IngestJob they dispatch:\n"
        + "\n".join(missing)
    )


def test_the_guard_stamps_before_it_defers() -> None:
    """Order is the whole point: the marker has to beat the task.

    If the stamp ran after the defer, a worker could claim, run and settle the
    row before the marker landed, and a crash in that window would leave a
    dispatched row looking abandoned.
    """
    from app.platform.jobs import defer_guard

    source = pathlib.Path(defer_guard.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    guard_fn = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == GUARD
    )

    stamp_lines = [
        node.lineno
        for node in ast.walk(guard_fn)
        if isinstance(node, ast.Call) and _called_name(node) == STAMP
    ]
    defer_lines = [
        node.lineno
        for node in ast.walk(guard_fn)
        if isinstance(node, ast.Call) and _called_name(node) == "defer_call"
    ]

    assert len(stamp_lines) == 1, f"expected one {STAMP} call in the guard"
    assert defer_lines, "the guard no longer invokes its defer callable"
    assert stamp_lines[0] < min(defer_lines), (
        "the guard defers before it stamps, so a dispatched row can be read as "
        "an abandoned upload"
    )


@pytest.mark.anyio
async def test_the_stamp_is_committed_not_left_on_the_session() -> None:
    """Durability, because the rows that need the marker never commit again.

    ``get_db`` closes the session without committing, and the two shapes the
    marker exists to catch are a defer whose rollback did not land and a
    dispatch whose queue row later vanished. A stamp left dirty on the session
    is gone in both.
    """
    import uuid
    from types import SimpleNamespace

    from app.platform.jobs.defer_guard import stamp_commit_attempted
    from app.platform.jobs.models import COMMIT_ATTEMPTED_METADATA_KEY

    executed: list[object] = []
    commits: list[int] = []

    class _Session:
        async def execute(self, statement):
            executed.append(statement)

        async def commit(self):
            commits.append(len(executed))

    job = SimpleNamespace(id=uuid.uuid4(), user_metadata=None)
    await stamp_commit_attempted(job, db=_Session())

    assert len(executed) == 1, "the stamp did not write the row"
    assert commits == [1], "the stamp was written but never committed"
    assert job.user_metadata[COMMIT_ATTEMPTED_METADATA_KEY]

    # Idempotent: a retry re-queues the same row, and the first attempt is the
    # honest answer to "was a dispatch ever tried".
    first = job.user_metadata[COMMIT_ATTEMPTED_METADATA_KEY]
    await stamp_commit_attempted(job, db=_Session())
    assert job.user_metadata[COMMIT_ATTEMPTED_METADATA_KEY] == first
    assert len(executed) == 1, "the second dispatch rewrote a marker it should keep"


class _FailedTransactionSession:
    """A session that behaves like SQLAlchemy after a statement has failed.

    Once the marker commit raises, every later ``execute`` raises
    ``PendingRollbackError`` until ``rollback`` is awaited. That is the real
    constraint the fix is about: SQLAlchemy will not run another statement on
    a session whose transaction failed, so the orphan settlement is only
    reachable after a reset.
    """

    def __init__(self) -> None:
        self.events: list[str] = []
        self.broken = False
        self._commits = 0

    async def execute(self, statement=None):
        self.events.append("execute")
        if self.broken:
            raise PendingRollbackError(
                "This Session's transaction has been rolled back due to a "
                "previous exception during flush."
            )
        return None

    async def commit(self):
        self.events.append("commit")
        self._commits += 1
        if self._commits == 1:
            self.broken = True
            raise OperationalError(
                "UPDATE catalog.ingest_jobs",
                None,
                Exception("deadlock detected"),
            )

    async def rollback(self):
        self.events.append("rollback")
        self.broken = False


@pytest.mark.anyio
async def test_a_failed_marker_write_resets_the_session_before_settling() -> None:
    """fix(#1774 review, codex P2): the settlement needs a usable session.

    A serialization failure or deadlock on the marker write leaves the session
    in a failed transaction. Handing it straight to the rollback closure makes
    `settle_ingest_job_failed` raise as well, and the job stays `pending` with
    no marker, which is the exact combination the stale sweep reads as an
    upload nobody committed. It would then cancel a dispatch that really was
    attempted and take away its retry.

    So: reset first, settle second, and the row ends up `failed`, which keeps
    it out of the sweep's pending class altogether.
    """
    import uuid
    from types import SimpleNamespace

    from app.platform.jobs.defer_guard import DeferFailed, defer_with_orphan_guard

    session = _FailedTransactionSession()

    # Positive control: the double really does refuse work until it is reset,
    # so the ordering assertion below cannot pass vacuously.
    control = _FailedTransactionSession()
    with pytest.raises(OperationalError):
        await control.commit()
    with pytest.raises(PendingRollbackError):
        await control.execute()
    await control.rollback()
    await control.execute()

    job = SimpleNamespace(id=uuid.uuid4(), user_metadata=None, status="pending")

    async def _settle(exc: BaseException) -> None:
        # Stands in for `settle_ingest_job_failed`: a statement on the same
        # session, which is what a failed transaction would reject.
        await session.execute()
        job.status = "failed"

    async def _defer() -> None:  # pragma: no cover - never reached
        raise AssertionError("the dispatch ran despite an unwritten marker")

    with pytest.raises(DeferFailed) as exc_info:
        await defer_with_orphan_guard(_defer, rollback=_settle, db=session, job=job)

    assert exc_info.value.status_code == 503
    assert exc_info.value.rolled_back, (
        "the orphan settlement did not land, so the row is still pending"
    )
    assert isinstance(exc_info.value.__cause__, OperationalError)

    # execute+commit for the marker, then the reset, then the settlement.
    assert session.events == ["execute", "commit", "rollback", "execute", "commit"]
    assert session.events.index("rollback") < session.events.index(
        "execute", session.events.index("rollback")
    ), "the settlement ran on a session that had not been reset"

    assert job.status == "failed", (
        "the job stayed pending, so the stale sweep would later read it as an "
        "abandoned upload and cancel it"
    )
    # The marker never landed, so `pending` is precisely the state that would
    # have been misread. Being terminal is what keeps the row out of the
    # sweep's pending class.
    assert is_abandoned_upload(job.user_metadata), (
        "the marker is expected NOT to have landed; if it did, this test is "
        "no longer exercising the failure it was written for"
    )


@pytest.mark.anyio
async def test_a_marker_write_that_succeeds_leaves_the_session_alone() -> None:
    """The counterweight: no reset on the path where nothing failed.

    A rollback on the happy path would discard whatever the caller had staged
    after its own commit, so the reset has to belong to the failure branch and
    only to it.
    """
    import uuid
    from types import SimpleNamespace

    from app.platform.jobs.defer_guard import defer_with_orphan_guard

    class _HealthySession(_FailedTransactionSession):
        async def commit(self):
            self.events.append("commit")

    session = _HealthySession()
    job = SimpleNamespace(id=uuid.uuid4(), user_metadata=None, status="pending")
    deferred: list[bool] = []

    async def _defer() -> None:
        deferred.append(True)

    async def _rollback(exc: BaseException) -> None:  # pragma: no cover
        raise AssertionError("rollback ran on a successful dispatch")

    await defer_with_orphan_guard(_defer, rollback=_rollback, db=session, job=job)

    assert deferred == [True]
    assert "rollback" not in session.events
    assert session.events == ["execute", "commit"]
