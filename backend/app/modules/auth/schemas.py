from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Literal, get_args

from pydantic import AwareDatetime, BaseModel, EmailStr, Field, field_validator

from app.modules.quota.schemas import UserQuotaUsage

# User account status enum mirrors the CHECK constraint on User.status.
UserStatus = Literal["active", "pending", "suspended", "deactivated"]

RoleName = Literal["admin", "editor", "viewer"]
VALID_ROLES = frozenset(get_args(RoleName))


def validate_role_name(value: object) -> str:
    """Return *value* when it names a built-in role, else raise ValueError."""
    if not isinstance(value, str) or value not in VALID_ROLES:
        raise ValueError(
            f"Unknown role {value!r}; must be one of: {', '.join(sorted(VALID_ROLES))}"
        )
    return value


class TokenResponse(BaseModel):
    access_token: str = Field(description="JWT access token for Authorization header")
    # Required-but-nullable, not optional: omitting `default=` keeps it in
    # OpenAPI's `required` list so generated SDKs don't get an `Unset`/absent
    # shape the server never emits.
    refresh_token: str | None = Field(
        description=(
            "Opaque token used to obtain a new access token. Always present for "
            "programmatic callers (CLI, SDKs, CI). Null when the caller opted "
            "into the browser cookie flow with 'X-GeoLens-Auth-Mode: cookie', "
            "in which case the token is delivered as an httpOnly cookie instead "
            "(GH-1302)."
        ),
    )
    token_type: str = "bearer"
    expires_in: int = Field(description="Seconds until the access token expires")


class DownloadTokenResponse(BaseModel):
    token: str = Field(
        description="Short-lived download-scoped JWT (typ='download', TTL ≤ 120s)"
    )
    expires_in: int = Field(
        default=120, description="Seconds until the download token expires"
    )


class UserCreate(BaseModel):
    username: str = Field(
        min_length=3,
        max_length=150,
        description="Unique login name",
        json_schema_extra={"example": "jdoe"},
    )
    password: str = Field(
        min_length=8,
        max_length=256,
        # min_length=8 is a fast-fail floor: Field constraints run before
        # @field_validator(mode="after"), and validate_password below enforces
        # the full policy (default 12 chars + 3-of-4 classes). Both errors are
        # 422; the field-level one fires first under 8 chars.
        description=(
            "Plaintext password (policy: min 12 chars, 3+ character classes, "
            "at most 72 bytes UTF-8)"
        ),
        # Deliberately no json_schema_extra example (Rule 3): a published
        # example password lands in openapi.json and both SDKs, and no example
        # beats one that invites copy-paste.
    )
    email: EmailStr | None = Field(
        default=None,
        max_length=255,
        description="Optional email address",
        json_schema_extra={"example": "jdoe@example.com"},
    )

    @field_validator("password", mode="after")
    @classmethod
    def validate_password(cls, v: str) -> str:
        """Enforce the application password policy."""
        from app.modules.auth.password_policy import validate_password_from_settings  # noqa: PLC0415

        validate_password_from_settings(v)
        return v


class RegisterResponse(BaseModel):
    message: str
    # Computed purely from (config + submitted email), so it is IDENTICAL for a
    # genuine new signup and a swallowed username/email collision — the
    # collision path must not be distinguishable (enumeration-safety).
    next_step: Literal["verify_email", "await_approval"] | None = Field(
        default=None,
        description=(
            "Post-registration step for the client to display: 'verify_email' when a "
            "verification email was (or, for a swallowed collision, would have been) sent; "
            "'await_approval' for the admin-approval path. None on non-register responses."
        ),
    )


class VerifyEmailRequest(BaseModel):
    token: str = Field(
        max_length=128,
        description="Raw opaque verification token from the email link",
    )


class ResendVerificationRequest(BaseModel):
    email: EmailStr = Field(
        description="Email address to resend the verification link to"
    )


