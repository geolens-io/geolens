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
