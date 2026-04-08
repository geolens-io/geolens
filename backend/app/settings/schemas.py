"""Pydantic models for site-wide settings: basemaps, map defaults, unified settings API."""

from typing import Any
from urllib.parse import urlsplit, urlunsplit

from pydantic import BaseModel, Field, field_validator


class BasemapEntry(BaseModel):
    id: str = Field(
        max_length=30,
        description="Unique identifier for the basemap (e.g. 'osm', 'satellite').",
    )
    label: str = Field(
        max_length=200, description="Human-readable label shown in the basemap picker."
    )
    url: str = Field(
        max_length=2000,
        description="Style JSON URL (ending in .json), /styles/ path, or tile URL with {z}/{x}/{y} placeholders.",
    )
    enabled: bool = Field(
        default=True, description="Whether the basemap is selectable in the picker."
    )
    is_preset: bool = Field(
        default=False,
        description="Whether this is a built-in preset (cannot be deleted, only disabled).",
    )
    attribution: str | None = Field(
        default=None,
        description="Optional attribution string shown on the map. May include HTML.",
    )
    api_key: str | None = Field(
        default=None,
        max_length=500,
        description="Optional API key for authenticated tile providers. Substituted into the URL via {api_key} placeholder.",
    )

    @field_validator("url")
    @classmethod
    def validate_tile_url(cls, v: str) -> str:
        """Allow style JSON URLs (.json), /styles/ paths, or tile URLs with {z}/{x}/{y} placeholders."""
        # Strip query string for path-based checks
        base_path = v.split("?")[0].rstrip("/")
        if base_path.endswith(".json"):
            return v
        if "{z}" in v and "{x}" in v and "{y}" in v:
            return v
        # Accept style endpoints that serve JSON without .json extension
        # (e.g. https://tiles.openfreemap.org/styles/bright)
        if "/styles/" in v:
            return v
        raise ValueError(
            "Tile URL must end with .json (style), contain /styles/, or contain {z}, {x}, {y} placeholders"
        )


class BasemapPublicResponse(BaseModel):
    """Public basemap response — excludes api_key."""

    id: str = Field(description="Unique basemap identifier.")
    label: str = Field(description="Display label.")
    url: str = Field(
        description="Tile URL or style JSON URL with API key already substituted (or omitted) for client use."
    )
    enabled: bool = Field(description="Whether the basemap is currently selectable.")
    is_preset: bool = Field(description="Whether this is a built-in preset.")
    attribution: str | None = Field(
        default=None, description="Attribution string for the basemap source."
    )


class BasemapsUpdate(BaseModel):
    basemaps: list[BasemapEntry] = Field(
        description="Complete list of basemaps. Replaces the existing list — entries not included are removed."
    )


class MapDefaultsUpdate(BaseModel):
    center_lat: float = Field(
        description="Initial map center latitude in WGS84. Clamped to [-90, 90]."
    )
    center_lng: float = Field(
        description="Initial map center longitude in WGS84. Clamped to [-180, 180]."
    )
    zoom: float = Field(description="Initial zoom level. Clamped to [0, 22].")

    @field_validator("center_lat")
    @classmethod
    def clamp_lat(cls, v: float) -> float:
        return max(-90.0, min(90.0, v))

    @field_validator("center_lng")
    @classmethod
    def clamp_lng(cls, v: float) -> float:
        return max(-180.0, min(180.0, v))

    @field_validator("zoom")
    @classmethod
    def clamp_zoom(cls, v: float) -> float:
        return max(0.0, min(22.0, v))


class MapDefaultsResponse(BaseModel):
    center_lat: float = Field(
        description="Currently configured initial center latitude."
    )
    center_lng: float = Field(
        description="Currently configured initial center longitude."
    )
    zoom: float = Field(description="Currently configured initial zoom level.")


