"""Settings API endpoints: unified admin settings, public basemaps/map-defaults/tile-config."""

import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.service import log_action
from app.modules.auth.dependencies import require_permission
from app.modules.auth.models import User
from app.modules.auth.oauth import service as oauth_service
from app.modules.auth.oauth.schemas import (
    OAuthProviderCreate,
    OAuthProviderResponse,
    OAuthProviderUpdate,
)
from app.core.config import settings as app_settings
from app.core.dependencies import get_client_ip, get_db
from app.core.edition import get_edition
from app.core.persistent_config import (
    BASEMAPS,
    BRANDING_SHOW_BADGE,
    EMBEDDING_DIMS,
    ENABLE_DATASET_EDITING,
    ENABLED_WIDGETS,
    MAP_DEFAULTS,
    REQUIRE_METADATA_FOR_PUBLISH,
    _registry,
)
from app.core.public_urls import _is_env_only, get_public_api_url, get_public_app_url
from app.modules.settings.models import AppSetting
from app.modules.settings.schemas import (
    SETTING_VALIDATORS,
    ApiKeyStatusResponse,
    BasemapPublicResponse,
    BrandingResponse,
    ConfigModeResponse,
    DetectEmbeddingDimsResponse,
    FeatureFlagsResponse,
    EditionInfoResponse,
    MapDefaultsResponse,
    SettingItem,
    SettingsAllResponse,
    SettingsResetRequest,
    SettingsUpdateRequest,
    TileConfigResponse,
)
from app.standards.ogc.errors import ERROR_RESPONSES_AUTH

logger = structlog.stdlib.get_logger(__name__)

router = APIRouter(prefix="/settings", tags=["Admin"], responses=ERROR_RESPONSES_AUTH)


# ---------------------------------------------------------------------------
# Setting-update helpers (extracted from route handler)
# ---------------------------------------------------------------------------


_ENTERPRISE_ONLY_TABS = frozenset({"branding"})


def _validate_setting(key: str, value: object) -> object:
    """Run permission and custom validators for a setting key. Returns validated value."""
    if key == "role_permissions":
        from app.modules.auth.permissions import validate_permission_matrix

        validate_permission_matrix(value)

    validator = SETTING_VALIDATORS.get(key)
    if validator is not None:
        value = validator(value)

    return value


_registry_by_key: dict[str, object] | None = None


def _get_registry_map() -> dict[str, object]:
    """Return a cached key→PersistentConfig lookup."""
    global _registry_by_key
    if _registry_by_key is None:
        _registry_by_key = {cfg.key: cfg for cfg in _registry}
    return _registry_by_key


def _require_enterprise_for_key(key: str) -> None:
    """Raise 403 if a setting key belongs to an enterprise-only tab."""
    from app.core.edition import is_enterprise

    if is_enterprise():
        return
    cfg = _get_registry_map().get(key)
    if cfg is not None and cfg.tab in _ENTERPRISE_ONLY_TABS:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Setting '{key}' requires enterprise edition",
        )


async def _auto_detect_embedding_dims(
    db: AsyncSession, user_id: uuid.UUID, ip: str | None
) -> None:
    """Probe the current embedding model and persist its dimension count."""
    try:
        from app.processing.embeddings.service import probe_embedding_dimensions

        dims = await probe_embedding_dimensions(db)
        await EMBEDDING_DIMS.set(db, dims, user_id=user_id, ip_address=ip)
    except Exception:
        # Non-fatal — admin can still set manually. Log with traceback so
        # operators can diagnose embedding probe failures (bad API key,
        # provider outage, network timeout) instead of seeing a silent skip.
        logger.warning(
            "Failed to auto-detect embedding dimensions",
            exc_info=True,
        )


