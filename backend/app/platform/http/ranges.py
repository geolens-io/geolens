"""One implementation of RFC 9110 byte-range parsing, shared by every route
that serves ranges off a stored object.

fix(#1532): lives here because ``processing/`` may not import
``modules/catalog/``, and both need the identical parser.
"""

import re

from fastapi import status
from starlette.responses import Response

# bytes=FIRST-LAST | bytes=FIRST- | bytes=-SUFFIX. `[0-9]` not `\d`: Python's
# `\d` is unicode-aware and accepts non-ASCII digits. Lenient parsing ignores
# anything unmatched (a second range, unknown unit, reversed pair), as RFC 9110
# section 14.2 allows, so the client still gets a usable response.
#
# The unit is case-insensitive (a token per RFC 9110 section 14.1), so
# `Bytes=0-16383` matches; an unmatched unit would serve the whole object as a
# 200 instead of a 206.
#
# Only the unit. Digits stay `[0-9]`, and entity-tag comparisons (section
# 8.8.3.2, including the `W/` prefix) stay case-SENSITIVE.
BYTE_RANGE_RE = re.compile(r"^bytes=(?:([0-9]+)-([0-9]*)|-([0-9]+))$", re.IGNORECASE)

# Strict parsing reads the unit and each range-spec of the set separately.
_BYTES_UNIT_RE = re.compile(r"^bytes=", re.IGNORECASE)
_RANGE_SPEC_RE = re.compile(r"^(?:([0-9]+)-([0-9]*)|-([0-9]+))$")

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


def parse_byte_range(
    raw: str | None, size: int, *, strict: bool = False
) -> tuple[int, int] | str | None:
    """Resolve a Range header to an inclusive ``(start, end)`` byte pair.

    Returns ``None`` for no usable range (serve the whole representation) or
    for a multi-range request — ``multipart/byteranges`` is not implemented,
    and answering just the first range would corrupt a client expecting both.
    Returns ``RANGE_UNSATISFIABLE`` for 416, else the pair, already clamped.

    ``strict`` refuses an invalid ``bytes`` range, one malformed or holding a
    reversed pair, with ``RANGE_UNSATISFIABLE`` instead of ignoring it, which
    RFC 9110 section 14.2 allows. It still ignores a Range in another unit, as
    that section requires, and serves a valid multi-range whole.
    """
    header = (raw or "").strip()
    if not header:
        return None
    if strict:
        return _parse_strictly(header, size)
    match = BYTE_RANGE_RE.match(header)
    if match is None:
        return None
    return _resolve(*match.groups(), size)


def _parse_strictly(header: str, size: int) -> tuple[int, int] | str | None:
    """``parse_byte_range`` for a present header, refusing an invalid bytes range."""
    if not _BYTES_UNIT_RE.match(header):
        return None
    # An empty list element is ignored, as RFC 9110 section 5.6.1.2 requires.
    specs = [spec.strip() for spec in header[len("bytes=") :].split(",")]
    matches = [_RANGE_SPEC_RE.match(spec) for spec in specs if spec]
    if not matches or not all(matches):
        return RANGE_UNSATISFIABLE
    resolved = [_resolve(*match.groups(), size) for match in matches]
    if None in resolved:
        return RANGE_UNSATISFIABLE
    return resolved[0] if len(resolved) == 1 else None


def _resolve(
    first: str | None, last: str | None, suffix: str | None, size: int
) -> tuple[int, int] | str | None:
    """One well-formed range-spec against the size; None for a reversed pair."""
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
        return None
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

    ``*`` matches even when ``etag`` is None — the section asks whether the
    RESOURCE has a current representation, not whether the server can name it.
    Requiring an etag here would force a multi-gigabyte re-fetch just to confirm
    what the caller already stat'd.

    ``evaluate_preconditions`` answers a match with 304 for GET and HEAD and
    with 412 for any other method, as the section requires.
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
