"""Detection and reporting of relationship join columns that no longer exist."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable

from fastapi import HTTPException, status
from sqlalchemy import select, text, update
from sqlalchemy.exc import DBAPIError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db.sqlstate import is_lock_conflict, sqlstate
from app.modules.catalog.datasets.domain.models import (
    AttributeMetadata,
    Dataset,
    DatasetRelationship,
    Record,
)
from app.modules.catalog.features.service import feature_table_exists
from app.platform.catalog_locks import (
    REQUEST_LOCK_TIMEOUT,
    CatalogLockConflict,
    lock_catalog_rows,
)
from app.platform.extensions import get_catalog_port


# Columns every feature table has but column_info never lists.
_INTERNAL_COLUMNS = frozenset({"gid", "geom", "geom_4326"})


def _lacks_column(dataset: Dataset, column: str) -> bool:
    """True when the dataset's stored schema is known and lacks the column.

    A dataset with no stored schema is not reported missing: nothing says the
    column is gone.
    """
    if dataset.column_info is None or column in _INTERNAL_COLUMNS:
        return False
    return column not in {c["name"] for c in dataset.column_info}


def has_missing_column(
    source: Dataset, target: Dataset, rel: DatasetRelationship
) -> bool:
    """True when a stored schema is known and lacks a join column."""
    return _lacks_column(source, rel.source_column) or _lacks_column(
        target, rel.target_column
    )


def tables_unavailable_error() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="A related dataset table is temporarily unavailable",
    )


def is_undefined_column(exc: ProgrammingError) -> bool:
    return sqlstate(exc) == "42703"


def join_column_error(
    exc: ProgrammingError, dataset: Dataset, join_column: str
) -> HTTPException | None:
    """409 when an undefined column is the failed query's join column and the
    dataset's stored schema no longer has it.

    Other undefined columns (``gid``, a projected property, the other endpoint's
    column) are not fixed by editing the relationship, so they return ``None``
    and keep the caller's 503. The stored schema, not the localized server
    message, says which column is gone. A retry cannot fix a missing join
    column; the relationship has to be deleted or recreated.
    """
    if sqlstate(exc) != "42703" or not _lacks_column(dataset, join_column):
        return None
    return column_missing_error(join_column)


def column_missing_error(join_column: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "code": "relationship_column_missing",
            "message": f"Relationship column {join_column!r} no longer exists in its dataset",
            "column": join_column,
        },
    )


async def refresh_dropped_join_column(
    session: AsyncSession,
    dataset_id: uuid.UUID,
    table_name: str,
    join_column: str,
    may_repair: Callable[[uuid.UUID], Awaitable[bool]] | None,
) -> HTTPException | None:
    """Return the permanent error when the live table lacks the join column.

    A column dropped directly in the database stays in ``column_info``, so the
    relationship list keeps reporting it healthy. The column is dropped from the stored
    list only when ``may_repair`` says the caller may modify the dataset; a read alone
    never writes the catalog. Returns ``None`` when the failure is not a
    dropped join column.
    """
    if join_column in _INTERNAL_COLUMNS:
        return None
    # The failed statement aborted the transaction; ids are captured by the caller.
    await session.rollback()
    # A shared table lock first, as the replacement swap orders its locks: a
    # direct DROP or ALTER waits, so the existence check and the scan see one
    # table.
    lock_sql = (
        f"LOCK TABLE {get_catalog_port().quote_table(table_name)} IN ACCESS SHARE MODE"
    )
    try:
        await session.execute(
            text(f"SET LOCAL lock_timeout = '{REQUEST_LOCK_TIMEOUT}'")
        )
        # codeql[py/sql-injection]
        await session.execute(text(lock_sql))
    except DBAPIError as exc:
        # A missing table or a held lock is the retryable 503; anything else is not ours.
        if not (isinstance(exc, ProgrammingError) or is_lock_conflict(exc)):
            raise
        await session.rollback()
        return None
    if not await feature_table_exists(session, table_name):
        return None
    live = await get_catalog_port().get_column_info(session, table_name)
    if any(c["name"] == join_column for c in live):
        return None
    error = column_missing_error(join_column)
    if may_repair is None or not await may_repair(dataset_id):
        return error
    record_id = (
        await session.execute(select(Dataset.record_id).where(Dataset.id == dataset_id))
    ).scalar_one_or_none()
    if record_id is None:
        return error
    try:
        await lock_catalog_rows(
            session,
            dataset_cls=Dataset,
            record_cls=Record,
            dataset_id=dataset_id,
            record_id=record_id,
        )
    except CatalogLockConflict:
        return None
    # Only the confirmed-missing column leaves the stored list; other drift is
    # left to the paths that reconcile attribute metadata with the schema.
    stored = await session.scalar(
        select(Dataset.column_info).where(Dataset.id == dataset_id)
    )
    if stored is not None:
        await session.execute(
            update(Dataset)
            .where(Dataset.id == dataset_id)
            .values(column_info=[c for c in stored if c["name"] != join_column])
        )
    await session.execute(
        update(AttributeMetadata)
        .where(
            AttributeMetadata.dataset_id == dataset_id,
            AttributeMetadata.field_name == join_column,
            AttributeMetadata.is_current.is_(True),
        )
        .values(is_current=False)
    )
    await session.commit()
    return error
