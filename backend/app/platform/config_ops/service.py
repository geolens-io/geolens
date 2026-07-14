"""Config export, import (merge/overwrite), dry-run, and connectivity validation."""

from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import hmac
import json
import time
import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx
import structlog
from pydantic import ValidationError
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.config_ops.exceptions import (
    ConfigLockedError,
    ConfigPreviewError,
    ConfigValidationError,
)

from app.core.config import settings as app_settings
from app.core.db.models import AppSetting
from app.modules.auth.oauth.schemas import OAuthProviderCreate, OAuthProviderUpdate
from app.modules.auth.permissions import validate_permission_matrix
from app.platform.config_ops.schemas import (
    ConnectivityResult,
    DryRunResponse,
    ImportMode,
    ImportResult,
    OAuthProviderChange,
    ServiceProbeResult,
    SettingChange,
)
from app.modules.settings.schemas import SETTING_VALIDATORS

logger = structlog.stdlib.get_logger(__name__)

_EXPORT_VERSION = "1.0"
_PREVIEW_TOKEN_VERSION = 1
_PREVIEW_TOKEN_TTL_SECONDS = 10 * 60
_CONFIG_IMPORT_LOCK_SQL = text(
    "LOCK TABLE catalog.oauth_providers, catalog.app_settings IN EXCLUSIVE MODE"
)
_DIGEST_DOMAIN_PREFIX = b"geolens.config-preview.v1\0"


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
        "idp_entity_id": provider.__dict__.get("idp_entity_id"),
        "idp_sso_url": provider.__dict__.get("idp_sso_url"),
        "sp_entity_id": provider.__dict__.get("sp_entity_id"),
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
    "idp_entity_id",
    "idp_sso_url",
    "sp_entity_id",
    "scopes",
    "default_role",
    "group_claim",
    "group_role_mapping",
    "enabled",
]

_OAUTH_ENDPOINT_FIELDS = frozenset(
    {"discovery_url", "authorize_url", "token_url", "userinfo_url"}
)


def _diff_provider(existing_dict: dict, imported: dict) -> list[str]:
    """Return list of fields that differ between existing and imported provider."""
    changed = []
    for field in _PROVIDER_COMPARE_FIELDS:
        if field in imported and imported[field] != existing_dict.get(field):
            changed.append(field)
    # Write-only credentials cannot be compared with their encrypted stored
    # values, but their presence always means apply will rotate a credential.
    # Return only field names; never expose either secret value.
    for field in ("client_secret", "idp_certificate"):
        if imported.get(field):
            changed.append(field)
    return changed


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------


async def export_config(db: AsyncSession) -> dict:
    """Export all PersistentConfig settings and OAuth providers as a dict.

    OAuth provider secrets are redacted (client_secret_encrypted omitted).
    """
    from app.core.persistent_config import _registry
    from app.modules.auth.oauth import service as oauth_service

    # Collect all setting values
    settings_dict: dict[str, Any] = {}
    for cfg in _registry:
        settings_dict[cfg.key] = await cfg.get(db)

    # Collect OAuth providers (without secrets)
    providers = await oauth_service.list_providers(db, include_saml_fields=True)
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
# Shared import preflight and overwrite confirmation
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ConfigImportPlan:
    """Validated, normalized import plan shared by preview and apply."""

    validated_settings: dict[str, Any]
    settings_to_apply: dict[str, Any]
    normalized_providers: list[dict[str, Any]]
    providers_to_apply: list[dict[str, Any]]
    setting_changes: list[dict[str, Any]]
    provider_changes: list[dict[str, Any]]
    skipped_unknown: list[str]
    skipped_restricted: list[str]
    oauth_accounts_deleted: int
    payload_digest: str
    state_digest: str
    caller_is_enterprise: bool


async def acquire_config_import_lock(db: AsyncSession) -> None:
    """Freeze settings and OAuth writes for preflight-through-commit.

    PostgreSQL's ``EXCLUSIVE`` table lock still permits ordinary reads, but it
    conflicts with DML and ``SELECT .. FOR UPDATE``.  Therefore every existing
    settings/OAuth writer is covered without relying on each route to opt into a
    cooperative advisory lock.  OAuth is listed first to match the lock order of
    the password-login/SSO lockout guards, which lock provider rows before
    mutating ``app_settings``.
    """
    await db.execute(_CONFIG_IMPORT_LOCK_SQL)


def _preview_signing_key() -> bytes:
    return app_settings.jwt_secret_key.get_secret_value().encode("utf-8")


