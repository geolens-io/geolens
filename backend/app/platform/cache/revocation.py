"""Cluster-global revocation generation (fix(#1778 codex r3)).

The problem this exists for
---------------------------

``RedisCacheProvider``'s in-memory fallback and its authoritative-replay queue
are PROCESS-local, and production runs several Uvicorn workers behind one
socket. That makes every process-local guarantee a per-worker guarantee:

  1. Redis goes down. Worker B validates embed token T, and (before the
     ``security`` rule below) caches a positive in its own fallback.
  2. Worker A revokes T. A writes the denial to ITS fallback and queues it for
     replay in ITS queue. B knows nothing about either.
  3. B keeps serving T from its fallback.
  4. Redis recovers. Redis still holds the pre-outage positive for T, because
     A's replay has not run yet and may never run if A gets no traffic. B reads
     Redis and gets the positive.

Step 3 is closed by the ``security=True`` rule on the cache provider: a positive
authorization decision is never served from a process-local store, so during an
outage every validation falls through to the database. Step 4 is what this
module closes. The database is the one thing still up when Redis is not, so the
revocation lands here, and every worker checks it.

How it works
------------

* A revoke calls :func:`bump_revocation_generation`, which is one ``nextval``
  on ``catalog.security_revocation_generation``.
* A positive validation-cache entry is stamped with the generation it was minted
  under.
* On a cache hit the validator compares the stamp with the current generation
  and treats a stale stamp as a miss, re-reading the database.

The current generation is read from Redis, because reading it is on the hot
path and a database round-trip per cache hit would undo the point of the cache.
It is re-read from the DATABASE, and the Redis key rewritten, in exactly the two
cases where the Redis copy cannot be trusted:

* the Redis key is missing (eviction, flush, a fresh Redis), and
* the worker's circuit breaker has just transitioned back to closed, which means
  this worker was cut off from Redis and cannot know what happened while it was.
  ``RedisCacheProvider.consume_recovery_signal()`` reports that transition once.

Residual, stated rather than papered over
-----------------------------------------

A worker that served no requests at all during the outage never opened its
circuit, so it never sees a recovery signal, and its Redis reads succeeded
throughout. If Redis itself still holds a pre-revocation positive for a token,
that worker keeps trusting it until the entry's own TTL expires. That TTL is
``EMBED_TOKEN_POSITIVE_TTL_SECONDS`` (300 seconds, five minutes) and it is the
bound on this residual. It is not zero and this module does not claim it is.

Closing it completely would need either a push channel every worker subscribes
to (Redis pub/sub, which is exactly the component that was down), or a database
read of the generation on every cache hit, which is the cache round-trip the
cache exists to avoid. Five minutes of exposure for a token revoked during a
Redis outage, in a multi-worker deployment, on a worker that took no traffic
during that outage, is the trade being made.
"""

from __future__ import annotations

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.cache.provider import get_cache

logger = structlog.stdlib.get_logger(__name__)

# Not tenant-scoped on purpose: the whole value of the generation is that every
# worker, and in hosted mode every tenant's request path, agrees on one number.
# A per-tenant counter would let a revoke in one tenant leave another tenant's
# stale positives standing, which is the defect this closes rather than a
# refinement of it.
REVOCATION_GENERATION_CACHE_KEY = "security:revocation_generation"

# Long, because the value is rewritten on every bump and on every recovery, and
# a stale read here is only ever "an entry is re-validated against the database
# once more than it needed to be".
_GENERATION_CACHE_TTL = 3600

_SEQUENCE = "catalog.security_revocation_generation"


async def bump_revocation_generation(db: AsyncSession) -> int:
    """Advance the generation and publish it. Returns the new value.

    ``nextval`` is non-transactional, so this survives a rollback of the
    surrounding revoke. That is deliberate: a generation that ran ahead of the
    revocations costs one extra database re-validation per cached entry, while
    one that lagged would leave a revoked capability being served.
    """
    generation = int(await db.scalar(text(f"SELECT nextval('{_SEQUENCE}')")))
    await _publish(generation)
    return generation


async def current_revocation_generation(db: AsyncSession) -> int:
    """The generation a cache entry must carry to still be trusted.

    Reads Redis, except in the two cases where the Redis copy cannot be trusted:
    the key is missing, or this worker has just come back from an outage. Both
    fall through to the database and rewrite the Redis key.

    Never raises. A cache backend that cannot answer resolves to the database;
    a database that cannot answer resolves to ``0``, which matches no stamp any
    entry carries and therefore fails every comparison -- a cache miss for every
    caller, which is the fail-closed direction.
    """
    cache = get_cache()

    recovered = False
    consume = getattr(cache, "consume_recovery_signal", None)
    if consume is not None:
        recovered = consume()

    if not recovered:
        try:
            cached = await cache.get(REVOCATION_GENERATION_CACHE_KEY)
        except Exception:  # broad: a cache backend failure must fall through to the database, never break authorization
            cached = None
        if isinstance(cached, int):
            return cached

    return await _refresh_from_database(db, recovered=recovered)


async def _refresh_from_database(db: AsyncSession, *, recovered: bool) -> int:
    try:
        # last_value, not nextval: reading the generation must not advance it.
        # A sequence that has never been advanced reports its START WITH value,
        # which is the stamp every entry minted before the first revoke carries.
        generation = int(await db.scalar(text(f"SELECT last_value FROM {_SEQUENCE}")))
    except Exception:  # broad: authorization must fail closed rather than propagate a cache-plumbing error
        logger.warning(
            "revocation_generation_read_failed",
            recovered=recovered,
            exc_info=True,
        )
        return 0
    if recovered:
        logger.info(
            "revocation_generation_refreshed_after_outage", generation=generation
        )
    await _publish(generation)
    return generation


async def _publish(generation: int) -> None:
    """Best-effort write of the generation to the shared cache.

    ``set_authoritative`` rather than ``set``: this value overrides whatever
    Redis is holding, and it has to survive an outage the same way a revocation
    denial does. If it does not land, the next reader finds the key missing and
    goes to the database, which is the correct fallback.
    """
    try:
        cache = get_cache()
        await cache.set_authoritative(
            REVOCATION_GENERATION_CACHE_KEY, generation, ttl=_GENERATION_CACHE_TTL
        )
    except Exception:  # broad: publishing the generation is an optimization; the database remains the source of truth
        logger.warning("revocation_generation_publish_failed", exc_info=True)
