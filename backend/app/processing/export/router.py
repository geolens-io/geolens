"""Export API endpoint: download datasets in various formats."""

import os
import re
import shutil
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import FileResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.background import BackgroundTask

from app.modules.audit.service import AuditEvent, audit_emit
from app.core.identity import Identity
from app.modules.auth.dependencies import get_optional_user
from app.modules.auth.permissions import get_effective_permissions
from app.core.dependencies import get_db
from app.core.db.tenant_schema import tenant_data_schema
from app.core.db.tenant_session import current_tenant_var
from app.platform.extensions import get_permission_extension, get_processing_port
from app.processing.export.ogr import ExportError
from app.processing.export.schemas import ExportFormat
from app.processing.export.service import export_dataset, validate_where_clause
from app.processing.export.where_validator import canonical_where
from app.processing.ingest.metadata import _qtable
from app.standards.ogc.errors import (
    BAD_REQUEST_RESPONSE,
    FORBIDDEN_RESPONSE,
    NOT_FOUND_RESPONSE,
    PAYLOAD_TOO_LARGE_RESPONSE,
)

router = APIRouter(
    prefix="/datasets",
    tags=["Datasets"],
    responses={
        400: BAD_REQUEST_RESPONSE,
        403: FORBIDDEN_RESPONSE,
        404: NOT_FOUND_RESPONSE,
        413: PAYLOAD_TOO_LARGE_RESPONSE,
    },
)

# fix(#430 BA-08): ceiling for full-table exports (by feature count). An
# unbounded ogr2ogr over the whole table writes an arbitrarily large temp file
# and holds a worker for the full duration; require callers to narrow very
# large datasets with bbox/where. Codex r8: a filter must actually narrow the
# selection — a merely-present tautological filter (e.g. where=1=1) previously
# bypassed the cap entirely, so oversized datasets now get a bounded COUNT with
# the caller's filters applied. BA-06's subprocess timeout bounds runtime
# regardless.
_MAX_EXPORT_FEATURES = 5_000_000


def _cleanup_export(path: str) -> None:
    """Remove the temporary export directory after response is sent."""
    if os.path.isdir(path):
        shutil.rmtree(path, ignore_errors=True)


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
    """Bounded COUNT of the rows an export's filters actually select.

    Cap guard for oversized datasets (fix(#430 BA-08), codex r8). The WHERE
    fragment is validated (AST allowlist + column check) before interpolation —
    the same trust boundary as the ogr2ogr -where path that executes the same
    fragment right after — and the inner LIMIT stops the scan at cap+1 rows, so
    this check does strictly less work than the export it gates.
    """
    clauses: list[str] = []
    params: dict = {"limit": _MAX_EXPORT_FEATURES + 1}
    if where is not None:
        try:
            validate_where_clause(where, column_info)
            # Interpolate the canonical AST re-render, not the caller's raw
            # bytes — the count query never splices unvalidated user input.
            safe_where = canonical_where(where)
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(e),
            )
        clauses.append(f"({safe_where})")
    if bbox is not None and has_geometry and bbox[0] <= bbox[2]:
        # Envelope && only (superset of exact intersects) — errs toward 413.
        # Antimeridian bboxes (minx > maxx) skip the clause and count without
        # it, also conservative. Non-spatial datasets skip it too: ogr2ogr
        # -spat is a no-op on a layer with no geometry, so the unfiltered
        # count matches what the export would actually emit.
        clauses.append("geom_4326 && ST_MakeEnvelope(:minx, :miny, :maxx, :maxy, 4326)")
        params.update(minx=bbox[0], miny=bbox[1], maxx=bbox[2], maxy=bbox[3])
    where_sql = " AND ".join(clauses) if clauses else "TRUE"
    sql = (
        f"SELECT COUNT(*) FROM (SELECT 1 FROM "
        f"{_qtable(table_name, schema=schema)} "
        f"WHERE {where_sql} LIMIT :limit) sub"
    )
    result = await db.execute(text(sql).bindparams(**params))
    return result.scalar_one()


