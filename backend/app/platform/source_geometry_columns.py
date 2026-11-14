"""The x/y or WKT columns a dataset's geometry was built from.

A CSV or spreadsheet has no geometry of its own; the import builds it from
the columns chosen at commit. A file replacement builds it the same way, so
the preview door and the replacement worker both read the choice here.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping
from typing import Any

from sqlalchemy import select

GEOMETRY_COLUMN_KEYS: tuple[str, ...] = ("x_column", "y_column", "geom_column")


def geometry_columns(mapping: Any) -> dict[str, str]:
    """The x/y pair or WKT column a mapping names, or ``{}`` when it names neither.

    Reads commit metadata and upload ``origin_ref`` payloads alike. The pair
    wins over a WKT column, as at import.
    """
    if not isinstance(mapping, Mapping):
        return {}
    named = {
        key: value
        for key in GEOMETRY_COLUMN_KEYS
        if isinstance(value := mapping.get(key), str) and value
    }
    if "x_column" in named and "y_column" in named:
        return {"x_column": named["x_column"], "y_column": named["y_column"]}
    if "geom_column" in named:
        return {"geom_column": named["geom_column"]}
    return {}


def columns_to_build(
    recorded: Mapping[str, str],
    *,
    source_geometry_type: str | None,
    source_columns: Iterable[Mapping[str, Any]],
) -> tuple[dict[str, str], list[str]]:
    """The recorded columns a source's geometry is built from, and those it lacks.

    A source with geometry of its own keeps it. Names compare
    case-insensitively, as at import; any missing column builds nothing.
    """
    if not recorded or source_geometry_type is not None:
        return {}, []
    names = {column["name"].lower() for column in source_columns}
    missing = [column for column in recorded.values() if column.lower() not in names]
    return ({} if missing else dict(recorded)), missing


async def recorded_geometry_columns(
    session, *, dataset_id: uuid.UUID, ref: Any
) -> dict[str, str]:
    """The columns the dataset's current geometry was built from, or ``{}``.

    ``ref`` is the dataset's origin payload, where the upload binding records
    them. A dataset imported before it did falls back to its newest completed
    job, ordered as retention orders the one job per dataset it keeps.
    """
    recorded = geometry_columns(ref)
    if recorded:
        return recorded
    from app.platform.jobs.models import IngestJob

    user_metadata = await session.scalar(
        select(IngestJob.user_metadata)
        .where(IngestJob.dataset_id == dataset_id, IngestJob.status == "complete")
        .order_by(IngestJob.created_at.desc())
        .limit(1)
    )
    return geometry_columns(user_metadata)
