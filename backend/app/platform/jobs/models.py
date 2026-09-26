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
    or_,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.tiles3d import UNPUBLISHED_TILESET_ATTEMPTS_FIELD

# Every value chk_ingest_jobs_status allows, in its order, and the two a live job
# holds. Tuples, so an IN list built from them renders the same every time.
ALL_STATUSES = ("pending", "running", "complete", "failed", "cancelled", "fanned_out")
ACTIVE_STATUSES = ("pending", "running")
TERMINAL_STATUSES = tuple(s for s in ALL_STATUSES if s not in ACTIVE_STATUSES)

# Statuses whose row still needs the staged `file_path`: pending/running read
# it now, failed keeps it for /jobs/{id}/retry. fix(#1249): lives here, not
# inline, since both the retention purge and staging-orphan reconciliation read it.
STATUSES_NEEDING_STAGED_INPUT = ("pending", "running", "failed")

# fix(#1709): stamped by the stale sweep on a fan-out parent whose dispatch
# crashed before any child committed. jobs/router.py refuses generic retry on
# it, since that would silently import only one layer of a multi-layer file.
FAN_OUT_INTERRUPTED_METADATA_KEY = "fan_out_interrupted"

# fix(#1710): stamped by the URL-import door and CLEARED by the staged
# transition. While present, `file_path` names a download destination rather
# than a complete file, so `_retry_capability` refuses the ordinary ingest
# retry: a crash-truncated CSV is still valid to a streaming reader.
URL_DOWNLOAD_IN_FLIGHT_METADATA_KEY = "url_download_in_flight"

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

# Set by that sweep's first pass; the re-check pass adds the final marker.
STAGING_REAPED_MARKER = "s3_key_reaped"

# The pre-queue stage a manifest job is in. The manifest reservation's exits
# clear it; a settled row that keeps it is inert, since the in-flight read
# filters on status.
MANIFEST_STAGE_METADATA_KEY = "manifest_stage"

# The manifest entry's content fingerprint, which the apply compares to skip an
# entry it has already imported or is importing.
MANIFEST_FINGERPRINT_METADATA_KEY = "manifest_fingerprint"

# The unpacked total the tileset upload door measured, which the commit door
# checks against the quota again.
TILESET_UNPACKED_BYTES_FIELD = "tileset_unpacked_bytes"

# Artifact records. A worker names each object, table or owed follow-up here no
# later than it creates it, so a killed attempt still leaves an owner, and the
# retention purge keeps a row while any of them is set.
UNPUBLISHED_STORAGE_KEYS_FIELD = "unpublished_storage_keys"
ANALYSIS_OUTPUT_TABLE_FIELD = "analysis_out_table"
# The follow-ups a landed terminal commit still owes: the task (a complete job's
# first ingest, or a failed job's replacement) and the attempt that wrote it,
# since a retry keeps the row and its metadata.
PUBLISH_FOLLOWUPS_FIELD = "publish_followups"
UNREAPED_ARTIFACT_FIELDS = (
    UNPUBLISHED_STORAGE_KEYS_FIELD,
    ANALYSIS_OUTPUT_TABLE_FIELD,
    UNPUBLISHED_TILESET_ATTEMPTS_FIELD,
    PUBLISH_FOLLOWUPS_FIELD,
)

# The user_metadata keys the admin job list shows: what the user supplied at
# upload, commit or in a manifest, the job's request and its outcome. Any other
# key, including one added later, is door or worker state and is left out.
PUBLIC_METADATA_KEYS = frozenset(
    {
        # Commit and upload fields.
        "title",
        "summary",
        "tags",
        "visibility",
        "temporal_start",
        "temporal_end",
        "file_type",
        "vrt_type",
        "layer_name",
        "srid_override",
        "geom_column",
        "x_column",
        "y_column",
        "compression",
        "nodata_override",
        "resampling",
        "strict_cog",
        # The request that created the job.
        "analysis",
        "dataset_id",
        "reupload",
        "refresh",
        "origin_kind",
        "verification_policy",
        "service_type",
        "layer_id",
        "object_id_field",
        "geometry_type",
        "source_type",
        "fan_out_parent_id",
        "all_layers",
        EMBEDDING_BACKFILL_METADATA_KEY,
        # What a manifest's author wrote.
        "record_status",
        "manifest_key",
        "manifest_source_type",
        "manifest_source_uri",
        "manifest_publication_intent",
        "manifest_tags",
        "manifest_organization",
        "manifest_license",
        "manifest_attribution",
        "manifest_bbox",
        # The outcome.
        "warnings",
        "rows_failed",
        "temporal_parse_errors",
        "collision_warning",
        "archive_failed",
    }
)


def public_job_metadata(metadata: dict[str, Any] | None) -> dict[str, Any] | None:
    """The job's public metadata keys, or None when it has none."""
    kept = {
        key: value
        for key, value in (metadata or {}).items()
        if key in PUBLIC_METADATA_KEYS
    }
    return kept or None


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
            "status IN ({})".format(", ".join(f"'{s}'" for s in ALL_STATUSES)),
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
    # The code of a fixed reason in ``error_message``; NULL for free text.
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
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


def holds_unarchived_original():
    """Predicate: the row records that its original never reached ``originals/``.

    Its staged upload may then be the only copy of that original.
    """
    return IngestJob.user_metadata["archive_failed"].astext.is_not(None)


def needs_staged_input():
    """Predicate: the row still needs the staged file its ``file_path`` names.

    Pending and running rows read it, a failed row may retry from it, and a row
    holding an unarchived original keeps that original's only copy in it.
    """
    return or_(
        IngestJob.status.in_(STATUSES_NEEDING_STAGED_INPUT),
        holds_unarchived_original(),
    )
