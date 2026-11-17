"""What an export request selects, the artifact that answers it, and the conversion that builds one."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.dataset_origin import geolens_owns_table
from app.platform.http.ranges import parse_byte_range
from app.processing.export import artifact_cache
from app.processing.export.artifact_cache import ExportArtifact
from app.processing.export.ogr import (
    MAX_EXPORT_FEATURES as _MAX_EXPORT_FEATURES,
    bbox_where_sql,
    pmtiles_maxzoom_for_extent,
)
from app.processing.export.schemas import ExportFormat
from app.processing.export.service import (
    export_dataset,
    export_descriptor,
    validate_where_clause,
)
from app.processing.export.where_validator import canonical_where
from app.processing.ingest.metadata import _qtable

if TYPE_CHECKING:
    from app.processing.export.parquet import ParquetExportPlan


class SelectionTooLargeError(Exception):
    """The selection is over the export cap; the message is the response detail."""


@dataclass(frozen=True)
class ArtifactSelection:
    """The cache key of the requested bytes and the file they download as."""

    key: str
    filename: str
    media_type: str


@dataclass(frozen=True)
class ExportSource:
    """The dataset fields a conversion reads, copied before the session is released."""

    title: str
    table_name: str
    column_info: list[dict] | None
    has_geometry: bool
    spatial_extent: Any

    @classmethod
    def of(cls, dataset: Any) -> ExportSource:
        return cls(
            title=dataset.record.title,
            table_name=dataset.table_name,
            column_info=dataset.column_info,
            has_geometry=dataset.geometry_type is not None,
            spatial_extent=dataset.record.spatial_extent,
        )


def wants_xy(
    xy: bool,
    format: ExportFormat,
    geometry_type: str | None,
    column_info: list[dict] | None,
) -> bool:
    """Whether a CSV export adds longitude and latitude columns.

    Only for a point or multipoint layer that has neither column already.
    """
    column_names = {
        str(col.get("name", "")).lower()
        for col in column_info or []
        if isinstance(col, dict)
    }
    return bool(
        xy
        and format == ExportFormat.csv
        and (geometry_type or "").upper() in ("POINT", "MULTIPOINT")
        and not column_names & {"longitude", "latitude"}
    )


def artifact_selection(
    dataset: Any,
    *,
    dataset_id: uuid.UUID,
    format: ExportFormat,
    target_crs: str | None,
    bbox: str | None,
    where: str | None,
    exporter_version: str,
    xy: bool,
) -> ArtifactSelection:
    """The cache key for this request and its download name, without touching the DB."""
    key = artifact_cache.selection_key(
        dataset_id=dataset_id,
        table_name=dataset.table_name,
        dataset_title=dataset.record.title,
        tile_cache_version=dataset.tile_cache_version,
        format_key=str(format),
        target_crs=target_crs,
        bbox=bbox,
        where=where,
        exporter_version=exporter_version,
        xy=xy,
    )
    filename, media_type = export_descriptor(dataset.record.title, str(format))
    return ArtifactSelection(key=key, filename=filename, media_type=media_type)


async def _count_selected_features(
    db: AsyncSession,
    *,
    table_name: str,
    where: str | None,
    column_info: list[dict] | None,
    bbox: list[float] | None,
    has_geometry: bool,
    schema: str,
) -> int:
    """Bounded COUNT of the rows an export's filters select, stopping at cap+1.

    Raises:
        ValueError: the filter fails validation.
    """
    clauses: list[str] = []
    params: dict = {"limit": _MAX_EXPORT_FEATURES + 1}
    if where is not None:
        validate_where_clause(where, column_info)
        # The canonical AST re-render, never the caller's raw bytes. text()
        # reads ":name" as a bind, so a colon in a validated literal (an ISO
        # timestamp) is escaped to \: as parquet.py does.
        safe_where = canonical_where(where).replace(":", "\\:")
        clauses.append(f"({safe_where})")
    if bbox is not None and has_geometry:
        # A crossing bbox counts with the predicate the export runs. An ordinary
        # one counts with && only: ogr2ogr -spat keeps envelope false positives,
        # so an exact ST_Intersects count could pass while the export is larger.
        if bbox[0] > bbox[2]:
            clauses.append(bbox_where_sql(bbox))
        else:
            clauses.append(
                "geom_4326 && ST_MakeEnvelope(:minx, :miny, :maxx, :maxy, 4326)"
            )
        params.update(minx=bbox[0], miny=bbox[1], maxx=bbox[2], maxy=bbox[3])
    where_sql = " AND ".join(clauses) if clauses else "TRUE"
    sql = (
        f"SELECT COUNT(*) FROM (SELECT 1 FROM "
        f"{_qtable(table_name, schema=schema)} "
        f"WHERE {where_sql} LIMIT :limit) sub"
    )
    result = await db.execute(text(sql).bindparams(**params))
    return result.scalar_one()


async def _enforce_feature_cap(
    db: AsyncSession,
    dataset: Any,
    *,
    bbox: list[float] | None,
    where: str | None,
    schema: str,
) -> None:
    """Refuse an ogr2ogr export whose selection is over the cap.

    Only a dataset recorded over the cap is counted, and only when a filter
    could narrow it.
    """
    if dataset.feature_count is None or dataset.feature_count <= _MAX_EXPORT_FEATURES:
        return
    if bbox is None and where is None:
        raise SelectionTooLargeError(
            f"Dataset has {dataset.feature_count} features, exceeding the "
            f"{_MAX_EXPORT_FEATURES} unfiltered-export limit; narrow the "
            "export with a bbox or attribute filter."
        )
    selected = await _count_selected_features(
        db,
        table_name=dataset.table_name,
        where=where,
        column_info=dataset.column_info,
        bbox=bbox,
        has_geometry=dataset.geometry_type is not None,
        schema=schema,
    )
    if selected > _MAX_EXPORT_FEATURES:
        raise SelectionTooLargeError(
            f"Export filter still selects more than "
            f"{_MAX_EXPORT_FEATURES} features; narrow the export with a "
            "more selective bbox or attribute filter."
        )


async def check_selection(
    db: AsyncSession,
    dataset: Any,
    *,
    format: ExportFormat,
    bbox: list[float] | None,
    where: str | None,
    schema: str,
) -> ParquetExportPlan | None:
    """Every status-deciding check on what the request selects, producing no file.

    Returns the parquet plan for a parquet export, else None.

    Raises:
        ValueError: the filter fails validation.
        SelectionTooLargeError: the selection is over the export cap.
    """
    if format != ExportFormat.parquet:
        await _enforce_feature_cap(db, dataset, bbox=bbox, where=where, schema=schema)
        if where is not None:
            # The check export_dataset runs, against the same column_info,
            # early enough for HEAD to see it.
            validate_where_clause(where, dataset.column_info)
        return None
    # Parquet validates against the LIVE columns, not the nullable
    # dataset.column_info, and owns its own bounded count against them.
    from app.processing.export.parquet import (
        ExportTooLargeError,
        plan_parquet_export,
    )

    try:
        return await plan_parquet_export(
            db, dataset.table_name, schema=schema, bbox=bbox, where=where
        )
    except ExportTooLargeError as e:
        raise SelectionTooLargeError(str(e)) from e


def bytes_follow_key(
    dataset: Any, *, where: str | None, parquet_plan: ParquetExportPlan | None
) -> bool:
    """Whether the selection key alone pins the exported bytes.

    Every in-app write to a table GeoLens owns rolls a keyed field; a registered
    table can change by direct SQL and a filter can read the clock. Parquet only:
    ogr2ogr reads a PostGIS layer in heap order, which an UPDATE moves.
    """
    return (
        where is None
        and parquet_plan is not None
        and parquet_plan.has_gid
        and geolens_owns_table(
            dataset.source_format, dataset.record.record_type, dataset.origin_ref
        )
    )


def bare_satisfiable_range(
    range_header: str | None, if_range: str | None, size: int
) -> tuple[int, int] | None:
    """The resolved slice a bare Range (no If-Range) asks for, if it could be a 206.

    Parsed with the function ``read_response`` uses, so a malformed,
    multi-range or unsatisfiable header never costs the URL-history listing.
    """
    if if_range is not None:
        return None
    resolved = parse_byte_range(range_header, size)
    return resolved if isinstance(resolved, tuple) else None


async def cached_range_allowed(
    artifact: ExportArtifact,
    *,
    dataset_id: uuid.UUID,
    selection: str,
    range_header: str | None,
    if_range: str | None,
) -> bool:
    """Whether a cache hit may answer a Range with a slice.

    Not while the selection is contested, nor for a bare Range inside the first
    TTL after this URL's bytes changed, which closes the resume-splice window.
    """
    if artifact.contested:
        return False
    if not bare_satisfiable_range(range_header, if_range, artifact.size):
        return True
    return not await artifact_cache.url_answered_other_bytes_recently(
        dataset_id, selection, artifact.digest
    )


async def built_range_policy(
    stored: ExportArtifact,
    *,
    dataset_id: uuid.UUID,
    selection: str,
    bytes_follow_key: bool,
    held_before_build: set[str],
    range_header: str | None,
    if_range: str | None,
) -> tuple[bool, bool]:
    """``(may_serve_range, leading_slice_ok)`` for an artifact this request built.

    A bare Range is sliced only when the selection held these bytes before the
    build, the URL holds nothing else and the key pins the bytes. Otherwise
    whole, except a byte-0 Range while the URL answered no other bytes recently.
    """
    resolved = (
        None
        if stored.contested
        else bare_satisfiable_range(range_header, if_range, stored.size)
    )
    if resolved is None:
        return False, False
    may_serve_range = (
        bytes_follow_key
        and stored.digest in held_before_build
        and await artifact_cache.url_held_only_these_bytes(
            dataset_id, selection, stored.digest
        )
    )
    if may_serve_range or resolved[0] != 0:
        return may_serve_range, False
    leading_slice_ok = not await artifact_cache.url_answered_other_bytes_recently(
        dataset_id, selection, stored.digest
    )
    return False, leading_slice_ok


def built_etag(stored: ExportArtifact | None, digest: str | None) -> str | None:
    """The validator for a conversion: the published artifact's, else its own digest's.

    ``store`` recomputes the digest when handed None, so the published one wins.
    """
    if stored is not None:
        return stored.etag
    if digest is not None:
        return artifact_cache.strong_etag(digest)
    return None


async def convert(
    db: AsyncSession,
    source: ExportSource,
    format: ExportFormat,
    *,
    schema: str,
    target_crs: str | None,
    bbox: list[float] | None,
    where: str | None,
    parquet_plan: ParquetExportPlan | None,
    ordered: bool,
    xy: bool,
    deadline: float,
) -> tuple[str, str, str]:
    """Write the export file; returns ``(file_path, filename, media_type)``.

    GeoParquet uses the pyarrow writer (Debian's GDAL has no Arrow driver);
    every other format uses ogr2ogr.

    Raises:
        ValueError: the request is invalid for the converter.
        ExportError: the conversion failed.
        OSError: staging is unavailable.
    """
    if format == ExportFormat.parquet:
        from app.processing.export.parquet import export_parquet

        assert parquet_plan is not None  # set by check_selection
        return await export_parquet(
            db,
            source.table_name,
            source.title,
            schema=schema,
            plan=parquet_plan,
            ordered=ordered,
            deadline=deadline,
        )
    pmtiles_maxzoom = None
    if format == ExportFormat.pmtiles:
        # Budgeted from the dataset extent, not the request bbox, since -spat
        # selects whole features without clipping.
        from geoalchemy2.shape import to_shape

        bounds: tuple[float, float, float, float] | None = None
        if source.spatial_extent is not None:
            bounds = to_shape(source.spatial_extent).bounds
        pmtiles_maxzoom = pmtiles_maxzoom_for_extent(bounds)

    return await export_dataset(
        source.table_name,
        source.title,
        format,
        schema=schema,
        target_srs=target_crs,
        # -spat is a no-op on csv, the one ogr format a non-spatial table reaches.
        bbox=bbox if source.has_geometry else None,
        where=where,
        column_info=source.column_info,
        pmtiles_maxzoom=pmtiles_maxzoom,
        deadline=deadline,
        **({"xy": True} if xy else {}),
    )
