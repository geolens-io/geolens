"""One-time handoff of a service credential from the API to the worker.

feat(#1220) / ADR-002 Amendment A7. A refresh of a protected service needs a
token in the worker, and the worker is a different process. Every existing way
of getting one there is durable: Procrastinate task arguments are rows in
``catalog.procrastinate_jobs``, ``ingest_jobs.user_metadata`` is a column, and
a failed job keeps both until the retention purge. ADR-002 invariant 4 says
the credential never lands in a committed row, so the handoff needs a channel
that is neither PostgreSQL nor the request.

This module is that channel: the API writes the secret once under an
unguessable reference with a short TTL, passes only the REFERENCE through the
task arguments, and the worker consumes it with an atomic read-and-delete. The
three properties that matter, and where each comes from:

- **Single use.** ``GETDEL`` reads and deletes in one server-side operation,
  so two claimants cannot both succeed. A ``GET`` followed by a ``DELETE``
  would leave a window; that window is the whole point of using ``GETDEL``.
- **Bounded lifetime.** ``SET ... EX`` expires the key whether or not anyone
  claims it, so a dispatch that never reaches a worker leaves no credential
  behind for anyone to find later. The TTL is short and stays short: rather
  than sizing it for the worst queue anybody might have,
  :func:`renew_queued_refresh_credentials` re-arms it while the dispatch is
  provably still waiting, so the lifetime IS the queue wait rather than an
  estimate of it. See :data:`CREDENTIAL_TTL_SECONDS`.
- **Nothing durable.** The reference is a random string that means nothing
  once claimed or expired. It is the only thing that reaches a task argument
  or a log line.

### Why this needs a real shared cache, and what happens without one

``REDIS_URL`` is unset by default — the compose ``valkey`` service is opt-in
behind the ``cloud-dev`` profile — and the ordinary cache provider degrades to
an in-memory dict when it is missing. That degradation is right for a cache
and wrong for this: the API and the worker are separate processes, so an
in-memory write would be invisible to the claimant and every credentialed
refresh would fail as ``credential_expired`` with nothing in the logs saying
why. So this module talks to Valkey directly rather than through
``get_cache()``, and :func:`credential_store_available` reports honestly when
there is no store. The refresh endpoint refuses a token-bearing request up
front in that case, which is a clear error at the door instead of a confusing
failure an hour later in a worker.

### Three doors, one mechanism, three states

#1220 wired the refresh door only. The first-import and re-upload-commit
doors kept passing their token as a task argument, because refusing a
credentialed request without Valkey would have stopped protected imports
working on every stock install — a live regression traded for a latent one.

feat(#1676) closes the gap without paying that regression, by keying the
decision on what the install HAS rather than on which door the request came
through:

- **state 1, store configured and reachable** — stash, dispatch the
  reference, claim once in the worker. Nothing durable, at every door.
- **state 2, store configured but the stash fails** — 503
  ``credential_store_unavailable``, identical at every door. An operator who
  opted into a store is told it is broken rather than silently downgraded to
  the durable argument they thought they had stopped using.
- **state 3, no store configured at all** — the token rides in the task
  argument, as it always has at the two pre-existing doors. The refresh door
  refuses here instead, and keeps refusing: token-bearing refresh has never
  worked without a store, so nothing regresses by leaving it that way.

State 3 is the one asymmetry and it is deliberate. The alternative — one
uniform refusal — reads tidier and breaks protected import on the default
install, which is the trade #1220 already declined once.

:func:`resolve_dispatch_credential` decides all three for the two doors that
can reach state 3, so neither of them can drift from the other or from this
text. The refresh door does not call it: it answers state 3 with an explicit
refusal in its own handler, before it writes anything, and then reaches
states 1 and 2 through :func:`stash_service_credential` — which is the only
other call this helper makes. Two spellings of the same two calls, because
the third state genuinely differs there.
"""

from __future__ import annotations

import re
import secrets
from typing import Any, Protocol

import structlog
from sqlalchemy import text

logger = structlog.get_logger(__name__)

