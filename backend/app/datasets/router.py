"""Dataset API endpoints: list, get, update, delete, history, re-upload, versions, and DCAT export."""

import asyncio
import io
import math
import uuid
from collections.abc import Iterable, Mapping
from pathlib import Path

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)
from fastapi.responses import JSONResponse, RedirectResponse, StreamingResponse
from geoalchemy2.shape import to_shape
from datetime import datetime, timezone

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.audit.schemas import AuditLogListResponse, AuditLogResponse
from app.audit.service import log_action, query_audit_logs
from app.cache import get_cache
from app.cache.tiles import invalidate_catalog_cache
from app.auth.dependencies import (
    get_current_active_user,
    get_optional_user,
    require_permission,
)
from app.auth.models import User
from app.auth.visibility import (
    apply_visibility_filter,
    check_dataset_access,
    check_dataset_access_or_anonymous,
    get_user_roles,
)
from app.config import settings
from app.dcat.service import catalog_to_dcat, record_to_dcat
from app.datasets.schemas import (
    AttributeMetadataListResponse,
    AttributeMetadataResponse,
    AttributeMetadataUpdate,
    ColumnStatsResponse,
    ColumnValuesResponse,
    CreateEmptyDatasetRequest,
    DatasetDeleteRequest,
    DatasetListResponse,
    DatasetMeta,
    DatasetRelationshipCreate,
    DatasetRelationshipResponse,
    DatasetResponse,
    DatasetRowsResponse,
    DatasetVersionListResponse,
    DatasetVersionResponse,
    RasterBandInfo,
    RasterConnect,
    RasterMetadata,
    RelatedDatasetsResponse,
    ReuploadCommitRequest,
    ReuploadCommitResponse,
    ReuploadPreviewResponse,
    ReuploadServicePreviewRequest,
    ReuploadResponse,
    SchemaDiff,
    StatusUpdate,
    VrtActiveGeneration,
    VrtGenerationItem,
    VrtGenerationListResponse,
    VrtSourceHealth,
    VrtSourceItem,
    VrtSourceListResponse,
    VrtStatusResponse,
)
from app.collections.service import get_dataset_collections
from app.datasets.models import Dataset as DatasetModel, DatasetGrant, Record
from app.validation.schemas import (
    ValidationIssue as ValidationIssueSchema,
    ValidationResultResponse,
)
from app.validation.service import validate_record as run_validation
from app.datasets.service import (
    DependentVrtError,
    compute_schema_diff,
    create_empty_dataset,
    delete_dataset,
    get_dataset,
    get_dataset_rows,
    get_dataset_versions,
    get_related_datasets,
    list_datasets,
    update_user_metadata,
)
from app.public_urls import get_public_api_url
from app.dependencies import get_db
from app.ingest.metadata import compute_quality_score
from app.ingest.ogr import IngestionError, run_ogrinfo_preview
from app.ingest.schemas import (
    PresignedCompleteRequest,
    PresignedUploadRequest,
    PresignedUploadResponse,
    UploadResponse,
)
from app.ingest.service import (
    create_ingest_job,
    save_upload_file,
    validate_file_extension,
)
from app.ingest.tasks import reupload_file, reupload_service
from app.ingest.validation import validate_file_content
from app.jobs.models import IngestJob
from app.services.provenance import (
    UNKNOWN_ACTOR_LABEL,
    derive_last_edited,
    resolve_actor,
)
from app.services.preview import build_gdal_source, run_service_preview
from app.services.security import SSRFError, validate_url_for_ssrf
from app.storage import get_storage

router = APIRouter(prefix="/datasets", tags=["Datasets"])


def _public_base_url(request: Request) -> str:
    """Derive the public-facing origin from forwarded headers (nginx/Vite proxy).

    Prefers X-Forwarded-Host (set by both nginx and Vite proxy) over Host,
    since changeOrigin proxies overwrite Host with the upstream target.
    """
    proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    host = (
        request.headers.get("x-forwarded-host")
        or request.headers.get("host")
        or str(request.base_url.hostname)
    )
    port = ""
    if ":" in host:
        host, port = host.rsplit(":", 1)
        # Suppress default ports
        if (proto == "https" and port == "443") or (proto == "http" and port == "80"):
            port = ""
    if port:
        return f"{proto}://{host}:{port}"
    return f"{proto}://{host}"

PRIORITY_QUEUE_THRESHOLD_BYTES = (
    10 * 1024 * 1024
)  # 10MB -- small files get priority queue


def _extent_to_bbox(extent) -> list[float] | None:
    """Convert a GeoAlchemy2 geometry extent to a [minx, miny, maxx, maxy] bbox."""
    if extent is None:
        return None
    try:
        shape = to_shape(extent)
        return list(shape.bounds)
    except Exception:
        return None


async def _load_actor_identities(
    db: AsyncSession,
    actor_ids: Iterable[uuid.UUID | None],
) -> dict[uuid.UUID, User]:
    ids = {actor_id for actor_id in actor_ids if actor_id is not None}
    if not ids:
        return {}
    result = await db.execute(select(User).where(User.id.in_(ids)))
    users = result.scalars().all()
    return {u.id: u for u in users}


def _build_raster_metadata(
    dataset, raster_asset, is_admin: bool = False, source_count: int | None = None, base_url: str | None = None,
) -> RasterMetadata | None:
    """Build RasterMetadata from a RasterAsset ORM object."""
    if raster_asset is None:
        return None

    # Build bands list from band_info JSONB
    bands = []
    if raster_asset.band_info:
        for b in raster_asset.band_info:
            bands.append(
                RasterBandInfo(
                    index=b.get("index", 0),
                    dtype=b.get("dtype", ""),
                    nodata=b.get("nodata"),
                    color_interp=b.get("color_interp"),
                )
            )

    # s3_uri exposed only to admins when storage backend is S3
    s3_uri = None
    if raster_asset.storage_backend == "s3" and is_admin:
        s3_uri = raster_asset.asset_uri

    # Build tile and download URLs
    # tile_url_meta stays relative (used by map rendering in the browser)
    # connect URLs are absolute with api_key placeholder (for external GIS tools)
    tile_url_path = f"/raster-tiles/{dataset.id}/tiles/{{z}}/{{x}}/{{y}}.png"
    tile_url_meta = tile_url_path
    quicklook_url = f"/api/datasets/{dataset.id}/quicklook?size=256"

    if base_url:
        tile_url_connect = f"{base_url}{tile_url_path}?api_key={{your_key}}"
    else:
        tile_url_connect = tile_url_path

    # VRT datasets don't have a single COG download
    record_type = getattr(dataset, "record_type", None) or getattr(dataset.record, "record_type", None)
    is_vrt = record_type == "vrt_dataset"
    if is_vrt:
        download_url = None
    else:
        download_url = f"/api/datasets/{dataset.id}/download/cog"

    connect = RasterConnect(
        download_url=download_url,
        tile_url=tile_url_connect,
        s3_uri=s3_uri,
    )

    return RasterMetadata(
        epsg=raster_asset.epsg,
        res_x=raster_asset.res_x,
        res_y=raster_asset.res_y,
        band_count=raster_asset.band_count,
        nodata=raster_asset.nodata,
        compression=raster_asset.compression,
        width=raster_asset.width,
        height=raster_asset.height,
        size_bytes=raster_asset.size_bytes,
        quicklook_url=quicklook_url,
        tile_url=tile_url_meta,
        bands=bands,
        connect=connect,
        status=raster_asset.status,
        vrt_type=raster_asset.vrt_type,
        source_count=source_count,
        resolution_strategy=raster_asset.resolution_strategy,
    )


