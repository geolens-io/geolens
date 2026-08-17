"""Settings API endpoints: unified admin settings, public basemaps/map-defaults/tile-config."""

import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.service import AuditEvent, audit_emit
from app.core.identity import Identity
from app.modules.auth.dependencies import require_mode_permission
from app.modules.auth.oauth import service as oauth_service
from app.modules.auth.oauth.schemas import (
    OAuthProviderCreate,
    OAuthProviderResponse,
    OAuthProviderUpdate,
)
from app.core.config import settings as app_settings
from app.core.dependencies import get_client_ip, get_db
from app.core.edition import is_enterprise
from app.core.persistent_config import (
    EMBEDDING_DIMS,
    EMBEDDING_MODEL,
    ENTERPRISE_ONLY_TABS,
    PASSWORD_LOGIN_ENABLED,
    _registry,
    apply_side_effects_batch,
)
from app.platform.ratelimit import limiter
from app.core.public_urls import (
    _is_env_only,
    get_public_api_url,
    get_public_app_url,
    get_shareable_app_url,
)
from app.core.db.models import AppSetting
from app.core.db.tenant_schema import tenant_data_schema
from app.core.tenancy import is_multi_tenant
from app.modules.settings.schemas import (
    SETTING_VALIDATORS,
    ApiKeyStatusResponse,
    ConfigModeResponse,
    DetectEmbeddingDimsResponse,
    EnterpriseTabsResponse,
    NotificationStatusResponse,
    NotificationTestChannelResult,
    NotificationTestResponse,
    SettingItem,
    SettingsAllResponse,
    SettingsResetRequest,
    SettingsUpdateRequest,
    TileConfigResponse,
)
from app.standards.ogc.errors import BAD_GATEWAY_RESPONSE, ERROR_RESPONSES_AUTH
from app.modules.settings.router_public import router as public_router

# Phase 1229 Plan 03 — channel functions imported at module level so tests can
# monkeypatch at `app.modules.settings.router.send_email` / `.post_webhook`
# (same discipline as app.platform.notifications.env_sink from Plan 02).
from app.platform.notifications.smtp_channel import send_email  # noqa: E402
from app.platform.notifications.webhook_channel import post_webhook  # noqa: E402

logger = structlog.stdlib.get_logger(__name__)

require_settings_admin = require_mode_permission(
    single_tenant="manage_settings", multi_tenant="manage_tenants"
)

router = APIRouter(prefix="/settings", tags=["Admin"], responses=ERROR_RESPONSES_AUTH)


# ---------------------------------------------------------------------------
# Setting-update helpers (extracted from route handler)
# ---------------------------------------------------------------------------


# Phase 279 ADMIN-09 (L-01): The PUT/RESET handlers below intentionally end with
# `return await get_all_settings(...)` to capture side-effects from
# rebuild_embedding_column rollback, validator coercion, and
# request-derived URL computation (public_app_url / public_api_url, computed
# from `request` in get_all_settings — NOT stored in AppSetting). An inline
# response construction would have to duplicate get_all_settings's body
# (registry iteration + value-source resolution + env-only handling). The
# second SELECT is cheaper to maintain than two parallel response builders.
# See the inline comment blocks at each return site for the full rationale.


def _validate_setting(key: str, value: object) -> object:
    """Run permission and custom validators for a setting key. Returns validated value."""
    if key == "role_permissions":
        from app.modules.auth.permissions import validate_permission_matrix

        validate_permission_matrix(value)

    validator = SETTING_VALIDATORS.get(key)
    if validator is not None:
        value = validator(value)

    return value


def _canonicalize_setting_value(key: str, value: object, cfg: object) -> object:
    """Run setting validation in the safe order and map failures to HTTP 422."""
    from pydantic import ValidationError as PydanticValidationError

    # Permission invariants must see the canonical booleans produced by the
    # adapter. Other custom validators intentionally pre-normalize their input.
    if key != "role_permissions":
        try:
            value = _validate_setting(key, value)
        except (ValueError, TypeError) as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Validation error for '{key}': {exc}",
            ) from exc

    try:
        value = cfg._adapter.validate_python(value)
    except PydanticValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Validation error for '{key}': {exc.errors()}",
        ) from exc

    if key == "role_permissions":
        try:
            value = _validate_setting(key, value)
        except (ValueError, TypeError) as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Validation error for '{key}': {exc}",
            ) from exc
    return value


_registry_by_key: dict[str, object] | None = None


def _get_registry_map() -> dict[str, object]:
    """Return a cached key→PersistentConfig lookup."""
    global _registry_by_key
    if _registry_by_key is None:
        _registry_by_key = {cfg.key: cfg for cfg in _registry}
    return _registry_by_key


def _require_enterprise_for_key(key: str) -> None:
    """Raise 404 if a setting key belongs to an enterprise-only tab.

    Returns 404 (not 403, no detail body) to match the ``require_enterprise()``
    guard contract — community callers cannot distinguish between "key does
    not exist" and "key requires enterprise edition", which prevents both
    feature leakage and trivial enumeration of paid keys.
    """
    from app.core.edition import is_enterprise

    if is_enterprise():
        return
    cfg = _get_registry_map().get(key)
    if cfg is not None and cfg.tab in ENTERPRISE_ONLY_TABS:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)


