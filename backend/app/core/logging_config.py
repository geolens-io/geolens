"""Structured logging configuration using structlog with stdlib bridge.

SEC-03 / M-65: a sensitive-field redactor processor is inserted into the
structlog chain so JWT / API-key / password values are replaced with
`[REDACTED]` before reaching stdout / log aggregators. Even if a developer
accidentally logs `logger.info("attempt", token=jwt)`, the token is
redacted at the structlog layer.

fix(#1485): exception rendering is never handed to rich in production.
`structlog.dev.ConsoleRenderer` defaults its `exception_formatter` to
`RichTracebackFormatter(show_locals=True)` whenever rich is importable, and
rich is in the backend's transitive dependency set. Rendering per-frame
locals costs time proportional to the `repr()` of every local in every frame,
and rich's line splitting is quadratic in the length of a single long line —
so one exception raised with ORM objects in scope burned minutes of
synchronous CPU inside the logging call, on the event loop, in the request
path. With `--workers 1` that is the whole API.

`RichTracebackFormatter`'s `locals_max_length` / `locals_max_string` do not
bound it: they truncate containers and `str` values, not the `repr()` of an
arbitrary object, which is exactly what a SQLAlchemy session or model
instance produces.
"""

import logging
from collections.abc import MutableMapping
from typing import Any

import structlog

# SEC-03: case-insensitive denylist of field names that contain sensitive
# values. Comparison is done in lower-case after stripping common
# delimiters. Keep this list small and high-signal — over-aggressive
# matching destroys log usefulness.
_SENSITIVE_FIELDS: frozenset[str] = frozenset(
    {
        "jwt",
        "token",
        "access_token",
        "refresh_token",
        "password",
        "password_hash",
        "api_key",
        "apikey",
        "x_api_key",  # normalized form of X-Api-Key
        "x-api-key",
        "authorization",
        "secret",
        "client_secret",
    }
)


def _redact_sensitive_fields(
    _logger: Any, _method_name: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    """Redact top-level event_dict values whose key is in the denylist.

    Case-insensitive on key. Replaces the value with the literal string
    "[REDACTED]" regardless of original type (str / int / dict / etc.).
    Shallow only — does not recursively walk nested dicts. This is a
    deliberate trade-off: structlog idiomatic usage logs flat key/value
    pairs; recursing would amplify the redactor's CPU cost on every log
    line.
    """
    for key in list(event_dict.keys()):
        if key.lower() in _SENSITIVE_FIELDS:
            event_dict[key] = "[REDACTED]"
    return event_dict


def _dev_exception_formatter() -> structlog.types.ExceptionRenderer:
    """The console exception formatter for non-production deployments.

    Keeps rich's syntax-highlighted frames, which are the reason the pretty
    renderer is worth having, and drops only the per-frame locals tables — the
    part whose cost is unbounded (see the module docstring). Deployments
    without rich installed keep whatever structlog picked for them.
    """
    formatter = structlog.dev.default_exception_formatter
    if isinstance(formatter, structlog.dev.RichTracebackFormatter):
        return structlog.dev.RichTracebackFormatter(show_locals=False)
    return formatter


def setup_logging(
    json_logs: bool = False, log_level: str = "INFO", *, production: bool = False
) -> None:
    """Configure structlog + stdlib logging with shared processor chain.

    `production` selects the exception-rendering posture rather than the log
    format: when set, tracebacks are formatted by the stdlib `traceback`
    module and rich is never reached, at a cost that does not depend on the
    size of any frame's local variables.
    """
    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.stdlib.ExtraAdder(),
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        # SEC-03: redact sensitive fields BEFORE rendering / stack-info.
        # Placed after TimeStamper (so the redactor runs on the final
        # field set) and before StackInfoRenderer (which doesn't add
        # user-supplied values).
        _redact_sensitive_fields,
        structlog.processors.StackInfoRenderer(),
    ]

    # fix(#1485): resolve `exc_info` into a plain `exception` string inside the
    # processor chain, so no renderer is ever handed a traceback object to
    # pretty-print. This chain is also the ProcessorFormatter's
    # `foreign_pre_chain` below, so it covers stdlib records (uvicorn.error and
    # friends) as well as structlog's own.
    if json_logs or production:
        shared_processors.append(structlog.processors.format_exc_info)

    structlog.configure(
        processors=shared_processors
        + [structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    log_renderer: structlog.types.Processor
    if json_logs:
        log_renderer = structlog.processors.JSONRenderer()
    elif production:
        # `plain_traceback` is the second half of the #1485 fix, not a
        # redundant one: ConsoleRenderer warns on every exception when a
        # non-plain formatter meets an already-rendered `exception` field
        # ("Remove `format_exc_info` from your processor chain..."), and it
        # still owns any exc_info that reaches it by another route.
        log_renderer = structlog.dev.ConsoleRenderer(
            exception_formatter=structlog.dev.plain_traceback
        )
    else:
        log_renderer = structlog.dev.ConsoleRenderer(
            exception_formatter=_dev_exception_formatter()
        )

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            log_renderer,
        ],
    )

    handler = logging.StreamHandler()
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(log_level.upper())

    for _log in ("uvicorn", "uvicorn.error"):
        logging.getLogger(_log).handlers.clear()
        logging.getLogger(_log).propagate = True

    logging.getLogger("uvicorn.access").handlers.clear()
    logging.getLogger("uvicorn.access").propagate = False
