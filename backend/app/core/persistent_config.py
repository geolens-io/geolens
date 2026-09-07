"""PersistentConfig: generic class for settings with DB override, caching, and audit.

Each PersistentConfig instance represents a single configuration key. Values are
resolved in order: cache -> DB override -> env_default. When ENV_ONLY_CONFIG=true,
DB overrides are ignored and writes are blocked.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Sequence
from typing import Any, Generic, TypeVar, cast

import structlog
from fastapi import HTTPException
from pydantic import TypeAdapter, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.cache import get_cache
from app.platform.cache.provider import CacheProvider
from app.platform.audit import AuditEvent, audit_emit
from app.core.config import settings
from app.core.logging_config import apply_http_logger_levels
from app.core.public_urls import (
    PUBLIC_URL_KEYS,
    _is_env_only,
    invalidate_public_url_cache,
    resolve_public_api_url,
    resolve_public_app_url,
)
from app.core.db.models import AppSetting

logger = structlog.stdlib.get_logger(__name__)

T = TypeVar("T")

_CACHE_TTL = 30  # seconds
_CACHE_PREFIX = "config:"

_registry: list[PersistentConfig] = []

# fix(#435): ADMIN-03 (M-03) — single source of truth for enterprise-only
# Settings tabs; the backend `_require_enterprise_for_key` gate, config
# import/export, and the frontend AdminSidebar all consult this set. Lives
# here so config_ops need not import settings/router.py at import time.
ENTERPRISE_ONLY_TABS = frozenset({"branding", "appearance"})


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
_DEFAULT_SEMANTIC_SEARCH_RATE_LIMIT = 30
_DEFAULT_BASEMAP_PROXY_RATE_LIMIT = 120
# Ceiling for the OGC Features `limit` page size. Conservative by default
# (#665 review): the offset path is O(N) in memory on an anonymous endpoint,
# so a low default protects resource-limited deployments; operators raise
# it from the dashboard for bulk export.
_DEFAULT_OGC_ITEMS_MAX_PAGE_SIZE = 1000


def _validate_or_fallback(cfg: PersistentConfig[T], raw: Any) -> tuple[T, bool]:
    """Validate `raw` against cfg's TypeAdapter; return (value, validated_ok).

    Used by `PersistentConfig.get()` and `get_all_registry_values()` on the
    DB-hit branch. On failure: logs a warning and returns
    `(cfg.env_default, False)` without raising or caching.

    Security: `exc.errors()` includes the offending input value. No
    registered config currently stores secrets — a future secret-containing
    key must scrub the `input` field before logging.
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
        # ENABLED_PLUGINS = None means "all plugins enabled"), so we
        # intentionally cast rather than assert non-None here.
        return cast(T, self._env_default_static)

    async def get(self, db: AsyncSession) -> T:
        """Resolve effective value: env_only -> cache -> DB -> env_default."""
        if _is_env_only():
            return self.env_default

        cache = _get_cache_safe()
        cache_key = f"{_CACHE_PREFIX}{self.key}"
        if cache is not None:
            cached = await cache.get(cache_key)
            if cached is not None:
                self._update_sync_cache(cached)
                return cached

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

        # On validation fallback, skip the cache write so the next read
        # re-hits the DB and re-logs until the corrupt row is fixed (D-03).
        if cache is not None and validated_ok:
            await cache.set(cache_key, effective, ttl=_CACHE_TTL)
        self._update_sync_cache(effective)
        return effective

    async def get_uncached(self, db: AsyncSession) -> T:
        """Resolve the effective value directly from the DB, bypassing the cache.

        Used by callers that must observe a value committed inside a lock
        they hold (e.g. the SSO lockout guards). The cached ``get`` has a
        race: a writer invalidates the cache before its commit, so a
        concurrent reader can repopulate it with the pre-commit value, and
        a guard resuming after the row lock would then read that stale
        value. This reads under READ COMMITTED and touches no cache, so it
        can't observe or create a stale entry.
        """
        if _is_env_only():
            return self.env_default

        result = await db.execute(
            select(AppSetting.value).where(AppSetting.key == self.key)
        )
        row = result.scalar_one_or_none()
        if row is not None:
            unwrapped = row if not isinstance(row, dict) or "v" not in row else row["v"]
            effective, _ = _validate_or_fallback(self, unwrapped)
            return effective
        return self.env_default

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

        if user_id is not None:
            await audit_emit(
                db,
                AuditEvent(
                    user_id=user_id,
                    action="update",
                    resource_type="setting",
                    details={
                        "setting_key": self.key,
                        "old_value": old_value,
                        "new_value": value,
                    },
                    ip_address=ip_address,
                ),
            )

        if commit:
            await db.commit()
            await self.apply_side_effects(value)
        # fix(#430): with commit=False, side effects are deferred to the
        # batching caller's terminal commit — running them pre-commit flips
        # runtime state (log level, rate limits) a rollback won't restore.

    async def apply_side_effects(self, value: T) -> None:
        """Post-commit cache invalidation + runtime hooks for a value change.

        Called automatically by set()/reset() when they own the commit. A
        caller batching with ``commit=False`` must not loop this per key —
        use ``apply_side_effects_batch`` after its terminal commit (fix
        #1543), never before it (fix(#430) r3; see set() above).
        """
        await apply_side_effects_batch([(self, value)])

    def _apply_local_side_effects(self, value: T) -> None:
        """The process-local half of apply_side_effects.

        Deliberately synchronous: this runs once per key of a batch, and having
        no await in it is what keeps a whole batch's worth uninterleavable.
        """
        # BUG-025: public-URL keys are also memoized in a separate 60s cache
        # in public_urls; clear it so the new value is reflected immediately.
        if self.key in PUBLIC_URL_KEYS:
            invalidate_public_url_cache()

        self._on_change(value)

        # BUG-008: warm the sync cache with the NEW value — set() only ever
        # warmed it with the OLD value (via get(db) above), so slowapi kept
        # enforcing the previous limit for up to _CACHE_TTL per process.
        self._update_sync_cache(value)

    async def reset(
        self,
        db: AsyncSession,
        *,
        user_id: uuid.UUID | None = None,
        ip_address: str | None = None,
        commit: bool = True,
    ) -> None:
        """Delete DB override, reverting to env_default. Audit and invalidate cache.

        fix(#430): pass ``commit=False`` to defer the DB commit to a caller's
        terminal commit (config-import overwrite mode), so a mid-import failure
        rolls the resets back instead of leaving settings wiped to defaults.
        """
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
                await audit_emit(
                    db,
                    AuditEvent(
                        user_id=user_id,
                        action="reset",
                        resource_type="setting",
                        details={
                            "setting_key": self.key,
                            "old_value": old_value,
                            "new_value": self.env_default,
                        },
                        ip_address=ip_address,
                    ),
                )

            if commit:
                await db.commit()
                await self.apply_side_effects(self.env_default)
            # fix(#430): with commit=False the caller applies side effects
            # (with env_default) after its terminal commit — see set().

    def _on_change(self, value: T) -> None:
        """Override in subclasses for side effects on set()."""

    def _update_sync_cache(self, value: Any) -> None:
        """Update sync cache for rate-limit accessor if applicable."""
        if self.key in (
            "login_rate_limit",
            "global_rate_limit",
            # CR-03 (Phase 1062 review): also warm the cache for the two new
            # rate-limit knobs so DB-overridden values are picked up by slowapi
            # at request time. Without these entries, get_cached_*_rate_limit()
            # always fell through to _DEFAULT_* and ignored admin-set values.
            "semantic_search_rate_limit",
            "basemap_proxy_rate_limit",
        ):
            _sync_rate_limit_cache[self.key] = (value, time.monotonic())