async def _probe_base_url(
    db: AsyncSession, provider_ext: object, requested: dict[str, object]
) -> object:
    """Endpoint the probe should call, honoring a URL this request publishes.

    When the request names neither URL key this is exactly
    ``resolve_runtime_config(db)["base_url"]``. When it names either, the
    provider's own chain is reproduced with each half taken from the request
    where present: EMBEDDING_BASE_URL -> OPENAI_BASE_URL -> None, then bound to
    the operator-approved destination. Clearing ``embedding_base_url`` in the
    same PUT therefore falls through to the ``openai_base_url`` that PUT sets,
    exactly as it will once the batch commits.

    ``resolve_runtime_config`` is deliberately not called on that branch. It
    reads COMMITTED configuration, which is the value the request is replacing,
    and it *raises* when that value is a stale row bound to a different
    destination than the environment credential.
    """
    if not ({"embedding_base_url", "openai_base_url"} & requested.keys()):
        runtime_config = await provider_ext.resolve_runtime_config(db)  # type: ignore[attr-defined]
        return runtime_config.get("base_url")

    from app.core.ai_credentials import bind_openai_credential_base_url
    from app.core.persistent_config import EMBEDDING_BASE_URL, OPENAI_BASE_URL

    embedding_url = (
        requested["embedding_base_url"]
        if "embedding_base_url" in requested
        else await EMBEDDING_BASE_URL.get_uncached(db)
    )
    openai_url = (
        requested["openai_base_url"]
        if "openai_base_url" in requested
        else await OPENAI_BASE_URL.get_uncached(db)
    )
    return bind_openai_credential_base_url(
        str(embedding_url or openai_url or "") or None, purpose="embedding"
    )


async def _probe_embedding_dims_for_model(
    db: AsyncSession, model: str, requested: dict[str, object]
) -> int:
    """Ask the provider for the natural output width of an explicitly named model.

    fix(#1529): ``probe_embedding_dimensions`` resolves the model from
    PersistentConfig, so it can only probe a model that is ALREADY published —
    which is the publish-then-probe ordering the issue is about. ``update_settings``
    needs the width of the model it is about to publish, at a point where nothing
    has been committed, so the model name is passed in rather than read back out.

    fix(#1538 review): the endpoint comes from ``requested`` too. Everything the
    probe resolves has to describe the configuration being published, not the
    one being replaced — the model was only half of that.

    Raises:
        EmbeddingUnavailableError: no embedding provider is configured, or the
            provider answered with an empty vector.
        Exception: whatever the provider SDK raises for a failed call.
    """
    from app.platform.extensions import get_embedding_provider
    from app.processing.embeddings.service import EmbeddingUnavailableError

    if not app_settings.openai_api_key:
        raise EmbeddingUnavailableError(
            "Embedding generation requires an OpenAI-compatible API key."
        )

    provider_ext = get_embedding_provider("openai_compatible")
    # dimensions=None means "discover the model's natural width" (Phase 231 D-02).
    # `model` carries no fallback to the runtime default on purpose: this path is
    # only reached when the request names embedding_model, and the community
    # provider's default_model IS the committed EMBEDDING_MODEL, so falling back
    # to it would probe the very model being replaced.
    vectors = await provider_ext.embed(
        texts=["dimension probe"],
        model=model,
        dimensions=None,
        base_url=await _probe_base_url(db, provider_ext, requested),
        timeout=30.0,
    )
    embedding = vectors[0] if vectors else []
    if not embedding:
        raise EmbeddingUnavailableError(
            f"Embedding probe for model '{model}' returned empty vector."
        )
    return len(embedding)


async def _detect_dims_for_requested_model(
    db: AsyncSession, model: str, requested: dict[str, object]
) -> int:
    """Probe ``model`` for ``update_settings``, mapping failures to HTTP status.

    Same mapping as POST /settings/detect-embedding-dims: a missing provider is
    a 422, any other provider failure is a 502. Both are raised BEFORE anything
    is committed, so a failed probe leaves the previous model/dimension pair
    exactly as it was.
    """
    from app.processing.embeddings.service import EmbeddingUnavailableError

    try:
        return await _probe_embedding_dims_for_model(db, model, requested)
    except EmbeddingUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Cannot detect the dimension count for embedding model '{model}': "
                f"{exc} Send embedding_dims alongside embedding_model to publish "
                "the pair explicitly."
            ),
        ) from exc
    except Exception as exc:  # broad: third-party embedding SDK can throw provider-specific errors; map to 502
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=(
                f"Embedding probe for model '{model}' failed: {exc}. Neither "
                "embedding_model nor embedding_dims was changed."
            ),
        ) from exc


# ---------------------------------------------------------------------------
# Unified admin endpoints
# ---------------------------------------------------------------------------


