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
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


# Statuses whose row still NEEDS the staged input its `file_path` points at:
# pending and running are reading it now, and failed keeps it for
# /jobs/{id}/retry (a failed-only endpoint). Every other status is done with
# the bytes — a `complete` fan-out child keeps its metadata row but not a claim
# on the shared original, which is why a successful fan-out's input is reapable
# at all rather than pinned forever by children that are each a dataset's
# latest complete job.
#
# fix(#1249 review r4): lives here rather than inline at either consumer,
# because two of them now ask the same question and a drift between them is a
# leak in one direction and a deletion of live input in the other. The
# retention purge's survivor query (`_reap_committed_staged_paths`'s feeder in
# sweep.py) and the staging-orphan reconciliation both read it.
STATUSES_NEEDING_STAGED_INPUT = ("pending", "running", "failed")

# `user_metadata` key stamped by the stale sweep on a fan-out parent whose
# dispatch crashed between the pre-dispatch flip and the first child commit
# (fix(#1709 review r8)). Two readers: the sweep writes it when it settles the
# childless `fanned_out` parent as `failed`, and the retry capability in
# jobs/router.py refuses generic retry on it — the layer selection lived only
# in the fan-out request body, so a generic retry would silently import ONE
# default layer of a multi-layer file. Cross-reader markers live here beside
# the others so the two sites cannot drift (#1249 r6 precedent).
FAN_OUT_INTERRUPTED_METADATA_KEY = "fan_out_interrupted"

# `user_metadata` key that marks an ``IngestJob`` row as an admin embedding
# backfill run (fix(#1542)). The run itself imports nothing — the row exists so
# the operator can see a run in flight and so a second one can be refused
# before it deletes anything. Three modules key off it (the admin dispatch, its
# concurrency guard, and the retry contract in jobs/router.py), so it lives
# here beside the other cross-reader marker rather than as a literal in each.
EMBEDDING_BACKFILL_METADATA_KEY = "embedding_backfill"

# Name of the partial unique index that enforces "at most one embedding
# backfill in flight per tenant" (migration 0050). The admin route matches on
# it to tell its own concurrency refusal apart from any other constraint
# violation — reporting an unrelated one as "a backfill is already running"
# would be its own fabricated answer.
ACTIVE_BACKFILL_INDEX_NAME = "uq_ingest_jobs_active_embedding_backfill"

# `user_metadata` key the post-expiry presigned sweep sets once it has finished
# with a row's `s3_key` for good — see `_sweep_expired_presigned_staging` in
# sweep.py, which owns the whole story of when it may be written.
#
# fix(#1249 review r6): it lives here because a SECOND reader now depends on
# it. Its presence is the fact that says "the row-driven reaper will never look
# at this key again", which is exactly when the staging-orphan reconciliation
# may take the key over — and a copy of the string in each module is one
# rename away from a row that shields an object forever.
STAGING_REAPED_FINAL_MARKER = "s3_key_reaped_final"


def owned_presigned_staging_key(
    job_id: uuid.UUID | str,
    user_metadata: dict[str, Any] | None,
    file_path: str | None,
) -> str | None:
    """Return the presigned staging key this job alone is responsible for.

    fix(#1202 review r5): a completed presigned upload points ``file_path`` at
    a frozen copy, which leaves ``user_metadata["s3_key"]`` as the only
    reference to the client-writable staging key. That URL stays valid until
    expiry, so the client can recreate the object after completion. Reapers
    use this to sweep it alongside ``file_path``.

    Ownership is decided by the key's OWN prefix, not by "differs from
    file_path". ``create_fan_out_jobs`` clones the parent's ``user_metadata``
    wholesale, so every fan-out child carries the PARENT's ``s3_key``:
    sweeping on difference alone would delete the shared original out from
    under siblings that still need it — the same breakage the
    ``is_fan_out_child`` default-true guard exists to prevent. A staging key
    is namespaced by the job that presigned it, so the prefix settles
    ownership outright and needs no survivor query.
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
        # fix(#1542 review P1): "at most one embedding backfill in flight per
        # tenant", enforced by the database rather than by a SELECT the route
        # runs before its INSERT. Two concurrent force runs mean two DELETEs of
        # every embedding, and a check-then-insert cannot stop two transactions
        # in two processes from both passing. NULLS NOT DISTINCT is load-bearing
        # in single-tenant mode, where every tenant_id is NULL and the default
        # NULLS DISTINCT would treat each row's key as unique — permitting
        # exactly the pair this refuses. Migration 0050 is the source of truth
        # for the DDL.
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
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("catalog.users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
