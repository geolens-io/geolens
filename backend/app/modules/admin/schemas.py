"""Admin schemas for user management endpoints."""

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.modules.auth.schemas import UserResponse

VALID_ROLES = {"admin", "editor", "viewer"}

# Mirror the CHECK constraint on IngestJob.status — see jobs/models.py
JobStatus = Literal["pending", "running", "complete", "failed", "cancelled", "fanned_out"]


class AdminUserCreate(BaseModel):
    username: str = Field(
        min_length=3,
        max_length=150,
        description="Login username (3-150 chars). Must be unique across the system.",
    )
    password: str = Field(
        min_length=8,
        max_length=256,
        # min_length=8 is a fast-fail floor; the canonical policy
        # (PASSWORD_MIN_LENGTH / PASSWORD_REQUIRE_CLASSES) is enforced by
        # validate_password below. See UserCreate docstring in auth/schemas.py.
        description=(
            "Initial password (policy: min 12 chars, 3+ character classes). "
            "The user can change this after first login."
        ),
    )
    email: EmailStr | None = Field(
        default=None,
        max_length=255,
        description="Optional email address. Used for OAuth account linking and notifications.",
    )
    role: str = Field(
        default="viewer",
        description="User role: 'admin', 'editor', or 'viewer'. Defaults to 'viewer'.",
    )

    @field_validator("password", mode="after")
    @classmethod
    def validate_password(cls, v: str) -> str:
        """Enforce the application password policy (SEC-S16, Phase 1062-01)."""
        from app.modules.auth.password_policy import validate_password_from_settings  # noqa: PLC0415

        validate_password_from_settings(v)
        return v

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: str) -> str:
        if v not in VALID_ROLES:
            raise ValueError(f"Role must be one of: {', '.join(sorted(VALID_ROLES))}")
        return v


class ApproveRequest(BaseModel):
    role: str = Field(
        max_length=50,
        description="Role to assign to the approved user: 'admin', 'editor', or 'viewer'.",
    )

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: str) -> str:
        if v not in VALID_ROLES:
            raise ValueError(f"Role must be one of: {', '.join(sorted(VALID_ROLES))}")
        return v


class UserUpdate(BaseModel):
    email: EmailStr | None = Field(
        default=None,
        description="New email address. Set to update; omit to leave unchanged.",
    )
    is_active: bool | None = Field(
        default=None,
        description="Whether the user can log in. Set to false to deactivate.",
    )
    role: str | None = Field(
        default=None,
        max_length=50,
        description="New role: 'admin', 'editor', or 'viewer'. Omit to leave unchanged.",
    )

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: str | None) -> str | None:
        if v is not None and v not in VALID_ROLES:
            raise ValueError(f"Role must be one of: {', '.join(sorted(VALID_ROLES))}")
        return v


class SamlToLocalConversion(BaseModel):
    """Request body for POST /admin/users/{user_id}/convert-saml-to-local/.

    Per Phase 221 D-01: a dedicated, single-purpose schema kept narrow on
    purpose -- password is intentionally NOT on the generic UserUpdate schema
    (which has no password field) so this conversion produces a single,
    audit-distinct action ('user.convert_saml_to_local') instead of being
    folded into 'user.update'.
    """

    password: str = Field(
        min_length=8,
        max_length=256,
        # min_length=8 is a fast-fail floor; the canonical policy is enforced
        # by validate_password below (SEC-S16, Phase 1062-01).
        description=(
            "Local-password for the converted account "
            "(policy: min 12 chars, 3+ character classes). "
            "The user can change this after first login."
        ),
    )

    @field_validator("password", mode="after")
    @classmethod
    def validate_password(cls, v: str) -> str:
        """Enforce the application password policy (SEC-S16, Phase 1062-01)."""
        from app.modules.auth.password_policy import validate_password_from_settings  # noqa: PLC0415

        validate_password_from_settings(v)
        return v


class UserNameItem(BaseModel):
    id: uuid.UUID = Field(description="Unique user identifier.")
    username: str = Field(description="User's login username.")


class UserListResponse(BaseModel):
    users: list[UserResponse] = Field(description="Page of users matching the query.")
    total: int = Field(
        description="Total number of users matching the query (across all pages)."
    )


class AdminJobResponse(BaseModel):
    id: uuid.UUID = Field(description="Unique ingestion job identifier.")
    status: JobStatus = Field(
        description="Current job status: 'pending', 'running', 'complete', 'failed', or 'cancelled'."
    )
    source_filename: str | None = Field(
        description="Original filename of the uploaded file, if applicable."
    )
    dataset_id: uuid.UUID | None = Field(
        description="ID of the dataset created by this job, if completed successfully."
    )
    error_message: str | None = Field(description="Error details if the job failed.")
    user_metadata: dict[str, Any] | None = Field(
        description="User-supplied metadata captured at upload time (title, summary, tags, vrt_type, file_type, warnings, etc.). Heterogeneous shape across ingest paths -- canonical keys: title, summary, visibility, file_type, vrt_type, warnings.",
    )
    created_by: uuid.UUID | None = Field(
        description="ID of the user who initiated the job."
    )
    username: str | None = Field(
        description="Username of the user who initiated the job."
    )
    started_at: datetime | None = Field(
        description="Timestamp when the worker began processing the job."
    )
    completed_at: datetime | None = Field(
        description="Timestamp when the job finished (success or failure)."
    )
    created_at: datetime = Field(description="Timestamp when the job was queued.")