# ROUTE-01 (Phase 1092): dual-shape decorator — both trailing-slash and
# no-trailing-slash variants register against the same handler. Slash form
# stays canonical (already in OpenAPI); no-slash is a hidden alias closing
# the 404 regression introduced by redirect_slashes=False (api/main.py).
@router.get("/all", response_model=SettingsAllResponse, include_in_schema=False)
@router.get("/all/", response_model=SettingsAllResponse)
async def get_all_settings(
    request: Request,
    _user: Identity = Depends(require_settings_admin),
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
        if not enterprise and cfg.tab in ENTERPRISE_ONLY_TABS:
            continue
        if cfg.key == "public_app_url":
            value = await get_public_app_url(db, request=request)
        elif cfg.key == "public_api_url":
            value = await get_public_api_url(db, request=request)
        elif not env_only and cfg.key in db_settings:
            # BUG-030: in ENV_ONLY_CONFIG mode, PersistentConfig.get short-
            # circuits to env_default and DB rows are dead data at runtime.
            # Resolving from db_settings here would surface stale overrides
            # that are NOT in effect; show the effective env_default instead.
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


# ROUTE-01 (Phase 1092): dual-shape decorator — see /all above.
@router.get(
    "/enterprise-tabs",
    response_model=EnterpriseTabsResponse,
    include_in_schema=False,
)
@router.get(
    "/enterprise-tabs/",
    response_model=EnterpriseTabsResponse,
    # fix(scripts/deployed_surface_gate.json#enterprise_tabs_op): neutral summary
    # replacing the auto-derived "Get Enterprise Only Tabs" banned public-copy id;
    # operationId/path unchanged.
    summary="List restricted settings tabs",
)
async def get_enterprise_only_tabs(
    _user: Identity = Depends(require_settings_admin),
) -> EnterpriseTabsResponse:
    """Return the canonical list of restricted Settings tab keys.

    The frontend AdminSidebar uses this to avoid rendering tabs that the
    current runtime does not expose. The backend write gate uses the same set
    to reject writes to restricted settings, keeping UI and API behavior
    aligned.
    """
    # Sort for stable JSON output (downstream tests rely on deterministic order)
    return EnterpriseTabsResponse(tabs=sorted(ENTERPRISE_ONLY_TABS))


# ROUTE-01 (Phase 1092): dual-shape decorator — see /all above. The empty
# path "" registers PUT /settings (prefix-only, no trailing slash).
@router.put("", response_model=SettingsAllResponse, include_in_schema=False)
@router.put("/", response_model=SettingsAllResponse)
@limiter.limit("30/minute")  # HARDEN-02: rate-limit settings mutations per client IP
async def update_settings(
    body: SettingsUpdateRequest,
    request: Request,
    user: Identity = Depends(require_settings_admin),
    db: AsyncSession = Depends(get_db),
) -> SettingsAllResponse:
    """Update one or more settings (admin only). Returns updated settings."""
    registry_map = _get_registry_map()

    # BUG-009 (Phase 1181): Validate ALL keys BEFORE applying any side effect.
    # Previously, the loop applied each key inline — if key N was invalid, keys
    # 0..N-1 were already persisted (or their side effects fired), producing
    # partial/corrupt state.  The two-pass approach below:
    #   Pass 1 — validate every key (unknown-key check, enterprise gate,
    #             custom validators, TypeAdapter type-level validation).
    #             On any error, raise 400/422 immediately with NOTHING applied.
    #   Pass 2 — apply all validated values (commit=False per key, single
    #             commit at the end — no change from before).
    validated_settings: dict[str, object] = {}
    for key, value in body.settings.items():
        cfg = registry_map.get(key)
        if cfg is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unknown setting key: {key}",
            )

        _require_enterprise_for_key(key)

        validated_settings[key] = _canonicalize_setting_value(key, value, cfg)

    # fix(#1529): publish embedding_model and its detected width ATOMICALLY.
    # The probe runs HERE — before the provider row locks below, before any
    # value is staged, and before the batch commit — and its result joins the
    # same batch, so the pair lands in one transaction. A reader therefore sees
    # the old pair or the new pair and never the new model beside the old
    # model's dimension count, and a failed probe leaves both values untouched.
    #
    # Folding the detected width into validated_settings also puts auto-detect
    # on the SAME commit-and-rebuild path as an explicitly named embedding_dims.
    # The two used to be mutually exclusive branches, which is how a detected
    # width could be persisted while the vector column kept the old one.
    #
    # Probing ahead of the SSO guard is deliberate: that guard row-locks the
    # enabled OAuth providers, and holding those locks across a provider
    # network call would serialize unrelated provider mutations behind it.
    #
    # The whole validated batch is handed to the probe, not just the model:
    # a PUT can change the endpoint in the same request, and the probe has to
    # describe the configuration being published (see _probe_base_url).
    if (
        "embedding_model" in validated_settings
        and "embedding_dims" not in validated_settings
        # In ENV_ONLY_CONFIG mode every cfg.set() below raises 403, so probing
        # would only burn a provider call on a request that cannot land.
        and not _is_env_only()
    ):
        requested_model = str(validated_settings["embedding_model"])
        # Uncached on purpose: a stale cache entry naming the requested model
        # would skip the probe and publish that model with an unrelated width.
        if requested_model != await EMBEDDING_MODEL.get_uncached(db):
            validated_settings["embedding_dims"] = _canonicalize_setting_value(
                "embedding_dims",
                await _detect_dims_for_requested_model(
                    db, requested_model, validated_settings
                ),
                registry_map["embedding_dims"],
            )

    # SSO-04 (Phase 1236 Plan 02): lockout guard — refuse to disable password
    # login when zero enabled OAuth providers exist.  This runs AFTER Pass-1
    # validation but BEFORE the apply loop so nothing is persisted on rejection.
    # An admin with manage_settings retains break-glass password-login regardless,
    # but we still prevent the foot-gun of locking out the entire org.
    #
    # Codex P2 (concurrency): row-lock the enabled providers (FOR UPDATE) so a
    # concurrent provider-disable/delete (which locks the same rows) is serialized
    # against this check — the two can no longer both pass and together remove the
    # last provider while disabling password login. Replaces the reverted global
    # advisory lock (898048b2); see oauth_service.lock_enabled_providers.
    if validated_settings.get("password_login_enabled") is False:
        locked_provider_ids = await oauth_service.lock_enabled_providers(db)
        if len(locked_provider_ids) == 0:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    "Cannot disable password login while no SSO provider is enabled "
                    "— enable an OAuth provider first"
                ),
            )

    # Capture the previous embedding pair before any changes (rollback source
    # for the column rebuild below). Uncached so the rollback restores what is
    # actually committed rather than a cache entry that may already be stale.
    old_dims_value: int | None = None
    old_model_value: str | None = None
    rollback_model = False
    if "embedding_dims" in validated_settings:
        old_dims_value = await EMBEDDING_DIMS.get_uncached(db)
        # fix(#1529): a request that publishes both halves has to roll back
        # both halves. Restoring embedding_dims alone would leave the NEW model
        # standing beside the OLD width — the mismatched pair, reached through
        # the failure path instead of the probe window.
        rollback_model = "embedding_model" in validated_settings
        if rollback_model:
            old_model_value = await EMBEDDING_MODEL.get_uncached(db)

    ip = get_client_ip(request)
    for key, value in validated_settings.items():
        cfg = registry_map[key]
        await cfg.set(db, value, user_id=user.id, ip_address=ip, commit=False)

    # Single commit for all setting writes
    await db.commit()

    # fix(#430 codex r3): set(commit=False) defers its side effects (cache
    # invalidation, _on_change runtime hooks, sync rate-limit warm) so a
    # rollback can't leave process-local state diverged from the DB. Apply
    # them now that the batch is durable.
    # fix(#1543): as ONE step, not a per-key loop — the loop left a window in
    # which a reader saw the already-evicted keys at their new values and the
    # rest at their cached old ones.
    await apply_side_effects_batch(
        [(registry_map[key], value) for key, value in validated_settings.items()]
    )

    # Rebuild column + index when embedding dimensions change. An auto-detected
    # width reaches this branch too (#1529): it was added to validated_settings
    # above, so the column follows every published width, not only the ones an
    # admin typed.
    if "embedding_dims" in validated_settings:
        from app.processing.embeddings.service import rebuild_embedding_column

        new_dims = int(validated_settings["embedding_dims"])
        try:
            await rebuild_embedding_column(db, new_dims)
        except Exception as exc:  # broad: DDL rebuild can fail for schema/lock reasons; roll setting back atomically
            # Roll the published pair back to its previous value(s) in ONE
            # transaction — same reason the forward publish is one transaction.
            # Side effects follow the commit, never precede it (fix #430 codex
            # r3): invalidating the cache first lets a concurrent reader
            # repopulate it with the value being rolled back.
            await EMBEDDING_DIMS.set(
                db, old_dims_value, user_id=user.id, ip_address=ip, commit=False
            )
            if rollback_model:
                await EMBEDDING_MODEL.set(
                    db, old_model_value, user_id=user.id, ip_address=ip, commit=False
                )
            await db.commit()
            # fix(#1543): and in ONE step, for the same reason the rollback is
            # one transaction. Evicting the two keys in sequence would put the
            # mismatched pair back into readable state on the way out of a
            # rollback whose whole purpose is to prevent it.
            rolled_back: list[tuple] = [(EMBEDDING_DIMS, old_dims_value)]
            if rollback_model:
                rolled_back.append((EMBEDDING_MODEL, old_model_value))
            await apply_side_effects_batch(rolled_back)
            logger.exception(
                "Embedding column rebuild failed, rolling back the embedding pair",
                old_dims=old_dims_value,
                new_dims=new_dims,
                old_model=old_model_value if rollback_model else None,
                rolled_back_model=rollback_model,
            )
            raise HTTPException(
                status_code=503,
                detail=(
                    "Embedding column rebuild failed. The embedding settings have "
                    "been reverted to their previous values."
                ),
            ) from exc

    # Phase 279 ADMIN-09 (L-01): The second get_all_settings() call is INTENTIONAL.
    # update_settings can persist values the request body does not name:
    #   1. an auto-detected embedding_dims (#1529) joins validated_settings
    #      before the apply loop when embedding_model changes on its own.
    #   2. rebuild_embedding_column failure (above) -- rolls the published
    #      embedding pair back to its previous value(s) if the DDL fails.
    #   3. .set() with commit=False above batches the writes; the final commit
    #      may differ from the request body if a validator coerced the value.
    # Additionally, get_all_settings computes public_app_url / public_api_url from
    # the request object, which the request-body iteration does not. An inline
    # construction would have to duplicate ALL of that logic; the second SELECT
    # is cheaper to maintain than two parallel response builders.
    return await get_all_settings(request=request, _user=user, db=db)


