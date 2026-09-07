"""ORM models owned by the sources domain.

One table, and it is deliberately outside the tenant RLS boundary. See
``ArcGISSignInAttempt`` and migration ``0056_arcgis_signin_attempts``.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class ArcGISSignInAttempt(Base):
    """One counted ArcGIS sign-in attempt against one target account.

    fix(#1758): NOT tenant-scoped, on purpose — never add tenant_id here.
    Esri locks an account after 5 failed sign-ins in 15 minutes across ALL
    tenants, so a per-tenant count (e.g. from audit_logs) undercounts.
    account_key and user_scope are non-reversible keyed HMAC-SHA256 digests
    with no username, password, token, URL, or user/tenant id; rows sweep
    after 15 minutes.

    fix(#1775): user_scope (the per-caller half) is counted here rather than
    audit_logs because reserve-then-settle commits the attempt before the
    audit row exists, so a cancelled request would otherwise go uncounted.
    """

    __tablename__ = "arcgis_signin_attempts"
    __table_args__ = (
        # Serves both the windowed per-account count and the time-only sweep.
        Index(
            "ix_catalog_arcgis_signin_attempts_account_time",
            "account_key",
            "attempted_at",
        ),
        # fix(#1775): the same shape for the per-caller budget's own count.
        Index(
            "ix_catalog_arcgis_signin_attempts_user_time",
            "user_scope",
            "attempted_at",
        ),
        Index("ix_catalog_arcgis_signin_attempts_attempted_at", "attempted_at"),
        {"schema": "catalog"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    account_key: Mapped[str] = mapped_column(String(64), nullable=False)
    # fix(#1775): nullable — pre-migration rows have no caller digest and
    # must not be charged to one; they age out via the 15-minute sweep.
    user_scope: Mapped[str | None] = mapped_column(String(64), nullable=True)
    attempted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