class TileConfigResponse(BaseModel):
    cdn_base_url: str | None = Field(
        default=None, description="CDN origin URL for tile delivery, if configured."
    )
    public_app_url: str | None = Field(
        default=None,
        description="Browser-facing app URL used for share links and OAuth redirects.",
    )
    public_api_url: str | None = Field(
        default=None,
        description="Externally-reachable API base URL used in OGC self-links.",
    )
    public_base_url: str | None = Field(
        default=None,
        description="Deprecated alias for public_api_url. Will be removed in a future release.",
    )


# ---------------------------------------------------------------------------
# Unified settings API models
# ---------------------------------------------------------------------------


class SettingItem(BaseModel):
    """A single setting in the unified response."""

    key: str = Field(description="Setting key (e.g. 'login_rate_limit', 'basemaps').")
    value: Any = Field(description="Current value. Type depends on the setting.")
    source: str = Field(
        description="Where the value came from: 'default' (built-in default), 'overridden' (admin set via UI), or 'env_only' (configured via environment variable, read-only)."
    )
    label: str = Field(description="Human-readable label for display in the admin UI.")


class SettingsAllResponse(BaseModel):
    """Response for GET /settings/all/."""

    env_only: bool = Field(
        description="Whether the instance is in env-only mode (settings are read-only and managed via environment variables)."
    )
    tabs: dict[str, list[SettingItem]] = Field(
        description="Settings grouped by admin UI tab (general, auth, ai, etc.)."
    )


class SettingsUpdateRequest(BaseModel):
    """Request for PUT /settings/."""

    settings: dict[str, Any] = Field(
        description="Map of setting keys to new values. Maximum 50 settings per request."
    )

    @field_validator("settings")
    @classmethod
    def limit_settings_count(cls, v: dict) -> dict:
        if len(v) > 50:
            raise ValueError("Too many settings in single request (max 50)")
        return v


class SettingsResetRequest(BaseModel):
    """Request for POST /settings/reset/."""

    keys: list[str] = Field(
        max_length=100,
        description="List of setting keys to reset to their default values. Maximum 100 keys per request.",
    )


class EditionInfoResponse(BaseModel):
    """Response for GET /settings/edition/."""

    edition: str = Field(description="Active edition: 'community' or 'enterprise'.")
    features: list[str] = Field(
        description="List of feature flags enabled for this edition."
    )


class BrandingResponse(BaseModel):
    """Response for GET /settings/branding/."""

    show_badge: bool = Field(
        description="Whether to show the 'Powered by GeoLens' badge in the footer."
    )


class ConfigModeResponse(BaseModel):
    """Response for GET /settings/config-mode/."""

    env_only: bool = Field(
        description="True if the instance is configured via environment variables only (admin UI is read-only)."
    )


class ApiKeyStatusResponse(BaseModel):
    """Response for GET /settings/api-key-status/."""

    anthropic_configured: bool = Field(
        description="Whether ANTHROPIC_API_KEY is set in the environment."
    )
    openai_configured: bool = Field(
        description="Whether OPENAI_API_KEY is set in the environment."
    )


class DetectEmbeddingDimsResponse(BaseModel):
    """Response for POST /settings/detect-embedding-dims/."""

    dimensions: int = Field(
        description="Number of dimensions in the embedding vector returned by the configured embedding provider."
    )


# ---------------------------------------------------------------------------
# Validators for PUT /settings/ -- reused from old schemas
# ---------------------------------------------------------------------------


def validate_login_rate_limit(v: Any) -> int:
    v = int(v)
    if v < 1 or v > 1000:
        raise ValueError("login_rate_limit must be between 1 and 1000")
    return v


def validate_global_rate_limit(v: Any) -> int:
    v = int(v)
    if v < 1 or v > 1000:
        raise ValueError("global_rate_limit must be between 1 and 1000")
    return v


def validate_upload_max_size(v: Any) -> int:
    v = int(v)
    if v < 1 or v > 10000:
        raise ValueError("max_size_mb must be between 1 and 10000")
    return v