# ROUTE-01 (Phase 1092): dual-shape decorator — see /all above.
@router.post("/reset", response_model=SettingsAllResponse, include_in_schema=False)
@router.post("/reset/", response_model=SettingsAllResponse)
@limiter.limit("30/minute")
async def reset_settings(
    body: SettingsResetRequest,
    request: Request,
    user: Identity = Depends(require_settings_admin),
    db: AsyncSession = Depends(get_db),
) -> SettingsAllResponse:
    """Reset one or more settings to their defaults (admin only). Returns updated settings."""
    registry_map = _get_registry_map()

    # Resolve and authorize the complete batch before staging any deletes. A
    # later unknown or restricted key therefore cannot leave earlier resets
    # committed as a partial request.
    configs_to_reset = []
    for key in body.keys:
        cfg = registry_map.get(key)
        if cfg is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unknown setting key: {key}",
            )
        _require_enterprise_for_key(key)
        configs_to_reset.append(cfg)

    # Reset is another way to change the effective password-login value and
    # must enforce the same final-state lockout invariant as PUT/import. Hold
    # the provider locks through the settings transaction so a concurrent IdP
    # disable/delete cannot race this check.
    if (
        PASSWORD_LOGIN_ENABLED in configs_to_reset
        and PASSWORD_LOGIN_ENABLED.env_default is False
    ):
        locked_provider_ids = await oauth_service.lock_enabled_providers(db)
        if len(locked_provider_ids) == 0:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    "Cannot reset password login to disabled while no SSO provider "
                    "is enabled — enable an OAuth provider first"
                ),
            )

    ip = get_client_ip(request)
    for cfg in configs_to_reset:
        await cfg.reset(
            db,
            user_id=user.id,
            ip_address=ip,
            commit=False,
        )

    # The setting deletes and their audit rows form one transaction. Runtime
    # caches/hooks are changed only after that transaction is durable, and in
    # one step so no reader sees a half-reset batch (fix #1543).
    await db.commit()
    await apply_side_effects_batch([(cfg, cfg.env_default) for cfg in configs_to_reset])

    # Phase 279 ADMIN-09 (L-01): Intentional second SELECT. cfg.reset() writes
    # the env_default value back to AppSetting; we re-read to capture the
    # post-reset state (which may differ from the env_default if a derivation
    # function -- see public_app_url / public_api_url computation in
    # get_all_settings -- runs at response-build time).
    return await get_all_settings(request=request, _user=user, db=db)


