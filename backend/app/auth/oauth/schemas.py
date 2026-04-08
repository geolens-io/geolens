"""Pydantic schemas for OAuth provider CRUD operations."""

import uuid
from datetime import datetime
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _validate_optional_http_url(value: str | None) -> str | None:
    """Validate an optional HTTP(S) URL (TYPE-N4).

    Returns the value unchanged if None or a parseable HTTP/HTTPS URL.
    Raises ValueError otherwise. Prefer this over Pydantic's HttpUrl so the
    DB column type can stay ``str`` (avoids an Alembic migration) while still
    rejecting obvious garbage like "not a url" or schemeless strings.
    """
    if value is None or value == "":
        return value
    parsed = urlparse(value)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("URL must use http or https scheme")
    if not parsed.netloc:
        raise ValueError("URL must include a host")
    return value


# TYPE-5: Pydantic max_length values below must match the SQLAlchemy String(N)
# widths in models.py to avoid silent truncation at DB insert. Column widths
# are the source of truth.
_SLUG_MAX = 50  # oauth_providers.slug: String(50)
_DISPLAY_NAME_MAX = 100  # oauth_providers.display_name: String(100)
_URL_MAX = 512  # discovery_url, authorize_url, token_url, userinfo_url: String(512)
_GROUP_CLAIM_MAX = 100  # oauth_providers.group_claim: String(100)


class OAuthProviderCreate(BaseModel):
    """Schema for creating a new OAuth provider."""

    slug: str = Field(
        min_length=1,
        max_length=_SLUG_MAX,
        pattern=r"^[a-z0-9-]+$",
        description="URL-safe identifier used in callback URLs (e.g. 'google', 'azure-ad'). Lowercase, digits, and hyphens only.",
    )
    display_name: str = Field(
        min_length=1,
        max_length=_DISPLAY_NAME_MAX,
        description="Human-readable label shown on the login page button.",
    )
    provider_type: Literal["google", "microsoft", "oidc"] = Field(
        description="OAuth provider type. 'google' and 'microsoft' auto-populate the discovery URL; 'oidc' is generic."
    )
    client_id: str = Field(
        min_length=1, max_length=500, description="OAuth client ID issued by the IdP."
    )
    client_secret: str = Field(
        min_length=1,
        max_length=1000,
        description="OAuth client secret issued by the IdP. Stored encrypted; never returned in responses.",
    )
    discovery_url: str | None = Field(
        default=None,
        max_length=_URL_MAX,
        description="OIDC discovery URL ending in `.well-known/openid-configuration`. Auto-populated for Google and Microsoft.",
    )
    authorize_url: str | None = Field(
        default=None,
        max_length=_URL_MAX,
        description="Authorization endpoint. Only needed when discovery_url is not set.",
    )
    token_url: str | None = Field(
        default=None,
        max_length=_URL_MAX,
        description="Token endpoint. Only needed when discovery_url is not set.",
    )
    userinfo_url: str | None = Field(
        default=None,
        max_length=_URL_MAX,
        description="Userinfo endpoint. Only needed when discovery_url is not set.",
    )
    scopes: str = Field(
        default="openid profile email",
        max_length=500,
        description="Space-separated OAuth scopes.",
    )
    default_role: str = Field(
        default="viewer",
        max_length=50,
        description="Role assigned to new users created via this provider: 'viewer', 'editor', or 'admin'.",
    )
    group_claim: str | None = Field(
        default=None,
        max_length=_GROUP_CLAIM_MAX,
        description="Name of the JWT/userinfo claim that contains group memberships. Set to enable group-based role mapping.",
    )
    group_role_mapping: dict | None = Field(
        default=None,
        description="JSON object mapping IdP group names to GeoLens roles. First match wins. Falls back to default_role if no group matches.",
    )
    enabled: bool = Field(
        default=True,
        description="Whether the provider button appears on the login page.",
    )

    @field_validator("discovery_url", "authorize_url", "token_url", "userinfo_url")
    @classmethod
    def _check_url(cls, value: str | None) -> str | None:
        return _validate_optional_http_url(value)


