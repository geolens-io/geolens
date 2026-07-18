"""Public, non-secret settings read endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db
from app.core.edition import get_edition
from app.core.persistent_config import (
    BASEMAPS,
    BRANDING_SHOW_BADGE,
    ENABLE_DATASET_EDITING,
    ENABLED_PLUGINS,
    MAP_DEFAULTS,
    REQUIRE_METADATA_FOR_PUBLISH,
    get_cached_basemap_proxy_rate_limit,
)
from app.modules.auth.router import limiter
from app.modules.settings.schemas import (
    BasemapPublicResponse,
    BrandingResponse,
    EditionInfoResponse,
    FeatureFlagsResponse,
    MapDefaultsResponse,
)

router = APIRouter(prefix="/settings", tags=["Admin"])


def _basemap_proxy_rate_limit(_request: Request | None = None) -> str:
    """SEC-S10: per-IP rate limit for the public basemap endpoint (caps key replay)."""
    return f"{get_cached_basemap_proxy_rate_limit()}/minute"


@router.get("/edition", response_model=EditionInfoResponse, include_in_schema=False)
@router.get(
    "/edition/",
    response_model=EditionInfoResponse,
    # fix(scripts/deployed_surface_gate.json#edition_info_op): neutral summary — the
    # auto-derived "Edition Info" label is a banned public-copy id; operationId/path
    # unchanged.
    summary="Get runtime capabilities",
)
async def edition_info() -> EditionInfoResponse:
    """Return runtime capability metadata. Public, no auth required."""
    from app.core.tenancy import TENANCY_MODE_SINGLE, is_multi_tenant

    info = get_edition()
    return EditionInfoResponse(
        edition=info.edition,
        features=list(info.features),
        tenancy_mode="multi_tenant" if is_multi_tenant() else TENANCY_MODE_SINGLE,
    )


@router.get(
    "/feature-flags", response_model=FeatureFlagsResponse, include_in_schema=False
)
@router.get("/feature-flags/", response_model=FeatureFlagsResponse)
async def get_feature_flags(
    db: AsyncSession = Depends(get_db),
) -> FeatureFlagsResponse:
    """Return public feature flags (no auth required)."""
    return FeatureFlagsResponse(
        enable_dataset_editing=await ENABLE_DATASET_EDITING.get(db),
        require_metadata_for_publish=await REQUIRE_METADATA_FOR_PUBLISH.get(db),
    )


@router.get("/branding", response_model=BrandingResponse, include_in_schema=False)
@router.get("/branding/", response_model=BrandingResponse)
async def get_branding(
    db: AsyncSession = Depends(get_db),
) -> BrandingResponse:
    """Return branding configuration (public, no auth required).

    The active ``BrandingExtension`` provides initial defaults for branding
    keys. PersistentConfig overrides take precedence when set. Community
    advertises read-only ``show_badge`` only; badge-removal writes and
    additional branding keys are restricted controls.
    """
    from app.platform.extensions import get_branding_extension

    defaults = get_branding_extension().get_branding_defaults()
    persisted = await BRANDING_SHOW_BADGE.get(db)
    show_badge = (
        persisted if persisted is not None else bool(defaults.get("show_badge", True))
    )
    return BrandingResponse(show_badge=show_badge)


@router.get(
    "/basemaps", response_model=list[BasemapPublicResponse], include_in_schema=False
)
@router.get("/basemaps/", response_model=list[BasemapPublicResponse])
@limiter.limit(_basemap_proxy_rate_limit)
async def get_basemaps(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> list[BasemapPublicResponse]:
    """Return the configured basemap list (public, no auth required).

    Basemaps with ``{api_key}`` in the URL are filtered out when no key is
    configured.  When a key IS set the placeholder is resolved server-side.
    The response uses ``BasemapPublicResponse`` which excludes ``api_key``.

    SEC-S10 (2026-05-20 audit): the resolved ``url`` field intentionally
    includes the substituted ``api_key`` value when configured. Client-side
    tile-provider keys (Mapbox, Stadia, MapTiler) are designed for browser
    exposure and the frontend MUST receive them to load tiles. Do NOT put a
    backend-only provider key in this field. Rotate the key in the
    provider dashboard if it is misused. Rate-limited via
    ``_basemap_proxy_rate_limit`` to cap replay-cost from anonymous clients.
    """
    del request
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


@router.get(
    "/map-defaults", response_model=MapDefaultsResponse, include_in_schema=False
)
@router.get("/map-defaults/", response_model=MapDefaultsResponse)
async def get_map_defaults(
    db: AsyncSession = Depends(get_db),
) -> MapDefaultsResponse:
    """Return the default map center and zoom (public, no auth required)."""
    return MapDefaultsResponse(**(await MAP_DEFAULTS.get(db)))


@router.get(
    "/enabled-plugins", response_model=list[str] | None, include_in_schema=False
)
@router.get("/enabled-plugins/", response_model=list[str] | None)
async def get_enabled_plugins(
    db: AsyncSession = Depends(get_db),
) -> list[str] | None:
    """Return enabled plugin IDs. null = no restriction (all shown), [] = none, [...ids] = only those."""
    return await ENABLED_PLUGINS.get(db)
