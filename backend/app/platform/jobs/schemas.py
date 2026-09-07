import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

# Structured ingest-warning contract (TYPE-1/TYPE-2/TYPE-3): warnings land in
# ``IngestJob.user_metadata['warnings']``. Producers use TypedDicts in
# ``app.ingest.warnings``; the router re-parses through ``IngestJobWarning``
# so malformed warnings are caught before they cross the wire.


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
    (fix(#899)).

    ``dropped_features`` lost their geometry entirely (a valid point at lat
    -89.95 becomes ``MULTIPOINT EMPTY``); ``clipped_features`` survived in
    reduced form.
    """

    dropped_features: int = Field(ge=0)
    clipped_features: int = Field(ge=0)
    # fix(#906): True when the clip was skipped because the Mercator safe
    # envelope degenerates under ST_Transform (e.g. EPSG:4807 collapses it to
    # a line); counts are 0/0 then. Defaults False so pre-#906 warnings validate.
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
    # Computed by ``_job_to_status_response``; required in OpenAPI so
    # generated clients match the hand-maintained frontend boundary type.
    can_retry: bool
    retry_reason: str | None
    warning_message: str | None = None
    # S3/TYPE-2: structured warnings from IngestJob.user_metadata. Legacy
    # scalar ``warning_message`` stays as a fallback for the pre-structured
    # table-name collision case; clients should prefer ``warnings``.
    warnings: list[IngestJobWarning] = Field(default_factory=list)
    # REMED-02 / ingest-audit P2-07: progress fields from the ingest worker,
    # for multi-minute ingests. Default None so pre-existing/service rows
    # validate. DB column stays String(32); this Literal is the source of truth.
    progress: Annotated[float, Field(ge=0.0, le=1.0)] | None = None
    current_step: (
        Literal[
            # ux(#698): stamped at creation so a pending job reads as queued,
            # not as having nothing to say. Analysis today; any producer may set it.
            "queued",
            "validating",
            "ogr2ogr",
            "finalize",
            "complete",
            "cog_convert",
            "quicklook",
            # Analysis materialize: single CTAS, no progress to report between these.
            "analyzing",
            "registering",
        ]
        | None
    ) = None
    rows_processed: Annotated[int, Field(ge=0)] | None = None
    # fix(#1550): rows processed but NOT completed. `rows_processed`
    # alone can't distinguish a clean run from a partial one (e.g. embedding
    # backfill after a FORCE run). Read from generic `user_metadata["rows_failed"]`.
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