def _dataset_to_response(
    dataset,
    *,
    collections=None,
    actors_by_id: Mapping[uuid.UUID, User] | None = None,
    raster_asset=None,
    is_admin: bool = False,
    source_count: int | None = None,
    base_url: str | None = None,
    stac_assets=None,
) -> DatasetResponse:
    """Convert a Dataset ORM object to a DatasetResponse schema."""
    record = dataset.record
    actor_map = actors_by_id or {}

    created_user = actor_map.get(record.created_by) if record.created_by else None
    updated_user = actor_map.get(record.updated_by) if record.updated_by else None

    created_by_display = resolve_actor(
        record.created_by,
        created_user,
        missing_label=UNKNOWN_ACTOR_LABEL,
    )
    last_edited = derive_last_edited(
        created_at=record.created_at,
        updated_at=record.updated_at,
        updated_by=record.updated_by,
        updated_user=updated_user,
    )

    # Build raster metadata for raster_dataset and vrt_dataset records
    raster_metadata = None
    record_type = getattr(record, "record_type", "vector_dataset") or "vector_dataset"
    if record_type in ("raster_dataset", "vrt_dataset") and raster_asset is not None:
        raster_metadata = _build_raster_metadata(dataset, raster_asset, is_admin=is_admin, source_count=source_count, base_url=base_url)

    return DatasetResponse(
        id=dataset.id,
        record_id=dataset.record_id,
        table_name=dataset.table_name,
        title=record.title,
        summary=record.summary,
        srid=dataset.srid,
        geometry_type=dataset.geometry_type,
        feature_count=dataset.feature_count,
        extent_bbox=_extent_to_bbox(record.spatial_extent),
        column_info=dataset.column_info,
        quality_detail=dataset.quality_detail,
        license=record.license,
        source_organization=record.source_organization,
        data_vintage_start=record.temporal_start,
        data_vintage_end=record.temporal_end,
        source_format=dataset.source_format,
        source_filename=dataset.source_filename,
        original_srid=dataset.original_srid,
        current_version=dataset.current_version,
        source_url=dataset.source_url,
        quality_statement=dataset.quality_statement,
        visibility=record.visibility,
        created_by=record.created_by,
        created_by_display=created_by_display,
        created_at=record.created_at,
        updated_at=record.updated_at,
        last_edited_by_display=last_edited.display,
        last_edited_at=last_edited.timestamp,
        collections=collections,
        record_status=record.record_status,
        lineage_summary=record.lineage_summary,
        update_frequency=record.update_frequency,
        usage_constraints=record.usage_constraints,
        access_constraints=record.access_constraints,
        sensitivity_classification=record.sensitivity_classification,
        theme_category=record.theme_category,
        owner_org=record.owner_org,
        published_at=record.published_at,
        updated_by=record.updated_by,
        record_type=record_type,
        raster=raster_metadata,
        stac_assets=stac_assets,
    )


_CATALOG_CACHE_TTL = 60  # seconds