class ConfigResponse(BaseModel):
    registration_enabled: bool = Field(
        description=(
            "Whether self-service registration is open. Single sign-on can "
            "create accounts whenever this is true."
        )
    )
    allow_signup: bool = Field(
        default=False,
        description=(
            "Whether password sign-up is open: registration is enabled and "
            "password login is enabled. Login UI uses this to show/hide the signup link."
        ),
    )
    email_verification_required: bool = Field(
        default=False,
        description=(
            "When true, new self-registered users must verify their email before logging in. "
            "Default false for back-compat-safe parsing by older clients."
        ),
    )
    auth_methods: list[str] = Field(
        default_factory=list,
        description=(
            "Auth methods contributed by the active AuthExtension. "
            "Empty by default; compatible deployments may add methods such as ['saml']. "
            "Login UI can render conditional sign-in options without needing admin OAuthProvider access."
        ),
    )
    landing_first: bool = Field(
        default=False,
        description=(
            "When true, unauthenticated visits to '/' are redirected to '/login' "
            "as the product landing page. Default false (search catalog is the root)."
        ),
    )
    banner_enabled: bool = Field(
        default=False,
        description=(
            "When true and banner_text is non-empty, the site-wide "
            "announcement banner is shown. Default false."
        ),
    )
    banner_text: str = Field(
        default="",
        description=(
            "Admin-configured site-wide announcement banner text. "
            "Empty string means no banner is shown."
        ),
    )
    banner_color: str = Field(
        default="warning",
        description=(
            "Theme token for the site banner color: "
            "warning | info | success | destructive."
        ),
    )
    password_login_enabled: bool = Field(
        default=True,
        description=(
            "When false, password login is disabled for users without manage_settings. "
            "Default true for back-compat-safe parsing by older clients."
        ),
    )


class UserResponse(BaseModel):
    id: uuid.UUID
    username: str
    email: str | None
    is_active: bool
    status: UserStatus = Field(
        description="Account status: active, pending, suspended, or deactivated."
    )
    last_login_at: datetime | None
    created_at: datetime
    roles: list[str] = Field(
        description="Assigned role names, e.g. ['admin', 'editor']"
    )
    can_reset_password: bool = Field(
        description=(
            "Whether an administrator can set a local password for this account. "
            "True for local accounts even when an identity provider is also linked."
        )
    )
    quota_usage: UserQuotaUsage | None = Field(
        default=None,
        description=(
            "Per-user storage quota usage. Populated only on admin list responses; "
            "None when the caller did not load usage (e.g. /auth/me, single-user GET)."
        ),
    )

    model_config = {"from_attributes": True}


class RefreshRequest(BaseModel):
    # Stays required: only the body as a whole is optional (route signature
    # `RefreshRequest | None = None`). Defaulting this field would make `{}` a
    # valid body the server can't do anything with.
    refresh_token: str = Field(max_length=512)


class PermissionsResponse(BaseModel):
    permissions: dict[str, bool] = Field(
        description="Map of permission names to granted/denied"
    )


def validate_future_expiry(value: AwareDatetime | None) -> AwareDatetime | None:
    """Reject an ``expires_at`` that is not in the future.

    Shared by the self-service and admin key-mint request schemas so both
    surfaces refuse to mint an already-expired key.
    """
    if value is not None and value <= datetime.now(timezone.utc):
        raise ValueError("expires_at must be in the future")
    return value


class ApiKeyCreateRequest(BaseModel):
    name: str = Field(
        min_length=1, max_length=255, description="Human-readable label for the API key"
    )
    expires_at: AwareDatetime | None = Field(
        default=None,
        description=(
            "Optional expiry timestamp (RFC 3339, timezone-aware). Omit or null "
            "for a non-expiring key; expired keys stop authenticating."
        ),
    )
    scope: Literal["full", "read_only", "publish"] = Field(
        default="full",
        description=(
            "Privilege scope. 'full' impersonates the owner completely. "
            "'read_only' authenticates GET, HEAD and "
            "OPTIONS requests only; any other method is refused with 403. "
            "'publish' also allows uploads, manifest apply, dataset metadata "
            "edits and new maps, but no map update, delete, feature write, "
            "public visibility, admin or key route."
        ),
    )

    _expires_at_future = field_validator("expires_at")(validate_future_expiry)


