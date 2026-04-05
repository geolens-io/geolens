"""Settings API endpoints: unified admin settings, public basemaps/map-defaults/tile-config."""

import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.stdlib.get_logger(__name__)

from app.audit.service import log_action
from app.auth.dependencies import require_permission
from app.auth.models import User
from app.auth.oauth.schemas import (
    OAuthProviderCreate,
    OAuthProviderResponse,
    OAuthProviderUpdate,
)
from app.auth.oauth import service as oauth_service
from app.dependencies import get_db
from app.persistent_config import (
    BASEMAPS,
    BRANDING_SHOW_BADGE,
    EMBEDDING_DIMS,
    ENABLED_WIDGETS,
    MAP_DEFAULTS,
    _is_env_only,
    _registry,
)
from app.edition import get_edition
from app.public_urls import get_public_api_url, get_public_app_url
from app.settings.models import AppSetting
from app.config import settings as app_settings
from app.settings.schemas import (
    ApiKeyStatusResponse,
    BasemapPublicResponse,
    BrandingResponse,
    ConfigModeResponse,
    DetectEmbeddingDimsResponse,
    EditionInfoResponse,
    MapDefaultsResponse,
    SETTING_VALIDATORS,
    SettingItem,
    SettingsAllResponse,
    SettingsResetRequest,
    SettingsUpdateRequest,
    TileConfigResponse,
)

router = APIRouter(prefix="/settings", tags=["Admin"])


# ---------------------------------------------------------------------------
# Unified admin endpoints
# ---------------------------------------------------------------------------


@router.get("/all/", response_model=SettingsAllResponse)
async def get_all_settings(
    request: Request,
    _user: User = Depends(require_permission("manage_settings")),
    db: AsyncSession = Depends(get_db),
) -> SettingsAllResponse:
    """Return all settings grouped by tab with source indicators (admin only)."""
    env_only = _is_env_only()

    # Bulk-fetch all DB overrides in one query (key + value)
    result = await db.execute(select(AppSetting.key, AppSetting.value))
    db_settings: dict[str, object] = {}
    for row in result.all():
        raw = row[1]
        # AppSetting.value is JSONB — unwrap the stored scalar wrapper
        db_settings[row[0]] = raw if not isinstance(raw, dict) or "v" not in raw else raw["v"]
    db_keys = set(db_settings.keys())

    tabs: dict[str, list[SettingItem]] = {}
    for cfg in _registry:
        if cfg.key == "public_app_url":
            value = await get_public_app_url(db, request=request)
        elif cfg.key == "public_api_url":
            value = await get_public_api_url(db, request=request)
        elif cfg.key in db_settings:
            value = db_settings[cfg.key]
        else:
            value = cfg.env_default

        if env_only:
            source = "env_only"
        elif cfg.key in db_keys:
            source = "overridden"
        else:
            source = "default"

        item = SettingItem(key=cfg.key, value=value, source=source, label=cfg.label)
        tabs.setdefault(cfg.tab, []).append(item)

    return SettingsAllResponse(env_only=env_only, tabs=tabs)


@router.put("/", response_model=SettingsAllResponse)
async def update_settings(
    body: SettingsUpdateRequest,
    request: Request,
    user: User = Depends(require_permission("manage_settings")),
    db: AsyncSession = Depends(get_db),
) -> SettingsAllResponse:
    """Update one or more settings (admin only). Returns updated settings."""
    # Build a lookup from registry
    registry_map = {cfg.key: cfg for cfg in _registry}

    for key, value in body.settings.items():
        cfg = registry_map.get(key)
        if cfg is None:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown setting key: {key}",
            )

        # Lockout prevention for role_permissions
        if key == "role_permissions":
            from app.auth.permissions import validate_permission_matrix

            try:
                validate_permission_matrix(value)
            except ValueError as e:
                raise HTTPException(
                    status_code=422,
                    detail=f"Validation error for '{key}': {e}",
                )

        # Run validator if one exists
        validator = SETTING_VALIDATORS.get(key)
        if validator is not None:
            try:
                value = validator(value)
            except (ValueError, TypeError) as e:
                raise HTTPException(
                    status_code=422,
                    detail=f"Validation error for '{key}': {e}",
                )

        ip = request.client.host if request.client else None
        await cfg.set(db, value, user_id=user.id, ip_address=ip, commit=False)

    # Single commit for all setting writes
    await db.commit()

    # Auto-detect embedding dimensions when embedding_model changes
    if "embedding_model" in body.settings and "embedding_dims" not in body.settings:
        try:
            from app.embeddings.service import probe_embedding_dimensions

            dims = await probe_embedding_dimensions(db)
            ip = request.client.host if request.client else None
            await EMBEDDING_DIMS.set(db, dims, user_id=user.id, ip_address=ip)
        except Exception:
            logger.warning("Failed to auto-detect embedding dimensions", exc_info=True)

    # When embedding dimensions change, delete incompatible embeddings and
    # rebuild the column + HNSW index so the backfill button reappears in the UI.
    if "embedding_dims" in body.settings:
        from app.embeddings.service import rebuild_embedding_column

        new_dims = int(body.settings["embedding_dims"])
        try:
            await rebuild_embedding_column(db, new_dims)
        except Exception:
            pass  # error already logged and rolled back inside helper

    # Return updated settings
    return await get_all_settings(request=request, _user=user, db=db)


