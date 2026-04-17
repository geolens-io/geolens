"""Structured ingest-warning producer contract (TYPE-1).

The ingest tasks emit warnings into ``IngestJob.user_metadata['warnings']``
via ``_append_job_warning``. Before the TYPE-1 remediation that helper
accepted an untyped ``dict`` which meant a typo in a ``kind`` value or a
shape drift in ``details`` would silently ship a warning the frontend drops
(or crashes on). These TypedDicts pin the producer side of the contract so
mypy catches a malformed warning at the call site rather than at deserialize
time on the client.

The matching Pydantic models live in ``app.jobs.schemas`` — the router
validates through them before returning ``JobStatusResponse`` so the
backend-frontend contract is closed at both ends.
"""

from typing import Literal, TypedDict


class ReservedRenameDetail(TypedDict):
    original: str
    renamed: str


class ReservedRenameWarning(TypedDict):
    kind: Literal["reserved_rename"]
    details: list[ReservedRenameDetail]


class DbfTruncationDetail(TypedDict):
    truncated: str
    originals: list[str]


class DbfTruncationCollisionWarning(TypedDict):
    kind: Literal["dbf_truncation_collision"]
    details: list[DbfTruncationDetail]


IngestJobWarning = ReservedRenameWarning | DbfTruncationCollisionWarning


def make_reserved_rename_warning(
    renames: list[dict],
) -> ReservedRenameWarning:
    """Build a ``reserved_rename`` warning from ``rename_reserved_columns`` output.

    The metadata helper returns ``list[dict]`` for backwards compat with
    raw SQLAlchemy callers; this wrapper narrows the shape to the
    producer contract before the warning goes into ``user_metadata``.
    """
    return ReservedRenameWarning(
        kind="reserved_rename",
        details=[
            ReservedRenameDetail(
                original=str(r.get("original", "")),
                renamed=str(r.get("renamed", "")),
            )
            for r in renames
        ],
    )


def make_dbf_truncation_warning(
    collisions: list[dict],
) -> DbfTruncationCollisionWarning:
    """Build a ``dbf_truncation_collision`` warning from the detector output."""
    return DbfTruncationCollisionWarning(
        kind="dbf_truncation_collision",
        details=[
            DbfTruncationDetail(
                truncated=str(c.get("truncated", "")),
                originals=[str(o) for o in c.get("originals", [])],
            )
            for c in collisions
        ],
    )
