"""One implementation of RFC 9110 byte-range parsing, for every route that serves
ranges off a stored object.

fix(#1532): moved here verbatim from
``modules/catalog/datasets/api/router_export.py``, where fix(#1528) and seven
rounds of review on fix(#1540) settled the behaviour against a real GDAL
``/vsicurl/`` client. The export download needs the same parser and lives under
``processing/``, which may not import ``modules/catalog/``; copying it would have
made two parsers that agree until one of them is fixed. Every judgement below is
that PR's, kept with its reasoning so a reader here does not have to go find it.
"""

import re

from fastapi import status
from starlette.responses import Response

# One anchored pattern, deliberately strict about what it accepts:
#   bytes=FIRST-LAST | bytes=FIRST- | bytes=-SUFFIX
# `[0-9]` rather than `\d` because Python's `\d` is unicode-aware, and
# int("٣") succeeds while int("²") raises — a header parser should not have
# opinions about Arabic-Indic digits. Anything this does not match (a second
# range, an unknown unit, a reversed pair) is IGNORED per RFC 9110 section
# 14.2, which is the safe direction: the client gets the whole representation
# it can already handle, never a partial one mislabelled as something else.
#
# fix(#1540 review P2): the unit match is case-INSENSITIVE. A range unit is a
# token (RFC 9110 section 14.1), and tokens compare case-insensitively unless
# the grammar says otherwise, so `Bytes=0-16383` is a conforming request. Being
# strict about it did not reject that request — "ignore the Range" sent the
# whole object with a 200, turning a 16 KiB tile read into a multi-gigabyte
# transfer. Strictness that fails toward MORE bytes is not strictness.
#
# Only the unit. The digits stay `[0-9]`, and entity-tag comparisons stay
# case-SENSITIVE wherever they live, because an entity-tag is opaque and
# section 8.8.3.2 compares it octet by octet — and the weak prefix is `%s"W/"`,
# spelled with a case-sensitive string literal in the grammar itself.
BYTE_RANGE_RE = re.compile(r"^bytes=(?:([0-9]+)-([0-9]*)|-([0-9]+))$", re.IGNORECASE)

# The Range named no byte of the representation (first-byte-pos at or past the
# end, or a zero-length suffix). RFC 9110 section 15.5.17 wants a 416 carrying
# the real size, NOT a 200 with the whole object: a client that asked for one
# tile and silently received the entire file splices it at the wrong offset.
RANGE_UNSATISFIABLE = "unsatisfiable"

# fix(#1540 review P2): every numeric field is saturated at this many digits
# before it reaches int(). CPython refuses to convert an integer literal longer
# than sys.get_int_max_str_digits() (4300 by default) and raises ValueError, so
# an unbounded `int(group)` turns `Range: bytes=<4301 digits>-` — which fits
# comfortably inside the 8 KiB per-header budget nginx and uvicorn both allow —
# into a 500 on a header RFC 9110 lets a server ignore.
#
# Saturating rather than rejecting because the RFC answer to each of these is
# already defined and none of them is "serve the whole object": a first-byte-pos
# past the end is a 416 carrying the real size (section 15.5.17), and a
# last-byte-pos or suffix past the end clamps to the object (section 14.1.1).
# Dropping an over-long value on the floor and replying 200 would hand a client
# that asked for one tile the entire file — the corrupt-splice failure
# `RANGE_UNSATISFIABLE` exists to prevent.
#
# 19 digits because 2**63-1 has 19 and no object is that large; every value
# above it compares against `size` identically.
_MAX_RANGE_DIGITS = 19


def _range_int(digits: str, size: int) -> int:
    """``int(digits)``, saturated above any size a stored object can have.

    Leading zeros are stripped before the length test so that a padded literal
    is measured by its value and not by its typing: ``bytes=-0000...0`` is a
    zero-length suffix and must reach the 416 branch, not be mistaken for an
    astronomically large one.
    """
    trimmed = digits.lstrip("0") or "0"
    if len(trimmed) > _MAX_RANGE_DIGITS:
        return size + 1
    return int(trimmed)


