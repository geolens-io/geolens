"""Pydantic models for config export, import, and dry-run operations."""

from typing import Any, Literal

from pydantic import BaseModel, Field, SkipValidation


class ConfigExportResponse(BaseModel):
    """Full configuration export."""

    version: str = Field(
        description="Schema version of the export format. Used by import to determine compatibility."
    )
    exported_at: str = Field(
        description="ISO 8601 timestamp when the export was generated."
    )
    settings: dict[str, Any] = Field(
        description="All admin-configurable settings keyed by setting name."
    )
    oauth_providers: list[dict] = Field(
        description="OAuth provider configurations. Client secrets are NOT included in exports."
    )


class ConfigImportRequest(BaseModel):
    """Payload for importing configuration."""

    settings: SkipValidation[dict[str, Any] | None] = Field(
        default=None,
        description="Optional settings to import. Omit to import only OAuth providers.",
    )
    oauth_providers: SkipValidation[list[dict] | None] = Field(
        default=None,
        description="Optional OAuth providers to import. Client secrets must be re-supplied via the admin UI after import.",
    )


ImportMode = Literal["merge", "overwrite"]


class SettingChange(BaseModel):
    """A single setting diff entry."""

    key: str = Field(description="Setting key being compared.")
    current: Any = Field(description="Current value in the database.")
    imported: Any = Field(description="Value from the import payload.")
    action: Literal[
        "update", "no_change", "reset", "skip_unknown", "skip_restricted"
    ] = Field(description="What the import would do for this setting.")
    reason: str | None = Field(
        default=None,
        description="Why a setting is skipped, when applicable.",
    )


class OAuthProviderChange(BaseModel):
    """A single OAuth provider diff entry."""

    slug: str = Field(description="OAuth provider slug being compared.")
    action: Literal["create", "update", "no_change", "delete", "replace"] = Field(
        description="What the import would do for this provider."
    )
    changed_fields: list[str] | None = Field(
        default=None,
        description="Names of fields that would change. Null when action is 'create' or 'no_change'.",
    )
    dependent_accounts_deleted: int = Field(
        default=0,
        ge=0,
        description=(
            "OAuth account links that would be cascade-deleted with this provider "
            "during overwrite. The linked subjects are never exposed."
        ),
    )


class DryRunResponse(BaseModel):
    """Result of a dry-run import showing what would change."""

    settings: dict[str, Any] = Field(
        description="Per-setting diff result keyed by setting name."
    )
    oauth_providers: dict[str, Any] = Field(
        description="Per-provider diff result keyed by slug."
    )
    preview_token: str | None = Field(
        default=None,
        description=(
            "Short-lived signed confirmation token required to apply an overwrite. "
            "Bound to the normalized payload, overwrite mode, and current configuration state."
        ),
    )


class ImportResult(BaseModel):
    """Summary of what was applied during an import."""

    settings_applied: int = Field(
        description="Number of settings successfully updated."
    )
    settings_skipped: int = Field(
        description="Number of settings skipped (no change, unknown key, or "
        "restricted key not writable by the current runtime)."
    )
    settings_skipped_restricted: list[str] = Field(
        default_factory=list,
        description="Names of restricted setting keys that were skipped by the "
        "current runtime.",
    )
    oauth_created: int = Field(description="Number of new OAuth providers created.")
    oauth_updated: int = Field(
        description="Number of existing OAuth providers updated."
    )
    oauth_deleted: int = Field(
        description="Number of OAuth providers deleted (overwrite mode only)."
    )
    oauth_accounts_deleted: int = Field(
        default=0,
        ge=0,
        description=(
            "Number of dependent OAuth account links cascade-deleted in overwrite mode."
        ),
    )


class ServiceProbeResult(BaseModel):
    """Result of a single service connectivity probe."""

    name: str = Field(
        description="Service name (e.g. 'storage', 'cache', 'oidc:google')."
    )
    status: Literal["ok", "error"] = Field(description="Probe outcome.")
    latency_ms: float = Field(description="Round-trip latency in milliseconds.")
    error: str | None = Field(
        default=None, description="Error message when status is 'error'."
    )


class ConnectivityResult(BaseModel):
    """Aggregate connectivity validation result."""

    storage: ServiceProbeResult = Field(description="Object storage probe result.")
    cache: ServiceProbeResult = Field(description="Cache backend probe result.")
    oidc_providers: dict[str, ServiceProbeResult] = Field(
        description="Per-provider OIDC discovery probe results, keyed by provider slug."
    )
