"""Structured ingest-warning producer contract for ``IngestJob.user_metadata['warnings']``.

These TypedDicts pin the producer side so mypy catches a malformed ``kind``
or ``details`` shape at the call site rather than at client deserialize
time. Matching Pydantic models live in ``app.jobs.schemas``, validated by
the router before ``JobStatusResponse`` goes out.
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
    # degenerates under ST_Transform into the source CRS (e.g. EPSG:4807
    # collapses to a line). Counts are 0/0 then; warn so it isn't silent.
    clip_skipped: NotRequired[bool]


class MercatorClipWarning(TypedDict):
    kind: Literal["mercator_clip"]
    details: MercatorClipDetail


class MercatorClipCounts(TypedDict):
    """Return shape of ``clip_to_mercator_bounds``.

    ``shifted_longitudes``: source was 0..360, translated to -180..180
    before the clip ran. ``clip_skipped`` (fix(#906)): clip didn't run
    because the safe envelope degenerated in the source CRS; the
    longitude shift was still applied.
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

    Narrows the helper's untyped ``list[dict]`` to the producer contract.
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

    fix(#888): the Web Mercator clamp can silently empty geometry (e.g. a
    point at lat -89.95 becomes ``MULTIPOINT EMPTY``); this makes that
    user-visible instead. Any shape other than the documented counts dict
    (stale producer, monkeypatched stand-in) yields None rather than a
    malformed warning — same fail-closed stance the router takes on re-parse.
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
