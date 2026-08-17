import uuid
from datetime import datetime
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.edition import is_enterprise

ADVANCED_SHARING_ERROR = "Advanced sharing controls are not enabled for this deployment"


def _normalize_origin(origin: str) -> str:
    normalized = origin.strip().lower().rstrip("/")
    # Reject wildcard entries — CSP frame-ancestors NEVER '*'.
    # Check is performed after strip+lower so leading/trailing whitespace cannot
    # smuggle wildcards. Covers '*', '*.example.com', 'https://*.example.com'.
    if "*" in normalized:
        raise ValueError("Wildcard origin not allowed")
    if not normalized.startswith(("http://", "https://")):
        normalized = f"https://{normalized}"

    parsed = urlparse(normalized)
    if not parsed.hostname:
        raise ValueError(f"Invalid origin: {origin}")

    scheme = parsed.scheme or "https"
    # fix(#1548 review r9): the host is taken from parsed.hostname and rebuilt,
    # NOT sliced out of netloc. netloc carries userinfo, so 'https://u:p@host'
    # used to store 'https://u:p@host' as an origin — a spelling no browser ever
    # sends, and one that would leak the credentials into any CSP header or
    # copied link built from it. hostname drops userinfo and lowercases for us.
    #
    # parsed.hostname also strips the square brackets from IPv6 literals (e.g.
    # '::1'), producing an invalid CSP source expression like 'http://::1:8080'
    # — RFC 3986 / W3C CSP3 §2.6.1 require them bracketed — so they go back on.
    host = parsed.hostname or ""
    # A browser serializes an internationalized host in its IDNA ASCII form:
    # the shell's Origin for https://máp.example arrives as
    # https://xn--mp-mia.example. Storing the Unicode spelling meant the domain
    # lock was issued and then missed on every request. Canonicalize to the
    # spelling the browser will present, rather than rejecting the value.
    if not host.isascii():
        try:
            host = host.encode("idna").decode("ascii")
        except UnicodeError as exc:
            raise ValueError(f"Invalid origin: {origin}") from exc
    netloc_host = f"[{host}]" if ":" in host else host
    port = parsed.port
    if (scheme == "http" and port == 80) or (scheme == "https" and port == 443):
        port = None

    if port:
        return f"{scheme}://{netloc_host}:{port}"
    return f"{scheme}://{netloc_host}"


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
            "always available; custom lifetimes require advanced sharing controls."
        ),
        json_schema_extra={"example": 90},
    )
    name: str | None = Field(
        default=None,
        min_length=1,
        max_length=255,
        description="Human-readable label for the token",
        json_schema_extra={"example": "Public dashboard embed"},
    )
    allowed_origins: list[str] | None = Field(
        default=None,
        max_length=50,
        description=(
            "Restrict embedding to these origins. Omit or null allows any origin; "
            "non-empty origin restrictions require advanced sharing controls."
        ),
        json_schema_extra={"example": ["https://dashboard.example.com"]},
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
            "non-empty origin restrictions require advanced sharing controls."
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
