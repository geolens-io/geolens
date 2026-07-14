from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.modules.quota.schemas import UserQuotaUsage

# User account status enum mirrors the CHECK constraint on User.status.
UserStatus = Literal["active", "pending", "suspended", "deactivated"]


class TokenResponse(BaseModel):
    access_token: str = Field(description="JWT access token for Authorization header")
    refresh_token: str = Field(
        description="Opaque token used to obtain a new access token"
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
        # Note on the min_length=8 floor: Pydantic evaluates Field constraints
        # (BEFORE) @field_validator(mode="after"). Keeping min_length=8 here
        # provides a fast-fail floor that avoids the database round-trip for
        # trivially short passwords. The canonical policy (default: 12 chars
        # + 3-of-4 class diversity) is enforced by validate_password below.
        # Both errors are 422; the field-level message fires first when the
        # password is < 8 chars.
        description="Plaintext password (policy: min 12 chars, 3+ character classes)",
        json_schema_extra={"example": "securePass123!"},
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
        """Enforce the application password policy (SEC-S16, Phase 1062-01)."""
        from app.modules.auth.password_policy import validate_password_from_settings  # noqa: PLC0415

        validate_password_from_settings(v)
        return v


class RegisterResponse(BaseModel):
    message: str
    # M1 follow-up (Phase 1234): machine-readable post-registration step so the
    # client renders the correct pending view from the server's actual decision
    # instead of inferring it from a cached /auth/config snapshot (race-free).
    # Computed purely from (config + submitted email) and therefore IDENTICAL for
    # a genuine new signup and a swallowed username/email collision — the
    # collision path must not be distinguishable (SEC-012 enumeration-safety).
    # None on non-register responses (verify/resend reuse this model).
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
        description="Whether self-service registration is open"
    )
    # SIGNUP-01 (Phase 1231): allow_signup is the cleaner public alias for
    # registration_enabled that the login page reads to gate the signup affordance.
    # Mirrors registration_enabled exactly; both are kept for back-compat.
    allow_signup: bool = Field(
        default=False,
        description=(
            "Whether self-serve registration is open. "
            "Alias for registration_enabled; login UI uses this to show/hide the signup link."
        ),
    )
    # SIGNUP-04 (Phase 1231): email verification required flag for the login
    # page to display appropriate messaging after registration.
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
    # FRONT-01 (Phase 1223): when True the frontend redirects unauthenticated
    # visitors at "/" to "/login" (the marketing landing surface).  Default
    # False — self-hosters upgrading see zero change.
    landing_first: bool = Field(
        default=False,
        description=(
            "When true, unauthenticated visits to '/' are redirected to '/login' "
            "as the product landing page. Default false (search catalog is the root)."
        ),
    )
    # DEMO-03 (Phase 1226): when True, logged-in users see a persistent
    # demo-account banner. Default false — self-hosters see no banner.
    demo_mode: bool = Field(
        default=False,
        description=(
            "When true, logged-in users see a persistent demo-account banner. "
            "Default false — self-hosters see no banner."
        ),
    )
    # SSO-03 (Phase 1236 Plan 02): when False, POST /auth/login returns 403 for
    # non-admin users and the login page should hide the username/password form.
    # Default True — older clients that don't parse this field keep the form visible.
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
    quota_usage: UserQuotaUsage | None = Field(
        default=None,
        description=(
            "Per-user storage quota usage. Populated only on admin list responses; "
            "None when the caller did not load usage (e.g. /auth/me, single-user GET)."
        ),
    )

    model_config = {"from_attributes": True}


class LoginRequest(BaseModel):
    username: str = Field(max_length=150, json_schema_extra={"example": "admin"})
    password: str = Field(max_length=256, json_schema_extra={"example": "changeme"})


class RefreshRequest(BaseModel):
    refresh_token: str = Field(max_length=512)


class PermissionsResponse(BaseModel):
    permissions: dict[str, bool] = Field(
        description="Map of permission names to granted/denied"
    )


class ApiKeyCreateRequest(BaseModel):
    name: str = Field(
        min_length=1, max_length=255, description="Human-readable label for the API key"
    )


class ApiKeyCreateResponse(BaseModel):
    id: uuid.UUID
    key: str = Field(description="The API key secret (shown only once)")
    fingerprint: str = Field(
        description="Non-secret key identifier (prefix and last four characters)"
    )
    name: str
    created_at: datetime


class ApiKeyListItem(BaseModel):
    id: uuid.UUID
    name: str
    fingerprint: str | None = Field(
        description="Non-secret key identifier; null for keys created before fingerprint support"
    )
    is_active: bool
    created_at: datetime
    last_used_at: datetime | None


class ApiKeyListResponse(BaseModel):
    items: list[ApiKeyListItem]
    total: int


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    # WR-03: min_length=8 is the schema floor (allows the Pydantic validator to
    # reject obviously short inputs before hitting the field_validator). The
    # runtime policy enforced by validate_new_password / validate_password_from_settings
    # is stricter: at least 12 characters and 3+ character classes (SEC-S16).
    # The description surfaces the actual policy in the OpenAPI docs so clients
    # do not generate passwords that pass schema validation but fail the route.
    new_password: str = Field(
        min_length=8,
        max_length=256,
        description="New password (policy: min 12 chars, 3+ character classes: "
        "lowercase, uppercase, digits, symbols). The min_length=8 here is a "
        "schema floor; the runtime validator enforces the full policy.",
    )

    @field_validator("new_password", mode="after")
    @classmethod
    def validate_new_password(cls, v: str) -> str:
        """Enforce the application password policy on the new password (SEC-S16)."""
        from app.modules.auth.password_policy import validate_password_from_settings  # noqa: PLC0415

        validate_password_from_settings(v)
        return v
