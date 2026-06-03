"""SQLAlchemy models for OAuth/OIDC provider configuration and account linking."""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class OAuthProvider(Base):
    """OAuth/OIDC provider configuration (Google, Microsoft, generic OIDC)."""

    __tablename__ = "oauth_providers"
    __table_args__ = (
        CheckConstraint(
            # 'saml' is added by enterprise migration e002_add_saml_columns;
            # the literal here matches the relaxed constraint so model and DB
            # stay in sync when the enterprise overlay is loaded. Community
            # deployments still see only oidc/google/microsoft rows because
            # SAML rows can only be created when the enterprise overlay also
            # supplies the required nullable SAML columns (added by e002).
            "provider_type IN ('oidc', 'google', 'microsoft', 'saml')",
            name="chk_oauth_providers_type",
        ),
        {"schema": "catalog"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=func.gen_random_uuid()
    )
    slug: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    provider_type: Mapped[str] = mapped_column(String(20), nullable=False)
    client_id: Mapped[str] = mapped_column(String(512), nullable=False)
    client_secret_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    discovery_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    authorize_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    token_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    userinfo_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # SAML provider columns (added by enterprise migration e002_add_saml_columns).
    # All four are nullable; only populated when provider_type='saml' and the
    # enterprise overlay is loaded.
    #
    # Pitfall 11 mitigation: declared with ``deferred=True`` so they are NOT
    # included in the default ``SELECT`` against ``oauth_providers``. Community
    # deployments (which do NOT run e002_add_saml_columns) lack these columns
    # entirely; without ``deferred``, every list/get of an OAuth provider would
    # raise ``UndefinedColumnError``. With ``deferred``, the columns are only
    # loaded when explicitly accessed (e.g. ``provider.idp_entity_id`` in the
    # SAML router) -- which only happens when the enterprise overlay is loaded
    # AND the row is provider_type='saml'. Grouped under ``deferred_group="saml"``
    # so the SAML router can ``undefer_group("saml")`` to load all four in a
    # single query when needed. Schema/service-layer validation that these are
    # required for SAML and forbidden for OAuth lands in Plan 03.
    idp_entity_id: Mapped[str | None] = mapped_column(
        String(512), nullable=True, deferred=True, deferred_group="saml"
    )
    idp_sso_url: Mapped[str | None] = mapped_column(
        String(512), nullable=True, deferred=True, deferred_group="saml"
    )
    idp_certificate: Mapped[str | None] = mapped_column(
        Text, nullable=True, deferred=True, deferred_group="saml"
    )
    sp_entity_id: Mapped[str | None] = mapped_column(
        String(512), nullable=True, deferred=True, deferred_group="saml"
    )
    scopes: Mapped[str] = mapped_column(
        String(512), server_default="openid profile email"
    )
    default_role: Mapped[str] = mapped_column(String(50), server_default="viewer")
    group_claim: Mapped[str | None] = mapped_column(String(100), nullable=True)
    group_role_mapping: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class OAuthAccount(Base):
    """Links an external OAuth identity to a local GeoLens user."""

    __tablename__ = "oauth_accounts"
    __table_args__ = (
        UniqueConstraint(
            "provider_id", "subject", name="uq_oauth_account_provider_subject"
        ),
        {"schema": "catalog"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=func.gen_random_uuid()
    )
    provider_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("catalog.oauth_providers.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("catalog.users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    user: Mapped["User"] = relationship("User", lazy="selectin")
    provider: Mapped["OAuthProvider"] = relationship("OAuthProvider", lazy="selectin")


# Avoid circular import - User is referenced as string in relationships
from app.modules.auth.models import User  # noqa: E402, F401