class OAuthProviderUpdate(BaseModel):
    """Schema for updating an existing OAuth provider. All fields optional."""

    slug: str | None = Field(
        default=None,
        min_length=1,
        max_length=_SLUG_MAX,
        pattern=r"^[a-z0-9-]+$",
        description="New slug. Changes the callback URL — coordinate with the IdP before updating.",
    )
    display_name: str | None = Field(
        default=None,
        min_length=1,
        max_length=_DISPLAY_NAME_MAX,
        description="New display label.",
    )
    provider_type: Literal["google", "microsoft", "oidc"] | None = Field(
        default=None, description="New provider type. Rarely changed after creation."
    )
    client_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=500,
        description="New client ID. Set when rotating credentials.",
    )
    client_secret: str | None = Field(
        default=None,
        min_length=1,
        max_length=1000,
        description="New client secret. Omit to leave unchanged; setting this rotates the stored secret.",
    )
    discovery_url: str | None = Field(
        default=None, max_length=_URL_MAX, description="Updated OIDC discovery URL."
    )
    authorize_url: str | None = Field(
        default=None, max_length=_URL_MAX, description="Updated authorization endpoint."
    )
    token_url: str | None = Field(
        default=None, max_length=_URL_MAX, description="Updated token endpoint."
    )
    userinfo_url: str | None = Field(
        default=None, max_length=_URL_MAX, description="Updated userinfo endpoint."
    )
    scopes: str | None = Field(
        default=None, max_length=500, description="Updated space-separated scopes."
    )
    default_role: str | None = Field(
        default=None, max_length=50, description="Updated default role for new users."
    )
    group_claim: str | None = Field(
        default=None,
        max_length=_GROUP_CLAIM_MAX,
        description="Updated group claim name.",
    )
    group_role_mapping: dict | None = Field(
        default=None,
        description="Updated group-to-role mapping. Pass an empty object to clear.",
    )
    enabled: bool | None = Field(
        default=None,
        description="Set to false to hide the provider button without deleting the configuration.",
    )

    @field_validator("discovery_url", "authorize_url", "token_url", "userinfo_url")
    @classmethod
    def _check_url(cls, value: str | None) -> str | None:
        return _validate_optional_http_url(value)


class OAuthProviderResponse(BaseModel):
    """Response schema for OAuth provider. Never exposes client_secret."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID = Field(description="Unique provider identifier.")
    slug: str = Field(description="URL-safe identifier used in the callback URL.")
    display_name: str = Field(description="Label shown on the login page button.")
    provider_type: str = Field(
        description="Provider type: 'google', 'microsoft', or 'oidc'."
    )
    client_id: str = Field(
        description="OAuth client ID. Visible to admins; never exposes client_secret."
    )
    discovery_url: str | None = Field(default=None, description="OIDC discovery URL.")
    authorize_url: str | None = Field(
        default=None, description="Authorization endpoint."
    )
    token_url: str | None = Field(default=None, description="Token endpoint.")
    userinfo_url: str | None = Field(default=None, description="Userinfo endpoint.")
    scopes: str = Field(description="Space-separated OAuth scopes.")
    default_role: str = Field(description="Default role assigned to new users.")
    group_claim: str | None = Field(
        default=None, description="Claim name used for group-based role mapping."
    )
    group_role_mapping: dict | None = Field(
        default=None, description="Group-to-role mapping rules."
    )
    enabled: bool = Field(
        description="Whether the provider button appears on the login page."
    )
    created_at: datetime = Field(description="Timestamp the provider was created.")
    updated_at: datetime = Field(description="Timestamp the provider was last updated.")


class OAuthProviderPublic(BaseModel):
    """Minimal provider info for the login page (no secrets, no config)."""

    model_config = ConfigDict(from_attributes=True)

    slug: str = Field(description="URL-safe identifier used in the callback URL.")
    display_name: str = Field(description="Label shown on the login page button.")
    provider_type: str = Field(
        description="Provider type, used by the frontend to pick the right icon."
    )
