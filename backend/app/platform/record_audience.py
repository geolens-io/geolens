"""Who a change to a catalog record's visibility and status lets read it.

The publish-key and restricted-public checks judge a change by the audience
it leaves, at the request and again where a worker applies it later.
"""

from __future__ import annotations

VISIBILITY_ORDER = ("private", "restricted", "internal", "public")


def opens_to_anonymous(
    now_visibility: str,
    now_status: str,
    *,
    visibility: str | None,
    record_status: str | None,
) -> bool:
    """Whether setting ``visibility`` and ``record_status`` (None keeps the
    current value) makes a record anonymously readable that was not."""
    after = (visibility or now_visibility, record_status or now_status)
    return after == ("public", "published") and (now_visibility, now_status) != after


def publish_key_widening(
    now_visibility: str,
    now_status: str,
    *,
    visibility: str | None,
    record_status: str | None,
) -> str | None:
    """The refusal a publish key gets for this change, or None when it may make it.

    A publish key may keep a record's visibility or narrow it. It may publish
    an internal or restricted draft, but not a public one, since publishing is
    what opens a public record to anonymous readers.
    """
    if visibility is not None and VISIBILITY_ORDER.index(
        visibility
    ) > VISIBILITY_ORDER.index(now_visibility):
        return "A publish key can't widen a dataset's visibility"
    if opens_to_anonymous(
        now_visibility, now_status, visibility=visibility, record_status=record_status
    ):
        return "A publish key can't publish a public dataset"
    return None