@router.get("/", response_model=DatasetListResponse)
async def list_all_datasets(
    request: Request,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> DatasetListResponse:
    """List datasets with visibility filtering and pagination."""
    user_roles = await get_user_roles(db, user)

    # Cache admin views only (non-admin results vary by user identity)
    is_admin = "admin" in user_roles
    cache_key = f"catalog:datasets:admin:{skip}:{limit}" if is_admin else None

    if cache_key:
        cache = get_cache()
        cached = await cache.get(cache_key)
        if cached is not None:
            return DatasetListResponse(**cached)

    datasets, total = await list_datasets(db, user, user_roles, skip=skip, limit=limit)
    actors_by_id = await _load_actor_identities(
        db,
        [
            actor_id
            for dataset in datasets
            for actor_id in (dataset.record.created_by, dataset.record.updated_by)
        ],
    )

    # Batch-fetch RasterAssets for all raster and VRT datasets in the page
    from app.raster.models import RasterAsset

    raster_ids = [
        d.id
        for d in datasets
        if getattr(d.record, "record_type", None) in ("raster_dataset", "vrt_dataset")
    ]
    raster_assets_by_dataset_id: dict = {}
    if raster_ids:
        ra_result = await db.execute(
            select(RasterAsset).where(RasterAsset.dataset_id.in_(raster_ids))
        )
        for ra in ra_result.scalars().all():
            raster_assets_by_dataset_id[ra.dataset_id] = ra

    # Batch source_count query for VRT datasets
    vrt_ids = [d.id for d in datasets if getattr(d.record, "record_type", None) == "vrt_dataset"]
    source_counts: dict = {}
    if vrt_ids:
        sc_result = await db.execute(
            text("SELECT vrt_dataset_id, COUNT(*) AS cnt FROM catalog.vrt_source_links WHERE vrt_dataset_id = ANY(:ids) GROUP BY vrt_dataset_id"),
            {"ids": [str(v) for v in vrt_ids]},
        )
        for row in sc_result.all():
            source_counts[row.vrt_dataset_id] = row.cnt

    list_base_url = _public_base_url(request)
    response = DatasetListResponse(
        datasets=[
            _dataset_to_response(
                d,
                actors_by_id=actors_by_id,
                raster_asset=raster_assets_by_dataset_id.get(d.id),
                is_admin=is_admin,
                source_count=source_counts.get(str(d.id)),
                base_url=list_base_url,
            )
            for d in datasets
        ],
        total=total,
    )

    if cache_key:
        cache = get_cache()
        await cache.set(
            cache_key, response.model_dump(mode="json"), ttl=_CATALOG_CACHE_TTL
        )

    return response


# ---------------------------------------------------------------------------
# DCAT 3 JSON-LD export endpoints
# ---------------------------------------------------------------------------


@router.get("/dcat/", response_class=JSONResponse)
async def get_dcat_catalog(
    user: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """DCAT 3 JSON-LD catalog feed. Respects dataset visibility."""
    from sqlalchemy.orm import joinedload as _jl

    stmt = (
        select(DatasetModel)
        .join(Record, DatasetModel.record_id == Record.id)
        .options(
            _jl(DatasetModel.record).joinedload(Record.keywords),
            _jl(DatasetModel.record).joinedload(Record.contacts),
            _jl(DatasetModel.record).joinedload(Record.distributions),
        )
    )

    if user is not None:
        user_roles = await get_user_roles(db, user)
    else:
        user_roles = set()

    stmt = apply_visibility_filter(stmt, user, user_roles, Record, DatasetGrant)

    result = await db.execute(stmt)
    datasets = list(result.unique().scalars().all())

    base_url = await get_public_api_url(db)
    catalog = catalog_to_dcat(datasets, base_url)

    return JSONResponse(content=catalog, media_type="application/ld+json")


# ---------------------------------------------------------------------------
# Create empty dataset
# ---------------------------------------------------------------------------


@router.post(
    "/create/", response_model=DatasetResponse, status_code=status.HTTP_201_CREATED
)
async def create_empty_dataset_endpoint(
    body: CreateEmptyDatasetRequest,
    request: Request,
    user: User = Depends(require_permission("edit_metadata")),
    db: AsyncSession = Depends(get_db),
) -> DatasetResponse:
    """Create an empty dataset with user-defined columns.

    Creates a PostGIS table in the data schema and a catalog record.
    """
    try:
        dataset = await create_empty_dataset(db, body, user)
        await db.commit()
        await db.refresh(dataset, ["record"])
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    actors_by_id = await _load_actor_identities(db, [dataset.record.created_by])
    return _dataset_to_response(dataset, actors_by_id=actors_by_id, base_url=_public_base_url(request))


@router.get("/{dataset_id}/dcat/", response_class=JSONResponse)
async def get_dcat_record(
    dataset_id: uuid.UUID,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """DCAT 3 JSON-LD for a single dataset."""
    dataset = await get_dataset(db, dataset_id)
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dataset not found",
        )
    await check_dataset_access(db, dataset, dataset_id, user)

    # Ensure relationships are loaded
    from sqlalchemy.orm import joinedload as _jl

    result = await db.execute(
        select(DatasetModel)
        .options(
            _jl(DatasetModel.record).joinedload(Record.keywords),
            _jl(DatasetModel.record).joinedload(Record.contacts),
            _jl(DatasetModel.record).joinedload(Record.distributions),
        )
        .where(DatasetModel.id == dataset_id)
    )
    dataset = result.unique().scalar_one()

    base_url = await get_public_api_url(db)
    dcat = record_to_dcat(dataset, base_url)

    return JSONResponse(content=dcat, media_type="application/ld+json")


@router.get("/{dataset_id}", response_model=DatasetResponse)
async def get_single_dataset(
    dataset_id: uuid.UUID,
    request: Request,
    user: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
) -> DatasetResponse:
    """Get a single dataset by ID with visibility check."""
    dataset = await get_dataset(db, dataset_id)
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dataset not found",
        )

    # Visibility check
    await check_dataset_access_or_anonymous(db, dataset, dataset_id, user)

    # Log dataset access for authenticated users only
    if user is not None:
        await log_action(
            db,
            user_id=user.id,
            action="dataset.view",
            resource_type="dataset",
            resource_id=dataset_id,
            ip_address=request.client.host if request.client else None,
        )
        await db.commit()

    # Fetch collection memberships for detail view
    colls = await get_dataset_collections(db, dataset_id)
    collections_data = [{"id": str(c.id), "name": c.name} for c in colls]

    actors_by_id = await _load_actor_identities(
        db,
        [dataset.record.created_by, dataset.record.updated_by],
    )

    # Fetch RasterAsset for raster and VRT datasets
    from app.raster.models import RasterAsset

    raster_asset = None
    source_count = None
    if getattr(dataset.record, "record_type", None) in ("raster_dataset", "vrt_dataset"):
        ra_result = await db.execute(
            select(RasterAsset).where(RasterAsset.dataset_id == dataset.id)
        )
        raster_asset = ra_result.scalar_one_or_none()

    if getattr(dataset.record, "record_type", None) == "vrt_dataset":
        sc_result = await db.execute(
            text("SELECT COUNT(*) FROM catalog.vrt_source_links WHERE vrt_dataset_id = :id"),
            {"id": str(dataset.id)},
        )
        source_count = sc_result.scalar()

    # Query DatasetAsset rows for STAC assets
    from app.raster.models import DatasetAsset
    from app.datasets.schemas import StacAsset

    da_result = await db.execute(
        select(DatasetAsset).where(DatasetAsset.dataset_id == dataset.id)
    )
    dataset_asset_rows = da_result.scalars().all()
    stac_assets_dict = {}
    for da in dataset_asset_rows:
        stac_assets_dict[da.key] = StacAsset(
            href=da.href,
            type=da.media_type,
            title=da.title,
            description=da.description,
            roles=da.roles,
            size_bytes=da.size_bytes,
        )

    single_user_roles = await get_user_roles(db, user) if user is not None else set()
    single_is_admin = "admin" in single_user_roles

    return _dataset_to_response(
        dataset,
        collections=collections_data,
        actors_by_id=actors_by_id,
        raster_asset=raster_asset,
        is_admin=single_is_admin,
        source_count=source_count,
        base_url=_public_base_url(request),
        stac_assets=stac_assets_dict or None,
    )


@router.get("/{dataset_id}/quicklook")
async def get_quicklook(
    dataset_id: uuid.UUID,
    size: int = Query(256, description="Quicklook size: 256 or 512"),
    user: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Serve a quicklook PNG image for a dataset."""
    dataset = await get_dataset(db, dataset_id)
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dataset not found",
        )

    await check_dataset_access_or_anonymous(db, dataset, dataset_id, user)

    record_type = getattr(dataset.record, "record_type", None)

    if record_type in ("raster_dataset", "vrt_dataset"):
        from app.raster.models import RasterAsset

        ra_result = await db.execute(
            select(RasterAsset).where(RasterAsset.dataset_id == dataset.id)
        )
        raster_asset = ra_result.scalar_one_or_none()
        if raster_asset is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Raster asset not found",
            )
        uri = raster_asset.quicklook_256_uri if size <= 256 else raster_asset.quicklook_512_uri

    elif record_type == "vector_dataset":
        uri = dataset.quicklook_256_uri
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Quicklook not available for this dataset type",
        )

    if uri is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Quicklook not available",
        )

    storage = get_storage()
    data = await storage.get(uri)
    return Response(
        content=data,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=3600"},
    )


@router.get("/{dataset_id}/vrt-sources/", response_model=VrtSourceListResponse)
async def list_vrt_sources(
    dataset_id: uuid.UUID,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> VrtSourceListResponse:
    """Return ordered list of COG sources for a VRT dataset."""
    dataset = await get_dataset(db, dataset_id)
    if dataset is None or getattr(dataset.record, "record_type", None) != "vrt_dataset":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found")
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


def _advisory_lock_key(dataset_id: uuid.UUID) -> int:
    """Derive a PostgreSQL advisory lock key from a UUID."""
    return dataset_id.int % (2**63)


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
        raise HTTPException(status_code=404, detail="Dataset not found")
    await check_dataset_access(db, dataset, dataset_id, user)

    # Load VRT RasterAsset
    asset_result = await db.execute(
        select(RasterAsset).where(RasterAsset.dataset_id == dataset_id)
    )
    vrt_asset = asset_result.scalar_one_or_none()
    if vrt_asset is None:
        raise HTTPException(status_code=404, detail="VRT asset not found")

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
        text("SELECT COUNT(*) FROM catalog.vrt_source_links WHERE vrt_dataset_id = :id"),
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
            elapsed = (datetime.now(timezone.utc) - active_gen.started_at).total_seconds()
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
        raise HTTPException(status_code=404, detail="Dataset not found")
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
    from app.raster.models import RasterAsset, VrtGeneration

    dataset = await get_dataset(db, dataset_id)
    if dataset is None or getattr(dataset.record, "record_type", None) != "vrt_dataset":
        raise HTTPException(status_code=404, detail="Dataset not found")
    await check_dataset_access(db, dataset, dataset_id, user)

    # Load VRT RasterAsset
    asset_result = await db.execute(
        select(RasterAsset).where(RasterAsset.dataset_id == dataset_id)
    )
    vrt_asset = asset_result.scalar_one_or_none()
    if vrt_asset is None:
        raise HTTPException(status_code=404, detail="VRT asset not found")

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
        text("SELECT COUNT(*) FROM catalog.vrt_source_links WHERE vrt_dataset_id = :id"),
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

    # Update RasterAsset
    vrt_asset.status = "regenerating"
    vrt_asset.current_generation_id = generation.id

    # Create IngestJob
    job = await create_ingest_job(db, "vrt_regenerate", "", user.id)
    job.dataset_id = dataset_id

    await db.commit()

    # Dispatch task
    await regenerate_vrt.defer_async(
        job_id=str(job.id),
        vrt_dataset_id=str(dataset_id),
        triggered_by=str(user.id),
    )

    return VrtMutationResponse(
        job_id=job.id,
        message="VRT regeneration started",
    )


@router.get("/{dataset_id}/related/", response_model=RelatedDatasetsResponse)
async def list_related_datasets(
    dataset_id: uuid.UUID,
    user: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
) -> RelatedDatasetsResponse:
    """Return top-5 datasets similar to this one by embedding cosine similarity."""
    user_roles = await get_user_roles(db, user) if user is not None else set()
    items = await get_related_datasets(db, dataset_id, user, user_roles)
    return RelatedDatasetsResponse(items=items, total=len(items))


@router.get("/{dataset_id}/rows", response_model=DatasetRowsResponse)
async def get_dataset_rows_endpoint(
    request: Request,
    dataset_id: uuid.UUID,
    limit: int = Query(50, ge=1, le=500),
    after: int = Query(0, ge=0),
    user: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
) -> DatasetRowsResponse:
    """Get keyset-paginated rows from a dataset's data table.

    Uses cursor-based pagination: pass ``after`` (gid) to fetch the next page.
    Supports column filtering via query params: ``filter[column_name]=value``.
    """
    # Fetch dataset
    dataset = await get_dataset(db, dataset_id)
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dataset not found",
        )

    # Visibility check
    await check_dataset_access_or_anonymous(db, dataset, dataset_id, user)

    # Extract filter[col]=value params
    filters: dict[str, str] = {}
    for key, value in request.query_params.items():
        if key.startswith("filter[") and key.endswith("]") and value:
            col_name = key[7:-1]
            filters[col_name] = value

    rows, approx_total, columns, next_cursor = await get_dataset_rows(
        db,
        dataset.table_name,
        limit=limit,
        after_gid=after,
        column_info=dataset.column_info,
        filters=filters if filters else None,
    )

    return DatasetRowsResponse(
        rows=rows,
        approximate_total=approx_total,
        columns=columns,
        next_cursor=next_cursor,
    )


@router.get("/{dataset_id}/validate/", response_model=ValidationResultResponse)
async def validate_dataset(
    dataset_id: uuid.UUID,
    user: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
) -> ValidationResultResponse:
    """Get validation status for a dataset. Shows hard errors and soft warnings."""
    result = await db.execute(
        select(DatasetModel)
        .options(joinedload(DatasetModel.record))
        .where(DatasetModel.id == dataset_id)
    )
    dataset = result.scalar_one_or_none()
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dataset not found",
        )
    await check_dataset_access_or_anonymous(db, dataset, dataset_id, user)

    validation = await run_validation(db, dataset.record, dataset)
    quality = await compute_quality_score(
        db, dataset.table_name, dataset.column_info or [], dataset
    )
    return ValidationResultResponse(
        is_valid=validation.is_valid,
        errors=[
            ValidationIssueSchema(field=e.field, message=e.message, severity=e.severity)
            for e in validation.errors
        ],
        warnings=[
            ValidationIssueSchema(field=w.field, message=w.message, severity=w.severity)
            for w in validation.warnings
        ],
        quality_score=quality,
    )


@router.patch("/{dataset_id}", response_model=DatasetResponse)
async def update_dataset_metadata(
    dataset_id: uuid.UUID,
    meta: DatasetMeta,
    request: Request,
    user: User = Depends(require_permission("edit_metadata")),
    db: AsyncSession = Depends(get_db),
) -> DatasetResponse:
    """Update user-editable dataset metadata."""
    try:
        dataset = await update_user_metadata(
            db,
            dataset_id,
            actor_id=user.id,
            title=meta.title,
            summary=meta.summary,
            visibility=meta.visibility,
            license=meta.license,
            source_organization=meta.source_organization,
            data_vintage_start=meta.data_vintage_start,
            data_vintage_end=meta.data_vintage_end,
            lineage_summary=meta.lineage_summary,
            update_frequency=meta.update_frequency,
            usage_constraints=meta.usage_constraints,
            access_constraints=meta.access_constraints,
            sensitivity_classification=meta.sensitivity_classification,
            theme_category=meta.theme_category,
            record_status=meta.record_status,
            owner_org=meta.owner_org,
            quality_statement=meta.quality_statement,
            source_url=meta.source_url,
        )
    except ValueError as e:
        msg = str(e)
        if "not found" in msg.lower():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Dataset not found",
            )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=msg,
        )

    # Log the metadata edit
    await log_action(
        db,
        user_id=user.id,
        action="metadata.edit",
        resource_type="dataset",
        resource_id=dataset_id,
        details=meta.model_dump(exclude_none=True),
        ip_address=request.client.host if request.client else None,
    )
    await db.commit()
    await db.refresh(dataset)
    await db.refresh(dataset.record)

    actors_by_id = await _load_actor_identities(
        db,
        [dataset.record.created_by, dataset.record.updated_by],
    )
    return _dataset_to_response(dataset, actors_by_id=actors_by_id, base_url=_public_base_url(request))


@router.delete("/{dataset_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_dataset_endpoint(
    dataset_id: uuid.UUID,
    body: DatasetDeleteRequest,
    request: Request,
    user: User = Depends(require_permission("edit_metadata")),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Delete a dataset with cascade cleanup. Admin only, requires confirm_title."""
    try:
        table_name = await delete_dataset(db, dataset_id, body.confirm_title)
    except DependentVrtError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": str(exc),
                "dependent_vrts": exc.dependents,
            },
        )
    except ValueError as exc:
        msg = str(exc)
        if "not found" in msg.lower():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=msg,
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=msg,
        )

    await log_action(
        db,
        user_id=user.id,
        action="dataset.delete",
        resource_type="dataset",
        resource_id=dataset_id,
        details={"title": body.confirm_title, "table_name": table_name},
        ip_address=request.client.host if request.client else None,
    )
    await db.commit()

    # Invalidate caches after dataset deletion
    await invalidate_catalog_cache()

    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{dataset_id}/history", response_model=AuditLogListResponse)
