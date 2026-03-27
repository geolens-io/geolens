"""Admin schemas for user management endpoints."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.auth.schemas import UserResponse

VALID_ROLES = {"admin", "editor", "viewer"}


class AdminUserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=150)
    password: str = Field(min_length=8)
    email: str | None = None
    role: str = "viewer"

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: str) -> str:
        if v not in VALID_ROLES:
            raise ValueError(f"Role must be one of: {', '.join(sorted(VALID_ROLES))}")
        return v


class ApproveRequest(BaseModel):
    role: str

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: str) -> str:
        if v not in VALID_ROLES:
            raise ValueError(f"Role must be one of: {', '.join(sorted(VALID_ROLES))}")
        return v


class UserUpdate(BaseModel):
    email: str | None = None
    is_active: bool | None = None
    role: str | None = None

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: str | None) -> str | None:
        if v is not None and v not in VALID_ROLES:
            raise ValueError(f"Role must be one of: {', '.join(sorted(VALID_ROLES))}")
        return v


class UserNameItem(BaseModel):
    id: uuid.UUID
    username: str


class UserListResponse(BaseModel):
    users: list[UserResponse]
    total: int


class AdminJobResponse(BaseModel):
    id: uuid.UUID
    status: str
    source_filename: str | None
    dataset_id: uuid.UUID | None
    error_message: str | None
    user_metadata: dict | None
    created_by: uuid.UUID | None
    username: str | None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime


class AdminJobListResponse(BaseModel):
    jobs: list[AdminJobResponse]
    total: int


class CatalogStatsResponse(BaseModel):
    total_datasets: int
    recent_additions: int
    total_storage_bytes: int | None
    datasets_by_geometry_type: dict[str, int]
    datasets_by_visibility: dict[str, int]
    users_by_status: dict[str, int] = {}
    total_users: int = 0


class AIStatusResponse(BaseModel):
    provider: str | None
    model: str | None
    enabled: bool
    configured: bool
    semantic_search_enabled: bool = False
    has_embeddings: bool = False


class AIStatusUpdate(BaseModel):
    enabled: bool


class EmbeddingStatsResponse(BaseModel):
    total_records: int
    embedded_records: int
    missing_records: int
    coverage_percent: float


class BackfillResponse(BaseModel):
    processed: int
    created: int
    skipped: int
    errors: int


class ProviderHealth(BaseModel):
    status: str  # "ok" or "error"
    latency_ms: float
    error: str | None = None


class InfrastructureConfig(BaseModel):
    storage_provider: str
    cache_provider: str
    database_type: str
    database_pooler: str
    tile_cache: str
    tile_cache_ttl: int
    cdn_configured: bool


class InfrastructureResponse(BaseModel):
    config: InfrastructureConfig
    health: dict[str, ProviderHealth]
    oidc_providers: dict[str, ProviderHealth] = {}


class AdminApiKeyCreateRequest(BaseModel):
    user_id: uuid.UUID
    name: str


class ApiKeyCreateResponse(BaseModel):
    id: uuid.UUID
    key: str
    name: str
    created_at: datetime


class AdminApiKeyListItem(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    name: str
    is_active: bool
    created_at: datetime
    last_used_at: datetime | None


class AdminApiKeyListResponse(BaseModel):
    items: list[AdminApiKeyListItem]
    total: int
