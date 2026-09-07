"""Abuse controls for the ArcGIS sign-in route: may this caller spend one
more sign-in attempt right now, and what gets recorded when they do.

* fix(#1775): RESERVE, then SETTLE — nothing here holds a pooled connection
  across the network. :func:`_signin_reserve` is one short transaction that
  takes both advisory locks, reads both budgets and commits the ledger row,
  BEFORE the credential POST; the route mints with no session held, and
  :func:`_signin_audit` writes the outcome in a second short transaction. A
  cancellation during the POST cannot lose the count: it is already
  committed.
* two advisory locks, taken caller-and-portal first then account, so the
  pair cannot deadlock (see :func:`_signin_locks`);
* two budgets, three attempts per fifteen minutes each, one per target
  ArcGIS account and one per caller and token service (see
  :func:`_signin_budgets_spent`);
* one audit row per attempt, one ledger row per attempt that counts.

Nothing here holds a credential — the caller's username is a keyed digest
before anything in this module sees it.
"""

import asyncio
import contextlib
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import NoReturn

import structlog
from fastapi import HTTPException, status
from sqlalchemy import delete, func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.models import (
    ARCGIS_SIGNIN_SETTLE_KEY,
    ARCGIS_SIGNIN_SETTLE_WHERE,
    AuditLog,
)
from app.modules.audit.service import AuditEvent, audit_emit, extension_audit_sinks
from app.modules.catalog.sources.arcgis_signin import (
    AUDIT_CONCURRENT,
    AUDIT_RATE_LIMITED,
    UNCOUNTED_SIGNIN_RESULTS,
    ArcGISSignInError,
    signin_account_key,
    signin_user_key,
)
from app.modules.catalog.sources.models import ArcGISSignInAttempt

logger = structlog.stdlib.get_logger(__name__)

# The shared limit, and the window it is counted over.
_ARCGIS_SIGNIN_ATTEMPT_LIMIT = 3
_ARCGIS_SIGNIN_WINDOW = timedelta(minutes=15)

# fix(#1775): strong references keeping an in-flight settle write
# alive — `asyncio` holds tasks weakly, and this one is deliberately left
# running when the drain gives up on it.
_SETTLE_TASKS: set[asyncio.Task] = set()

# fix(#1775, #1825): ceiling on a settle write so a database that has
# stopped answering cannot hold a shutting-down worker open.
_SETTLE_DRAIN_SECONDS = 5.0


@dataclass(frozen=True)
class SignInTarget:
    """Everything one attempt is charged to, and the only shape that carries it.

    fix(#1775): one frozen value for the three fields that must always
    agree, so a phase cannot reserve against one account and settle against
    another.

    ``host`` is the canonical ``host:port/webadaptor`` of the destination
    that receives the password (fix(#1758) codex r7/r11), or the synthetic
    ``"unknown"`` for outcomes that precede discovery, where nothing was sent.
    """

    host: str
    account_key: str
    user_scope: str


def signin_target(user_id: uuid.UUID, host: str, username: str) -> SignInTarget:
    """Derive both digests for one (caller, destination, ArcGIS account)."""
    return SignInTarget(
        host=host,
        account_key=signin_account_key(host, username),
        user_scope=signin_user_key(user_id, host),
    )


def _signin_event(
    user_id: uuid.UUID,
    target: SignInTarget,
    result: str,
    note: str | None = None,
    *,
    attempt_id: uuid.UUID | None = None,
) -> AuditEvent:
    """The audit event for one sign-in outcome, the same row from every writer.

    Records the token-service HOST (never the portal URL) and a keyed digest
    (never the username) — the signal an operator watching for account
    walking needs, with nothing more.
    """
    return AuditEvent(
        user_id=user_id,
        action="arcgis_signin",
        resource_type="service_url",
        details={
            # fix(#1758): DESTINATION host from authInfo.tokenServicesUrl,
            # never the address the caller typed.
            "token_service_host": target.host,
            "result": result,
            "account_key": target.account_key,
            # fix(#1825): the reservation this outcome settles; distinguishes
            # a retry of one attempt from a second attempt.
            **({"attempt_id": str(attempt_id)} if attempt_id else {}),
            **({"discovery_note": note} if note else {}),
        },
    )


