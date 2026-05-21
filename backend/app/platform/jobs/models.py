import uuid
from datetime import datetime
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
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class IngestJob(Base):
    __tablename__ = "ingest_jobs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'running', 'complete', 'failed', 'cancelled', 'fanned_out')",
            name="chk_ingest_jobs_status",
        ),
        # DBM-03: partial index for stale-job recovery scans.
        # Migration 0013 is the source of truth for the actual DDL.
        Index(
            "ix_ingest_jobs_status_active",
            "status",
            postgresql_where=text("status IN ('running', 'pending')"),
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
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # REMED-02 / ingest-audit P2-07: progress fields. Workers write these at
    # natural step boundaries (see tasks_vector.ingest_file + tasks_raster.ingest_raster)
    # so the polling UI (BulkTrackingList, ReuploadDialog) can show progress
    # during 10-minute raster ingests / large VRT mosaics. All three are
    # nullable for back-compat — pre-migration rows + service-ingest paths
    # that don't write them surface as None via JobStatusResponse.
    # The Pydantic Literal at the API boundary is the contract for valid
    # current_step values; the DB column is intentionally a flexible String(32)
    # so adding a step doesn't require a migration (per project KNOWN-04).
    progress: Mapped[float | None] = mapped_column(Float, nullable=True)
    current_step: Mapped[str | None] = mapped_column(String(32), nullable=True)
    rows_processed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # IA-P0-04 (Phase 1067 option b): last_heartbeat_at column dropped.
    # Stale recovery uses started_at < JOB_TIMEOUT_SECONDS instead — see
    # platform/jobs/worker.py:recover_stale_jobs.
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("catalog.users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