async def get_dataset_history(
    dataset_id: uuid.UUID,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    user: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
) -> AuditLogListResponse:
    """Get audit log history for a specific dataset."""
    dataset = await get_dataset(db, dataset_id)
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dataset not found",
        )

    # Visibility check
    await check_dataset_access_or_anonymous(db, dataset, dataset_id, user)

    logs, total = await query_audit_logs(
        db,
        resource_type="dataset",
        resource_id=dataset_id,
        skip=skip,
        limit=limit,
    )

    return AuditLogListResponse(
        logs=[
            AuditLogResponse(
                id=log.id,
                user_id=log.user_id,
                username=log.user.username if log.user else None,
                action=log.action,
                resource_type=log.resource_type,
                resource_id=log.resource_id,
                details=log.details,
                ip_address=log.ip_address,
                created_at=log.created_at,
            )
            for log in logs
        ],
        total=total,
    )


# ---------------------------------------------------------------------------
# Re-upload endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/{dataset_id}/reupload",
    response_model=ReuploadResponse,
    status_code=status.HTTP_201_CREATED,
)
async def reupload_dataset(
    dataset_id: uuid.UUID,
    file: UploadFile = File(...),
    user: User = Depends(require_permission("edit_metadata")),
    db: AsyncSession = Depends(get_db),
) -> ReuploadResponse:
    """Upload a new file to replace the data in an existing dataset."""
    dataset = await get_dataset(db, dataset_id)
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dataset not found",
        )

    try:
        from app.persistent_config import UPLOAD_ALLOWED_EXTENSIONS

        allowed_ext_str = await UPLOAD_ALLOWED_EXTENSIONS.get(db)
        allowed_list = [e.strip() for e in allowed_ext_str.split(",")]
        validate_file_extension(file.filename, allowed_list)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )

    job = await create_ingest_job(db, file.filename, "", user.id)
    job.dataset_id = dataset_id
    job.user_metadata = {"reupload": True, "dataset_id": str(dataset_id)}

    saved_path = await save_upload_file(file, str(job.id))

    # Inline content validation for immediate feedback
    try:
        validate_file_content(str(saved_path), file.filename)
    except ValueError as exc:
        saved_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )

    job.file_path = str(saved_path)
    await db.commit()

    return ReuploadResponse(
        job_id=job.id,
        status="pending",
        message="File uploaded for re-upload preview",
    )