@router.post("/reset/", response_model=SettingsAllResponse)
async def reset_settings(
    body: SettingsResetRequest,
    request: Request,
    user: User = Depends(require_permission("manage_settings")),
    db: AsyncSession = Depends(get_db),
) -> SettingsAllResponse:
    """Reset one or more settings to their defaults (admin only). Returns updated settings."""
    registry_map = {cfg.key: cfg for cfg in _registry}

    for key in body.keys:
        cfg = registry_map.get(key)
        if cfg is None:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown setting key: {key}",
            )
        ip = request.client.host if request.client else None
        await cfg.reset(db, user_id=user.id, ip_address=ip)

    return await get_all_settings(request=request, _user=user, db=db)


@router.get("/api-key-status/", response_model=ApiKeyStatusResponse)
async def get_api_key_status(
    _user: User = Depends(require_permission("manage_settings")),
) -> ApiKeyStatusResponse:
    """Return which LLM API keys are configured (without exposing values)."""
    return ApiKeyStatusResponse(
        anthropic_configured=bool(app_settings.anthropic_api_key),
        openai_configured=bool(app_settings.openai_api_key),
    )


@router.post("/detect-embedding-dims/", response_model=DetectEmbeddingDimsResponse)
async def detect_embedding_dims(
    _user: User = Depends(require_permission("manage_settings")),
    db: AsyncSession = Depends(get_db),
) -> DetectEmbeddingDimsResponse:
    """Probe the configured embedding model and return its output dimensions."""
    from app.embeddings.service import (
        EmbeddingUnavailableError,
        probe_embedding_dimensions,
    )

    try:
        dims = await probe_embedding_dimensions(db)
    except EmbeddingUnavailableError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Embedding probe failed: {e}")

    return DetectEmbeddingDimsResponse(dimensions=dims)


@router.get("/config-mode/", response_model=ConfigModeResponse)
async def get_config_mode() -> ConfigModeResponse:
    """Return whether the app is in env-only config mode (public, no auth)."""
    return ConfigModeResponse(env_only=_is_env_only())


# ---------------------------------------------------------------------------
# OAuth provider CRUD (admin only)
# ---------------------------------------------------------------------------


@router.get("/oauth-providers/", response_model=list[OAuthProviderResponse])
async def list_oauth_providers(
    _user: User = Depends(require_permission("manage_settings")),
    db: AsyncSession = Depends(get_db),
) -> list[OAuthProviderResponse]:
    """List all OAuth providers (admin only)."""
    providers = await oauth_service.list_providers(db)
    return [OAuthProviderResponse.model_validate(p) for p in providers]


@router.post(
    "/oauth-providers/",
    response_model=OAuthProviderResponse,
    status_code=201,
)
async def create_oauth_provider(
    body: OAuthProviderCreate,
    request: Request,
    user: User = Depends(require_permission("manage_settings")),
    db: AsyncSession = Depends(get_db),
) -> OAuthProviderResponse:
    """Create a new OAuth provider (admin only)."""
    provider = await oauth_service.create_provider(db, body)
    ip = request.client.host if request.client else None
    await log_action(
        session=db,
        user_id=user.id,
        action="oauth_provider.create",
        resource_type="oauth_provider",
        resource_id=provider.id,
        details={"slug": body.slug},
        ip_address=ip,
    )
    await db.commit()
    return OAuthProviderResponse.model_validate(provider)


