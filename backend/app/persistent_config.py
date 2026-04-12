"""PersistentConfig: generic class for settings with DB override, caching, and audit.

Each PersistentConfig instance represents a single configuration key. Values are
resolved in order: cache -> DB override -> env_default. When ENV_ONLY_CONFIG=true,
DB overrides are ignored and writes are blocked.
"""

from __future__ import annotations

import logging
import os
import time
import uuid
from typing import Any, Generic, TypeVar, cast

import structlog
from fastapi import HTTPException
from pydantic import TypeAdapter, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import log_action
from app.cache import get_cache
from app.cache.provider import CacheProvider
from app.config import settings
from app.public_urls import resolve_public_api_url, resolve_public_app_url
from app.settings.models import AppSetting

logger = structlog.stdlib.get_logger(__name__)

T = TypeVar("T")

_CACHE_TTL = 30  # seconds
_CACHE_PREFIX = "config:"

# ---------------------------------------------------------------------------
# Module-level registry and ENV_ONLY helper
# ---------------------------------------------------------------------------

_registry: list[PersistentConfig] = []


def _is_env_only() -> bool:
    return os.environ.get("ENV_ONLY_CONFIG", "").lower() in ("true", "1", "yes")


def _get_cache_safe() -> CacheProvider | None:
    """Return the cache provider or None if not yet initialized."""
    try:
        return get_cache()
    except RuntimeError:
        return None


# Sync cache for slowapi (cannot use async CacheProvider)
_sync_rate_limit_cache: dict[str, tuple[Any, float]] = {}
_DEFAULT_LOGIN_RATE_LIMIT = 5
_DEFAULT_GLOBAL_RATE_LIMIT = 60


# ---------------------------------------------------------------------------
# Shared validation helper (used by PersistentConfig.get and get_all_registry_values)
# ---------------------------------------------------------------------------


def _validate_or_fallback(cfg: PersistentConfig[T], raw: Any) -> tuple[T, bool]:
    """Validate `raw` against cfg's TypeAdapter; return (value, validated_ok).

    Called by `PersistentConfig.get()` and `get_all_registry_values()` on the
    DB-hit branch to enforce runtime shape at the JSONB unwrap boundary.

    On ValidationError: logs a structured warning and returns
    `(cfg.env_default, False)`. Does NOT raise. Does NOT write to cache — the
    caller uses the boolean to decide whether to cache.

    Security note: `exc.errors()` includes the offending `input` value in its
    payload. Current registered configs do not store secrets (secrets live in
    `app.config.settings` / env vars, not `app_settings`). If a future
    PersistentConfig adds a secret-containing key, the logger must scrub the
    `input` field from the errors list before emission.
    """
    try:
        return cfg._adapter.validate_python(raw), True
    except ValidationError as exc:
        logger.warning(
            "persistent_config.validation_failed",
            key=cfg.key,
            errors=exc.errors(),
            action="fell_back_to_env_default",
        )
        return cfg.env_default, False


# ---------------------------------------------------------------------------
# PersistentConfig generic class
# ---------------------------------------------------------------------------


