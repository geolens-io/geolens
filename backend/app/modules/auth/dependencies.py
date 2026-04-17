"""FastAPI dependencies for JWT authentication and role-based access control."""

import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import ApiKey, User
from app.modules.auth.visibility import get_user_roles
from app.core.config import settings
from app.core.dependencies import get_db

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")
oauth2_scheme_optional = OAuth2PasswordBearer(tokenUrl="/auth/login", auto_error=False)


async def _resolve_api_key(request: Request, db: AsyncSession) -> User | None:
    """Try to resolve a user from X-Api-Key header or api_key query parameter."""
    api_key = request.headers.get("X-Api-Key")
    if not api_key:
        api_key = request.query_params.get("api_key")
    if not api_key:
        return None
    key_hash = hashlib.sha256(api_key.encode()).hexdigest()
    result = await db.execute(
        select(ApiKey).where(ApiKey.key_hash == key_hash, ApiKey.is_active == True)  # noqa: E712
    )
    api_key_obj = result.scalar_one_or_none()
    if api_key_obj is None:
        return None
    user = api_key_obj.user
    if user is None or not user.is_active or user.status != "active":
        return None
    # Only update last_used_at if it's been more than 60 seconds (reduce write amplification)
    now = datetime.now(timezone.utc)
    if api_key_obj.last_used_at is None or (now - api_key_obj.last_used_at) > timedelta(
        seconds=60
    ):
        api_key_obj.last_used_at = now
        await db.commit()
    return user


async def get_optional_user(
    request: Request,
    token: Annotated[str | None, Depends(oauth2_scheme_optional)],
    db: AsyncSession = Depends(get_db),
) -> User | None:
    """Try to extract the current user from an API key or JWT token.

    Returns None if no credentials are provided or they are invalid.
    Used on endpoints that should be accessible anonymously (public datasets)
    but can show additional data when authenticated.
    """
    # Try API key first
    user = await _resolve_api_key(request, db)
    if user is not None:
        return user

    if token is None:
        return None
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key.get_secret_value(),
            algorithms=[settings.jwt_algorithm],
        )
        user_id_str: str | None = payload.get("sub")
        if user_id_str is None:
            return None
    except jwt.PyJWTError:
        return None

    try:
        user_id = uuid.UUID(user_id_str)
    except (ValueError, AttributeError):
        return None

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if user is None or not user.is_active or user.status != "active":
        return None

    return user


async def get_current_user(
    request: Request,
    token: Annotated[str | None, Depends(oauth2_scheme_optional)],
    db: AsyncSession = Depends(get_db),
) -> User:
    """Decode a JWT Bearer token (or API key) and return the corresponding User.

    Raises 401 if credentials are invalid, expired, or the user does not exist.
    Uses oauth2_scheme_optional so that X-Api-Key requests without a Bearer
    token are not rejected before the function body runs.
    """
    # Try API key first
    user = await _resolve_api_key(request, db)
    if user is not None:
        return user

    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    if token is None:
        raise credentials_exception

    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key.get_secret_value(),
            algorithms=[settings.jwt_algorithm],
        )
        user_id_str: str | None = payload.get("sub")
        if user_id_str is None:
            raise credentials_exception
    except jwt.PyJWTError:
        raise credentials_exception

    try:
        user_id = uuid.UUID(user_id_str)
    except (ValueError, AttributeError):
        raise credentials_exception

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if user is None or not user.is_active or user.status != "active":
        raise credentials_exception

    return user


async def get_current_active_user(
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    """Ensure the current user is active."""
    if not current_user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Inactive user",
        )
    return current_user


async def get_cached_user_roles(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User | None = Depends(get_optional_user),
) -> set[str]:
    """Return user roles, cached for the lifetime of this request.

    Prevents repeated DB hits when require_role/require_permission are
    called multiple times on the same request path.
    """
    if user is None:
        return set()
    cached = getattr(request.state, "_user_roles", None)
    if cached is not None:
        return cached
    roles = await get_user_roles(db, user)
    request.state._user_roles = roles
    return roles


def require_role(*roles: str):
    """Factory that returns a dependency enforcing role-based access.

    Usage::

        @router.get("/admin", dependencies=[Depends(require_role("admin"))])
        async def admin_only(): ...

    The dependency resolves to the current User so endpoints can also
    consume it as a parameter.
    """

    async def _role_checker(
        request: Request,
        current_user: Annotated[User, Depends(get_current_active_user)],
        db: AsyncSession = Depends(get_db),
    ) -> User:
        user_roles = await get_cached_user_roles(request, db, current_user)

        if not user_roles.intersection(roles):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions",
            )
        return current_user

    return _role_checker


def require_permission(*capabilities: str):
    """Factory that returns a dependency enforcing capability-based access.

    Checks the permission matrix to see if ANY of the user's roles grants
    the requested capabilities.

    Usage::

        @router.post("/upload", dependencies=[Depends(require_permission("upload"))])
        async def upload(): ...
    """

    async def _permission_checker(
        request: Request,
        current_user: Annotated[User, Depends(get_current_active_user)],
        db: AsyncSession = Depends(get_db),
    ) -> User:
        from app.modules.auth.permissions import get_effective_permissions

        # Get user roles (cached per-request)
        user_roles = await get_cached_user_roles(request, db, current_user)

        # Get effective permission matrix (cached per-request)
        cached = getattr(request.state, "_effective_permissions", None)
        if cached is not None:
            matrix = cached
        else:
            matrix = await get_effective_permissions(db)
            request.state._effective_permissions = matrix

        # Check each requested capability
        for cap in capabilities:
            granted = any(matrix.get(role, {}).get(cap, False) for role in user_roles)
            if not granted:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Missing permission: {cap}",
                )

        return current_user

    return _permission_checker
