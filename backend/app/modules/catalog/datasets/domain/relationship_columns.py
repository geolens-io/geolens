"""Detection and reporting of relationship join columns that no longer exist."""

from __future__ import annotations

import re

from fastapi import HTTPException, status
from sqlalchemy.exc import ProgrammingError

from app.core.db.sqlstate import sqlstate
from app.modules.catalog.datasets.domain.models import Dataset, DatasetRelationship


def has_missing_column(
    source: Dataset, target: Dataset, rel: DatasetRelationship
) -> bool:
    """True when a stored schema is known and lacks a join column.

    A dataset with no stored schema is not reported broken: nothing says the
    column is gone.
    """
    for dataset, column in ((source, rel.source_column), (target, rel.target_column)):
        if dataset.column_info is None:
            continue
        if column != "gid" and column not in {c["name"] for c in dataset.column_info}:
            return True
    return False


_MISSING_COLUMN_RE = re.compile(r'column "([^"]+)"')


def tables_unavailable_error() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="A related dataset table is temporarily unavailable",
    )


def join_column_error(
    exc: ProgrammingError, rel: DatasetRelationship
) -> HTTPException | None:
    """409 naming the join column the table no longer has, else ``None``.

    Other undefined columns (``gid``, a projected property) are not fixed by
    editing the relationship, so they keep the caller's 503. A retry cannot
    fix a missing join column; the relationship has to be deleted or recreated.
    """
    if sqlstate(exc) != "42703":
        return None
    match = _MISSING_COLUMN_RE.search(str(getattr(exc, "orig", exc)))
    column = match.group(1) if match else None
    joins = {rel.source_column, rel.source_column.lower(), rel.target_column}
    if column not in joins:
        return None
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "code": "relationship_column_missing",
            "message": f"Relationship column {column!r} no longer exists in its dataset",
            "column": column,
        },
    )