class PersistentConfig(Generic[T]):
    """A single configuration key with DB override, caching, and audit."""

    def __init__(
        self,
        key: str,
        *,
        type_: type[T],
        env_default: T | None = None,
        tab: str = "",
        label: str = "",
        env_default_factory: Any | None = None,
    ) -> None:
        self.key = key
        self._type = type_
        self._adapter: TypeAdapter[T] = TypeAdapter(type_)
        self._env_default_static = env_default
        self._env_default_factory = env_default_factory
        self.tab = tab
        self.label = label
        _registry.append(self)

    @property
    def env_default(self) -> T:
        """Resolve env_default: factory (dynamic) or static."""
        if self._env_default_factory is not None:
            return cast(T, self._env_default_factory())
        # ``None`` is a valid default for Optional settings (e.g.
        # ENABLED_WIDGETS = None means "all widgets enabled"), so we
        # intentionally cast rather than assert non-None here.
        return cast(T, self._env_default_static)

    async def get(self, db: AsyncSession) -> T:
        """Resolve effective value: env_only -> cache -> DB -> env_default."""
        if _is_env_only():
            return self.env_default

        # Check cache (gracefully handle uninitialized cache)
        cache = _get_cache_safe()
        cache_key = f"{_CACHE_PREFIX}{self.key}"
        if cache is not None:
            cached = await cache.get(cache_key)
            if cached is not None:
                self._update_sync_cache(cached)
                return cached

        # Check DB
        result = await db.execute(
            select(AppSetting.value).where(AppSetting.key == self.key)
        )
        row = result.scalar_one_or_none()
        effective: T
        validated_ok = True  # default: cache-write OK (applies to env_default path)
        if row is not None:
            # AppSetting.value is JSONB -- unwrap the stored value
            unwrapped = row if not isinstance(row, dict) or "v" not in row else row["v"]
            effective, validated_ok = _validate_or_fallback(self, unwrapped)
        else:
            effective = self.env_default

        # Populate cache only when we got a valid DB value or env_default path.
        # On validation fallback, skip cache write so the next read re-hits the
        # DB and re-logs until the corrupt row is fixed (D-03).
        if cache is not None and validated_ok:
            await cache.set(cache_key, effective, ttl=_CACHE_TTL)
        self._update_sync_cache(effective)
        return effective

    async def set(
        self,
        db: AsyncSession,
        value: T,
        *,
        user_id: uuid.UUID | None = None,
        ip_address: str | None = None,
        commit: bool = True,
    ) -> None:
        """Upsert value into app_settings, audit, and invalidate cache."""
        if _is_env_only():
            raise HTTPException(
                status_code=403,
                detail="Configuration locked to environment variables",
            )

        old_value = await self.get(db)

        # Upsert
        result = await db.execute(select(AppSetting).where(AppSetting.key == self.key))
        existing = result.scalar_one_or_none()
        # Wrap value in a JSONB-friendly dict for non-dict types. AppSetting.value
        # is typed as dict JSONB, so cast the wrapped payload for mypy.
        stored: dict[str, Any] = (
            cast(dict[str, Any], value)
            if isinstance(value, (dict, list))
            else {"v": value}
        )
        if existing is None:
            db.add(AppSetting(key=self.key, value=stored))
        else:
            existing.value = stored

        # Audit log
        if user_id is not None:
            await log_action(
                session=db,
                user_id=user_id,
                action="update",
                resource_type="setting",
                details={
                    "setting_key": self.key,
                    "old_value": old_value,
                    "new_value": value,
                },
                ip_address=ip_address,
            )

        if commit:
            await db.commit()

        # Invalidate cache
        cache = _get_cache_safe()
        if cache is not None:
            await cache.delete(f"{_CACHE_PREFIX}{self.key}")

        # Side effect hook
        self._on_change(value)

    async def reset(
        self,
        db: AsyncSession,
        *,
        user_id: uuid.UUID | None = None,
        ip_address: str | None = None,
    ) -> None:
        """Delete DB override, reverting to env_default. Audit and invalidate cache."""
        if _is_env_only():
            raise HTTPException(
                status_code=403,
                detail="Configuration locked to environment variables",
            )

        old_value = await self.get(db)

        result = await db.execute(select(AppSetting).where(AppSetting.key == self.key))
        existing = result.scalar_one_or_none()
        if existing is not None:
            await db.delete(existing)

            if user_id is not None:
                await log_action(
                    session=db,
                    user_id=user_id,
                    action="reset",
                    resource_type="setting",
                    details={
                        "setting_key": self.key,
                        "old_value": old_value,
                        "new_value": self.env_default,
                    },
                    ip_address=ip_address,
                )

            await db.commit()

            cache = _get_cache_safe()
            if cache is not None:
                await cache.delete(f"{_CACHE_PREFIX}{self.key}")

            self._on_change(self.env_default)

    def _on_change(self, value: T) -> None:
        """Override in subclasses for side effects on set()."""

    def _update_sync_cache(self, value: Any) -> None:
        """Update sync cache for rate-limit accessor if applicable."""
        if self.key == "login_rate_limit":
            _sync_rate_limit_cache["login_rate_limit"] = (value, time.monotonic())
        elif self.key == "global_rate_limit":
            _sync_rate_limit_cache["global_rate_limit"] = (value, time.monotonic())


# ---------------------------------------------------------------------------
# LOG_LEVEL subclass with side effect
# ---------------------------------------------------------------------------


