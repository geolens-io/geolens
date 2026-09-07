"""One-time handoff of a service credential from the API to the worker.

A refresh of a protected service needs a token in the worker, a different
process. Every existing way of getting one there is durable: Procrastinate
task arguments are rows in ``catalog.procrastinate_jobs``,
``ingest_jobs.user_metadata`` is a column, and a failed job keeps both until
the retention purge. The credential must never land in a committed row, so
the handoff needs a channel that is neither PostgreSQL nor the request.

This module is that channel: the API writes the secret once under an
unguessable reference with a short TTL, passes only the REFERENCE through
task arguments, and the worker consumes it with an atomic read-and-delete.
Three properties matter:

- **Single use.** ``GETDEL`` reads and deletes in one server-side operation,
  so two claimants cannot both succeed — a ``GET`` followed by a ``DELETE``
  would leave exactly the window ``GETDEL`` exists to close.
- **Bounded lifetime.** ``SET ... EX`` expires the key whether or not anyone
  claims it, so a dispatch that never reaches a worker leaves no credential
  behind. The TTL stays short: rather than sizing it for the worst-case
  queue, :func:`renew_queued_refresh_credentials` re-arms it while the
  dispatch is provably still waiting, so the lifetime IS the queue wait, not
  an estimate of it. See :data:`CREDENTIAL_TTL_SECONDS`.
- **Nothing durable.** The reference is a random string that means nothing
  once claimed or expired — the only thing that reaches a task argument or
  a log line.

### Why this needs a real shared cache

``REDIS_URL`` is unset by default (the compose ``valkey`` service is opt-in
behind ``cloud-dev``), and the ordinary cache provider degrades to an
in-memory dict when missing. That's right for a cache and wrong for this:
API and worker are separate processes, so an in-memory write is invisible to
the claimant, and every credentialed refresh would fail as
``credential_expired`` with nothing in the logs saying why. So this module
talks to Valkey directly rather than through ``get_cache()``, and
:func:`credential_store_available` reports honestly when there is no store —
the refresh endpoint refuses a token-bearing request up front in that case,
a clear error at the door instead of a confusing failure an hour later.

### Three doors, one mechanism, three states

#1220 wired the refresh door only; the first-import and re-upload-commit
doors kept passing their token as a task argument, because refusing a
credentialed request without Valkey would have broken protected imports on
every stock install. feat(#1676) closes the gap by keying the decision on
what the install HAS, not which door the request came through:

- **state 1, store configured and reachable** — stash, dispatch the
  reference, claim once in the worker. Nothing durable, at every door.
- **state 2, store configured but the stash fails** — 503
  ``credential_store_unavailable``, identical at every door: an operator who
  opted into a store is told it is broken rather than silently downgraded.
- **state 3, no store configured at all** — the token rides in the task
  argument, as always at the two pre-existing doors. The refresh door
  refuses here and keeps refusing: token-bearing refresh has never worked
  without a store.

State 3 is the one deliberate asymmetry — a uniform refusal would break
protected import on the default install, the trade #1220 already declined.

:func:`resolve_dispatch_credential` decides all three for the two doors that
can reach state 3, so they can't drift from each other or from this text.
The refresh door does not call it: it refuses state 3 explicitly in its own
handler before writing anything, then reaches states 1 and 2 through
:func:`stash_service_credential`, the only other call this helper makes.
"""

from __future__ import annotations

import re
import secrets
from typing import Any, Protocol

import structlog
from sqlalchemy import text

from app.core.service_tokens import ServiceCredential
from app.platform.service_auth import wire_credential

logger = structlog.get_logger(__name__)

# fix(#1277): the TTL is bounded by RENEWAL, not by a constant.
#
# Deriving it from JOB_TIMEOUT_SECONDS was tried and is wrong:
# `maintain_ingest_job_heartbeat` refreshes `heartbeat_at` every 30s and the
# sweep only fails rows whose heartbeat has gone stale, so that constant
# bounds a DEAD worker's lease, not a healthy long import — a legitimate
# multi-hour ingest at the queue head would outlive any fixed constant, and
# raising it is a step toward durable storage, which ADR-002 Amendment A7 forbids.
#
# So the lifetime tracks the real queue wait instead: the TTL stays short,
# and `renew_queued_refresh_credentials` re-arms it every sweep cycle for
# credentials whose dispatch is still waiting. Renewal stops on its own at
# the abandonment sweep's own definition of a run still being alive.
#
# Arithmetic: renewal runs once per CREDENTIAL_RENEWAL_INTERVAL_SECONDS
# (300s), so the TTL must survive at least two cycles, or a single skipped
# pass (slow sweep, GC pause, restart between cycles) expires a credential
# whose task is still queued. Two cycles is 600s; the remaining 300s is
# jitter margin, giving 900.
#
# If the API dies, renewal stops and the credential expires within one TTL —
# the correct outcome, not a gap: nothing is left to dispatch the work, and
# the run fails `credential_expired`, whose message says to start again.
CREDENTIAL_RENEWAL_INTERVAL_SECONDS = 300

