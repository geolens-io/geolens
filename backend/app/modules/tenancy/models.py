"""Tenancy ORM models — dormant substrate for Phase 1207.

These three tables (organizations, tenants, org_memberships) are created by
migration 0005_dormant_tenancy and are inert in single_tenant mode.  No
foreign-key enforcement is wired in this phase; FK constraints and RLS
policies land in Phase 1208.

All models are declared on the shared Base so ``alembic check`` / autogenerate
see them alongside the rest of the catalog schema.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, String, Text, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Organization(Base):
    """Top-level billing/ownership entity.

    In single_tenant mode this table is empty and never queried.
    The cloud overlay (Phase 1211) populates it at tenant-signup time.
    """

    __tablename__ = "organizations"
    __table_args__ = {"schema": "catalog"}

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class Tenant(Base):
    """Logical tenant within an organization (subdomain-shaped slug).

    ``slug`` is used later by the TSEAM-04 request-context middleware to
    resolve the tenant from the subdomain.  The non-unique index is intentional
    at this phase — per-tenant uniqueness wiring lands in Phase 1208.

    ``organization_id`` is stored without a FK constraint (dormant link).
    """

    __tablename__ = "tenants"
    __table_args__ = (
        Index("ix_tenants_slug", "slug"),
        {"schema": "catalog"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    slug: Mapped[str] = mapped_column(String(63), nullable=False)
    # Dormant link — no FK constraint until Phase 1208.
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    # Shard routing key — trivial 'shard-0' at one shard; Phase 1214 populates
    # real values when shards are promoted/rebalanced.  This is the routing MAP
    # consumed by tenant_shard_id() in backend/app/core/db/tenant_schema.py.
    shard_id: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        server_default=text("'shard-0'"),
        comment="Shard routing key for Phase-1214 promote/rebalance (trivial 'shard-0' at one shard)",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class OrgMembership(Base):
    """User ↔ Organization membership join table.

    Composite PK (user_id, organization_id) — both stored without FK
    constraints (dormant) until Phase 1208.
    """

    __tablename__ = "org_memberships"
    __table_args__ = {"schema": "catalog"}

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, nullable=False
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, nullable=False
    )
    # e.g. 'owner', 'admin', 'member' — nullable until roles are wired.
    role: Mapped[str | None] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
