"""VRT dataset endpoints: sources, status, generations, and regeneration."""

import asyncio
import uuid
from datetime import datetime, timezone

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    status,
)
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_active_user
from app.auth.models import User
from app.auth.visibility import check_dataset_access
from app.datasets.schemas import (
    VrtActiveGeneration,
    VrtGenerationItem,
    VrtGenerationListResponse,
    VrtSourceHealth,
    VrtSourceItem,
    VrtSourceListResponse,
    VrtStatusResponse,
)
from app.datasets.service import get_dataset
from app.dependencies import get_db

router = APIRouter(prefix="/datasets", tags=["Datasets - VRT"])


def _advisory_lock_key(dataset_id: uuid.UUID) -> int:
    """Derive a PostgreSQL advisory lock key from a UUID."""
    return dataset_id.int % (2**63)


@router.get("/{dataset_id}/vrt-sources/", response_model=VrtSourceListResponse)
async def list_vrt_sources(
    dataset_id: uuid.UUID,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> VrtSourceListResponse:
    """Return ordered list of COG sources for a VRT dataset."""
    dataset = await get_dataset(db, dataset_id)
    if dataset is None or getattr(dataset.record, "record_type", None) != "vrt_dataset":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found"
        )
    await check_dataset_access(db, dataset, dataset_id, user)
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
    sources = []
    for row in rows.all():
        extent_bbox = None
        if row.extent_wkt:
            try:
                from shapely import wkt as shapely_wkt

                extent_bbox = list(shapely_wkt.loads(row.extent_wkt).bounds)
            except Exception:
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


@router.get("/{dataset_id}/vrt/status/", response_model=VrtStatusResponse)
async def get_vrt_status(
    dataset_id: uuid.UUID,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> VrtStatusResponse:
    """Return VRT dataset status, last generation time, source count, and per-source health."""
    from app.raster.models import RasterAsset, VrtGeneration
    from app.storage import get_storage

    dataset = await get_dataset(db, dataset_id)
    if dataset is None or getattr(dataset.record, "record_type", None) != "vrt_dataset":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found"
        )
    await check_dataset_access(db, dataset, dataset_id, user)

    # Load VRT RasterAsset
    asset_result = await db.execute(
        select(RasterAsset).where(RasterAsset.dataset_id == dataset_id)
    )
    vrt_asset = asset_result.scalar_one_or_none()
    if vrt_asset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="VRT asset not found"
        )

    vrt_status = vrt_asset.status or "ready"

    # Latest completed generation for last_generation_at
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

    # Source count
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
                ra.asset_uri
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

    # Collect sources and their URIs for parallel checks
    sources_to_check = []
    for row in source_rows.all():
        if row.ds_id is None:
            # Source dataset was deleted
            source_health_list.append(
                VrtSourceHealth(
                    dataset_id=row.source_dataset_id,
                    title=row.title or "Unknown (deleted)",
                    status="missing",
                )
            )
        else:
            sources_to_check.append(row)

    # Parallel storage.exists() checks for non-missing sources
    if sources_to_check:
        exists_results = await asyncio.gather(
            *(storage.exists(row.asset_uri) for row in sources_to_check)
        )
        for row, file_exists in zip(sources_to_check, exists_results):
            source_health_list.append(
                VrtSourceHealth(
                    dataset_id=row.source_dataset_id,
                    title=row.title or "Unknown",
                    status="healthy" if file_exists else "inaccessible",
                )
            )

    return VrtStatusResponse(
        status=vrt_status,
        last_generation_at=last_generation_at,
        source_count=source_count,
        active_generation=active_generation,
        source_health=source_health_list,
    )


@router.get("/{dataset_id}/vrt/generations/", response_model=VrtGenerationListResponse)
async def list_vrt_generations(
    dataset_id: uuid.UUID,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> VrtGenerationListResponse:
    """Return paginated generation history for a VRT dataset."""
    from app.raster.models import VrtGeneration

    dataset = await get_dataset(db, dataset_id)
    if dataset is None or getattr(dataset.record, "record_type", None) != "vrt_dataset":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found"
        )
    await check_dataset_access(db, dataset, dataset_id, user)

    # Total count
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
        .offset(offset)
    )
    generations = [
        VrtGenerationItem(
            id=g.id,
            status=g.status,
            started_at=g.started_at,
            completed_at=g.completed_at,
            duration_seconds=g.duration_seconds,
            error_message=g.error_message,
            source_count=g.source_count,
            triggered_by=g.triggered_by,
        )
        for g in gen_result.scalars().all()
    ]

    return VrtGenerationListResponse(generations=generations, total=total)