# ROUTE-01 (Phase 1092): dual-shape decorator — see /all above.
@router.get(
    "/api-key-status",
    response_model=ApiKeyStatusResponse,
    include_in_schema=False,
)
@router.get("/api-key-status/", response_model=ApiKeyStatusResponse)
async def get_api_key_status(
    _user: Identity = Depends(require_settings_admin),
) -> ApiKeyStatusResponse:
    """Return which LLM API keys are configured (without exposing values)."""
    return ApiKeyStatusResponse(
        anthropic_configured=bool(app_settings.anthropic_api_key),
        openai_configured=bool(app_settings.openai_api_key),
    )


# ROUTE-01 (Phase 1092): dual-shape decorator — see /all above.
@router.post(
    "/detect-embedding-dims",
    response_model=DetectEmbeddingDimsResponse,
    include_in_schema=False,
)
@router.post(
    "/detect-embedding-dims/",
    response_model=DetectEmbeddingDimsResponse,
    responses={502: BAD_GATEWAY_RESPONSE},
)
async def detect_embedding_dims(
    _user: Identity = Depends(require_settings_admin),
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
    except Exception as e:  # broad: third-party embedding SDK can throw provider-specific errors; map to 502
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Embedding probe failed: {e}",
        )

    return DetectEmbeddingDimsResponse(dimensions=dims)


# ROUTE-01 (Phase 1092): dual-shape decorator — see /all above.
@router.get(
    "/notifications/status",
    response_model=NotificationStatusResponse,
    include_in_schema=False,
)
@router.get("/notifications/status/", response_model=NotificationStatusResponse)
async def get_notification_status(
    _user: Identity = Depends(require_settings_admin),
) -> NotificationStatusResponse:
    """Return which notification channels are configured (booleans only — no secrets).

    Mirrors get_api_key_status: returns presence flags derived from env/settings
    without ever echoing the SMTP password, webhook URL, or webhook secret
    (NOTIF-05 / T-1229-09).
    """
    return NotificationStatusResponse(
        notifications_enabled=app_settings.notifications_enabled,
        smtp_configured=bool(app_settings.smtp_host),
        webhook_configured=bool(app_settings.notification_webhook_url),
    )


# ROUTE-01 (Phase 1092): dual-shape decorator — see /all above.
@router.post(
    "/notifications/test",
    response_model=NotificationTestResponse,
    include_in_schema=False,
)
@router.post("/notifications/test/", response_model=NotificationTestResponse)
async def send_test_notification(
    request: Request,
    user: Identity = Depends(require_settings_admin),
    db: AsyncSession = Depends(get_db),
) -> NotificationTestResponse:
    """Send a canned test notification through each configured channel (admin only).

    Mirrors detect_embedding_dims: admin-gated probe that reports per-channel
    reachable/error in a 200 body without leaking secrets or raising 5xx on a
    bad channel (NOTIF-06 / T-1229-08 / T-1229-09 / T-1229-10).

    Per-channel approach (not EnvConfiguredNotificationSink.deliver) is used so
    each channel's success/failure is captured in its own
    NotificationTestChannelResult for display in the admin UI.
    """
    from app.platform.extensions.protocols import Notification

    # send_email / post_webhook are module-level imports (see top of function
    # module section) so tests can monkeypatch at
    # app.modules.settings.router.send_email / .post_webhook — same discipline
    # as app.platform.notifications.env_sink (Plan 02 decision).
    # Canned test payload — generic enough for both SMTP and webhook channels.
    test_notification = Notification(
        event_type="test",
        subject="GeoLens test notification",
        body="This is a test notification from GeoLens settings.",
        data={"source": "admin-test-send"},
    )

    # Master toggle: if notifications are disabled, report immediately.
    if not app_settings.notifications_enabled:
        return NotificationTestResponse(
            sent=False,
            channels=[],
            message="Notifications are disabled (NOTIFICATIONS_ENABLED=false).",
        )

    # Determine which channels are configured.
    channel_fns: list[tuple[str, object]] = []
    if app_settings.smtp_host:
        channel_fns.append(("smtp", send_email))
    if app_settings.notification_webhook_url:
        channel_fns.append(("webhook", post_webhook))

    if not channel_fns:
        return NotificationTestResponse(
            sent=False,
            channels=[],
            message="No notification channel is configured.",
        )

    # Invoke each channel individually and collect per-channel results.
    results: list[NotificationTestChannelResult] = []
    any_ok = False

    for name, channel_fn in channel_fns:
        try:
            await channel_fn(test_notification)  # type: ignore[call-arg]
            results.append(
                NotificationTestChannelResult(channel=name, ok=True, error=None)
            )
            any_ok = True
        except Exception as exc:  # noqa: BLE001 — per-channel isolation; channel failure → 200 body, not 5xx
            # Safe error string: exception TYPE name + short class-level message only.
            # NEVER interpolate exc.args or str(exc) — those may echo the SMTP
            # password, webhook URL, or webhook secret (T-1229-09).
            safe_error = f"{type(exc).__name__}: channel delivery failed"
            results.append(
                NotificationTestChannelResult(channel=name, ok=False, error=safe_error)
            )

    message = (
        "Test notification sent successfully."
        if any_ok
        else "Test notification failed on all configured channels."
    )

    await audit_emit(
        db,
        AuditEvent(
            user_id=user.id,
            action="notification.test_sent",
            resource_type="settings",
            resource_id=None,
            details={
                "channels": [r.channel for r in results],
                "any_ok": any_ok,
            },
            ip_address=get_client_ip(request),
        ),
    )
    # Persist the audit row (M2 — Codex review): this endpoint's session is not
    # auto-committed, so without an explicit commit the test-send audit is lost.
    await db.commit()

    return NotificationTestResponse(sent=any_ok, channels=results, message=message)