class _LogLevelConfig(PersistentConfig[str]):
    def __init__(self, key: str, **kwargs: Any) -> None:
        # Hard-code type_=str for this subclass — the sole purpose of the
        # subclass is to attach a side effect hook for log level propagation.
        super().__init__(key, type_=str, **kwargs)

    def _on_change(self, value: str) -> None:
        logging.getLogger().setLevel(value.upper())


# ---------------------------------------------------------------------------
# Registry declarations
# ---------------------------------------------------------------------------

# -- General tab --
REGISTRATION_ENABLED = PersistentConfig[bool](
    key="registration_enabled",
    type_=bool,
    env_default_factory=lambda: settings.registration_enabled,
    tab="auth",
    label="Registration Enabled",
)

PUBLIC_BASE_URL = PersistentConfig[str](
    key="public_base_url",
    type_=str,
    env_default_factory=lambda: resolve_public_api_url(
        settings.public_app_url,
        settings.public_api_url,
        settings.public_base_url,
    ),
    tab="general",
    label="Public API URL (Legacy)",
)

PUBLIC_APP_URL = PersistentConfig[str](
    key="public_app_url",
    type_=str,
    env_default_factory=lambda: resolve_public_app_url(
        settings.public_app_url,
        settings.public_api_url,
        settings.public_base_url,
    ),
    tab="general",
    label="Public App URL",
)

PUBLIC_API_URL = PersistentConfig[str](
    key="public_api_url",
    type_=str,
    env_default_factory=lambda: resolve_public_api_url(
        settings.public_app_url,
        settings.public_api_url,
        settings.public_base_url,
    ),
    tab="general",
    label="Public API URL",
)

LOG_LEVEL = _LogLevelConfig(
    key="log_level",
    env_default_factory=lambda: settings.log_level,
    tab="general",
    label="Log Level",
)

LOG_JSON = PersistentConfig[bool](
    key="log_json",
    type_=bool,
    env_default_factory=lambda: settings.log_json,
    tab="general",
    label="JSON Logging",
)

REQUIRE_METADATA_FOR_PUBLISH = PersistentConfig[bool](
    key="require_metadata_for_publish",
    type_=bool,
    env_default=False,
    tab="general",
    label="Require Metadata for Publishing",
)

# -- Auth tab --
ACCESS_TOKEN_EXPIRE_MINUTES = PersistentConfig[int](
    key="access_token_expire_minutes",
    type_=int,
    env_default_factory=lambda: settings.access_token_expire_minutes,
    tab="auth",
    label="Access Token Expiry (min)",
)

REFRESH_TOKEN_EXPIRE_DAYS = PersistentConfig[int](
    key="refresh_token_expire_days",
    type_=int,
    env_default_factory=lambda: settings.refresh_token_expire_days,
    tab="auth",
    label="Refresh Token Expiry (days)",
)

LOGIN_RATE_LIMIT = PersistentConfig[int](
    key="login_rate_limit",
    type_=int,
    env_default=_DEFAULT_LOGIN_RATE_LIMIT,
    tab="auth",
    label="Login Rate Limit (per min)",
)

# -- AI tab --
AI_ENABLED = PersistentConfig[bool](
    key="ai_enabled",
    type_=bool,
    env_default=True,
    tab="ai",
    label="AI Features Enabled",
)

LLM_PROVIDER = PersistentConfig[str](
    key="llm_provider",
    type_=str,
    env_default_factory=lambda: (
        "anthropic" if settings.anthropic_api_key else "openai_compatible"
    ),
    tab="ai",
    label="LLM Provider",
)

LLM_MODEL = PersistentConfig[str](
    key="llm_model",
    type_=str,
    env_default_factory=lambda: (
        settings.llm_model if settings.anthropic_api_key else settings.openai_model
    ),
    tab="ai",
    label="LLM Model",
)

OPENAI_BASE_URL = PersistentConfig[str](
    key="openai_base_url",
    type_=str,
    env_default_factory=lambda: settings.openai_base_url or "",
    tab="ai",
    label="OpenAI-Compatible Base URL",
)

EMBEDDING_MODEL = PersistentConfig[str](
    key="embedding_model",
    type_=str,
    env_default_factory=lambda: settings.embedding_model,
    tab="ai",
    label="Embedding Model",
)