# A dataset key usually lives in a third-party webhook's settings, where it is
# easy to forget, so it must expire and be re-minted at least yearly.
DATASET_KEY_MAX_LIFETIME = timedelta(days=365)


class DatasetApiKeyCreateRequest(BaseModel):
    name: str = Field(
        min_length=1, max_length=255, description="Human-readable label for the API key"
    )
    expires_at: AwareDatetime = Field(
        description=(
            "Expiry timestamp (RFC 3339, timezone-aware), in the future and at "
            "most 365 days away. Expired keys stop authenticating."
        ),
    )
    scope: Literal["dataset_write", "dataset_append"] = Field(
        default="dataset_write",
        description=(
            "'dataset_write' reads and writes the dataset's features. "
            "'dataset_append' only creates features, one or a FeatureCollection "
            "per request, and can't read, change or delete them."
        ),
    )

    @field_validator("expires_at")
    @classmethod
    def _expires_within_a_year(cls, value: AwareDatetime) -> AwareDatetime:
        validate_future_expiry(value)
        if value > datetime.now(timezone.utc) + DATASET_KEY_MAX_LIFETIME:
            raise ValueError("expires_at must be at most 365 days away")
        return value


_SCOPE_DESCRIPTION = (
    "Privilege scope: 'full', 'read_only', 'publish' (reads, uploads, manifest "
    "apply, dataset metadata edits and new maps, but no map updates, deletes, "
    "feature writes or public visibility), "
    "'dataset_write' (reads and writes the features of the dataset in "
    "dataset_id, and nothing else), or 'dataset_append' (only creates features "
    "in that dataset)"
)
_DATASET_ID_DESCRIPTION = (
    "The dataset a 'dataset_write' or 'dataset_append' key is bound to; null "
    "for other scopes"
)


class ApiKeyCreateResponse(BaseModel):
    id: uuid.UUID
    key: str = Field(description="The API key secret (shown only once)")
    fingerprint: str = Field(
        description="Non-secret key identifier (prefix and last four characters)"
    )
    name: str
    expires_at: datetime | None = Field(
        default=None,
        description="Expiry timestamp; null means the key does not expire",
    )
    scope: str = Field(description=_SCOPE_DESCRIPTION)
    dataset_id: uuid.UUID | None = Field(
        default=None, description=_DATASET_ID_DESCRIPTION
    )
    created_at: datetime


class ApiKeyListItem(BaseModel):
    id: uuid.UUID
    name: str
    fingerprint: str | None = Field(
        description="Non-secret key identifier; null for keys created before fingerprint support"
    )
    is_active: bool
    expires_at: datetime | None = Field(
        default=None,
        description="Expiry timestamp; null means the key does not expire",
    )
    scope: str = Field(description=_SCOPE_DESCRIPTION)
    dataset_id: uuid.UUID | None = Field(
        default=None, description=_DATASET_ID_DESCRIPTION
    )
    created_at: datetime
    last_used_at: datetime | None


class ApiKeyListResponse(BaseModel):
    items: list[ApiKeyListItem]
    total: int


class DatasetApiKeyListItem(ApiKeyListItem):
    user_id: uuid.UUID = Field(
        description="The user who minted the key; it acts as them"
    )
    username: str = Field(description="That user's username")


class DatasetApiKeyListResponse(BaseModel):
    items: list[DatasetApiKeyListItem]
    total: int


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(
        min_length=8,
        max_length=256,
        description="New password (policy: min 12 chars, 3+ character classes: "
        "lowercase, uppercase, digits, symbols; at most 72 bytes UTF-8). The "
        "min_length=8 here is a schema floor; the runtime validator enforces "
        "the full policy.",
    )

    @field_validator("new_password", mode="after")
    @classmethod
    def validate_new_password(cls, v: str) -> str:
        """Enforce the application password policy on the new password."""
        from app.modules.auth.password_policy import validate_password_from_settings  # noqa: PLC0415

        validate_password_from_settings(v)
        return v
