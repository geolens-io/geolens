"""Abuse controls for the ArcGIS sign-in route.

Everything here answers one question: may this caller spend one more ArcGIS
sign-in attempt right now, and what is recorded when they do. It is separated
from ``router.py`` because none of it is routing, and because the route module
sits under a 1500-line cap that this grew through five review rounds.

The shape, in the order the route applies it:

* two PostgreSQL advisory locks, taken caller-and-portal first and account
  second, so the budget reads below are serialized and the pair cannot
  deadlock (see :func:`_signin_lock`);
* two budgets, three attempts per fifteen minutes each, one per target ArcGIS
  account and one per caller and portal, read from different tables for the
  reason :func:`_signin_budgets_spent` gives;
* one audit row per attempt, and a ledger row for the attempts that count.

Nothing here holds a credential. The caller's username reaches the route and
is turned into a keyed digest before anything in this module sees it.
"""

import contextlib
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import NoReturn

import structlog
from fastapi import HTTPException, status
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.models import AuditLog
from app.modules.audit.service import AuditEvent, audit_emit
from app.modules.catalog.sources.arcgis_signin import (
    AUDIT_CONCURRENT,
    AUDIT_RATE_LIMITED,
    UNCOUNTED_SIGNIN_RESULTS,
    ArcGISSignInError,
)
from app.modules.catalog.sources.models import ArcGISSignInAttempt

logger = structlog.stdlib.get_logger(__name__)

# The shared limit, and the window it is counted over.
_ARCGIS_SIGNIN_ATTEMPT_LIMIT = 3
_ARCGIS_SIGNIN_WINDOW = timedelta(minutes=15)


async def _signin_audit(
    db: AsyncSession,
    user_id: uuid.UUID,
    host: str,
    result: str,
    account_key: str,
    note: str | None = None,
) -> None:
    """Record one sign-in attempt: who, which portal, which account, what happened.

    The token-service HOST rather than the portal URL, and a keyed digest
    rather than the username: an audit row is read by an operator looking for someone walking
    accounts, and the host, the digest and the outcome are the whole of that
    signal. ``result`` carries the distinction the caller-facing message
    deliberately collapses.
    """
    await audit_emit(
        db,
        AuditEvent(
            user_id=user_id,
            action="arcgis_signin",
            resource_type="service_url",
            details={
                # fix(#1758 codex r7): the DESTINATION host, resolved from
                # authInfo.tokenServicesUrl, not the address the caller typed.
                # That is what the limits are keyed on, so that is what an
                # operator reading this row needs to see.
                "token_service_host": host,
                "result": result,
                # fix(#1758 codex r3): a keyed digest of the target account,
                # never the username. It is what both budgets below are
                # counted on, and it is the only trace of which ArcGIS account
                # was addressed that survives the request.
                "account_key": account_key,
                # fix(#1758 codex r9): present only when discovery turned up
                # something an operator should see, so the common row keeps
                # its shape.
                **({"discovery_note": note} if note else {}),
            },
        ),
    )
    if result not in UNCOUNTED_SIGNIN_RESULTS:
        # fix(#1758 codex r4): the account budget's own copy, in the one table
        # that is not tenant-scoped. Written here rather than at the call
        # sites so the ledger and the audit row can never disagree about what
        # counted. Same transaction, so they commit or fail together.
        db.add(ArcGISSignInAttempt(account_key=account_key))
        await _sweep_expired_signin_attempts(db)
    await db.commit()


async def _sweep_expired_signin_attempts(db: AsyncSession) -> None:
    """Drop ledger rows that have aged out of the window.

    Opportunistic, on the write path, because the ledger has no other reader
    and no scheduled job should exist for a table this small. Every row it
    deletes is already outside the window, so it can never remove one a
    concurrent count would have seen, and the rate limits bound how often
    this runs to a handful of times per account per window.
    """
    await db.execute(
        delete(ArcGISSignInAttempt).where(
            ArcGISSignInAttempt.attempted_at
            < datetime.now(tz=UTC) - _ARCGIS_SIGNIN_WINDOW
        )
    )


