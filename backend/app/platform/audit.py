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

    ``user_id`` is nullable (FK ON DELETE SET NULL to catalog.users): used by
    SAML JIT-provisioning rows that pre-date user creation, and anonymous-
    download rows where user_id=NULL rather than a fabricated
    actor.
    """

    user_id: uuid.UUID | None
    action: str
    resource_type: str
    resource_id: uuid.UUID | None = None
    details: dict | None = None
    ip_address: str | None = None


def _event_fields(event: AuditEvent) -> dict:
    """Every field of a dropped event, so the log IS the fallback audit record.

    fix(#1491): the previous drop-path log omitted the actor, address and
    payload — the audit content itself. NIST AU-5 requires alerting on an
    audit-logging failure; logging the full event here is the "alternate
    audit logging capability" AU-5(4) waives fail-closed for.

    ``details`` goes through ``redact_nested()``, not straight to the
    logger: the structlog redactor is shallow and ``details`` isn't itself
    denylisted, so a ``persistent_config`` ``old_value``/``new_value`` or a
    basemap ``api_key`` would otherwise be emitted verbatim into the
    application log. The deep walk is affordable here — it runs only when a
    row is dropped.
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

    ``sinks`` narrows the dispatch; by default every registered sink is used.

    An audit sink must never break the operation it records. The
    try/except alone is not enough — the default sink's ``emit()`` bottoms
    out in ``session.add()``, which cannot fail; the INSERT it stages runs
    at the CALLER's flush/commit, outside any guard here.

    fix(#1491): each sink now runs inside its own SAVEPOINT, flushed there,
    so a bad audit row rolls back only itself. Fail-open and loud: failures
    are logged with the sink and event.

    Two consequences at the ~100 call sites: the caller's pending work is
    flushed here, so a staged mutation's IntegrityError now raises at this
    call instead of at a later ``commit()``; and each event costs a
    SAVEPOINT / INSERT / RELEASE round trip.
    """
    sinks = get_audit_sinks() if sinks is None else list(sinks)
    if not sinks:
        return

    # A missing session is an audit-infrastructure fault (must not
    # break the caller) — concretely, on the OAuth generic-error path, whose
    # only job here is a clean 302 with Referrer-Policy: no-referrer.
    # Logged at error, not swallowed: this should never happen in a
    # wired-up app.
    if session is None:
        logger.error(
            "audit_emit called without a session; event dropped",
            **_event_fields(event),
        )
        return

    # Flush the CALLER's work HERE, outside every guarded block below — this
    # is the safety argument for the savepoint, not an optimisation.
    # ``begin_nested()`` flushes the whole session as it takes its snapshot
    # (SQLAlchemy's ``_take_snapshot``); left inside the try/except, a broken
    # caller mutation would raise inside the audit savepoint, roll back with
    # it, and be swallowed as an "audit failure" — the edit silently
    # discarded, pointing at the wrong culprit.
    #
    # Second effect the code below depends on: the session is clean when
    # each savepoint opens, so anything pending inside one is the sink's own.
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
