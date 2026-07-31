"""Save and restore everything ``setup_logging()`` mutates.

fix(#1064 codex r2): ``setup_logging()`` does not only touch the root logger.
Reading ``app/core/logging_config.py:103-112`` line by line, it clears root's
handlers, then clears handlers and rewrites ``propagate`` on ``uvicorn``,
``uvicorn.error`` and ``uvicorn.access``. A teardown that restores only root
leaves those three changed — measured, a caller's ``uvicorn.access`` goes in
with ``propagate=True`` and comes back out with ``propagate=False``.

Two earlier rounds of this same mistake are why the list is derived from the
source rather than from memory. The first restored root but not the structlog
processor chain, which silently dropped ``_redact_sensitive_fields``. The
second restored the chain but not these three loggers. The rule: to undo a
function, read what it actually mutates and restore that list — not what its
name suggests, and not the one thing that broke last time.

Restoring what was there, rather than resetting to a library default, is the
point. A reset still changes state the caller established, so it trades one
order-dependence for another and can strip app behaviour a later test relies
on. Repairing a leak that was already there when the test arrived is a
different job, and belongs to the conftest guard in #1066.
"""

from __future__ import annotations

import contextlib
import logging
from collections.abc import Iterator

import structlog

# Every logger setup_logging() reaches, from logging_config.py:103-112.
# "" is the root logger.
_MUTATED_LOGGERS = ("", "uvicorn", "uvicorn.error", "uvicorn.access")


@contextlib.contextmanager
def preserved_logging_state() -> Iterator[None]:
    """Restore the logging state ``setup_logging()`` changes, exactly as found.

    Covers the stdlib side (handlers, ``propagate`` and level, for root and
    each named logger) and the structlog side (the whole config, including the
    processor chain). Callers still have to invoke ``setup_logging()`` inside
    the test body themselves — pytest swaps ``sys.stdout``/``stderr`` for the
    call phase only, so a handler created during fixture setup binds to a
    stream capsys is not capturing.
    """
    saved_loggers = {
        name: (
            logging.getLogger(name).handlers[:],
            logging.getLogger(name).propagate,
            logging.getLogger(name).level,
        )
        for name in _MUTATED_LOGGERS
    }
    saved_structlog = dict(structlog.get_config())
    try:
        yield
    finally:
        structlog.configure(**saved_structlog)
        for name, (handlers, propagate, level) in saved_loggers.items():
            logger = logging.getLogger(name)
            logger.handlers[:] = handlers
            logger.propagate = propagate
            logger.setLevel(level)
