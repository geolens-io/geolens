"""Config export, import (merge/overwrite), dry-run, and connectivity validation."""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx
import structlog
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.oauth.schemas import OAuthProviderCreate, OAuthProviderUpdate
from app.auth.permissions import validate_permission_matrix
from app.config_ops.schemas import (
    ConnectivityResult,
    DryRunResponse,
    ImportMode,
    ImportResult,
    OAuthProviderChange,
    ServiceProbeResult,
    SettingChange,
)
from app.settings.schemas import SETTING_VALIDATORS

logger = structlog.stdlib.get_logger(__name__)

_EXPORT_VERSION = "1.0"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _provider_to_dict(provider: Any) -> dict:
    """Convert an OAuthProvider ORM object to a dict, omitting encrypted secret."""
    return {
        "slug": provider.slug,
        "display_name": provider.display_name,
        "provider_type": provider.provider_type,
        "client_id": provider.client_id,
        "discovery_url": provider.discovery_url,
        "authorize_url": provider.authorize_url,
        "token_url": provider.token_url,
        "userinfo_url": provider.userinfo_url,
        "scopes": provider.scopes,
        "default_role": provider.default_role,
        "group_claim": provider.group_claim,
        "group_role_mapping": provider.group_role_mapping,
        "enabled": provider.enabled,
    }


_PROVIDER_COMPARE_FIELDS = [
    "display_name",
    "provider_type",
    "client_id",
    "discovery_url",
    "authorize_url",
    "token_url",
    "userinfo_url",
    "scopes",
    "default_role",
    "group_claim",
    "group_role_mapping",
    "enabled",
]


def _diff_provider(existing_dict: dict, imported: dict) -> list[str]:
    """Return list of fields that differ between existing and imported provider."""
    changed = []
    for field in _PROVIDER_COMPARE_FIELDS:
        if field in imported and imported[field] != existing_dict.get(field):
            changed.append(field)
    return changed


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------


async def export_config(db: AsyncSession) -> dict:
    """Export all PersistentConfig settings and OAuth providers as a dict.

    OAuth provider secrets are redacted (client_secret_encrypted omitted).
    """
    from app.persistent_config import _registry
    from app.auth.oauth import service as oauth_service

    # Collect all setting values
    settings_dict: dict[str, Any] = {}
    for cfg in _registry:
        settings_dict[cfg.key] = await cfg.get(db)

    # Collect OAuth providers (without secrets)
    providers = await oauth_service.list_providers(db)
    providers_list = [_provider_to_dict(p) for p in providers]

    export = {
        "version": _EXPORT_VERSION,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "settings": settings_dict,
        "oauth_providers": providers_list,
    }

    logger.info(
        "config_exported",
        settings_count=len(settings_dict),
        providers_count=len(providers_list),
    )
    return export


# ---------------------------------------------------------------------------
# Dry-run import
# ---------------------------------------------------------------------------


async def _diff_settings(
    db: AsyncSession,
    import_settings: dict,
) -> list[dict]:
    """Compare imported settings against current values."""
    from app.persistent_config import _registry

    registry_map = {cfg.key: cfg for cfg in _registry}
    changes: list[dict] = []
    for key, imported_value in import_settings.items():
        cfg = registry_map.get(key)
        if cfg is None:
            continue
        current_value = await cfg.get(db)
        action = "no_change" if current_value == imported_value else "update"
        changes.append(
            SettingChange(
                key=key, current=current_value, imported=imported_value, action=action
            ).model_dump()
        )
    return changes


