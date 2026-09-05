"""Audit event emission facade shared by core, modules, and extensions."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging_config import redact_nested
from app.platform.extensions import get_audit_sinks
from app.platform.extensions.defaults_extensions import DefaultAuditSink

if TYPE_CHECKING:
    from app.platform.extensions.protocols import AuditSink

logger = structlog.stdlib.get_logger(__name__)


@dataclass(frozen=True)
class AuditEvent:
    """Immutable audit event passed to every registered AuditSink.

    ``user_id`` is optional (uuid.UUID | None): the underlying ``audit_logs.user_id``
    column is nullable (ON DELETE SET NULL via FK to catalog.users) and is used by:
    - SAML JIT-provisioning rows that pre-date the user creation
    - Anonymous-download audit rows (KNOWN-01, Phase 1071): public datasets can
      be downloaded by anonymous callers, and the audit row records this with
      user_id=NULL rather than fabricating an actor.
    """

    user_id: uuid.UUID | None
    action: str
    resource_type: str
    resource_id: uuid.UUID | None = None
    details: dict | None = None
    ip_address: str | None = None


def _event_fields(event: AuditEvent) -> dict:
    """Every field of a dropped event, so the log IS the fallback audit record.

    fix(#1491): the two drop paths below used to log action/resource_type/
    resource_id only. That is an alert nobody can reconstruct the event from —
    the actor, their address and the payload, which are the whole point of an
    audit row, went with the row.

    This is what makes fail-open defensible rather than merely convenient.
    NIST SP 800-53 AU-5 is allocated to every baseline and asks for an alert on
    an audit-logging process failure; fail-closed is AU-5(4), which sits in no
    baseline at all and is waived "unless an alternate audit logging capability
    exists". Logging the complete event is that capability: a rejected row
    lands in the application log instead of vanishing.

    ``details`` goes through ``redact_nested()`` rather than straight to the
    logger. Most payloads carry nothing sensitive — fingerprints, token hints,
    ids, changed-field names — but ``persistent_config`` puts ``old_value``/
    ``new_value`` in there, and a ``basemaps`` setting holds an ``api_key``
    inside a basemap entry. The structlog redactor is shallow by design and
    ``details`` is not itself a denylisted key, so that credential would have
    been emitted verbatim, during an audit failure, into the application log.
    The deep walk is affordable here because this runs only when a row is
    dropped, not on every log line.
    """
    return {
        "action": event.action,
        "resource_type": event.resource_type,
        "resource_id": str(event.resource_id) if event.resource_id else None,
        "user_id": str(event.user_id) if event.user_id else None,
        "ip_address": event.ip_address,
        "details": redact_nested(event.details),
    }


def extension_audit_sinks() -> list["AuditSink"]:
    """Every registered sink except the one that writes ``audit_logs``.

    For a caller that has written that row itself and needs the other sinks
    to receive the same event.
    """
    return [
        sink for sink in get_audit_sinks() if not isinstance(sink, DefaultAuditSink)
    ]


async def audit_emit(
    session: AsyncSession,
    event: AuditEvent,
    *,
    sinks: Sequence["AuditSink"] | None = None,
) -> None:
    """Dispatch an audit event to every registered sink with failure isolation.

    ``sinks`` narrows the dispatch to the given sinks; by default every
    registered sink receives the event.

    AUDIT-03's contract is that an audit sink must never break the operation it
    records. The try/except below is only half of that: the default sink's
    ``emit()`` bottoms out in ``session.add()``, which cannot fail, and the
    INSERT it stages runs at the CALLER's flush/commit — outside any guard here.
    A row the database rejects therefore used to roll back the caller's mutation
    along with itself (#1484: a ``datetime.date`` in a stdlib-JSON column 500'd
    a dataset PATCH and silently discarded the other fields in the same body).

    fix(#1491): each sink now runs inside its own SAVEPOINT and its work is
    flushed there, so a bad audit row rolls back only itself and the caller's
    transaction survives. Fail-open, and loud: the failure is logged with the
    sink and the event that produced it.

    Two consequences worth knowing at the 100-odd call sites:

    * The caller's pending work is flushed here (see the flush below). Callers
      that stage a mutation and rely on a later ``commit()`` to raise its
      IntegrityError will now see it raised at this call instead.
    * Each event costs a SAVEPOINT / INSERT / RELEASE round trip that used to
      ride along with the caller's commit.
    """
    sinks = get_audit_sinks() if sinks is None else list(sinks)
    if not sinks:
        return

    # A missing session is an audit-infrastructure fault, and AUDIT-03 says
    # those must not break the caller. The pre-#1491 code degraded here by
    # accident: with no session it raised inside sink.emit(), where the
    # try/except swallowed it. Moving the flush out of that guard (see below)
    # made the same input a 500 instead, which surfaced on the OAuth generic-
    # error path — a route whose entire job at that point is to return a clean
    # 302 with Referrer-Policy: no-referrer. Turning an unaudited failure into
    # an unhandled one there is strictly worse.
    #
    # Logged at error rather than passed over: this should not happen in a
    # wired-up app, and swallowing it silently would hide a real defect.
    if session is None:
        logger.error(
            "audit_emit called without a session; event dropped",
            **_event_fields(event),
        )
        return

    # Flush the CALLER's pending work HERE, outside every guarded block below.
    # This is not an optimisation; it is the safety argument for the savepoint.
    #
    # ``begin_nested()`` flushes the whole session as the first act of taking
    # its snapshot (SQLAlchemy ``SessionTransaction._take_snapshot``), and that
    # flush is the caller's work, not ours. Left to happen inside the try/except
    # below, a caller whose own mutation is broken would have that error raised
    # inside the audit savepoint, rolled back with it, and swallowed as an audit
    # failure — the user's edit discarded and the log pointing at the wrong
    # culprit. That is the #1484 bug inverted and much harder to diagnose.
    #
    # Running it here has a second effect the code below depends on: the session
    # is clean when each savepoint opens, so anything pending inside one is
    # necessarily the sink's own.
    await session.flush()

    for sink in sinks:
        await _emit_isolated(session, sink, event)


async def _emit_isolated(
    session: AsyncSession, sink: AuditSink, event: AuditEvent
) -> None:
    """Run one sink inside a SAVEPOINT and flush only what that sink staged."""
    try:
        async with session.begin_nested():
            # ``session.new`` and friends are IdentitySets built fresh on each
            # access, so these are snapshots, not live views.
            before_new = session.new
            before_dirty = session.dirty
            before_deleted = session.deleted

            await sink.emit(session, event)

            # Flush ONLY what this sink staged. A bare ``session.flush()`` here
            # would flush the entire session, which is the trap described above.
            staged = list(
                (session.new - before_new)
                | (session.dirty - before_dirty)
                | (session.deleted - before_deleted)
            )
            if staged:
                await session.flush(staged)
    except Exception:  # noqa: BLE001 - audit sinks must not break callers
        logger.exception(
            "Audit sink raised; suppressed per AUDIT-03",
            sink=type(sink).__name__,
            **_event_fields(event),
        )
