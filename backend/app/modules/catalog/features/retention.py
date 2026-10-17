"""Delete a feature dataset's rows once they fall out of its retention window.

A dataset with retention keeps the rows whose retention column is no older
than its last ``retention_days`` days; a row where that column is null is
kept. A run deletes older rows in batches of ``BATCH_ROWS`` by ascending gid.
Each batch commits with the feature count lowered by what it deleted, the tile
cache version and data revision rolled, and an audit row recording it, so no
transaction holds a large share of a table's row locks and a committed batch
is current for tiles, exports and the count. The batch also marks the
dataset ``retention_settle_pending``, and the run that deleted then
recomputes the extent and derived geometry type and clears the mark. A run
cut short before that leaves the mark set, and the next run settles every
marked dataset, retention on or off, so the repair survives the setting
being cleared. A timestamp without time zone is read as UTC.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta, timezone

import structlog
from sqlalchemy import case, func, or_, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db.tenant_schema import tenant_data_schema
from app.core.db.tenant_session import current_tenant_var
from app.core.record_types import capabilities
from app.modules.audit.service import AuditEvent, audit_emit_required
from app.modules.catalog.datasets.domain.models import Dataset, Record
from app.modules.catalog.datasets.domain.schemas import DatasetRetention
from app.modules.catalog.datasets.domain.service import _safe_column_ref, get_dataset
from app.modules.catalog.features.idempotency import current_table_oid, held_table_oid
from app.modules.catalog.features.service import refresh_dataset_metadata
from app.platform.catalog_locks import (
    WORKER_LOCK_TIMEOUT,
    CatalogLockConflict,
    lock_catalog_rows,
    record_live_data_write,
    worker_lock_budget,
)
from app.platform.extensions import get_catalog_port

logger = structlog.get_logger(__name__)

BATCH_ROWS = 5000
# Per dataset per run; a larger backlog drains over later runs.
RUN_BATCHES = 20
SETTLE_ATTEMPTS = 3

TEMPORAL_TYPES = frozenset(
    {"date", "timestamp with time zone", "timestamp without time zone"}
)
# The name is spliced into SQL, quoted, so only plain names qualify.
_PLAIN_COLUMN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")
_GID_FLOOR = -(2**63)

# The relations a batch can delete from by (tableoid, ctid): ordinary and
# partitioned tables. A view, even an updatable one, has neither column.
TABLE_KINDS = frozenset({"r", "p"})
_TABLE_KIND = text(
    "SELECT c.relkind::text FROM pg_class c WHERE c.oid = to_regclass(format("
    "'%I.%I', CAST(:schema AS text), CAST(:table AS text)))"
)
_COLUMN_TYPE = text(
    "SELECT a.atttypid::regtype::text FROM pg_attribute a "
    "WHERE a.attrelid = to_regclass(format('%I.%I', "
    "CAST(:schema AS text), CAST(:table AS text))) "
    "AND a.attname = :column AND a.attnum > 0 AND NOT a.attisdropped"
)


class RetentionRefused(ValueError):
    """A retention setting the dataset cannot take."""


class _BatchStale(Exception):
    """The dataset, its table or its setting changed before the batch's lock."""


@dataclass(frozen=True)
class _Window:
    table_name: str
    column: str
    days: int
    cutoff: datetime | date
    table_oid: int | None


def is_feature_dataset(dataset: Dataset) -> bool:
    """Whether the dataset has a feature table with geometry, as feature writes need."""
    return (
        capabilities(dataset.record.record_type).feature_table
        and dataset.geometry_type is not None
    )


async def column_type(
    session: AsyncSession, table_name: str, column: str
) -> str | None:
    """The type of ``column`` in the dataset's live table, None when it is absent."""
    if not _PLAIN_COLUMN.match(column):
        return None
    return await session.scalar(
        _COLUMN_TYPE,
        {
            "schema": tenant_data_schema(current_tenant_var.get()),
            "table": table_name,
            "column": column,
        },
    )


