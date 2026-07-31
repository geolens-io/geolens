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

from typing import Literal, NotRequired, TypedDict


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


class MercatorClipDetail(TypedDict):
    dropped_features: int
    clipped_features: int
    # fix(#906): True when the clip was skipped because the safe envelope
    # degenerates under ST_Transform into the source CRS (narrow-validity
    # CRSs — EPSG:4807 collapses it to a line and the intersection would
    # have emptied the table). Counts are 0/0 in that case; the warning
    # exists so the skip is not silent.
    clip_skipped: NotRequired[bool]


class MercatorClipWarning(TypedDict):
    kind: Literal["mercator_clip"]
    details: MercatorClipDetail


class MercatorClipCounts(TypedDict):
    """Return shape of ``clip_to_mercator_bounds`` (fix(#888)).

    ``shifted_longitudes`` records whether the source was recognised as
    0..360 and translated into -180..180 before the clip ran; the two counts
    describe what the clip itself destroyed. ``clip_skipped`` (fix(#906))
    records that the clip did not run because the safe envelope degenerated
    in the source CRS; the 0..360 shift has still been applied.
    """

    shifted_longitudes: bool
    dropped_features: int
    clipped_features: int
    clip_skipped: NotRequired[bool]


IngestJobWarning = (
    ReservedRenameWarning | DbfTruncationCollisionWarning | MercatorClipWarning
)


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


def make_mercator_clip_warning(
    clip: MercatorClipCounts | None,
) -> MercatorClipWarning | None:
    """Build a ``mercator_clip`` warning, or None when no geometry was lost.

    fix(#888): the Web Mercator clamp is intentional, but it used to run
    silently — a valid point at lat -89.95 became ``MULTIPOINT EMPTY`` and the
    user only found out when a later analysis reported "produced no features
    to save". This producer turns the clip accounting into the user-visible
    warning, and returns None for the overwhelmingly common no-loss clip so
    the "warn only when the user actually lost data" decision lives here
    rather than being re-derived at each ingest call site.

    Shapes that are not the documented counts dict (a stale producer, a
    monkeypatched stand-in) yield None rather than a malformed warning: same
    fail-closed stance the router takes when it re-parses these.
    """
    if not isinstance(clip, dict):
        return None
    dropped = clip.get("dropped_features")
    clipped = clip.get("clipped_features")
    if not isinstance(dropped, int) or not isinstance(clipped, int):
        return None
    # fix(#906): a skipped clip lost no data but must not be silent either —
    # the dataset now carries geometry the Mercator clamp never inspected.
    skipped = clip.get("clip_skipped") is True
    if dropped <= 0 and clipped <= 0 and not skipped:
        return None
    details = MercatorClipDetail(
        dropped_features=max(dropped, 0),
        clipped_features=max(clipped, 0),
    )
    if skipped:
        details["clip_skipped"] = True
    return MercatorClipWarning(kind="mercator_clip", details=details)