async def _signin_audit(
    db: AsyncSession,
    user_id: uuid.UUID,
    target: SignInTarget,
    result: str,
    note: str | None = None,
    *,
    reserved: bool = False,
    attempt_id: uuid.UUID | None = None,
) -> None:
    """Record one sign-in attempt on the caller's session and commit it.

    fix(#1775): ``reserved`` means the ledger row was already committed by
    :func:`_signin_reserve` before the credential POST, so this must not
    write a second one. An attempt that reaches an outcome without being
    reserved still counts here.
    """
    await audit_emit(
        db, _signin_event(user_id, target, result, note, attempt_id=attempt_id)
    )
    if not reserved and result not in UNCOUNTED_SIGNIN_RESULTS:
        # fix(#1758): written here, not at call sites, so the ledger
        # and audit row can never disagree — same transaction, commit or
        # fail together.
        db.add(
            ArcGISSignInAttempt(
                account_key=target.account_key, user_scope=target.user_scope
            )
        )
        await _sweep_expired_signin_attempts(db)
    await db.commit()


async def _sweep_expired_signin_attempts(db: AsyncSession) -> None:
    """Drop ledger rows that have aged out of the window.

    Opportunistic, on the write path, because the ledger has no other reader
    and no scheduled job should exist for a table this small. Every row it
    deletes is already outside the window, so it can never remove one a
    concurrent count would have seen, and the rate limits bound how often
    this runs to a handful of times per account per window.

    fix(#1775): rows are picked in a fixed order (`ORDER BY id`) with
    concurrent holders SKIPPED (`SKIP LOCKED`). Two sign-ins for different
    scopes hold different advisory locks and sweep concurrently — a bare
    `DELETE ... WHERE attempted_at < ...` let two sweeps take the same
    expired rows in plan-chosen order and deadlock (40P01) on housekeeping,
    failing an otherwise-fine sign-in. Dropping a skip-locked row costs
    nothing: it's already expired and the other sweeper is deleting it.
    """
    expired = (
        select(ArcGISSignInAttempt.id)
        .where(
            ArcGISSignInAttempt.attempted_at
            < datetime.now(tz=UTC) - _ARCGIS_SIGNIN_WINDOW
        )
        .order_by(ArcGISSignInAttempt.id)
        .with_for_update(skip_locked=True)
    )
    await db.execute(
        delete(ArcGISSignInAttempt).where(
            ArcGISSignInAttempt.id.in_(expired.scalar_subquery())
        )
    )


async def _signin_budgets_spent(db: AsyncSession, target: SignInTarget) -> bool:
    """Whether either attempt budget is spent inside the window.

    fix(#1758): cross-worker via the shared `arcgis_signin_attempts`
    table, so no new dependency on an install with only PostgreSQL.

    fix(#1758): TWO budgets, refusal on either. The account budget
    mirrors what Esri itself counts (a lockout belongs to the account, so a
    per-user limit alone lets colleagues jointly lock one account); the
    per-user budget stops one user from walking many accounts at three each.

    fix(#1758): the account budget counts `arcgis_signin_attempts`,
    not `audit_logs` — `audit_logs` carries `tenant_isolation_audit_logs`,
    which would make the budget per-tenant and let two tenants each send
    three failures at one account. The ledger is deliberately outside the
    RLS boundary (see that model's docstring).

    fix(#1775): the per-caller budget now reads the same ledger, keyed on
    `user_scope` (a digest, no plaintext identifier). It used to read
    `audit_logs`, but reserve-then-settle commits the attempt BEFORE the
    credential POST while the audit row writes after — a mid-POST
    cancellation would spend a real attempt with no audit row, undercounting
    exactly the attempts that matter.

    Outcomes GeoLens refused on its own account (no credential reached
    ArcGIS) don't count — an EXCLUSION list, so a refusal doesn't extend its
    own window and lock the caller out on every retry.
    """
    since = datetime.now(tz=UTC) - _ARCGIS_SIGNIN_WINDOW
    by_user = await db.scalar(
        select(func.count())
        .select_from(ArcGISSignInAttempt)
        .where(
            ArcGISSignInAttempt.user_scope == target.user_scope,
            ArcGISSignInAttempt.attempted_at >= since,
        )
    )
    if int(by_user or 0) >= _ARCGIS_SIGNIN_ATTEMPT_LIMIT:
        return True
    by_account = await db.scalar(
        select(func.count())
        .select_from(ArcGISSignInAttempt)
        .where(
            ArcGISSignInAttempt.account_key == target.account_key,
            ArcGISSignInAttempt.attempted_at >= since,
        )
    )
    return int(by_account or 0) >= _ARCGIS_SIGNIN_ATTEMPT_LIMIT