CREDENTIAL_TTL_SECONDS = 3 * CREDENTIAL_RENEWAL_INTERVAL_SECONDS

_KEY_PREFIX = "geolens:refresh-cred:"

# The reference is generated by :func:`stash_service_credential`, but it's
# also the only thing between a task argument and a key lookup, and task
# arguments are rows a future migration or backfill could touch.
# Constraining the shape means a malformed reference can never be composed
# into a lookup for some other key.
_REF_PATTERN = re.compile(r"\A[A-Za-z0-9_-]{22,64}\Z")


class CredentialStoreUnavailable(RuntimeError):
    """No shared credential store is configured.

    Raised at the API door, before anything is written, so the caller gets a
    503 naming the missing configuration rather than a dispatch that fails in
    a worker an hour later for reasons nothing surfaces.
    """


class CredentialExpiredError(RuntimeError):
    """The reference names nothing: already claimed, or past its TTL.

    Both are the same fact from the worker's side — no credential to fetch —
    and both are permanent for this attempt, since a single-use secret is
    gone the moment it's read. The refresh worker turns this into the
    ``credential_expired`` run error code ("supply a token and try again"
    rather than blaming the origin); the import worker has no run row and
    carries the same sentence as its ``error_message``.
    """


class CredentialBackend(Protocol):
    """The two operations this module needs from a shared store."""

    async def put(self, key: str, value: str, ttl_seconds: int) -> None:
        """Store *value* under *key*, expiring after *ttl_seconds*."""
        ...

    async def take(self, key: str) -> str | None:
        """Atomically read and delete *key*. None when it does not exist."""
        ...

    async def renew(self, key: str, ttl_seconds: int) -> bool:
        """Re-arm *key*'s expiry. False when it no longer exists."""
        ...


class RedisCredentialBackend:
    """Valkey/Redis backend. ``SET NX EX`` to write, ``GETDEL`` to claim.

    ``NX`` makes a reference collision a write failure rather than a silent
    overwrite of somebody else's in-flight credential. With 24 random bytes a
    collision is not a thing that happens, which is exactly why treating it as
    an error costs nothing.

    No circuit breaker and no in-memory fallback, unlike
    ``RedisCacheProvider``: a fallback here would accept a credential the
    worker can never read. Failing the write is the honest outcome.

    fix(#1277): both operations translate transport failures into
    ``CredentialStoreUnavailable`` at this boundary rather than letting
    redis-py's own exceptions escape. Untranslated, they broke both callers
    differently — a connection error during stash returned 500 instead of
    503, and one during claim was swallowed and reported as
    ``credential_expired``, blaming a spent token for what was actually an
    outage. Reaching the store is an availability question the store
    answers; only the store SAYING the key is absent is evidence about the
    credential.

    The exception is never rendered into the message either: redis-py bakes
    the command it was running — including the key — into its error text.
    """

    def __init__(self, url: str) -> None:
        import redis.asyncio as redis_async

        self._client = redis_async.from_url(url, decode_responses=True)

    async def put(self, key: str, value: str, ttl_seconds: int) -> None:
        try:
            stored = await self._client.set(key, value, ex=ttl_seconds, nx=True)
        except Exception as exc:  # broad: any transport failure means "no store"
            logger.warning(
                "refresh_credential_store_write_failed", error_type=type(exc).__name__
            )
            raise CredentialStoreUnavailable(
                "The credential store could not be reached, so this request "
                "cannot be started with a token."
            ) from exc
        if not stored:
            raise CredentialStoreUnavailable(
                "Could not stash the service credential for this request."
            )

    async def take(self, key: str) -> str | None:
        try:
            return await self._client.getdel(key)
        except Exception as exc:  # broad: any transport failure means "cannot tell"
            logger.warning(
                "refresh_credential_store_read_failed", error_type=type(exc).__name__
            )
            raise CredentialStoreUnavailable(
                "The credential store could not be reached, so this job "
                "could not retrieve its token."
            ) from exc

    async def renew(self, key: str, ttl_seconds: int) -> bool:
        """``EXPIRE``, which is a no-op on a key that is already gone.

        That is the property the renewal sweep needs: a credential claimed
        between the query and this call cannot be resurrected, because
        ``EXPIRE`` only ever moves the deadline of a key that still exists.
        Redis reports that as 0, and this returns False.

        Failures are swallowed, not raised: a missed renewal costs at most
        one cycle (the TTL is sized to survive two), and this runs in a
        background sweep with nobody to report to.
        """
        try:
            return bool(await self._client.expire(key, ttl_seconds))
        except Exception as exc:  # broad: a missed renewal is not fatal
            logger.warning(
                "refresh_credential_renew_failed", error_type=type(exc).__name__
            )
            return False


