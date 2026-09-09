"""ADR-002 Decision 3 (#1953): what may become a stored failure reason.

The single enforcement point for the clause "a stored reason string carries
no raw exception, no URL with query-string credentials, and no GDAL command
line". Every sink that persists or returns failure text routes through this
module, so the clause holds whichever caller composed the text.
"""

from __future__ import annotations

import re

from app.core.url_redaction import (
    redact_filesystem_paths,
    redact_libpq_credentials,
    redact_url_credentials,
    scrub_registered_credentials,
)

# Cap on stored failure text. GDAL stderr runs to kilobytes and the useful
# part is at the front.
MAX_REASON_CHARS = 2000

# fix(#1953): what a sink stores instead of an exception it did not compose.
# A code rather than prose, so a reader (`ReuploadDialog.tsx`) can localize
# it and no driver text can hide behind it.
INTERNAL_FAILURE_REASON = "internal_error"

_OWN_EXCEPTION_ROOT = "app."


def is_composed_exception(exc: BaseException) -> bool:
    """Whether this codebase, rather than a library, wrote the message.

    fix(#1953): provenance, not shape. A class defined under ``app.``, or
    ``ValueError`` itself, which is this tree's spelling for a refusal the
    user is meant to read. Its subclasses are NOT admitted by that half: a
    library's own is still a library's text, and ``UnicodeDecodeError``
    renders the byte a decoder choked on.
    """
    return type(exc) is ValueError or type(exc).__module__.startswith(
        _OWN_EXCEPTION_ROOT
    )


def redact_failure_reason(reason: str | BaseException) -> str:
    """Failure text safe to store in a reason column or return in a response.

    fix(#1953): a sink is reached both with an exception and with text a
    caller already flattened, so the raw-exception clause is enforced for
    both. A library exception becomes ``INTERNAL_FAILURE_REASON``; text
    keeps only its first line, which is where an exception's own summary
    ends and its payload dump begins.
    """
    if isinstance(reason, BaseException):
        if not is_composed_exception(reason):
            return INTERNAL_FAILURE_REASON
        reason = str(reason)
    lines = reason.splitlines()
    summary = _drop_subprocess_output(_scrub(lines[0] if lines else ""))
    # fix(#1953): the scrubbers must see a credential whole, and choosing the
    # summary line first can hand them half of one. Scrubbing the whole text
    # cannot replace that (urlsplit deletes the line breaks the payload cut
    # needs), so it is the cross-check: a line the wider pass would have
    # changed is not one to keep.
    if not summary or _scrub_stable(summary) not in _scrub_stable(_scrub(reason)):
        return INTERNAL_FAILURE_REASON
    return summary[:MAX_REASON_CHARS]


# fix(#1953): a GDAL invocation, which is the clause's "command line". The
# lookahead is what tells one from a mention: an invocation is followed by a
# flag or an operand, never by "failed" or by prose. Scrubbing the operands
# cannot meet the clause, since the flags and the target table are operands.
_GDAL_INVOCATION_RE = re.compile(
    r"(?i)\b(?:ogr2ogr|ogrinfo|ogrtindex|gdal[a-z_]{0,24})\s+(?=-|/|PG:|<redacted>)"
)


def _drop_subprocess_output(summary: str) -> str:
    """Everything from a GDAL invocation onward, removed.

    What comes before it is this tree's own prefix and GDAL's diagnostic,
    which is the part a reader needs.
    """
    match = _GDAL_INVOCATION_RE.search(summary)
    return summary[: match.start()].rstrip(" :-") if match else summary


def _scrub(text: str) -> str:
    """Every shape Decision 3 keeps out of a reason, masked.

    fix(#1953): the last two are what a GDAL wrapper drags in. Being defined
    under ``app.`` says who raised the exception, never that its message is
    free of the subprocess output it was built from.
    """
    return redact_filesystem_paths(
        redact_libpq_credentials(
            scrub_registered_credentials(redact_url_credentials(text))
        )
    )


# The characters `urlsplit` deletes, so the cross-check above compares what
# the scrubbers changed rather than where they were handed a line break.
_URLSPLIT_STRIPS = str.maketrans("", "", "\t\r\n")


def _scrub_stable(text: str) -> str:
    return text.translate(_URLSPLIT_STRIPS)


def prefixed_failure_reason(prefix: str, reason: str | BaseException) -> str:
    """``prefix: reason``, or the bare code when there is no reason to give.

    fix(#1953): a prefix wrapped around ``INTERNAL_FAILURE_REASON`` hides the
    code inside a sentence, and the readers that localize it match the code
    exactly.
    """
    redacted = redact_failure_reason(reason)
    if redacted == INTERNAL_FAILURE_REASON:
        return INTERNAL_FAILURE_REASON
    return f"{prefix}: {redacted}"[:MAX_REASON_CHARS]


def coded_failure_reason(prefix: str, exc: BaseException) -> str:
    """A composed reason naming the exception's TYPE, never its message.

    fix(#1953): the durable half of #1755's ``DeferFailed.cause_class``
    argument. A class name is a Python identifier and can carry no
    credential, so it survives Decision 3 where ``str(exc)`` does not.
    """
    return f"{prefix} ({type(exc).__name__})"