@router.post(
    "/{dataset_id}/reupload/service/preview",
    response_model=ReuploadPreviewResponse,
)
async def reupload_service_preview(
    dataset_id: uuid.UUID,
    request: ReuploadServicePreviewRequest,
    user: User = Depends(require_permission("edit_metadata")),
    db: AsyncSession = Depends(get_db),
) -> ReuploadPreviewResponse:
    """Preview a remote service layer for dataset re-upload."""
    dataset = await get_dataset(db, dataset_id)
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dataset not found",
        )

    try:
        validate_url_for_ssrf(request.url)
    except SSRFError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )

    try:
        gdal_source, layer_arg = build_gdal_source(
            request.service_type,
            request.url,
            request.layer_name,
            request.layer_id,
            token=request.token,
            order_field=request.object_id_field or "OBJECTID",
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )

    try:
        preview_data = await run_service_preview(
            gdal_source,
            layer_arg,
            token=request.token,
        )
    except IngestionError:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to preview remote layer. The service may be unavailable or the layer format is unsupported.",
        )

    diff = compute_schema_diff(
        dataset.column_info or [],
        preview_data["columns"],
        dataset.feature_count,
        preview_data["feature_count"],
    )
    schema_diff = SchemaDiff(**diff)

    job = IngestJob(
        dataset_id=dataset_id,
        source_filename=request.layer_title or request.layer_name,
        source_url=request.url,
        source_layer=request.layer_name,
        created_by=user.id,
        status="pending",
        user_metadata={
            "reupload": True,
            "dataset_id": str(dataset_id),
            "service_type": request.service_type,
            "layer_id": request.layer_id,
            "source_type": "service_url",
            "object_id_field": request.object_id_field,
        },
    )
    db.add(job)
    await db.flush()
    await db.commit()

    return ReuploadPreviewResponse(
        job_id=job.id,
        source_filename=job.source_filename,
        columns=preview_data["columns"],
        crs=preview_data["srid"],
        geometry_type=preview_data["geometry_type"],
        feature_count=preview_data["feature_count"],
        sample_rows=preview_data["sample_rows"],
        layer_name=request.layer_name
        if request.service_type.startswith("ArcGIS")
        else preview_data["layer_name"],
        schema_diff=schema_diff,
    )


@router.post(
    "/{dataset_id}/reupload/{job_id}/preview",
    response_model=ReuploadPreviewResponse,
)
async def reupload_preview(
    dataset_id: uuid.UUID,
    job_id: uuid.UUID,
    user: User = Depends(require_permission("edit_metadata")),
    db: AsyncSession = Depends(get_db),
) -> ReuploadPreviewResponse:
    """Preview the schema diff between old dataset and new upload."""
    dataset = await get_dataset(db, dataset_id)
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dataset not found",
        )

    result = await db.execute(select(IngestJob).where(IngestJob.id == job_id))
    job = result.scalar_one_or_none()
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job not found",
        )

    # Validate job belongs to this dataset
    job_dataset_id = job.dataset_id or (
        job.user_metadata.get("dataset_id") if job.user_metadata else None
    )
    if job_dataset_id is not None and str(job_dataset_id) != str(dataset_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Job does not belong to this dataset",
        )

    if job.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Job already processed",
        )

    # Resolve S3 key to local file for ogrinfo
    file_path = job.file_path
    if file_path and not Path(file_path).exists():
        from app.ingest.service import resolve_file_path

        file_path = await resolve_file_path(file_path, str(job.id))

    info = await run_ogrinfo_preview(file_path)

    diff = compute_schema_diff(
        dataset.column_info or [],
        info["columns"],
        dataset.feature_count,
        info["feature_count"],
    )
    schema_diff = SchemaDiff(**diff)

    return ReuploadPreviewResponse(
        job_id=job.id,
        source_filename=job.source_filename,
        columns=info["columns"],
        crs=info["srid"],
        geometry_type=info["geometry_type"],
        feature_count=info["feature_count"],
        sample_rows=info["sample_rows"],
        layer_name=info["layer_name"],
        schema_diff=schema_diff,
    )