_backend: CredentialBackend | None = None
_backend_url: str | None = None


def credential_store_available() -> bool:
    """Whether a token-bearing refresh can be dispatched at all.

    Reads the setting rather than the cached backend so the answer does not
    depend on whether anything has stashed a credential yet in this process.
    """
    from app.core.config import settings

    return bool(settings.redis_url) or _backend is not None


def get_credential_backend() -> CredentialBackend:
    """The process-wide backend, built on first use.

    Rebuilt when ``redis_url`` changes so a test that points the setting
    somewhere else is not served a client for the previous address.
    """
    global _backend, _backend_url
    from app.core.config import settings

    if _backend is not None and _backend_url == settings.redis_url:
        return _backend
    if not settings.redis_url:
        raise CredentialStoreUnavailable(
            "Handing a service token to the worker requires a shared "
            "credential store. Set REDIS_URL to a Valkey/Redis instance "
            "reachable by both the API and the worker."
        )
    _backend = RedisCredentialBackend(settings.redis_url)
    _backend_url = settings.redis_url
    return _backend


def set_credential_backend(backend: CredentialBackend | None) -> None:
    """Install a backend directly, for tests and for embedding hosts.

    Passing ``None`` clears both the backend and the URL it was built for, so
    the next :func:`get_credential_backend` rebuilds from settings.
    """
    global _backend, _backend_url
    _backend = backend
    _backend_url = None
    if backend is not None:
        from app.core.config import settings

        _backend_url = settings.redis_url


async def stash_service_credential(
    secret: str, *, ttl_seconds: int = CREDENTIAL_TTL_SECONDS
) -> str:
    """Store *secret* once and return the reference that claims it.

    The reference is the only value safe to persist, log, or pass as a task
    argument. Nothing about the secret is derivable from it — it is random,
    not a hash — so a leaked reference after the claim or the TTL is worth
    nothing at all.
    """
    if not secret:
        raise ValueError("refusing to stash an empty credential")
    ref = secrets.token_urlsafe(24)
    await get_credential_backend().put(_KEY_PREFIX + ref, secret, ttl_seconds)
    return ref


async def claim_service_credential(ref: str) -> str:
    """Consume the credential *ref* names. Raises once it is gone.

    Called exactly once per attempt, at the top of the worker task. A retry
    of the same dispatch necessarily fails here, by design: a credential is
    request-scoped, so a run that outlives its credential must ask a human
    for a new one rather than silently retrying unauthenticated and
    reporting the origin's 401.

    fix(#1277): "gone" and "could not tell" are two answers, and only one is
    about the credential. A store that ANSWERS with no such key is evidence
    the secret was claimed or expired; a store that cannot be reached is
    evidence of nothing but an outage. This used to conflate the two, so a
    Valkey blip surfaced as `credential_expired` and sent the reader to
    re-issue a token that was never the problem.
    """
    if not _REF_PATTERN.match(ref or ""):
        raise CredentialExpiredError(
            "The service credential for this job is no longer available."
        )
    try:
        secret = await get_credential_backend().take(_KEY_PREFIX + ref)
    except CredentialStoreUnavailable:
        raise
    except Exception as exc:  # broad: an unreachable store is not an expiry
        # The exception itself never crosses this boundary: a redis-py error
        # can carry the command it was running, and that command carries the
        # key. Log the class, surface the fixed sentence.
        logger.warning("refresh_credential_claim_failed", error_type=type(exc).__name__)
        raise CredentialStoreUnavailable(
            "The credential store could not be reached, so this job could "
            "not retrieve its token."
        ) from exc
    if secret is None:
        raise CredentialExpiredError(
            "The service credential for this job was already used or has "
            "expired. Start again with a fresh token."
        )
    return secret


