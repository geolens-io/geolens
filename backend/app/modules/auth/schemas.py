import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field, field_validator

# User account status enum mirrors the CHECK constraint on User.status.
UserStatus = Literal["active", "pending", "suspended", "deactivated"]


class TokenResponse(BaseModel):
    access_token: str = Field(description="JWT access token for Authorization header")
    refresh_token: str = Field(
        description="Opaque token used to obtain a new access token"
    )
    token_type: str = "bearer"
    expires_in: int = Field(description="Seconds until the access token expires")


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


class ConfigResponse(BaseModel):
    registration_enabled: bool = Field(
        description="Whether self-service registration is open"
    )
    auth_methods: list[str] = Field(
        default_factory=list,
        description=(
            "Auth methods contributed by the active AuthExtension. "
            "Empty in community; e.g. ['saml'] when the enterprise SAML overlay is installed. "
            "Login UI can render conditional sign-in options without needing admin OAuthProvider access."
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
    name: str
    created_at: datetime


class ApiKeyListItem(BaseModel):
    id: uuid.UUID
    name: str
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