def _domain_hmac(domain: str, value: bytes) -> bytes:
    """Authenticate preview material in a purpose-specific namespace."""
    domain_bytes = domain.encode("ascii")
    return hmac.new(
        _preview_signing_key(),
        _DIGEST_DOMAIN_PREFIX + domain_bytes + b"\0" + value,
        hashlib.sha256,
    ).digest()


def _canonical_digest(value: Any, *, domain: str) -> str:
    """Return a keyed canonical digest for one preview-token purpose."""
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=str,
    ).encode("utf-8")
    return _domain_hmac(domain, encoded).hex()


def _urlsafe_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _urlsafe_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def _credential_version(value: str | None) -> str | None:
    """Return a non-reversible version marker for a stored credential."""
    if value is None:
        return None
    return _domain_hmac("credential-version", value.encode("utf-8")).hex()


def _oauth_account_state(account: Any) -> dict[str, Any]:
    """Project linked-account identity/version state without exposing subjects."""
    return {
        "id": str(account.id),
        "provider_id": str(account.provider_id),
        "user_id": str(account.user_id),
        "created_at": account.created_at,
        "subject_version": _domain_hmac(
            "oauth-account-subject", account.subject.encode("utf-8")
        ).hex(),
    }


def _provider_state_dict(provider: Any) -> dict[str, Any]:
    """Project all provider state relevant to destructive overwrite approval.

    Unlike the export projection, this internal structure binds provider
    identity and write-only credential versions.  Credential material itself is
    never placed in the token claims or returned by an API.
    """
    return {
        "id": str(provider.id),
        "updated_at": provider.updated_at,
        "config": _provider_to_dict(provider),
        "client_secret_version": _credential_version(provider.client_secret_encrypted),
        "idp_certificate_version": _credential_version(
            provider.__dict__.get("idp_certificate")
        ),
    }


def _issue_preview_token(plan: ConfigImportPlan, mode: ImportMode) -> str:
    claims = {
        "v": _PREVIEW_TOKEN_VERSION,
        "mode": mode,
        "payload": plan.payload_digest,
        "state": plan.state_digest,
        "exp": int(time.time()) + _PREVIEW_TOKEN_TTL_SECONDS,
    }
    payload = json.dumps(claims, sort_keys=True, separators=(",", ":")).encode("utf-8")
    signature = _domain_hmac("token-signature", payload)
    return f"{_urlsafe_encode(payload)}.{_urlsafe_encode(signature)}"


def _verify_preview_token(
    token: str | None, plan: ConfigImportPlan, mode: ImportMode
) -> None:
    message = (
        "A current matching dry-run is required before overwrite; preview the "
        "configuration again and retry."
    )
    if not token:
        raise ConfigPreviewError(message)
    try:
        payload_part, signature_part = token.split(".", 1)
        payload = _urlsafe_decode(payload_part)
        supplied_signature = _urlsafe_decode(signature_part)
        expected_signature = _domain_hmac("token-signature", payload)
        if not hmac.compare_digest(supplied_signature, expected_signature):
            raise ValueError("invalid signature")
        claims = json.loads(payload)
        if not isinstance(claims, dict):
            raise ValueError("invalid claims")
        if (
            claims.get("v") != _PREVIEW_TOKEN_VERSION
            or claims.get("mode") != mode
            or claims.get("payload") != plan.payload_digest
            or claims.get("state") != plan.state_digest
            or not isinstance(claims.get("exp"), int)
            or claims["exp"] <= int(time.time())
        ):
            raise ValueError("stale preview")
    except (ValueError, TypeError, KeyError, binascii.Error, UnicodeError) as exc:
        raise ConfigPreviewError(message) from exc


def _safe_setting_validation_message(key: str, exc: Exception) -> str:
    """Return a useful validation error without reflecting submitted values."""
    from app.core.ai_credentials import OpenAICredentialDestinationError

    if isinstance(exc, OpenAICredentialDestinationError):
        # This exception family contains only code-owned policy text and never
        # interpolates the submitted endpoint or credential.
        return f"Validation failed for setting '{key}': {exc}"
    if key == "role_permissions":
        message = str(exc)
        if "manage_tenants" in message:
            return (
                "Validation failed for setting 'role_permissions': "
                "manage_tenants cannot be granted by stored roles."
            )
        return (
            "Validation failed for setting 'role_permissions': "
            "the permission matrix violates a lockout or escalation invariant."
        )
    return f"Validation failed for setting '{key}': invalid value."


