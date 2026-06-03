import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, String, desc, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base

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
        # Migration 0015 is the source of truth for the actual DDL.
        Index(
            "ix_audit_logs_action_trgm",
            text("lower(catalog.immutable_unaccent(action))"),
            postgresql_using="gin",
            postgresql_ops={
                "lower(catalog.immutable_unaccent(action))": "gin_trgm_ops"
            },
        ),
        {"schema": "catalog"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=func.gen_random_uuid()
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("catalog.users.id", ondelete="SET NULL"), nullable=True, index=True
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