@router.post(
    "/{dataset_id}/reupload/{job_id}/commit",
    response_model=ReuploadCommitResponse,
)
async def reupload_commit(
    dataset_id: uuid.UUID,
    job_id: uuid.UUID,
    request: ReuploadCommitRequest,
    user: User = Depends(require_permission("edit_metadata")),
    db: AsyncSession = Depends(get_db),
) -> ReuploadCommitResponse:
    """Commit a re-upload, queuing the background swap task."""
    dataset = await get_dataset(db, dataset_id)
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dataset not found",
        )

    result = await db.execute(select(IngestJob).where(IngestJob.id == job_id))
    job = result.scalar_one_or_none()
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job not found",
        )

    # Validate job belongs to this dataset
    job_dataset_id = job.dataset_id or (
        job.user_metadata.get("dataset_id") if job.user_metadata else None
    )
    if job_dataset_id is not None and str(job_dataset_id) != str(dataset_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Job does not belong to this dataset",
        )

    if job.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Job already processed",
        )

    # Merge commit request params into user_metadata, preserving existing keys.
    # Keep token request-only (never persisted).
    existing_meta = job.user_metadata or {}
    existing_meta.update(request.model_dump(exclude_none=True, exclude={"token"}))
    job.user_metadata = existing_meta
    await db.commit()

    if job.source_url and not job.file_path:
        await reupload_service.defer_async(
            job_id=str(job.id),
            dataset_id=str(dataset_id),
            source_url=job.source_url,
            source_layer=job.source_layer or "",
            user_id=str(user.id),
            token=request.token,
        )
    else:
        # Route small files to priority queue
        import os

        file_size = 0
        # Only check local files; S3 paths (no leading /) use default queue
        if job.file_path and job.file_path.startswith("/"):
            try:
                if Path(job.file_path).exists():
                    file_size = os.path.getsize(job.file_path)
            except OSError:
                pass  # If we can't stat, use default queue

        if file_size > 0 and file_size <= PRIORITY_QUEUE_THRESHOLD_BYTES:
            await reupload_file.configure(queue="priority").defer_async(
                job_id=str(job.id),
                dataset_id=str(dataset_id),
                file_path=job.file_path,
                user_id=str(user.id),
            )
        else:
            await reupload_file.defer_async(
                job_id=str(job.id),
                dataset_id=str(dataset_id),
                file_path=job.file_path,
                user_id=str(user.id),
            )

    return ReuploadCommitResponse(
        job_id=job.id,
        status="pending",
        message="Re-upload queued",
    )


# ---------------------------------------------------------------------------
# Presigned re-upload endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/{dataset_id}/reupload/presigned",
    response_model=PresignedUploadResponse,
    status_code=status.HTTP_201_CREATED,
)
async def request_presigned_reupload(
    dataset_id: uuid.UUID,
    request: PresignedUploadRequest,
    user: User = Depends(require_permission("edit_metadata")),
    db: AsyncSession = Depends(get_db),
) -> PresignedUploadResponse:
    """Request presigned URL(s) for direct-to-S3 reupload."""
    if settings.storage_provider != "s3":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Presigned uploads only available in S3 mode",
        )

    dataset = await get_dataset(db, dataset_id)
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dataset not found",
        )

    from app.persistent_config import UPLOAD_ALLOWED_EXTENSIONS, UPLOAD_MAX_SIZE_MB

    allowed_ext_str = await UPLOAD_ALLOWED_EXTENSIONS.get(db)
    allowed_list = [e.strip() for e in allowed_ext_str.split(",")]
    validate_file_extension(request.filename, allowed_list)

    # Reject files exceeding configured size limit at request time
    max_size_mb = await UPLOAD_MAX_SIZE_MB.get(db)
    max_size_bytes = max_size_mb * 1024 * 1024
    if request.file_size > max_size_bytes:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"File size ({request.file_size / (1024 * 1024):.1f} MB) exceeds the maximum allowed ({max_size_mb} MB).",
        )

    job = await create_ingest_job(db, request.filename, "", user.id)
    job.dataset_id = dataset_id
    storage = get_storage()
    s3_key = f"staging/{job.id}/{request.filename}"
    threshold = settings.presigned_multipart_threshold_mb * 1024 * 1024

    from app.ingest.router import PART_SIZE

    if request.file_size > threshold:
        upload_id = await asyncio.to_thread(
            storage.initiate_multipart_upload,
            s3_key,
            request.content_type,
        )
        num_parts = math.ceil(request.file_size / PART_SIZE)
        urls = []
        for i in range(1, num_parts + 1):
            url = await asyncio.to_thread(
                storage.generate_presigned_part_url,
                s3_key,
                upload_id,
                i,
            )
            urls.append(url)
        job.user_metadata = {
            "presigned": True,
            "s3_key": s3_key,
            "upload_id": upload_id,
            "multipart": True,
            "reupload": True,
            "dataset_id": str(dataset_id),
        }
        await db.commit()
        return PresignedUploadResponse(
            job_id=job.id,
            urls=urls,
            s3_key=s3_key,
            upload_id=upload_id,
            part_size=PART_SIZE,
        )
    else:
        url = await asyncio.to_thread(
            storage.generate_presigned_put_url,
            s3_key,
            request.content_type,
        )
        job.user_metadata = {
            "presigned": True,
            "s3_key": s3_key,
            "multipart": False,
            "reupload": True,
            "dataset_id": str(dataset_id),
        }
        await db.commit()
        return PresignedUploadResponse(
            job_id=job.id,
            urls=[url],
            s3_key=s3_key,
        )