EMBEDDING_DIMS = PersistentConfig[int](
    key="embedding_dims",
    type_=int,
    env_default_factory=lambda: settings.embedding_dims,
    tab="ai",
    label="Embedding Dimensions",
)

EMBEDDING_BASE_URL = PersistentConfig[str](
    key="embedding_base_url",
    type_=str,
    env_default_factory=lambda: settings.embedding_base_url or "",
    tab="ai",
    label="Embedding Base URL",
)

SEMANTIC_SEARCH_ENABLED = PersistentConfig[bool](
    key="semantic_search_enabled",
    type_=bool,
    env_default=False,
    tab="ai",
    label="Semantic Search",
)

AI_SEND_SAMPLE_VALUES = PersistentConfig[bool](
    key="ai_send_sample_values",
    type_=bool,
    env_default=True,
    tab="ai",
    label="Send Sample Values to LLM",
)

LLM_MODEL_LIGHT = PersistentConfig[str](
    key="llm_model_light",
    type_=str,
    env_default_factory=lambda: (
        "claude-haiku-4-5-20251001" if settings.anthropic_api_key else "gpt-4o-mini"
    ),
    tab="ai",
    label="Light LLM Model (SQL/Metadata)",
)

# -- Network tab --
GLOBAL_RATE_LIMIT = PersistentConfig[int](
    key="global_rate_limit",
    type_=int,
    env_default=_DEFAULT_GLOBAL_RATE_LIMIT,
    tab="network",
    label="Global Rate Limit (per second)",
)

CORS_ALLOWED_ORIGINS = PersistentConfig[str](
    key="cors_allowed_origins",
    type_=str,
    env_default_factory=lambda: settings.cors_allowed_origins,
    tab="network",
    label="CORS Allowed Origins",
)

# -- Storage tab --
UPLOAD_MAX_SIZE_MB = PersistentConfig[int](
    key="upload_max_size_mb",
    type_=int,
    env_default_factory=lambda: settings.upload_max_size_mb,
    tab="storage",
    label="Upload Max Size (MB)",
)

UPLOAD_ALLOWED_EXTENSIONS = PersistentConfig[str](
    key="upload_allowed_extensions",
    type_=str,
    env_default_factory=lambda: settings.upload_allowed_extensions,
    tab="storage",
    label="Allowed Upload Extensions",
)


async def get_all_registry_values(db: AsyncSession) -> dict[str, Any]:
    """Batch-load all registry settings in a single DB query.

    Returns a dict mapping each registered key to its effective value
    (DB override if present, otherwise env_default). Bypassed when ENV_ONLY_CONFIG
    is set — returns env_defaults directly without hitting the DB.
    """
    settings_dict: dict[str, Any] = {}

    if _is_env_only():
        for cfg in _registry:
            settings_dict[cfg.key] = cfg.env_default
        return settings_dict

    # Batch-load all settings in one query
    result = await db.execute(select(AppSetting))
    all_settings = {row.key: row.value for row in result.scalars().all()}

    for cfg in _registry:
        raw = all_settings.get(cfg.key)
        if raw is not None:
            # AppSetting.value is JSONB — unwrap the stored scalar wrapper
            unwrapped = raw if not isinstance(raw, dict) or "v" not in raw else raw["v"]
            value, _ok = _validate_or_fallback(cfg, unwrapped)
            settings_dict[cfg.key] = value
        else:
            settings_dict[cfg.key] = cfg.env_default

    return settings_dict


async def get_allowed_extensions_list(db: AsyncSession) -> list[str]:
    """Return the allowed upload extensions as a parsed list."""
    raw = await UPLOAD_ALLOWED_EXTENSIONS.get(db)
    return [e.strip() for e in raw.split(",")]


TILE_CACHE_TTL = PersistentConfig[int](
    key="tile_cache_ttl",
    type_=int,
    env_default_factory=lambda: settings.tile_cache_ttl,
    tab="storage",
    label="Tile Cache TTL (s)",
)

