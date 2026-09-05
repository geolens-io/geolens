import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, String, desc, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base

# fix(#1889): the sign-in settle finaliser's ON CONFLICT names this index, so
# the key and the predicate are read from here by the model and by the write.
# Migration 0059 is the source of truth for the DDL.
ARCGIS_SIGNIN_SETTLE_INDEX = "uq_audit_logs_arcgis_signin_attempt"
ARCGIS_SIGNIN_SETTLE_KEY = "(details ->> 'attempt_id')"
ARCGIS_SIGNIN_SETTLE_WHERE = (
    "action = 'arcgis_signin' AND details ->> 'attempt_id' IS NOT NULL"
)

if TYPE_CHECKING:
    from app.modules.auth.models import User


class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (
        # Indexes added in migration 0009 (H-06) — declared on the model so
        # alembic check sees them; the migration is the source of truth for
        # the actual DDL.
        Index(
            "ix_catalog_audit_logs_created_action_resource",
            desc("created_at"),
            "action",
            "resource_type",
        ),
        Index(
            "ix_catalog_audit_logs_resource_id",
            "resource_id",
            postgresql_where="resource_id IS NOT NULL",
        ),
        # DBM-09: GIN trigram index for admin audit-log ILIKE search.
        # Migration 0001_baseline is the source of truth for the actual DDL.
        Index(
            "ix_audit_logs_action_trgm",
            text("lower(catalog.immutable_unaccent(action))"),
            postgresql_using="gin",
            postgresql_ops={
                "lower(catalog.immutable_unaccent(action))": "gin_trgm_ops"
            },
        ),
        Index("ix_catalog_audit_logs_tenant_id", "tenant_id"),
        # fix(#1550 review): one terminal entry per embedding backfill run,
        # enforced by the database rather than by three call sites remembering
        # to check. Three actors can legitimately close the same run — the
        # worker, the status poll and the stale sweeper — and a read-before-
        # write existence check is the same check-then-insert race this change
        # already replaced on the job row. `requested` is excluded so a run can
        # still record both that it was asked for and how it ended. Migration
        # 0051 is the source of truth for the DDL.
        Index(
            "uq_audit_logs_terminal_embedding_backfill",
            text("(details ->> 'job_id')"),
            unique=True,
            postgresql_where=text(
                "action = 'embedding.backfill' AND details ->> 'outcome' <> 'requested'"
            ),
        ),
        Index(
            ARCGIS_SIGNIN_SETTLE_INDEX,
            text(ARCGIS_SIGNIN_SETTLE_KEY),
            unique=True,
            postgresql_where=text(ARCGIS_SIGNIN_SETTLE_WHERE),
        ),
        {"schema": "catalog"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=func.gen_random_uuid()
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("catalog.users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # Durable scope survives actor deletion and covers system-authored events.
    # NULL retains byte-identical single-tenant behavior; hosted RLS fails
    # closed and the insert trigger stamps it from the active tenant GUC.
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(50), nullable=False)
    resource_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    details: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    user: Mapped["User"] = relationship("User", lazy="joined")
