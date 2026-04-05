"""Admin API endpoints: user management and catalog stats (admin-only)."""

import asyncio
import hashlib
import logging
import secrets
import uuid
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.schemas import (
    AIStatusResponse,
    AIStatusUpdate,
    AdminApiKeyCreateRequest,
    AdminApiKeyListItem,
    AdminApiKeyListResponse,
    AdminJobListResponse,
    AdminJobResponse,
    AdminUserCreate,
    UserNameItem,
    ApproveRequest,
    BackfillResponse,
    CatalogStatsResponse,
    EmbeddingStatsResponse,
    InfrastructureConfig,
    InfrastructureResponse,
    UserListResponse,
    UserUpdate,
)
from app.admin.service import AdminService
from app.auth.dependencies import get_current_active_user, require_permission
from app.auth.models import ApiKey, User
from app.auth.schemas import ApiKeyCreateResponse, UserResponse
from app.config import settings as app_settings
from app.dependencies import get_db
from app.audit.service import log_action
from app.maps.schemas import AdminShareTokenListResponse, AdminShareTokenResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["Admin"])


def _user_response(user: User) -> UserResponse:
    """Convert a User ORM object to a UserResponse schema."""
    return UserResponse(
        id=user.id,
        username=user.username,
        email=user.email,
        is_active=user.is_active,
        status=user.status,
        last_login_at=user.last_login_at,
        created_at=user.created_at,
        roles=sorted(r.name for r in user.roles),
    )