@router.post(
    "/{dataset_id}/reupload/presigned/{job_id}/complete",
    response_model=UploadResponse,
)
async def complete_presigned_reupload(
    dataset_id: uuid.UUID,
    job_id: uuid.UUID,
    request: PresignedCompleteRequest,
    user: User = Depends(require_permission("edit_metadata")),
    db: AsyncSession = Depends(get_db),
) -> UploadResponse:
    """Notify that direct-to-S3 reupload is complete."""
    dataset = await get_dataset(db, dataset_id)
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dataset not found",
        )

    from app.ingest.service import get_job_or_404

    job = await get_job_or_404(db, job_id, user)
    um = job.user_metadata or {}

    if not um.get("presigned"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Job is not a presigned upload",
        )

    storage = get_storage()
    s3_key = um["s3_key"]

    if um.get("multipart") and request.parts:
        await asyncio.to_thread(
            storage.complete_multipart_upload,
            s3_key,
            um["upload_id"],
            [{"ETag": p.etag, "PartNumber": p.part_number} for p in request.parts],
        )

    if not await storage.exists(s3_key):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File not found in S3 after upload",
        )

    job.file_path = s3_key
    await db.commit()

    return UploadResponse(
        job_id=job.id,
        status="pending",
        message="File uploaded for re-upload preview",
    )


# ---------------------------------------------------------------------------
# Versions endpoint
# ---------------------------------------------------------------------------


@router.get(
    "/{dataset_id}/versions",
    response_model=DatasetVersionListResponse,
)
async def get_dataset_versions_endpoint(
    dataset_id: uuid.UUID,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    user: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
) -> DatasetVersionListResponse:
    """Get paginated version history for a dataset."""
    dataset = await get_dataset(db, dataset_id)
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dataset not found",
        )

    # Visibility check
    await check_dataset_access_or_anonymous(db, dataset, dataset_id, user)

    versions, total = await get_dataset_versions(db, dataset_id, skip=skip, limit=limit)

    return DatasetVersionListResponse(
        versions=[DatasetVersionResponse.model_validate(v) for v in versions],
        total=total,
    )


# ---------------------------------------------------------------------------
# Attribute metadata endpoints
# ---------------------------------------------------------------------------


@router.get("/{dataset_id}/attributes/", response_model=AttributeMetadataListResponse)
async def list_attributes_endpoint(
    dataset_id: uuid.UUID,
    include_removed: bool = Query(False),
    user: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
) -> AttributeMetadataListResponse:
    """List all attribute metadata for a dataset."""
    dataset = await get_dataset(db, dataset_id)
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found"
        )
    await check_dataset_access_or_anonymous(db, dataset, dataset_id, user)
    from app.datasets.service import list_attributes

    attributes = await list_attributes(db, dataset_id, include_removed=include_removed)
    return AttributeMetadataListResponse(
        attributes=[AttributeMetadataResponse.model_validate(a) for a in attributes],
        total=len(attributes),
    )


@router.get(
    "/{dataset_id}/attributes/{attribute_id}/", response_model=AttributeMetadataResponse
)
async def get_attribute_endpoint(
    dataset_id: uuid.UUID,
    attribute_id: uuid.UUID,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> AttributeMetadataResponse:
    """Get a single attribute metadata entry."""
    dataset = await get_dataset(db, dataset_id)
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found"
        )
    await check_dataset_access(db, dataset, dataset_id, user)
    from app.datasets.service import get_attribute

    attr = await get_attribute(db, attribute_id)
    if attr is None or attr.dataset_id != dataset.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Attribute not found"
        )
    return AttributeMetadataResponse.model_validate(attr)


@router.patch(
    "/{dataset_id}/attributes/{attribute_id}/", response_model=AttributeMetadataResponse
)
async def update_attribute_endpoint(
    dataset_id: uuid.UUID,
    attribute_id: uuid.UUID,
    body: AttributeMetadataUpdate,
    user: User = Depends(require_permission("edit_metadata")),
    db: AsyncSession = Depends(get_db),
) -> AttributeMetadataResponse:
    """Update user-editable attribute metadata fields."""
    dataset = await get_dataset(db, dataset_id)
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found"
        )
    await check_dataset_access(db, dataset, dataset_id, user)
    from app.datasets.service import get_attribute as get_attr_svc
    from app.datasets.service import update_attribute

    attr = await get_attr_svc(db, attribute_id)
    if attr is None or attr.dataset_id != dataset.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Attribute not found"
        )
    try:
        # Use exclude_unset (not exclude_none) so explicit null clears the field
        updates = body.model_dump(exclude_unset=True)
        if updates:
            attr = await update_attribute(db, attribute_id, **updates)
            dataset.record.updated_by = user.id
            await log_action(
                db,
                user_id=user.id,
                action="attribute.edit",
                resource_type="dataset",
                resource_id=dataset_id,
                details={
                    "attribute_id": str(attr.id),
                    "field_name": attr.field_name,
                    "changed_fields": sorted(updates.keys()),
                },
            )
            await db.commit()
        await db.refresh(attr)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Attribute not found"
        )
    return AttributeMetadataResponse.model_validate(attr)


@router.post(
    "/{dataset_id}/attributes/{attribute_id}/reset/",
    response_model=AttributeMetadataResponse,
)
async def reset_attribute_endpoint(
    dataset_id: uuid.UUID,
    attribute_id: uuid.UUID,
    user: User = Depends(require_permission("edit_metadata")),
    db: AsyncSession = Depends(get_db),
) -> AttributeMetadataResponse:
    """Reset attribute metadata to auto-populated values, clearing user_modified_fields."""
    dataset = await get_dataset(db, dataset_id)
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found"
        )
    await check_dataset_access(db, dataset, dataset_id, user)
    from app.datasets.service import get_attribute as get_attr_svc
    from app.datasets.service import reset_attribute

    attr = await get_attr_svc(db, attribute_id)
    if attr is None or attr.dataset_id != dataset.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Attribute not found"
        )
    try:
        attr = await reset_attribute(db, attribute_id, dataset.table_name)
        dataset.record.updated_by = user.id
        await log_action(
            db,
            user_id=user.id,
            action="attribute.reset",
            resource_type="dataset",
            resource_id=dataset_id,
            details={
                "attribute_id": str(attr.id),
                "field_name": attr.field_name,
                "changed_fields": [
                    "title",
                    "description",
                    "units",
                    "domain_type",
                    "semantic_role",
                    "example_values",
                    "user_modified_fields",
                ],
            },
        )
        await db.commit()
        await db.refresh(attr)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Attribute not found"
        )
    return AttributeMetadataResponse.model_validate(attr)


# ---------------------------------------------------------------------------
# Column values & stats endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/{dataset_id}/columns/{column_name}/values", response_model=ColumnValuesResponse
)
async def get_column_values(
    dataset_id: uuid.UUID,
    column_name: str,
    limit: int = Query(100, ge=1, le=500),
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> ColumnValuesResponse:
    """Get distinct values for a dataset column (for categorical styling)."""
    from app.datasets.column_stats import get_distinct_values

    dataset = await get_dataset(db, dataset_id)
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dataset not found",
        )

    # Visibility check
    await check_dataset_access(db, dataset, dataset_id, user)

    try:
        values = await get_distinct_values(db, dataset.table_name, column_name, limit)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )

    return ColumnValuesResponse(values=values, count=len(values))


