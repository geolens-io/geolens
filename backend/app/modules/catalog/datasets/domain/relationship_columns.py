"""Detection and reporting of relationship join columns that no longer exist."""

from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy.exc import ProgrammingError

from app.core.db.sqlstate import sqlstate
from app.modules.catalog.datasets.domain.models import Dataset, DatasetRelationship


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
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "code": "relationship_column_missing",
            "message": f"Relationship column {join_column!r} no longer exists in its dataset",
            "column": join_column,
        },
    )
