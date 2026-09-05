"""The one lock order for the (datasets, records) row pair (fix(#1847)).

Shared infrastructure rather than catalog code, for the same reason
``platform/security.py`` is: both halves of the application need it. Request
handlers under ``modules/catalog`` reach it directly; worker tasks under
``processing/`` reach it with the ORM classes ``ProcessingPort`` hands them,
because ``processing/`` may not import ``app.modules.catalog``
(``test_no_processing_imports_catalog``). Parameterising on the two mapped
classes is what lets one function serve both without either layer reaching
past its boundary.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

# The budget a REQUEST spends waiting for the pair. Matches
# ``app.platform.jobs.router`` and ``catalog.maps.service_crud``, which spend
# the same on the same question: a row lock still contended after two seconds
# is held by another live writer, not by latency inside this request, and the
# caller is better served by a retryable conflict than by an open-ended hang.
#
# A worker passes ``lock_timeout=None``. ``SET LOCAL`` applies to every lock
# wait for the rest of the transaction, and clamping a multi-minute ingest
# transaction to a request's budget would fail it on contention it is supposed
# to wait out.
REQUEST_LOCK_TIMEOUT = "2s"

# Resolved at CALL time, not bound as a default argument, so the value above is
# the single source of truth (a default argument would snapshot it at import).
_USE_REQUEST_DEFAULT: Any = object()


async def lock_catalog_rows(
    session: AsyncSession,
    *,
    dataset_cls: Any,
    record_cls: Any,
    dataset_id: Any,
    record_id: Any,
    lock_timeout: str | None = _USE_REQUEST_DEFAULT,
) -> None:
    """Take the datasets row, then the records row. In that order, always.

    **THE ORDER: datasets first, records second.** Call this from any
    transaction that will write both rows, BEFORE it writes either. Cite this
    docstring rather than restating the rule.

    Why this order and not the other one. The two background refresh writers
    (``processing/ingest/tasks_postgis_refresh.py`` and
    ``tasks_stac_refresh.py``) take the datasets row ``FOR UPDATE`` to make a
    superseded-content check and the write that depends on it one indivisible
    step, and the VRT publish transaction takes it through its asset join. Those
    are the sites that cannot give the order up, so the order is theirs.

    Why calling this is not optional for a writer that "only" touches one row.
    It is almost never only one. Stamping ``record.updated_by`` and rolling
    ``tile_cache_version`` is already both, and SQLAlchemy's unit of work
    flushes ``catalog.records`` BEFORE ``catalog.datasets`` because
    ``Dataset.record_id`` makes ``Record`` the parent mapper. So a transaction
    that acquires nothing acquires them in the inverted order by default, and
    deadlocks (40P01) against any of the writers above. That is #1847, and it
    is why ``tests/test_feature_lock_order_1847.py`` gates every such site.

    Splitting the two acquisitions across two flushes is the same bug. The
    acquisition has to precede the transaction's FIRST write to either row, not
    merely sit in the same flush as both: the feature-write handlers dirty
    ``record.updated_by``, flush it inside ``audit_emit``, and only then roll
    the tile version, so a rule keyed on "both dirty in one flush" would not
    have fired at all.
    """
    if lock_timeout is _USE_REQUEST_DEFAULT:
        lock_timeout = REQUEST_LOCK_TIMEOUT
    if lock_timeout is not None:
        # `SET LOCAL` takes a literal, not a bind parameter; the value is a
        # module constant or a caller's literal, never request-supplied data.
        await session.execute(text(f"SET LOCAL lock_timeout = '{lock_timeout}'"))

    # `no_autoflush` so the order below is what actually reaches PostgreSQL. An
    # autoflush triggered by either statement emits the ORM's own flush order,
    # which is the exact inversion this function exists to prevent.
    with session.no_autoflush:
        # One column, on each table alone. Reading through a joined
        # relationship would not lock the joined row anyway, and would put the
        # statement on the records row ahead of the lock it is ordering.
        await session.execute(
            select(dataset_cls.id).where(dataset_cls.id == dataset_id).with_for_update()
        )
        if record_id is not None:
            await session.execute(
                select(record_cls.id)
                .where(record_cls.id == record_id)
                .with_for_update()
            )