async def apply_side_effects_batch(
    items: Sequence[tuple[PersistentConfig[Any], Any]],
) -> None:
    """Apply the post-commit side effects of a whole settings batch at once.

    fix(#1543): a per-key eviction loop let a concurrent reader see the new
    value for already-evicted keys and the old value for the rest — surfaced
    by the embedding model/dimensions pair never resolving as committed.
    One ``delete_many`` collapses that span to a single atomic step, evicted
    only after commit (evicting before it would let a reader repopulate the
    cache with the pre-commit value for a full TTL).

    Scope: this makes the WRITER atomic, not a reader — two separate
    ``get`` calls can still straddle this step and see one key's new value
    against another's cached-old one. ``get_uncached`` is the per-key
    opt-out (#1539); the embedding endpoint has no uncached variant yet, so
    it can still lag by a full ``_CACHE_TTL`` regardless of this eviction —
    closing that needs the read protocol widened, not another eviction fix.
    """
    if not items:
        return

    cache = _get_cache_safe()
    if cache is not None:
        await cache.delete_many(*(f"{_CACHE_PREFIX}{cfg.key}" for cfg, _ in items))

    for cfg, value in items:
        cfg._apply_local_side_effects(value)


class _LogLevelConfig(PersistentConfig[str]):
    def __init__(self, key: str, **kwargs: Any) -> None:
        # Hard-code type_=str for this subclass — the sole purpose of the
        # subclass is to attach a side effect hook for log level propagation.
        super().__init__(key, type_=str, **kwargs)

    def _on_change(self, value: str) -> None:
        logging.getLogger().setLevel(value.upper())
        # fix(#1746): keep httpx/httpcore's WARNING floor correct after a
        # runtime log-level change too — see apply_http_logger_levels().
        apply_http_logger_levels(value.upper())


