"""Dataset export endpoints: DCAT JSON-LD catalog and COG download."""

import io
import uuid

import jwt
from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Request,
    status,
)
from fastapi.responses import JSONResponse, RedirectResponse, StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import log_action
from app.auth.dependencies import (
    get_current_active_user,
    get_optional_user,
)
from app.auth.models import Role, User, UserRole
from app.config import settings
from app.auth.visibility import (
    apply_visibility_filter,
    check_dataset_access,
    get_user_roles,
)
from app.dcat.service import catalog_to_dcat, record_to_dcat
from app.datasets.models import Dataset as DatasetModel, DatasetGrant, Record
from app.datasets.service import get_dataset
from app.dependencies import get_db
from app.export.service import safe_content_disposition
from app.public_urls import get_public_api_url
from app.storage import get_storage

router = APIRouter(prefix="/datasets", tags=["Datasets - Export"])


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


# ---------------------------------------------------------------------------
# COG download
# ---------------------------------------------------------------------------


async def _resolve_download_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User | None = Depends(get_optional_user),
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
            payload = jwt.decode(qt, settings.jwt_secret_key, algorithms=["HS256"])
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


@router.get("/{dataset_id}/download/cog")
async def download_cog(
    dataset_id: uuid.UUID,
    request: Request,
    user: User = Depends(_resolve_download_user),
    db: AsyncSession = Depends(get_db),
):
    """Download the Cloud-Optimized GeoTIFF for a raster dataset.

    Local storage: streams the COG file with Content-Type image/tiff.
    S3 storage: returns a 302 redirect to a presigned GET URL (1-hour expiry).
    Accepts standard auth or ?token= JWT query parameter for browser downloads.
    """
    from slugify import slugify

    from app.auth.permissions import get_effective_permissions
    from app.raster.models import RasterAsset

    # 0. Verify export permission
    role_result = await db.execute(
        select(Role.name)
        .join(UserRole, Role.id == UserRole.role_id)
        .where(UserRole.user_id == user.id)
    )
    user_roles = {row[0] for row in role_result.all()}
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
        url = storage.generate_presigned_get_url(
            raster_asset.asset_uri, expiration=3600
        )
        return RedirectResponse(url=url, status_code=302)

    # Local storage: stream bytes
    data = await storage.get(raster_asset.asset_uri)
    return StreamingResponse(
        io.BytesIO(data),
        media_type="image/tiff",
        headers={"Content-Disposition": safe_content_disposition(filename)},
    )
