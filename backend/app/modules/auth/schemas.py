import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


class TokenResponse(BaseModel):
    access_token: str = Field(description="JWT access token for Authorization header")
    refresh_token: str = Field(
        description="Opaque token used to obtain a new access token"
    )
    token_type: str = "bearer"
    expires_in: int = Field(description="Seconds until the access token expires")


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=150, description="Unique login name", example="jdoe")
    password: str = Field(
        min_length=8, max_length=256, description="Plaintext password (min 8 chars)", example="securePass123"
    )
    email: EmailStr | None = Field(
        default=None, max_length=255, description="Optional email address", example="jdoe@example.com"
    )


class RegisterResponse(BaseModel):
    message: str


class ConfigResponse(BaseModel):
    registration_enabled: bool = Field(
        description="Whether self-service registration is open"
    )


class UserResponse(BaseModel):
    id: uuid.UUID
    username: str
    email: str | None
    is_active: bool
    status: str = Field(description="Account status: active, pending, disabled")
    last_login_at: datetime | None
    created_at: datetime
    roles: list[str] = Field(
        description="Assigned role names, e.g. ['admin', 'editor']"
    )

    model_config = {"from_attributes": True}


class LoginRequest(BaseModel):
    username: str = Field(max_length=150, example="admin")
    password: str = Field(max_length=256, example="changeme")


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
    new_password: str = Field(min_length=8, max_length=256)
