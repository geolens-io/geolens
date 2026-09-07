import uuid
from datetime import datetime
from urllib.parse import urlparse

from app.core.public_urls import canonical_host_error

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.edition import is_enterprise

ADVANCED_SHARING_ERROR = "Advanced sharing controls are not enabled for this deployment"


def _normalize_origin(origin: str) -> str:
    normalized = origin.strip().lower().rstrip("/")
    # fix(#1548): a backslash is an origin-confusion primitive --
    # 'https://maps.example.com\\@evil.com' parses to a different host here
    # than in a browser. Refused for the same reason as
    # is_usable_public_origin (app/core/public_urls.py).
    if "\\" in normalized:
        raise ValueError(f"Invalid origin: {origin}")
    # Reject wildcards (CSP frame-ancestors NEVER '*'); checked after
    # strip+lower so whitespace can't smuggle one past this.
    if "*" in normalized:
        raise ValueError("Wildcard origin not allowed")
    if not normalized.startswith(("http://", "https://")):
        normalized = f"https://{normalized}"

    parsed = urlparse(normalized)
    if not parsed.hostname:
        raise ValueError(f"Invalid origin: {origin}")

    scheme = parsed.scheme or "https"
    # fix(#1548): host comes from parsed.hostname, not sliced out
    # of netloc -- netloc carries userinfo, so 'https://u:p@host' used to be
    # stored verbatim, leaking credentials into any CSP header built from it.
    # hostname also strips IPv6 brackets (e.g. '::1'), producing an invalid
    # CSP source ('http://::1:8080'); RFC 3986/CSP3 require them bracketed,
    # so they're added back below.
    host = parsed.hostname or ""
    # fix(#1548): non-ASCII hosts are REFUSED, not converted --
    # Python's idna codec is IDNA2003 (faß.de -> fass.de) while browsers use
    # WHATWG/UTS #46 (xn--fa-hia.de), so converting here would produce a
    # near-match that silently denies every request.
    if not host.isascii():
        raise ValueError(
            f"Invalid origin: {origin}. An internationalized domain must be "
            "given in its punycode (xn--) form, which is what browsers send."
        )
    # fix(#1548): host must already be spelled the way a browser
    # serializes it (e.g. compressed IPv6, no leading zeros) or the stored
    # origin can never match the shell's Origin header.
    host_problem = canonical_host_error(host)
    if host_problem is not None:
        raise ValueError(f"Invalid origin: {origin}. {host_problem}")
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