def validate_upload_extensions(v: Any) -> str:
    if not isinstance(v, str):
        raise ValueError("allowed_extensions must be a string")
    exts = [e.strip() for e in v.split(",") if e.strip()]
    for ext in exts:
        if not ext.startswith("."):
            raise ValueError(f"Extension must start with '.': {ext}")
    if not exts:
        raise ValueError("At least one extension is required")
    return ",".join(exts)


def validate_basemaps(v: Any) -> list[dict]:
    if not isinstance(v, list):
        raise ValueError("basemaps must be a list")
    # Validate each entry through the Pydantic model
    return [BasemapEntry(**entry).model_dump() for entry in v]


def validate_map_defaults(v: Any) -> dict:
    if not isinstance(v, dict):
        raise ValueError("map_defaults must be a dict")
    validated = MapDefaultsUpdate(**v)
    return validated.model_dump()


def validate_strip_string(v: Any) -> str:
    if not isinstance(v, str):
        raise ValueError("Value must be a string")
    return v.strip()


def _normalize_absolute_url(v: Any) -> str:
    if not isinstance(v, str):
        raise ValueError("Value must be a string")
    stripped = v.strip()
    if not stripped:
        raise ValueError("Value must not be empty")

    parsed = urlsplit(stripped)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Value must be an absolute http(s) URL")
    if parsed.query or parsed.fragment:
        raise ValueError("Value must not include a query string or fragment")

    path = parsed.path.rstrip("/")
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


def validate_public_app_url(v: Any) -> str:
    normalized = _normalize_absolute_url(v)
    if urlsplit(normalized).path.rstrip("/").endswith("/api"):
        raise ValueError("public_app_url must point to the app, not the /api base")
    return normalized


def validate_public_api_url(v: Any) -> str:
    return _normalize_absolute_url(v)


# Mapping from setting key to validator function
def validate_enabled_widgets(v: Any) -> list[str] | None:
    if v is None:
        return None
    if not isinstance(v, list):
        raise ValueError("enabled_widgets must be a list or null")
    for item in v:
        if not isinstance(item, str) or not item.strip():
            raise ValueError("Each widget ID must be a non-empty string")
    return [item.strip() for item in v]


def _validate_bounded_int(v: Any, name: str, min_val: int, max_val: int) -> int:
    if isinstance(v, bool):
        raise ValueError(f"{name} must be an integer")
    try:
        result = int(v)
    except (ValueError, TypeError):
        raise ValueError(f"{name} must be a valid integer")
    if result < min_val or result > max_val:
        raise ValueError(f"{name} must be between {min_val} and {max_val}")
    return result


def validate_access_token_expire(v: Any) -> int:
    return _validate_bounded_int(v, "access_token_expire_minutes", 1, 1440)


def validate_refresh_token_expire(v: Any) -> int:
    return _validate_bounded_int(v, "refresh_token_expire_days", 1, 365)


def validate_embedding_dims(v: Any) -> int:
    return _validate_bounded_int(v, "embedding_dims", 1, 4096)


def validate_tile_cache_ttl(v: Any) -> int:
    return _validate_bounded_int(v, "tile_cache_ttl", 0, 86400)


SETTING_VALIDATORS: dict[str, Any] = {
    "login_rate_limit": validate_login_rate_limit,
    "global_rate_limit": validate_global_rate_limit,
    "upload_max_size_mb": validate_upload_max_size,
    "upload_allowed_extensions": validate_upload_extensions,
    "basemaps": validate_basemaps,
    "map_defaults": validate_map_defaults,
    "embedding_model": validate_strip_string,
    "embedding_base_url": validate_strip_string,
    "openai_base_url": validate_strip_string,
    "llm_model": validate_strip_string,
    "public_app_url": validate_public_app_url,
    "public_api_url": validate_public_api_url,
    "public_base_url": validate_public_api_url,
    "enabled_widgets": validate_enabled_widgets,
    "access_token_expire_minutes": validate_access_token_expire,
    "refresh_token_expire_days": validate_refresh_token_expire,
    "embedding_dims": validate_embedding_dims,
    "tile_cache_ttl": validate_tile_cache_ttl,
}