async def _signin_reserve(
    db: AsyncSession,
    user_id: uuid.UUID,
    target: SignInTarget,
    note: str | None = None,
) -> uuid.UUID:
    """Spend one attempt DURABLY, in one short transaction, before any password moves.

    Returns the ledger row's id, which the settle writes carry so one attempt
    cannot end up with two audit rows.

    fix(#1775): take both locks, read both budgets, insert the ledger row,
    commit — one transaction, so no caller can read either counter between
    this caller's read and write.

    fix(#1758): locks taken user-and-host FIRST, account SECOND —
    the account lock alone left the per-caller budget racy (one caller
    signing into three accounts on one host took three different account
    locks, so all three read the same pre-attempt count and all three passed
    a limit of three).

    The connection returns to the pool at commit, so the mint that follows
    holds none — thirteen concurrent sign-ins used to occupy a 10+3 pool for
    the full network budget and time out unrelated requests.

    Counted BEFORE the credential POST, not after: a `CancelledError` during
    the POST (worker shutdown) bypasses both `PortalSignIn.mint`'s
    `except Exception` and the route's `except ArcGISSignInError`, so
    write-at-settle lost both the ledger and audit rows while ArcGIS may
    have counted the password anyway. Counting first is the conservative
    direction — worst case a wasted attempt, not a lost ArcGIS account.

    Locks are held for this transaction only, so the "sign-in already in
    progress" 409 now fires on a collision inside the reservation, not
    across the whole mint — allowing up to three concurrent credential POSTs
    per account, still under Esri's five-failure account lock.
    """
    # Client-side rather than the column default: the caller needs the id and
    # a server default would cost a flush and a read back to learn it.
    reservation_id = uuid.uuid4()
    async with _signin_locks(
        db, f"user:{user_id}:host:{target.host}", f"account:{target.account_key}"
    ) as locked:
        if not locked:
            await _signin_refusal(db, user_id, target, _signin_in_progress(), note)
        if await _signin_budgets_spent(db, target):
            await _signin_refusal(db, user_id, target, _signin_rate_limited(), note)
        db.add(
            ArcGISSignInAttempt(
                id=reservation_id,
                account_key=target.account_key,
                user_scope=target.user_scope,
            )
        )
        await _sweep_expired_signin_attempts(db)
        await db.commit()
    return reservation_id


async def _write_settled_outcome(
    user_id: uuid.UUID,
    target: SignInTarget,
    result: str,
    note: str | None = None,
    attempt_id: uuid.UUID | None = None,
) -> AuditEvent | None:
    """Write one settled attempt's audit row on a session of its OWN, at most once.

    Returns the event when this call wrote the row, and ``None`` when a row
    already carried this ``attempt_id``: the interrupted commit had landed.

    fix(#1775): NOT the request's session — the caller stops waiting at
    a deadline and the route re-raises, which would close the request
    session's connection under a statement still running.

    fix(#1889): one INSERT arbitrated by `uq_audit_logs_arcgis_signin_attempt`
    that no-ops when a row already carries this `attempt_id`, so a commit the
    cancellation interrupted can land at any point without a second row.

    Only the `audit_logs` row is written here; :func:`_forward_settled_outcome`
    reaches every other registered sink.

    Late-bound import (fix(#909), per `test_layering.py`): a module-scope
    binding would snapshot the dev-DB factory before the test fixture
    rebinds `app.core.db.async_session`.
    """
    from app.core.db import async_session

    event = _signin_event(user_id, target, result, note, attempt_id=attempt_id)
    settle = (
        pg_insert(AuditLog)
        .values(
            user_id=event.user_id,
            action=event.action,
            resource_type=event.resource_type,
            details=event.details,
        )
        .on_conflict_do_nothing(
            index_elements=[text(ARCGIS_SIGNIN_SETTLE_KEY)],
            index_where=text(ARCGIS_SIGNIN_SETTLE_WHERE),
        )
    )
    async with async_session() as session:
        inserted = (await session.execute(settle)).rowcount == 1
        await session.commit()
    return event if inserted else None


