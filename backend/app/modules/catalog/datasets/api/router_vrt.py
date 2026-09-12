"""VRT dataset endpoints: sources, status, generations, and regeneration."""

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    status,
)
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.core.identity import Identity
from app.modules.auth.dependencies import get_current_active_user
from app.modules.catalog.authorization import (
    can_view_dataset_provenance,
    check_dataset_access,
    check_dataset_write_access,
)
from app.modules.catalog.datasets.domain.schemas import (
    VrtActiveGeneration,
    VrtGenerationItem,
    VrtGenerationListResponse,
    VrtSourceHealth,
    VrtSourceItem,
    VrtSourceListResponse,
    VrtStatusResponse,
)
from app.modules.catalog.datasets.domain.models import Dataset
from app.modules.catalog.datasets.domain.service import get_dataset
from app.core.db.tenant_session import current_tenant_var, defer_async_with_tenant
from app.core.dependencies import get_db
from app.platform.catalog_locks import admit_vrt_mutation
from app.platform.extensions import get_catalog_port, get_permission_extension
from app.modules.catalog.sources.origin_probe import remote_asset_exists
from app.platform.storage.titiler_url import resolve_storage_key
from app.standards.ogc.errors import ERROR_RESPONSES_WRITE, FORBIDDEN_RESPONSE

router = APIRouter(
    prefix="/datasets", tags=["Datasets - VRT"], responses=ERROR_RESPONSES_WRITE
)

VrtMutationResponse = get_catalog_port().vrt_mutation_response_model()


async def _load_source_datasets(
    db: AsyncSession, dataset_ids: list[uuid.UUID]
) -> dict[uuid.UUID, object]:
    """Load VRT source datasets by id in one query, records eager-loaded.

    fix(#435): both VRT source endpoints called `get_dataset()` once per
    member row, so a 200-source VRT cost 200 round trips. The per-row
    `can_access_dataset()` call stays -- it's the permission seam's
    decision, and batching it too would risk skipping an overlay's policy.
    """
    if not dataset_ids:
        return {}
    result = await db.execute(
        select(Dataset)
        .options(joinedload(Dataset.record))
        .where(Dataset.id.in_(dataset_ids))
    )
    return {dataset.id: dataset for dataset in result.scalars().unique().all()}


@router.get(
    "/{dataset_id}/vrt-sources/",
    response_model=VrtSourceListResponse,
    responses={403: FORBIDDEN_RESPONSE},
)
async def list_vrt_sources(
    dataset_id: uuid.UUID,
    user: Identity = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> VrtSourceListResponse:
    """Return ordered list of COG sources for a VRT dataset."""
    dataset = await get_dataset(db, dataset_id)
    if dataset is None or getattr(dataset.record, "record_type", None) != "vrt_dataset":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found"
        )
    user_roles = await check_dataset_access(db, dataset, dataset_id, user)
    rows = await db.execute(
        text("""
            SELECT vsl.source_dataset_id AS dataset_id, rec.title, vsl.position,
                   ra.band_count, ra.res_x AS resolution_x, ra.res_y AS resolution_y,
                   ra.epsg AS crs_epsg, ST_AsText(rec.spatial_extent) AS extent_wkt
            FROM catalog.vrt_source_links vsl
            JOIN catalog.datasets d ON d.id = vsl.source_dataset_id
            JOIN catalog.records rec ON rec.id = d.record_id
            JOIN catalog.raster_assets ra ON ra.dataset_id = vsl.source_dataset_id
            WHERE vsl.vrt_dataset_id = :vrt_id
            ORDER BY vsl.position ASC
        """),
        {"vrt_id": str(dataset_id)},
    )
    # SEC-E: SEC-C authorizes sources only at link time with no migration
    # re-authorizing pre-existing links, so a VRT may hold member rows the
    # caller can't access. Drop those here so title/CRS/resolution/extent
    # never leak; non-raising (can_access_dataset) since a 404 would abort
    # the whole listing.
    ext = get_permission_extension()
    source_rows = rows.all()
    datasets_by_id = await _load_source_datasets(
        db, [row.dataset_id for row in source_rows]
    )
    sources = []
    for row in source_rows:
        src_dataset = datasets_by_id.get(row.dataset_id)
        if src_dataset is None or not await ext.can_access_dataset(
            db, src_dataset, row.dataset_id, user, user_roles=user_roles
        ):
            continue
        extent_bbox = None
        if row.extent_wkt:
            try:
                from shapely import wkt as shapely_wkt

                extent_bbox = list(shapely_wkt.loads(row.extent_wkt).bounds)
            except Exception:  # broad: WKT parse — shapely can throw varied errors on malformed extent; degrade to no-bbox
                pass
        sources.append(
            VrtSourceItem(
                dataset_id=row.dataset_id,
                title=row.title,
                position=row.position,
                band_count=row.band_count,
                resolution_x=row.resolution_x,
                resolution_y=row.resolution_y,
                crs_epsg=row.crs_epsg,
                extent_bbox=extent_bbox,
            )
        )
    return VrtSourceListResponse(sources=sources)


