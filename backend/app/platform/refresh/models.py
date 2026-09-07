"""``catalog.dataset_refresh_runs`` — one row per refresh attempt.

A sibling table rather than extra columns on ``DatasetVersion``: that table
is a SUCCESS ledger with ``UNIQUE (dataset_id, version_number)``, and a
failed refresh has no Nth good state, so a nullable counter would destroy
the uniqueness constraint's meaning.

No ``tenant_id``/RLS, matching ``dataset_versions``: a run is reachable only
through ``dataset_id``, which carries the tenant boundary (see the
tenant-scoped table list in ``tests/test_rls_drift_gate.py``).
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
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
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class DatasetRefreshRun(Base):
    __tablename__ = "dataset_refresh_runs"
    __table_args__ = (
        # `blocked` is deliberately absent: v1 has no schema policy so the
        # state is unreachable. Reserved spelling for whoever adds one;
        # widening the VARCHAR CHECK is a two-line migration.
        CheckConstraint(
            "status IN ('pending', 'running', 'succeeded', 'failed', 'cancelled')",
            name="chk_refresh_runs_status",
        ),
        # `scheduled` excluded on purpose (no scheduler in Community). The
        # migration that adds it must, in the SAME migration, add
        # `scheduled_for` and its UNIQUE (dataset_id, scheduled_for) partial
        # index, or a scheduled occurrence loses its durable identity.
        CheckConstraint(
            "trigger IN ('manual', 'api', 'cli')",
            name="chk_refresh_runs_trigger",
        ),
        # fix(#1325): origin_kind is the run's execution DOOR, written once
        # by create_pending_run at commit time and never updated afterward.
        # It is NOT the dataset's current origin — ORIGIN_KINDS/classify_origin()
        # in platform/dataset_origin.py recompute that live from the
        # dataset's current source_format, so a pending/failed run can
        # visibly disagree with the dataset it belongs to (e.g. a STAC
        # raster's replace run stamps 'upload' immediately, while the
        # dataset stays 'stac' until a successful swap rebinds it). 'raster'
        # is RESERVED for the raster-replace door (#1290) and unused today;
        # reupload_commit always stamps raster replaces 'upload'.
        CheckConstraint(
            "origin_kind IN ('upload', 'postgis', 'service', 'stac', 'raster')",
            name="chk_refresh_runs_origin_kind",
        ),
        # Admission control in the schema: at most one mutation per dataset
        # at a time, v1 REJECTS rather than queues. The partial unique index
        # makes that atomic at request time — the loser of a race gets an
        # IntegrityError turned into 409 dataset_busy; a check-then-insert
        # would leave a window between the SELECT and the INSERT.
        Index(
            "uq_refresh_runs_one_active",
            "dataset_id",
            unique=True,
            postgresql_where=text("status IN ('pending', 'running')"),
        ),
        # The history query: newest-first for one dataset.
        Index("ix_dataset_refresh_runs_dataset_started", "dataset_id", "started_at"),
        # The three remaining FKs need their own leading index or a parent
        # delete degrades to a full child scan
        # (`test_every_catalog_fk_has_a_valid_leading_index`). Partial on
        # IS NOT NULL: a NULL references nothing, so indexing it buys nothing.
        Index(
            "ix_dataset_refresh_runs_version",
            "dataset_version_id",
            postgresql_where=text("dataset_version_id IS NOT NULL"),
        ),
        Index(
            "ix_dataset_refresh_runs_job",
            "ingest_job_id",
            postgresql_where=text("ingest_job_id IS NOT NULL"),
        ),
        Index(
            "ix_dataset_refresh_runs_triggered_by",
            "triggered_by",
            postgresql_where=text("triggered_by IS NOT NULL"),
        ),
        {"schema": "catalog"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=func.gen_random_uuid()
    )
    dataset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("catalog.datasets.id", ondelete="CASCADE"), nullable=False
    )
    # TSEAM-01 dormant tenant_id. Not in migration 0018's stamping-trigger
    # set, so `create_pending_run` writes it explicitly from the parent
    # dataset's STORED value, not the ORM attribute — the trigger fills the
    # DB column but leaves the ORM attribute None (#1218 finding).
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    # The version this run produced, when it produced one. A failed run links
    # to nothing, which is the whole reason this is not a DatasetVersion.
    dataset_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("catalog.dataset_versions.id", ondelete="SET NULL"), nullable=True
    )
    # SET NULL, not CASCADE: history must survive the ingest_jobs retention
    # purge, so the run row outlives the job and the link nulls out.
    ingest_job_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("catalog.ingest_jobs.id", ondelete="SET NULL"), nullable=True
    )
    origin_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    trigger: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    triggered_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("catalog.users.id", ondelete="SET NULL"), nullable=True
    )
    # Dispatch time, NOT claim time. The worker leaves it alone when it moves
    # the row to `running`.
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    # When the worker began executing. Queue wait is claimed_at - started_at,
    # which is only measurable because these are three separate columns; fold
    # any two together and the number is gone.
    claimed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    feature_count_before: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    feature_count_after: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # compute_schema_diff() output (#1223), recomputed at swap time against the
    # staging table rather than copied from the preview.
    schema_diff: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
