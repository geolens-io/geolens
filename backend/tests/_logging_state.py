"""Save and restore everything ``setup_logging()`` mutates.

fix(#1064 codex r2): ``setup_logging()`` does not only touch the root logger.
Reading ``app/core/logging_config.py:283-304`` line by line, it clears root's
handlers, then clears handlers and rewrites ``propagate`` on ``uvicorn``,
``uvicorn.error`` and ``uvicorn.access``. A teardown that restores only root
leaves those three changed — measured, a caller's ``uvicorn.access`` goes in
with ``propagate=True`` and comes back out with ``propagate=False``.

fix(#1746 codex r5): the same function also sets ``httpx``/``httpcore`` to
``WARNING`` (finding 1/13's fix), and that level survived every restore here
until now for exactly the reason the paragraph above warns about: it was not
on this list. A caller doing ``configured_logging()`` around a direct
``setup_logging()`` call left both loggers pinned at ``WARNING`` for the rest
of the worker.

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

from app.core.logging_config import setup_logging

# Every logger setup_logging() reaches, from logging_config.py:283-304.
# "" is the root logger.
_MUTATED_LOGGERS = (
    "",
    "uvicorn",
    "uvicorn.error",
    "uvicorn.access",
    "httpx",
    "httpcore",
)


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


@contextlib.contextmanager
def configured_logging(
    *, json_logs: bool = True, log_level: str = "DEBUG", production: bool = False
) -> Iterator[None]:
    """``setup_logging()`` inside a preserved window, with the freeze disarmed.

    fix(#1064 codex r4): use this rather than ``preserved_logging_state()``
    directly whenever the window CALLS ``setup_logging()``. Restoring the
    config on exit is not enough on its own, because ``setup_logging()`` turns
    ``cache_logger_on_first_use`` ON, and a module-level logger that emits
    while it is on freezes its ``BoundLoggerLazyProxy`` against the
    then-current chain. That bind lives on the proxy object, not in the config,
    so no amount of restoring undoes it — the logger is simply invisible to
    every later ``capture_logs()`` in the worker. It is the #1063 mechanism.

    **The order is the entire reason this is a separate helper.** The disable
    has to land AFTER ``setup_logging()``; ``preserved_logging_state()`` cannot
    do the job by configuring before it yields, because ``setup_logging()``
    would immediately turn caching back on. A caller composing the two by hand
    gets that wrong silently — nothing fails, the freeze just happens.

    Turning caching off keeps the processor chain and the stdlib routing
    ``setup_logging()`` installed; only the freezing goes. The original value
    is restored on exit like everything else.

    Enter it INSIDE the test body, never in fixture setup: pytest swaps
    ``sys.stdout``/``sys.stderr`` for the call phase only, so a handler built
    during setup binds to a stream ``capsys`` is not capturing and every write
    fails with ``--- Logging error ---`` instead of landing anywhere assertable.
    """
    with preserved_logging_state():
        setup_logging(json_logs=json_logs, log_level=log_level, production=production)
        structlog.configure(cache_logger_on_first_use=False)
        yield