# ROUTE-01 (Phase 1092): dual-shape decorator — see /all above.
@router.get("/config-mode", response_model=ConfigModeResponse, include_in_schema=False)
@router.get("/config-mode/", response_model=ConfigModeResponse)
async def get_config_mode() -> ConfigModeResponse:
    """Return whether the app is in env-only config mode (public, no auth)."""
    return ConfigModeResponse(env_only=_is_env_only())


# ---------------------------------------------------------------------------
# OAuth provider CRUD (admin only)
# ---------------------------------------------------------------------------


# Audit-log redaction allowlist. SECRET_FIELDS is the authoritative set used
# when diffing old_values snapshots (which contain the internal encrypted
# column ``client_secret_encrypted``). SECRET_BODY_FIELDS is the user-input
# subset — body fields a caller can submit; ``client_secret_encrypted`` is
# excluded because it's an internal column name and would never appear in
# request bodies (per checker WARNING #3 — iterating it in the body-detection
# loop is dead code). Pitfall 9 mitigation (HIGH severity, T-217-03-AUDIT-LEAK).
SECRET_FIELDS = {"idp_certificate", "client_secret_encrypted", "client_secret"}
SECRET_BODY_FIELDS = {"idp_certificate", "client_secret"}


def _snapshot_provider(provider) -> dict:
    """Snapshot non-secret OAuth/SAML provider fields for audit-log diffing.

    Only includes fields whose old/new values are safe to log verbatim. Secret
    fields are NEVER included here — they are flagged as "<redacted>" by the
    body-detection loop in ``update_oauth_provider`` if the request body
    submitted a new value, OR by the SECRET_FIELDS membership check when
    comparing old_values to new state. Avoiding them here also dodges the
    deferred-load trap on community DBs where SAML columns may not exist
    (Pitfall 11) — we read attributes that are loaded by the default SELECT.
    """
    return {
        "group_claim": provider.group_claim,
        "group_role_mapping": provider.group_role_mapping,
        "default_role": provider.default_role,
        "enabled": provider.enabled,
        # SAML fields (deferred=True on the ORM); these have already been
        # loaded by the SAML admin path's undefer_group("saml") call OR by
        # the previous get_provider_by_id() that the update endpoint did.
        # Reading from __dict__ avoids triggering an implicit deferred load
        # (which would fail with MissingGreenlet on community DBs that lack
        # the columns).
        "idp_entity_id": provider.__dict__.get("idp_entity_id"),
        "idp_sso_url": provider.__dict__.get("idp_sso_url"),
        "sp_entity_id": provider.__dict__.get("sp_entity_id"),
    }


# ROUTE-01 (Phase 1092): dual-shape decorator — see /all above.
@router.get(
    "/oauth-providers",
    response_model=list[OAuthProviderResponse],
    include_in_schema=False,
)
@router.get("/oauth-providers/", response_model=list[OAuthProviderResponse])
async def list_oauth_providers(
    _user: Identity = Depends(require_settings_admin),
    db: AsyncSession = Depends(get_db),
) -> list[OAuthProviderResponse]:
    """List all OAuth providers (admin only)."""
    providers = await oauth_service.list_providers(db)
    return [OAuthProviderResponse.model_validate(p) for p in providers]