async def table_kind(session: AsyncSession, table_name: str) -> str | None:
    """The pg_class relkind of the dataset's live relation, None when it is absent."""
    return await session.scalar(
        _TABLE_KIND,
        {"schema": tenant_data_schema(current_tenant_var.get()), "table": table_name},
    )


def cutoff_for(now: datetime, days: int, type_name: str) -> datetime | date:
    """The value a row's column must be older than to be deleted."""
    instant = now.astimezone(timezone.utc) - timedelta(days=days)
    if type_name == "date":
        return instant.date()
    if type_name == "timestamp without time zone":
        return instant.replace(tzinfo=None)
    return instant


async def check_retention(
    session: AsyncSession, dataset: Dataset, retention: DatasetRetention
) -> datetime | date:
    """Refuse a setting the dataset can't take; return its cutoff as of now."""
    if not is_feature_dataset(dataset):
        raise RetentionRefused("Retention applies only to datasets with features.")
    if await table_kind(session, dataset.table_name) not in TABLE_KINDS:
        raise RetentionRefused(
            "Retention needs the dataset's data in a table; this dataset reads "
            "it from a view or another kind of relation."
        )
    type_name = await column_type(session, dataset.table_name, retention.column)
    if type_name is None:
        raise RetentionRefused(f"Column {retention.column!r} does not exist.")
    if type_name not in TEMPORAL_TYPES:
        raise RetentionRefused(
            f"Column {retention.column!r} is {type_name}; retention needs a "
            "date or timestamp column."
        )
    return cutoff_for(datetime.now(timezone.utc), retention.days, type_name)


async def count_rows_past(
    session: AsyncSession, table_name: str, column: str, cutoff: datetime | date
) -> int:
    """Rows whose ``column`` is older than ``cutoff``. The caller checked ``column``."""
    quoted = get_catalog_port().quote_table(table_name)
    sql = f"SELECT count(*) FROM {quoted} WHERE {_safe_column_ref(column)} < :cutoff"
    # codeql[py/sql-injection] column matched _PLAIN_COLUMN, exists in the table and is quoted by _safe_column_ref; table via quote_table; cutoff is bound
    return await session.scalar(text(sql), {"cutoff": cutoff})


async def _window(
    session: AsyncSession, dataset_id: uuid.UUID, now: datetime
) -> tuple[Dataset, _Window] | None:
    """The dataset and its retention as stored now, or None when nothing is due."""
    dataset = await get_dataset(session, dataset_id)
    if dataset is None or dataset.retention_column is None:
        return None
    if dataset.retention_days is None or not is_feature_dataset(dataset):
        return None
    type_name = await column_type(session, dataset.table_name, dataset.retention_column)
    if type_name not in TEMPORAL_TYPES:
        logger.warning(
            "dataset_retention_column_unusable",
            dataset_id=str(dataset_id),
            column=dataset.retention_column,
            column_type=type_name,
        )
        return None
    return dataset, _Window(
        dataset.table_name,
        dataset.retention_column,
        dataset.retention_days,
        cutoff_for(now, dataset.retention_days, type_name),
        await current_table_oid(session, dataset.table_name),
    )


async def _hold_live_window(
    session: AsyncSession, window: _Window, now: datetime
) -> _Window:
    """Hold the table against DDL, then take the cutoff from its live column.

    ``_window`` reads the column's type without a lock, so a retype or a
    table swap can commit before the delete. ROW EXCLUSIVE conflicts with
    the ACCESS EXCLUSIVE every ALTER and swap takes, so the type read here
    holds until the batch ends. Raises ``_BatchStale`` when the table was
    replaced, is no longer an ordinary or partitioned table, or the column is
    no longer a date or timestamp.
    """
    quoted = get_catalog_port().quote_table(window.table_name)
    async with worker_lock_budget(session):
        # codeql[py/sql-injection] table via quote_table; the mode is a literal
        await session.execute(text(f"LOCK TABLE {quoted} IN ROW EXCLUSIVE MODE"))
    type_name = await column_type(session, window.table_name, window.column)
    if (
        await current_table_oid(session, window.table_name) != window.table_oid
        or await table_kind(session, window.table_name) not in TABLE_KINDS
        or type_name not in TEMPORAL_TYPES
    ):
        raise _BatchStale("table_or_column_changed")
    return replace(window, cutoff=cutoff_for(now, window.days, type_name))