@router.put(
    "/oauth-providers/{provider_id}",
    response_model=OAuthProviderResponse,
)
async def update_oauth_provider(
    provider_id: uuid.UUID,
    body: OAuthProviderUpdate,
    request: Request,
    user: User = Depends(require_permission("manage_settings")),
    db: AsyncSession = Depends(get_db),
) -> OAuthProviderResponse:
    """Update an existing OAuth provider (admin only)."""
    provider = await oauth_service.get_provider_by_id(db, provider_id)
    if provider is None:
        raise HTTPException(status_code=404, detail="OAuth provider not found")
    provider = await oauth_service.update_provider(db, provider, body)
    ip = request.client.host if request.client else None
    await log_action(
        session=db,
        user_id=user.id,
        action="oauth_provider.update",
        resource_type="oauth_provider",
        resource_id=provider.id,
        details={"slug": provider.slug},
        ip_address=ip,
    )
    await db.commit()
    return OAuthProviderResponse.model_validate(provider)


@router.delete(
    "/oauth-providers/{provider_id}",
    status_code=204,
)
async def delete_oauth_provider(
    provider_id: uuid.UUID,
    request: Request,
    user: User = Depends(require_permission("manage_settings")),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete an OAuth provider (admin only)."""
    provider = await oauth_service.get_provider_by_id(db, provider_id)
    if provider is None:
        raise HTTPException(status_code=404, detail="OAuth provider not found")
    slug = provider.slug
    await oauth_service.delete_provider(db, provider)
    ip = request.client.host if request.client else None
    await log_action(
        session=db,
        user_id=user.id,
        action="oauth_provider.delete",
        resource_type="oauth_provider",
        resource_id=provider_id,
        details={"slug": slug},
        ip_address=ip,
    )
    await db.commit()


# ---------------------------------------------------------------------------
# Public endpoints (no auth required)
# ---------------------------------------------------------------------------


@router.get("/edition/", response_model=EditionInfoResponse)
async def edition_info() -> EditionInfoResponse:
    """Return current edition and available features. Public, no auth required."""
    info = get_edition()
    return EditionInfoResponse(edition=info.edition, features=list(info.features))


@router.get("/branding/", response_model=BrandingResponse)
async def get_branding(
    db: AsyncSession = Depends(get_db),
) -> BrandingResponse:
    """Return branding configuration (public, no auth required)."""
    show_badge = await BRANDING_SHOW_BADGE.get(db)
    return BrandingResponse(show_badge=show_badge)


@router.get("/basemaps/", response_model=list[BasemapPublicResponse])
async def get_basemaps(
    db: AsyncSession = Depends(get_db),
) -> list[BasemapPublicResponse]:
    """Return the configured basemap list (public, no auth required).

    Basemaps with ``{api_key}`` in the URL are filtered out when no key is
    configured.  When a key IS set the placeholder is resolved server-side.
    The response uses ``BasemapPublicResponse`` which excludes ``api_key``.
    """
    stored = await BASEMAPS.get(db)
    result: list[BasemapPublicResponse] = []
    for entry in stored:
        url = entry.get("url", "")
        key_value = entry.get("api_key")
        if "{api_key}" in url:
            if not key_value:
                continue
            entry = {**entry, "url": url.replace("{api_key}", key_value)}
        result.append(BasemapPublicResponse(**entry))
    return result


@router.get("/map-defaults/", response_model=MapDefaultsResponse)
async def get_map_defaults(
    db: AsyncSession = Depends(get_db),
) -> MapDefaultsResponse:
    """Return the default map center and zoom (public, no auth required)."""
    stored = await MAP_DEFAULTS.get(db)
    return MapDefaultsResponse(**stored)


@router.get("/enabled-widgets/", response_model=list[str] | None)
async def get_enabled_widgets(
    db: AsyncSession = Depends(get_db),
) -> list[str] | None:
    """Return enabled widget IDs. null = no restriction (all shown), [] = none, [...ids] = only those."""
    return await ENABLED_WIDGETS.get(db)


@router.get("/tile-config/", response_model=TileConfigResponse)
async def get_tile_config(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> TileConfigResponse:
    """Return tile delivery configuration (public, no auth required)."""
    public_app_url = await get_public_app_url(db, request=request)
    public_api_url = await get_public_api_url(db, request=request)
    return TileConfigResponse(
        cdn_base_url=app_settings.cdn_base_url,
        public_app_url=public_app_url,
        public_api_url=public_api_url,
        public_base_url=public_api_url,
    )