async def _signin_budgets_spent(
    db: AsyncSession, user_id: uuid.UUID, host: str, account_key: str
) -> bool:
    """Whether either attempt budget is spent inside the window.

    fix(#1758 codex r1): the cross-worker half of the lockout limit. The rows
    this endpoint already writes are the shared counter, so nothing new is
    stored and no new dependency appears on an install that has only
    PostgreSQL.

    fix(#1758 codex r3): TWO budgets, and the refusal fires when either is
    spent. The account budget is the one Esri actually counts, because a
    lockout belongs to the ArcGIS account rather than to whoever spent it, and
    a per-GeoLens-user limit alone lets two colleagues put six attempts
    against one account and lock it. The per-user budget stays beside it,
    because the account budget alone would let one user walk many accounts at
    three each.

    fix(#1758 codex r4): the two budgets read DIFFERENT tables, and that is
    the fix rather than an accident. ``audit_logs`` carries
    ``tenant_isolation_audit_logs``, so counting the account budget there
    made it per tenant and let two tenants send six failures at one account.
    The account budget therefore counts ``arcgis_signin_attempts``, which is
    deliberately outside the RLS boundary; see that model's docstring for why
    that is safe. The per-user budget stays on ``audit_logs`` and stays
    tenant-scoped, which is correct, because a limit on one caller only ever
    needs to see that caller's own rows.

    Outcomes GeoLens refused on its own account do not count, because no
    credential reached ArcGIS on those and Esri counted nothing. That set is
    an EXCLUSION list rather than an inclusion list, so a new outcome added
    later counts toward the limit until somebody decides otherwise. It also
    keeps a refusal from extending its own window: a rate-limited attempt
    that counted itself would hold the caller over the limit for another
    fifteen minutes on every retry, and they would never get back in. The
    ledger holds only counted attempts, so it needs no such filter.
    """
    since = datetime.now(tz=UTC) - _ARCGIS_SIGNIN_WINDOW
    by_user = await db.scalar(
        select(func.count())
        .select_from(AuditLog)
        .where(
            AuditLog.action == "arcgis_signin",
            AuditLog.created_at >= since,
            AuditLog.user_id == user_id,
            AuditLog.details["token_service_host"].astext == host,
            AuditLog.details["result"].astext.not_in(sorted(UNCOUNTED_SIGNIN_RESULTS)),
        )
    )
    if int(by_user or 0) >= _ARCGIS_SIGNIN_ATTEMPT_LIMIT:
        return True
    by_account = await db.scalar(
        select(func.count())
        .select_from(ArcGISSignInAttempt)
        .where(
            ArcGISSignInAttempt.account_key == account_key,
            ArcGISSignInAttempt.attempted_at >= since,
        )
    )
    return int(by_account or 0) >= _ARCGIS_SIGNIN_ATTEMPT_LIMIT


