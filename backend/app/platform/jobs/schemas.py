import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Structured ingest-warning contract (TYPE-1/TYPE-2/TYPE-3)
# ---------------------------------------------------------------------------
#
# The Procrastinate ingest tasks emit warnings into
# ``IngestJob.user_metadata['warnings']``. Historically this was a free-form
# ``list[dict[str, Any]]`` on the backend and a properly-typed discriminated
# union on the frontend — which meant a typo in a ``kind`` value or a change
# in ``details`` shape on the Python side could silently ship a warning the
# frontend would drop or crash on.
#
# These Pydantic models pin the shape at the API boundary. Warnings are
# produced via TypedDicts in ``app.ingest.warnings`` (so the producers stay
# fast and cheap); the router re-parses them through ``IngestJobWarning``
# before returning a ``JobStatusResponse`` so malformed warnings are caught
# before they cross the wire. OpenAPI consumers get a proper union instead
# of ``dict``.


class ReservedRenameDetail(BaseModel):
    original: str
    renamed: str

    model_config = ConfigDict(extra="forbid")


class ReservedRenameWarning(BaseModel):
    kind: Literal["reserved_rename"]
    details: list[ReservedRenameDetail]

    model_config = ConfigDict(extra="forbid")


class DbfTruncationDetail(BaseModel):
    truncated: str
    originals: list[str]

    model_config = ConfigDict(extra="forbid")


class DbfTruncationCollisionWarning(BaseModel):
    kind: Literal["dbf_truncation_collision"]
    details: list[DbfTruncationDetail]

    model_config = ConfigDict(extra="forbid")


class MercatorClipDetail(BaseModel):
    """fix(#888): how much geometry the Web Mercator clamp destroyed.

    The clamp is a box, not a latitude cutoff: longitude -180 to 180 and
    latitude -85.06 to 85.06. Either bound can be the one that cost the user
    geometry, so clients must not present this as a latitude-only problem
    (fix(#899 codex r1)).

    ``dropped_features`` lost their geometry entirely (a valid point at lat
    -89.95 becomes ``MULTIPOINT EMPTY``); ``clipped_features`` survived in
    reduced form.
    """

    dropped_features: int = Field(ge=0)
    clipped_features: int = Field(ge=0)
    # fix(#906): True when the clip was skipped because the Mercator safe
    # envelope degenerates under ST_Transform into the source CRS (e.g.
    # EPSG:4807 collapses it to a line); counts are 0/0 then, and the flag is
    # what makes the skip user-visible instead of silent. Defaults False so
    # pre-#906 stored warnings still validate.
    clip_skipped: bool = False

    model_config = ConfigDict(extra="forbid")


class MercatorClipWarning(BaseModel):
    kind: Literal["mercator_clip"]
    details: MercatorClipDetail

    model_config = ConfigDict(extra="forbid")


IngestJobWarning = Annotated[
    ReservedRenameWarning | DbfTruncationCollisionWarning | MercatorClipWarning,
    Field(discriminator="kind"),
]


class JobStatusResponse(BaseModel):
    id: uuid.UUID
    status: Literal[
        "pending", "running", "complete", "failed", "cancelled", "fanned_out"
    ]
    dataset_id: uuid.UUID | None
    source_filename: str | None
    error_message: str | None
    # These are computed for every response by ``_job_to_status_response``.
    # Keep them required in OpenAPI so generated clients match the runtime
    # contract and the hand-maintained frontend boundary type.
    can_retry: bool
    retry_reason: str | None
    warning_message: str | None = None
    # S3/TYPE-2: structured warnings surfaced from IngestJob.user_metadata so
    # the frontend can render a banner on the upload success screen / dataset
    # detail page. The legacy scalar ``warning_message`` is kept as an escape
    # hatch for the table-name collision case that predates the structured
    # shape; clients should prefer ``warnings`` and fall back to it.
    warnings: list[IngestJobWarning] = Field(default_factory=list)
    # REMED-02 / ingest-audit P2-07: progress fields populated by the ingest
    # worker at natural step boundaries so the UI can surface progress during
    # multi-minute ingests (raster COG convert, large VRT mosaics) instead of
    # rendering a dead spinner. All three default to None so pre-existing job
    # rows + service ingests that never write them validate cleanly. The
    # `current_step` Literal is the union of vector + raster step names — the
    # DB column intentionally stays a flexible String(32) so adding a step
    # only requires touching this Literal (single-source-of-truth boundary).
    progress: Annotated[float, Field(ge=0.0, le=1.0)] | None = None
    current_step: (
        Literal[
            # ux(#698): stamped at creation so a pending job reads as queued
            # rather than as a job with nothing to say for itself. Applies to
            # analysis today; any producer may set it.
            "queued",
            "validating",
            "ogr2ogr",
            "finalize",
            "complete",
            "cog_convert",
            "quicklook",
            # Analysis materialize (no numeric progress — the operation is a
            # single CTAS, so there is nothing to report between these two).
            "analyzing",
            "registering",
        ]
        | None
    ) = None
    rows_processed: Annotated[int, Field(ge=0)] | None = None
    # fix(#1550 review): rows the job processed but could NOT complete. The
    # embedding backfill is the first producer: it catches per-record provider
    # errors and returns counts rather than raising, so a run that regenerated
    # most of the catalog and had some records rejected finishes `complete`
    # with real coverage gaps — and after a FORCE run those gaps are records
    # whose old vectors were deleted. The synchronous endpoint returned enough
    # for the UI to warn about that; moving to the queue lost it, because
    # `rows_processed` alone cannot distinguish a clean run from a partial one.
    # Read from a generic `user_metadata["rows_failed"]` so any job type can
    # populate it without this shared schema learning a domain.
    rows_failed: Annotated[int, Field(ge=0)] | None = None
    archive_failed: bool = False
    # TYPE-3: the temporal parser only ever emits these two keys; pin the
    # shape so adding a third key requires touching the contract deliberately.
    temporal_parse_errors: dict[Literal["temporal_start", "temporal_end"], str] = Field(
        default_factory=dict
    )
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class JobCancelResponse(BaseModel):
    """Outcome of ``POST /jobs/{id}/cancel`` (#1677).

    ``run_id`` is the ``dataset_refresh_runs`` row this cancel finalized, when
    the job had one bound (refreshes and reuploads do; plain imports don't).
    ``already`` is True when the job was cancelled before this request — the
    repeat is idempotent and nothing was written.
    """

    id: uuid.UUID
    status: Literal["cancelled"]
    run_id: uuid.UUID | None
    already: bool = False


class StaleCleanupResponse(BaseModel):
    pending_failed: int
    running_failed: int
    total_cleaned: int
    vrt_assets_recovered: int
    vrt_generations_failed: int
    terminal_jobs_purged: int
    staged_paths_considered: int
    local_files_reaped: int
    storage_objects_reaped: int
    staged_paths_skipped: int
    staged_cleanup_failures: int
    total_affected: int
