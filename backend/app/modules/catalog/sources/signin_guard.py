"""Abuse controls for the ArcGIS sign-in route.

Everything here answers one question: may this caller spend one more ArcGIS
sign-in attempt right now, and what is recorded when they do. It is separated
from ``router.py`` because none of it is routing, and because the route module
sits under a 1500-line cap that this grew through five review rounds.

The shape, in the order the route applies it:

* fix(#1775): RESERVE, then SETTLE, and nothing here holds a pooled
  connection across the network. :func:`_signin_reserve` is one short
  transaction that takes both advisory locks, reads both budgets and commits
  the ledger row, all BEFORE the credential POST; the route then mints with
  no session held, and :func:`_signin_audit` writes the outcome in a second
  short transaction. A cancellation during the POST therefore cannot lose the
  count: it is already committed.
* two PostgreSQL advisory locks, taken caller-and-portal first and account
  second, so the budget read and the ledger write are serialized and the pair
  cannot deadlock (see :func:`_signin_locks`);
* two budgets, three attempts per fifteen minutes each, one per target ArcGIS
  account and one per caller and token service, both read from the ledger for
  the reason :func:`_signin_budgets_spent` gives;
* one audit row per attempt, and one ledger row for each attempt that counts.

Nothing here holds a credential. The caller's username reaches the route and
is turned into a keyed digest before anything in this module sees it.
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
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.service import AuditEvent, audit_emit
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

# fix(#1775 audit): the strong references that keep an in-flight settle write
# alive. `asyncio` holds tasks weakly, and this one is deliberately left
# running when the drain gives up on it, so nothing else would.
_SETTLE_TASKS: set[asyncio.Task] = set()

# fix(#1775): how long _signin_settle_shielded will keep handing the event
# loop a turn so its shielded audit write can finish. One local INSERT and
# COMMIT, so a second is three orders of magnitude of headroom; the ceiling is
# there so a database that has stopped answering cannot hold a shutting-down
# worker open, not because the write is expected to need it.
_SETTLE_DRAIN_SECONDS = 1.0


@dataclass(frozen=True)
class SignInTarget:
    """Everything one attempt is charged to, and the only shape that carries it.

    fix(#1775): three values that must always agree — the canonical
    token-service scope, the account digest and the caller digest — travelled
    as three parallel arguments through five functions, and the reserve/settle
    split adds a third phase that has to charge the same three. One frozen
    value means a phase cannot reserve against one account and settle against
    another.

    ``host`` is the canonical ``host:port/webadaptor`` of the destination that
    receives the password (fix(#1758 codex r7/r11)), or the synthetic
    ``"unknown"`` for the outcomes that precede discovery, where nothing was
    sent.
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


async def _signin_audit(
    db: AsyncSession,
    user_id: uuid.UUID,
    target: SignInTarget,
    result: str,
    note: str | None = None,
    *,
    reserved: bool = False,
) -> None:
    """Record one sign-in attempt: who, which portal, which account, what happened.

    The token-service HOST rather than the portal URL, and a keyed digest
    rather than the username: an audit row is read by an operator looking for someone walking
    accounts, and the host, the digest and the outcome are the whole of that
    signal. ``result`` carries the distinction the caller-facing message
    deliberately collapses.

    fix(#1775): ``reserved`` says the ledger row for this attempt was already
    committed by :func:`_signin_reserve` before the credential POST, so this
    call must not write a second one. It is NOT a rename of the exclusion
    list: an attempt that reaches an outcome without ever being reserved —
    every refusal that precedes discovery, and any counted outcome a later
    change adds there — still counts here, so the exclusion list keeps its
    "a new outcome counts until somebody decides otherwise" property.
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
                "token_service_host": target.host,
                "result": result,
                # fix(#1758 codex r3): a keyed digest of the target account,
                # never the username. It is what both budgets below are
                # counted on, and it is the only trace of which ArcGIS account
                # was addressed that survives the request.
                "account_key": target.account_key,
                # fix(#1758 codex r9): present only when discovery turned up
                # something an operator should see, so the common row keeps
                # its shape.
                **({"discovery_note": note} if note else {}),
            },
        ),
    )
    if not reserved and result not in UNCOUNTED_SIGNIN_RESULTS:
        # fix(#1758 codex r4): both budgets' own copy, in the one table that is
        # not tenant-scoped. Written here rather than at the call sites so the
        # ledger and the audit row can never disagree about what counted. Same
        # transaction, so they commit or fail together.
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

    fix(#1775 audit): the rows are picked in a fixed order and any a
    concurrent sweep already holds are SKIPPED. Two sign-ins for different
    scopes hold different advisory locks, so their sweeps run concurrently and
    a bare ``DELETE ... WHERE attempted_at < ...`` let them take the same
    expired rows in whatever order the plan chose — deadlock (40P01) on a
    statement whose whole job is housekeeping, failing a sign-in that had
    nothing wrong with it. ``ORDER BY id`` gives every sweeper one order, and
    ``SKIP LOCKED`` means the loser of a race drops the row rather than
    queueing for it. Dropping it costs nothing: the row is already expired and
    the other sweeper is deleting it.
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

    fix(#1758 codex r4): the account budget counts ``arcgis_signin_attempts``
    rather than ``audit_logs``, and that is the fix rather than an accident.
    ``audit_logs`` carries ``tenant_isolation_audit_logs``, so counting there
    made the budget per tenant and let two tenants send six failures at one
    account. The ledger is deliberately outside the RLS boundary; see that
    model's docstring for why that is safe.

    fix(#1775): the per-caller budget now counts the SAME table, keyed on
    ``user_scope``. It read ``audit_logs`` while the audit row was the only
    record of an attempt, and that was correct then: a limit on one caller
    only ever needs that caller's own rows, so tenant scoping cost it nothing.
    Reserve-then-settle breaks the premise rather than the reasoning. The
    attempt is now committed BEFORE the credential POST and the audit row is
    written after it, so a request cancelled mid-POST has spent a real
    attempt and left no audit row at all, and an ``audit_logs`` count would
    undercount exactly the attempts this endpoint most needs to remember.
    ``user_scope`` is a keyed digest of the caller and the token-service
    scope, so the ledger still holds no plaintext identifier and one caller
    still only ever counts their own rows.

    Outcomes GeoLens refused on its own account do not count, because no
    credential reached ArcGIS on those and Esri counted nothing. That set is
    an EXCLUSION list rather than an inclusion list, so a new outcome added
    later counts toward the limit until somebody decides otherwise. It also
    keeps a refusal from extending its own window: a rate-limited attempt
    that counted itself would hold the caller over the limit for another
    fifteen minutes on every retry, and they would never get back in. The
    ledger holds only counted attempts, so it needs no such filter — which is
    the second reason both budgets now read it rather than one.
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
) -> None:
    """Spend one attempt DURABLY, in one short transaction, before any password moves.

    fix(#1775): this is the whole of the issue's shape. Take both locks, read
    both budgets, insert the ledger row, commit. Everything in that sentence
    is inside one transaction, so the no-interleaving property #1758 built the
    locks for survives intact: no other caller can read either counter between
    this caller's read and this caller's write.

    fix(#1758 codex r5): both locks, taken user-and-host FIRST and account
    SECOND, and that order is the whole of the deadlock argument. The account
    lock alone left the per-caller budget racy: one caller signing in to three
    different accounts on one host took three different account locks, so all
    three read the same pre-attempt count and all three passed a limit of
    three.

    Two things change, and both are the point.

    The connection goes back to the pool at the commit, so the mint that
    follows holds none. Thirteen concurrent sign-ins for distinct scopes used
    to be able to occupy a 10+3 pool for the 45-second network budget and time
    out unrelated API requests; now a sign-in touches the pool only for this
    transaction and the settle that follows it, and never while the network is
    in flight.

    The attempt is counted BEFORE the credential POST rather than after it. A
    ``CancelledError`` during the POST — a worker shutting down, which on the
    pinned Starlette is the only source that reaches the route, since a client
    hanging up arrives as an ``http.disconnect`` message a non-streaming route
    never reads (fix(#1775 audit)) —
    bypasses both ``PortalSignIn.mint``'s ``except Exception`` and the route's
    ``except ArcGISSignInError``, so under write-at-settle the audit row and
    the ledger row were both lost while ArcGIS may well have counted the
    password. Counting first is the conservative direction: the worst case is
    an attempt charged for a POST that never left, which costs the caller one
    of three, where the other direction costs a customer their ArcGIS account.

    The locks are held for this transaction only, so the 409 that says a
    sign-in is already in progress now fires on a collision inside the
    reservation rather than across the whole mint. That is not a weakening of
    the counter: what the lock protected was the read-then-write race, and the
    read and the write are both in here. What it does allow is up to three
    concurrent credential POSTs for one account instead of one, and three is
    the budget's own ceiling, still strictly below the five failures Esri
    locks an account on.
    """
    async with _signin_locks(
        db, f"user:{user_id}:host:{target.host}", f"account:{target.account_key}"
    ) as locked:
        if not locked:
            await _signin_refusal(db, user_id, target, _signin_in_progress(), note)
        if await _signin_budgets_spent(db, target):
            await _signin_refusal(db, user_id, target, _signin_rate_limited(), note)
        db.add(
            ArcGISSignInAttempt(
                account_key=target.account_key, user_scope=target.user_scope
            )
        )
        await _sweep_expired_signin_attempts(db)
        await db.commit()


async def _write_settled_outcome(
    user_id: uuid.UUID,
    target: SignInTarget,
    result: str,
    note: str | None = None,
) -> None:
    """Write one settled attempt's audit row on a session of its OWN.

    fix(#1775 audit): NOT the request's session. The caller below stops
    waiting at a deadline and the route then re-raises, so FastAPI runs
    ``get_db``'s teardown and closes the request session — which, if this
    write were still in flight on it, closes the connection out from under a
    live statement and turns a lost audit row into an ``InterfaceError`` or a
    greenlet error on a shutting-down worker. A session this coroutine opens
    and closes in its own frame cannot be closed by anybody else, so the
    abandoned case is a task that finishes quietly rather than one that
    faults.

    Late-bound import, per the rule ``test_layering.py`` enforces (fix(#909)):
    a module-scope binding snapshots the dev-DB factory before the test
    fixture rebinds ``app.core.db.async_session``.
    """
    from app.core.db import async_session

    async with async_session() as session:
        # `reserved=True` unconditionally: every caller of this reaches it
        # after `_signin_reserve` committed, so the ledger row already exists.
        await _signin_audit(session, user_id, target, result, note, reserved=True)


def _settle_failure(settle: asyncio.Future) -> str | None:
    """What stopped the settle write, by name, or ``None`` when it landed.

    fix(#1775 audit): PENDING is its own answer and it is checked FIRST. A
    task that has only just been asked to cancel is neither done nor
    cancelled, and ``Future.exception()`` on a pending task raises
    ``InvalidStateError`` — which would have escaped the finaliser on the one
    path the drain deadline exists for, so the route's ``raise`` would have
    propagated an ``InvalidStateError`` instead of the ``CancelledError`` it
    was re-raising, and the warning would never have been logged. Verified
    with a plain asyncio repro: after ``cancel()``, ``done()`` is False,
    ``cancelled()`` is False, and ``exception()`` raises.

    A cancellation this module asked for reads as ``CancelledError`` whether
    the task has finished unwinding yet or not, because that is what stopped
    the write either way.
    """
    if not settle.done() or settle.cancelled():
        return "CancelledError"
    exc = settle.exception()
    return None if exc is None else type(exc).__name__


async def _signin_settle_shielded(
    user_id: uuid.UUID,
    target: SignInTarget,
    result: str,
    note: str | None = None,
) -> None:
    """Record *result* for an attempt a cancellation interrupted.

    fix(#1775): a shielded finaliser rather than a bare ``finally``, and the
    distinction matters in both directions.

    Why a finaliser at all, when the count is already durable: the ledger row
    was committed by :func:`_signin_reserve` before the POST, so the budget is
    correct whether or not this ever runs. What is missing after a cancellation
    is the OPERATOR-facing half — the audit row that says a password went to
    this token service on this caller's say-so. Silence there reads as "no
    attempt", which is the one thing that is not true.

    fix(#1825): *result* is a parameter because the gap is on both sides of
    the mint. A cancellation in the settle loses that outcome's row exactly
    as one in the POST loses the ``cancelled`` row.

    Why a shield rather than a plain await, and why the loop. The caller
    reaches here from ``except asyncio.CancelledError``, and a plain await
    would simply be cancelled again. Measured rather than assumed: a bare
    ``await asyncio.shield(...)`` here returns ``CancelledError``, not the
    written row. Every request runs as a child of the anyio task group each
    ``BaseHTTPMiddleware`` layer starts the downstream app in
    (``task_group.start_soon(coro)``, middleware/base.py:148), and an anyio
    cancel scope re-arms cancellation on EVERY await a task makes inside it
    while the scope is cancelled. The same call under a bare
    ``asyncio.Task.cancel()``, with no middleware, completes first time. So
    the shield is necessary and not sufficient: it keeps the write itself
    alive across those re-arms, and the loop is what waits for it.

    The loop is a bounded drain, not a spin. Each pass awaits, so each pass
    hands the event loop a turn and the shielded write is what makes progress;
    it ends the moment that write finishes, and a wall-clock deadline ends it
    anyway. One local INSERT and COMMIT is milliseconds against a one-second
    ceiling, and this runs at most once per request still in flight when a
    worker shuts down.

    Still best effort, and it says so by swallowing. The database may be
    unreachable under a shutting-down worker, and there is nothing useful to do
    about that from inside a cancelled request; re-raising would only replace a
    cancellation with a database error. Durability lives in the reservation.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + _SETTLE_DRAIN_SECONDS
    settle = asyncio.ensure_future(
        _write_settled_outcome(user_id, target, result, note)
    )
    # fix(#1775 audit): the event loop keeps only a WEAK reference to a task,
    # so a settle this function stops awaiting at the deadline could be
    # collected mid-write. Held here until it finishes, whichever way it
    # finishes, which is also what keeps the abandoned case a task that
    # completes rather than one that vanishes.
    _SETTLE_TASKS.add(settle)
    settle.add_done_callback(_SETTLE_TASKS.discard)
    while not settle.done() and loop.time() < deadline:
        # One shield future per event-loop turn, which is the price of
        # surviving anyio's re-arm and is only paid while a re-arm is
        # happening: with no cancel scope re-arming this awaits ONCE and
        # blocks there until the write finishes. Every outcome is handled by
        # the loop condition rather than here — a completed write ends it, a
        # failed one ends it with `settle.done()` true and is reported below,
        # and a re-armed cancellation is the thing this exists to absorb.
        with contextlib.suppress(BaseException):  # broad: the loop decides
            await asyncio.shield(settle)
    if not settle.done():
        # fix(#1775 audit): the task keeps a session of its own, so leaving it
        # to unwind after this returns cannot fault against a session somebody
        # else closed. Cancelling is still right: a write that lands after the
        # request is gone is a row nobody is waiting for.
        settle.cancel()
    failure = _settle_failure(settle)
    if failure is not None:
        # No credential, no token and no username in this line: the scope is
        # the destination host that every other row here already carries, and
        # the exception TYPE, which is the same thing `PortalSignIn.mint` logs
        # on a transport failure and for the same reason — the instance can
        # hold a request whose encoded body is the password.
        logger.warning(
            "ArcGIS sign-in cancelled before its outcome could be recorded",
            token_service_host=target.host,
            error_type=failure,
        )


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
    traffic until the pool timeout.

    fix(#1775): the transaction they ride is now the RESERVATION's, which is
    open from the first lock through the budget reads to the ledger insert,
    and no further. The commit that ends it is both what persists the row and
    what releases the locks, in that order, so no other caller can read either
    counter between this one's read and its write — the property #1758 needed,
    now bought without holding a connection across a 45-second network budget.
    An unwind without a commit releases them when the request session is
    closed and rolled back.

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
    target: SignInTarget,
    exc: ArcGISSignInError,
    note: str | None = None,
    *,
    reserved: bool = False,
) -> NoReturn:
    """Log, audit and raise one classified refusal.

    fix(#1758 codex r5): one exit for every refusal, because there are now six
    of them across two nested locks and hand-writing the log line, the audit
    row and the HTTPException at each was how they would drift apart.

    fix(#1775): ``reserved`` is passed straight through to
    :func:`_signin_audit`, so a refusal that follows the reservation records
    its outcome without counting the attempt a second time.
    """
    logger.warning(
        "ArcGIS sign-in refused",
        token_service_host=target.host,
        code=exc.code,
        result=exc.audit_result,
    )
    try:
        await _signin_audit(
            db, user_id, target, exc.audit_result, note, reserved=reserved
        )
    except Exception:  # broad: any failed transaction, whatever poisoned it
        # fix(#1758 codex r11): a refusal has to be recorded even when the
        # session it arrives on is already broken. A cancellation landing in a
        # flush or a commit leaves the transaction failed, every later
        # statement on it errors, and the row that says a credential POST went
        # out would be lost with it. Rolling back is the only way back to a
        # usable session, and it costs nothing here: `_signin_audit` commits,
        # so there is never uncommitted work of ours to discard.
        await db.rollback()
        await _signin_audit(
            db, user_id, target, exc.audit_result, note, reserved=reserved
        )
    # `from None`: the chained cause of a transport failure is an httpx error
    # holding the request whose encoded body is the password, and nothing
    # downstream needs it.
    raise HTTPException(
        status_code=exc.status_code,
        detail={"code": exc.code, "message": exc.message, "field": exc.field},
    ) from None
