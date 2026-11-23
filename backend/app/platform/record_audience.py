"""Who a change to a catalog record's visibility and status lets read it.

The publish-key and restricted-public checks judge a change by the audience
it leaves, at the request and again where a worker applies it later.
"""

from __future__ import annotations

from dataclasses import dataclass

VISIBILITY_ORDER = ("private", "restricted", "internal", "public")

PUBLIC_VISIBILITY_DENIED = (
    "Public visibility is restricted to administrators on this instance. "
    "Choose a narrower visibility or ask an admin to make this content public."
)


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


@dataclass(frozen=True)
class Publication:
    """The visibility and status an apply writes. ``visibility`` None keeps
    the record's; ``fell_back_for`` names who was refused public when the
    fallback wrote internal instead: ``"key"`` or ``"restriction"``."""

    visibility: str | None
    record_status: str
    fell_back_for: str | None = None


class PublicationRefused(Exception):
    """The apply may not write what it asks for. ``reason`` is ``"key"`` or
    ``"restriction"`` for a refused public, ``"widening"`` for a publish
    key's widening, which ``message`` then states."""

    def __init__(self, reason: str, message: str | None = None) -> None:
        super().__init__(message or reason)
        self.reason = reason
        self.message = message


def may_set_public(*, is_key: bool, is_admin: bool, restricted: bool) -> bool:
    """Whether a caller may set ``public``: never with a publish key, and
    only as an admin while public visibility is restricted."""
    return not is_key and (is_admin or not restricted)


def effective_publication(
    requested_visibility: str | None,
    record_status: str,
    public_fallback: str | None,
    *,
    may_set_public: bool,
    is_key: bool,
    now: tuple[str, str] | None,
) -> Publication:
    """What a version 2 manifest entry writes onto its record.

    ``now`` is the record's current ``(visibility, record_status)``, None for
    a create. An omitted visibility keeps the record's, or is private on a
    create. A refused ``public`` becomes internal when ``public_fallback`` is
    ``"internal"`` and is refused otherwise. A publish key never opens a
    record to anonymous readers, which is a refused public too, and never
    widens. The status is the intent's. Raises ``PublicationRefused``.
    """
    visibility, fell_back_for = requested_visibility, None
    refused_for = "key" if is_key else "restriction"
    if visibility == "public" and (is_key or not may_set_public):
        visibility, fell_back_for = _fall_back(public_fallback, refused_for)
    if now is None:
        return Publication(visibility or "private", record_status, fell_back_for)
    if is_key:
        if visibility is None and opens_to_anonymous(
            *now, visibility=None, record_status=record_status
        ):
            visibility, fell_back_for = _fall_back(public_fallback, "key")
        refusal = publish_key_widening(
            *now, visibility=visibility, record_status=record_status
        )
        if refusal is not None:
            raise PublicationRefused("widening", refusal)
    return Publication(visibility, record_status, fell_back_for)


def settled_visibility(
    stored: str | None, recomputed: str | None, now: str | None
) -> str | None:
    """What a publish writes: the narrower of the visibility its job stored
    and the one recomputed for the record as it is now.

    None in ``stored`` or ``recomputed`` means the record's current
    visibility ``now``, or private on a create (``now`` None). Returns None
    when that is the record's current visibility, which the write keeps.
    The recomputed target passed every rule against the record now, and a
    narrower one passes them too.
    """

    written = _narrower(stored, recomputed, now)
    return None if written == now else written


def accepted_visibility(
    stored: str | None, recomputed: str | None, now: str | None
) -> str | None:
    """What an accepted run stores for its publish to settle against: the
    narrower of the visibility the apply stored and the one recomputed for
    the accepter, resolved as ``settled_visibility`` does.

    Explicit even when it is the record's current visibility, so a record
    widened before the publish can't lift it. None only when both are None,
    which keeps whatever the record is by then.
    """
    if stored is None and recomputed is None:
        return None
    return _narrower(stored, recomputed, now)


def _narrower(stored: str | None, recomputed: str | None, now: str | None) -> str:
    def resolved(visibility: str | None) -> str:
        return visibility or now or "private"

    return min(resolved(stored), resolved(recomputed), key=VISIBILITY_ORDER.index)


def _fall_back(public_fallback: str | None, refused_for: str) -> tuple[str, str]:
    if public_fallback == "internal":
        return "internal", refused_for
    raise PublicationRefused(refused_for)
