import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'pending', 'suspended', 'deactivated')",
            name="chk_users_status",
        ),
        CheckConstraint(
            "auth_provider IN ('local', 'oidc', 'oauth')",
            name="chk_users_auth_provider",
        ),
        CheckConstraint(
            "is_active = (status = 'active')",
            name="chk_users_status_active_consistency",
        ),
        # Partial index: most user lookups don't need to scan pending rows; the
        # admin "pending users" view does, and benefits from this targeted index.
        Index(
            "idx_users_status_pending",
            "status",
            postgresql_where="status = 'pending'",
        ),
        # DBM-09: GIN trigram index for admin user search ILIKE on username.
        # Migration 0001_baseline is the source of truth for the actual DDL.
        Index(
            "ix_users_username_trgm",
            text("lower(catalog.immutable_unaccent(username))"),
            postgresql_using="gin",
            postgresql_ops={
                "lower(catalog.immutable_unaccent(username))": "gin_trgm_ops"
            },
        ),
        # GIN trigram index for admin user search ILIKE on email (pairs with the
        # username index so the username-OR-email search BitmapOrs both).
        # Migration 0001_baseline is the source of truth for the actual DDL.
        Index(
            "ix_users_email_trgm",
            text("lower(catalog.immutable_unaccent(email))"),
            postgresql_using="gin",
            postgresql_ops={"lower(catalog.immutable_unaccent(email))": "gin_trgm_ops"},
        ),
        # TSEAM-02: Two-partial-index uniqueness pattern (Phase 1207).
        # Migration 0005_dormant_tenancy replaces the global unique
        # constraints with these four partial unique indexes: global
        # uniqueness when tenant_id IS NULL, per-tenant when NOT NULL. A
        # naive composite unique on nullable tenant_id is forbidden because
        # Postgres treats NULLs as DISTINCT, silently breaking single_tenant.
        Index(
            "uq_users_username_global",
            "username",
            unique=True,
            postgresql_where=text("tenant_id IS NULL"),
        ),
        Index(
            "uq_users_username_tenant",
            "tenant_id",
            "username",
            unique=True,
            postgresql_where=text("tenant_id IS NOT NULL"),
        ),
        Index(
            "uq_users_email_global",
            "email",
            unique=True,
            postgresql_where=text("tenant_id IS NULL"),
        ),
        Index(
            "uq_users_email_tenant",
            "tenant_id",
            "email",
            unique=True,
            postgresql_where=text("tenant_id IS NOT NULL"),
        ),
        {"schema": "catalog"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=func.gen_random_uuid()
    )
    username: Mapped[str] = mapped_column(String(150), nullable=False)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # TSEAM-01 (Phase 1207): dormant tenant_id — nullable, no FK enforcement.
    # NULL means single_tenant (global) scope.  FK + RLS enforcement: Phase 1208.
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    password_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), server_default="active", nullable=False
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true", nullable=False
    )
    # SIGNUP-03 (Phase 1231): set to True by redeem_verification_token() on
    # verification-link click; server_default="false" so new users start unverified.
    email_verified: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )
    # SEC-S15 (Phase 1062-01): JWT revocation primitive, bumped on logout
    # and password change. An access JWT whose token_version is less than
    # this value is rejected on the next authenticated request.
    token_version: Mapped[int] = mapped_column(
        Integer, default=1, server_default="1", nullable=False
    )
    # fix(#821): API-key revocation primitive, separate from token_version.
    # Bumped only on security events (password/role change, SAML-to-local),
    # NOT logout, so long-lived API keys (CI, MCP, tile URLs) survive a web
    # sign-out. Keys snapshot this at mint and stop resolving on mismatch.
    key_epoch: Mapped[int] = mapped_column(
        Integer, default=1, server_default="1", nullable=False
    )
    # fix(#1455): revocation horizon — every session credential issued at or
    # before this instant is dead, regardless of its own state. token_version
    # and the refresh-row UPDATE only revoke what one statement's snapshot
    # sees, which can't express "everything issued up to now"; this covers a
    # rotation committing just after that snapshot. Read at use time by both
    # refresh lookups and both JWT dependencies. NULL until first
    # revocation; stamped from the DB clock (matches RefreshToken.created_at).
    sessions_revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    auth_provider: Mapped[str] = mapped_column(
        String(20), server_default="local", nullable=False
    )
    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    roles: Mapped[list["Role"]] = relationship(
        secondary="catalog.user_roles", back_populates="users", lazy="selectin"
    )


