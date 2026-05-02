"""Dataset export endpoints: DCAT JSON-LD catalog and COG download."""

import io
import uuid

import jwt
import structlog
from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Request,
    Response,
    status,
)
from fastapi.responses import JSONResponse, RedirectResponse, StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.service import AuditEvent, audit_emit
from app.core.identity import Identity
from app.modules.auth.dependencies import (
    get_optional_user,
)
from app.modules.auth.models import User
from app.core.config import settings
from app.modules.catalog.authorization import (
    apply_visibility_filter,
    check_dataset_access,
    check_dataset_access_or_anonymous,
    get_user_roles,
)
from app.standards.dcat.service import catalog_to_dcat, record_to_dcat
from app.modules.catalog.datasets.domain.models import (
    Dataset as DatasetModel,
    DatasetGrant,
    Record,
)
from app.modules.catalog.datasets.domain.service import get_dataset
from app.core.dependencies import get_db
from app.processing.export.service import safe_content_disposition
from app.core.public_urls import get_public_api_url
from app.platform.storage import get_storage
from app.standards.ogc.errors import ERROR_RESPONSES_PUBLIC

logger = structlog.get_logger()

router = APIRouter(
    prefix="/datasets", tags=["Datasets - Export"], responses=ERROR_RESPONSES_PUBLIC
)


# ---------------------------------------------------------------------------
# DCAT 3 JSON-LD export endpoints
# ---------------------------------------------------------------------------


@router.get("/dcat/", response_class=JSONResponse)
async def get_dcat_catalog(
    request: Request,
    user: Identity | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """DCAT 3 JSON-LD catalog feed. Respects dataset visibility."""
    from sqlalchemy.orm import joinedload as _jl, selectinload as _sl

    stmt = (
        select(DatasetModel)
        .join(Record, DatasetModel.record_id == Record.id)
        .options(
            _jl(DatasetModel.record).options(
                _sl(Record.keywords),
                _sl(Record.contacts),
                _sl(Record.distributions),
            ),
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

    from app.standards.ogc.utils import parse_accept_language

    lang = parse_accept_language(request)
    return JSONResponse(
        content=catalog,
        media_type="application/ld+json",
        headers={"Content-Language": lang},
    )


@router.get("/{dataset_id}/dcat/", response_class=JSONResponse)
async def get_dcat_record(
    dataset_id: uuid.UUID,
    request: Request,
    user: Identity | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """DCAT 3 JSON-LD for a single dataset."""
    dataset = await get_dataset(db, dataset_id)
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dataset not found",
        )
    await check_dataset_access_or_anonymous(db, dataset, dataset_id, user)

    # Ensure relationships are loaded
    from sqlalchemy.orm import joinedload as _jl, selectinload as _sl

    result = await db.execute(
        select(DatasetModel)
        .options(
            _jl(DatasetModel.record).options(
                _sl(Record.keywords),
                _sl(Record.contacts),
                _sl(Record.distributions),
            ),
        )
        .where(DatasetModel.id == dataset_id)
    )
    dataset = result.unique().scalar_one()

    base_url = await get_public_api_url(db)
    dcat = record_to_dcat(dataset, base_url)

    from app.standards.ogc.utils import parse_accept_language

    lang = parse_accept_language(request)
    return JSONResponse(
        content=dcat,
        media_type="application/ld+json",
        headers={"Content-Language": lang},
    )


# ---------------------------------------------------------------------------
# COG download
# ---------------------------------------------------------------------------


async def _resolve_download_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: Identity | None = Depends(get_optional_user),
) -> User:
    """Resolve user for download endpoints.

    Accepts standard auth (header JWT, API key) plus a `token` query
    parameter carrying a JWT — needed for browser-initiated downloads
    where fetch+blob would load the entire file into memory.
    """
    if user is not None:
        return user

    # Fallback: JWT in ?token= query param (browser <a href> downloads)
    qt = request.query_params.get("token")
    if qt:
        try:
            payload = jwt.decode(
                qt, settings.jwt_secret_key.get_secret_value(), algorithms=["HS256"]
            )
            user_id = payload.get("sub")
            if user_id:
                result = await db.execute(
                    select(User).where(User.id == uuid.UUID(user_id))
                )
                found = result.scalar_one_or_none()
                if found and found.is_active and found.status == "active":
                    return found
        except (jwt.PyJWTError, ValueError):
            pass

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required",
    )


@router.get("/{dataset_id}/download/cog", response_class=Response)
async def download_cog(
    dataset_id: uuid.UUID,
    request: Request,
    user: Identity = Depends(_resolve_download_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Download the Cloud-Optimized GeoTIFF for a raster dataset.

    Local storage: streams the COG file with Content-Type image/tiff.
    S3 storage: returns a 302 redirect to a presigned GET URL (1-hour expiry).
    Accepts standard auth or ?token= JWT query parameter for browser downloads.
    """
    from slugify import slugify

    from app.modules.auth.permissions import get_effective_permissions
    from app.processing.raster.models import RasterAsset

    # 0. Verify export permission
    user_roles = await get_user_roles(db, user)
    matrix = await get_effective_permissions(db)
    if not any(matrix.get(role, {}).get("export", False) for role in user_roles):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Missing permission: export",
        )

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
    await audit_emit(
        db,
        AuditEvent(
            user_id=user.id,
            action="dataset.download_cog",
            resource_type="dataset",
            resource_id=dataset_id,
            details={
                "filename": filename,
                "storage_backend": raster_asset.storage_backend,
            },
            ip_address=request.client.host if request.client else None,
        ),
    )
    await db.commit()

    # 7. Storage-backend branching
    storage = get_storage()

    if raster_asset.storage_backend == "remote":
        # STAC import: asset_uri is the original remote COG URL — redirect
        return RedirectResponse(url=raster_asset.asset_uri, status_code=302)

    if raster_asset.storage_backend == "s3":
        url = storage.generate_presigned_get_url(
            raster_asset.asset_uri, expiration=3600
        )
        return RedirectResponse(url=url, status_code=302)

    # Local storage: stream bytes
    try:
        data = await storage.get(raster_asset.asset_uri)
    except FileNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="COG file not found"
        )
    except Exception:
        logger.exception("cog_storage_error", dataset_id=str(dataset_id))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="COG download temporarily unavailable",
        )
    return StreamingResponse(
        io.BytesIO(data),
        media_type="image/tiff",
        headers={"Content-Disposition": safe_content_disposition(filename)},
    )