# -- Map tab --
# Import default basemaps/map-defaults from the existing router constants
# to avoid circular imports, define them inline
_DEFAULT_BASEMAPS = [
    {
        "id": "openfreemap-positron",
        "label": "OpenFreeMap Positron",
        "url": "https://tiles.openfreemap.org/styles/positron",
        "enabled": True,
        "is_preset": True,
        "attribution": "&copy; <a href='https://openfreemap.org'>OpenFreeMap</a>, &copy; <a href='https://openmaptiles.org/'>OpenMapTiles</a>, &copy; <a href='https://www.openstreetmap.org/copyright'>OpenStreetMap</a> contributors",
    },
    {
        "id": "openfreemap-dark",
        "label": "OpenFreeMap Dark",
        "url": "https://tiles.openfreemap.org/styles/dark",
        "enabled": True,
        "is_preset": True,
        "attribution": "&copy; <a href='https://openfreemap.org'>OpenFreeMap</a>, &copy; <a href='https://openmaptiles.org/'>OpenMapTiles</a>, &copy; <a href='https://www.openstreetmap.org/copyright'>OpenStreetMap</a> contributors",
    },
    {
        "id": "openstreetmap",
        "label": "OpenStreetMap",
        "url": "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
        "enabled": True,
        "is_preset": True,
        "attribution": "&copy; <a href='https://www.openstreetmap.org/copyright'>OpenStreetMap</a> contributors",
    },
    {
        "id": "openfreemap-bright",
        "label": "OpenFreeMap Bright",
        "url": "https://tiles.openfreemap.org/styles/bright",
        "enabled": True,
        "is_preset": True,
        "attribution": "&copy; <a href='https://openfreemap.org'>OpenFreeMap</a>, &copy; <a href='https://openmaptiles.org/'>OpenMapTiles</a>, &copy; <a href='https://www.openstreetmap.org/copyright'>OpenStreetMap</a> contributors",
    },
]

_DEFAULT_MAP_DEFAULTS = {"center_lat": 20.0, "center_lng": 0.0, "zoom": 2.0}

from app.settings.schemas import BasemapEntry, MapDefaultsResponse

BASEMAPS = PersistentConfig[list[BasemapEntry]](
    key="basemaps",
    type_=list[BasemapEntry],
    env_default=_DEFAULT_BASEMAPS,
    tab="map",
    label="Basemaps",
)

MAP_DEFAULTS = PersistentConfig[MapDefaultsResponse](
    key="map_defaults",
    type_=MapDefaultsResponse,
    env_default=_DEFAULT_MAP_DEFAULTS,
    tab="map",
    label="Map Defaults",
)


# -- Widgets --
ENABLED_WIDGETS = PersistentConfig[list[str] | None](
    key="enabled_widgets",
    type_=list[str] | None,
    env_default=None,
    tab="map",
    label="Enabled Widgets",
)


# -- Permissions tab --
# Import DEFAULT_ROLE_PERMISSIONS lazily to avoid circular imports
def _default_role_permissions() -> dict:
    from app.auth.permissions import DEFAULT_ROLE_PERMISSIONS

    return DEFAULT_ROLE_PERMISSIONS


ROLE_PERMISSIONS = PersistentConfig[dict[str, list[str]]](
    key="role_permissions",
    type_=dict[str, list[str]],
    env_default_factory=_default_role_permissions,
    tab="permissions",
    label="Role Permissions",
)

# -- Branding tab --
BRANDING_SHOW_BADGE = PersistentConfig[bool](
    key="branding.show_badge",
    type_=bool,
    env_default=True,
    tab="branding",
    label="Show Powered by GeoLens Footer Label",
)


# ---------------------------------------------------------------------------
# Sync rate limit accessor (for slowapi)
# ---------------------------------------------------------------------------


def get_cached_login_rate_limit() -> int:
    """Sync accessor for slowapi callable -- reads from sync cache, falls back to default."""
    cached = _sync_rate_limit_cache.get("login_rate_limit")
    if cached and (time.monotonic() - cached[1]) < _CACHE_TTL:
        return cached[0]
    return _DEFAULT_LOGIN_RATE_LIMIT


def get_cached_global_rate_limit() -> int:
    """Sync accessor for slowapi callable -- reads from sync cache, falls back to default."""
    cached = _sync_rate_limit_cache.get("global_rate_limit")
    if cached and (time.monotonic() - cached[1]) < _CACHE_TTL:
        return cached[0]
    return _DEFAULT_GLOBAL_RATE_LIMIT
