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


IngestJobWarning = Annotated[
    ReservedRenameWarning | DbfTruncationCollisionWarning,
    Field(discriminator="kind"),
]


class JobStatusResponse(BaseModel):
    id: uuid.UUID
    status: str
    dataset_id: uuid.UUID | None
    source_filename: str | None
    error_message: str | None
    warning_message: str | None = None
    # S3/TYPE-2: structured warnings surfaced from IngestJob.user_metadata so
    # the frontend can render a banner on the upload success screen / dataset
    # detail page. The legacy scalar ``warning_message`` is kept as an escape
    # hatch for the table-name collision case that predates the structured
    # shape; clients should prefer ``warnings`` and fall back to it.
    warnings: list[IngestJobWarning] = Field(default_factory=list)
    archive_failed: bool = False
    # TYPE-3: the temporal parser only ever emits these two keys; pin the
    # shape so adding a third key requires touching the contract deliberately.
    temporal_parse_errors: dict[Literal["temporal_start", "temporal_end"], str] = (
        Field(default_factory=dict)
    )
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class StaleCleanupResponse(BaseModel):
    pending_failed: int
    running_failed: int
    total_cleaned: int
