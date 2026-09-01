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

fix(#1746): `_redact_sensitive_fields` is KEY-based, so it never looks inside
the `event` message string itself. That leaves two leak paths open: httpx
(and its httpcore transport) log the full outgoing request URL at INFO for
every call, including a `?token=...` query string on the ArcGIS path; and
Procrastinate's worker logs `task_kwargs` rendered by `Job.call_string`
(`procrastinate/jobs.py`: `", ".join(f"{key}={value!r}" ...)`), e.g.
`Starting job ingest_service[1270](token='...', credential_ref=None)`, which
puts a credential-store token inside the message text as a bare keyword
argument rather than a keyed field. Both are stdlib records, and
`shared_processors` doubles as the `ProcessorFormatter`'s `foreign_pre_chain`,
so this chain already runs for them.

fix(#1746 codex r2): `redact_url_credentials()` is built for a URL (or a
GDAL-style URL-shaped string): its `_URLSPLIT_STRIPS` step deletes `\t`,
`\r`, `\n` unconditionally, on the assumption the caller already knows the
string is URL-shaped (see that module's own docstring). An arbitrary log
`event` is not that — a plain multi-line or tab-delimited message with no
credential in it at all came back with every `\n`/`\t` silently removed.
`has_url_credentials()` is the read-only counterpart with none of that side
effect, so it gates the call: only a string that actually carries a
credential-shaped URL is worth the stripping `redact_url_credentials` does.
"""

import logging
import re
from collections.abc import Mapping, MutableMapping
from typing import Any

import structlog

from app.core.url_redaction import has_url_credentials, redact_url_credentials

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

# Depth ceiling for redact_nested(). Audit payloads are two or three levels at
# most; this only exists so a caller-supplied cyclic structure terminates.
_MAX_REDACT_DEPTH = 8

# fix(#1746): catches a token value rendered either as a Python dict repr
# (`{'token': 'abc', ...}`) or as `key=value!r` keyword arguments — the shape
# `Job.call_string` actually produces, e.g.
# `ingest_service[1270](token='abc', credential_ref=None)`. `\btoken\b`
# excludes `credential_ref=` and `token_hint=`: a word boundary never falls
# between "n" and "_", so a name that merely CONTAINS "token" as a sub-word
# never matches either branch.
_TOKEN_VALUE_RE = re.compile(
    r"""
    (?:
        (?P<dq>['\"])token(?P=dq)\s*:\s*(?P<dv>['\"]).*?(?P=dv)
      |
        \btoken\b\s*=\s*(?P<kv>['\"]).*?(?P=kv)
    )
    """,
    re.VERBOSE,
)


def _redact_token_value_repr(value: str) -> str:
    """Redact a `'token': '...'` (dict-repr) or `token='...'` (kwarg) pair."""

    def _sub(match: re.Match[str]) -> str:
        if match.group("dq") is not None:
            quote, value_quote = match.group("dq"), match.group("dv")
            return f"{quote}token{quote}: {value_quote}[REDACTED]{value_quote}"
        value_quote = match.group("kv")
        return f"token={value_quote}[REDACTED]{value_quote}"

    return _TOKEN_VALUE_RE.sub(_sub, value)


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

    fix(#1746): the key-based loop above only ever sees STRUCTURED fields, so
    it cannot catch a secret embedded in the rendered MESSAGE STRING itself —
    which is exactly how it reaches the log for a raw stdlib record (httpx's
    request-URL line, Procrastinate's keyword-rendered task_kwargs). `event`
    is the one field every record has by this point, so it is scrubbed here
    by pattern and by shape rather than by key.
    """
    for key in list(event_dict.keys()):
        if key.lower() in _SENSITIVE_FIELDS:
            event_dict[key] = "[REDACTED]"
    event = event_dict.get("event")
    if isinstance(event, str):
        # fix(#1746 codex r2): only feed a credential-bearing string through
        # redact_url_credentials() -- see the module docstring for why an
        # unconditional call corrupts every other event.
        if has_url_credentials(event):
            event = redact_url_credentials(event)
        event_dict["event"] = _redact_token_value_repr(event)
    return event_dict


def redact_nested(value: Any, _depth: int = 0) -> Any:
    """Deep-redact denylisted keys in a nested payload.

    The processor above is shallow on purpose: it runs on every log line and
    recursing there would put the walk in the hot path. This is the opt-in
    counterpart for a payload that is known to be nested AND known to be worth
    the cost, which today means the audit event logged when a sink drops it
    (fix(#1491)).

    That path needs it. ``persistent_config`` puts ``old_value``/``new_value``
    into ``details``, and a ``basemaps`` setting carries ``api_key`` inside a
    basemap entry — nested two levels down, where the shallow pass cannot see
    it. ``details`` is not itself a denylisted key, so without this the whole
    payload was emitted verbatim, and precisely during an audit failure.

    Depth is capped because ``details`` is caller-supplied and need not be
    JSON-derived; a self-referencing structure would otherwise not terminate.
    """
    if _depth >= _MAX_REDACT_DEPTH:
        return "[TRUNCATED]"
    if isinstance(value, Mapping):
        return {
            key: (
                "[REDACTED]"
                if str(key).lower() in _SENSITIVE_FIELDS
                else redact_nested(val, _depth + 1)
            )
            for key, val in value.items()
        }
    if isinstance(value, (list, tuple, set)):
        return [redact_nested(item, _depth + 1) for item in value]
    return value


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

    # fix(#1746): httpx (and its httpcore transport) logs the full request
    # URL at INFO on every call, including a `?token=...` query string on the
    # ArcGIS path — with or without a credential store. Root defaults to
    # INFO (see core/config.py), so that line reached every deployment's logs
    # by default, twice per refresh on the credential-store path. WARNING
    # keeps connection failures visible while dropping the routine per-request
    # echo; the `event`-string scrub above is the backstop for whatever still
    # gets through at WARNING or above.
    for _log in ("httpx", "httpcore"):
        logging.getLogger(_log).setLevel(logging.WARNING)
