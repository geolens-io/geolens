"""``catalog.dataset_refresh_runs`` — one row per refresh attempt.

feat(#1219) / ADR-002 Decision 4a. A sibling table rather than extra columns
on ``DatasetVersion``: that table is a SUCCESS ledger whose identity is
``UNIQUE (dataset_id, version_number)``, and ``version_number`` means "the Nth
good state of this data". A failed refresh has no Nth good state, so making
the counter nullable would not add a column — it would destroy the meaning of
the uniqueness constraint. Two tables joined by one nullable FK is cheaper
than one table with a nullable identity.

No ``tenant_id`` column and no RLS policy, matching ``dataset_versions`` and
every other per-dataset child table: a run is reachable only through
``dataset_id``, and ``catalog.datasets`` carries the tenant boundary. The
nine tenant-scoped tables are enumerated in ``tests/test_rls_drift_gate.py``.
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
        # `blocked` is deliberately absent (ADR-002 Decision 4d): v1 has no
        # schema policy, so the state is unreachable and shipping it would
        # invite dead handling code. It is the reserved spelling for whoever
        # adds an enforced policy; widening a VARCHAR CHECK is a two-line
        # migration.
        CheckConstraint(
            "status IN ('pending', 'running', 'succeeded', 'failed', 'cancelled')",
            name="chk_refresh_runs_status",
        ),
        # `scheduled` is excluded on purpose (gate 4, no scheduler in
        # Community). Handoff invariant 8 rides on that exclusion: the
        # migration that adds `scheduled` here must, in the SAME migration,
        # add `scheduled_for` and its UNIQUE (dataset_id, scheduled_for)
        # partial index, or a scheduled occurrence loses its durable identity.
        CheckConstraint(
            "trigger IN ('manual', 'api', 'cli')",
            name="chk_refresh_runs_trigger",
        ),
        # fix(#1325): origin_kind here is the run's execution DOOR, not the
        # dataset's origin — see ORIGIN_KINDS in platform/dataset_origin.py, a
        # separate vocabulary derived once from source_format and never
        # revisited per run. 'upload'/'postgis'/'service'/'stac' share both
        # spelling and meaning with their ORIGIN_KINDS counterparts because
        # every door built so far executes the same way its origin formed.
        # 'raster' does not: it is RESERVED for the raster-replace door
        # (#1290), which has no ORIGIN_KINDS counterpart (a raster dataset's
        # origin is 'upload', the file it arrived as). Reserved, not live —
        # reupload_commit (router_reupload.py) still stamps raster-replace
        # runs 'upload' today, matching the dataset's origin rather than a
        # distinct door, so no row has ever actually carried 'raster'.
        # Decision (a) on #1325 is to document this split, not close it by
        # renaming a value or migrating a column.
        CheckConstraint(
            "origin_kind IN ('upload', 'postgis', 'service', 'stac', 'raster')",
            name="chk_refresh_runs_origin_kind",
        ),
        # Admission control in the schema. ADR-002 Decision 5b: at most one
        # mutation per dataset at a time, and v1 REJECTS rather than queues.
        # A partial unique index makes that atomic at request time — the loser
        # of a race gets an IntegrityError the dispatch handler turns into 409
        # dataset_busy, instead of two runs reaching the worker and finding
        # each other at the advisory lock. A check-then-insert could not:
        # between the SELECT and the INSERT there is a window, and this is
        # exactly the window two humans clicking commit occupy.
        Index(
            "uq_refresh_runs_one_active",
            "dataset_id",
            unique=True,
            postgresql_where=text("status IN ('pending', 'running')"),
        ),
        # The history query: newest-first for one dataset.
        Index("ix_dataset_refresh_runs_dataset_started", "dataset_id", "started_at"),
        # The three remaining FKs need their own leading index or a parent
        # delete degrades to a full child scan —
        # `test_every_catalog_fk_has_a_valid_leading_index` enforces it.
        # Partial on IS NOT NULL, matching ix_dataset_versions_uploaded_by:
        # a NULL references nothing, so indexing it buys nothing.
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
    # TSEAM-01 dormant tenant_id — nullable, no FK enforcement, matching the
    # column on `datasets`. This table is NOT in migration 0018's
    # stamping-trigger set, so `create_pending_run` writes it explicitly from
    # the parent dataset's STORED value rather than from the ORM attribute:
    # in multi-tenant mode the trigger fills the parent's column in the
    # database and the ORM attribute stays None, so copying the attribute
    # would silently write NULL (the #1218 finding, one table over).
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    # The version this run produced, when it produced one. A failed run links
    # to nothing, which is the whole reason this is not a DatasetVersion.
    dataset_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("catalog.dataset_versions.id", ondelete="SET NULL"), nullable=True
    )
    # SET NULL, not CASCADE: #1219's acceptance criterion is that history
    # survives the ingest_jobs retention purge. The run row outlives the job
    # and the link simply nulls out — strictly better than an unconstrained
    # UUID, which would leave a dangling pointer.
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
