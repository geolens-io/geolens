"""Admin schemas for user management endpoints."""

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    EmailStr,
    Field,
    field_validator,
    model_validator,
)

from app.modules.auth.schemas import UserResponse, validate_future_expiry
from app.processing.ai.schemas import AIProbeReport

VALID_ROLES = {"admin", "editor", "viewer"}

# Mirror the CHECK constraint on IngestJob.status — see jobs/models.py
JobStatus = Literal[
    "pending", "running", "complete", "failed", "cancelled", "fanned_out"
]

# Sortable columns for the admin user list. This Literal is the OUTER half of a
# two-layer allowlist: FastAPI rejects anything outside it with a 422 before the
# service runs, and USER_SORT_COLUMNS in service.py resolves the surviving value
# to a mapped column. A caller-supplied string is therefore never interpolated
# into an ORDER BY clause.
#
# Membership is limited to real `users` columns. Roles is a many-to-many and
# storage is computed per page after the query returns, so neither can be
# ordered by the database without restructuring the endpoint.
UserSortField = Literal["username", "email", "status", "last_login_at", "created_at"]

# Sortable columns for the admin job list, same two-layer shape as
# UserSortField above (inner half: _job_sort_columns() in service.py).
#
# `username` orders by the already-joined users row, and `duration` by the
# completed_at - started_at interval, which is NULL for exactly the jobs whose
# Duration cell renders "-". Nothing else the row displays is orderable: the
# retry affordance is computed per page after the query returns.
JobSortField = Literal[
    "created_at", "source_filename", "status", "username", "duration"
]

# Sortable columns for the admin published-maps list (inner half:
# _share_token_ordering() in catalog/maps/service_public.py).
#
# Link status is absent: it is derived in Python from is_active plus expires_at
# against now(), so ordering by it would need a CASE expression the listing
# does not have. See AdminSharedMapsPage for the matching UI comment.
ShareTokenSortField = Literal[
    "map_name", "created_at", "creator", "expires_at", "embed_token_count"
]

SortDirection = Literal["asc", "desc"]