@router.post(
    "/{dataset_id}/vrt/regenerate/",
    response_model=None,
    status_code=status.HTTP_202_ACCEPTED,
)
async def regenerate_vrt_endpoint(
    dataset_id: uuid.UUID,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Trigger manual VRT regeneration with advisory lock to prevent concurrent rebuilds."""
    from app.ingest.schemas import VrtMutationResponse
    from app.ingest.service import create_ingest_job
    from app.ingest.tasks import regenerate_vrt
    from app.jobs.defer_guard import defer_with_orphan_guard
    from app.raster.models import RasterAsset, VrtGeneration

    dataset = await get_dataset(db, dataset_id)
    if dataset is None or getattr(dataset.record, "record_type", None) != "vrt_dataset":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found"
        )
    await check_dataset_access(db, dataset, dataset_id, user)

    # Load VRT RasterAsset
    asset_result = await db.execute(
        select(RasterAsset).where(RasterAsset.dataset_id == dataset_id)
    )
    vrt_asset = asset_result.scalar_one_or_none()
    if vrt_asset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="VRT asset not found"
        )

    # Status check
    if vrt_asset.status == "regenerating":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="VRT is currently regenerating",
        )

    # Advisory lock
    lock_key = _advisory_lock_key(dataset_id)
    lock_result = await db.execute(
        text("SELECT pg_try_advisory_xact_lock(:key)"),
        {"key": lock_key},
    )
    acquired = lock_result.scalar()
    if not acquired:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Another regeneration is in progress",
        )

    # Count sources
    count_result = await db.execute(
        text(
            "SELECT COUNT(*) FROM catalog.vrt_source_links WHERE vrt_dataset_id = :id"
        ),
        {"id": str(dataset_id)},
    )
    src_count = count_result.scalar() or 0

    # Create VrtGeneration record
    generation = VrtGeneration(
        vrt_dataset_id=dataset_id,
        status="pending",
        started_at=datetime.now(timezone.utc),
        source_count=src_count,
        triggered_by=str(user.id),
    )
    db.add(generation)
    await db.flush()

    # Update RasterAsset — capture pre-mutation values so the orphan
    # guard rollback (Theme H) can restore them if Procrastinate is
    # unreachable.
    previous_status = vrt_asset.status
    previous_generation_id = vrt_asset.current_generation_id
    vrt_asset.status = "regenerating"
    vrt_asset.current_generation_id = generation.id

    # Create IngestJob
    job = await create_ingest_job(db, "vrt_regenerate", "", user.id)
    job.dataset_id = dataset_id

    await db.commit()

    # Dispatch task with orphan guard.
    # No stale-cleanup sweep exists for VRT ``status="regenerating"``
    # or for ``VrtGeneration`` rows — a Procrastinate outage would
    # leave the VRT permanently stuck and the generation row dangling
    # until manual operator intervention.
    async def _defer() -> None:
        await regenerate_vrt.defer_async(
            job_id=str(job.id),
            vrt_dataset_id=str(dataset_id),
            triggered_by=str(user.id),
        )

    async def _rollback(defer_exc: BaseException) -> None:
        # Mark the VrtGeneration record failed so listings reflect
        # reality (the row was already committed via db.flush +
        # db.commit above).
        generation.status = "failed"
        generation.completed_at = datetime.now(timezone.utc)
        generation.error_message = (
            f"Failed to queue VRT regeneration: {defer_exc}"
        )
        # Revert VRT asset state to pre-mutation values.
        vrt_asset.status = previous_status
        vrt_asset.current_generation_id = previous_generation_id
        # Mark the IngestJob failed.
        job.status = "failed"
        job.error_message = f"Failed to queue VRT regeneration: {defer_exc}"
        job.completed_at = datetime.now(timezone.utc)

    await defer_with_orphan_guard(_defer, rollback=_rollback, db=db)

    return VrtMutationResponse(
        job_id=job.id,
        message="VRT regeneration started",
    )