def _safe_pydantic_provider_message(
    index: int,
    exc: ValidationError,
) -> str:
    """Summarize schema failures using only code-owned field names."""
    allowed_fields = set(OAuthProviderCreate.model_fields) | set(
        OAuthProviderUpdate.model_fields
    )
    fields: set[str] = set()
    for error in exc.errors(
        include_url=False,
        include_context=False,
        include_input=False,
    ):
        location = error.get("loc") or ()
        if location and isinstance(location[0], str) and location[0] in allowed_fields:
            fields.add(location[0])
    suffix = f" Fields: {', '.join(sorted(fields))}." if fields else ""
    return f"OAuth provider at index {index} failed schema validation.{suffix}"


def _validate_setting_value(key: str, value: Any, cfg: Any) -> Any:
    validator = SETTING_VALIDATORS.get(key)
    if validator is not None:
        try:
            value = validator(value)
        except (ValueError, TypeError) as exc:
            raise ConfigValidationError(
                _safe_setting_validation_message(key, exc)
            ) from exc

    try:
        validated_value = cfg._adapter.validate_python(value)
    except ValidationError as exc:
        raise ConfigValidationError(_safe_setting_validation_message(key, exc)) from exc

    # Apply-equivalent validation must inspect the canonical value. Otherwise
    # a raw JSON string such as "false" passes a truthiness check and then
    # canonicalizes to False, producing an administrator lockout matrix.
    if key == "role_permissions":
        try:
            validate_permission_matrix(validated_value)
        except (ValueError, TypeError) as exc:
            raise ConfigValidationError(
                _safe_setting_validation_message(key, exc)
            ) from exc
    return validated_value


def _validate_login_method_plan(
    *,
    password_login_enabled: bool,
    existing_providers: list[Any],
    normalized_providers: list[dict[str, Any]],
    mode: ImportMode,
) -> None:
    """Reject a final import plan that would disable every login method."""
    if password_login_enabled:
        return

    if mode == "overwrite":
        enabled_provider_count = sum(
            bool(provider.get("enabled", True)) for provider in normalized_providers
        )
    else:
        final_enabled = {
            provider.slug: bool(provider.enabled) for provider in existing_providers
        }
        for provider in normalized_providers:
            slug = provider["slug"]
            if slug in final_enabled:
                final_enabled[slug] = bool(provider.get("enabled", final_enabled[slug]))
            else:
                final_enabled[slug] = bool(provider.get("enabled", True))
        enabled_provider_count = sum(final_enabled.values())

    if enabled_provider_count == 0:
        raise ConfigValidationError(
            "Configuration import would disable every login method; enable "
            "password login or at least one SSO provider."
        )