# fix(#1715): one wiring for the password policy, shared by every admin schema
# that accepts a password. Each of these used to carry its own copy of the same
# four-line field_validator; the reset endpoint would have made three. The rules
# themselves live in auth/password_policy.py and are unchanged.
def _enforce_password_policy(value: str) -> str:
    """Enforce the application password policy (SEC-S16, Phase 1062-01)."""
    from app.modules.auth.password_policy import validate_password_from_settings  # noqa: PLC0415

    validate_password_from_settings(value)
    return value


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

    validate_password = field_validator("password", mode="after")(
        _enforce_password_policy
    )

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
        description=(
            "Legacy account-state toggle. False maps to 'deactivated' and true "
            "maps to 'active'. Prefer the explicit status field."
        ),
    )
    status: Literal["active", "suspended", "deactivated"] | None = Field(
        default=None,
        description=(
            "Explicit account lifecycle state. Pending registrations must use "
            "the approve/reject endpoints."
        ),
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

    @model_validator(mode="after")
    def validate_state_fields(self) -> "UserUpdate":
        """Reject contradictory legacy and explicit lifecycle fields."""
        if self.status is not None and self.is_active is not None:
            expected_active = self.status == "active"
            if self.is_active is not expected_active:
                raise ValueError("status and is_active describe conflicting states")
        return self


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

    validate_password = field_validator("password", mode="after")(
        _enforce_password_policy
    )


class AdminPasswordReset(BaseModel):
    """Request body for POST /admin/users/{user_id}/reset-password/.

    Single-purpose for the same reason as SamlToLocalConversion above: the
    generic UserUpdate schema has no password field, so an admin-set password
    lands as its own audited action ('user.password_reset') rather than
    disappearing into 'user.update'.
    """

    password: str = Field(
        min_length=8,
        max_length=256,
        # min_length=8 is a fast-fail floor; the canonical policy is enforced
        # by validate_password below (SEC-S16, Phase 1062-01).
        description=(
            "Replacement password for the account "
            "(policy: min 12 chars, 3+ character classes). "
            "The user can change this after their next login."
        ),
    )

    validate_password = field_validator("password", mode="after")(
        _enforce_password_policy
    )


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
    can_retry: bool = Field(
        description="Whether the failed job can be retried with its retained source."
    )
    retry_reason: str | None = Field(
        description="Why the job cannot be retried, when retry is unavailable."
    )
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


class AdminShareTokenResponse(BaseModel):
    id: uuid.UUID | None = None
    map_id: uuid.UUID
    map_name: str
    token: str | None = None
    is_active: bool | None = None
    expires_at: datetime | None = None
    created_at: datetime
    created_by: str | None
    embed_token_count: int = 0


class AdminShareTokenListResponse(BaseModel):
    tokens: list[AdminShareTokenResponse]
    total: int


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
    # fix(#627): key presence != key validity. Present only when the caller
    # passed ?probe=true (the ai-status routes serialize with exclude_unset,
    # so default responses keep their exact pre-probe shape).
    probe: AIProbeReport | None = Field(
        default=None,
        description="Live provider probe results. Only present when the "
        "request opted in via ?probe=true.",
    )


class AIStatusUpdate(BaseModel):
    enabled: bool = Field(
        description="Set to true to enable AI features (chat, generation, semantic search), false to disable."
    )


class EmbeddingStatsResponse(BaseModel):
    total_records: int = Field(description="Total number of records in the catalog.")
    embedded_records: int = Field(
        description=(
            "Number of records with an embedding for the ACTIVE embedding model "
            "— the only vectors semantic search can use."
        )
    )
    missing_records: int = Field(
        description=(
            "Number of records without an active-model embedding "
            "(total_records - embedded_records)."
        )
    )
    stale_records: int = Field(
        description=(
            "Subset of missing_records whose only stored embeddings belong to "
            "other models. Regenerating all embeddings clears these; generating "
            "missing ones does not."
        )
    )
    coverage_percent: float = Field(
        description="Embedding coverage as a percentage (0-100)."
    )


class BackfillResponse(BaseModel):
    """Acknowledgement that a backfill run was queued (fix(#1542)).

    The run itself happens on the job queue, so this carries no counts — a full
    regenerate takes minutes and used to hold the HTTP request open past the
    600s edge timeout. Poll ``GET /jobs/{job_id}`` for the run's status.
    """

    job_id: uuid.UUID = Field(
        description="Identifier of the queued backfill job; poll /jobs/{job_id}."
    )
    status: str = Field(description="Job status at enqueue time ('pending').")


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
    expires_at: AwareDatetime | None = Field(
        default=None,
        description=(
            "Optional expiry timestamp (RFC 3339, timezone-aware). Omit or null "
            "for a non-expiring key; expired keys stop authenticating."
        ),
    )
    scope: Literal["full", "read_only"] = Field(
        default="full",
        description=(
            "Privilege scope (#875). 'full' impersonates the owner completely, "
            "the pre-existing behavior. 'read_only' authenticates GET, HEAD and "
            "OPTIONS requests only; any other method is refused with 403. A "
            "service-account key minted for an application is the usual case "
            "for 'read_only'."
        ),
    )

    _expires_at_future = field_validator("expires_at")(validate_future_expiry)


class AdminApiKeyListItem(BaseModel):
    id: uuid.UUID = Field(description="Unique API key identifier.")
    user_id: uuid.UUID = Field(description="Owning user's ID.")
    name: str = Field(description="Human-readable label.")
    fingerprint: str | None = Field(
        description="Non-secret key identifier; null for legacy keys."
    )
    is_active: bool = Field(
        description="Whether the key is active. Inactive keys cannot authenticate."
    )
    expires_at: datetime | None = Field(
        default=None,
        description="Expiry timestamp; null means the key does not expire.",
    )
    scope: str = Field(description="Privilege scope: 'full' or 'read_only' (#875).")
    created_at: datetime = Field(description="Timestamp when the key was created.")
    last_used_at: datetime | None = Field(
        description="Timestamp of the most recent successful authentication using this key."
    )


class AdminApiKeyListResponse(BaseModel):
    items: list[AdminApiKeyListItem] = Field(description="Page of API keys.")
    total: int = Field(description="Total number of API keys matching the query.")