async def _diff_oauth_providers(
    db: AsyncSession,
    import_providers: list[dict],
    mode: ImportMode,
) -> list[dict]:
    """Compare imported OAuth providers against existing ones."""
    from app.auth.oauth import service as oauth_service

    existing_providers = await oauth_service.list_providers(db)
    existing_by_slug = {p.slug: p for p in existing_providers}
    import_slugs = {p["slug"] for p in import_providers if "slug" in p}

    changes: list[dict] = []
    for imp in import_providers:
        slug = imp.get("slug")
        if not slug:
            continue
        existing = existing_by_slug.get(slug)
        if existing is None:
            changes.append(OAuthProviderChange(slug=slug, action="create").model_dump())
        else:
            changed = _diff_provider(_provider_to_dict(existing), imp)
            action = "update" if changed else "no_change"
            changes.append(
                OAuthProviderChange(
                    slug=slug, action=action, changed_fields=changed or None
                ).model_dump()
            )

    if mode == "overwrite":
        for slug in existing_by_slug:
            if slug not in import_slugs:
                changes.append(
                    OAuthProviderChange(slug=slug, action="delete").model_dump()
                )
    return changes


async def dry_run_import(
    db: AsyncSession,
    data: dict,
    mode: ImportMode,
) -> DryRunResponse:
    """Compare imported config against current without modifying the database."""
    setting_changes = await _diff_settings(db, data.get("settings") or {})
    provider_changes = await _diff_oauth_providers(
        db, data.get("oauth_providers") or [], mode
    )
    return DryRunResponse(
        settings={"changes": setting_changes},
        oauth_providers={"changes": provider_changes},
    )


# ---------------------------------------------------------------------------
# Import helpers
# ---------------------------------------------------------------------------


async def _apply_oauth_providers(
    db: AsyncSession,
    import_providers: list[dict],
    mode: ImportMode,
) -> tuple[int, int, int]:
    """Apply OAuth provider changes. Returns (created, updated, deleted) counts."""
    from app.auth.oauth import service as oauth_service

    created = updated = deleted = 0

    if mode == "overwrite":
        existing = await oauth_service.list_providers(db)
        for provider in existing:
            await oauth_service.delete_provider(db, provider)
            deleted += 1
        await db.flush()

        for imp in import_providers:
            if not imp.get("client_secret"):
                raise HTTPException(
                    status_code=422,
                    detail=f"client_secret required for provider '{imp.get('slug', '?')}' in overwrite mode",
                )
            await oauth_service.create_provider(db, OAuthProviderCreate(**imp))
            created += 1
    else:
        existing_providers = await oauth_service.list_providers(db)
        existing_by_slug = {p.slug: p for p in existing_providers}

        for imp in import_providers:
            slug = imp.get("slug")
            if not slug:
                continue
            existing = existing_by_slug.get(slug)
            if existing is None:
                if not imp.get("client_secret"):
                    raise HTTPException(
                        status_code=422,
                        detail=f"client_secret required for new provider '{slug}'",
                    )
                await oauth_service.create_provider(db, OAuthProviderCreate(**imp))
                created += 1
            else:
                update_fields = {
                    k: v for k, v in imp.items() if k != "slug" and v is not None
                }
                if update_fields:
                    await oauth_service.update_provider(
                        db, existing, OAuthProviderUpdate(**update_fields)
                    )
                    updated += 1

    return created, updated, deleted


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------