async def resolve_worker_credential(
    token: str | None, credential_ref: str | None
) -> str | None:
    """The credential this attempt will fetch with, redeeming a ref if given.

    Called inside the task's handled region and after the attempt check, so
    a single-use credential is only ever consumed for an attempt that is
    actually going to run. A ref that names nothing raises
    :class:`CredentialExpiredError` — deliberately NOT a fall-through to an
    unauthenticated fetch, which would reach the origin, collect a 401, and
    report a protected service as broken.

    The ref wins over a directly-passed token when both are somehow set: the
    door that sends a ref is the door that promised nothing durable, and
    honouring the durable value instead would quietly undo that promise. In
    practice the pair is mutually exclusive by construction (only
    :func:`resolve_dispatch_credential` fills either), so this is the
    tie-break for a rolling deploy, not a routine branch.

    Lives here rather than in either task module because both
    ``reupload_service`` and ``ingest_service`` need it and neither may
    import the other: ``tasks_reupload`` already reaches into
    ``tasks_vector`` at call time, so a top-level edge back would close a
    cycle.
    """
    if credential_ref:
        return await claim_service_credential(credential_ref)
    return token


async def resolve_dispatch_credential(
    token: str | None = None,
    *,
    door: str,
    credential: ServiceCredential | None = None,
) -> tuple[str | None, str | None]:
    """Decide how the caller's credential reaches the worker. Returns ``(token, ref)``.

    The single decision point for the three states in this module's
    docstring, so the three doors cannot answer it three ways:

    - no token at all      -> ``(None, None)``; nothing to protect.
    - store configured     -> ``(None, ref)``; the secret is stashed and
                              only the reference returned, so nothing
                              durable can carry it. Configured-but-
                              unreachable raises
                              :class:`CredentialStoreUnavailable` from the
                              stash, which every caller turns into 503.
    - no store configured  -> ``(token, None)``; the pre-existing durable
                              argument, unchanged.

    Exactly one element of the pair is ever set, which is what lets
    :func:`resolve_worker_credential` treat "both" as impossible.

    The fallback is logged, not silent, so an operator asking "is this
    install actually leasing?" can answer it from logs. The log line
    carries the DOOR, never the token or the reference — a reference is
    harmless after its claim but not before it, and log sinks outlive TTLs.

    feat(#1746) D2: ``credential`` is the structured spelling an in-process
    caller uses (e.g. a scheduler with a resolved stored credential) instead
    of assembling an HTTP request for a door to take apart again. ``token``
    stays the positional form existing callers pass, already converted to
    the wire value by their own door; supplying both is redundant, so the
    structured one wins.

    A structured credential is converted here by ``wire_credential``, which
    for a header-auth service format composes the finished header line
    (plan D9) and for every other one yields the bare token. The in-process
    caller must set ``service_format`` on the credential it builds; without
    it, the credential degrades to its bare-token form, which a WFS origin
    answers with a 401 rather than silently mis-sending.
    """
    if credential is not None:
        token = wire_credential(credential)
    if not token:
        return None, None
    if not credential_store_available():
        logger.info("service_credential_durable_fallback", door=door)
        return token, None
    return None, await stash_service_credential(token)


async def discard_service_credential(ref: str | None) -> None:
    """Best-effort release of a credential whose dispatch never happened.

    The TTL would clear it anyway; this just shortens the window when we
    already know the worker will never come for it. Never raises — it runs on
    a failure path, and a store that is misbehaving must not replace the error
    the caller is already reporting.
    """
    if not ref or not _REF_PATTERN.match(ref):
        return
    try:
        await get_credential_backend().take(_KEY_PREFIX + ref)
    except Exception:  # broad: cleanup must not mask the caller's failure
        logger.warning("refresh_credential_discard_failed")


