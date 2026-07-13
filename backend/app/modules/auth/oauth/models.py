"""SQLAlchemy models for OAuth/OIDC provider configuration and account linking."""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class OAuthProvider(Base):
    """OAuth/OIDC provider configuration (Google, Microsoft, generic OIDC)."""

    __tablename__ = "oauth_providers"
    __table_args__ = (
        CheckConstraint(
            # 'saml' is co-owned by enterprise migration e002_add_saml_columns;
            # 'github' is added by OSS migration 0010_oauth_github_provider_type.
            # The literal here matches the widest constraint so the model and DB
            # stay in sync when either overlay is loaded. Community deployments
            # still see only oidc/google/microsoft/github rows in practice because
            # SAML rows require the enterprise overlay (e002 + is_enterprise() gate).
            "provider_type IN ('oidc', 'google', 'microsoft', 'saml', 'github')",
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
    # SAML provider columns. All four are nullable; only populated when
    # provider_type='saml' and the enterprise overlay is loaded.
    #
    # fix(#435): these are core-owned columns now. Community databases DO have them
    # — core migration ``0008_oauth_saml_columns`` adds all four (``ADD COLUMN IF
    # NOT EXISTS``, so the enterprise overlay's ``e002_add_saml_columns`` stays a
    # compatible no-op). They simply sit NULL for OSS OAuth/OIDC providers, and the
    # ``'saml'`` provider_type CHECK constraint remains enterprise-only.
    #
    # ``deferred=True`` is kept for the original reason it was added: the columns stay
    # out of the default ``SELECT`` against ``oauth_providers``. Grouped under
    # ``deferred_group="saml"`` so the SAML router can ``undefer_group("saml")`` to
    # load all four in a single query when needed.
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
        Index(
            "uq_oauth_accounts_provider_subject_global",
            "provider_id",
            "subject",
            unique=True,
            postgresql_where=text("tenant_id IS NULL"),
        ),
        Index(
            "uq_oauth_accounts_provider_subject_tenant",
            "tenant_id",
            "provider_id",
            "subject",
            unique=True,
            postgresql_where=text("tenant_id IS NOT NULL"),
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
    # NULL is the dormant single-tenant scope. In hosted mode PostgreSQL stamps
    # this from app.current_tenant and RLS keeps account links tenant-local.
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    user: Mapped["User"] = relationship("User", lazy="selectin")
    provider: Mapped["OAuthProvider"] = relationship("OAuthProvider", lazy="selectin")


# Avoid circular import - User is referenced as string in relationships
from app.modules.auth.models import User  # noqa: E402, F401