@router.get(
    "/{dataset_id}/vrt/status/",
    response_model=VrtStatusResponse,
    responses={403: FORBIDDEN_RESPONSE},
)
async def get_vrt_status(
    dataset_id: uuid.UUID,
    user: Identity = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> VrtStatusResponse:
    """Return VRT dataset status, last generation time, source count, and per-source health."""
    from app.platform.storage import get_storage

    RasterAsset = get_catalog_port().raster_asset_orm_class()
    VrtGeneration = get_catalog_port().vrt_generation_orm_class()

    dataset = await get_dataset(db, dataset_id)
    if dataset is None or getattr(dataset.record, "record_type", None) != "vrt_dataset":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found"
        )
    user_roles = await check_dataset_access(db, dataset, dataset_id, user)

    asset_result = await db.execute(
        select(RasterAsset).where(RasterAsset.dataset_id == dataset_id)
    )
    vrt_asset = asset_result.scalar_one_or_none()
    if vrt_asset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="VRT asset not found"
        )

    vrt_status = vrt_asset.status or "ready"

    gen_result = await db.execute(
        select(VrtGeneration)
        .where(
            VrtGeneration.vrt_dataset_id == dataset_id,
            VrtGeneration.status == "completed",
        )
        .order_by(VrtGeneration.completed_at.desc())
        .limit(1)
    )
    last_gen = gen_result.scalar_one_or_none()
    last_generation_at = last_gen.completed_at if last_gen else None

    # Raw total link count, intentionally including ALL links, while
    # source_health below reflects only accessible members (SEC-E).
    # Recomputing from the filtered set would leak the unauthorized delta.
    count_result = await db.execute(
        text(
            "SELECT COUNT(*) FROM catalog.vrt_source_links WHERE vrt_dataset_id = :id"
        ),
        {"id": str(dataset_id)},
    )
    source_count = count_result.scalar() or 0

    # Active generation (if regenerating)
    active_generation = None
    if vrt_status == "regenerating":
        active_result = await db.execute(
            select(VrtGeneration)
            .where(
                VrtGeneration.vrt_dataset_id == dataset_id,
                VrtGeneration.status.in_(["pending", "running"]),
            )
            .order_by(VrtGeneration.started_at.desc())
            .limit(1)
        )
        active_gen = active_result.scalar_one_or_none()
        if active_gen and active_gen.started_at:
            elapsed = (
                datetime.now(timezone.utc) - active_gen.started_at
            ).total_seconds()
            active_generation = VrtActiveGeneration(
                generation_id=active_gen.id,
                started_at=active_gen.started_at,
                elapsed_seconds=elapsed,
            )

    # Source health check
    source_rows = await db.execute(
        text("""
            SELECT
                vsl.source_dataset_id,
                r.title,
                d.id AS ds_id,
                ra.asset_uri,
                ra.storage_backend,
                ra.ingested_at
            FROM catalog.vrt_source_links vsl
            LEFT JOIN catalog.datasets d ON d.id = vsl.source_dataset_id
            LEFT JOIN catalog.records r ON r.id = d.record_id
            LEFT JOIN catalog.raster_assets ra ON ra.dataset_id = d.id
            WHERE vsl.vrt_dataset_id = :vrt_id
            ORDER BY vsl.position ASC
        """),
        {"vrt_id": str(dataset_id)},
    )
    source_health_list = []
    storage = get_storage()
    # SEC-E: drop members the caller cannot access (legacy links / authz
    # drift) before probing storage, so their existence/health never leaks.
    ext = get_permission_extension()

    health_rows = source_rows.all()
    datasets_by_id = await _load_source_datasets(
        db, [row.source_dataset_id for row in health_rows if row.ds_id is not None]
    )
    sources_to_check = []
    for row in health_rows:
        if row.ds_id is None:
            # Source dataset was deleted; this branch and the None-guard
            # below keep can_access_dataset from deref'ing None.record.
            source_health_list.append(
                VrtSourceHealth(
                    dataset_id=row.source_dataset_id,
                    title=row.title or "Unknown (deleted)",
                    status="missing",
                )
            )
            continue
        src_dataset = datasets_by_id.get(row.source_dataset_id)
        if src_dataset is None or not await ext.can_access_dataset(
            db, src_dataset, row.source_dataset_id, user, user_roles=user_roles
        ):
            # SEC-E: omit unauthorized members before any storage.exists probe.
            continue
        sources_to_check.append(row)

    # Remote STAC assets are HTTP(S) URLs and can't be meaningfully checked
    # by local/S3 storage providers.
    if sources_to_check:
        tenant_id = current_tenant_var.get()
        exists_results = await asyncio.gather(
            *(
                remote_asset_exists(row.asset_uri)
                if row.storage_backend == "remote"
                else storage.exists(
                    resolve_storage_key(row.asset_uri, tenant_id=tenant_id)
                )
                for row in sources_to_check
            )
        )
        # feat(#1221): a replaced member probes healthy on its own, but the
        # parent's stored VRT still names the old COG -- surface that as
        # the member's own "stale" state instead of "fine".
        # fix(#1290): compares STATE (what the member IS vs what the VRT
        # was built FROM), not timestamps -- a replacement's `ingested_at`
        # commits after a concurrent rebuild's read, so a timestamp
        # comparison can read a healthy member as stale. `built_from` NULL
        # means pre-#1290 VRTs, which fall back to the timestamp comparison.
        built_from = vrt_asset.built_from or None
        built_at = vrt_asset.last_regenerated_at or vrt_asset.ingested_at
        for row, file_exists in zip(sources_to_check, exists_results):
            if not file_exists:
                member_status = "inaccessible"
            elif built_from is not None:
                recorded = built_from.get(str(row.source_dataset_id))
                member_status = "healthy" if recorded == row.asset_uri else "stale"
            elif (
                built_at is not None
                and row.ingested_at is not None
                and row.ingested_at > built_at
            ):
                member_status = "stale"
            else:
                member_status = "healthy"
            source_health_list.append(
                VrtSourceHealth(
                    dataset_id=row.source_dataset_id,
                    title=row.title or "Unknown",
                    status=member_status,
                )
            )

    return VrtStatusResponse(
        status=vrt_status,
        last_generation_at=last_generation_at,
        source_count=source_count,
        active_generation=active_generation,
        source_health=source_health_list,
    )


