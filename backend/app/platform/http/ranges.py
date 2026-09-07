"""One implementation of RFC 9110 byte-range parsing, shared by every route
that serves ranges off a stored object.

fix(#1532): lives here because ``processing/`` may not import
``modules/catalog/``, and both need the identical parser.
"""

import re

from fastapi import status
from starlette.responses import Response

# bytes=FIRST-LAST | bytes=FIRST- | bytes=-SUFFIX. `[0-9]` not `\d`: Python's
# `\d` is unicode-aware and accepts non-ASCII digits. Anything unmatched (a
# second range, unknown unit, reversed pair) is IGNORED per RFC 9110 section
# 14.2 — the safe direction, since the client still gets a usable response.
#
# fix(#1540): the unit is case-INSENSITIVE (a token per RFC 9110
# section 14.1), so `Bytes=0-16383` must match — treating it as unmatched
# served the whole object as a 200 instead of a 206.
#
# Only the unit. Digits stay `[0-9]`, and entity-tag comparisons (section
# 8.8.3.2, including the `W/` prefix) stay case-SENSITIVE.
BYTE_RANGE_RE = re.compile(r"^bytes=(?:([0-9]+)-([0-9]*)|-([0-9]+))$", re.IGNORECASE)

# No byte of the representation was named (first-byte-pos past the end, or a
# zero-length suffix). RFC 9110 section 15.5.17 wants 416 with the real size,
# NOT a 200 with the whole object — a client resuming one tile would splice it.
RANGE_UNSATISFIABLE = "unsatisfiable"

# fix(#1540): saturated at this many digits before reaching int().
# CPython refuses to convert a literal longer than
# sys.get_int_max_str_digits() (4300 default) — an unbounded `int(group)` on a
# 4301-digit value (fits an 8 KiB header) would be a 500. Saturating instead of
# rejecting keeps the RFC answer (416, or a clamp) rather than a 200 with the
# whole object, which would splice a resumed download at the wrong offset.
#
# 19 digits: 2**63-1 has 19, and no stored object is that large.
_MAX_RANGE_DIGITS = 19


def _range_int(digits: str, size: int) -> int:
    """``int(digits)``, saturated above any size a stored object can have.

    Leading zeros are stripped before the length test, so a padded
    ``bytes=-0000...0`` reads as a zero-length suffix (416), not an
    astronomically large one.
    """
    trimmed = digits.lstrip("0") or "0"
    if len(trimmed) > _MAX_RANGE_DIGITS:
        return size + 1
    return int(trimmed)


def parse_byte_range(raw: str | None, size: int) -> tuple[int, int] | str | None:
    """Resolve a Range header to an inclusive ``(start, end)`` byte pair.

    Returns ``None`` for no usable range (serve the whole representation) or
    for a multi-range request — ``multipart/byteranges`` is not implemented,
    and answering just the first range would corrupt a client expecting both.
    Returns ``RANGE_UNSATISFIABLE`` for 416, else the pair, already clamped.
    """
    if not raw:
        return None
    match = BYTE_RANGE_RE.match(raw.strip())
    if match is None:
        return None
    first, last, suffix = match.groups()

    if suffix is not None:
        # bytes=-N: the final N bytes. A zero-length suffix names nothing.
        wanted = _range_int(suffix, size)
        if wanted == 0 or size == 0:
            return RANGE_UNSATISFIABLE
        return (max(0, size - wanted), size - 1)

    start = _range_int(first, size)
    if size == 0 or start >= size:
        return RANGE_UNSATISFIABLE
    if last == "":
        # bytes=N-: from N to the end.
        return (start, size - 1)
    end = _range_int(last, size)
    if end < start:
        return None  # reversed pair: invalid, so ignore rather than reject
    # A last-byte-pos past the end is CLAMPED, not rejected — clients that do
    # not know the size ask for more than exists on purpose.
    return (start, min(end, size - 1))


def range_bound_to_this_version(if_range: str | None, etag: str | None) -> bool:
    """May this Range be served, given the client's ``If-Range`` precondition?

    RFC 9110 section 13.1.5: STRONG comparison. On mismatch the server MUST
    ignore the Range and answer 200 with the whole representation (not 416 or
    a 206 of new bytes) — this stops two versions of an object being spliced
    into one file.

    Returns False when the validators differ, when the client sent
    ``W/"..."`` (never matches strong comparison), or when there is no
    validator to compare against. An absent ``If-Range`` returns True.

    fix(#1532): shared with the export route under ``processing/``,
    which needs the identical evaluation — reimplementing it there is how the
    two would drift.
    """
    if if_range is None:
        return True
    return etag is not None and if_range.strip() == etag


def if_match_passes(if_match: str | None, etag: str | None) -> bool:
    """May this request proceed, given the client's ``If-Match``? Section 13.1.1.

    STRONG comparison, like ``If-Range`` and unlike ``If-None-Match``: a weak
    validator cannot promise byte-for-byte identity.

    ``*`` passes for any current representation, including a row with no
    ``sha256``. A specific tag against such a row is False — unverifiable is
    not a pass, the same call ``range_bound_to_this_version`` makes.
    """
    if not if_match:
        return True
    candidates = [tag.strip() for tag in if_match.split(",")]
    if "*" in candidates:
        return True
    return etag is not None and etag in candidates


def if_none_match_matches(if_none_match: str | None, etag: str | None) -> bool:
    """Does the client already hold this representation? RFC 9110 section 13.1.2.

    WEAK comparison, unlike ``If-Range``: a cache revalidation only needs
    equivalence, not byte-identity.

    fix(#1554): ``*`` matches even when ``etag`` is None — the section asks
    whether the RESOURCE has a current representation, not whether the server
    can name it. Requiring an etag here would force a multi-gigabyte re-fetch
    just to confirm what the caller already stat'd.

    A match is answered 304 unconditionally: this route serves GET/HEAD only
    (``test_the_cog_download_answers_only_safe_methods`` pins it). The
    section's ``*`` to 412 case applies to unsafe methods this route has no
    caller for.
    """
    if not if_none_match:
        return False
    candidates = [tag.strip() for tag in if_none_match.split(",")]
    if "*" in candidates:
        return True
    if etag is None:
        return False
    return any(_without_weak_prefix(tag) == etag for tag in candidates)


def _without_weak_prefix(tag: str) -> str:
    return tag[2:] if tag.startswith("W/") else tag


def not_modified_response(etag: str | None) -> Response:
    """304: the client's copy is current, so send it nothing else.

    ``ETag`` and ``Accept-Ranges`` go back per RFC 9110 section 15.4.5, so a
    client revalidating before a resume does not have to re-probe. No body or
    ``Content-Length``: starlette's ``init_headers`` already omits both for 304.

    fix(#1554): ``etag`` may be None, matching what the 200 for a row with no
    stored digest would send. Minting one here would wrongly authorize a resume
    ``range_bound_to_this_version`` refuses on exactly those rows.
    """
    headers = {"Accept-Ranges": "bytes"}
    if etag is not None:
        headers["ETag"] = etag
    return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers=headers)
