"""The x/y or WKT columns a dataset's geometry was built from, and their CRS.

A CSV or spreadsheet has no geometry of its own; the import builds it from
the columns chosen at commit. A file replacement builds it the same way, so
the preview door and the replacement worker both read the choice here.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping
from typing import Any, NamedTuple

from sqlalchemy import select

from app.platform.column_names import laundered_column_name

GEOMETRY_COLUMN_KEYS: tuple[str, ...] = ("x_column", "y_column", "geom_column")
COLUMN_SRID_KEY = "column_srid"

# Drivers that read a table of rows, where geometry is a choice of columns and
# GDAL's own detection of a WKT column must not override that choice.
TABULAR_DRIVERS = frozenset({"CSV", "XLSX", "XLS", "ODS"})


class GeometrySelection(NamedTuple):
    """The columns geometry is built from and the CRS of their coordinates."""

    columns: dict[str, str]
    srid: int | None

    def fields(self) -> dict[str, Any]:
        """The keys an upload binding, a job or a version records it under."""
        return {**self.columns, COLUMN_SRID_KEY: self.srid}


def geometry_selection(mapping: Any) -> GeometrySelection | None:
    """The x/y pair or WKT column a mapping names, or ``None`` when it names neither.

    Reads commit metadata, upload ``origin_ref`` payloads and version rows. The
    pair wins over a WKT column, as at import. The CRS is the recorded one, or
    a commit's ``srid_override``.
    """
    if not isinstance(mapping, Mapping):
        return None
    named = {
        key: value
        for key in GEOMETRY_COLUMN_KEYS
        if isinstance(value := mapping.get(key), str) and value
    }
    if "x_column" in named and "y_column" in named:
        columns = {"x_column": named["x_column"], "y_column": named["y_column"]}
    elif "geom_column" in named:
        columns = {"geom_column": named["geom_column"]}
    else:
        return None
    srid = mapping.get(COLUMN_SRID_KEY, mapping.get("srid_override"))
    return GeometrySelection(
        columns, srid if isinstance(srid, int) and not isinstance(srid, bool) else None
    )


def selection_fields(mapping: Any) -> dict[str, Any] | None:
    """The fields of the selection a mapping names, or ``None``."""
    selection = geometry_selection(mapping)
    return None if selection is None else selection.fields()


def columns_to_build(
    recorded: GeometrySelection | None,
    *,
    source_geometry_type: str | None,
    source_columns: Iterable[Mapping[str, Any]],
    driver: str | None,
) -> tuple[GeometrySelection | None, list[str]]:
    """The selection a source's geometry is built from, and the columns it lacks.

    A table of rows always builds from the recorded columns, so a WKT column
    GDAL detects cannot replace them. Any other source with geometry of its
    own keeps it. Names compare as ogr2ogr stores them.
    """
    if recorded is None:
        return None, []
    if driver not in TABULAR_DRIVERS and source_geometry_type is not None:
        return None, []
    names = {laundered_column_name(column["name"]) for column in source_columns}
    missing = [
        column
        for column in recorded.columns.values()
        if laundered_column_name(column) not in names
    ]
    return (None if missing else recorded), missing


async def recorded_geometry_selection(
    session, *, dataset_id: uuid.UUID, current_version: int | None, ref: Any
) -> GeometrySelection | None:
    """The selection the dataset's live data was built from, or ``None``.

    ``ref`` is the dataset's origin payload, where the upload binding records
    it. A dataset imported before it did and never replaced since reads it
    from its import job, the oldest completed job for the dataset.
    """
    recorded = geometry_selection(ref)
    if recorded is not None or current_version != 1:
        return recorded
    from app.platform.jobs.models import IngestJob

    user_metadata = await session.scalar(
        select(IngestJob.user_metadata)
        .where(IngestJob.dataset_id == dataset_id, IngestJob.status == "complete")
        .order_by(IngestJob.created_at)
        .limit(1)
    )
    return geometry_selection(user_metadata)