# The credentials whose dispatch is still genuinely waiting to be picked up.
#
# Two liveness stops, both deferring to the abandonment sweep's own
# definition of "still alive" rather than a second opinion:
#
# 1. the task is still LIVE — 'todo' or 'doing', the abandonment sweep's own
#    liveness test, character for character.
#
#    fix(#1277): 'todo' alone was wrong. Procrastinate flips the status to
#    'doing' BEFORE invoking the task, and the task revalidates its URL for
#    SSRF (unbounded DNS resolution) before it claims — a stalled resolver
#    longer than the TTL expired a credential for a refresh actively being
#    worked on. Including 'doing' is safe for the same reason GETDEL is the
#    right primitive: EXPIRE cannot resurrect, so once the claim removes the
#    key every later renewal is a no-op — this self-terminates at the true
#    claim event, not at a status flip that merely precedes it.
# 2. the run is still active — a terminal run cannot use a credential.
#
# fix(#1277): a third stop, an age bound on the run, was tried and
# CONTRADICTED the sweep. `_ABANDONED_RUN_SQL` deliberately never cancels a
# run whose task is live 'todo' (#1274), so a protected refresh queued
# behind a healthy long ingest kept its run while renewal dropped its
# credential at the cutoff, failing the eventual claim `credential_expired`.
# Two modules disagreeing about the same run's abandonment is worse than
# either answer, so this defers to the sweep instead. A task no worker
# subscribes to sits 'todo' forever (docker-compose.yml, #695) and would be
# renewed forever — but while a claimant-reachable task exists the
# credential IS legitimately in flight (the ADR-002 A7 window, not durable
# storage), and it still dies the instant either the task or the run leaves
# its state, since renewal keys on both.
#
# Correlated on `args->>'job_id'`, the correlation every task in this
# codebase passes and both refresh sweeps already use.
#
# feat(#1676): the run join is LEFT, with a fallback stop, because the
# FIRST-IMPORT door writes no `dataset_refresh_runs` row at all (unlike the
# refresh and re-upload-commit doors). An INNER join would silently drop
# renewal for that door: a protected import queued behind a long ingest
# would expire at the TTL and fail `credential_expired` where today it
# simply waits — a regression no refresh-path test could have caught. The
# fallback stop is `ingest_jobs.status`, asking the same "still being
# worked?" question of the row that exists for a run-less job, with the
# same self-terminating property: EXPIRE cannot resurrect a claimed key.
_RENEWABLE_CREDENTIALS_SQL = text(
    """
    SELECT DISTINCT pj.args->>'credential_ref' AS credential_ref
    FROM catalog.procrastinate_jobs pj
    JOIN catalog.ingest_jobs j ON pj.args->>'job_id' = j.id::text
    LEFT JOIN catalog.dataset_refresh_runs r ON r.ingest_job_id = j.id
    WHERE pj.status IN ('todo', 'doing')
      AND pj.args->>'credential_ref' IS NOT NULL
      AND (
          r.status IN ('pending', 'running')
          OR (r.id IS NULL AND j.status IN ('pending', 'running'))
      )
      AND (
          CAST(:tenant_id AS uuid) IS NULL
          OR j.tenant_id = CAST(:tenant_id AS uuid)
      )
    """
)


async def renew_queued_refresh_credentials(
    session: Any, *, tenant_id: str | None = None
) -> int:
    """Re-arm the TTL of every credential whose task is still queued.

    Returns how many were renewed. Driven by the API's existing stale-job
    sweeper, once per :data:`CREDENTIAL_RENEWAL_INTERVAL_SECONDS`.

    The ``refresh`` in the name is historical: since the import and
    re-upload-commit doors lease too, this covers every leased dispatch (see
    the query's own note on the widened join). Kept because it's the
    spelling structural tests already pin.

    This is what makes a short TTL correct rather than optimistic: the
    credential's lifetime becomes the real queue wait, and shortens itself
    the moment the wait ends.

    fix(#1277): ``tenant_id`` filters the query EXPLICITLY rather than
    leaning on RLS: pre-#998 ``tenant_job_context`` only sets a GUC nothing
    reads, so without this every tenant's iteration renewed every OTHER
    tenant's credentials too — N tenants meant N passes of fleet-wide
    EXPIRE, and a boundary crossed in a loop written specifically to respect
    it. Filters on ``ingest_jobs.tenant_id`` (already in the join, kept
    equal to its parent dataset's by `trg_validate_ingest_job_parent_tenant`)
    rather than joining out to ``datasets``. Single-tenant passes None and
    the predicate folds away.

    Never raises: it runs inside a background loop whose other work must
    not be lost to a credential-store blip, and a missed cycle is
    survivable by construction (the TTL covers two).
    """
    if not credential_store_available():
        return 0
    try:
        rows = await session.execute(
            _RENEWABLE_CREDENTIALS_SQL,
            {"tenant_id": tenant_id},
        )
        refs = [row.credential_ref for row in rows]
    except Exception as exc:  # broad: the sweep's other work must survive this
        # fix(#1277): named, not swallowed. A query rejected because it
        # ran outside a tenant context looks exactly like "nothing to
        # renew" from the return value, so the exception TYPE (logged) is
        # what tells those apart in ops. The query text is deliberately
        # not logged — it's the one string here carrying credential refs.
        logger.warning(
            "refresh_credential_renewal_query_failed",
            error_type=type(exc).__name__,
        )
        return 0

    renewed = 0
    for ref in refs:
        if not ref or not _REF_PATTERN.match(ref):
            continue
        try:
            if await get_credential_backend().renew(
                _KEY_PREFIX + ref, CREDENTIAL_TTL_SECONDS
            ):
                renewed += 1
        except CredentialStoreUnavailable:
            # No store, no renewals — and nothing to report to.
            break
    return renewed


