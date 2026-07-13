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
        ge=-90.0, le=90.0, description="Currently configured initial center latitude."
    )
    center_lng: float = Field(
        ge=-180.0,
        le=180.0,
        description="Currently configured initial center longitude.",
    )
    zoom: float = Field(
        ge=0.0,
        le=22.0,
        description="Currently configured initial zoom level.",
    )


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


class FeatureFlagsResponse(BaseModel):
    """Public feature flags readable by any authenticated user."""

    enable_dataset_editing: bool = False
    require_metadata_for_publish: bool = False


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
    """Response for runtime capability metadata."""

    edition: str = Field(description="Runtime capability channel.")
    features: list[str] = Field(description="List of enabled runtime feature flags.")
    tenancy_mode: str = Field(
        default="single_tenant",
        description="Deployment tenancy mode.",
    )


class EnterpriseTabsResponse(BaseModel):
    """Response for restricted Settings tab keys."""

    tabs: list[str] = Field(
        description=(
            "Tab keys (e.g. 'branding', 'appearance') restricted by the current "
            "runtime. Sorted alphabetically for stable client-side comparison."
        )
    )


class BrandingResponse(BaseModel):
    """Response for GET /settings/branding/."""

    show_badge: bool = Field(
        description=(
            "Whether to show the 'Powered by GeoLens' label in public and shared "
            "footers. Badge-removal writes are restricted controls."
        )
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


class NotificationStatusResponse(BaseModel):
    """Response for GET /settings/notifications/status/ (NOTIF-05 / NOTIF-06).

    Returns only boolean presence flags — never a secret value (SMTP password,
    webhook URL, or webhook secret).
    """

    notifications_enabled: bool = Field(
        description="Whether the NOTIFICATIONS_ENABLED master toggle is set to true."
    )
    smtp_configured: bool = Field(
        description="Whether an SMTP host is configured (SMTP_HOST is set). Does not echo the host value."
    )
    webhook_configured: bool = Field(
        description="Whether a notification webhook URL is configured (NOTIFICATION_WEBHOOK_URL is set). Does not echo the URL."
    )


class NotificationTestChannelResult(BaseModel):
    """Per-channel result from POST /settings/notifications/test/.

    The ``error`` field contains only the exception type name and a short
    safe message — never the SMTP password, webhook URL, or webhook secret
    (T-1229-09 / NOTIF-05).
    """

    channel: str = Field(description="Channel name, e.g. 'smtp' or 'webhook'.")
    ok: bool = Field(
        description="True if the channel delivered the test notification without error."
    )
    error: str | None = Field(
        default=None,
        description="Safe error string (exception type name + short message) if ok=False, else null. Never contains secrets.",
    )


class NotificationTestResponse(BaseModel):
    """Response for POST /settings/notifications/test/ (NOTIF-06).

    Always returns HTTP 200 — a channel delivery failure is captured in the
    per-channel ``channels`` list rather than as a 5xx. Never contains secret
    values (T-1229-09 / NOTIF-05).
    """

    sent: bool = Field(
        description="True if at least one channel successfully delivered the test notification."
    )
    channels: list[NotificationTestChannelResult] = Field(
        description="Per-channel delivery results. Empty when no channel is configured."
    )
    message: str = Field(description="Human-readable summary of the test result.")


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


def validate_semantic_search_rate_limit(v: Any) -> int:
    v = int(v)
    if v < 1 or v > 1000:
        raise ValueError("semantic_search_rate_limit must be between 1 and 1000")
    return v


def validate_basemap_proxy_rate_limit(v: Any) -> int:
    v = int(v)
    if v < 1 or v > 1000:
        raise ValueError("basemap_proxy_rate_limit must be between 1 and 1000")
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


def validate_openai_base_url(v: Any) -> str:
    """Keep the environment API key bound to the operator's chat endpoint."""
    from app.core.ai_credentials import validate_persistent_openai_base_url

    return validate_persistent_openai_base_url(v, purpose="chat")


def validate_embedding_base_url(v: Any) -> str:
    """Keep the environment API key bound to the operator's embedding endpoint."""
    from app.core.ai_credentials import validate_persistent_openai_base_url

    return validate_persistent_openai_base_url(v, purpose="embedding")


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
    if not v or (isinstance(v, str) and not v.strip()):
        return ""
    normalized = _normalize_absolute_url(v)
    if urlsplit(normalized).path.rstrip("/").endswith("/api"):
        raise ValueError("public_app_url must point to the app, not the /api base")
    return normalized


def validate_public_api_url(v: Any) -> str:
    if not v or (isinstance(v, str) and not v.strip()):
        return ""
    return _normalize_absolute_url(v)


# Mapping from setting key to validator function
def validate_enabled_plugins(v: Any) -> list[str] | None:
    if v is None:
        return None
    if not isinstance(v, list):
        raise ValueError("enabled_plugins must be a list or null")
    for item in v:
        if not isinstance(item, str) or not item.strip():
            raise ValueError("Each plugin ID must be a non-empty string")
    return [item.strip() for item in v]


def _validate_bounded_int(v: Any, name: str, min_val: int, max_val: int) -> int:
    if isinstance(v, bool):
        raise ValueError(f"{name} must be an integer")
    if isinstance(v, float) and not v.is_integer():
        # Reject fractional numbers up front; int(0.5) would otherwise truncate to
        # 0 and pass the range check. For quotas 0 means "unlimited", so a typo'd
        # 0.5 would silently disable the cap instead of returning 422.
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


def validate_max_storage_bytes_per_user(v: Any) -> int:
    # 0 = unlimited; reject negatives (which would otherwise persist and show as
    # "overridden" yet behave as unlimited via the cap>0 guard). Ceiling is the
    # JS safe-integer max so the admin number input round-trips losslessly.
    return _validate_bounded_int(v, "max_storage_bytes_per_user", 0, 9007199254740991)


def validate_max_datasets_per_user(v: Any) -> int:
    # 0 = unlimited; reject negatives. Generous ceiling for a per-user count.
    return _validate_bounded_int(v, "max_datasets_per_user", 0, 10_000_000)


def validate_max_ai_tokens_per_user_per_day(v: Any) -> int:
    # 0 = unlimited; reject negatives, which would otherwise persist as
    # "overridden" yet behave as unlimited via the cap>0 guard in
    # _check_ai_budget — silently disabling the cost cap (codex P3 on #402).
    return _validate_bounded_int(
        v, "max_ai_tokens_per_user_per_day", 0, 9007199254740991
    )


_VALID_LOG_LEVELS = frozenset({"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"})


def validate_log_level(v: Any) -> str:
    """Accept only standard Python logging level names (case-insensitive)."""
    if not isinstance(v, str):
        raise ValueError("log_level must be a string")
    upper = v.strip().upper()
    if upper not in _VALID_LOG_LEVELS:
        raise ValueError(
            f"Invalid log_level {v!r}. Must be one of: {', '.join(sorted(_VALID_LOG_LEVELS))}"
        )
    return upper


def validate_allowed_email_domains(v: Any) -> list[str]:
    """Validate and normalize the allowed_email_domains setting.

    - Raises ValueError if v is not a list.
    - Normalizes each entry (strip, lower-case, drop empties, de-dup).
    - Raises ValueError with the offending pattern named if any entry is invalid.
    - Returns the normalized list (case-folded, de-duplicated).
    - An empty input list returns [] (unrestricted — valid).

    Imports domain helpers inline to avoid any circular-import risk at module load.
    """
    from app.modules.auth.domain_validation import (
        is_domain_pattern_valid,
        normalize_domains,
    )

    if not isinstance(v, list):
        raise ValueError("allowed_email_domains must be a list")
    # Codex P3: reject non-string entries here (ValueError -> 422) before
    # normalize_domains calls .strip() on them, which would raise AttributeError
    # and surface as a 500 (update_settings only catches ValueError/TypeError).
    for entry in v:
        if not isinstance(entry, str):
            raise ValueError(
                "allowed_email_domains entries must be strings, got "
                f"{type(entry).__name__}: {entry!r}"
            )
    normalized = normalize_domains(v)
    for pattern in normalized:
        if not is_domain_pattern_valid(pattern):
            raise ValueError(f"Invalid email domain pattern: {pattern!r}")
    return normalized


SETTING_VALIDATORS: dict[str, Any] = {
    "log_level": validate_log_level,
    "login_rate_limit": validate_login_rate_limit,
    "global_rate_limit": validate_global_rate_limit,
    "semantic_search_rate_limit": validate_semantic_search_rate_limit,
    "basemap_proxy_rate_limit": validate_basemap_proxy_rate_limit,
    "upload_max_size_mb": validate_upload_max_size,
    "upload_allowed_extensions": validate_upload_extensions,
    "basemaps": validate_basemaps,
    "map_defaults": validate_map_defaults,
    "embedding_model": validate_strip_string,
    "embedding_base_url": validate_embedding_base_url,
    "openai_base_url": validate_openai_base_url,
    "llm_model": validate_strip_string,
    "public_app_url": validate_public_app_url,
    "public_api_url": validate_public_api_url,
    "public_base_url": validate_public_api_url,
    "enabled_plugins": validate_enabled_plugins,
    "access_token_expire_minutes": validate_access_token_expire,
    "refresh_token_expire_days": validate_refresh_token_expire,
    "embedding_dims": validate_embedding_dims,
    "tile_cache_ttl": validate_tile_cache_ttl,
    "max_storage_bytes_per_user": validate_max_storage_bytes_per_user,
    "max_datasets_per_user": validate_max_datasets_per_user,
    "max_ai_tokens_per_user_per_day": validate_max_ai_tokens_per_user_per_day,
    "allowed_email_domains": validate_allowed_email_domains,
}
