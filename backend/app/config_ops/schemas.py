"""Pydantic models for config export, import, and dry-run operations."""

from typing import Any, Literal

from pydantic import BaseModel


class ConfigExportResponse(BaseModel):
    """Full configuration export."""

    version: str
    exported_at: str
    settings: dict[str, Any]
    oauth_providers: list[dict]


class ConfigImportRequest(BaseModel):
    """Payload for importing configuration."""

    settings: dict[str, Any] | None = None
    oauth_providers: list[dict] | None = None


ImportMode = Literal["merge", "overwrite"]


class SettingChange(BaseModel):
    """A single setting diff entry."""

    key: str
    current: Any
    imported: Any
    action: Literal["update", "no_change"]


class OAuthProviderChange(BaseModel):
    """A single OAuth provider diff entry."""

    slug: str
    action: Literal["create", "update", "no_change", "delete"]
    changed_fields: list[str] | None = None


class DryRunResponse(BaseModel):
    """Result of a dry-run import showing what would change."""

    settings: dict[str, Any]
    oauth_providers: dict[str, Any]


class ImportResult(BaseModel):
    """Summary of what was applied during an import."""

    settings_applied: int
    settings_skipped: int
    oauth_created: int
    oauth_updated: int
    oauth_deleted: int


class ServiceProbeResult(BaseModel):
    """Result of a single service connectivity probe."""

    name: str
    status: Literal["ok", "error"]
    latency_ms: float
    error: str | None = None


class ConnectivityResult(BaseModel):
    """Aggregate connectivity validation result."""

    storage: ServiceProbeResult
    cache: ServiceProbeResult
    oidc_providers: dict[str, ServiceProbeResult]