# ROUTE-01 (Phase 1092): dual-shape decorator — see /all above.
@router.post(
    "/oauth-providers",
    response_model=OAuthProviderResponse,
    status_code=status.HTTP_201_CREATED,
    include_in_schema=False,
)
@router.post(
    "/oauth-providers/",
    response_model=OAuthProviderResponse,
    status_code=status.HTTP_201_CREATED,
)
@limiter.limit("30/minute")
async def create_oauth_provider(
    body: OAuthProviderCreate,
    request: Request,
    user: Identity = Depends(require_settings_admin),
    db: AsyncSession = Depends(get_db),
) -> OAuthProviderResponse:
    """Create a new OAuth or SAML provider (admin only).

    Audit-log payload includes the full ``created`` snapshot with non-secret
    fields verbatim and ``<redacted>`` markers for secrets that were submitted
    in the request body (SAML-12 / Pitfall 9 / T-217-03-AUDIT-LEAK).
    """
    try:
        provider = await oauth_service.create_provider(db, body)
    except oauth_service.OAuthProviderConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    ip = get_client_ip(request)

    created_state = {
        "slug": provider.slug,
        "display_name": provider.display_name,
        "provider_type": provider.provider_type,
        "default_role": provider.default_role,
        "group_claim": provider.group_claim,
        "group_role_mapping": provider.group_role_mapping,
        "enabled": provider.enabled,
        # SAML fields — read body (input) values directly to avoid deferred
        # load on the just-created ORM instance. body.idp_entity_id is the
        # value the admin submitted; for OAuth providers it's None (filtered
        # out of the snapshot).
        "idp_entity_id": body.idp_entity_id,
        "idp_sso_url": body.idp_sso_url,
        "sp_entity_id": body.sp_entity_id,
    }
    # Mark presence (NOT value) of secrets — iterate only over user-input
    # field names since SECRET_BODY_FIELDS excludes the internal
    # client_secret_encrypted column.
    if body.client_secret:
        created_state["client_secret"] = "<redacted>"
    if body.idp_certificate:
        created_state["idp_certificate"] = "<redacted>"

    await audit_emit(
        db,
        AuditEvent(
            user_id=user.id,
            action="oauth_provider.create",
            resource_type="oauth_provider",
            resource_id=provider.id,
            details={"slug": body.slug, "created": created_state},
            ip_address=ip,
        ),
    )
    await db.commit()
    return OAuthProviderResponse.model_validate(provider)


@router.put(
    "/oauth-providers/{provider_id}",
    response_model=OAuthProviderResponse,
)
@limiter.limit("30/minute")
async def update_oauth_provider(
    provider_id: uuid.UUID,
    body: OAuthProviderUpdate,
    request: Request,
    user: Identity = Depends(require_settings_admin),
    db: AsyncSession = Depends(get_db),
) -> OAuthProviderResponse:
    """Update an existing OAuth or SAML provider (admin only).

    Audit-log payload contains ``details.changes`` with per-field
    ``{"old": ..., "new": ...}`` diffs. Secret fields (idp_certificate,
    client_secret_encrypted, client_secret) are redacted as
    ``{"old": "<redacted>", "new": "<redacted>"}`` (Pitfall 9 / SAML-12 /
    T-217-03-AUDIT-LEAK HIGH severity).
    """
    provider = await oauth_service.get_provider_by_id(db, provider_id)
    if provider is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="OAuth provider not found"
        )
    if not is_enterprise() and provider.provider_type == "saml":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    # CR-02 (Phase 1236 Plan 03): lockout guard — mirror the update_settings
    # guard but applied to the provider PATCH side.  When password_login_enabled
    # is False AND this update would disable the last enabled OAuth provider,
    # refuse the operation.  We count enabled providers EXCLUDING the target so
    # that disabling a provider when >=2 others are enabled is still allowed.
    # The guard fires BEFORE any persist so nothing is written on rejection.
    #
    # Codex P2 (concurrency): row-lock the enabled providers FIRST — before
    # reading password_login_enabled — so a concurrent password-disable cannot
    # flip the flag between our read and our write. Counting from the locked set
    # (rather than a fresh COUNT) keeps the decision consistent with the rows we
    # hold. See oauth_service.lock_enabled_providers.
    update_data = body.model_dump(exclude_unset=True)
    if update_data.get("enabled") is False:
        locked_provider_ids = await oauth_service.lock_enabled_providers(db)
        # Cache-bypass read: a concurrent password-disable invalidates the cache
        # before its commit, so a stale `true` could be repopulated by another
        # reader; reading the committed DB value under the held lock avoids it.
        if not await PASSWORD_LOGIN_ENABLED.get_uncached(db):
            enabled_others = [pid for pid in locked_provider_ids if pid != provider_id]
            if len(enabled_others) == 0:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=(
                        "Cannot disable the last SSO provider while password login is disabled "
                        "— enable another OAuth provider or re-enable password login first"
                    ),
                )

    # Snapshot non-secret fields BEFORE the update so we can diff old vs. new.
    old_values = _snapshot_provider(provider)

    try:
        provider = await oauth_service.update_provider(db, provider, body)
    except oauth_service.OAuthProviderConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    # Build the changes diff. SECRET_FIELDS membership flips any matching
    # field's diff to <redacted>/<redacted> — protects against future
    # additions to old_values that accidentally include a secret field.
    # Read NEW values via __dict__ directly (NOT getattr) to avoid triggering
    # a deferred lazy-load on community DBs where SAML columns may not exist
    # (Pitfall 11). Non-deferred fields are populated by the ORM on refresh.
    changes: dict[str, dict] = {}
    new_snapshot = _snapshot_provider(provider)
    for field, old in old_values.items():
        new = new_snapshot.get(field)
        if old != new:
            if field in SECRET_FIELDS:
                changes[field] = {"old": "<redacted>", "new": "<redacted>"}
            else:
                changes[field] = {"old": old, "new": new}

    # Detect secret-field changes via the body (since they're not in old_values
    # snapshot — we never log secret old values, even pre-redaction). Iterate
    # ONLY over user-input field names: client_secret_encrypted is internal-only
    # and would never appear in body.model_dump() (per checker WARNING #3).
    body_dict = body.model_dump(exclude_unset=True)
    for secret_field in SECRET_BODY_FIELDS:
        if body_dict.get(secret_field) is not None:
            changes[secret_field] = {"old": "<redacted>", "new": "<redacted>"}

    ip = get_client_ip(request)
    await audit_emit(
        db,
        AuditEvent(
            user_id=user.id,
            action="oauth_provider.update",
            resource_type="oauth_provider",
            resource_id=provider.id,
            details={"slug": provider.slug, "changes": changes},
            ip_address=ip,
        ),
    )
    await db.commit()
    return OAuthProviderResponse.model_validate(provider)


