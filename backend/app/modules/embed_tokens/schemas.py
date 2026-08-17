import uuid
from datetime import datetime
from urllib.parse import urlparse

from app.core.public_urls import canonical_host_error

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.edition import is_enterprise

ADVANCED_SHARING_ERROR = "Advanced sharing controls are not enabled for this deployment"


def _normalize_origin(origin: str) -> str:
    normalized = origin.strip().lower().rstrip("/")
    # fix(#1548 review r10): a backslash is an origin-confusion primitive, not a
    # formatting nit — 'https://maps.example.com\\@evil.com' parses as host
    # 'maps.example.com\\' here and as host 'evil.com' in a browser. Refused for
    # the same reason as in is_usable_public_origin (app/core/public_urls.py):
    # the two parsers disagree, and that disagreement is the bug.
    if "\\" in normalized:
        raise ValueError(f"Invalid origin: {origin}")
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
    # fix(#1548 review r10): a non-ASCII host is REFUSED, not converted. Python's
    # built-in idna codec is IDNA2003 and maps `faß.de` to `fass.de`, while
    # browsers follow WHATWG/UTS #46 and send `xn--fa-hia.de` — so converting
    # here would produce a near match, which denies every request while looking
    # correct. Supply the punycode form, which is what the browser sends anyway.
    if not host.isascii():
        raise ValueError(
            f"Invalid origin: {origin}. An internationalized domain must be "
            "given in its punycode (xn--) form, which is what browsers send."
        )
    # fix(#1548 review r11): the host must already be spelled the way a browser
    # serializes it. Storing our own spelling of `192.168.1` or an uncompressed
    # IPv6 literal meant the stored origin and the shell's Origin header could
    # never match. The message names the canonical form where it can be computed
    # without re-implementing the browser's parser.
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