def parse_byte_range(raw: str | None, size: int) -> tuple[int, int] | str | None:
    """Resolve a Range header to an inclusive ``(start, end)`` byte pair.

    Returns ``None`` when there is no usable range and the caller should serve
    the complete representation, ``RANGE_UNSATISFIABLE`` when it must answer
    416, and otherwise the resolved pair — already clamped to the object, so
    callers never have to re-check the bounds.

    Multi-range requests return ``None``. RFC 9110 section 14.2 lets a server
    answer a multi-range request with a single range or with the whole
    representation; ``multipart/byteranges`` is not implemented here, and
    answering the FIRST range while echoing only its Content-Range would be
    the corrupt-download failure — a client expecting two parts writes one of
    them over both offsets.
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

    RFC 9110 section 13.1.5: ``If-Range`` is evaluated with the STRONG
    comparison function, and on a mismatch the server MUST ignore the Range
    header field — which means answering 200 with the whole representation, not
    416 and not a 206 of the new bytes. The client throws away the prefix it
    was resuming and starts again, which is the outcome that keeps two versions
    of an object from being spliced into one file.

    Three ways this returns False, all of them "cannot prove the client is
    resuming the object it started":

    - the validators differ (the usual case: a replacement landed);
    - the client sent ``W/"..."``, which strong comparison never matches;
    - this representation has no validator at all, so there is nothing to
      compare against.

    An absent ``If-Range`` returns True: the client asked for a range with no
    precondition, and RFC 9110 gives the server nothing to check it against.
    Such a client can still splice across a replacement, and no server-side
    change can stop it — which is why the validator has to be ON the response,
    where a client that wants to resume safely can pick it up.

    fix(#1532 review r1): moved here from the COG route alongside the parser,
    because the export download needs the identical evaluation and lives under
    ``processing/``. Reimplementing strong comparison a second time is how the
    two would drift.
    """
    if if_range is None:
        return True
    return etag is not None and if_range.strip() == etag


def if_match_passes(if_match: str | None, etag: str | None) -> bool:
    """May this request proceed, given the client's ``If-Match``? Section 13.1.1.

    STRONG comparison, like ``If-Range`` and unlike ``If-None-Match``: the
    client is saying "only act on the representation I already hold", and a
    weak validator cannot promise byte-for-byte identity.

    ``*`` passes whenever a current representation exists, which by this point
    is what the RasterAsset row asserts — deliberately including a row with no
    digest, because ``*`` asks whether there is a representation at all, not
    whether it is the one the client remembers.

    A specific tag against a row with no ``sha256`` is False: unverifiable is
    not a pass. That is the same call ``range_bound_to_this_version`` makes,
    and it costs those rows nothing a conditional request was going to give
    them anyway.
    """
    if not if_match:
        return True
    candidates = [tag.strip() for tag in if_match.split(",")]
    if "*" in candidates:
        return True
    return etag is not None and etag in candidates


def if_none_match_matches(if_none_match: str | None, etag: str | None) -> bool:
    """Does the client already hold this representation? RFC 9110 section 13.1.2.

    WEAK comparison, unlike ``If-Range`` above, and the difference is not an
    oversight: a cache revalidation only needs the two representations to be
    equivalent, while a resumed range needs them byte-identical. The spec picks
    a different comparison function for each, so this route does too.

    ``*`` matches any current representation, and fix(#1554) is that it does so
    even when ``etag`` is None. The section says "if the field value is '*',
    the condition is false if the origin server has a current representation" —
    a statement about the RESOURCE, with no clause about the server being able
    to name it. A row predating the ``sha256`` column has bytes in storage, the
    caller stat'd them before asking, and answering 200 there transfers a
    multi-gigabyte COG to tell a cache what it already knew.

    The wildcard is checked before ``etag`` for that reason, and the specific
    tags after it are still refused when there is nothing to compare: a
    representation this route holds no entity-tag for matches no entity-tag,
    so the condition is true and the client gets the bytes it asked for.

    A match is answered 304 unconditionally because this path serves GET and
    HEAD only (``test_the_cog_download_answers_only_safe_methods`` pins that).
    The same section makes ``*`` a 412 for a method that would create or
    replace a representation, which is a different answer this route has no
    caller for.

    A list is a list: a client may hold several versions and offer all of them.
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

    The ETag goes back per RFC 9110 section 15.4.5, and ``Accept-Ranges``
    with it so a client revalidating before a resume does not have to
    re-probe to learn ranges are available. No body and no ``Content-Length``:
    starlette's ``init_headers`` skips the length for 304 (and 204) exactly as
    the spec requires, which is why this response does not need the explicit
    header ``_cog_head_response`` has to pass.

    fix(#1554): ``etag`` may be None, and then the 304 carries none. Section
    15.4.5 asks for the header fields a 200 would have sent, and the 200 for a
    row with no stored digest sends no validator either (the response helpers omits
    it for the same reason). Minting one to fill the slot would be worse than
    the blank: it would authorize the resume ``range_bound_to_this_version``
    refuses on exactly these rows.
    """
    headers = {"Accept-Ranges": "bytes"}
    if etag is not None:
        headers["ETag"] = etag
    return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers=headers)