class Role(Base):
    __tablename__ = "roles"
    __table_args__ = {"schema": "catalog"}

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=func.gen_random_uuid()
    )
    name: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    users: Mapped[list["User"]] = relationship(
        secondary="catalog.user_roles", back_populates="roles", lazy="selectin"
    )


class UserRole(Base):
    __tablename__ = "user_roles"
    __table_args__ = (
        # T-3: trailing composite-PK FK; covering index added in migration 0001_baseline.
        Index("ix_user_roles_role_id", "role_id"),
        {"schema": "catalog"},
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("catalog.users.id", ondelete="CASCADE"), primary_key=True
    )
    role_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("catalog.roles.id", ondelete="CASCADE"), primary_key=True
    )


class ApiKey(Base):
    __tablename__ = "api_keys"
    __table_args__ = (
        CheckConstraint(
            "scope IN ('full', 'read_only')",
            name="chk_api_keys_scope",
        ),
        {"schema": "catalog"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=func.gen_random_uuid()
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("catalog.users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    key_hash: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    # Non-secret operator identifier. Keys pre-dating migration 0016 are
    # NULL; new keys store an 8-char prefix plus last four for identification.
    fingerprint: Mapped[str | None] = mapped_column(String(20), nullable=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true"
    )
    # fix(#821): optional expiry. NULL preserves the pre-0029 forever-key
    # behavior; at resolution an expired key fails exactly like an invalid one.
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # fix(#821): snapshot of owner's key_epoch at mint. When key_epoch is
    # bumped (password/role change, SAML-to-local — NOT logout), keys minted
    # before the bump stop resolving. Migration 0029 backfilled existing keys.
    key_epoch: Mapped[int] = mapped_column(Integer, nullable=False)
    # fix(#875): least-privilege machine credentials. "read_only"
    # authenticates GET/HEAD/OPTIONS only, refused elsewhere at the
    # resolution chokepoint (_resolve_api_key). server_default backfills
    # pre-0032 keys as "full" (no behavior change).
    scope: Mapped[str] = mapped_column(
        String(20), server_default="full", nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    user: Mapped["User"] = relationship("User", lazy="selectin")


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"
    __table_args__ = (
        # Index added in migration 0008 (H-09) — declared on the model so
        # alembic check sees it; the migration is the source of truth for
        # the actual DDL.
        Index("ix_catalog_refresh_tokens_expires_at", "expires_at"),
        # DBM-10 covering index added in migration 0001_baseline.
        Index("ix_refresh_tokens_user_id", "user_id"),
        Index("ix_refresh_tokens_family_id", "family_id"),
        {"schema": "catalog"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=func.gen_random_uuid()
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("catalog.users.id", ondelete="CASCADE"), nullable=False
    )
    family_id: Mapped[uuid.UUID] = mapped_column(
        server_default=func.gen_random_uuid(), nullable=False
    )
    rotated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    revoked: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )

    user: Mapped["User"] = relationship("User", lazy="selectin")


class EmailVerificationToken(Base):
    """Single-use expiring verification token for email confirmation (SIGNUP-03).

    Mirrors the ``RefreshToken`` opaque-token pattern: the raw token is
    returned once and never persisted, only its sha256 digest is stored.
    Redeeming sets ``consumed_at`` (single-use gate); expired or consumed
    tokens are rejected by the same query filter, so the caller can't
    distinguish them (enumeration-safe, SIGNUP-05).
    """

    __tablename__ = "email_verification_tokens"
    __table_args__ = (
        # Index on expires_at mirrors the RefreshToken pattern — efficient
        # cleanup of expired tokens.  Migration 0009 is the source of truth
        # for the actual DDL.
        Index("ix_catalog_email_verification_tokens_expires_at", "expires_at"),
        # Covering index on user_id for per-user token queries (resend flow).
        Index("ix_email_verification_tokens_user_id", "user_id"),
        {"schema": "catalog"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=func.gen_random_uuid()
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("catalog.users.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    # None = not yet consumed; set to now() on first successful redemption.
    consumed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    user: Mapped["User"] = relationship("User", lazy="selectin")
