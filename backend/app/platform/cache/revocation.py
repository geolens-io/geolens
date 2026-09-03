"""Cluster-global revocation generation (fix(#1778 codex r3/r4)).

The problem this exists for
---------------------------

``RedisCacheProvider``'s in-memory fallback and its authoritative-replay queue
are PROCESS-local, and production runs several Uvicorn workers behind one
socket. That makes every process-local guarantee a per-worker guarantee:

  1. Redis goes down. Worker B validates embed token T and caches a positive.
  2. Worker A revokes T. A writes the denial to ITS fallback and queues it for
     replay in ITS queue. B knows nothing about either.
  3. B keeps serving T.
  4. Redis recovers. Redis still holds the pre-outage positive, because A's
     replay has not run and may never run if A gets no traffic. B reads it.

Step 3 is closed by the ``security=True`` rule on the cache provider: a positive
authorization decision is never served from a process-local store, so during an
outage every validation falls through to the database. Step 4 is what this
module closes. The database is the one thing still up when Redis is not, so the
revocation lands here, and every worker checks it.

Why the counter is read from the DATABASE every time
----------------------------------------------------

fix(#1778 codex r4): the first draft cached this number in Redis and re-read it
from the database only on two triggers -- a missing key, and a circuit-breaker
transition back to closed. Both of those were wrong in the same way, and the
second was wrong twice over:

* A Redis copy can be STALE-LOW. A worker reading generation G while a
  revocation has committed at G+1 finds its cached entry stamped G, sees a
  match, and serves a revoked token. Staleness is not conservative here.
* The transition trigger fired one step too late. Nothing detects a lapsed
  cooldown until some cache method looks, so the FIRST request after recovery
  consumed a signal that had not been raised yet, read the stale Redis
  generation, and accepted a pre-outage positive.

Reading the counter from the database on every validation removes all of it: no
publish to order, no signal to race, no staleness window, and no residual for a
worker that happened to take no traffic during the outage. The cost is one
single-row indexed read per validation, on a code path that already issues at
least one database query on both its cache-hit and cache-miss branches
(``map_contains_dataset``, plus the origin and tenant checks). That is the
trade, and it is a cheap one.

Why the counter is a transactional ROW, not a sequence
------------------------------------------------------

fix(#1778 codex r4): ``nextval`` takes no row lock, which is why the first draft
used it, but it is also non-transactional, and that is fatal rather than
convenient. The advance became visible to every other worker the instant it ran,
while the ``is_active`` flip it stood for stayed invisible until the revoking
transaction committed. A validator landing in that window read the NEW
generation, read the token row as still active, and cached a positive stamped
with the new generation, which then survived the commit and stayed valid until
its TTL.

An ``UPDATE ... RETURNING`` inside the revoking transaction makes the counter
and the ``is_active`` flip become visible in the same instant, to everyone. A
validator reads the generation BEFORE it reads the token row, so:

* generation G (revoke uncommitted) -> the row may still read active, and the
  entry is cached stamped G, which the next reader refuses once the revoke
  commits and the generation is G+1;
* generation G+1 -> the revoke has committed, so the row read that follows sees
  ``is_active`` false and denies.

There is no interleaving that caches a positive stamped with a generation the
committed revocation has already passed.

Concurrent revocations serialize on this one row. They already serialize on the
embed-token rows they are flipping, they are rare, and every revoke path reaches
the two in the same order (token flips first, counter second), so the lock adds
no cycle.
"""

from __future__ import annotations

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.stdlib.get_logger(__name__)

_TABLE = "catalog.security_revocation_generation"

# Matches no stamp any entry can carry, so every comparison against it fails and
# every caller falls through to the database. Returned when the counter cannot
# be read at all, which is the fail-closed direction.
_UNKNOWN_GENERATION = -1


async def bump_revocation_generation(db: AsyncSession) -> int:
    """Advance the generation inside the CALLER's transaction. Returns the new value.

    Deliberately not committed here and deliberately not run on a side session:
    the whole point is that this becomes visible at the same instant as the
    ``is_active`` flip the caller is making, so it must share the caller's
    transaction. A revoke that rolls back leaves the generation where it was,
    which is correct, because the revocation it stood for did not happen either.
    """
    generation = await db.scalar(
        text(
            f"UPDATE {_TABLE} SET generation = generation + 1 "
            "WHERE id IS TRUE RETURNING generation"
        )
    )
    if generation is None:
        # The seeded row is gone. Refusing to invent one is the safe answer: a
        # silent INSERT here would reset the counter and make every stale entry
        # in the fleet compare equal again.
        logger.error("revocation_generation_row_missing", operation="bump")
        return _UNKNOWN_GENERATION
    return int(generation)


async def current_revocation_generation(db: AsyncSession) -> int:
    """The generation a cache entry must carry to still be trusted.

    Read in the caller's transaction, and read BEFORE the caller reads whatever
    row the cached decision is about, so the two cannot disagree about which
    side of a revocation they are on.

    Never raises: a counter that cannot be read resolves to a value no entry
    carries, so every cached positive is refused and re-derived.
    """
    try:
        generation = await db.scalar(
            text(f"SELECT generation FROM {_TABLE} WHERE id IS TRUE")
        )
    except (
        Exception
    ):  # broad: authorization must fail closed rather than propagate a plumbing error
        logger.warning("revocation_generation_read_failed", exc_info=True)
        return _UNKNOWN_GENERATION
    if generation is None:
        logger.error("revocation_generation_row_missing", operation="read")
        return _UNKNOWN_GENERATION
    return int(generation)