async def _rebuild_embedding_column(db: AsyncSession, new_dims: int) -> None:
    """Delete incompatible embeddings and rebuild the column + HNSW index."""
    from sqlalchemy import text as sa_text

    col_check = await db.execute(
        sa_text(
            "SELECT atttypmod FROM pg_attribute "
            "WHERE attrelid = 'catalog.record_embeddings'::regclass "
            "AND attname = 'embedding'"
        )
    )
    current_dims = col_check.scalar_one_or_none()
    if current_dims is None or current_dims == new_dims:
        return

    try:
        await db.execute(sa_text("DELETE FROM catalog.record_embeddings"))
        await db.execute(
            sa_text("DROP INDEX IF EXISTS catalog.ix_record_embeddings_hnsw")
        )
        await db.execute(
            sa_text(
                f"ALTER TABLE catalog.record_embeddings "
                f"ALTER COLUMN embedding TYPE vector({new_dims}) "
                f"USING embedding::vector({new_dims})"
            )
        )
        await db.execute(
            sa_text(
                "CREATE INDEX ix_record_embeddings_hnsw "
                "ON catalog.record_embeddings USING hnsw (embedding vector_cosine_ops) "
                "WITH (m=16, ef_construction=64)"
            )
        )
        await db.commit()
    except Exception:
        logger.error("Failed to rebuild embedding column", exc_info=True)
        await db.rollback()


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
    from app.core.edition import is_enterprise

    env_only = _is_env_only()
    enterprise = is_enterprise()

    # Bulk-fetch all DB overrides in one query (key + value)
    result = await db.execute(select(AppSetting.key, AppSetting.value))
    db_settings: dict[str, object] = {}
    for row in result.all():
        raw = row[1]
        # AppSetting.value is JSONB — unwrap the stored scalar wrapper
        db_settings[row[0]] = (
            raw if not isinstance(raw, dict) or "v" not in raw else raw["v"]
        )
    db_keys = set(db_settings.keys())

    tabs: dict[str, list[SettingItem]] = {}
    for cfg in _registry:
        # Hide enterprise-only tabs in community edition
        if not enterprise and cfg.tab in _ENTERPRISE_ONLY_TABS:
            continue
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
    registry_map = _get_registry_map()

    # Capture old embedding_dims before any changes (needed for rollback)
    old_dims_value: int | None = None
    if "embedding_dims" in body.settings:
        old_dims_value = await EMBEDDING_DIMS.get(db)

    for key, value in body.settings.items():
        cfg = registry_map.get(key)
        if cfg is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unknown setting key: {key}",
            )

        _require_enterprise_for_key(key)

        try:
            value = _validate_setting(key, value)
        except (ValueError, TypeError) as e:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Validation error for '{key}': {e}",
            )

        ip = get_client_ip(request)
        await cfg.set(db, value, user_id=user.id, ip_address=ip, commit=False)

    # Single commit for all setting writes
    await db.commit()

    # Auto-detect embedding dimensions when embedding_model changes
    if "embedding_model" in body.settings and "embedding_dims" not in body.settings:
        ip = get_client_ip(request)
        await _auto_detect_embedding_dims(db, user.id, ip)

    # Rebuild column + index when embedding dimensions change
    if "embedding_dims" in body.settings:
        from app.processing.embeddings.service import rebuild_embedding_column

        new_dims = int(body.settings["embedding_dims"])
        try:
            await rebuild_embedding_column(db, new_dims)
        except Exception as exc:
            # Roll back the persisted embedding_dims setting to the previous value
            ip = get_client_ip(request)
            await EMBEDDING_DIMS.set(db, old_dims_value, user_id=user.id, ip_address=ip)
            await db.commit()
            logger.exception(
                "Embedding column rebuild failed, rolling back embedding_dims",
                old_dims=old_dims_value,
                new_dims=new_dims,
            )
            raise HTTPException(
                status_code=503,
                detail="Embedding column rebuild failed. The embedding_dims setting has been reverted.",
            ) from exc

    return await get_all_settings(request=request, _user=user, db=db)


@router.post("/reset/", response_model=SettingsAllResponse)
async def reset_settings(
    body: SettingsResetRequest,
    request: Request,
    user: User = Depends(require_permission("manage_settings")),
    db: AsyncSession = Depends(get_db),
) -> SettingsAllResponse:
    """Reset one or more settings to their defaults (admin only). Returns updated settings."""
    registry_map = _get_registry_map()

    for key in body.keys:
        cfg = registry_map.get(key)
        if cfg is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unknown setting key: {key}",
            )
        _require_enterprise_for_key(key)
        ip = get_client_ip(request)
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
    from app.processing.embeddings.service import (
        EmbeddingUnavailableError,
        probe_embedding_dimensions,
    )

    try:
        dims = await probe_embedding_dimensions(db)
    except EmbeddingUnavailableError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Embedding probe failed: {e}",
        )

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
    status_code=status.HTTP_201_CREATED,
)
async def create_oauth_provider(
    body: OAuthProviderCreate,
    request: Request,
    user: User = Depends(require_permission("manage_settings")),
    db: AsyncSession = Depends(get_db),
) -> OAuthProviderResponse:
    """Create a new OAuth provider (admin only)."""
    provider = await oauth_service.create_provider(db, body)
    ip = get_client_ip(request)
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
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="OAuth provider not found"
        )
    provider = await oauth_service.update_provider(db, provider, body)
    ip = get_client_ip(request)
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
    status_code=status.HTTP_204_NO_CONTENT,
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
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="OAuth provider not found"
        )
    slug = provider.slug
    await oauth_service.delete_provider(db, provider)
    ip = get_client_ip(request)
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


@router.get("/feature-flags/", response_model=FeatureFlagsResponse)
async def get_feature_flags(
    db: AsyncSession = Depends(get_db),
) -> FeatureFlagsResponse:
    """Return public feature flags (no auth required)."""
    return FeatureFlagsResponse(
        enable_dataset_editing=await ENABLE_DATASET_EDITING.get(db),
        require_metadata_for_publish=await REQUIRE_METADATA_FOR_PUBLISH.get(db),
    )


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
