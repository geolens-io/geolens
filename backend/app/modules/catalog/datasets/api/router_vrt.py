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
from app.platform.extensions import get_catalog_port, get_permission_extension
from app.modules.catalog.sources.origin_probe import remote_asset_exists
from app.platform.storage.titiler_url import resolve_storage_key
from app.standards.ogc.errors import ERROR_RESPONSES_WRITE, FORBIDDEN_RESPONSE

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
                remote_asset_exists(row.asset_uri)
                if row.storage_backend == "remote"
                else storage.exists(
                    resolve_storage_key(row.asset_uri, tenant_id=tenant_id)
                )
                for row in sources_to_check
            )
        )
        # feat(#1221): a member whose own raster was replaced (#1221's replace
        # path restamps `ingested_at` when it swaps the pointer) leaves this
        # parent's stored VRT naming a COG that no longer exists. The member
        # itself probes healthy — it is the parent that needs regenerating —
        # so surface that as its own state rather than letting a working
        # source read as fine while the mosaic is broken.
        # fix(#1290 review): staleness is a STATE comparison now — what the
        # member IS versus what the published VRT was built FROM. Timestamps
        # could not answer it: a replacement assigns `ingested_at` inside its
        # transaction and commits later, so a rebuild snapshotting in between
        # reads the OLD uri (read committed) and afterwards finds the member's
        # stamp EARLIER than its own. Healthy, and wrong. Postgres exposes no
        # commit-time stamp from inside the transaction, so no clock scheme
        # could have closed it.
        #
        # `built_from` is NULL for VRTs built before it existed; those fall
        # back to the legacy timestamp comparison, which is the best available
        # answer for a row that never recorded its inputs.
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

    fix(#1860): the listing gated on ``check_dataset_access``, which is a
    VISIBILITY check by its own contract, admitting any signed-in caller on a
    published public or internal dataset. It then returned every row's
    ``error_message`` and ``triggered_by``: failure text plus who edits the
    dataset, behind visibility alone. That is the same door this change closes
    on ``GET /jobs/by-dataset/{dataset_id}``, and the one
    ``list_dataset_refresh_runs`` had already closed on its own identical
    fields.

    ``include_detail`` is the ``can_view_dataset_provenance`` answer, and there
    is deliberately no per-row "you triggered this one" arm. Every writer of a
    ``VrtGeneration`` row goes through ``check_dataset_write_access``
    (``regenerate_vrt_endpoint`` here, ``add_vrt_source`` and
    ``remove_vrt_source`` in the ingest router), which is owner-or-admin, so
    every actor who can appear in ``triggered_by`` already passes the
    predicate. Such an arm would select nobody.

    Kept for a reader who fails the predicate, because ``get_vrt_status`` on
    the same dataset already publishes the same facts to the same audience:
    ``id`` (no route reads a generation by id), ``status``, ``started_at``,
    ``completed_at``, ``duration_seconds`` and ``source_count``.

    Redacted: ``error_message``, which is GDAL and VRT failure text naming
    server paths and member assets, and ``triggered_by``, which is a raw user
    id. Those are the two fields ``DatasetRefreshRunResponse`` nulls for this
    same reader.
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
    # fix(#1860): visibility and disclosure are two questions. The check above
    # settles the first and admits any signed-in reader of a published public
    # or internal dataset; this settles the second.
    can_view_detail = can_view_dataset_provenance(dataset.record, user, user_roles)

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

    # Dispatch task with orphan guard. This closes the SYNCHRONOUS failure —
    # Procrastinate unreachable at enqueue time — by reverting the mutation
    # below before it is ever visible. A worker that dies AFTER a successful
    # dispatch is a different failure and is not this guard's job: fix(#1267)
    # gives ``sweep_stale_vrt_assets`` (GAP-002) a periodic + startup pass
    # that reconciles it — restoring the asset to ``'ready'`` and failing the
    # orphaned ``VrtGeneration`` row — so neither state is stuck on manual
    # operator intervention.
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
