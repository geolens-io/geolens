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
from sqlalchemy.orm import joinedload

from app.core.identity import Identity
from app.modules.auth.dependencies import get_current_active_user
from app.modules.catalog.authorization import (
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
from app.platform.extensions import get_catalog_port, get_permission_extension
from app.modules.catalog.sources.security import make_safe_client
from app.platform.storage.titiler_url import resolve_storage_key
from app.standards.ogc.errors import ERROR_RESPONSES_WRITE

router = APIRouter(
    prefix="/datasets", tags=["Datasets - VRT"], responses=ERROR_RESPONSES_WRITE
)

VrtMutationResponse = get_catalog_port().vrt_mutation_response_model()


def _advisory_lock_key(dataset_id: uuid.UUID) -> int:
    """Derive a PostgreSQL advisory lock key from a UUID."""
    return dataset_id.int % (2**63)


async def _load_source_datasets(
    db: AsyncSession, dataset_ids: list[uuid.UUID]
) -> dict[uuid.UUID, object]:
    """Load VRT source datasets by id in one query, records eager-loaded.

    fix(#435): both VRT source endpoints called `get_dataset()` once per member row,
    so a 200-source VRT cost 200 round trips before it could return a page. The
    per-row `can_access_dataset()` call stays — it is the permission seam's decision
    to make, and only `restricted` rows reach the database from there. Batching that
    too needs a seam-level operation, because an overlay wrapping
    `DefaultPermissionExtension` must not have its policy skipped.
    """
    if not dataset_ids:
        return {}
    result = await db.execute(
        select(Dataset)
        .options(joinedload(Dataset.record))
        .where(Dataset.id.in_(dataset_ids))
    )
    return {dataset.id: dataset for dataset in result.scalars().unique().all()}


async def _remote_asset_exists(asset_uri: str) -> bool:
    """Probe a remote raster without downloading its body.

    Remote STAC assets are deliberately not passed to the configured object
    storage provider. The safe client pins validated public IPs and revalidates
    redirects, while the range request and context-manager close bound the
    amount of response data consumed by this health endpoint.
    """
    try:
        async with make_safe_client(timeout=10.0) as client:
            async with client.stream(
                "GET", asset_uri, headers={"Range": "bytes=0-0"}
            ) as response:
                return response.status_code < 400
    except (
        Exception
    ):  # broad: provider/network/SSRF failures all map to an inaccessible health state
        return False


@router.get("/{dataset_id}/vrt-sources/", response_model=VrtSourceListResponse)
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
    # SEC-E: SEC-C authorizes sources only at link time and there is no
    # migration re-authorizing pre-existing vrt_source_links, so a VRT may hold
    # member rows the caller cannot access (created before the fix, or a source
    # later flipped private / lost a grant). Drop those members here so their
    # title/CRS/resolution/extent never leak. Non-raising (can_access_dataset)
    # — a 404 would abort the whole listing.
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


@router.get("/{dataset_id}/vrt/status/", response_model=VrtStatusResponse)
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

    # Source count — raw total link count. This intentionally reflects ALL
    # links, while source_health below reflects only members the caller can
    # access (SEC-E). Recomputing the count from the filtered set would leak
    # the size of the unauthorized delta, so the totals are allowed to diverge.
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
                ra.storage_backend
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
    # SEC-E: drop members the caller cannot access (legacy links / authz drift)
    # before probing storage, so their existence/health never leaks.
    ext = get_permission_extension()

    # Collect sources and their URIs for parallel checks
    health_rows = source_rows.all()
    datasets_by_id = await _load_source_datasets(
        db, [row.source_dataset_id for row in health_rows if row.ds_id is not None]
    )
    sources_to_check = []
    for row in health_rows:
        if row.ds_id is None:
            # Source dataset was deleted. Keep this "missing" health branch and
            # the None-guard below so can_access_dataset never deref's
            # None.record for a source whose dataset row no longer exists.
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

    # Parallel backend-aware checks for non-missing sources. Remote STAC
    # assets are HTTP(S) URLs and cannot be meaningfully checked by local/S3
    # storage providers.
    if sources_to_check:
        tenant_id = current_tenant_var.get()
        exists_results = await asyncio.gather(
            *(
                _remote_asset_exists(row.asset_uri)
                if row.storage_backend == "remote"
                else storage.exists(
                    resolve_storage_key(row.asset_uri, tenant_id=tenant_id)
                )
                for row in sources_to_check
            )
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
    user: Identity = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> VrtGenerationListResponse:
    """Return paginated generation history for a VRT dataset."""
    VrtGeneration = get_catalog_port().vrt_generation_orm_class()

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
    response_model=VrtMutationResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def regenerate_vrt_endpoint(
    dataset_id: uuid.UUID,
    user: Identity = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> VrtMutationResponse:
    """Trigger manual VRT regeneration with advisory lock to prevent concurrent rebuilds."""
    from app.platform.jobs.defer_guard import defer_with_orphan_guard

    RasterAsset = get_catalog_port().raster_asset_orm_class()
    VrtGeneration = get_catalog_port().vrt_generation_orm_class()

    dataset = await get_dataset(db, dataset_id)
    if dataset is None or getattr(dataset.record, "record_type", None) != "vrt_dataset":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found"
        )
    # Owner-or-admin: regenerating the VRT mutates asset status and enqueues
    # work; previously any authenticated user could trigger it on a peer's raster.
    await check_dataset_write_access(db, dataset, dataset_id, user)

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
    job = await get_catalog_port().create_ingest_job(db, "vrt_regenerate", "", user.id)
    job.dataset_id = dataset_id

    await db.commit()

    # Dispatch task with orphan guard.
    # No stale-cleanup sweep exists for VRT ``status="regenerating"``
    # or for ``VrtGeneration`` rows — a Procrastinate outage would
    # leave the VRT permanently stuck and the generation row dangling
    # until manual operator intervention.
    async def _defer() -> None:
        await defer_async_with_tenant(
            get_catalog_port().regenerate_vrt_task(),
            job_id=str(job.id),
            attempt_id=str(job.attempt_id),
            vrt_dataset_id=str(dataset_id),
            generation_id=str(generation.id),
            triggered_by=str(user.id),
        )

    async def _rollback(defer_exc: BaseException) -> None:
        # Mark the VrtGeneration record failed so listings reflect
        # reality (the row was already committed via db.flush +
        # db.commit above).
        generation.status = "failed"
        generation.completed_at = datetime.now(timezone.utc)
        generation.error_message = f"Failed to queue VRT regeneration: {defer_exc}"
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