@router.delete(
    "/oauth-providers/{provider_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
@limiter.limit("30/minute")
async def delete_oauth_provider(
    provider_id: uuid.UUID,
    request: Request,
    user: Identity = Depends(require_settings_admin),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete an OAuth or SAML provider (admin only).

    Audit-log payload contains a ``deleted`` snapshot with the pre-delete
    state — non-secret fields verbatim, secret fields marked ``<redacted>``
    if they were previously set (T-217-03-AUDIT-LEAK mitigation extends to
    delete events too).
    """
    provider = await oauth_service.get_provider_by_id(db, provider_id)
    if provider is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="OAuth provider not found"
        )

    # CR-02 (Phase 1236 Plan 03): lockout guard for delete — same policy as
    # the update guard above.  Deleting the last enabled SSO provider when
    # password_login_enabled is False would lock everyone out.  Count enabled
    # providers EXCLUDING the target; if zero remain, refuse.
    # Only applies when the provider being deleted is currently enabled.
    #
    # Codex P2 (concurrency): row-lock the enabled providers FIRST (before the
    # password_login_enabled read) and count from the locked set — same
    # serialization as the update guard. See oauth_service.lock_enabled_providers.
    if provider.enabled:
        locked_provider_ids = await oauth_service.lock_enabled_providers(db)
        # Cache-bypass read (see update_oauth_provider): observe the committed
        # password_login_enabled under the held provider lock, not a stale cache.
        if not await PASSWORD_LOGIN_ENABLED.get_uncached(db):
            enabled_others = [pid for pid in locked_provider_ids if pid != provider_id]
            if len(enabled_others) == 0:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=(
                        "Cannot delete the last SSO provider while password login is disabled "
                        "— enable another OAuth provider or re-enable password login first"
                    ),
                )

    slug = provider.slug
    deleted_state = {
        "slug": provider.slug,
        "display_name": provider.display_name,
        "provider_type": provider.provider_type,
        "default_role": provider.default_role,
        "group_claim": provider.group_claim,
        "group_role_mapping": provider.group_role_mapping,
        "enabled": provider.enabled,
        "idp_entity_id": provider.__dict__.get("idp_entity_id"),
        "idp_sso_url": provider.__dict__.get("idp_sso_url"),
        "sp_entity_id": provider.__dict__.get("sp_entity_id"),
    }
    # Mark presence of secrets — use SECRET_FIELDS allowlist here because the
    # snapshot reads from the existing provider row (which DOES carry the
    # internal client_secret_encrypted column, unlike the body-input loop).
    if provider.client_secret_encrypted:
        deleted_state["client_secret"] = "<redacted>"
    if provider.__dict__.get("idp_certificate"):
        deleted_state["idp_certificate"] = "<redacted>"

    await oauth_service.delete_provider(db, provider)
    ip = get_client_ip(request)
    await audit_emit(
        db,
        AuditEvent(
            user_id=user.id,
            action="oauth_provider.delete",
            resource_type="oauth_provider",
            resource_id=provider_id,
            details={"slug": slug, "deleted": deleted_state},
            ip_address=ip,
        ),
    )
    await db.commit()


# ---------------------------------------------------------------------------
# Public endpoints (no auth required)
# ---------------------------------------------------------------------------


# ROUTE-01 (Phase 1092): dual-shape decorator — see /all above.
@public_router.get(
    "/tile-config", response_model=TileConfigResponse, include_in_schema=False
)
@public_router.get("/tile-config/", response_model=TileConfigResponse)
async def get_tile_config(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> TileConfigResponse:
    """Return tile delivery configuration (public, no auth required)."""
    # fix(#1548 review r9/r10): not the resolver. This field's only consumer is
    # share-URL generation (frontend/src/lib/public-urls.ts), and a resolver
    # INFERRED value is not the origin a browser presents when it loads the
    # embed shell: it can be an ``/api``-stripped PUBLIC_API_URL for a split
    # app/API deployment, or the caller's own request headers. Handing either to
    # the share builder produces /m/ and /card links pointing at a host that does
    # not serve them. A hosted tenant's ``tenant_public_origin`` is a different
    # thing — middleware-validated against the tenant registry, and the only
    # origin that is right there — so get_shareable_app_url returns it and falls
    # back to the explicit fleet setting otherwise. Null when neither exists,
    # which that module treats as unconfigured.
    public_app_url = await get_shareable_app_url(db, request=request)
    public_api_url = await get_public_api_url(db, request=request)
    tenant_id = getattr(getattr(request, "state", None), "tenant_id", None)
    mvt_source_layer_prefix = (
        None
        if is_multi_tenant() and tenant_id is None
        else tenant_data_schema(tenant_id)
    )
    return TileConfigResponse(
        cdn_base_url=app_settings.cdn_base_url,
        public_app_url=public_app_url,
        public_api_url=public_api_url,
        public_base_url=public_api_url,
        mvt_source_layer_prefix=mvt_source_layer_prefix,
    )
