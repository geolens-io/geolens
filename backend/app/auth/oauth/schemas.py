"""Pydantic schemas for OAuth provider CRUD operations."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class OAuthProviderCreate(BaseModel):
    """Schema for creating a new OAuth provider."""

    slug: str = Field(min_length=1, max_length=100, pattern=r"^[a-z0-9-]+$")
    display_name: str = Field(min_length=1, max_length=200)
    provider_type: Literal["google", "microsoft", "oidc", "saml"]
    client_id: str | None = Field(default=None, min_length=1, max_length=500)
    client_secret: str | None = Field(default=None, min_length=1, max_length=1000)
    metadata_xml: str | None = Field(default=None, max_length=100000)
    discovery_url: str | None = Field(default=None, max_length=2000)
    authorize_url: str | None = Field(default=None, max_length=2000)
    token_url: str | None = Field(default=None, max_length=2000)
    userinfo_url: str | None = Field(default=None, max_length=2000)
    scopes: str = Field(default="openid profile email", max_length=500)
    default_role: str = Field(default="viewer", max_length=50)
    group_claim: str | None = Field(default=None, max_length=200)
    group_role_mapping: dict | None = None
    enabled: bool = True


class OAuthProviderUpdate(BaseModel):
    """Schema for updating an existing OAuth provider. All fields optional."""

    slug: str | None = None
    display_name: str | None = None
    provider_type: Literal["google", "microsoft", "oidc", "saml"] | None = None
    client_id: str | None = None
    client_secret: str | None = None
    metadata_xml: str | None = None
    discovery_url: str | None = None
    authorize_url: str | None = None
    token_url: str | None = None
    userinfo_url: str | None = None
    scopes: str | None = None
    default_role: str | None = None
    group_claim: str | None = None
    group_role_mapping: dict | None = None
    enabled: bool | None = None


class OAuthProviderResponse(BaseModel):
    """Response schema for OAuth provider. Never exposes client_secret."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    slug: str
    display_name: str
    provider_type: str
    client_id: str
    discovery_url: str | None = None
    authorize_url: str | None = None
    token_url: str | None = None
    userinfo_url: str | None = None
    scopes: str
    default_role: str
    group_claim: str | None = None
    group_role_mapping: dict | None = None
    idp_entity_id: str | None = None
    sp_entity_id: str | None = None
    enabled: bool
    created_at: datetime
    updated_at: datetime


class OAuthProviderPublic(BaseModel):
    """Minimal provider info for the login page (no secrets, no config)."""

    model_config = ConfigDict(from_attributes=True)

    slug: str
    display_name: str
    provider_type: str
