"""ADR-002 Decision 3 (#1953): what may become a stored failure reason.

The single enforcement point for the clause "a stored reason string carries
no raw exception, no URL with query-string credentials, and no GDAL command
line". Every sink that persists or returns failure text routes through this
module, so the clause holds whichever caller composed the text.
"""

from __future__ import annotations

from app.core.url_redaction import redact_url_credentials, scrub_registered_credentials

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

    fix(#1953): provenance, not shape. A class defined under ``app.``
    carries text we chose; anything else renders library internals, which
    for SQLAlchemy means the statement and its bound parameters.
    """
    return type(exc).__module__.startswith(_OWN_EXCEPTION_ROOT)


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
    summary = lines[0] if lines else ""
    redacted = scrub_registered_credentials(redact_url_credentials(summary))
    return redacted[:MAX_REASON_CHARS]


def coded_failure_reason(prefix: str, exc: BaseException) -> str:
    """A composed reason naming the exception's TYPE, never its message.

    fix(#1953): the durable half of #1755's ``DeferFailed.cause_class``
    argument. A class name is a Python identifier and can carry no
    credential, so it survives Decision 3 where ``str(exc)`` does not.
    """
    return f"{prefix} ({type(exc).__name__})"
