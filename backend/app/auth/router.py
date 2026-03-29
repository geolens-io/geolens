"""Auth API endpoints: login, register, me, and self-service API keys."""

import hashlib
import secrets
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.security import OAuth2PasswordRequestForm
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_active_user
from app.auth.models import ApiKey, User
from app.auth.providers import AuthenticationError
from app.auth.providers.local import LocalAuthProvider
from app.auth.schemas import (
    ApiKeyCreateRequest,
    ApiKeyCreateResponse,
    ApiKeyListItem,
    ApiKeyListResponse,
    ConfigResponse,
    PermissionsResponse,
    RefreshRequest,
    RegisterResponse,
    TokenResponse,
    UserCreate,
    UserResponse,
)
from app.auth.service import AuthService
from app.dependencies import get_db
from app.persistent_config import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    REFRESH_TOKEN_EXPIRE_DAYS,
    REGISTRATION_ENABLED,
    get_cached_global_rate_limit,
    get_cached_login_rate_limit,
)

router = APIRouter(prefix="/auth", tags=["Auth"])


def _global_rate_limit(_request: Request | None = None) -> str:
    return f"{get_cached_global_rate_limit()}/second"


limiter = Limiter(key_func=get_remote_address, default_limits=[_global_rate_limit])


def _login_rate_limit(_request: Request | None = None) -> str:
    return f"{get_cached_login_rate_limit()}/minute"


@router.post("/login/", response_model=TokenResponse)
@limiter.limit(_login_rate_limit)
async def login(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    """Authenticate with username and password, receive a JWT token."""
    provider = LocalAuthProvider(db)
    try:
        identity = await provider.authenticate(
            username=form_data.username, password=form_data.password
        )
    except AuthenticationError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Check user status before issuing token
    result = await db.execute(select(User).where(User.id == identity.user_id))
    user = result.scalar_one_or_none()
    if user is not None:
        if user.status == "pending":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Your account is awaiting approval",
            )
        if user.status != "active" or not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Account not active",
            )

    # Record login timestamp
    user.last_login_at = func.now()

    # Read token lifetimes from PersistentConfig (hot-reloadable)
    expire_minutes = await ACCESS_TOKEN_EXPIRE_MINUTES.get(db)
    expire_days = await REFRESH_TOKEN_EXPIRE_DAYS.get(db)

    service = AuthService(db)
    token = service.create_access_token(identity, expire_minutes=expire_minutes)
    refresh_token = service.create_refresh_token(user.id, expire_days=expire_days)
    await db.commit()
    return TokenResponse(
        access_token=token,
        refresh_token=refresh_token,
        expires_in=expire_minutes * 60,
    )


@router.post("/refresh/", response_model=TokenResponse)
async def refresh(
    body: RefreshRequest,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    """Exchange a valid refresh token for a new access + refresh token pair."""
    # Read token lifetimes from PersistentConfig (hot-reloadable)
    expire_minutes = await ACCESS_TOKEN_EXPIRE_MINUTES.get(db)
    expire_days = await REFRESH_TOKEN_EXPIRE_DAYS.get(db)

    service = AuthService(db)
    try:
        access_token, refresh_token = await service.rotate_refresh_token(
            body.refresh_token,
            expire_minutes=expire_minutes,
            expire_days=expire_days,
        )
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=expire_minutes * 60,
    )


@router.post(
    "/register/", response_model=RegisterResponse, status_code=status.HTTP_201_CREATED
)
async def register(
    body: UserCreate,
    db: AsyncSession = Depends(get_db),
) -> RegisterResponse:
    """Register a new user. Account requires admin approval before login."""
    reg_enabled = await REGISTRATION_ENABLED.get(db)
    if not reg_enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Registration is disabled",
        )

    service = AuthService(db)
    try:
        await service.register_user(
            username=body.username,
            password=body.password,
            email=body.email,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        )

    return RegisterResponse(
        message="Registration submitted. Your account is awaiting admin approval."
    )


@router.get("/config/", response_model=ConfigResponse)
async def config(
    db: AsyncSession = Depends(get_db),
) -> ConfigResponse:
    """Return public auth configuration (no authentication required)."""
    reg_enabled = await REGISTRATION_ENABLED.get(db)
    return ConfigResponse(registration_enabled=reg_enabled)


@router.get("/me/", response_model=UserResponse)
async def me(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    """Return the currently authenticated user's profile and roles."""
    service = AuthService(db)
    roles = await service.get_user_roles(current_user.id)
    return UserResponse(
        id=current_user.id,
        username=current_user.username,
        email=current_user.email,
        is_active=current_user.is_active,
        status=current_user.status,
        last_login_at=current_user.last_login_at,
        created_at=current_user.created_at,
        roles=sorted(roles),
    )


@router.get("/me/permissions/", response_model=PermissionsResponse)
async def me_permissions(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> PermissionsResponse:
    """Return the effective permissions for the currently authenticated user."""
    from app.auth.permissions import ALL_CAPABILITIES, get_effective_permissions

    service = AuthService(db)
    user_roles = await service.get_user_roles(current_user.id)
    matrix = await get_effective_permissions(db)

    # Merge: user has capability if ANY of their roles grants it
    effective: dict[str, bool] = {}
    for cap in ALL_CAPABILITIES:
        effective[cap] = any(
            matrix.get(role, {}).get(cap, False) for role in user_roles
        )

    return PermissionsResponse(permissions=effective)


# ---------------------------------------------------------------------------
# Self-service API key management
# ---------------------------------------------------------------------------


@router.get("/api-keys/", response_model=ApiKeyListResponse)
async def list_my_api_keys(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> ApiKeyListResponse:
    """List the current user's API keys."""
    base_stmt = select(ApiKey).where(ApiKey.user_id == current_user.id)
    total = (
        await db.execute(select(func.count()).select_from(base_stmt.subquery()))
    ).scalar_one()
    result = await db.execute(base_stmt.offset(skip).limit(limit))
    keys = result.scalars().all()
    return ApiKeyListResponse(
        items=[
            ApiKeyListItem(
                id=k.id,
                name=k.name,
                is_active=k.is_active,
                created_at=k.created_at,
                last_used_at=k.last_used_at,
            )
            for k in keys
        ],
        total=total,
    )


@router.post(
    "/api-keys/",
    response_model=ApiKeyCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_my_api_key(
    body: ApiKeyCreateRequest,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> ApiKeyCreateResponse:
    """Create an API key for the current user.

    The raw key is returned only in this response and cannot be retrieved again.
    """
    raw_key = secrets.token_urlsafe(32)
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()

    api_key = ApiKey(
        user_id=current_user.id,
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


@router.delete("/api-keys/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_my_api_key(
    key_id: uuid.UUID,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Revoke (soft-delete) one of the current user's API keys."""
    result = await db.execute(
        select(ApiKey).where(ApiKey.id == key_id, ApiKey.user_id == current_user.id)
    )
    api_key = result.scalar_one_or_none()
    if api_key is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="API key not found",
        )
    api_key.is_active = False
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
