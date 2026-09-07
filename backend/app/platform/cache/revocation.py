"""Cluster-global revocation generation (fix(#1778)).

``RedisCacheProvider``'s fallback and replay queue are PROCESS-local, so a
revocation made by one worker during a Redis outage is invisible to other
workers until replay runs -- which may never happen for a worker that gets
no traffic. Positive reads already fail closed during the outage itself
(``security=True``); this module closes the OTHER gap: after Redis
recovers, another worker still serving a positive that predates the revoke.

The counter is read from the database on every validation, not cached, and
is a transactional ROW rather than a sequence:

* A Redis-cached copy of the counter can be STALE-LOW -- a worker reads
  generation G while a revocation has committed at G+1, and a stamped-G
  entry compares equal and is served as valid. Reading from the DB every
  time removes the staleness window (the cost is one indexed row read on a
  path that already queries the DB on both its cache-hit and -miss branches).
* ``nextval`` is non-transactional: the counter would advance the instant it
  ran, before the ``is_active`` flip it represents commits, letting a
  validator in that window cache a positive under the NEW generation that
  then survives the commit. An ``UPDATE ... RETURNING`` inside the revoking
  transaction makes the counter and the flip visible atomically, and a
  validator reads the generation BEFORE the token row -- so no interleaving
  can cache a positive stamped with a generation the commit has already
  passed.

Concurrent revocations serialize on this one row; they already serialize on
the token rows they flip, are rare, and every path touches the two in the
same order, so the lock adds no cycle.
"""

from __future__ import annotations

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.stdlib.get_logger(__name__)

_TABLE = "catalog.security_revocation_generation"
_TABLE_NAME = "security_revocation_generation"

# Returned when the counter cannot be read. fix(#1778): a sentinel is NOT a
# generation -- two entries stamped with it compared EQUAL, letting a stale
# positive outlive a revocation. Callers must check `is_usable_generation`.
UNKNOWN_GENERATION = -1


class RevocationGenerationError(RuntimeError):
    """The revocation counter could not be advanced.

    fix(#1778): a revocation other workers won't hear about must not quietly
    proceed. Raising rolls back the caller's transaction (undoing the
    ``is_active`` flip too), so the operator sees a failed revoke and retries
    rather than a "successful" one half the fleet ignores.
    """


def is_usable_generation(generation: int) -> bool:
    """Whether *generation* may be stamped on, or compared against, an entry."""
    return generation != UNKNOWN_GENERATION


# fix(#1778): a random 62-bit value, not a wall-clock second -- the old epoch
# seed could collide with itself (delete+heal within the same second
# reproduces it, or a fast-revoking fleet outpaces epoch-seconds so a reseed
# lands BEHIND the counter it replaces). A value drawn from [0, 2**62) makes
# any collision a ~2**-62 event; 2**62 (not the full 63-bit range) keeps
# floor()+cast from rounding the boundary into a negative bigint.
_SEED_EXPR = "(floor(random() * 4611686018427387904))::bigint"


async def bump_revocation_generation(db: AsyncSession) -> int:
    """Advance the generation inside the CALLER's transaction. Returns the new value.

    Not committed here and not run on a side session: it must become visible
    at the same instant as the caller's ``is_active`` flip, so a rollback
    leaves both undone together.
    """
    generation = await db.scalar(
        text(
            f"UPDATE {_TABLE} SET generation = generation + 1 "
            "WHERE id IS TRUE RETURNING generation"
        )
    )
    if generation is None:
        # fix(#1778): raise rather than return a sentinel -- returning one let
        # the revoke commit while every worker kept honouring cached positives.
        logger.error("revocation_generation_row_missing", operation="bump")
        raise RevocationGenerationError(
            "The revocation generation counter row is missing, so this "
            "revocation cannot be made visible to other workers. Refusing to "
            "complete it."
        )
    return int(generation)


async def current_revocation_generation(db: AsyncSession) -> int:
    """The generation a cache entry must carry to still be trusted.

    Read in the caller's transaction, BEFORE the row the cached decision is
    about, so the two can't disagree about which side of a revocation
    they're on.

    Never raises: an unreadable counter resolves to UNKNOWN_GENERATION, which
    is NOT a generation -- check ``is_usable_generation`` and skip the cache
    rather than stamp or compare with it. fix(#1778): treating the sentinel
    as an ordinary value let two entries stamped with it compare EQUAL.
    """
    try:
        generation = await db.scalar(
            text(f"SELECT generation FROM {_TABLE} WHERE id IS TRUE")
        )
        if generation is None:
            # fix(#1778): the heal must NOT run on `db` -- every production
            # caller's session is a get_db() read session, committed on
            # NOTHING. Healing on it "worked" for the rest of that request
            # then vanished when the session closed, re-healing forever.
            # Only a heal on its own connection, committed independently,
            # outlives the request that triggered it.
            logger.error("revocation_generation_row_missing", operation="read")
            healed_generation = await _reseed_missing_generation_row()
            logger.warning(
                "revocation_generation_row_healed",
                generation=healed_generation,
            )
            # Re-read through the CALLER's session rather than trust the
            # heal's return value: under READ COMMITTED (the default here) a
            # fresh statement in `db` always sees the just-committed row, so
            # this stays to one source of truth -- what `db` itself sees.
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

    fix(#1778): committed independently of the caller, NEVER on the caller's
    `AsyncSession` (see ``current_revocation_generation``). Late-imports
    ``app.core.db.engine`` like ``get_db()`` does -- a module-scope import
    would snapshot the engine before test fixtures rebind it, silently
    healing against the wrong database in tests.
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