@router.get(
    "/{dataset_id}/columns/{column_name}/stats", response_model=ColumnStatsResponse
)
async def get_column_stats_endpoint(
    dataset_id: uuid.UUID,
    column_name: str,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> ColumnStatsResponse:
    """Get statistics for a numeric dataset column (for graduated styling)."""
    from app.datasets.column_stats import get_column_stats

    dataset = await get_dataset(db, dataset_id)
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dataset not found",
        )

    # Visibility check
    await check_dataset_access(db, dataset, dataset_id, user)

    try:
        stats = await get_column_stats(db, dataset.table_name, column_name)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )

    return ColumnStatsResponse(**stats)


# ---------------------------------------------------------------------------
# Maps containing dataset
# ---------------------------------------------------------------------------


@router.get("/{dataset_id}/maps/")
async def dataset_maps(
    dataset_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User | None = Depends(get_optional_user),
):
    """Return maps that contain this dataset, filtered by caller's RBAC visibility."""
    from app.maps.schemas import MapListResponse
    from app.maps.service import get_maps_for_dataset

    user_id = user.id if user else None
    user_roles = await get_user_roles(db, user) if user else set()

    maps = await get_maps_for_dataset(
        db, dataset_id, user_id=user_id, user_roles=user_roles
    )
    return MapListResponse(maps=maps, total=len(maps))


# ---------------------------------------------------------------------------
# COG download
# ---------------------------------------------------------------------------


@router.get("/{dataset_id}/download/cog")
async def download_cog(
    dataset_id: uuid.UUID,
    request: Request,
    user: User = Depends(require_permission("export")),
    db: AsyncSession = Depends(get_db),
):
    """Download the Cloud-Optimized GeoTIFF for a raster dataset.

    Local storage: streams the COG file with Content-Type image/tiff.
    S3 storage: returns a 302 redirect to a presigned GET URL (1-hour expiry).
    Requires authentication and export permission.
    """
    from slugify import slugify

    from app.raster.models import RasterAsset

    # 1. Fetch dataset
    dataset = await get_dataset(db, dataset_id)
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dataset not found",
        )

    # 2. Visibility check
    await check_dataset_access(db, dataset, dataset_id, user)

    # 3. Verify raster type
    if dataset.record.record_type != "raster_dataset":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Not a raster dataset",
        )

    # 4. Fetch RasterAsset
    ra_result = await db.execute(
        select(RasterAsset).where(RasterAsset.dataset_id == dataset.id)
    )
    raster_asset = ra_result.scalar_one_or_none()
    if raster_asset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Raster asset not found",
        )

    # 5. Build filename
    filename = f"{slugify(dataset.record.title)}.cog.tif"

    # 6. Audit log
    await log_action(
        db,
        user_id=user.id,
        action="dataset.download_cog",
        resource_type="dataset",
        resource_id=dataset_id,
        details={"filename": filename, "storage_backend": raster_asset.storage_backend},
        ip_address=request.client.host if request.client else None,
    )
    await db.commit()

    # 7. Storage-backend branching
    storage = get_storage()

    if raster_asset.storage_backend == "s3":
        url = storage.generate_presigned_get_url(raster_asset.asset_uri, expiration=3600)
        return RedirectResponse(url=url, status_code=302)

    # Local storage: stream bytes
    data = await storage.get(raster_asset.asset_uri)
    return StreamingResponse(
        io.BytesIO(data),
        media_type="image/tiff",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------------------------------------------------------------------------
# Publication status transitions
# ---------------------------------------------------------------------------

ALLOWED_TRANSITIONS = {
    "draft": {"ready"},
    "ready": {"draft", "internal"},
    "internal": {"ready", "published"},
    "published": {"internal"},
}


@router.patch("/{dataset_id}/status")
async def update_publication_status(
    dataset_id: uuid.UUID,
    body: StatusUpdate,
    request: Request,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Transition a dataset's publication status following allowed paths.

    Allowed transitions:
      draft -> ready -> internal -> published (and back one step).
    """
    dataset = await db.execute(
        select(DatasetModel)
        .options(joinedload(DatasetModel.record))
        .where(DatasetModel.id == dataset_id)
    )
    dataset = dataset.unique().scalar_one_or_none()
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")

    current = dataset.record.record_status
    target = body.status
    if target not in ALLOWED_TRANSITIONS.get(current, set()):
        raise HTTPException(
            status_code=422,
            detail=(
                f"Cannot transition from '{current}' to '{target}'. "
                f"Allowed: {ALLOWED_TRANSITIONS.get(current, set())}"
            ),
        )

    dataset.record.record_status = target
    await db.commit()
    await db.refresh(dataset)
    return {"id": str(dataset.id), "record_status": target}


# ---------------------------------------------------------------------------
# Dataset FK relationships
# ---------------------------------------------------------------------------


@router.get("/{dataset_id}/relationships/")
async def list_dataset_relationships(
    dataset_id: uuid.UUID,
    user: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
):
    """List all FK relationships for a dataset."""
    dataset = await get_dataset(db, dataset_id)
    if dataset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found")
    await check_dataset_access_or_anonymous(db, dataset, dataset_id, user)

    from app.datasets.service import list_relationships

    items = await list_relationships(db, dataset.record_id)
    return [DatasetRelationshipResponse(**item) for item in items]


@router.post("/{dataset_id}/relationships/", status_code=201)
async def create_dataset_relationship(
    dataset_id: uuid.UUID,
    body: DatasetRelationshipCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("edit_metadata")),
):
    """Create a new FK relationship. Editor+ required."""
    from app.datasets.service import create_relationship

    # Resolve dataset_id to record_id (FK references catalog.records.id)
    dataset = await get_dataset(db, dataset_id)
    if dataset is None:
        raise HTTPException(status_code=404, detail="Dataset not found")

    rel = await create_relationship(db, dataset.record_id, body)
    await db.commit()
    return DatasetRelationshipResponse.model_validate(rel)


@router.delete("/relationships/{relationship_id}/", status_code=204)
async def delete_dataset_relationship(
    relationship_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("edit_metadata")),
):
    """Delete a FK relationship. Editor+ required."""
    from app.datasets.service import delete_relationship

    try:
        await delete_relationship(db, relationship_id)
        await db.commit()
    except ValueError:
        raise HTTPException(status_code=404, detail="Relationship not found")


@router.get("/{dataset_id}/features/{gid}/related/{relationship_id}/")
async def get_feature_related_records(
    dataset_id: uuid.UUID,
    gid: int,
    relationship_id: uuid.UUID,
    limit: int = Query(50, ge=1, le=500),
    after: int = Query(0, ge=0),
    user: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
):
    """Get related records for a feature via FK relationship."""
    dataset = await get_dataset(db, dataset_id)
    if dataset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found")
    await check_dataset_access_or_anonymous(db, dataset, dataset_id, user)

    from app.datasets.service import get_related_records

    try:
        return await get_related_records(
            db, dataset_id, gid, relationship_id, limit=limit, after=after
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