@contextlib.asynccontextmanager
async def _signin_locks(
    db: AsyncSession, user_scope: str, account_scope: str
) -> AsyncIterator[bool]:
    """Hold both sign-in locks on the REQUEST session, yielding whether both were free.

    fix(#1758 codex r1): transaction-scoped advisory locks rather than the
    session-scoped ``pg_try_advisory_lock``. That one outlives the pool's
    rollback-on-return, so a single missed unlock would lock an account out
    for the life of that pooled connection; a transaction-scoped lock is
    released by the transaction ending, and by the connection dying.

    fix(#1758 codex r3): the account scope is keyed on the ARCGIS account
    rather than on the GeoLens user, for the same reason the counter is.

    fix(#1758 codex r5): two scopes, one per budget, taken in the ORDER of
    the arguments, caller-and-host before account. Every caller takes them in
    that order, so no two can hold one another's next lock.

    fix(#1758 codex r10): on the request's OWN session, which is what makes a
    sign-in cost ONE pooled connection. A dedicated lock session cost two, and
    the second was checked out FIRST: thirteen concurrent sign-ins for
    distinct scopes could each hold a lock connection and then queue for a
    request connection that the other twelve were holding, stalling unrelated
    traffic until the pool timeout. The request transaction is exactly the
    right lifetime anyway. It is open from the first lock through the budget
    reads and the mint to the audit write, and ``_signin_audit``'s commit is
    both what persists the row and what releases the locks, in that order, so
    no other caller can read the counter between this one's read and its
    write. An unwind without a commit releases them when the request session
    is closed and rolled back.

    Both are TRY-locks: a busy scope answers immediately rather than queuing,
    so a caller never waits on another caller's portal round trip.
    """
    # Imported here rather than at module scope: `_is_sensitive_connector_key`
    # in router.py binds `text` as a local name, and a module-level import of
    # the same word reads like a shadowing bug to everyone who meets it later.
    from sqlalchemy import text

    for scope in (user_scope, account_scope):
        held = await db.execute(
            text("SELECT pg_try_advisory_xact_lock(hashtextextended(:lock_key, 0))"),
            {"lock_key": f"arcgis-signin:{scope}"},
        )
        if not held.scalar():
            # Whichever was taken first stays held until this transaction
            # ends, which is the same moment it would have been released
            # anyway. There is nothing to unwind here.
            yield False
            return
    yield True


def _signin_in_progress() -> ArcGISSignInError:
    return ArcGISSignInError(
        code="arcgis_signin_in_progress",
        message=(
            "A sign-in to that ArcGIS account is already in progress. Wait "
            "for it to finish before trying again."
        ),
        status_code=status.HTTP_409_CONFLICT,
        audit_result=AUDIT_CONCURRENT,
    )


def _signin_rate_limited() -> ArcGISSignInError:
    return ArcGISSignInError(
        code="rate_limited",
        message=(
            "Too many sign-in attempts for that ArcGIS account. Wait fifteen "
            "minutes before trying again. ArcGIS locks an account after five "
            "failed attempts, so GeoLens stops short of that on purpose."
        ),
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        audit_result=AUDIT_RATE_LIMITED,
    )


async def _signin_refusal(
    db: AsyncSession,
    user_id: uuid.UUID,
    host: str,
    account_key: str,
    exc: ArcGISSignInError,
    note: str | None = None,
) -> NoReturn:
    """Log, audit and raise one classified refusal.

    fix(#1758 codex r5): one exit for every refusal, because there are now six
    of them across two nested locks and hand-writing the log line, the audit
    row and the HTTPException at each was how they would drift apart.
    """
    logger.warning(
        "ArcGIS sign-in refused",
        token_service_host=host,
        code=exc.code,
        result=exc.audit_result,
    )
    try:
        await _signin_audit(db, user_id, host, exc.audit_result, account_key, note)
    except Exception:  # broad: any failed transaction, whatever poisoned it
        # fix(#1758 codex r11): a refusal has to be recorded even when the
        # session it arrives on is already broken. A cancellation landing in a
        # flush or a commit leaves the transaction failed, every later
        # statement on it errors, and the row that says a credential POST went
        # out would be lost with it. Rolling back is the only way back to a
        # usable session, and it costs nothing here: `_signin_audit` commits,
        # so there is never uncommitted work of ours to discard.
        await db.rollback()
        await _signin_audit(db, user_id, host, exc.audit_result, account_key, note)
    # `from None`: the chained cause of a transport failure is an httpx error
    # holding the request whose encoded body is the password, and nothing
    # downstream needs it.
    raise HTTPException(
        status_code=exc.status_code,
        detail={"code": exc.code, "message": exc.message, "field": exc.field},
    ) from None