def _vrt_generation_item(generation: Any, *, include_detail: bool) -> VrtGenerationItem:
    """One row of a VRT dataset's regeneration history.

    fix(#1860): visibility alone used to gate this list, leaking every
    row's ``error_message`` (GDAL/VRT failure text naming server paths)
    and ``triggered_by`` (a raw user id) to any signed-in reader of a
    public/internal dataset. ``include_detail`` is the
    ``can_view_dataset_provenance`` answer; both fields null otherwise,
    matching what ``DatasetRefreshRunResponse`` redacts for the same reader.

    No per-row "you triggered this one" arm: every ``VrtGeneration``
    writer goes through ``check_dataset_write_access`` (owner-or-admin),
    so it would select nobody.
    """
    return VrtGenerationItem(
        id=generation.id,
        status=generation.status,
        started_at=generation.started_at,
        completed_at=generation.completed_at,
        duration_seconds=generation.duration_seconds,
        error_message=generation.error_message if include_detail else None,
        source_count=generation.source_count,
        triggered_by=generation.triggered_by if include_detail else None,
    )


@router.get(
    "/{dataset_id}/vrt/generations/",
    response_model=VrtGenerationListResponse,
    responses={403: FORBIDDEN_RESPONSE},
)
async def list_vrt_generations(
    dataset_id: uuid.UUID,
    limit: int = Query(20, ge=1, le=100),
    skip: int = Query(
        0,
        ge=0,
        description="Number of generation records to skip.",
    ),
    offset: int | None = Query(
        None,
        ge=0,
        deprecated=True,
        description="Deprecated alias for skip; takes precedence when supplied.",
    ),
    user: Identity = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> VrtGenerationListResponse:
    """Return paginated generation history for a VRT dataset.

    Not every caller gets every field. Seeing the dataset decides whether there
    is a history at all; the provenance predicate decides whether its rows carry
    their failure text and the id of whoever triggered them. See
    ``_vrt_generation_item``.
    """
    VrtGeneration = get_catalog_port().vrt_generation_orm_class()
    pagination_offset = offset if offset is not None else skip

    dataset = await get_dataset(db, dataset_id)
    if dataset is None or getattr(dataset.record, "record_type", None) != "vrt_dataset":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found"
        )
    user_roles = await check_dataset_access(db, dataset, dataset_id, user)
    # fix(#1860): visibility and disclosure are two questions. The check
    # above settles the first; this settles the second.
    can_view_detail = can_view_dataset_provenance(dataset.record, user, user_roles)

    count_result = await db.execute(
        select(func.count())
        .select_from(VrtGeneration)
        .where(VrtGeneration.vrt_dataset_id == dataset_id)
    )
    total = count_result.scalar() or 0

    # Paginated results
    gen_result = await db.execute(
        select(VrtGeneration)
        .where(VrtGeneration.vrt_dataset_id == dataset_id)
        .order_by(VrtGeneration.created_at.desc())
        .limit(limit)
        .offset(pagination_offset)
    )
    generations = [
        _vrt_generation_item(g, include_detail=can_view_detail)
        for g in gen_result.scalars().all()
    ]

    return VrtGenerationListResponse(generations=generations, total=total)