@router.post(
    "/users/",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("manage_users"))],
)
async def create_user(
    body: AdminUserCreate,
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    """Create a new user with the specified role (admin only)."""
    service = AdminService(db)
    try:
        user = await service.create_user(
            username=body.username,
            password=body.password,
            email=body.email,
            role_name=body.role,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        )
    return _user_response(user)


@router.get(
    "/users/",
    response_model=UserListResponse,
    dependencies=[Depends(require_permission("manage_users"))],
)
async def list_users(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    status_filter: str | None = Query(None, alias="status"),
    search: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
) -> UserListResponse:
    """List all users with pagination and optional status/search filter (admin only)."""
    service = AdminService(db)
    users, total = await service.list_users(
        skip=skip, limit=limit, status=status_filter, search=search
    )
    return UserListResponse(
        users=[_user_response(u) for u in users],
        total=total,
    )


@router.get(
    "/users/names/",
    response_model=list[UserNameItem],
    dependencies=[Depends(require_permission("manage_users"))],
)
async def list_user_names(
    db: AsyncSession = Depends(get_db),
) -> list[UserNameItem]:
    """Return lightweight id+username list for all users (for filter dropdowns)."""
    result = await db.execute(select(User.id, User.username).order_by(User.username))
    return [UserNameItem(id=row.id, username=row.username) for row in result.all()]


@router.get(
    "/users/{user_id}",
    response_model=UserResponse,
    dependencies=[Depends(require_permission("manage_users"))],
)
async def get_user(
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    """Get a specific user by ID (admin only)."""
    service = AdminService(db)
    try:
        user = await service.get_user(user_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    return _user_response(user)


@router.patch(
    "/users/{user_id}",
    response_model=UserResponse,
    dependencies=[Depends(require_permission("manage_users"))],
)
async def update_user(
    user_id: uuid.UUID,
    body: UserUpdate,
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    """Update a user's fields and/or role (admin only)."""
    service = AdminService(db)
    try:
        user = await service.update_user(user_id, body)
    except ValueError as exc:
        detail = str(exc)
        if "not found" in detail.lower():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=detail,
            )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=detail,
        )
    return _user_response(user)


@router.post(
    "/users/{user_id}/deactivate/",
    response_model=UserResponse,
)
async def deactivate_user(
    user_id: uuid.UUID,
    current_user: User = Depends(require_permission("manage_users")),
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    """Deactivate a user (admin only)."""
    service = AdminService(db)
    try:
        user = await service.deactivate_user(user_id, current_user.id)
    except ValueError as exc:
        detail = str(exc)
        if "not found" in detail.lower():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=detail,
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=detail,
        )
    return _user_response(user)


@router.post(
    "/users/{user_id}/approve/",
    response_model=UserResponse,
)
async def approve_user(
    user_id: uuid.UUID,
    body: ApproveRequest,
    current_user: User = Depends(require_permission("manage_users")),
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    """Approve a pending user with the specified role (admin only)."""
    service = AdminService(db)
    try:
        user = await service.approve_user(user_id, body.role)
    except ValueError as exc:
        detail = str(exc)
        if "not found" in detail.lower():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=detail,
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=detail,
        )
    return _user_response(user)


@router.post(
    "/users/{user_id}/reject/",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def reject_user(
    user_id: uuid.UUID,
    current_user: User = Depends(require_permission("manage_users")),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Reject a pending user by hard-deleting them (admin only)."""
    service = AdminService(db)
    try:
        await service.reject_user(user_id)
    except ValueError as exc:
        detail = str(exc)
        if "not found" in detail.lower():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=detail,
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=detail,
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete(
    "/users/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_user(
    user_id: uuid.UUID,
    current_user: User = Depends(require_permission("manage_users")),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Hard-delete a user (admin only). Returns 400 for self-deletion or last-admin."""
    service = AdminService(db)
    try:
        await service.delete_user(user_id, current_user.id)
    except ValueError as exc:
        detail = str(exc)
        if "not found" in detail.lower():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=detail,
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=detail,
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/stats/",
    response_model=CatalogStatsResponse,
)
async def get_catalog_stats(
    user: User = Depends(require_permission("manage_users")),
    db: AsyncSession = Depends(get_db),
) -> CatalogStatsResponse:
    """Return catalog statistics: counts, storage, breakdowns (admin only)."""
    service = AdminService(db)
    return await service.get_catalog_stats()


@router.get(
    "/jobs/",
    response_model=AdminJobListResponse,
    dependencies=[Depends(require_permission("manage_users"))],
)
async def list_admin_jobs(
    status: str | None = Query(None),
    user_id: uuid.UUID | None = Query(None),
    search: str | None = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> AdminJobListResponse:
    """List all ingestion jobs with optional status/user/search filters (admin only)."""
    from app.auth.models import User as UserModel
    from app.jobs.models import IngestJob

    # Build filters
    filters = []
    if status is not None:
        filters.append(IngestJob.status == status)
    if user_id is not None:
        filters.append(IngestJob.created_by == user_id)
    if search is not None:
        filters.append(IngestJob.source_filename.ilike(f"%{search}%"))

    # Count query
    count_stmt = select(func.count()).select_from(IngestJob)
    for f in filters:
        count_stmt = count_stmt.where(f)
    result = await db.execute(count_stmt)
    total = result.scalar_one()

    # List query with username via outerjoin
    list_stmt = (
        select(IngestJob, UserModel.username)
        .outerjoin(UserModel, IngestJob.created_by == UserModel.id)
        .order_by(IngestJob.created_at.desc())
    )
    for f in filters:
        list_stmt = list_stmt.where(f)
    list_stmt = list_stmt.offset(skip).limit(limit)
    result = await db.execute(list_stmt)
    rows = result.all()

    jobs = [
        AdminJobResponse(
            id=job.id,
            status=job.status,
            source_filename=job.source_filename,
            dataset_id=job.dataset_id,
            error_message=job.error_message,
            user_metadata=job.user_metadata,
            created_by=job.created_by,
            username=username,
            started_at=job.started_at,
            completed_at=job.completed_at,
            created_at=job.created_at,
        )
        for job, username in rows
    ]

    return AdminJobListResponse(jobs=jobs, total=total)


# ---------------------------------------------------------------------------
# API Key management endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/api-keys/",
    response_model=ApiKeyCreateResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("manage_users"))],
)
async def create_api_key(
    body: AdminApiKeyCreateRequest,
    db: AsyncSession = Depends(get_db),
) -> ApiKeyCreateResponse:
    """Create an API key for a user (admin only).

    The raw key is returned only in this response and cannot be retrieved again.
    """
    raw_key = secrets.token_urlsafe(32)
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()

    api_key = ApiKey(
        user_id=body.user_id,
        key_hash=key_hash,
        name=body.name,
    )
    db.add(api_key)
    await db.commit()
    await db.refresh(api_key)

    return ApiKeyCreateResponse(
        id=api_key.id,
        key=raw_key,
        name=api_key.name,
        created_at=api_key.created_at,
    )


@router.get(
    "/api-keys/",
    response_model=AdminApiKeyListResponse,
    dependencies=[Depends(require_permission("manage_users"))],
)
async def list_api_keys(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    user_id: uuid.UUID | None = Query(None, description="Filter by user ID"),
    db: AsyncSession = Depends(get_db),
) -> AdminApiKeyListResponse:
    """List all API keys (admin only). Never returns the raw key."""
    stmt = select(ApiKey)
    if user_id is not None:
        stmt = stmt.where(ApiKey.user_id == user_id)
    total = (
        await db.execute(select(func.count()).select_from(stmt.subquery()))
    ).scalar_one()
    result = await db.execute(stmt.offset(skip).limit(limit))
    keys = result.scalars().all()
    return AdminApiKeyListResponse(
        items=[
            AdminApiKeyListItem(
                id=k.id,
                user_id=k.user_id,
                name=k.name,
                is_active=k.is_active,
                created_at=k.created_at,
                last_used_at=k.last_used_at,
            )
            for k in keys
        ],
        total=total,
    )


# ---------------------------------------------------------------------------
# AI Status endpoints
# ---------------------------------------------------------------------------


def _ai_status(
    enabled: bool,
    semantic_search_enabled: bool = False,
    has_embeddings: bool = False,
) -> AIStatusResponse:
    """Build AIStatusResponse from current env config + DB toggle."""
    if app_settings.anthropic_api_key:
        provider = "anthropic"
        model = app_settings.llm_model
    elif app_settings.openai_api_key:
        provider = "openai"
        model = app_settings.openai_model
    else:
        provider = None
        model = None

    configured = bool(app_settings.anthropic_api_key or app_settings.openai_api_key)
    return AIStatusResponse(
        provider=provider,
        model=model,
        enabled=enabled,
        configured=configured,
        semantic_search_enabled=semantic_search_enabled,
        has_embeddings=has_embeddings,
    )


@router.get(
    "/ai-status/",
    response_model=AIStatusResponse,
)
async def get_ai_status(
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> AIStatusResponse:
    """Return AI provider status and runtime toggle (any authenticated user)."""
    from app.persistent_config import AI_ENABLED, SEMANTIC_SEARCH_ENABLED

    from app.embeddings.helpers import has_embeddings

    enabled = await AI_ENABLED.get(db)
    semantic = await SEMANTIC_SEARCH_ENABLED.get(db)
    has_embeds = await has_embeddings(db)
    return _ai_status(
        enabled, semantic_search_enabled=semantic, has_embeddings=has_embeds
    )


@router.patch(
    "/ai-status/",
    response_model=AIStatusResponse,
)
async def update_ai_status(
    body: AIStatusUpdate,
    user: User = Depends(require_permission("manage_users")),
    db: AsyncSession = Depends(get_db),
) -> AIStatusResponse:
    """Toggle AI features on/off at runtime (admin only)."""
    from app.embeddings.helpers import has_embeddings
    from app.persistent_config import AI_ENABLED, SEMANTIC_SEARCH_ENABLED

    await AI_ENABLED.set(db, body.enabled, user_id=user.id)
    semantic = await SEMANTIC_SEARCH_ENABLED.get(db)
    has_embeds = await has_embeddings(db)
    return _ai_status(
        body.enabled, semantic_search_enabled=semantic, has_embeddings=has_embeds
    )


@router.get(
    "/embedding-stats/",
    response_model=EmbeddingStatsResponse,
    dependencies=[Depends(require_permission("manage_users"))],
)
async def get_embedding_stats(
    db: AsyncSession = Depends(get_db),
) -> EmbeddingStatsResponse:
    """Return embedding coverage statistics (admin only)."""
    total_result = await db.execute(text("SELECT COUNT(*) FROM catalog.records"))
    total_records = total_result.scalar_one()

    embedded_result = await db.execute(
        text("SELECT COUNT(DISTINCT record_id) FROM catalog.record_embeddings")
    )
    embedded_records = embedded_result.scalar_one()

    missing_records = total_records - embedded_records
    coverage_percent = (
        (embedded_records / total_records * 100) if total_records > 0 else 0.0
    )

    return EmbeddingStatsResponse(
        total_records=total_records,
        embedded_records=embedded_records,
        missing_records=missing_records,
        coverage_percent=round(coverage_percent, 1),
    )


@router.post(
    "/backfill-embeddings/",
    response_model=BackfillResponse,
    dependencies=[Depends(require_permission("manage_users"))],
)
async def trigger_backfill(
    db: AsyncSession = Depends(get_db),
    force: bool = False,
) -> BackfillResponse:
    """Trigger embedding generation for records (admin only).

    Pass ?force=true to delete all existing embeddings and regenerate from
    scratch (required after changing the embedding model or dimensions).
    """
    from app.embeddings.backfill import backfill_embeddings

    result = await backfill_embeddings(db, force=force)
    return BackfillResponse(**result)


@router.delete(
    "/api-keys/{key_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_permission("manage_users"))],
)
async def revoke_api_key(
    key_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Revoke (soft-delete) an API key (admin only)."""
    result = await db.execute(select(ApiKey).where(ApiKey.id == key_id))
    api_key = result.scalar_one_or_none()
    if api_key is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="API key not found",
        )
    api_key.is_active = False
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Infrastructure endpoint
# ---------------------------------------------------------------------------


@router.get(
    "/infrastructure/",
    response_model=InfrastructureResponse,
    dependencies=[Depends(require_permission("manage_users"))],
)
async def get_infrastructure(
    db: AsyncSession = Depends(get_db),
) -> InfrastructureResponse:
    """Return infrastructure configuration, live health status, and OIDC provider connectivity."""
    from app.health.service import check_health, check_oidc_health

    health, oidc_health = await asyncio.gather(
        check_health(),
        check_oidc_health(db),
    )

    config = InfrastructureConfig(
        storage_provider=app_settings.storage_provider,
        cache_provider="redis" if app_settings.redis_url else "memory",
        database_type="external"
        if app_settings.database_url_override
        else "docker-compose",
        database_pooler="external"
        if app_settings.db_use_external_pooler
        else "internal",
        tile_cache="cdn",
        tile_cache_ttl=app_settings.tile_cache_ttl,
        cdn_configured=bool(app_settings.cdn_base_url),
    )

    return InfrastructureResponse(
        config=config,
        health=health["providers"],
        oidc_providers=oidc_health,
    )


# ---------------------------------------------------------------------------
# Share token management endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/share-tokens/",
    response_model=AdminShareTokenListResponse,
    dependencies=[Depends(require_permission("manage_users"))],
)
async def list_share_tokens_endpoint(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    search: str | None = Query(None, max_length=200),
    status: str | None = Query(None, pattern="^(active|expired|revoked)$"),
    db: AsyncSession = Depends(get_db),
) -> AdminShareTokenListResponse:
    """List all share tokens with map info (admin only)."""
    from app.maps.service import list_share_tokens

    tokens, total = await list_share_tokens(
        db, skip, limit, search=search, status_filter=status
    )
    return AdminShareTokenListResponse(
        tokens=[AdminShareTokenResponse(**t) for t in tokens],
        total=total,
    )


@router.delete(
    "/share-tokens/{token_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_permission("manage_users"))],
)
async def admin_revoke_share_token(
    token_id: uuid.UUID,
    current_user: User = Depends(require_permission("manage_users")),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Revoke (soft-delete) a share token and cascade to its embed tokens (admin only)."""
    from app.embed_tokens.models import EmbedToken
    from app.embed_tokens.service import bulk_revoke_embed_tokens
    from app.maps.service import revoke_share_token

    token_obj = await revoke_share_token(db, token_id)
    if token_obj is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Share token not found",
        )

    # Cascade: revoke all active embed tokens for this map
    result = await db.execute(
        select(EmbedToken.id).where(
            EmbedToken.map_id == token_obj.map_id,
            EmbedToken.is_active.is_(True),
        )
    )
    embed_ids = [row[0] for row in result.all()]
    if embed_ids:
        await bulk_revoke_embed_tokens(db, embed_ids)

    await log_action(
        db,
        user_id=current_user.id,
        action="map.admin_share_revoke",
        resource_type="map_share_token",
        resource_id=token_obj.id,
        details={
            "map_id": str(token_obj.map_id),
            "cascade_embed_count": len(embed_ids),
        },
    )

    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
