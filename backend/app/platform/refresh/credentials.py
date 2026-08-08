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
  behind for anyone to find later. The TTL is derived from the queue wait it
  has to survive rather than picked — see :data:`CREDENTIAL_TTL_SECONDS`,
  which also documents the one case it deliberately does not cover.
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

Deliberately NOT wired into the existing re-upload commit door, which still
passes its token as a task argument. Doing both would have made a protected
re-upload stop working on every install without Valkey — a live regression
traded for a latent one. See the #1220 PR body for the disposition.
"""

from __future__ import annotations

import re
import secrets
from typing import Protocol

import structlog

logger = structlog.get_logger(__name__)

# fix(#1277 review): the TTL is DERIVED from the wait it has to survive, not
# picked. The first version used a flat 900s on the reasoning that a queue is
# usually short — but `worker_concurrency` defaults to 1 and refreshes share
# the `ingest` queue with every other ingest, so a refresh queued behind one
# large import waits for that import, and Procrastinate offers no pickup
# guarantee to bound it. Fifteen minutes is well inside the range a single
# large ingest occupies, which made `credential_expired` reachable on a
# perfectly healthy instance.
#
# The supported bound on the job at the head of a concurrency-1 queue is
# JOB_TIMEOUT_SECONDS: past that the stale sweep fails it and the queue moves.
# So one blocking job plus a margin is the wait this has to outlive.
#
# Mirrored rather than imported, because `platform/jobs/router.py` is an API
# edge and importing it executes route registration as a side effect — the
# same reason `ABANDONED_RUN_CUTOFF_SECONDS` mirrors it one module over.
# `test_service_refresh_1220` pins the two values together so drift fails a
# test rather than silently shortening the window again.
_QUEUE_HEAD_JOB_TIMEOUT_SECONDS = 3600

# Slack over the bound above, covering the sweep's own cycle time plus the gap
# between a queue freeing up and this task being claimed.
_CREDENTIAL_TTL_MARGIN_SECONDS = 600

# Never shorter than the original 15 minutes, whatever the timeout is tuned
# to. An operator who lowers JOB_TIMEOUT_SECONDS is tightening a liveness
# policy, not asking for credentials that expire during a normal dispatch.
_CREDENTIAL_TTL_FLOOR_SECONDS = 900

# How long a stashed credential survives unclaimed. Short enough that a
# dispatch nobody ever ran does not leave a usable secret sitting around, long
# enough that an ordinary queue never eats it.
#
# ACCEPTED RESIDUAL: a queue several large ingests deep can still outlast
# this, and no TTL fixes that — the whole point of A7 is that the credential
# is single-use and short-lived, and stretching it toward "long enough for any
# queue" is stretching it toward "durable", which is the property this
# mechanism exists to avoid. When it does happen the outcome is clean and
# actionable rather than mysterious: the run fails `credential_expired` and
# its message already says to start again with a fresh token.
CREDENTIAL_TTL_SECONDS = max(
    _CREDENTIAL_TTL_FLOOR_SECONDS,
    _QUEUE_HEAD_JOB_TIMEOUT_SECONDS + _CREDENTIAL_TTL_MARGIN_SECONDS,
)

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
    503 naming the missing configuration rather than a refresh that dispatches
    and then fails in a worker for reasons nothing surfaces.
    """


class CredentialExpiredError(RuntimeError):
    """The reference names nothing: already claimed, or past its TTL.

    Both cases are the same fact from the worker's side — there is no
    credential to fetch — and both are permanent for this attempt, because a
    single-use secret is gone the moment it is read. The worker turns this
    into the ``credential_expired`` run error code so the history row says
    "supply a token and try again" rather than blaming the origin.
    """


class CredentialBackend(Protocol):
    """The two operations this module needs from a shared store."""

    async def put(self, key: str, value: str, ttl_seconds: int) -> None:
        """Store *value* under *key*, expiring after *ttl_seconds*."""
        ...

    async def take(self, key: str) -> str | None:
        """Atomically read and delete *key*. None when it does not exist."""
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
                "The credential store could not be reached, so this refresh "
                "cannot be started with a token."
            ) from exc
        if not stored:
            raise CredentialStoreUnavailable(
                "Could not stash the service credential for this refresh."
            )

    async def take(self, key: str) -> str | None:
        try:
            return await self._client.getdel(key)
        except Exception as exc:  # broad: any transport failure means "cannot tell"
            logger.warning(
                "refresh_credential_store_read_failed", error_type=type(exc).__name__
            )
            raise CredentialStoreUnavailable(
                "The credential store could not be reached, so this refresh "
                "could not retrieve its token."
            ) from exc


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
            "Refreshing a protected service requires a shared credential "
            "store. Set REDIS_URL to a Valkey/Redis instance reachable by "
            "both the API and the worker."
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
            "The service credential for this refresh is no longer available."
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
            "The credential store could not be reached, so this refresh could "
            "not retrieve its token."
        ) from exc
    if secret is None:
        raise CredentialExpiredError(
            "The service credential for this refresh was already used or has "
            "expired. Start the refresh again with a fresh token."
        )
    return secret


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
