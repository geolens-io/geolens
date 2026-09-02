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
