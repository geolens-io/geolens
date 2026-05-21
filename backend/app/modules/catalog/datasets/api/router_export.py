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
from app.core.public_urls import get_public_api_url
from app.platform.extensions import get_catalog_port
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
) -> Identity | None:
    """Resolve user for download endpoints.

    Accepts standard auth (header JWT, API key) plus a ``token`` query
    parameter — but the query-param token MUST be a download-scoped JWT
    (``typ='download'``, ``scope='dataset:{dataset_id}'``) with ≤2-minute
    TTL, not a session JWT.

    SEC-04 / M-66: a session JWT in a URL is leak-prone (browser history,
    server logs, referer headers). Restricting query-param auth to
    download-scoped tokens bounds damage if the URL is exposed. The
    Authorization header path keeps accepting full session JWTs unchanged.

    KNOWN-01 (Phase 1071): returns ``Identity | None`` rather than ``User``.
    The mint endpoint at ``POST /auth/download-token/{id}`` issues a no-sub
    download token for anonymous callers on public datasets. A VALID no-sub
    token is a valid auth signal — the typ/scope/exp checks already gate
    the request — so we return ``None`` instead of raising 401. The
    downstream consumer (``download_cog``) is responsible for enforcing
    public visibility when user is None.

    401 is reserved for: no auth signal at all (no header AND no token),
    invalid token bytes, wrong typ, wrong scope, expired token, or a
    sub-bearing token whose user no longer exists / is inactive.
    """
    if user is not None:
        return user

    # Fallback: download-scoped JWT in ?token= query param (browser <a href> downloads)
    qt = request.query_params.get("token")
    if qt:
        try:
            payload = jwt.decode(
                qt, settings.jwt_secret_key.get_secret_value(), algorithms=["HS256"]
            )
        except jwt.PyJWTError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired download token",
            )

        # Per SEC-04: enforce typ='download' on the query-param lane.
        if payload.get("typ") != "download":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=(
                    "Query-param ?token= requires a download-scoped JWT "
                    "(typ='download'); use Authorization header for session tokens"
                ),
            )

        # Scope check: token MUST be bound to the dataset_id in the URL.
        expected_scope = f"dataset:{request.path_params.get('dataset_id', '')}"
        if payload.get("scope") != expected_scope:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Download token scope does not match this dataset",
            )

        user_id = payload.get("sub")
        if user_id:
            # Sub-bearing authenticated download token: look up the user.
            # CR-02 (Phase 1071 review): narrow the except to only guard the
            # uuid.UUID() conversion, not the db.execute() call. A ValueError
            # from SQLAlchemy (ORM-contract violation) should bubble up rather
            # than being silently swallowed by a broad except ValueError: pass.
            try:
                user_uuid = uuid.UUID(user_id)
            except ValueError:
                pass  # malformed sub claim — fall through to 401
            else:
                result = await db.execute(select(User).where(User.id == user_uuid))
                found = result.scalar_one_or_none()
                if found and found.is_active and found.status == "active":
                    return found
            # Sub-bearing token whose user disappeared or is inactive — 401
            # (fall through to the unconditional 401 below).
        else:
            # KNOWN-01: no-sub anonymous download token. Token is valid
            # (typ/scope/exp all passed); return None and let download_cog
            # enforce public-visibility as defense-in-depth.
            return None

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required",
    )


@router.get("/{dataset_id}/download/cog", response_class=Response)
async def download_cog(
    dataset_id: uuid.UUID,
    request: Request,
    user: Identity | None = Depends(_resolve_download_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Download the Cloud-Optimized GeoTIFF for a raster dataset.

    Local storage: streams the COG file with Content-Type image/tiff.
    S3 storage: returns a 302 redirect to a presigned GET URL (1-hour expiry).
    Accepts standard auth or ?token= JWT query parameter for browser downloads.

    KNOWN-01 (Phase 1071): ``user`` may be None when a no-sub anonymous
    download token (issued by POST /auth/download-token/{id} for a public
    dataset) is presented on ``?token=``. The function branches on
    user-None to enforce public visibility and emit the audit row with
    user_id=NULL.
    """
    from slugify import slugify

    from app.modules.auth.permissions import get_effective_permissions

    # 1. Fetch dataset FIRST so we can branch visibility/permission on user-None.
    dataset = await get_dataset(db, dataset_id)
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dataset not found",
        )

    # 2. Visibility + permission check (branches on authenticated vs anonymous).
    if user is None:
        # Anonymous download via mint-issued no-sub token. The mint endpoint at
        # POST /auth/download-token/{id} already enforced
        # check_dataset_access_or_anonymous(); the token's typ/scope/exp checks
        # in _resolve_download_user are the auth gate. Still require public
        # visibility here as defense-in-depth (a tampered/replayed token
        # cannot grant access to a private dataset).
        await check_dataset_access_or_anonymous(db, dataset, dataset_id, user)
        if dataset.record.visibility != "public":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Anonymous download requires public dataset",
            )
    else:
        # Authenticated path: full RBAC visibility check + export permission.
        await check_dataset_access(db, dataset, dataset_id, user)
        user_roles = await get_user_roles(db, user)
        matrix = await get_effective_permissions(db)
        if not any(matrix.get(role, {}).get("export", False) for role in user_roles):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Missing permission: export",
            )

    # 3. Verify raster type
    if dataset.record.record_type != "raster_dataset":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Not a raster dataset",
        )

    # 4. Fetch RasterAsset
    raster_asset = await get_catalog_port().get_raster_asset(db, dataset.id)
    if raster_asset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Raster asset not found",
        )

    # 5. Build filename
    filename = f"{slugify(dataset.record.title)}.cog.tif"

    # 6. Audit log. user_id may be None for anonymous downloads (KNOWN-01).
    # The audit_logs.user_id column is nullable; AuditEvent.user_id is typed
    # uuid.UUID | None to match.
    await audit_emit(
        db,
        AuditEvent(
            user_id=user.id if user is not None else None,
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
        # STAC import: asset_uri is the original remote COG URL — redirect.
        # SEC-06 / M-68: DNS records can change between import time (when
        # validate_url_for_ssrf was last run) and now. Re-run the SSRF check
        # immediately before redirecting to defeat DNS-rebinding TOCTOU.
        # If the hostname now resolves to a private IP (cloud metadata,
        # internal network), refuse the redirect with 403.
        from app.modules.catalog.sources.security import (
            SSRFError,
            validate_url_for_ssrf,
        )

        try:
            await validate_url_for_ssrf(raster_asset.asset_uri)
        except SSRFError as exc:
            logger.warning(
                "cog_remote_redirect_blocked_by_ssrf",
                dataset_id=str(dataset_id),
                asset_uri=raster_asset.asset_uri,
                reason=str(exc),
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Remote COG URL failed SSRF re-validation",
            )

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
    except Exception:  # broad: storage backend (S3/MinIO/local) can throw varied SDK/I/O errors; map to 503
        logger.exception("cog_storage_error", dataset_id=str(dataset_id))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="COG download temporarily unavailable",
        )
    return StreamingResponse(
        io.BytesIO(data),
        media_type="image/tiff",
        headers={
            "Content-Disposition": get_catalog_port().safe_content_disposition(filename)
        },
    )