async def import_config(
    db: AsyncSession,
    data: dict,
    mode: ImportMode,
    user_id: uuid.UUID,
    ip_address: str | None,
) -> ImportResult:
    """Import configuration, applying settings and OAuth provider changes.

    In merge mode: upserts settings, matches OAuth by slug (update or create).
    In overwrite mode: resets all settings then applies, deletes all OAuth then recreates.

    Raises HTTPException(403) if ENV_ONLY_CONFIG is true.
    Validates role_permissions to prevent admin lockout.
    Skips unknown setting keys for forward compatibility.
    """
    from app.persistent_config import _registry, _is_env_only
    from app.audit.service import log_action

    if _is_env_only():
        raise HTTPException(
            status_code=403, detail="Configuration locked to environment variables"
        )

    registry_map = {cfg.key: cfg for cfg in _registry}
    import_settings = data.get("settings") or {}
    import_providers = data.get("oauth_providers") or []

    settings_applied = 0
    settings_skipped = 0
    oauth_created = 0
    oauth_updated = 0
    oauth_deleted = 0

    # --- Validate role_permissions before applying anything ---
    if "role_permissions" in import_settings:
        try:
            validate_permission_matrix(import_settings["role_permissions"])
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(e)
            )

    # --- Settings ---
    if mode == "overwrite":
        # Reset all known settings first
        for cfg in _registry:
            if cfg.key in import_settings:
                continue  # will be set below
            await cfg.reset(db, user_id=user_id, ip_address=ip_address)

    for key, value in import_settings.items():
        cfg = registry_map.get(key)
        if cfg is None:
            settings_skipped += 1
            continue

        # Run per-key validator if one exists
        validator = SETTING_VALIDATORS.get(key)
        if validator is not None:
            try:
                value = validator(value)
            except (ValueError, TypeError) as e:
                raise HTTPException(
                    status_code=422,
                    detail=f"Validation failed for '{key}': {e}",
                )

        await cfg.set(db, value, user_id=user_id, ip_address=ip_address)
        settings_applied += 1

    # --- OAuth providers ---
    created, updated, deleted = await _apply_oauth_providers(db, import_providers, mode)
    oauth_created = created
    oauth_updated = updated
    oauth_deleted = deleted

    await db.commit()

    # Audit log
    await log_action(
        session=db,
        user_id=user_id,
        action="config_import",
        resource_type="config",
        details={
            "mode": mode,
            "settings_applied": settings_applied,
            "oauth_created": oauth_created,
            "oauth_updated": oauth_updated,
            "oauth_deleted": oauth_deleted,
        },
        ip_address=ip_address,
    )
    await db.commit()

    logger.info(
        "config_imported",
        mode=mode,
        settings_applied=settings_applied,
        settings_skipped=settings_skipped,
        oauth_created=oauth_created,
        oauth_updated=oauth_updated,
        oauth_deleted=oauth_deleted,
    )

    return ImportResult(
        settings_applied=settings_applied,
        settings_skipped=settings_skipped,
        oauth_created=oauth_created,
        oauth_updated=oauth_updated,
        oauth_deleted=oauth_deleted,
    )


# ---------------------------------------------------------------------------
# Connectivity validation
# ---------------------------------------------------------------------------

OIDC_PROBE_TIMEOUT = 5.0


async def check_oidc_endpoint(provider: Any) -> None:
    """Probe an OIDC provider's discovery or authorize endpoint.

    Raises on failure so the _probe wrapper captures the error.
    """
    async with httpx.AsyncClient(timeout=OIDC_PROBE_TIMEOUT) as client:
        if provider.discovery_url:
            resp = await client.get(provider.discovery_url)
            resp.raise_for_status()
        elif provider.authorize_url:
            resp = await client.head(provider.authorize_url, follow_redirects=False)
            if resp.status_code not in (200, 301, 302):
                raise httpx.HTTPStatusError(
                    f"Unexpected status {resp.status_code}",
                    request=resp.request,
                    response=resp,
                )
        else:
            raise ValueError("Provider has no discovery_url or authorize_url")


async def validate_connectivity(db: AsyncSession) -> ConnectivityResult:
    """Validate connectivity to storage, cache, and all enabled OIDC providers.

    Probes run concurrently. Failures return error details rather than raising.
    """
    from app.auth.oauth import service as oauth_service
    from app.health.service import _check_cache, _check_storage, _probe

    # Run storage and cache probes concurrently
    storage_result, cache_result = await asyncio.gather(
        _probe("storage", _check_storage()),
        _probe("cache", _check_cache()),
    )

    # Probe each enabled OIDC provider
    providers = await oauth_service.list_providers(db, enabled_only=True)
    oidc_results: dict[str, ServiceProbeResult] = {}

    if providers:
        oidc_probes = await asyncio.gather(
            *[_probe(p.slug, check_oidc_endpoint(p)) for p in providers]
        )
        for provider, result in zip(providers, oidc_probes):
            oidc_results[provider.slug] = ServiceProbeResult(
                name=provider.slug, **result
            )

    return ConnectivityResult(
        storage=ServiceProbeResult(name="storage", **storage_result),
        cache=ServiceProbeResult(name="cache", **cache_result),
        oidc_providers=oidc_results,
    )