async def _delete_batch(
    session: AsyncSession, window: _Window, after: int, limit: int
) -> list[int]:
    quoted = get_catalog_port().quote_table(window.table_name)
    column = _safe_column_ref(window.column)
    # MATERIALIZED picks the batch once; an IN subquery a nested loop rescans
    # would lock and delete a fresh batch per outer row. The delete matches the
    # locked rows themselves, not their gids: a registered table can hold one
    # gid twice, or in an inheritance child, where only (tableoid, ctid) is
    # unique. Locked rows cannot move before the delete.
    sql = (
        f"WITH batch AS MATERIALIZED (SELECT tableoid, ctid FROM {quoted} "
        f"WHERE {column} < :cutoff AND gid >= CAST(:after AS bigint) "
        "ORDER BY gid LIMIT :limit FOR UPDATE SKIP LOCKED) "
        f"DELETE FROM {quoted} WHERE (tableoid, ctid) IN "
        f"(SELECT tableoid, ctid FROM batch) AND {column} < :cutoff RETURNING gid"
    )
    params = {"cutoff": window.cutoff, "after": after, "limit": limit}
    async with worker_lock_budget(session):
        # codeql[py/sql-injection] column matched _PLAIN_COLUMN, exists in the table and is quoted by _safe_column_ref; table via quote_table; values are bound
        result = await session.execute(text(sql), params)
    # One gid per deleted row, repeats included. The caller pages from the
    # max inclusively, so expired rows sharing it are picked up next batch.
    return list(result.scalars())


async def _record_batch(
    session: AsyncSession, dataset: Dataset, window: _Window, deleted: int
) -> None:
    """Settle a batch's deletion in its own transaction, after the table work.

    The catalog rows are taken after the delete, the order every feature
    write uses, and the count moves by what was deleted rather than by a
    recount of the table. Raises ``_BatchStale``, for the caller to roll the
    delete back, when the dataset is gone or no longer names the table and
    setting the delete used.
    """
    await lock_catalog_rows(
        session,
        dataset_cls=Dataset,
        record_cls=Record,
        dataset_id=dataset.id,
        record_id=dataset.record_id,
        lock_timeout=WORKER_LOCK_TIMEOUT,
    )
    stored = (
        await session.execute(
            select(
                Dataset.table_name, Dataset.retention_column, Dataset.retention_days
            ).where(Dataset.id == dataset.id)
        )
    ).one_or_none()
    if stored is None or tuple(stored) != (
        window.table_name,
        window.column,
        window.days,
    ):
        raise _BatchStale
    await session.execute(
        update(Dataset)
        .where(Dataset.id == dataset.id)
        .values(
            feature_count=case(
                (Dataset.feature_count.is_(None), None),
                else_=func.greatest(Dataset.feature_count - deleted, 0),
            ),
            retention_settle_pending=True,
        )
        .execution_options(synchronize_session=False)
    )
    if await record_live_data_write(session, dataset) is None:
        raise _BatchStale
    await audit_emit_required(
        session,
        AuditEvent(
            user_id=None,
            action="dataset.retention_prune",
            resource_type="dataset",
            resource_id=dataset.id,
            details={
                "deleted": deleted,
                "column": window.column,
                "retention_days": window.days,
                "cutoff": window.cutoff.isoformat(),
            },
        ),
    )