REGISTRATION_ENABLED = PersistentConfig[bool](
    key="registration_enabled",
    type_=bool,
    env_default_factory=lambda: settings.registration_enabled,
    tab="auth",
    label="Registration Enabled",
)

# SIGNUP-04: when self-serve registration is ON, email verification is the
# activation gate. Default True for the secure path; independent of
# REGISTRATION_ENABLED, which gates availability, not activation.
# SECURITY (#267): with SMTP, this is NOT username-enumeration-safe — the
# /auth/register response is uniform, but a verification email sends only
# when the identity was free, letting a registrant infer it out-of-band.
# Mitigated by /register rate limiting, not eliminated.
EMAIL_VERIFICATION_REQUIRED = PersistentConfig[bool](
    key="email_verification_required",
    type_=bool,
    env_default=True,
    tab="auth",
    label="Require Email Verification",
)


PUBLIC_BASE_URL = PersistentConfig[str](
    key="public_base_url",
    type_=str,
    env_default_factory=lambda: settings.public_base_url or "",
    tab="general",
    label="Public Base URL",
)

# CONF-01: PUBLIC_BASE_URL is the legacy alias for PUBLIC_API_URL, kept
# functional for backwards compatibility. Warn once at import time rather
# than per-request.
if settings.public_base_url:
    logger.warning(
        "config.public_base_url.deprecated",
        message=(
            "PUBLIC_BASE_URL is deprecated. Use PUBLIC_API_URL instead. "
            "PUBLIC_BASE_URL still resolves to PUBLIC_API_URL for backwards "
            "compatibility but will be removed in a future release."
        ),
        current_value_set=True,
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

# PRIV-1: per-instance privacy-policy link for the login/register pages.
# tab="general" (not "branding") deliberately: ENTERPRISE_ONLY_TABS gates the
# branding tab, and self-hosted community operators need this the most.
PRIVACY_URL = PersistentConfig[str](
    key="privacy_url",
    type_=str,
    env_default_factory=lambda: settings.privacy_url or "",
    tab="general",
    label="Privacy Policy URL",
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

ENABLE_DATASET_EDITING = PersistentConfig[bool](
    key="enable_dataset_editing",
    type_=bool,
    env_default=False,
    tab="general",
    label="Enable Dataset Editing",
)

# feat(#1691): when ON, only admins may set `visibility: public` on datasets/
# maps (gate: `check_public_visibility_allowed` in catalog/authorization.py).
# Default OFF; fires only on a mutation that requests public, so existing
# public content is untouched.
RESTRICT_PUBLIC_VISIBILITY = PersistentConfig[bool](
    key="restrict_public_visibility",
    type_=bool,
    env_default=False,
    tab="general",
    label="Restrict Public Visibility to Admins",
)

# FRONT-01: landing-first flag, default OFF. When ON, the frontend root
# guard redirects unauthenticated visitors from "/" to "/login" unless
# they've set the gl-guest-browse sessionStorage escape hatch.
LANDING_FIRST = PersistentConfig[bool](
    key="landing_first",
    type_=bool,
    env_default_factory=lambda: settings.landing_first,
    tab="auth",
    label="Login-as-Landing Page",
)

# Site-wide announcement banner. Disabled by default; empty text also means
# "no banner". The enabled flag lets admins stage/pause a message without
# deleting the text. Color is a frontend theme token name (warning | info |
# success | destructive); unknown values fall back to warning on the client.
BANNER_ENABLED = PersistentConfig[bool](
    key="banner_enabled",
    type_=bool,
    env_default_factory=lambda: settings.banner_enabled,
    tab="general",
    label="Site Banner Enabled",
)

BANNER_TEXT = PersistentConfig[str](
    key="banner_text",
    type_=str,
    env_default_factory=lambda: settings.banner_text,
    tab="general",
    label="Site Banner Text",
)

BANNER_COLOR = PersistentConfig[str](
    key="banner_color",
    type_=str,
    env_default_factory=lambda: settings.banner_color,
    tab="general",
    label="Site Banner Color",
)

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

# DOMAIN-01: allowlist of permitted email domains for signup/login/SSO/
# admin-create. Default [] means unrestricted. JSONB-backed key — no
# Alembic migration required.
ALLOWED_EMAIL_DOMAINS = PersistentConfig[list[str]](
    key="allowed_email_domains",
    type_=list[str],
    env_default=[],
    tab="auth",
    label="Allowed Email Domains",
)

# SSO-01: when False, POST /auth/login returns 403 for users without
# manage_settings — admins always retain password-login as a break-glass
# escape hatch. Default True. JSONB-backed key — no Alembic migration
# required.
PASSWORD_LOGIN_ENABLED = PersistentConfig[bool](
    key="password_login_enabled",
    type_=bool,
    env_default=True,
    tab="auth",
    label="Password Login Enabled",
)

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
    # Fall back to openai_model rather than a hardcoded model name — a
    # hardcoded name 404s on Azure OpenAI/gateways/Ollama, where it must
    # match a real deployment. Set OPENAI_MODEL_LIGHT for a cheaper model.
    env_default_factory=lambda: (
        "claude-haiku-4-5-20251001"
        if settings.anthropic_api_key
        else (settings.openai_model_light or settings.openai_model)
    ),
    tab="ai",
    label="Light LLM Model (SQL/Metadata)",
)

MAX_AI_TOKENS_PER_USER_PER_DAY = PersistentConfig[int](
    key="max_ai_tokens_per_user_per_day",
    type_=int,
    env_default=0,
    tab="ai",
    label="Max AI Tokens per User per Day (0=unlimited)",
)

GLOBAL_RATE_LIMIT = PersistentConfig[int](
    key="global_rate_limit",
    type_=int,
    env_default=_DEFAULT_GLOBAL_RATE_LIMIT,
    tab="network",
    label="Global Rate Limit (per second)",
)

SEMANTIC_SEARCH_RATE_LIMIT = PersistentConfig[int](
    key="semantic_search_rate_limit",
    type_=int,
    env_default=_DEFAULT_SEMANTIC_SEARCH_RATE_LIMIT,
    tab="network",
    label="Semantic Search Rate Limit (per minute)",
)

BASEMAP_PROXY_RATE_LIMIT = PersistentConfig[int](
    key="basemap_proxy_rate_limit",
    type_=int,
    env_default=_DEFAULT_BASEMAP_PROXY_RATE_LIMIT,
    tab="network",
    label="Basemap Proxy Rate Limit (per minute)",
)

CORS_ALLOWED_ORIGINS = PersistentConfig[str](
    key="cors_allowed_origins",
    type_=str,
    env_default_factory=lambda: settings.cors_allowed_origins,
    tab="network",
    label="CORS Allowed Origins",
)

OGC_ITEMS_MAX_PAGE_SIZE = PersistentConfig[int](
    key="ogc_items_max_page_size",
    type_=int,
    env_default=_DEFAULT_OGC_ITEMS_MAX_PAGE_SIZE,
    tab="network",
    label="OGC Features Max Page Size (items limit ceiling)",
)

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

MAX_STORAGE_BYTES_PER_USER = PersistentConfig[int](
    key="max_storage_bytes_per_user",
    type_=int,
    env_default=0,
    tab="storage",
    label="Max Storage per User (bytes, 0=unlimited)",
)

MAX_DATASETS_PER_USER = PersistentConfig[int](
    key="max_datasets_per_user",
    type_=int,
    env_default=0,
    tab="storage",
    label="Max Datasets per User (0=unlimited)",
)


async def get_all_registry_values(db: AsyncSession) -> dict[str, Any]:
    """Batch-load all registry settings in a single DB query.

    Returns a dict mapping each registered key to its effective value
    (DB override if present, otherwise env_default). Bypassed when
    ENV_ONLY_CONFIG is set — returns env_defaults directly without
    hitting the DB.

    .. note::
        Consumed only by tests today; kept as a forward-looking helper for
        an admin/settings dump endpoint that needs an atomic snapshot
        without N round-trips.
    """
    settings_dict: dict[str, Any] = {}

    if _is_env_only():
        for cfg in _registry:
            settings_dict[cfg.key] = cfg.env_default
        return settings_dict

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

BASEMAPS = PersistentConfig[list[dict[str, Any]]](
    key="basemaps",
    type_=list[dict[str, Any]],
    env_default=_DEFAULT_BASEMAPS,
    tab="map",
    label="Basemaps",
)

MAP_DEFAULTS = PersistentConfig[dict[str, float]](
    key="map_defaults",
    type_=dict[str, float],
    env_default=_DEFAULT_MAP_DEFAULTS,
    tab="map",
    label="Map Defaults",
)


# -- Plugins --
ENABLED_PLUGINS = PersistentConfig[list[str] | None](
    key="enabled_plugins",
    type_=list[str] | None,
    env_default=None,
    tab="map",
    label="Enabled Plugins",
)


def _default_role_permissions() -> dict:
    from app.core.permissions import DEFAULT_ROLE_PERMISSIONS

    return DEFAULT_ROLE_PERMISSIONS


ROLE_PERMISSIONS = PersistentConfig[dict[str, dict[str, bool]]](
    key="role_permissions",
    type_=dict[str, dict[str, bool]],
    env_default_factory=_default_role_permissions,
    tab="permissions",
    label="Role Permissions",
)

BRANDING_SHOW_BADGE = PersistentConfig[bool](
    key="branding.show_badge",
    type_=bool,
    env_default=True,
    tab="branding",
    label="Show Powered by GeoLens Footer Label",
)


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


def get_cached_semantic_search_rate_limit() -> int:
    """Sync accessor for slowapi callable -- reads from sync cache, falls back to default.

    SEC-S11: caps OpenAI embedding cost-DoS by limiting unique novel queries per IP.
    Default 30/min matches the audit recommendation for cost-sensitive endpoints.
    Configurable at runtime via the admin Settings UI / PUT /settings/ with key
    `semantic_search_rate_limit` (there is no SEMANTIC_SEARCH_RATE_LIMIT env var;
    Settings uses extra="ignore").
    """
    cached = _sync_rate_limit_cache.get("semantic_search_rate_limit")
    if cached and (time.monotonic() - cached[1]) < _CACHE_TTL:
        return cached[0]
    return _DEFAULT_SEMANTIC_SEARCH_RATE_LIMIT


def get_cached_basemap_proxy_rate_limit() -> int:
    """Sync accessor for slowapi callable -- reads from sync cache, falls back to default.

    SEC-S10: caps commercial-tier basemap key replay from anonymous clients.
    Default 120/min is loose enough for the SPA boot path (one call per page load
    across users behind a shared NAT) while still bounding attacker throughput.
    Configurable at runtime via the admin Settings UI / PUT /settings/ with key
    `basemap_proxy_rate_limit` (there is no BASEMAP_PROXY_RATE_LIMIT env var;
    Settings uses extra="ignore").
    """
    cached = _sync_rate_limit_cache.get("basemap_proxy_rate_limit")
    if cached and (time.monotonic() - cached[1]) < _CACHE_TTL:
        return cached[0]
    return _DEFAULT_BASEMAP_PROXY_RATE_LIMIT
