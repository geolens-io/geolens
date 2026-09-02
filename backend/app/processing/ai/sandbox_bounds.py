"""Cost bounds shared by the two surfaces that reach the SQL sandbox.

fix(#1778): ``POST /api/query/`` and the AI chat ``query_data`` tool are gated
by the same ``use_ai_chat`` permission, run the same validator and executor,
and draw on the same connection pool. Every bound feat(#565) installed lived in
``query_router.py`` and applied to one of them, so each one was opt-out by
asking the chatbot instead of posting SQL. The comments there reasoned about
not changing chat's behavior, which was the right question for that PR and the
wrong one for two surfaces behind one permission.

What lives here is the bounds that protect a SHARED resource: the connection
pool (one semaphore, not one per surface -- two would admit twice the
concurrency the pool can serve) and the planner's worst-case cardinality.
Per-surface budgets stay with their surface: the raw endpoint keeps its
tighter statement timeout and its output-amplification denylist, because those
trade quality for cost on model-written SQL. ``query_router`` documents that
split at its own call site.
"""

from __future__ import annotations

import asyncio

from app.core.config import settings

# Self-join fan-out cap: the largest number of times any one base table is
# multiplied into a statement's worst-case cardinality (through CTEs, subquery
# correlation, LATERAL, and parenthesized groups). Two keeps ordinary pairwise
# self-joins working while refusing `a, a, a` and its launderings. The outer
# LIMIT bounds rows returned, not work performed, so nothing else catches it.
MAX_TABLE_REPEATS = 2

# Cap on inline VALUES rows: a large constant relation cross-joined a few times
# is a row explosion the base-table fan-out cap cannot see (#565 codex P1 r17).
# Generous enough for real lookup lists; the fan-out cap bounds the cross-join.
MAX_VALUES_ROWS = 256

# fix(#565 codex P1 r20): repeated plain projections need no function to
# amplify -- SELECT payload, payload, ... (1600x) FROM foo LIMIT 1 fits under
# the SQL cap and materializes a gigabyte-wide row.
MAX_OUTPUT_COLUMNS = 100


def capacity_bound() -> int:
    """Max concurrent sandbox queries admitted across both surfaces.

    A pool-derived, fail-fast global bound on top of the per-user advisory lock
    -- the lock stops ONE user stacking queries but not N distinct users each
    holding a connection, and the 10+3 pool exhausts at seven. Sizing at a
    third of the pool keeps unrelated endpoints from ever waiting on the pool
    timeout. Mirrors the analysis-preview bound (service_analysis.py) but
    cannot import it -- processing/ may not import modules.catalog -- so the
    small calc is repeated.
    """
    if settings.db_use_external_pooler:
        # NullPool: the real budget belongs to PgBouncer/RDS Proxy, invisible
        # here. Keep a throttle at the default-pool value rather than sizing
        # from settings that no longer apply.
        return 4
    overflow = max(0, settings.db_max_overflow)
    return max(1, (settings.db_pool_size + overflow) // 3)


# Per-worker (an asyncio.Semaphore cannot span processes); each worker has its
# own pool, so the ratio this protects holds per pool -- the thing that runs
# out. ONE object for both surfaces: the raw endpoint releases its request
# session before executing and chat does not, so chat's slot is the more
# expensive of the two, and giving it a second semaphore of the same size would
# put 2N queries on a pool sized for N.
query_slots = asyncio.Semaphore(capacity_bound())