async def _settle(dataset_id: uuid.UUID) -> None:
    """Recompute count, extent and derived geometry type, and clear the mark.

    The table is held first, then the catalog rows, the order column DDL,
    deletion and replacement take them, so settlement waits on a held table
    without holding the pair. A batch committing meanwhile either finishes
    before the recount, which then sees it, or waits for the rows and marks
    the dataset again.
    """
    from app.core.db import async_session

    for attempt in range(SETTLE_ATTEMPTS):
        async with async_session() as session:
            dataset = await get_dataset(session, dataset_id)
            if dataset is None:
                return
            try:
                async with worker_lock_budget(session):
                    await held_table_oid(session, dataset.table_name)
                await refresh_dataset_metadata(session, dataset)
            except CatalogLockConflict:
                if attempt + 1 == SETTLE_ATTEMPTS:
                    raise
                continue
            await session.execute(
                update(Dataset)
                .where(Dataset.id == dataset_id)
                .values(retention_settle_pending=False)
                .execution_options(synchronize_session=False)
            )
            await session.commit()
            return


async def prune_dataset(
    dataset_id: uuid.UUID,
    *,
    now: datetime,
    batch_rows: int = BATCH_ROWS,
    max_batches: int = RUN_BATCHES,
    settle_pending: bool = False,
) -> int:
    """Delete up to ``max_batches`` batches of the dataset's expired rows.

    Each batch re-reads the setting, so turning retention off stops a run
    after the batch in flight, and a batch whose dataset or setting changed
    before its lock deletes nothing and ends the dataset's run. Rows another
    transaction holds are skipped until a later run. The dataset is settled
    when this run deleted rows or ``settle_pending`` says an earlier one
    did not settle. Returns the number deleted.
    """
    from app.core.db import async_session

    deleted = 0
    after = _GID_FLOOR
    try:
        for _ in range(max_batches):
            try:
                async with async_session() as session:
                    due = await _window(session, dataset_id, now)
                    if due is None:
                        break
                    dataset, window = due
                    window = await _hold_live_window(session, window, now)
                    gids = await _delete_batch(session, window, after, batch_rows)
                    if gids:
                        await _record_batch(session, dataset, window, len(gids))
                    await session.commit()
            except _BatchStale as stale:
                logger.warning(
                    "dataset_retention_batch_rolled_back",
                    dataset_id=str(dataset_id),
                    reason=str(stale) or "dataset_or_setting_changed",
                )
                break
            if gids:
                deleted += len(gids)
                after = max(gids)
            if len(gids) < batch_rows:
                break
    finally:
        # Also after a failed batch, for the batches already committed.
        if deleted or settle_pending:
            await _settle(dataset_id)
    return deleted


async def prune_expired_rows(
    *,
    now: datetime | None = None,
    batch_rows: int = BATCH_ROWS,
    max_batches: int = RUN_BATCHES,
) -> dict[uuid.UUID, int]:
    """Run retention for every dataset in the current tenant scope that has it.

    A dataset whose retention was cleared after an unsettled batch is only
    settled. Returns the number of rows deleted per dataset that lost any.
    """
    from app.core.db import async_session

    now = now or datetime.now(timezone.utc)
    async with async_session() as session:
        due = (
            await session.execute(
                select(Dataset.id, Dataset.retention_settle_pending)
                .where(
                    or_(
                        Dataset.retention_days.is_not(None),
                        Dataset.retention_settle_pending,
                    )
                )
                .order_by(Dataset.id)
            )
        ).all()
    pruned: dict[uuid.UUID, int] = {}
    for dataset_id, settle_pending in due:
        try:
            deleted = await prune_dataset(
                dataset_id,
                now=now,
                batch_rows=batch_rows,
                max_batches=max_batches,
                settle_pending=settle_pending,
            )
        except Exception:  # broad: one dataset's failure must not stop the rest
            logger.warning(
                "dataset_retention_failed", dataset_id=str(dataset_id), exc_info=True
            )
            continue
        if deleted:
            pruned[dataset_id] = deleted
    if pruned:
        logger.info(
            "dataset_retention_run",
            datasets=len(pruned),
            deleted=sum(pruned.values()),
        )
    return pruned
