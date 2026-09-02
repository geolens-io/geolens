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

    fix(#1758 codex r4): the cluster-global half of the sign-in lockout limit.
    Esri locks an account after five failed sign-ins in fifteen minutes and
    counts them per ACCOUNT, so the budget has to be the account's. Counting
    it from ``audit_logs`` made it per tenant instead, because that table
    carries ``tenant_isolation_audit_logs``, and two tenants could then send
    six failures at one account between them.

    NOT tenant-scoped, on purpose, and a sweep that adds ``tenant_id`` to
    every catalog table must skip this one: a per-tenant view of this ledger
    is the defect it exists to fix. That is safe because the row carries
    nothing tenant-identifying and nothing secret. ``account_key`` is the
    HMAC-SHA256 digest from ``arcgis_signin.signin_account_key`` and stands
    for an ArcGIS account without being reversible to one; there is no
    username, no password, no token, no portal URL, no user id and no tenant
    id, and rows are swept fifteen minutes after they are written.

    The per-GeoLens-user half of the limit stays on ``audit_logs`` and stays
    tenant-scoped, which is correct: that budget only ever needs to see the
    caller's own rows.
    """

    __tablename__ = "arcgis_signin_attempts"
    __table_args__ = (
        # Serves the windowed count for one account, and the sweep, which
        # scans by time alone and takes the leading column as a no-op.
        Index(
            "ix_catalog_arcgis_signin_attempts_account_time",
            "account_key",
            "attempted_at",
        ),
        Index("ix_catalog_arcgis_signin_attempts_attempted_at", "attempted_at"),
        {"schema": "catalog"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    account_key: Mapped[str] = mapped_column(String(64), nullable=False)
    attempted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
