"""Pydantic schemas for OAuth provider CRUD operations."""

import uuid
from datetime import datetime
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.edition import is_enterprise


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
_IDP_ENTITY_ID_MAX = 512  # oauth_providers.idp_entity_id: String(512)
_IDP_SSO_URL_MAX = 512  # oauth_providers.idp_sso_url: String(512)
_SP_ENTITY_ID_MAX = 512  # oauth_providers.sp_entity_id: String(512)

# SAML provider fields — required when provider_type='saml', forbidden otherwise.
# Enforced by the per-type model_validator below.
_SAML_FIELDS = ("idp_entity_id", "idp_sso_url", "idp_certificate", "sp_entity_id")


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
    provider_type: Literal["google", "microsoft", "oidc", "saml"] = Field(
        description="OAuth or SAML provider type. 'google' and 'microsoft' auto-populate the discovery URL; 'oidc' is generic OAuth/OIDC; 'saml' enables SAML SSO (requires enterprise edition)."
    )
    client_id: str | None = Field(
        default=None,
        max_length=500,
        description="OAuth client ID issued by the IdP. Required for OAuth/OIDC providers; omit for SAML.",
    )
    client_secret: str | None = Field(
        default=None,
        max_length=1000,
        description="OAuth client secret issued by the IdP. Stored encrypted; never returned in responses. Required for OAuth/OIDC providers; omit for SAML.",
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
    idp_entity_id: str | None = Field(
        default=None,
        max_length=_IDP_ENTITY_ID_MAX,
        description="SAML IdP entityID. Required for SAML providers.",
    )
    idp_sso_url: str | None = Field(
        default=None,
        max_length=_IDP_SSO_URL_MAX,
        description="SAML IdP SSO URL (HTTP-Redirect or HTTP-POST binding). Required for SAML providers.",
    )
    idp_certificate: str | None = Field(
        default=None,
        description="SAML IdP signing certificate (PEM). Required for SAML providers. Stored Fernet-encrypted at rest; never returned in responses.",
    )
    sp_entity_id: str | None = Field(
        default=None,
        max_length=_SP_ENTITY_ID_MAX,
        description="SP entityID for this provider. Required for SAML providers. Default suggestion: {public_api_url}/auth/saml/{slug}.",
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
        description="Name of the JWT/userinfo claim (or SAML attribute) that contains group memberships. Set to enable group-based role mapping.",
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

    @field_validator("idp_sso_url")
    @classmethod
    def _check_idp_url(cls, value: str | None) -> str | None:
        return _validate_optional_http_url(value)

    @model_validator(mode="after")
    def _validate_per_type(self):
        """Enforce per-type field requirements (RESEARCH §6, D-12).

        SAML providers require all 4 SAML fields and don't need OAuth credentials.
        OAuth providers require client_id + client_secret and must NOT have SAML
        fields populated (mixed config is rejected to prevent ambiguity).
        """
        if self.provider_type == "saml":
            missing = [f for f in _SAML_FIELDS if not getattr(self, f)]
            if missing:
                raise ValueError(f"SAML providers require: {', '.join(missing)}")
        else:
            if not self.client_id or not self.client_secret:
                raise ValueError(
                    f"{self.provider_type} providers require client_id and client_secret"
                )
            extra = [f for f in _SAML_FIELDS if getattr(self, f)]
            if extra:
                raise ValueError(
                    f"{self.provider_type} providers must not set SAML fields: {', '.join(extra)}"
                )
        return self

    @model_validator(mode="after")
    def _validate_idp_mapping_gate(self):
        """Gate group-based role mapping behind the enterprise edition (D-01, D-02, D-03).

        Empty dict ({}) and None are allowed in community — they represent
        "no mapping" / "clear mapping" (D-02 carve-out). Only non-empty
        group_role_mapping or a non-None group_claim triggers the gate.
        """
        if not is_enterprise():
            if self.group_claim is not None:
                raise ValueError(
                    "Group-based role mapping requires the GeoLens Enterprise overlay"
                )
            if (
                isinstance(self.group_role_mapping, dict)
                and len(self.group_role_mapping) > 0
            ):
                raise ValueError(
                    "Group-based role mapping requires the GeoLens Enterprise overlay"
                )
        return self


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
    provider_type: Literal["google", "microsoft", "oidc", "saml"] | None = Field(
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
    idp_entity_id: str | None = Field(
        default=None,
        max_length=_IDP_ENTITY_ID_MAX,
        description="Updated SAML IdP entityID.",
    )
    idp_sso_url: str | None = Field(
        default=None,
        max_length=_IDP_SSO_URL_MAX,
        description="Updated SAML IdP SSO URL.",
    )
    idp_certificate: str | None = Field(
        default=None,
        description="Updated SAML IdP signing certificate (PEM). Setting this rotates the stored cert; omit to leave unchanged.",
    )
    sp_entity_id: str | None = Field(
        default=None,
        max_length=_SP_ENTITY_ID_MAX,
        description="Updated SP entityID.",
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

    @field_validator("idp_sso_url")
    @classmethod
    def _check_idp_url(cls, value: str | None) -> str | None:
        return _validate_optional_http_url(value)

    @model_validator(mode="after")
    def _validate_idp_mapping_gate(self):
        """Gate group-based role mapping behind the enterprise edition (D-01, D-02, D-03).

        Empty dict ({}) and None are allowed in community — they represent
        "no mapping" / "clear mapping" (D-02 carve-out). Only non-empty
        group_role_mapping or a non-None group_claim triggers the gate.
        """
        if not is_enterprise():
            if self.group_claim is not None:
                raise ValueError(
                    "Group-based role mapping requires the GeoLens Enterprise overlay"
                )
            if (
                isinstance(self.group_role_mapping, dict)
                and len(self.group_role_mapping) > 0
            ):
                raise ValueError(
                    "Group-based role mapping requires the GeoLens Enterprise overlay"
                )
        return self


class OAuthProviderResponse(BaseModel):
    """Response schema for OAuth/SAML provider.

    Write-only credentials are never exposed:
      - ``client_secret_encrypted`` (OAuth client secret) — excluded.
      - ``idp_certificate`` (SAML IdP signing cert, Fernet-encrypted at rest) — excluded.

    The 3 non-secret SAML fields (``idp_entity_id``, ``idp_sso_url``,
    ``sp_entity_id``) ARE exposed so the admin UI can display them.

    Pitfall 11 interaction: those 3 fields are declared with ``deferred=True``
    on the OAuth ORM model so community DBs (which lack the columns) do not
    crash on SELECT. Pydantic's ``from_attributes=True`` would normally trigger
    an implicit deferred load on attribute access, which fails under FastAPI's
    async context with ``MissingGreenlet``. The ``model_validator(mode="before")``
    below reads the SAML fields directly from ``obj.__dict__`` so unloaded
    attributes default to None instead of triggering IO. SAML admin endpoints
    that need the values must use ``undefer_group("saml")`` at query time.
    """

    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode="before")
    @classmethod
    def _safe_read_deferred_saml_fields(cls, data):
        """Read SAML fields from __dict__ to skip deferred lazy-load.

        Returning a plain dict bypasses ``from_attributes`` for SAML fields
        only — community OAuth queries (which never load SAML columns) get
        ``None`` for the 3 non-secret SAML fields rather than triggering a
        deferred SELECT against a non-existent column.
        """
        # Pydantic passes either a dict (already-projected) or an ORM instance.
        # Only intercept the ORM-instance case.
        if isinstance(data, dict):
            return data
        # Build a dict from the ORM instance's loaded attributes; deferred
        # SAML columns appear as None unless explicitly loaded.
        loaded = dict(getattr(data, "__dict__", {}))
        # Drop SQLAlchemy internal state.
        loaded.pop("_sa_instance_state", None)
        # Ensure the 3 non-secret SAML fields exist as keys (None if not loaded).
        for f in ("idp_entity_id", "idp_sso_url", "sp_entity_id"):
            loaded.setdefault(f, None)
        return loaded

    id: uuid.UUID = Field(description="Unique provider identifier.")
    slug: str = Field(description="URL-safe identifier used in the callback URL.")
    display_name: str = Field(description="Label shown on the login page button.")
    provider_type: str = Field(
        description="Provider type: 'google', 'microsoft', 'oidc', or 'saml'."
    )
    client_id: str | None = Field(
        default=None,
        description="OAuth client ID. Visible to admins; never exposes client_secret. Null for SAML providers.",
    )
    discovery_url: str | None = Field(default=None, description="OIDC discovery URL.")
    authorize_url: str | None = Field(
        default=None, description="Authorization endpoint."
    )
    token_url: str | None = Field(default=None, description="Token endpoint.")
    userinfo_url: str | None = Field(default=None, description="Userinfo endpoint.")
    idp_entity_id: str | None = Field(
        default=None, description="SAML IdP entityID (SAML providers only)."
    )
    idp_sso_url: str | None = Field(
        default=None, description="SAML IdP SSO URL (SAML providers only)."
    )
    sp_entity_id: str | None = Field(
        default=None,
        description="SP entityID for this SAML provider (SAML providers only).",
    )
    # idp_certificate intentionally NOT exposed — write-only credential, mirrors
    # client_secret_encrypted exclusion.
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
