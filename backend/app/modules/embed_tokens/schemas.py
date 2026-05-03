import uuid
from datetime import datetime
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.edition import is_enterprise

ADVANCED_SHARING_ERROR = "Advanced sharing controls require the GeoLens Enterprise overlay"


def _normalize_origin(origin: str) -> str:
    normalized = origin.strip().lower().rstrip("/")
    if not normalized.startswith(("http://", "https://")):
        normalized = f"https://{normalized}"

    parsed = urlparse(normalized)
    if not parsed.hostname:
        raise ValueError(f"Invalid origin: {origin}")

    scheme = parsed.scheme or "https"
    host = parsed.hostname
    port = parsed.port
    if (scheme == "http" and port == 80) or (scheme == "https" and port == 443):
        port = None

    if port:
        return f"{scheme}://{host}:{port}"
    return f"{scheme}://{host}"


def _validate_origins(v: list[str] | None) -> list[str] | None:
    if v is None:
        return None
    cleaned = []
    for origin in v:
        s = origin.strip()
        if not s:
            continue
        cleaned.append(_normalize_origin(s))
    return cleaned or None


class EmbedTokenCreate(BaseModel):
    expires_in_days: int = Field(
        default=30,
        ge=1,
        le=365,
        description=(
            "Token lifetime in days (1-365). The default 30-day lifetime is "
            "available in Community; custom lifetimes require GeoLens Enterprise."
        ),
        example=90,
    )
    name: str | None = Field(
        default=None,
        min_length=1,
        max_length=255,
        description="Human-readable label for the token",
        example="Public dashboard embed",
    )
    allowed_origins: list[str] | None = Field(
        default=None,
        max_length=50,
        description=(
            "Restrict embedding to these origins. Omit or null allows any origin; "
            "non-empty origin restrictions require GeoLens Enterprise."
        ),
        example=["https://dashboard.example.com"],
    )

    @field_validator("allowed_origins", mode="before")
    @classmethod
    def validate_origins(cls, v: list[str] | None) -> list[str] | None:
        return _validate_origins(v)

    @model_validator(mode="after")
    def validate_enterprise_controls(self):
        if not is_enterprise() and (
            self.expires_in_days != 30 or bool(self.allowed_origins)
        ):
            raise ValueError(ADVANCED_SHARING_ERROR)
        return self


class EmbedTokenUpdate(BaseModel):
    allowed_origins: list[str] | None = Field(
        default=None,
        max_length=50,
        description=(
            "Updated list of allowed embedding origins. Null clears restrictions; "
            "non-empty origin restrictions require GeoLens Enterprise."
        ),
    )

    @field_validator("allowed_origins", mode="before")
    @classmethod
    def validate_origins(cls, v: list[str] | None) -> list[str] | None:
        return _validate_origins(v)

    @model_validator(mode="after")
    def validate_enterprise_controls(self):
        if not is_enterprise() and bool(self.allowed_origins):
            raise ValueError(ADVANCED_SHARING_ERROR)
        return self


class EmbedTokenResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    map_id: uuid.UUID
    name: str | None = None
    token_hint: str
    scoped_dataset_ids: list[str]
    allowed_origins: list[str] | None = None
    expires_at: datetime
    is_active: bool
    use_count: int = 0
    last_used_at: datetime | None = None
    created_at: datetime


class EmbedTokenCreatedResponse(EmbedTokenResponse):
    raw_token: str


class EmbedTokenListResponse(BaseModel):
    tokens: list[EmbedTokenResponse]
    total: int


class AdminEmbedTokenResponse(EmbedTokenResponse):
    map_name: str | None = None
    creator_username: str | None = None


class AdminEmbedTokenListResponse(BaseModel):
    tokens: list[AdminEmbedTokenResponse]
    total: int


class BulkRevokeRequest(BaseModel):
    token_ids: list[uuid.UUID] = Field(min_length=1, max_length=100)


class BulkRevokeResponse(BaseModel):
    revoked_count: int