# fix(#1277 review round 2): the TTL is bounded by RENEWAL, not by a constant.
#
# Round 1 derived it from JOB_TIMEOUT_SECONDS on the reasoning that the job at
# the head of a concurrency-1 queue is bounded by the stale sweep. That premise
# was wrong: `maintain_ingest_job_heartbeat` refreshes `heartbeat_at` every 30
# seconds and the sweep only fails rows whose heartbeat has gone stale, so
# JOB_TIMEOUT_SECONDS bounds a DEAD worker's lease, not a healthy long import.
# A legitimate multi-hour ingest at the queue head outlives any constant, and
# raising the constant until it does not is walking toward durable storage —
# which is the one thing A7 exists to prevent.
#
# So the lifetime tracks the real queue wait instead. The TTL stays short, and
# `renew_queued_refresh_credentials` re-arms it every sweep cycle for exactly
# those credentials whose dispatch is still waiting to be picked up. The bound
# is then the actual wait by construction, and renewal stops on its own at
# two points, both of them the abandonment sweep's own definition of a run
# that is still alive — see that function.
#
# The arithmetic, against the real interval: renewal runs once per
# CREDENTIAL_RENEWAL_INTERVAL_SECONDS (300s), so the TTL must survive at least
# two cycles or a single skipped pass — a slow sweep, a GC pause, a restart
# between cycles — expires a credential whose task is still queued. Two cycles
# is 600s; the remaining 300s is margin for scheduling jitter, giving 900.
#
# If the API dies, renewal stops and the credential expires within one TTL.
# That is the correct outcome rather than a gap: nothing is left to dispatch
# the work, and the run fails `credential_expired`, whose message already says
# to start again with a fresh token.
CREDENTIAL_RENEWAL_INTERVAL_SECONDS = 300

CREDENTIAL_TTL_SECONDS = 3 * CREDENTIAL_RENEWAL_INTERVAL_SECONDS

_KEY_PREFIX = "geolens:refresh-cred:"

# The reference is generated by :func:`stash_service_credential` and travels
# through task arguments, so it is ours end to end — but it is also the only
# thing between a task argument and a key lookup, and task arguments are rows
# a future migration or backfill could touch. Constraining the shape means a
# malformed reference can never be composed into a lookup for some other key.
_REF_PATTERN = re.compile(r"\A[A-Za-z0-9_-]{22,64}\Z")


class CredentialStoreUnavailable(RuntimeError):
    """No shared credential store is configured.

    Raised at the API door, before anything is written, so the caller gets a
    503 naming the missing configuration rather than a dispatch that fails in
    a worker an hour later for reasons nothing surfaces.
    """


class CredentialExpiredError(RuntimeError):
    """The reference names nothing: already claimed, or past its TTL.

    Both cases are the same fact from the worker's side — there is no
    credential to fetch — and both are permanent for this attempt, because a
    single-use secret is gone the moment it is read. The refresh worker turns
    this into the ``credential_expired`` run error code so the history row
    says "supply a token and try again" rather than blaming the origin; the
    import worker has no run row and carries the same sentence as its
    ``error_message``.
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

    fix(#1277 review): both operations translate transport failures into
    ``CredentialStoreUnavailable`` at this boundary, rather than letting
    redis-py's own exceptions escape. Untranslated they broke both callers in
    different ways — a connection error during stash left the endpoint
    returning 500 instead of its 503, and one during claim was swallowed by
    the caller's broad handler and reported as ``credential_expired``, which
    blames a spent token for what is actually an outage. Reaching the store is
    an availability question and answering it is the store's job; only the
    store SAYING the key is absent is evidence about the credential.

    The exception is never rendered into the message either: redis-py bakes
    the command it was running into its error text, and that command carries
    the key.
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

        Failures are swallowed rather than raised. A missed renewal costs at
        most one cycle — the TTL is sized to survive two — and this runs in a
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

    Called exactly once per attempt, at the top of the worker task. A retry of
    the same dispatch necessarily fails here, which is the intended shape:
    ADR-002 Decision 3 says a credential is request-scoped, so a run that
    outlives its credential must ask a human for a new one rather than
    silently retrying unauthenticated and reporting the origin's 401.

    fix(#1277 review): "gone" and "could not tell" are two answers, and only
    one of them is about the credential. A store that ANSWERS and reports no
    such key is evidence the secret was claimed or expired; a store that
    cannot be reached is evidence of nothing except an outage. This fallback
    used to report the second as the first, so a Valkey blip surfaced as
    `credential_expired` and sent the reader to re-issue a token that was
    never the problem.
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

    feat(#1220), shared with the import door by feat(#1676). Called inside the
    task's handled region and after the attempt check, so a single-use
    credential is only ever consumed for an attempt that is actually going to
    run. A ref that names nothing raises :class:`CredentialExpiredError` —
    deliberately NOT a fall-through to an unauthenticated fetch, which would
    reach the origin, collect a 401, and report a protected service as broken.

    The ref wins over a directly-passed token when both are somehow set: the
    door that sends a ref is the door that promised nothing durable, and
    honouring the durable value instead would quietly undo that promise. In
    practice the pair is mutually exclusive by construction — see
    :func:`resolve_dispatch_credential`, which is the only thing that fills
    either — so this is the tie-break for a rolling deploy, not a routine
    branch.

    Lives here rather than in either task module because both
    ``reupload_service`` and ``ingest_service`` need it and neither may import
    the other: ``tasks_reupload`` already reaches into ``tasks_vector`` at
    call time, so a top-level edge back would close a cycle.
    """
    if credential_ref:
        return await claim_service_credential(credential_ref)
    return token


