import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


# Statuses whose row still needs the staged `file_path`: pending/running read
# it now, failed keeps it for /jobs/{id}/retry. fix(#1249): lives here, not
# inline, since both the retention purge and staging-orphan reconciliation read it.
STATUSES_NEEDING_STAGED_INPUT = ("pending", "running", "failed")

# fix(#1709): stamped by the stale sweep on a fan-out parent whose dispatch
# crashed before any child committed. jobs/router.py refuses generic retry on
# it, since that would silently import only one layer of a multi-layer file.
FAN_OUT_INTERRUPTED_METADATA_KEY = "fan_out_interrupted"

# fix(#1744): stamped by ``defer_with_orphan_guard`` at dispatch time. ABSENCE
# is load-bearing — a stamp-less pending row was never queued, so the stale
# sweep settles it `cancelled` not `failed`. Read by sweep, status poll, worker startup.
COMMIT_ATTEMPTED_METADATA_KEY = "commit_attempted_at"


def commit_attempted_marker() -> dict[str, str]:
    """The ``user_metadata`` fragment that records a dispatch attempt.

    One producer for two writers (the guard and ``create_fan_out_jobs``), so
    they can't disagree on the timestamp format the predicate reads.
    """
    return {COMMIT_ATTEMPTED_METADATA_KEY: datetime.now(timezone.utc).isoformat()}


# fix(#1542): marks an admin embedding backfill run; the row exists so the
# operator sees it in flight and a second run is refused before it deletes
# anything. Read by the admin dispatch, its concurrency guard, and jobs/router.py.
EMBEDDING_BACKFILL_METADATA_KEY = "embedding_backfill"

# Partial unique index name enforcing "at most one embedding backfill per
# tenant" (migration 0050). The admin route matches on it to tell its own
# concurrency refusal apart from an unrelated constraint violation.
ACTIVE_BACKFILL_INDEX_NAME = "uq_ingest_jobs_active_embedding_backfill"

# Set by the post-expiry presigned sweep (`_sweep_expired_presigned_staging`
# in sweep.py) once done with a row's `s3_key`. fix(#1249): presence signals
# staging-orphan reconciliation may take the key over; one string, two readers.
STAGING_REAPED_FINAL_MARKER = "s3_key_reaped_final"


def owned_presigned_staging_key(
    job_id: uuid.UUID | str,
    user_metadata: dict[str, Any] | None,
    file_path: str | None,
) -> str | None:
    """Return the presigned staging key this job alone is responsible for.

    fix(#1202): ``user_metadata["s3_key"]`` is the only remaining
    reference to the client-writable staging key once ``file_path`` points at
    a frozen copy; reapers sweep it alongside ``file_path``.

    Ownership is the key's OWN prefix, not "differs from file_path" — a
    fan-out child clones the parent's ``s3_key``, so diffing would delete the
    shared original out from under siblings that still need it.
    """
    key = (user_metadata or {}).get("s3_key")
    if not isinstance(key, str) or not key or key == file_path:
        return None
    return key if key.startswith(f"staging/{job_id}/") else None


class IngestJob(Base):
    __tablename__ = "ingest_jobs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'running', 'complete', 'failed', 'cancelled', 'fanned_out')",
            name="chk_ingest_jobs_status",
        ),
        # DBM-03: partial index for stale-job recovery scans.
        # Migration 0001_baseline is the source of truth for the actual DDL.
        Index(
            "ix_ingest_jobs_status_active",
            "status",
            postgresql_where=text("status IN ('running', 'pending')"),
        ),
        Index("ix_catalog_ingest_jobs_tenant_id", "tenant_id"),
        # fix(#1542): DB-enforced (not check-then-insert, which can't stop
        # two concurrent force runs). NULLS NOT DISTINCT is load-bearing in
        # single-tenant mode, where every tenant_id is NULL. Migration 0050 = DDL.
        Index(
            ACTIVE_BACKFILL_INDEX_NAME,
            "tenant_id",
            unique=True,
            postgresql_nulls_not_distinct=True,
            postgresql_where=text(
                "user_metadata ? 'embedding_backfill' "
                "AND status IN ('pending', 'running')"
            ),
        ),
        {"schema": "catalog"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=func.gen_random_uuid()
    )
    dataset_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("catalog.datasets.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # Durable tenant ownership remains after nullable creator/dataset FKs are
    # cleared. The database derives/stamps and validates this key.
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", server_default="pending"
    )
    source_filename: Mapped[str | None] = mapped_column(String(500), nullable=True)
    file_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    source_url: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    source_layer: Mapped[str | None] = mapped_column(String(500), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    user_metadata: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    heartbeat_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Identifies the single queue delivery that currently owns this job. A
    # retry rotates the token, fencing a worker whose lease expired but later
    # resumed from renewing or finalizing the newer attempt.
    attempt_id: Mapped[uuid.UUID | None] = mapped_column(
        nullable=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # REMED-02 / ingest-audit P2-07: progress fields written by workers at
    # step boundaries; nullable for back-compat (pre-migration/service-ingest
    # rows surface None). DB column stays String(32); Pydantic Literal is the contract (KNOWN-04).
    progress: Mapped[float | None] = mapped_column(Float, nullable=True)
    current_step: Mapped[str | None] = mapped_column(String(32), nullable=True)
    rows_processed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("catalog.users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