class AdminJobListResponse(BaseModel):
    jobs: list[AdminJobResponse] = Field(description="Page of ingestion jobs.")
    total: int = Field(description="Total number of jobs matching the query.")


class CatalogStatsResponse(BaseModel):
    total_datasets: int = Field(description="Total number of datasets in the catalog.")
    recent_additions: int = Field(
        description="Number of datasets added in the last 30 days."
    )
    total_storage_bytes: int | None = Field(
        description="Total storage used by all dataset tables, in bytes. Null if calculation is unavailable."
    )
    datasets_by_geometry_type: dict[str, int] = Field(
        description="Histogram of datasets keyed by geometry type (Point, MultiPolygon, etc.)."
    )
    datasets_by_visibility: dict[str, int] = Field(
        description="Histogram of datasets keyed by visibility level (private, internal, restricted, public)."
    )
    users_by_status: dict[str, int] = Field(
        default={},
        description="Histogram of users keyed by status (active, deactivated, pending).",
    )
    total_users: int = Field(
        default=0, description="Total number of users in the system."
    )


class AIStatusResponse(BaseModel):
    provider: str | None = Field(
        description="Active AI provider name (e.g. 'anthropic', 'openai')."
    )
    model: str | None = Field(
        description="Active model name (e.g. 'claude-sonnet-4-20250514')."
    )
    enabled: bool = Field(
        description="Whether AI features are enabled for this instance."
    )
    configured: bool = Field(
        description="Whether an API key is configured. AI features require both 'enabled' and 'configured'."
    )
    semantic_search_enabled: bool = Field(
        default=False, description="Whether pgvector-backed semantic search is enabled."
    )
    has_embeddings: bool = Field(
        default=False, description="Whether at least one record has embeddings stored."
    )


class AIStatusUpdate(BaseModel):
    enabled: bool = Field(
        description="Set to true to enable AI features (chat, generation, semantic search), false to disable."
    )


class EmbeddingStatsResponse(BaseModel):
    total_records: int = Field(description="Total number of records in the catalog.")
    embedded_records: int = Field(
        description="Number of records that have an embedding stored."
    )
    missing_records: int = Field(
        description="Number of records still missing embeddings."
    )
    coverage_percent: float = Field(
        description="Embedding coverage as a percentage (0-100)."
    )


class BackfillResponse(BaseModel):
    processed: int = Field(
        description="Number of records processed in this backfill batch."
    )
    created: int = Field(description="Number of new embeddings created.")
    skipped: int = Field(
        description="Number of records skipped because an embedding already existed."
    )
    errors: int = Field(
        description="Number of records that failed during embedding generation."
    )


class ProviderHealth(BaseModel):
    status: str = Field(description="Provider health status: 'ok' or 'error'.")
    latency_ms: float = Field(
        description="Latency of the most recent health probe in milliseconds."
    )
    error: str | None = Field(
        default=None, description="Error message when status is 'error'."
    )


class InfrastructureConfig(BaseModel):
    storage_provider: str = Field(
        description="Active storage backend ('local' or 's3')."
    )
    cache_provider: str = Field(
        description="Active cache backend ('memory' or 'redis')."
    )
    database_type: str = Field(
        description="Database flavor (e.g. 'postgres', 'managed-postgres')."
    )
    database_pooler: str = Field(
        description="Active connection pooler mode ('sqlalchemy' or 'external')."
    )
    tile_cache: str = Field(description="Tile caching backend in use.")
    tile_cache_ttl: int = Field(description="Tile cache TTL in seconds.")
    cdn_configured: bool = Field(
        description="Whether a CDN base URL is configured for tile delivery."
    )


class InfrastructureResponse(BaseModel):
    config: InfrastructureConfig = Field(
        description="Snapshot of active infrastructure configuration."
    )
    health: dict[str, ProviderHealth] = Field(
        description="Health probe results keyed by provider name (db, storage, cache, llm, embedding)."
    )
    oidc_providers: dict[str, ProviderHealth] = Field(
        default={},
        description="Health probe results for configured OAuth/OIDC providers, keyed by slug.",
    )


class AdminApiKeyCreateRequest(BaseModel):
    user_id: uuid.UUID = Field(
        description="ID of the user the new API key will belong to."
    )
    name: str = Field(
        min_length=1,
        max_length=255,
        description="Human-readable label for the API key (e.g. 'CI pipeline', 'QGIS desktop').",
    )


class AdminApiKeyListItem(BaseModel):
    id: uuid.UUID = Field(description="Unique API key identifier.")
    user_id: uuid.UUID = Field(description="Owning user's ID.")
    name: str = Field(description="Human-readable label.")
    is_active: bool = Field(
        description="Whether the key is active. Inactive keys cannot authenticate."
    )
    created_at: datetime = Field(description="Timestamp when the key was created.")
    last_used_at: datetime | None = Field(
        description="Timestamp of the most recent successful authentication using this key."
    )


class AdminApiKeyListResponse(BaseModel):
    items: list[AdminApiKeyListItem] = Field(description="Page of API keys.")
    total: int = Field(description="Total number of API keys matching the query.")