async def resolve_dispatch_credential(
    token: str | None, *, door: str
) -> tuple[str | None, str | None]:
    """Decide how *token* reaches the worker. Returns ``(token, ref)``.

    feat(#1676). The single decision point for the three states in this
    module's docstring, so the three doors cannot answer it three ways:

    - no token at all           -> ``(None, None)``; nothing to protect.
    - store configured          -> ``(None, ref)``; the secret is stashed and
                                   only the reference is returned, so nothing
                                   durable can carry it. A store that is
                                   configured but unreachable raises
                                   :class:`CredentialStoreUnavailable` from
                                   the stash, which every caller turns into
                                   the same 503.
    - no store configured       -> ``(token, None)``; the pre-existing durable
                                   argument, unchanged.

    Exactly one element of the pair is ever set, which is what lets
    :func:`resolve_worker_credential` treat "both" as an impossibility rather
    than a case.

    The fallback is logged rather than silent. It is the one branch where the
    stored shape of a request differs from what the UI copy leads with, and an
    operator asking "is this install actually leasing?" should be able to
    answer it from logs instead of from settings archaeology. The log line
    carries the DOOR, never the token and never the reference — a reference is
    harmless after its claim but not before it, and log sinks outlive TTLs.
    """
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
# TWO stops, and both are the abandonment sweep's own definition of "still
# alive" rather than a second opinion about it. Round 5 made the RUN side
# defer to the sweep; round 7 finished the job on the TASK side, which had
# been narrower than the sweep's all along:
#
# 1. the task is still LIVE — 'todo' or 'doing', which is the abandonment
#    sweep's own liveness test, character for character.
#
#    fix(#1277 review round 7): this said 'todo' alone, on the belief that a
#    worker moving the row to 'doing' and GETDELing the key were the same
#    event. They are not. Procrastinate flips the status BEFORE invoking the
#    task, and the task revalidates its URL for SSRF — an unbounded DNS
#    resolution — before it claims. A stalled resolver longer than the TTL
#    therefore expired a credential belonging to a refresh that was actively
#    being worked on.
#
#    'doing' is safe to include for the reason that made GETDEL the right
#    primitive in the first place: EXPIRE cannot resurrect. Once the claim has
#    removed the key, every later renewal is a no-op on a key that does not
#    exist, so this self-terminates at the true claim event rather than at a
#    status flip that merely precedes it. No new constant, no new coordination.
# 2. the run is still active — a terminal run cannot use a credential, so
#    there is nothing left to keep alive.
#
# fix(#1277 review round 5): there was a third, an age bound on the run, and
# it CONTRADICTED the sweep. `_ABANDONED_RUN_SQL` deliberately never cancels a
# run whose task is live 'todo' (#1274), so a protected refresh queued behind
# a healthy long ingest kept its run — while renewal dropped its credential at
# the cutoff and the eventual claim failed `credential_expired`. Two modules
# disagreeing about whether the same run is abandoned is worse than either
# answer; the sweep owns that question, so this defers to it.
#
# What the age bound was guarding is answered here instead of by a constant. A
# task no worker subscribes to sits 'todo' forever (documented on the `worker`
# service in docker-compose.yml, fix #695) and would be renewed forever — but
# while a claimant-reachable task exists the credential is legitimately in
# flight, which IS the A7 window rather than durable storage. In that
# misconfiguration the whole run, job and task are stuck and visible as queue
# depth; the credential is the least of what is wrong, and it still dies the
# instant either the task or the run leaves its state, because renewal keys on
# both. Any constant here would just reproduce the finding it was meant to
# prevent one level up: "healthy but longer than the number" is unbounded by
# construction, which is exactly what rounds 2 and 5 already established.
#
# Correlated on `args->>'job_id'`, the correlation every task in this codebase
# passes and the one both refresh sweeps already use.
#
# feat(#1676): the run join is a LEFT join, and the run-liveness stop has a
# fallback. The INNER join was correct while only the refresh door leased,
# because that door writes a `dataset_refresh_runs` row on the way in — and so
# does the re-upload commit door, which is why that one inherits renewal for
# free. The FIRST-IMPORT door writes no run at all. Left as an inner join it
# would have matched nothing for an import, silently dropping renewal for the
# one door with no run row: a protected import queued behind a long ingest
# would have expired at the TTL and failed `credential_expired` where today it
# simply waits. That is a regression the lease itself would have introduced,
# and no test of the refresh path could have seen it.
#
# The fallback stop is `ingest_jobs.status`, which is the same question the
# run's status answers on the other branch — is this dispatch still going to
# be worked? — asked of the row that exists for a run-less job. It keeps the
# self-terminating property intact for the same reason the run branch has it:
# `EXPIRE` cannot resurrect, so once the worker's GETDEL has removed the key
# every later renewal is a no-op regardless of what any status column says.
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

    feat(#1676): the ``refresh`` in the name is historical. Since the import
    and re-upload-commit doors lease too, this covers every leased dispatch —
    see the query's own note on why a run-less import needed the join
    widened. The name is kept because it is the spelling
    ``test_service_refresh_1220`` and the lifespan structural assertions
    already pin, and renaming it would churn a dozen call sites to say the
    same thing the docstring says.

    This is what makes a short TTL correct rather than optimistic: the
    credential's lifetime becomes the real queue wait instead of a number
    somebody guessed, and it shortens itself the moment the wait ends.

    fix(#1277 review round 4): ``tenant_id`` filters the query EXPLICITLY
    rather than leaning on RLS to do it. Pre-#998 ``tenant_job_context`` only
    sets a GUC that nothing reads, so without this every tenant's iteration
    renewed every OTHER tenant's credentials too — N tenants meant N passes of
    fleet-wide EXPIRE, an inflated count, and a boundary crossed in a loop
    written specifically to respect it. Filtering on ``ingest_jobs.tenant_id``
    rather than joining out to ``datasets``: it is already in the join, it
    carries ``trg_stamp_current_tenant_on_insert`` like ``datasets`` does, and
    ``trg_validate_ingest_job_parent_tenant`` keeps it equal to its parent
    dataset's, so the two cannot disagree. Single-tenant passes None and the
    predicate folds away.

    Never raises. It runs inside a background loop whose other work must not
    be lost to a credential-store blip, and a missed cycle is survivable by
    construction — the TTL covers two.
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
        # fix(#1277 review round 3): named, not swallowed. The never-raises
        # contract is what lets the sweeper call this without a guard of its
        # own, and it is also what would hide a misconfiguration forever —
        # a query rejected because it ran outside a tenant context looks
        # exactly like "nothing to renew" from the return value. The
        # exception TYPE is enough to tell those apart in ops; the query text
        # is deliberately not logged, because it is the one string here that
        # carries credential references.
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

    fix(#1277 review round 3): iterates tenants the way the stale-job sweep
    does — one plain call in single-tenant mode, one scoped transaction per
    tenant otherwise, each inside ``tenant_job_context`` so the GUC is set
    before the query runs. Per-tenant recovery is best-effort: one broken
    tenant must not cost the others their renewals.

    fix(#1277 review round 4): lives here rather than in ``api/main.py`` so the
    worker can host it too — see :func:`renew_credentials_periodically`. A
    module under ``platform/`` is importable from both processes; the API app
    module is not.

    Returns before touching the database at all when no credential store is
    configured, which is the default deployment. There is nothing to renew
    without a store, and the alternative is a registry query plus a session
    per tenant every cycle, forever, to find that out.
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

    fix(#1277 review round 4): the API sweeper alone was not enough, because
    API liveness does not bound the lifetime of an already-committed task. The
    API could be down for longer than the TTL while the dispatch sat queued
    behind a long ingest, and the worker — healthy the whole time, and the only
    process that could ever claim it — would find the credential gone.

    The coupling that makes two hosts the right answer: the process whose
    liveness gates the CLAIM is the WORKER, so worker-hosted renewal keeps the
    handoff alive exactly while a claim is still possible. API-hosted renewal
    covers the converse, a worker briefly down with the API up. Both call the
    same tenant-aware helper and ``EXPIRE`` is idempotent, so a cycle where
    both run costs one extra round trip and nothing else.

    If BOTH are down past the TTL the credential expires, and that is the
    accepted floor rather than a gap: no claimant existed at any point during
    the credential's life, so there was never a refresh to keep alive. The run
    fails ``credential_expired``, whose message already says to retry with a
    fresh token.

    An asyncio loop rather than a Procrastinate periodic task, deliberately:
    the codebase registers no periodic tasks at all (``procrastinate_periodic_
    defers`` is stock schema, not evidence of use), while this worker already
    runs ``update_job_metrics`` exactly this way. Matching the pattern that is
    here beats introducing the machinery that is not.
    """
    import asyncio

    while True:
        await asyncio.sleep(CREDENTIAL_RENEWAL_INTERVAL_SECONDS)
        try:
            await renew_queued_credentials_once()
        except Exception:  # broad: the renewal loop must outlive any blip
            logger.warning("refresh_credential_renewal_cycle_failed", exc_info=True)
