"""Detection and reporting of relationship join columns that no longer exist."""

from __future__ import annotations

import uuid

from fastapi import HTTPException, status
from sqlalchemy import select, text, update
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db.sqlstate import sqlstate
from app.modules.catalog.datasets.domain.models import (
    Dataset,
    DatasetRelationship,
    Record,
)
from app.modules.catalog.features.service import feature_table_exists
from app.platform.catalog_locks import lock_catalog_rows
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
    session: AsyncSession, dataset_id: uuid.UUID, table_name: str, join_column: str
) -> HTTPException | None:
    """Store the live column list when a join column was dropped behind the catalog.

    A column dropped directly in the database stays in ``column_info``, so the
    relationship list keeps reporting it healthy. Returns the permanent error
    once the live table confirms the column is gone, else ``None``.
    """
    if join_column in _INTERNAL_COLUMNS:
        return None
    # The failed statement aborted the transaction; ids are captured by the caller.
    await session.rollback()
    # A shared table lock first, as the replacement swap orders its locks: a
    # direct DROP or ALTER waits, so the existence check, the scan and the
    # update all see one table.
    lock_sql = (
        f"LOCK TABLE {get_catalog_port().quote_table(table_name)} IN ACCESS SHARE MODE"
    )
    try:
        # codeql[py/sql-injection]
        await session.execute(text(lock_sql))
    except ProgrammingError:
        await session.rollback()
        return None
    record_id = (
        await session.execute(select(Dataset.record_id).where(Dataset.id == dataset_id))
    ).scalar_one_or_none()
    if record_id is None:
        return None
    await lock_catalog_rows(
        session,
        dataset_cls=Dataset,
        record_cls=Record,
        dataset_id=dataset_id,
        record_id=record_id,
    )
    if not await feature_table_exists(session, table_name):
        return None
    live = await get_catalog_port().get_column_info(session, table_name)
    if any(c["name"] == join_column for c in live):
        return None
    await session.execute(
        update(Dataset).where(Dataset.id == dataset_id).values(column_info=live)
    )
    await session.commit()
    return column_missing_error(join_column)
