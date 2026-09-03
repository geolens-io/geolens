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
_TABLE_NAME = "security_revocation_generation"

# Returned when the counter cannot be read at all. fix(#1778 codex r5): a
# sentinel is NOT a generation, and treating it as one was a hole. Two entries
# both stamped with it compared EQUAL, so a positive cached while the counter
# was unreadable stayed trusted through a later revocation whose denial could
# not reach shared Redis. Callers must ask `is_usable_generation` and refuse to
# cache, or to trust, anything stamped with an unusable value.
UNKNOWN_GENERATION = -1


class RevocationGenerationError(RuntimeError):
    """The revocation counter could not be advanced.

    fix(#1778 codex r5): a revocation whose generation cannot advance is a
    revocation other workers will never hear about, so it must not quietly
    proceed. Raising rolls back the caller's transaction, which takes the
    ``is_active`` flip with it: the operator sees a failed revoke and retries,
    rather than a successful one that half the fleet ignores.
    """


def is_usable_generation(generation: int) -> bool:
    """Whether *generation* may be stamped on, or compared against, an entry."""
    return generation != UNKNOWN_GENERATION


# fix(#1778 codex r6 P2): a random 62-bit value, not a wall-clock second. The
# epoch seed used through round 5 could collide with itself: deleting the row
# and healing it again inside the same wall-clock second reproduces the exact
# same seed, and a Redis positive stamped with the pre-delete value would then
# compare equal to it and be trusted after "recovery". It also degrades under
# sustained load rather than only at that one boundary: a fleet revoking fast
# enough can walk the counter's integer value past the current epoch-seconds
# count, and a later re-seed then lands BEHIND the counter it is replacing
# instead of ahead of it. Monotonic wall-clock time was never the guarantee
# this needed. A value drawn uniformly from [0, 2**62) makes a collision with
# ANY earlier stamp, from any prior seed or any counted revocation, a
# ~2**-62 event, independent of timing. 2**62 rather than the full 63-bit
# signed range so the floor() and the cast can never round the boundary into
# a negative bigint.
_SEED_EXPR = "(floor(random() * 4611686018427387904))::bigint"


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
        # The row is gone, so this revocation cannot be announced to the rest of
        # the fleet. fix(#1778 codex r5): raise rather than return a sentinel.
        # Returning one let the revoke commit while every other worker kept
        # honouring its cached positives until they expired.
        logger.error("revocation_generation_row_missing", operation="bump")
        raise RevocationGenerationError(
            "The revocation generation counter row is missing, so this "
            "revocation cannot be made visible to other workers. Refusing to "
            "complete it."
        )
    return int(generation)


async def current_revocation_generation(db: AsyncSession) -> int:
    """The generation a cache entry must carry to still be trusted.

    Read in the caller's transaction, and read BEFORE the caller reads whatever
    row the cached decision is about, so the two cannot disagree about which
    side of a revocation they are on.

    Never raises: a counter that cannot be read resolves to UNKNOWN_GENERATION.
    That is NOT a generation, and a caller must neither stamp it on an entry nor
    compare two entries by it; ask ``is_usable_generation`` and skip the cache
    entirely. fix(#1778 codex r5): treating the sentinel as an ordinary value
    made two entries stamped with it compare EQUAL, which is the opposite of
    fail-closed.
    """
    try:
        generation = await db.scalar(
            text(f"SELECT generation FROM {_TABLE} WHERE id IS TRUE")
        )
        if generation is None:
            # fix(#1778 codex r6 P1): the heal must NOT run on `db`. Every
            # production caller of this function is a read endpoint on
            # get_db() (core/dependencies.py), whose session is committed on
            # NOTHING -- it either rolls back on an exception or is simply
            # closed at the end of a successful request. Round 5's heal ran
            # the INSERT on that same session, so it "worked" for the rest of
            # THIS request and then vanished the instant the session closed:
            # the next validation found the row missing again and re-healed
            # it, over and over, while every revoke kept raising
            # RevocationGenerationError until an operator repaired the table
            # by hand. Healing on its own connection, committed independently
            # of whatever the caller's session does with its own transaction,
            # is the only way the fix outlives the request that triggered it.
            logger.error("revocation_generation_row_missing", operation="read")
            healed_generation = await _reseed_missing_generation_row()
            logger.warning(
                "revocation_generation_row_healed",
                generation=healed_generation,
            )
            # Re-read through the CALLER's session rather than trusting the
            # value the heal returned directly. The heal committed on a
            # separate connection; this SELECT is a fresh statement in `db`'s
            # transaction, and under READ COMMITTED (the default, and nothing
            # in this request path raises the isolation level) a fresh
            # statement always sees a just-committed row from elsewhere. That
            # keeps this function to one source of truth -- what `db` itself
            # can see -- rather than a value trusted from a connection this
            # session never touches.
            generation = await db.scalar(
                text(f"SELECT generation FROM {_TABLE} WHERE id IS TRUE")
            )
    except (
        Exception
    ):  # broad: authorization must fail closed rather than propagate a plumbing error
        logger.warning("revocation_generation_read_failed", exc_info=True)
        return UNKNOWN_GENERATION
    if generation is None:
        return UNKNOWN_GENERATION
    return int(generation)


async def _reseed_missing_generation_row() -> int:
    """Recreate the deleted singleton counter row on its own connection.

    fix(#1778 codex r6 P1): committed independently of the caller, and NEVER
    on the caller's `AsyncSession` -- see the call site in
    ``current_revocation_generation`` for why that failed to persist. Late
    imports ``app.core.db.engine`` the same way ``get_db()`` late-imports
    ``async_session``: a module-scope import would snapshot the engine
    ``client``/test fixtures rebind before their override takes effect,
    silently healing against the wrong database in tests.
    """
    from app.core.db import engine  # noqa: PLC0415

    async with engine.begin() as conn:
        generation = await conn.scalar(
            text(
                f"INSERT INTO {_TABLE} (id, generation) "
                f"VALUES (TRUE, {_SEED_EXPR}) "
                "ON CONFLICT (id) DO UPDATE SET generation = "
                f"{_TABLE_NAME}.generation "
                "RETURNING generation"
            )
        )
    return int(generation)