@router.get("/{dataset_id}/export", response_class=FileResponse)
async def export_dataset_endpoint(
    dataset_id: uuid.UUID,
    request: Request,
    format: ExportFormat = Query(ExportFormat.gpkg, description="Export format"),
    target_crs: str | None = Query(None, description="Target CRS, e.g. EPSG:3857"),
    bbox: str | None = Query(
        None, description="Bounding box: minx,miny,maxx,maxy (WGS84)"
    ),
    where: str | None = Query(
        None, description="Attribute filter expression, e.g. pop > 1000"
    ),
    # IA-P1-01 (Phase 1069, updated Phase 1157 EXP-01): the "export" capability
    # is now enforced on the authenticated branch only (see handler body).
    # Anonymous callers are allowed to export public+published datasets without
    # a capability check — matching the OGC/tiles anonymous-access contract.
    # Authenticated callers still require the "export" capability via the
    # per-role matrix check below.
    user: Identity | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
) -> FileResponse:
    """Export a dataset as a downloadable file.

    Supports GeoPackage, GeoJSON, Shapefile (zipped), CSV, and GeoParquet
    formats. Optional CRS reprojection, spatial filtering, and attribute
    filtering. GeoParquet is always emitted in EPSG:4326 (OGC:CRS84).
    """
    port = get_processing_port()
    data_schema = tenant_data_schema(current_tenant_var.get())
    # 1. Fetch dataset
    dataset = await port.get_dataset(db, dataset_id)
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dataset not found",
        )

    # 2. Visibility + permission check (branches on authenticated vs anonymous).
    # Function-level import: processing/ must not import app.modules.catalog at
    # module scope (Phase 225 PROCESS-02/04 layering guard — test_layering.py).
    # Mirrors the existing parse_bbox import below.
    from app.modules.catalog.authorization import (
        check_dataset_access,
        check_dataset_access_or_anonymous,
        get_user_roles,
    )

    if user is None:
        # Anonymous export: enforce public+published gate via the anon-aware
        # helper (raises 404 to hide existence on denial), then a
        # defense-in-depth guard requiring public visibility.
        await check_dataset_access_or_anonymous(db, dataset, dataset_id, user)
        if dataset.record.visibility != "public":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Anonymous export requires public dataset",
            )
    else:
        # Authenticated path: full RBAC visibility check + export capability.
        await check_dataset_access(db, dataset, dataset_id, user)
        user_roles = await get_user_roles(db, user)
        matrix = await get_effective_permissions(db)
        # Enforce the export capability through the permission extension — the
        # same path as require_permission("export") — so deployments that
        # register a custom PermissionExtension apply their policy here too. The
        # default extension reduces to the role/matrix check, so OSS behavior is
        # unchanged. (Codex review: export/router.py:92.)
        granted = await get_permission_extension().check_permission(
            db,
            user,
            "export",
            user_roles=user_roles,
            permission_matrix=matrix,
        )
        if not granted:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Missing permission: export",
            )

    # 3. Parse bbox
    from app.modules.catalog.features.service import parse_bbox

    bbox_parsed: list[float] | None = None
    if bbox:
        try:
            bbox_parsed = parse_bbox(bbox)
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid bbox: {e}",
            )

    # 4. Validate target_crs
    if target_crs is not None:
        if not re.match(r"^EPSG:\d+$", target_crs, re.IGNORECASE):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid target_crs: must match EPSG:<code> (e.g. EPSG:3857)",
            )
        # GeoParquet is written directly via pyarrow in EPSG:4326 (OGC:CRS84);
        # reprojection/PROJJSON isn't implemented on that path, so reject a
        # conflicting target rather than silently emitting 4326.
        if format == ExportFormat.parquet and target_crs.upper() != "EPSG:4326":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="GeoParquet export is emitted in EPSG:4326; omit target_crs.",
            )

    # 5. Reject raster/VRT datasets: they have no tabular feature table.
    # Key on record_type (loaded via joinedload(Dataset.record) in
    # get_dataset), NOT geometry_type — a legitimate non-spatial TABLE
    # dataset (record_type="table") also has geometry_type=None but IS a
    # real CSV-exportable table and must NOT be blocked. A raster/VRT
    # dataset has a synthetic table_name with no backing table, so letting
    # csv proceed would hit ogr2ogr on a nonexistent table -> raw 500.
    if dataset.record.record_type in ("raster_dataset", "vrt_dataset"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Raster datasets have no tabular feature data to export; "
                "use the raster tile/COG endpoints."
            ),
        )

    # 6. Check geometry compatibility
    if dataset.geometry_type is None and format in (
        "gpkg",
        "geojson",
        "shp",
        "parquet",
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot export non-spatial dataset as {format}. Use csv format.",
        )

    # 6b. fix(#430 BA-08): bound full-table exports. Codex r8: for oversized
    # datasets a filter only passes if it actually narrows the selection under
    # the cap (bounded filtered COUNT), closing the where=1=1 bypass.
    #
    # Parquet is exempt here: export_parquet() runs its own bounded-count cap
    # against the LIVE-introspected columns. Running this guard for parquet too
    # would validate the filter against the nullable dataset.column_info and
    # wrongly reject a valid filter on a metadata-less oversized dataset before
    # the parquet path's introspection can run (Codex r10).
    if (
        format != ExportFormat.parquet
        and dataset.feature_count is not None
        and dataset.feature_count > _MAX_EXPORT_FEATURES
    ):
        if bbox_parsed is None and where is None:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=(
                    f"Dataset has {dataset.feature_count} features, exceeding the "
                    f"{_MAX_EXPORT_FEATURES} unfiltered-export limit; narrow the "
                    "export with a bbox or attribute filter."
                ),
            )
        selected = await _count_selected_features(
            db,
            table_name=dataset.table_name,
            where=where,
            column_info=dataset.column_info,
            bbox=bbox_parsed,
            has_geometry=dataset.geometry_type is not None,
            schema=data_schema,
        )
        if selected > _MAX_EXPORT_FEATURES:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=(
                    f"Export filter still selects more than "
                    f"{_MAX_EXPORT_FEATURES} features; narrow the export with a "
                    "more selective bbox or attribute filter."
                ),
            )

    # 7. Run export. GeoParquet goes through the pyarrow writer (the Debian GDAL
    # build has no Arrow driver); all other formats use the ogr2ogr path.
    try:
        if format == ExportFormat.parquet:
            from app.processing.export.parquet import (
                ExportTooLargeError,
                export_parquet,
            )

            try:
                file_path, filename, media_type = await export_parquet(
                    db,
                    dataset.table_name,
                    dataset.record.title,
                    schema=data_schema,
                    bbox=bbox_parsed,
                    where=where,
                )
            except ExportTooLargeError as e:
                # In-memory parquet build exceeded the cap (covers datasets with a
                # NULL feature_count that skipped the guard above).
                raise HTTPException(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail=str(e),
                )
        else:
            file_path, filename, media_type = await export_dataset(
                dataset.table_name,
                dataset.record.title,
                format,
                schema=data_schema,
                target_srs=target_crs,
                bbox=bbox_parsed,
                where=where,
                column_info=dataset.column_info,
            )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except ExportError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Export failed",
        )
    except OSError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Export temporarily unavailable",
        )

    # 8. Audit log. user_id may be None for anonymous exports (EXP-01).
    # The audit_logs.user_id column is nullable; AuditEvent.user_id is typed
    # uuid.UUID | None to match.
    #
    # fix(#435): the export file exists from here on, but nothing owns it until the
    # FileResponse below attaches the background cleanup. An audit or commit failure
    # in between used to strand the directory on the staging volume.
    temp_dir = os.path.dirname(file_path)
    try:
        await audit_emit(
            db,
            AuditEvent(
                user_id=user.id if user is not None else None,
                action="dataset.export",
                resource_type="dataset",
                resource_id=dataset_id,
                details={
                    "format": format,
                    "target_crs": target_crs,
                    "bbox": bbox,
                    "where": where,
                },
                ip_address=request.client.host if request.client else None,
            ),
        )
        await db.commit()
    except BaseException:
        _cleanup_export(temp_dir)
        raise

    # 9. Return file with background cleanup
    return FileResponse(
        path=file_path,
        filename=filename,
        media_type=media_type,
        background=BackgroundTask(_cleanup_export, temp_dir),
    )