@router.post(
    "/{dataset_id}/vrt/regenerate/",
    response_model=VrtMutationResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def regenerate_vrt_endpoint(
    dataset_id: uuid.UUID,
    user: Identity = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> VrtMutationResponse:
    """Trigger manual VRT regeneration with advisory lock to prevent concurrent rebuilds."""
    from app.platform.jobs.defer_guard import (
        defer_with_orphan_guard,
        make_vrt_regeneration_failed_rollback,
    )

    RasterAsset = get_catalog_port().raster_asset_orm_class()
    VrtGeneration = get_catalog_port().vrt_generation_orm_class()

    dataset = await get_dataset(db, dataset_id)
    if dataset is None or getattr(dataset.record, "record_type", None) != "vrt_dataset":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found"
        )
    # Owner-or-admin: regenerating mutates asset status and enqueues work;
    # any authenticated user could otherwise trigger it on a peer's raster.
    await check_dataset_write_access(db, dataset, dataset_id, user)

    asset_result = await db.execute(
        select(RasterAsset).where(RasterAsset.dataset_id == dataset_id)
    )
    vrt_asset = asset_result.scalar_one_or_none()
    if vrt_asset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="VRT asset not found"
        )

    # fix(#1955): the lock, then the status re-read under it. The two used to
    # be a status check followed by a lock, which leaves the window the second
    # of two concurrent triggers lands in.
    if not await admit_vrt_mutation(db, dataset_id, vrt_asset):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "dataset_busy",
                "message": "Another regeneration is in progress",
            },
        )

    count_result = await db.execute(
        text(
            "SELECT COUNT(*) FROM catalog.vrt_source_links WHERE vrt_dataset_id = :id"
        ),
        {"id": str(dataset_id)},
    )
    src_count = count_result.scalar() or 0

    generation = VrtGeneration(
        vrt_dataset_id=dataset_id,
        status="pending",
        started_at=datetime.now(timezone.utc),
        source_count=src_count,
        triggered_by=str(user.id),
    )
    db.add(generation)
    await db.flush()

    # Capture pre-mutation values so the orphan guard rollback can restore
    # them if Procrastinate is unreachable.
    previous_status = vrt_asset.status
    previous_generation_id = vrt_asset.current_generation_id
    vrt_asset.status = "regenerating"
    vrt_asset.current_generation_id = generation.id

    job = await get_catalog_port().create_ingest_job(db, "vrt_regenerate", "", user.id)
    job.dataset_id = dataset_id

    await db.commit()

    # Dispatch with orphan guard: closes the SYNCHRONOUS failure
    # (Procrastinate unreachable at enqueue time) by reverting the mutation
    # before it's ever visible. A worker dying AFTER a successful dispatch
    # is fix(#1267)'s ``sweep_stale_vrt_assets`` job to reconcile instead.
    async def _defer() -> None:
        await defer_async_with_tenant(
            get_catalog_port().regenerate_vrt_task(),
            job_id=str(job.id),
            attempt_id=str(job.attempt_id),
            vrt_dataset_id=str(dataset_id),
            generation_id=str(generation.id),
            triggered_by=str(user.id),
        )

    # The VrtGeneration row was already committed via db.flush + db.commit
    # above; rollback marks it failed and reverts vrt_asset to its
    # pre-mutation values (captured before that commit).
    rollback = make_vrt_regeneration_failed_rollback(
        vrt_asset,
        generation,
        job,
        previous_status=previous_status,
        previous_generation_id=previous_generation_id,
    )
    await defer_with_orphan_guard(_defer, rollback=rollback, db=db, job=job)

    return VrtMutationResponse(
        job_id=job.id,
        message="VRT regeneration started",
    )