async def _forward_settled_outcome(event: AuditEvent, sinks: list) -> None:
    """Hand a written outcome to every registered sink except the ``audit_logs`` one.

    fix(#1889): a cancel can land while the ``audit_logs`` sink is still on
    its round trips and before a later sink ran, so a written row is no
    proof the others heard it — at-least-once for them, keyed on
    ``attempt_id``. Late-bound import, for the reason
    :func:`_write_settled_outcome` gives.
    """
    from app.core.db import async_session

    async with async_session() as session:
        await audit_emit(session, event, sinks=sinks)
        await session.commit()


def _settle_failure(settle: asyncio.Future) -> str | None:
    """What stopped the settle write, by name, or ``None`` when it landed.

    fix(#1775): PENDING is checked FIRST. A task just asked to cancel
    is neither done nor cancelled, and `Future.exception()` on a pending
    task raises `InvalidStateError` — on the drain-deadline path that would
    have escaped the finaliser and propagated instead of the
    `CancelledError` being re-raised, silently dropping the warning log.

    A cancellation this module asked for reads as `CancelledError` whether
    the task has finished unwinding yet or not — that's what stopped the
    write either way.
    """
    if not settle.done() or settle.cancelled():
        return "CancelledError"
    exc = settle.exception()
    return None if exc is None else type(exc).__name__


async def _drain_shielded(coro, deadline: float) -> asyncio.Future:
    """Run *coro* under a shield until it finishes or *deadline* passes.

    The caller is inside `except asyncio.CancelledError`, and every request
    runs under an anyio cancel scope that re-arms cancellation on every
    await — so one shielded await per event-loop turn, until the work lands
    or time runs out. Holds a strong reference throughout since the event
    loop keeps only a weak one, and cancels at the deadline rather than
    leaving the work unbounded.
    """
    task = asyncio.ensure_future(coro)
    _SETTLE_TASKS.add(task)
    task.add_done_callback(_SETTLE_TASKS.discard)
    loop = asyncio.get_running_loop()
    while not task.done() and loop.time() < deadline:
        with contextlib.suppress(BaseException):  # broad: the loop decides
            await asyncio.shield(task)
    if not task.done():
        task.cancel()
    return task