async def renew_queued_credentials_once() -> int:
    """Re-arm queued refresh credentials across the whole deployment.

    fix(#1277): iterates tenants the way the stale-job sweep does — one
    plain call in single-tenant mode, one scoped transaction per tenant
    otherwise, each inside ``tenant_job_context`` so the GUC is set before
    the query runs. Per-tenant recovery is best-effort: one broken tenant
    must not cost the others their renewals.

    fix(#1277): lives here rather than in ``api/main.py`` so the worker
    can host it too (see :func:`renew_credentials_periodically`) — a module
    under ``platform/`` is importable from both processes; the API app
    module is not.

    Returns before touching the database at all when no credential store is
    configured (the default deployment): nothing to renew without a store,
    and the alternative is a registry query plus a session per tenant every
    cycle, forever, to find that out.
    """
    from app.core.db import async_session  # fix(#909): late-bind for tests
    from app.core.db.tenant_session import tenant_job_context
    from app.core.tenancy import is_multi_tenant

    if not credential_store_available():
        return 0

    if not is_multi_tenant():
        async with async_session() as session:
            return await renew_queued_refresh_credentials(session)

    async with async_session() as registry_session:
        tenant_ids = list(
            (
                await registry_session.execute(
                    text("SELECT id FROM catalog.tenants ORDER BY id")
                )
            ).scalars()
        )

    renewed = 0
    for tenant_id in tenant_ids:
        try:
            with tenant_job_context(str(tenant_id)):
                async with async_session() as session:
                    renewed += await renew_queued_refresh_credentials(
                        session, tenant_id=str(tenant_id)
                    )
        except Exception as exc:  # broad: fleet renewal continues tenant-by-tenant
            logger.warning(
                "refresh_credential_renewal_tenant_failed",
                tenant_id=str(tenant_id),
                error_type=type(exc).__name__,
            )
    return renewed


async def renew_credentials_periodically() -> None:
    """Worker-side renewal loop. The second host, and the important one.

    fix(#1277): the API sweeper alone was not enough, because API
    liveness does not bound the lifetime of an already-committed task. The
    API could be down longer than the TTL while the dispatch sat queued
    behind a long ingest, and the worker — healthy the whole time, and the
    only process that could ever claim it — would find the credential gone.

    Two hosts is right because the process whose liveness gates the CLAIM
    is the WORKER, so worker-hosted renewal keeps the handoff alive exactly
    while a claim is still possible; API-hosted renewal covers the
    converse, a worker briefly down with the API up. Both call the same
    tenant-aware helper and ``EXPIRE`` is idempotent, so a cycle where both
    run costs one extra round trip and nothing else.

    If BOTH are down past the TTL the credential expires — the accepted
    floor, not a gap: no claimant existed at any point, so there was never
    a refresh to keep alive. The run fails ``credential_expired``.

    An asyncio loop rather than a Procrastinate periodic task, deliberately:
    the codebase registers no periodic tasks at all, while this worker
    already runs ``update_job_metrics`` exactly this way.
    """
    import asyncio

    while True:
        await asyncio.sleep(CREDENTIAL_RENEWAL_INTERVAL_SECONDS)
        try:
            await renew_queued_credentials_once()
        except Exception:  # broad: the renewal loop must outlive any blip
            logger.warning("refresh_credential_renewal_cycle_failed", exc_info=True)
