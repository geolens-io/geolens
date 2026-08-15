"""An audit row that the database rejects must roll back only itself (#1491).

``audit_emit()`` has always wrapped each ``sink.emit()`` in try/except, because
AUDIT-03's contract is that an audit sink cannot break the operation it records.
That guard was structurally incomplete: the default sink's ``emit()`` bottoms
out in ``session.add()``, which cannot fail, and the INSERT it stages runs at
the CALLER's flush/commit — outside the guard entirely. So a row Postgres
rejects took the caller's mutation down with it. #1484 (a ``datetime.date`` in a
stdlib-JSON column) was one instance; #1489 removed that trigger at two call
sites and left the structure alone.

The fix runs each sink inside its own SAVEPOINT and flushes what that sink
staged there, so the failure is contained. The subtle half is WHERE the caller's
own pending work gets flushed: ``begin_nested()`` flushes the whole session as
the first act of taking its snapshot, so that flush has to happen outside the
guard, or a broken caller mutation would be rolled back inside the audit
savepoint and logged as an audit failure. ``test_caller_side_failure_propagates
_and_is_not_swallowed_as_audit`` is the test that pins that half, and it is the
more important of the two directions.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import date

import pytest
import structlog
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.modules.audit.models import AuditLog
from app.modules.catalog.collections.models import Collection
from app.platform.audit import AuditEvent, audit_emit
from app.platform.extensions import _extensions
from app.platform.extensions.defaults import DefaultAuditSink
from tests.factories import get_user_id

pytestmark = pytest.mark.anyio

_SWALLOWED = "Audit sink raised"


class PoisonSink:
    """Stages an audit row the database will reject.

    ``user_id`` points at a user that does not exist, so ``session.add()``
    succeeds and the INSERT fails on the ``audit_logs.user_id`` foreign key.
    That is the exact shape of the structural gap: a DB-level rejection no
    payload normalization can pre-empt, surfacing at flush rather than at
    ``emit()``.
    """

    def __init__(self, action: str) -> None:
        self.action = action

    async def emit(self, session, event) -> None:
        session.add(
            AuditLog(
                user_id=uuid.uuid4(),
                action=self.action,
                resource_type="audit_test",
                resource_id=event.resource_id,
            )
        )


@contextmanager
def audit_sinks(*sinks):
    """Swap the registered audit sinks for the duration of a test.

    Mirrors the save/restore pattern in ``test_audit_sink.py``.
    """
    saved = _extensions.get("audit_sinks")
    _extensions["audit_sinks"] = list(sinks)
    try:
        yield
    finally:
        if saved is None:
            _extensions.pop("audit_sinks", None)
        else:
            _extensions["audit_sinks"] = saved


def _swallowed(captured: list[dict]) -> list[dict]:
    return [r for r in captured if _SWALLOWED in str(r.get("event", ""))]


async def _count_rows(session, action: str) -> int:
    return int(
        (
            await session.execute(
                select(func.count())
                .select_from(AuditLog)
                .where(AuditLog.action == action)
            )
        ).scalar_one()
    )


async def test_rejected_audit_row_rolls_back_only_itself(test_db_session) -> None:
    """The #1491 defect, from the caller's side.

    The caller's mutation is deliberately still PENDING when ``audit_emit()`` is
    called — unflushed ``session.add()`` — because that is the state the old
    code destroyed. Both sinks are registered so this also re-pins the per-sink
    isolation from AUDIT-03: the poisoned sink must not cost the default sink
    its row.
    """
    session = test_db_session
    admin_id = await get_user_id(session, "admin")
    marker = uuid.uuid4().hex[:8]
    good_action = f"savepoint.good_{marker}"
    poison_action = f"savepoint.poison_{marker}"
    collection_name = f"savepoint-caller-{marker}"

    with audit_sinks(DefaultAuditSink(), PoisonSink(poison_action)):
        session.add(Collection(name=collection_name, created_by=admin_id))
        assert session.new, (
            "caller mutation must still be pending, or this proves nothing"
        )

        with structlog.testing.capture_logs() as captured:
            await audit_emit(
                session,
                AuditEvent(
                    user_id=admin_id,
                    action=good_action,
                    resource_type="audit_test",
                    resource_id=uuid.uuid4(),
                    details={"marker": marker},
                ),
            )
        await session.commit()

    try:
        # 1. The caller's mutation is durable.
        assert (
            await session.execute(
                select(func.count())
                .select_from(Collection)
                .where(Collection.name == collection_name)
            )
        ).scalar_one() == 1, "the caller's mutation was rolled back with the audit row"

        # 2. The rejected row is absent, and the healthy sibling sink's is not.
        assert await _count_rows(session, poison_action) == 0
        assert await _count_rows(session, good_action) == 1

        # 3. The failure is loud.
        records = _swallowed(captured)
        assert len(records) == 1, f"expected one suppressed-sink log; got {captured}"
        assert records[0]["log_level"] == "error"
        assert records[0]["sink"] == "PoisonSink"
        assert records[0]["action"] == good_action
    finally:
        await session.execute(
            Collection.__table__.delete().where(Collection.name == collection_name)
        )
        await session.execute(
            AuditLog.__table__.delete().where(AuditLog.action == good_action)
        )
        await session.commit()


async def test_caller_side_failure_propagates_and_is_not_swallowed_as_audit(
    test_db_session,
) -> None:
    """The inverted bug: a broken CALLER mutation must not become an audit failure.

    ``session.begin_nested()`` flushes the whole session before it opens the
    savepoint. An implementation that opens the savepoint inside the try/except
    — or that calls a bare ``session.flush()`` in there — would have this
    IntegrityError raised inside the audit savepoint, rolled back with it, and
    logged as "Audit sink raised". The caller's edit would vanish with a 200 and
    a log line naming the wrong culprit. That is strictly worse than #1484, so
    this is the load-bearing test of the pair.

    Measured against that exact wrong implementation (savepoint entered inside
    the guard, bare ``session.flush()`` in the body): every other test in this
    file still passes and only this one goes red. Hence the assertions are
    ordered swallow-first — the exception is captured by hand rather than with
    ``pytest.raises`` so the diagnostic names the swallow, not the absence of a
    raise.

    Note what this also pins: the caller's IntegrityError now surfaces AT
    ``audit_emit()`` rather than at their later ``commit()``, because the
    savepoint cannot be opened without flushing first. That is a deliberate
    consequence of the mechanism, not an accident.
    """
    session = test_db_session
    admin_id = await get_user_id(session, "admin")
    marker = uuid.uuid4().hex[:8]
    action = f"savepoint.caller_fail_{marker}"
    collection_name = f"savepoint-dup-{marker}"

    session.add(Collection(name=collection_name, created_by=admin_id))
    await session.commit()

    try:
        with audit_sinks(DefaultAuditSink()):
            # A second collection with the same name violates
            # uq_collections_name_global. Still pending when audit_emit runs.
            session.add(Collection(name=collection_name, created_by=admin_id))

            raised: BaseException | None = None
            with structlog.testing.capture_logs() as captured:
                try:
                    await audit_emit(
                        session,
                        AuditEvent(
                            user_id=admin_id,
                            action=action,
                            resource_type="audit_test",
                            resource_id=uuid.uuid4(),
                        ),
                    )
                except IntegrityError as exc:
                    raised = exc

        assert not _swallowed(captured), (
            "the caller's own IntegrityError was rolled back inside the audit "
            f"savepoint and logged as an audit-sink failure: {captured}"
        )
        assert isinstance(raised, IntegrityError), (
            "the caller's IntegrityError did not reach the caller; audit_emit "
            f"returned {raised!r}"
        )
        await session.rollback()
        assert await _count_rows(session, action) == 0
    finally:
        await session.rollback()
        await session.execute(
            Collection.__table__.delete().where(Collection.name == collection_name)
        )
        await session.commit()


async def test_happy_path_writes_one_row_and_leaves_no_open_savepoint(
    test_db_session,
) -> None:
    """The ordinary case is unchanged, and the savepoint does not leak.

    A savepoint left open would make every later statement on this session part
    of a nested transaction the caller never opened, so the RELEASE is worth an
    explicit assertion rather than being inferred from the row count.
    """
    session = test_db_session
    admin_id = await get_user_id(session, "admin")
    action = f"savepoint.happy_{uuid.uuid4().hex[:8]}"

    with audit_sinks(DefaultAuditSink()):
        with structlog.testing.capture_logs() as captured:
            await audit_emit(
                session,
                AuditEvent(
                    user_id=admin_id,
                    action=action,
                    resource_type="audit_test",
                    resource_id=uuid.uuid4(),
                    details={"marker": "happy"},
                ),
            )

    try:
        assert not _swallowed(captured)
        assert not session.in_nested_transaction(), "audit savepoint was left open"
        assert await _count_rows(session, action) == 1

        # The row is written inside the caller's transaction, not on a
        # connection of its own: it survives the caller's commit ...
        await session.commit()
        assert await _count_rows(session, action) == 1
    finally:
        await session.execute(
            AuditLog.__table__.delete().where(AuditLog.action == action)
        )
        await session.commit()


async def test_audit_row_still_rolls_back_with_the_caller(test_db_session) -> None:
    """... and dies with the caller's rollback.

    Fail-open must not have turned into fail-independent. An audit row recording
    a mutation that never committed is a worse artifact than a missing one, so
    the savepoint must be nested inside the caller's transaction rather than
    committed on its own.
    """
    session = test_db_session
    admin_id = await get_user_id(session, "admin")
    action = f"savepoint.rollback_{uuid.uuid4().hex[:8]}"

    with audit_sinks(DefaultAuditSink()):
        await audit_emit(
            session,
            AuditEvent(
                user_id=admin_id,
                action=action,
                resource_type="audit_test",
                resource_id=uuid.uuid4(),
            ),
        )
    assert await _count_rows(session, action) == 1

    await session.rollback()
    assert await _count_rows(session, action) == 0


async def test_non_json_details_are_normalized_rather_than_dropped(
    test_db_session,
) -> None:
    """The #1484 payload class is now recorded, not merely survived.

    The savepoint alone would contain a ``date``-bearing payload by discarding
    the whole audit row — the caller's mutation would be safe but the audit
    trail would have a hole. ``log_action`` normalizes ``details`` through
    ``jsonable_encoder``, so the row lands with ISO strings instead. Passing a
    raw ``date`` straight to ``AuditEvent`` bypasses the ``model_dump(mode=
    "json")`` that #1489 added at the call sites, which is the point: this pins
    the sink, not the callers.
    """
    session = test_db_session
    admin_id = await get_user_id(session, "admin")
    action = f"savepoint.encode_{uuid.uuid4().hex[:8]}"
    resource_id = uuid.uuid4()

    with audit_sinks(DefaultAuditSink()):
        with structlog.testing.capture_logs() as captured:
            await audit_emit(
                session,
                AuditEvent(
                    user_id=admin_id,
                    action=action,
                    resource_type="audit_test",
                    resource_id=resource_id,
                    details={"data_vintage_start": date(1950, 1, 1)},
                ),
            )
        await session.commit()

    try:
        assert not _swallowed(captured), f"the date payload was dropped: {captured}"
        details = (
            await session.execute(
                select(AuditLog.details).where(AuditLog.action == action)
            )
        ).scalar_one()
        assert details == {"data_vintage_start": "1950-01-01"}
    finally:
        await session.execute(
            AuditLog.__table__.delete().where(AuditLog.action == action)
        )
        await session.commit()


async def test_dropped_event_is_logged_in_full(test_db_session) -> None:
    """Fail-open only holds up if the log can stand in for the lost row.

    NIST SP 800-53 AU-5(4) waives fail-closed "unless an alternate audit
    logging capability exists", and that clause is the whole argument for
    suppressing the failure here. It is only true if the alert carries the
    event: the actor, their address and the payload. Logging action and
    resource alone — what this did before #1491 — leaves an alert nobody can
    reconstruct the event from, which is not an alternate capability.
    """
    session = test_db_session
    admin_id = await get_user_id(session, "admin")
    marker = uuid.uuid4().hex[:8]
    resource_id = uuid.uuid4()

    with audit_sinks(PoisonSink(f"savepoint.poison_{marker}")):
        with structlog.testing.capture_logs() as captured:
            await audit_emit(
                session,
                AuditEvent(
                    user_id=admin_id,
                    action=f"savepoint.dropped_{marker}",
                    resource_type="audit_test",
                    resource_id=resource_id,
                    details={"marker": marker},
                    ip_address="203.0.113.7",
                ),
            )
        await session.rollback()

    # Liveness half: without it every assertion below iterates nothing and the
    # test cannot fail (see test_notification_channels.py for the class).
    dropped = _swallowed(captured)
    assert len(dropped) == 1, f"expected one suppressed-sink record, got {captured}"

    record = dropped[0]
    assert record["user_id"] == str(admin_id)
    assert record["ip_address"] == "203.0.113.7"
    assert record["details"] == {"marker": marker}
    assert record["resource_id"] == str(resource_id)
    assert record["action"] == f"savepoint.dropped_{marker}"


async def test_missing_session_is_logged_in_full(test_db_session) -> None:
    """The other drop path carries the same payload.

    ``audit_emit(None, ...)`` reaches its own early return rather than the
    savepoint, so it needs its own assertion — the OAuth generic-error path
    hits exactly this branch.
    """
    marker = uuid.uuid4().hex[:8]

    with audit_sinks(DefaultAuditSink()):
        with structlog.testing.capture_logs() as captured:
            await audit_emit(
                None,
                AuditEvent(
                    user_id=None,
                    action=f"savepoint.nosession_{marker}",
                    resource_type="audit_test",
                    details={"marker": marker},
                    ip_address="203.0.113.9",
                ),
            )

    records = [r for r in captured if "without a session" in str(r.get("event", ""))]
    assert len(records) == 1, f"expected one missing-session record, got {captured}"
    assert records[0]["details"] == {"marker": marker}
    assert records[0]["ip_address"] == "203.0.113.9"
    assert records[0]["user_id"] is None


async def test_details_none_stays_null(test_db_session) -> None:
    """``jsonable_encoder`` must not turn an absent payload into ``{}``.

    ``audit_logs.details`` is nullable and "no payload" is a distinct row from
    "empty payload"; the sibling ``record_map_history_event`` coerces with
    ``details or {}`` because its column is not nullable, and copying that
    verbatim would silently rewrite every payload-free audit row.
    """
    session = test_db_session
    admin_id = await get_user_id(session, "admin")
    action = f"savepoint.nodetails_{uuid.uuid4().hex[:8]}"

    with audit_sinks(DefaultAuditSink()):
        await audit_emit(
            session,
            AuditEvent(
                user_id=admin_id,
                action=action,
                resource_type="audit_test",
                resource_id=uuid.uuid4(),
            ),
        )
        await session.commit()

    try:
        details = (
            await session.execute(
                select(AuditLog.details).where(AuditLog.action == action)
            )
        ).scalar_one()
        assert details is None
    finally:
        await session.execute(
            AuditLog.__table__.delete().where(AuditLog.action == action)
        )
        await session.commit()