def _normalize_provider_payload(
    raw_providers: list[Any],
    existing_by_slug: dict[str, Any],
    mode: ImportMode,
    dependent_account_counts: dict[uuid.UUID, int] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    from app.modules.auth.oauth import service as oauth_service

    normalized: list[dict[str, Any]] = []
    changes: list[dict[str, Any]] = []
    seen_slugs: set[str] = set()
    account_counts = dependent_account_counts or {}

    for index, raw in enumerate(raw_providers):
        if not isinstance(raw, dict):
            raise ConfigValidationError(
                f"OAuth provider at index {index} must be an object"
            )
        slug = raw.get("slug")
        if not isinstance(slug, str) or not slug:
            raise ConfigValidationError(
                f"OAuth provider at index {index} requires a slug"
            )
        if slug in seen_slugs:
            raise ConfigValidationError(
                f"OAuth provider at index {index} has a duplicate slug."
            )
        seen_slugs.add(slug)
        existing = existing_by_slug.get(slug)

        try:
            if mode == "overwrite" or existing is None:
                provider = OAuthProviderCreate.model_validate(raw)
                normalized_provider = oauth_service.normalize_provider_create(provider)
            else:
                update_fields = {
                    key: value
                    for key, value in raw.items()
                    if key != "slug"
                    and (value is not None or key in _OAUTH_ENDPOINT_FIELDS)
                }
                provider_update = OAuthProviderUpdate.model_validate(update_fields)
                normalized_provider = {
                    "slug": slug,
                    **oauth_service.normalize_provider_update(
                        existing, provider_update
                    ),
                }
        except ValidationError as exc:
            raise ConfigValidationError(
                _safe_pydantic_provider_message(index, exc)
            ) from exc
        except oauth_service.OAuthProviderConfigurationError as exc:
            raise ConfigValidationError(
                f"OAuth provider at index {index} failed security validation: {exc}"
            ) from exc
        except (ValueError, TypeError) as exc:
            raise ConfigValidationError(
                f"OAuth provider at index {index} has invalid configuration."
            ) from exc

        normalized.append(normalized_provider)
        if mode == "overwrite":
            action = "replace" if existing is not None else "create"
            changes.append(
                OAuthProviderChange(
                    slug=slug,
                    action=action,
                    dependent_accounts_deleted=(
                        account_counts.get(existing.id, 0)
                        if existing is not None
                        else 0
                    ),
                ).model_dump()
            )
        elif existing is None:
            changes.append(OAuthProviderChange(slug=slug, action="create").model_dump())
        else:
            changed = _diff_provider(_provider_to_dict(existing), normalized_provider)
            changes.append(
                OAuthProviderChange(
                    slug=slug,
                    action="update" if changed else "no_change",
                    changed_fields=changed or None,
                ).model_dump()
            )

    if mode == "overwrite":
        for slug in sorted(existing_by_slug):
            if slug not in seen_slugs:
                changes.append(
                    OAuthProviderChange(
                        slug=slug,
                        action="delete",
                        dependent_accounts_deleted=account_counts.get(
                            existing_by_slug[slug].id, 0
                        ),
                    ).model_dump()
                )

    return normalized, changes


def _providers_to_apply(
    normalized_providers: list[dict[str, Any]],
    provider_changes: list[dict[str, Any]],
    mode: ImportMode,
) -> list[dict[str, Any]]:
    """Filter true merge no-ops while preserving destructive overwrite input."""
    if mode == "overwrite":
        return normalized_providers
    return [
        provider
        for provider, change in zip(
            normalized_providers,
            provider_changes,
            strict=True,
        )
        if change["action"] in {"create", "update"}
    ]


def _validate_setting_payload(
    raw_settings: dict[str, Any],
    registry_map: dict[str, Any],
    *,
    caller_is_enterprise: bool,
    enterprise_only_tabs: set[str] | frozenset[str],
) -> tuple[dict[str, Any], dict[str, Any], list[str], list[str]]:
    """Validate writable values without reflecting inputs or reading the DB."""
    validated: dict[str, Any] = {}
    normalized: dict[str, Any] = {}
    skipped_unknown: list[str] = []
    skipped_restricted: list[str] = []
    for key, raw_value in raw_settings.items():
        cfg = registry_map.get(key)
        if cfg is None:
            skipped_unknown.append(key)
            normalized[key] = raw_value
            continue
        if not caller_is_enterprise and cfg.tab in enterprise_only_tabs:
            skipped_restricted.append(key)
            normalized[key] = raw_value
            continue
        value = _validate_setting_value(key, raw_value, cfg)
        validated[key] = value
        normalized[key] = value
    return validated, normalized, skipped_unknown, skipped_restricted


async def _load_setting_state(
    db: AsyncSession,
    registry: list[Any],
) -> tuple[dict[str, Any], set[str], set[str]]:
    """Load effective values plus source and stored-validity markers."""
    from app.core.persistent_config import _validate_or_fallback

    result = await db.execute(select(AppSetting.key, AppSetting.value))
    stored_settings = {key: value for key, value in result.all()}
    overridden_keys = set(stored_settings)
    current_settings: dict[str, Any] = {}
    valid_stored_keys: set[str] = set()
    for cfg in registry:
        if cfg.key not in stored_settings:
            current_settings[cfg.key] = cfg.env_default
            continue
        raw_value = stored_settings[cfg.key]
        unwrapped = (
            raw_value
            if not isinstance(raw_value, dict) or "v" not in raw_value
            else raw_value["v"]
        )
        current_value, stored_value_is_valid = _validate_or_fallback(cfg, unwrapped)
        current_settings[cfg.key] = current_value
        if stored_value_is_valid:
            valid_stored_keys.add(cfg.key)
    return current_settings, overridden_keys, valid_stored_keys


def _build_setting_changes(
    raw_settings: dict[str, Any],
    registry_map: dict[str, Any],
    validated_settings: dict[str, Any],
    current_settings: dict[str, Any],
    overridden_keys: set[str],
    valid_stored_keys: set[str],
    *,
    caller_is_enterprise: bool,
    enterprise_only_tabs: set[str] | frozenset[str],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Create source-aware setting diffs and the exact write subset."""
    settings_to_apply: dict[str, Any] = {}
    changes: list[dict[str, Any]] = []
    for key, raw_value in raw_settings.items():
        cfg = registry_map.get(key)
        if cfg is None:
            changes.append(
                SettingChange(
                    key=key,
                    current=None,
                    imported=raw_value,
                    action="skip_unknown",
                    reason="Unknown setting key; retained for forward compatibility.",
                ).model_dump()
            )
            continue
        if not caller_is_enterprise and cfg.tab in enterprise_only_tabs:
            changes.append(
                SettingChange(
                    key=key,
                    current=current_settings[key],
                    imported=raw_value,
                    action="skip_restricted",
                    reason="Setting is not writable in the current runtime.",
                ).model_dump()
            )
            continue

        value = validated_settings[key]
        current = current_settings[key]
        pins_runtime_default = key not in overridden_keys and current == value
        repairs_invalid_override = (
            key in overridden_keys and key not in valid_stored_keys
        )
        needs_write = (
            current != value or pins_runtime_default or repairs_invalid_override
        )
        if needs_write:
            settings_to_apply[key] = value
        reason = None
        if pins_runtime_default:
            reason = "Pins the current runtime default as a database override."
        elif repairs_invalid_override:
            reason = "Repairs an invalid database override."
        changes.append(
            SettingChange(
                key=key,
                current=current,
                imported=value,
                action="update" if needs_write else "no_change",
                reason=reason,
            ).model_dump()
        )
    return settings_to_apply, changes


async def _load_oauth_account_rows(
    db: AsyncSession,
    mode: ImportMode,
    *,
    lock_rows: bool,
) -> list[Any]:
    """Load overwrite-dependent account state, optionally share-locking rows."""
    if mode != "overwrite":
        return []

    from app.modules.auth.oauth.models import OAuthAccount

    query = select(
        OAuthAccount.id,
        OAuthAccount.provider_id,
        OAuthAccount.user_id,
        OAuthAccount.subject,
        OAuthAccount.created_at,
    ).order_by(OAuthAccount.id)
    if lock_rows:
        # The import already holds EXCLUSIVE on oauth_providers. Existing link
        # rows are share-locked against update/delete, while FK-backed inserts
        # must acquire a parent key-share lock and cannot pass the provider fence.
        query = query.with_for_update(read=True)
    result = await db.execute(query)
    return list(result.all())


async def preflight_import(
    db: AsyncSession,
    data: dict[str, Any],
    mode: ImportMode,
    *,
    lock_dependent_accounts: bool = False,
) -> ConfigImportPlan:
    """Build the exact validated plan used by both dry-run and import."""
    from app.core.edition import is_enterprise
    from app.core.persistent_config import (
        ENTERPRISE_ONLY_TABS,
        _registry,
    )
    from app.core.public_urls import _is_env_only
    from app.modules.auth.oauth import service as oauth_service

    if _is_env_only():
        raise ConfigLockedError("Configuration locked to environment variables")
    if mode not in ("merge", "overwrite"):
        raise ConfigValidationError(f"Unsupported import mode '{mode}'")

    raw_settings = data.get("settings")
    raw_providers = data.get("oauth_providers")
    if raw_settings is None:
        raw_settings = {}
    if raw_providers is None:
        raw_providers = []
    if not isinstance(raw_settings, dict):
        raise ConfigValidationError("settings must be an object")
    if not isinstance(raw_providers, list):
        raise ConfigValidationError("oauth_providers must be an array")

    caller_is_enterprise = is_enterprise()
    registry_map = {cfg.key: cfg for cfg in _registry}

    # Validate every recognized, writable input before touching database state.
    # Besides keeping preview/apply identical, this guarantees malformed secret-
    # bearing payloads take the sanitized validation path even with a failed or
    # mocked database connection.
    (
        validated_settings,
        normalized_payload_settings,
        skipped_unknown,
        skipped_restricted,
    ) = _validate_setting_payload(
        raw_settings,
        registry_map,
        caller_is_enterprise=caller_is_enterprise,
        enterprise_only_tabs=ENTERPRISE_ONLY_TABS,
    )
    current_settings, overridden_keys, valid_stored_keys = await _load_setting_state(
        db,
        _registry,
    )
    settings_to_apply, setting_changes = _build_setting_changes(
        raw_settings,
        registry_map,
        validated_settings,
        current_settings,
        overridden_keys,
        valid_stored_keys,
        caller_is_enterprise=caller_is_enterprise,
        enterprise_only_tabs=ENTERPRISE_ONLY_TABS,
    )

    if mode == "overwrite":
        for cfg in _registry:
            if cfg.key in raw_settings:
                continue
            if not caller_is_enterprise and cfg.tab in ENTERPRISE_ONLY_TABS:
                continue
            setting_changes.append(
                SettingChange(
                    key=cfg.key,
                    current=current_settings[cfg.key],
                    imported=cfg.env_default,
                    action="reset",
                    reason="Omitted from overwrite payload; reset to runtime default.",
                ).model_dump()
            )

    existing_providers = await oauth_service.list_providers(
        db, include_saml_fields=True
    )
    existing_by_slug = {provider.slug: provider for provider in existing_providers}

    account_rows = await _load_oauth_account_rows(
        db,
        mode,
        lock_rows=lock_dependent_accounts,
    )
    account_counts = Counter(account.provider_id for account in account_rows)

    normalized_providers, provider_changes = _normalize_provider_payload(
        raw_providers,
        existing_by_slug,
        mode,
        dict(account_counts),
    )
    providers_to_apply = _providers_to_apply(
        normalized_providers,
        provider_changes,
        mode,
    )

    if "password_login_enabled" in validated_settings:
        final_password_login_enabled = bool(
            validated_settings["password_login_enabled"]
        )
    elif mode == "overwrite":
        final_password_login_enabled = bool(
            registry_map["password_login_enabled"].env_default
        )
    else:
        final_password_login_enabled = bool(current_settings["password_login_enabled"])
    _validate_login_method_plan(
        password_login_enabled=final_password_login_enabled,
        existing_providers=existing_providers,
        normalized_providers=normalized_providers,
        mode=mode,
    )

    payload_digest = _canonical_digest(
        {
            "mode": mode,
            "settings": normalized_payload_settings,
            "oauth_providers": normalized_providers,
        },
        domain="payload",
    )
    state_digest = _canonical_digest(
        {
            "enterprise": caller_is_enterprise,
            "settings": [
                {
                    "key": cfg.key,
                    "value": current_settings[cfg.key],
                    "overridden": cfg.key in overridden_keys,
                }
                for cfg in _registry
                if caller_is_enterprise or cfg.tab not in ENTERPRISE_ONLY_TABS
            ],
            "oauth_providers": sorted(
                (_provider_state_dict(provider) for provider in existing_providers),
                key=lambda provider: provider["config"]["slug"],
            ),
            "oauth_accounts": sorted(
                (_oauth_account_state(account) for account in account_rows),
                key=lambda account: account["id"],
            ),
        },
        domain="state",
    )

    return ConfigImportPlan(
        validated_settings=validated_settings,
        settings_to_apply=settings_to_apply,
        normalized_providers=normalized_providers,
        providers_to_apply=providers_to_apply,
        setting_changes=setting_changes,
        provider_changes=provider_changes,
        skipped_unknown=skipped_unknown,
        skipped_restricted=skipped_restricted,
        oauth_accounts_deleted=len(account_rows) if mode == "overwrite" else 0,
        payload_digest=payload_digest,
        state_digest=state_digest,
        caller_is_enterprise=caller_is_enterprise,
    )


async def dry_run_import(
    db: AsyncSession,
    data: dict,
    mode: ImportMode,
) -> DryRunResponse:
    """Validate and compare imported config without modifying the database."""
    plan = await preflight_import(db, data, mode)
    return DryRunResponse(
        settings={
            "changes": plan.setting_changes,
            "skipped_unknown": plan.skipped_unknown,
            "skipped_restricted": plan.skipped_restricted,
        },
        oauth_providers={
            "changes": plan.provider_changes,
            "dependent_accounts_deleted": plan.oauth_accounts_deleted,
        },
        preview_token=(
            _issue_preview_token(plan, mode) if mode == "overwrite" else None
        ),
    )


# ---------------------------------------------------------------------------
# Import helpers
# ---------------------------------------------------------------------------


def _sanitized_provider_apply_error(
    index: int,
    exc: Exception,
) -> ConfigValidationError:
    """Map provider apply failures to non-reflective validation details."""
    from app.modules.auth.oauth import service as oauth_service

    if isinstance(exc, ValidationError):
        return ConfigValidationError(_safe_pydantic_provider_message(index, exc))
    if isinstance(exc, oauth_service.OAuthProviderConfigurationError):
        return ConfigValidationError(
            f"OAuth provider at index {index} failed security validation: {exc}"
        )
    return ConfigValidationError(
        f"OAuth provider at index {index} has invalid configuration."
    )


async def _create_imported_provider(
    db: AsyncSession,
    provider: dict[str, Any],
    index: int,
    *,
    overwrite: bool,
) -> None:
    from app.modules.auth.oauth import service as oauth_service

    if provider.get("provider_type") != "saml" and not provider.get("client_secret"):
        suffix = " in overwrite mode" if overwrite else ""
        raise ConfigValidationError(
            f"OAuth provider at index {index} requires client_secret{suffix}."
        )
    try:
        data = OAuthProviderCreate(**provider)
        await oauth_service.create_provider(db, data)
    except (ValidationError, ValueError, TypeError) as exc:
        raise _sanitized_provider_apply_error(index, exc) from exc


async def _update_imported_provider(
    db: AsyncSession,
    existing: Any,
    provider: dict[str, Any],
    index: int,
) -> bool:
    from app.modules.auth.oauth import service as oauth_service

    # Exported endpoint nulls explicitly clear the inactive OAuth mode. Other
    # null values retain merge mode's "leave unchanged" semantics.
    update_fields = {
        key: value
        for key, value in provider.items()
        if key != "slug" and (value is not None or key in _OAUTH_ENDPOINT_FIELDS)
    }
    if not update_fields:
        return False
    try:
        data = OAuthProviderUpdate(**update_fields)
        await oauth_service.update_provider(db, existing, data)
    except (ValidationError, ValueError, TypeError) as exc:
        raise _sanitized_provider_apply_error(index, exc) from exc
    return True


async def _apply_oauth_providers(
    db: AsyncSession,
    import_providers: list[dict],
    mode: ImportMode,
) -> tuple[int, int, int, int]:
    """Apply providers; return provider and cascaded-account deletion counts."""
    from app.modules.auth.oauth import service as oauth_service
    from app.modules.auth.oauth.models import OAuthAccount

    created = updated = deleted = accounts_deleted = 0

    if mode == "overwrite":
        account_count = await db.scalar(select(func.count()).select_from(OAuthAccount))
        # SQLAlchemy returns an int. Treat non-integer test doubles/fallbacks as
        # zero instead of letting ``int(AsyncMock())`` invent a deletion count.
        accounts_deleted = account_count if isinstance(account_count, int) else 0
        existing = await oauth_service.list_providers(db)
        for provider in existing:
            await oauth_service.delete_provider(db, provider)
            deleted += 1
        await db.flush()

        for index, imp in enumerate(import_providers):
            await _create_imported_provider(db, imp, index, overwrite=True)
            created += 1
    else:
        existing_providers = await oauth_service.list_providers(db)
        existing_by_slug = {p.slug: p for p in existing_providers}

        for index, imp in enumerate(import_providers):
            slug = imp.get("slug")
            if not slug:
                continue
            existing = existing_by_slug.get(slug)
            if existing is None:
                await _create_imported_provider(db, imp, index, overwrite=False)
                created += 1
            elif await _update_imported_provider(db, existing, imp, index):
                updated += 1

    return created, updated, deleted, accounts_deleted


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------


async def import_config(
    db: AsyncSession,
    data: dict,
    mode: ImportMode,
    user_id: uuid.UUID,
    ip_address: str | None,
    *,
    preview_token: str | None = None,
) -> ImportResult:
    """Import configuration, applying settings and OAuth provider changes.

    In merge mode: upserts settings, matches OAuth by slug (update or create).
    In overwrite mode: resets all settings then applies, deletes all OAuth then recreates.

    Preview and apply consume the same preflight plan. Overwrite additionally
    requires the signed token returned by a matching, current dry-run.
    """
    from app.core.persistent_config import ENTERPRISE_ONLY_TABS, _registry
    from app.modules.audit.service import (
        AuditEvent,
        audit_emit,
    )  # LAZY — preserved per D-17

    # Hold a database-enforced write fence while recomputing state, verifying
    # the destructive confirmation, and applying the plan.  Without this, a
    # concurrent settings/OAuth transaction could commit after the state read
    # and be silently overwritten by a token that was already stale.
    await acquire_config_import_lock(db)
    plan = await preflight_import(
        db,
        data,
        mode,
        lock_dependent_accounts=mode == "overwrite",
    )
    if mode == "overwrite":
        _verify_preview_token(preview_token, plan, mode)

    registry_map = {cfg.key: cfg for cfg in _registry}
    settings_no_change = len(plan.validated_settings) - len(plan.settings_to_apply)
    settings_skipped = (
        len(plan.skipped_unknown) + len(plan.skipped_restricted) + settings_no_change
    )
    settings_applied = len(plan.settings_to_apply)

    # fix(#430 codex r3): with commit=False, set()/reset() DEFER their side
    # effects (cache invalidation, _on_change runtime hooks, sync rate-limit
    # warm) — running them pre-commit flipped process-local runtime state that
    # a rollback wouldn't restore. Collect (cfg, committed_value) pairs and
    # apply side effects only after the terminal commit succeeds.
    deferred_side_effects: list = []

    if mode == "overwrite":
        for cfg in _registry:
            if cfg.key in plan.validated_settings:
                continue
            if not plan.caller_is_enterprise and cfg.tab in ENTERPRISE_ONLY_TABS:
                continue
            await cfg.reset(db, user_id=user_id, ip_address=ip_address, commit=False)
            deferred_side_effects.append((cfg, cfg.env_default))

    for key, value in plan.settings_to_apply.items():
        cfg = registry_map[key]
        await cfg.set(db, value, user_id=user_id, ip_address=ip_address, commit=False)
        deferred_side_effects.append((cfg, value))

    (
        oauth_created,
        oauth_updated,
        oauth_deleted,
        oauth_accounts_deleted,
    ) = await _apply_oauth_providers(db, plan.providers_to_apply, mode)
    if oauth_accounts_deleted != plan.oauth_accounts_deleted:
        # The provider table fence plus dependent-row share locks should make
        # this unreachable. Fail closed if a future write path bypasses those
        # invariants rather than under-reporting a destructive cascade.
        raise ConfigPreviewError(
            "OAuth account links changed during import; preview the configuration again."
        )

    # Stage exactly one aggregate import event in the same transaction as the
    # settings, per-setting audit rows, and OAuth mutations. Either all of them
    # are durable or none of them are.
    await audit_emit(
        db,
        AuditEvent(
            user_id=user_id,
            action="config_import",
            resource_type="config",
            details={
                "mode": mode,
                "settings_applied": settings_applied,
                "settings_skipped_unknown": plan.skipped_unknown,
                "settings_skipped_restricted": plan.skipped_restricted,
                "oauth_created": oauth_created,
                "oauth_updated": oauth_updated,
                "oauth_deleted": oauth_deleted,
                "oauth_accounts_deleted": oauth_accounts_deleted,
            },
            ip_address=ip_address,
        ),
    )

    # Single commit for config changes and all associated audit rows.
    await db.commit()

    for cfg, committed_value in deferred_side_effects:
        await cfg.apply_side_effects(committed_value)

    logger.info(
        "config_imported",
        mode=mode,
        settings_applied=settings_applied,
        settings_skipped=settings_skipped,
        settings_skipped_unknown=plan.skipped_unknown,
        settings_skipped_restricted=plan.skipped_restricted,
        oauth_created=oauth_created,
        oauth_updated=oauth_updated,
        oauth_deleted=oauth_deleted,
        oauth_accounts_deleted=oauth_accounts_deleted,
    )

    return ImportResult(
        settings_applied=settings_applied,
        settings_skipped=settings_skipped,
        settings_skipped_restricted=plan.skipped_restricted,
        oauth_created=oauth_created,
        oauth_updated=oauth_updated,
        oauth_deleted=oauth_deleted,
        oauth_accounts_deleted=oauth_accounts_deleted,
    )


# ---------------------------------------------------------------------------
# Connectivity validation
# ---------------------------------------------------------------------------

OIDC_PROBE_TIMEOUT = 5.0


async def check_oidc_endpoint(provider: Any) -> None:
    """Probe an OIDC provider's discovery or authorize endpoint.

    Raises on failure so the _probe wrapper captures the error.
    """
    from app.modules.catalog.sources.security import (
        make_safe_client,
        validate_url_for_ssrf,
    )

    endpoint = provider.discovery_url or provider.authorize_url
    if endpoint:
        await validate_url_for_ssrf(endpoint)

    async with make_safe_client(timeout=OIDC_PROBE_TIMEOUT) as client:
        if provider.discovery_url:
            resp = await client.get(provider.discovery_url, follow_redirects=False)
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
    from app.modules.auth.oauth import service as oauth_service
    from app.observability.health.service import _check_cache, _check_storage, _probe

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