async def _signin_settle_shielded(
    user_id: uuid.UUID,
    target: SignInTarget,
    result: str,
    note: str | None = None,
    *,
    attempt_id: uuid.UUID | None = None,
    release: AsyncSession | None = None,
) -> None:
    """Record *result* for an attempt whose settlement a cancellation cut short.

    Best effort, deliberately: the ledger row is already durable, and what's
    missing is only the operator-facing half — a failure here is logged and
    swallowed rather than replacing a cancellation with a database error.

    *release* is the request's session, rolled back first so this write does
    not queue behind a connection FastAPI has not torn down yet.
    *attempt_id* is the reservation; a row already carrying it means an
    interrupted commit landed after all, so nothing is written.

    Everything runs under one ceiling: a rollback that cannot finish spends
    it and the write is abandoned with a warning; a sink that cannot finish
    is cut off with the row already durable, and says so.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + _SETTLE_DRAIN_SECONDS
    if release is not None:
        # fix(#1825): the request session owns its connection until
        # FastAPI's teardown, which does not run until the route re-raises, so
        # the write below would queue behind it on a pool with no spare slot.
        await _drain_shielded(release.rollback(), deadline)
    settle = await _drain_shielded(
        _write_settled_outcome(user_id, target, result, note, attempt_id), deadline
    )
    failure = _settle_failure(settle)
    if failure is not None:
        # No credential, token or username here: only the destination host
        # and the exception TYPE (never the instance, which can hold a
        # request whose encoded body is the password) — same as
        # `PortalSignIn.mint` logs on a transport failure.
        logger.warning(
            "ArcGIS sign-in cancelled before its outcome could be recorded",
            token_service_host=target.host,
            error_type=failure,
        )
        return
    written = settle.result()
    sinks = extension_audit_sinks()
    if written is None or not sinks:
        return
    forward = await _drain_shielded(_forward_settled_outcome(written, sinks), deadline)
    failure = _settle_failure(forward)
    if failure is not None:
        logger.warning(
            "ArcGIS sign-in outcome recorded but not forwarded to every audit sink",
            token_service_host=target.host,
            error_type=failure,
        )


@contextlib.asynccontextmanager
async def _signin_locks(
    db: AsyncSession, user_scope: str, account_scope: str
) -> AsyncIterator[bool]:
    """Hold both sign-in locks on the REQUEST session, yielding whether both were free.

    fix(#1758): transaction-scoped locks (`pg_try_advisory_xact_lock`),
    not the session-scoped variant — that one outlives the pool's
    rollback-on-return, so one missed unlock would lock an account out for
    the life of that pooled connection.

    fix(#1758): two scopes taken in argument ORDER (caller-and-host
    before account) by every caller, so no two can hold one another's next
    lock.

    fix(#1758): on the request's OWN session, so a sign-in costs
    ONE pooled connection — a dedicated lock session cost two, checked out
    in an order where thirteen concurrent sign-ins could each hold a lock
    connection and queue for a request connection the other twelve held,
    stalling unrelated traffic until the pool timeout.

    fix(#1775): the transaction they ride is now the RESERVATION's — open
    from the first lock through the ledger insert and no further. The commit
    that ends it both persists the row and releases the locks, in that
    order, buying #1758's no-interleaving property without holding a
    connection across the network budget.

    Both are TRY-locks: a busy scope answers immediately rather than
    queuing, so a caller never waits on another caller's portal round trip.
    """
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
    target: SignInTarget,
    exc: ArcGISSignInError,
    note: str | None = None,
    *,
    reserved: bool = False,
    attempt_id: uuid.UUID | None = None,
) -> NoReturn:
    """Log, audit and raise one classified refusal.

    fix(#1758): one exit for all six refusal sites, so the log
    line, audit row and HTTPException can't drift apart by being
    hand-written at each.

    fix(#1775): ``reserved`` passes straight through to
    :func:`_signin_audit`, so a refusal following the reservation doesn't
    count the attempt a second time.
    """
    logger.warning(
        "ArcGIS sign-in refused",
        token_service_host=target.host,
        code=exc.code,
        result=exc.audit_result,
    )
    try:
        await _signin_audit(
            db,
            user_id,
            target,
            exc.audit_result,
            note,
            reserved=reserved,
            attempt_id=attempt_id,
        )
    except Exception:  # broad: any failed transaction, whatever poisoned it
        # fix(#1758): a refusal must be recorded even when a
        # cancellation left this session's transaction failed. Rolling back
        # is the only way to a usable session, and costs nothing here since
        # `_signin_audit` commits, so there is never uncommitted work to lose.
        await db.rollback()
        await _signin_audit(
            db,
            user_id,
            target,
            exc.audit_result,
            note,
            reserved=reserved,
            attempt_id=attempt_id,
        )
    # `from None`: the chained cause of a transport failure is an httpx error
    # holding the request whose encoded body is the password, and nothing
    # downstream needs it.
    raise HTTPException(
        status_code=exc.status_code,
        detail={"code": exc.code, "message": exc.message, "field": exc.field},
    ) from None
