"""Structured logging configuration using structlog with stdlib bridge.

SEC-03 / M-65: a sensitive-field redactor processor is inserted into the
structlog chain so JWT / API-key / password values are replaced with
`[REDACTED]` before reaching stdout / log aggregators. Even a bare
`logger.info("attempt", token=jwt)` gets redacted at the structlog layer.

fix(#1485): exception rendering never goes through rich, in production or
dev. `structlog.dev.ConsoleRenderer` defaults to
`RichTracebackFormatter(show_locals=True)` whenever rich is importable;
rendering per-frame locals costs time proportional to `repr()` of every
local in every frame, and rich's line splitting is quadratic in line length
-- one exception with ORM objects in scope burned minutes of synchronous CPU
on the event loop, in the request path. `locals_max_length`/
`locals_max_string` don't bound this: they truncate containers and `str`
values, not an arbitrary object's `repr()`.

fix(#1746): `_redact_sensitive_fields` is KEY-based, so it never scans the
`event` message string. Two leak paths bypass it: httpx logs the full
outgoing request URL at INFO, including `?token=...` on the ArcGIS path; and
Procrastinate's worker logs `task_kwargs` via `Job.call_string`
(`procrastinate/jobs.py`), putting a credential-store token in the message
text as a bare keyword rather than a keyed field. Both are stdlib records
routed through `shared_processors` as the `ProcessorFormatter`'s
`foreign_pre_chain`.

fix(#1746): `redact_url_credentials()` assumes its input is already
URL-shaped -- its `_URLSPLIT_STRIPS` step deletes `\t`/`\r`/`\n`
unconditionally on that assumption. Gating on `has_url_credentials(event)`
parsing the WHOLE event as one URL missed real credentials, because a
message like `HTTP Request: GET https://user:SECRET@example.com/path
"HTTP/1.1 200 OK"` doesn't parse as a URL on its own. Matching every
`url_redaction.URL_LIKE_RE` substring individually finds the credential the
whole-event parse missed, and stays safe since the regex's character class
excludes whitespace -- a match can never contain what the strip removes.

fix(#1746): `format_exc_info` now runs UNCONDITIONALLY (not gated
on `json_logs or production`), and dev's `ConsoleRenderer` takes the same
`plain_traceback` formatter production does -- the only formatter compatible
with a pre-rendered `exception` field (see the comment in `setup_logging`).
Locals are where a secret variable itself leaks regardless of any string
scrub, so removing rich from dev closes that path too. Dev keeps every other
`ConsoleRenderer` default; only the exception formatter changed.

fix(#1844): #1746 fixed the `event` string but left the STRUCTURED half of
the record alone -- `_redact_sensitive_fields` only checked top-level keys.
`structlog.stdlib.ExtraAdder()` lifts a stdlib record's whole `extra`
mapping in, and Procrastinate's worker puts `task_kwargs` there twice (raw
plus a rendered `call_string` copy), so a wire credential on a default
install (no credential store) hit the operator log twice per line on three
INFO lines before the task body ran. `_redact_sensitive_fields` now walks
container values through `redact_nested()`, which redacts denylisted keys at
depth and applies `_scrub_text` to nested strings.
"""

import dataclasses
import logging
import re
from collections import deque
from collections.abc import Mapping, MutableMapping
from typing import Any

import structlog

from app.core.url_redaction import (
    URL_LIKE_RE,
    query_has_credentials,
    redact_url_credentials,
    scrub_registered_credentials,
)

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
        # fix(#1844): a credential-store reference is a single-use bearer
        # capability with a sweeper-renewed TTL, so reading it from a log
        # line before the worker claims it lets it be redeemed instead.
        "credential_ref",
    }
)

# Depth ceiling for redact_nested(). Audit payloads are two or three levels at
# most; this only exists so a caller-supplied cyclic structure terminates.
_MAX_REDACT_DEPTH = 8

# fix(#1844): keys `_redact_sensitive_fields` must never hand to
# `redact_nested()`. The deep walk returns a LIST for every sequence it
# rebuilds, but `exc_info` is a `(type, value, traceback)` TUPLE a downstream
# renderer unpacks positionally -- a guard against chain reordering, since
# `format_exc_info` pops it before this processor runs today.
_NEVER_WALKED_FIELDS: frozenset[str] = frozenset({"exc_info", "positional_args"})

# fix(#1778): share-link and embed paths carry a bearer capability as a PATH
# segment, unreachable to the key-based `_redact_sensitive_fields`. Two 5xx
# handlers (api/main.py's 503, standards/ogc/errors.py's 500) logged
# `request.url.path` raw, writing the full replayable token on any server
# error for a shared-map request. `/m/` joins the two `maps/shared/` shapes
# since frontend/nginx.conf already redacts all three at the edge.
_CAPABILITY_PATH_RE = re.compile(r"^(?P<prefix>/(?:api/)?maps/shared/|/m/)[^/]+")


def safe_access_log_path(path: str) -> str:
    """Remove bearer capability segments from paths written to logs."""
    return _CAPABILITY_PATH_RE.sub(r"\g<prefix>[REDACTED]", path, count=1)


# fix(#1844): names redacted here MUST be `_SENSITIVE_FIELDS`
# itself, not a hand-kept subset -- an earlier cut covered only 2 of 14
# denylist names, so the other 12 were redacted as keys but emitted verbatim
# in the `call_string` text beside them. `test_repr_scrub_covers_every_denylisted_name`
# pins the equality so this can't drift again.
#
# Longest-first keeps the alternation deterministic (no name shadows a
# suffix); `re.escape` handles regex-significant names (`x-api-key`);
# IGNORECASE matches the key pass's `key.lower()`. A word boundary keeps
# `token_hint=` from matching. Only a QUOTED value is redacted, so
# `credential_ref=None` stays legible while `credential_ref='...'` becomes
# `credential_ref='[REDACTED]'` -- "was a credential attached" stays
# answerable, "which one" doesn't.
_REDACTED_REPR_NAMES: tuple[str, ...] = tuple(
    sorted(_SENSITIVE_FIELDS, key=lambda name: (-len(name), name))
)
_REPR_NAME_ALTERNATION = "|".join(re.escape(name) for name in _REDACTED_REPR_NAMES)

# fix(#1746): catches a token rendered as a Python dict repr (`{'token':
# 'abc', ...}`) or `key=value!r` kwargs -- the shape `Job.call_string`
# produces, e.g. `ingest_service[1270](token='abc', credential_ref=None)`.
#
# fix(#1746): value body is `(?:\\.|[^\\])*?`, not a bare `.*?`.
# `repr()` of a string with both quote styles escapes its delimiter
# character inside the value, so a bare lazy `.*?` stops at that escaped
# delimiter instead of the real closing quote. `\\.` consumes an escape as
# one unit before the closing-quote alternative can match it.
#
# fix(#1746): the non-escape alternative excludes the backslash
# (`[^\\]`, not `.`) so the two alternatives never overlap -- otherwise a run
# of N backslashes with no closing quote has N ways to split, and the engine
# tried all of them: exponential backtracking, 36 backslashes over 3 seconds,
# synchronously, on every log record. Excluding it makes an unterminated
# match fail in linear time instead.
_TOKEN_VALUE_RE = re.compile(
    rf"""
    (?:
        (?P<dq>['\"])(?P<dname>{_REPR_NAME_ALTERNATION})(?P=dq)
        \s*:\s*(?P<dv>['\"])(?:\\.|[^\\])*?(?P=dv)
      |
        \b(?P<kname>{_REPR_NAME_ALTERNATION})\b
        \s*=\s*(?P<kv>['\"])(?:\\.|[^\\])*?(?P=kv)
    )
    """,
    re.VERBOSE | re.IGNORECASE,
)


def _redact_token_value_repr(value: str) -> str:
    """Redact a `'token': '...'` (dict-repr) or `token='...'` (kwarg) pair."""

    def _sub(match: re.Match[str]) -> str:
        if match.group("dq") is not None:
            quote, value_quote = match.group("dq"), match.group("dv")
            name = match.group("dname")
            return f"{quote}{name}{quote}: {value_quote}[REDACTED]{value_quote}"
        value_quote = match.group("kv")
        return f"{match.group('kname')}={value_quote}[REDACTED]{value_quote}"

    return _TOKEN_VALUE_RE.sub(_sub, value)


def _redact_url_match(match: re.Match[str]) -> str:
    """Redact one `URL_LIKE_RE` match, escalating to the whole query if needed.

    fix(#1746): `redact_url_credentials()` replaces only KNOWN
    credential query-parameter values via `urlsplit`/`parse_qsl`, which a
    token value containing an unescaped `#` or `&` breaks (`urlsplit` treats
    `#` as a fragment start; `parse_qsl` treats `&` as a new, valueless
    parameter) -- either way part of the secret survives. Once the query is
    known to carry a credential, dropping it whole is cheaper than trusting a
    partial parse. Checked with `#` also treated as `&`, since it isn't a
    `parse_qsl` delimiter, to catch a credential split across that boundary.
    """
    url = match.group(0)
    redacted = redact_url_credentials(url)
    _, _, query = url.partition("?")
    if query and (
        query_has_credentials(query) or query_has_credentials(query.replace("#", "&"))
    ):
        head, _, _ = redacted.partition("?")
        redacted = f"{head}?<redacted>"
    return redacted


# fix(#1746): catches a credential-bearing query independent of
# whether URL_LIKE_RE matched the URL it belongs to. A path character
# URL_LIKE_RE's `[^\s"'<>]+` class excludes (e.g. an apostrophe, accepted by
# validators and kept literal by httpx) makes URL_LIKE_RE stop before the
# query starts, so `_redact_url_match()` never runs and `?token=...`
# survives. Scans for any `?`-led non-whitespace run anywhere in the text.
_QUERY_TAIL_RE = re.compile(r"\?[^\s]*")


def _redact_query_tail_match(match: re.Match[str]) -> str:
    """Redact one `?`-led run of non-whitespace if its tail carries a credential."""
    tail = match.group(0)[1:]
    if query_has_credentials(tail) or query_has_credentials(tail.replace("#", "&")):
        return "?<redacted>"
    return match.group(0)


def _scrub_text(value: str) -> str:
    """Redact URL credentials and rendered token values in free text.

    fix(#1746): scrubs PER URL-SHAPED SUBSTRING, not the whole
    string -- see the module docstring for why a whole-string gate missed a
    userinfo credential. `_redact_url_match()` (codex r6) escalates to the
    whole query when a partial parse would leave part of a credential behind.

    fix(#1746): factored out of `_redact_sensitive_fields` so the
    same scrub applies to a rendered `exception` string as to `event` -- e.g.
    `httpx.HTTPStatusError`'s message quotes the failing URL verbatim.

    fix(#1746): the `_QUERY_TAIL_RE` pass runs independently of
    `URL_LIKE_RE` above it -- see its own comment for why the URL match alone
    isn't reliable enough to gate a query redaction on.

    fix(#1770): `scrub_registered_credentials` runs LAST, since
    every pattern-based pass above only recognises a credential by SHAPE
    (known query-parameter name, or userinfo), missing one reflected into a
    path or an unknown query key by a same-origin redirect.
    `register_credential_secret` (`core/service_tokens.py`) runs wherever a
    credential header is composed, so this closes it by EXACT VALUE instead.
    """
    value = URL_LIKE_RE.sub(_redact_url_match, value)
    value = _QUERY_TAIL_RE.sub(_redact_query_tail_match, value)
    value = _redact_token_value_repr(value)
    return scrub_registered_credentials(value)


def _redact_sensitive_fields(
    _logger: Any, _method_name: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    """Redact event_dict values whose key is in the denylist.

    Case-insensitive on key. Replaces the value with the literal string
    "[REDACTED]" regardless of original type (str / int / dict / etc.).

    fix(#1844): a CONTAINER value goes through `redact_nested()` instead of
    being emitted verbatim. `structlog.stdlib.ExtraAdder()` lifts a stdlib
    record's whole `extra` mapping in, and Procrastinate's worker sets
    `extra["job"]` to `asdict()` plus `call_string` on every outcome line --
    the job's `task_kwargs` verbatim AND a second rendered copy, which is the
    wire credential itself on a default install. The walk is gated on the
    value being a container, so a flat record still costs one `isinstance`
    per field. `redact_nested()` keeps its own depth ceiling.

    fix(#1746): the key-based loop above only sees STRUCTURED fields, so it
    can't catch a secret in the rendered MESSAGE STRING (httpx's request-URL
    line, Procrastinate's keyword-rendered task_kwargs). `event` is scrubbed
    here by pattern and shape instead.

    fix(#1746): `exception` gets the identical scrub when present as
    a string. `format_exc_info` runs BEFORE this processor (see
    `setup_logging`) so `exception` is already a plain string by then.
    `exc_info` itself (the raw tuple/bool, dev mode only) is never touched:
    dev's rich-based renderer turns it into text after this processor.
    """
    for key in list(event_dict.keys()):
        if key.lower() in _SENSITIVE_FIELDS:
            event_dict[key] = "[REDACTED]"
            continue
        value = event_dict[key]
        if key in _NEVER_WALKED_FIELDS:
            continue
        if _is_walkable(value):
            # fix(#1844): a container in `extra` is third-party
            # input all the way down; a lazy Mapping whose `.items()` raises
            # would take the exception out through the chain and cost the
            # whole log line. Falling back to a placeholder keeps the line.
            try:
                event_dict[key] = redact_nested(value)
            except Exception:  # noqa: BLE001 - see comment above
                event_dict[key] = "[UNREDACTABLE]"
    event = event_dict.get("event")
    if isinstance(event, str):
        event_dict["event"] = _scrub_text(event)
    exception = event_dict.get("exception")
    if isinstance(exception, str):
        event_dict["exception"] = _scrub_text(exception)
    return event_dict


# fix(#1857): the container types the walk takes apart. One tuple,
# because the walk and the processor that decides WHETHER to walk must agree:
# a type in one and not the other is walkable and never walked.
_ITERABLE_CONTAINERS = (list, tuple, set, frozenset, deque)
_WALKABLE_CONTAINERS = (Mapping, *_ITERABLE_CONTAINERS)


def _is_dataclass_instance(value: Any) -> bool:
    """A dataclass INSTANCE, never the class, which has no field values."""
    return dataclasses.is_dataclass(value) and not isinstance(value, type)


def _is_walkable(value: Any) -> bool:
    return isinstance(value, _WALKABLE_CONTAINERS) or _is_dataclass_instance(value)


def redact_nested(value: Any, _depth: int = 0) -> Any:
    """Deep-redact denylisted keys and scrub nested strings in a payload.

    Two callers, one policy. ``platform/audit.py`` uses it for the audit event
    logged when a sink drops a row (fix #1491): a ``basemaps`` setting can
    carry an ``api_key`` nested two levels inside ``details``, where a shallow
    pass can't see it. ``_redact_sensitive_fields`` uses it for any container
    reaching the event dict, covering a third-party library's stdlib
    ``extra`` (see that function for the Procrastinate case).

    fix(#1844): every nested ``str`` also goes through ``_scrub_text`` -- a
    denylisted KEY is not the only way a credential travels inside a
    container, e.g. Procrastinate's ``call_string`` key isn't sensitive but
    its value is. Key redaction and pattern scrubbing are complements, not
    alternatives.

    Depth is capped since a caller-supplied payload need not be JSON-derived;
    a self-referencing structure would otherwise not terminate.

    ``frozenset``, ``deque`` and dataclass instances are walked; anything
    else is returned as-is. A dataclass yields field name to redacted value
    via ``dataclasses.fields`` (#1857).
    """
    if _depth >= _MAX_REDACT_DEPTH:
        return "[TRUNCATED]"
    if isinstance(value, str):
        return _scrub_text(value)
    if isinstance(value, Mapping):
        return _redact_items(value.items(), _depth)
    if isinstance(value, _ITERABLE_CONTAINERS):
        return [redact_nested(item, _depth + 1) for item in value]
    if _is_dataclass_instance(value):
        return _redact_items(
            [
                (field.name, getattr(value, field.name, None))
                for field in dataclasses.fields(value)
            ],
            _depth,
        )
    return value


def _redact_items(items: Any, _depth: int) -> dict:
    """Key-denylist plus a recursive walk, for anything with named members."""
    return {
        key: (
            "[REDACTED]"
            if str(key).lower() in _SENSITIVE_FIELDS
            else redact_nested(val, _depth + 1)
        )
        for key, val in items
    }


def apply_http_logger_levels(root_level: int | str) -> None:
    """Keep httpx/httpcore at least as quiet as WARNING, never quieter than root.

    fix(#1746): httpx (and httpcore) logs the full request URL at INFO on
    every call, including `?token=...` on the ArcGIS path. Root defaults to
    INFO, so WARNING drops the routine per-request echo while keeping
    connection failures visible; the `event`-string scrub in
    `_redact_sensitive_fields` backstops whatever still gets through.

    fix(#1746): a FIXED WARNING reverses itself once root is raised
    past it, since `Logger.isEnabledFor` uses the logger's own explicit level
    and never re-derives from root -- `LOG_LEVEL=ERROR` left httpx sitting at
    WARNING, MORE verbose than asked. Deriving from whichever level is
    stricter makes WARNING a floor: quieter than WARNING, httpx follows root;
    noisier, httpx stays at WARNING.
    """
    if isinstance(root_level, str):
        root_level = logging.getLevelName(root_level.upper())
    level = max(logging.WARNING, root_level)
    for _log in ("httpx", "httpcore"):
        logging.getLogger(_log).setLevel(level)


def setup_logging(
    json_logs: bool = False, log_level: str = "INFO", *, production: bool = False
) -> None:
    """Configure structlog + stdlib logging with shared processor chain.

    fix(#1746): `production` no longer selects the exception-
    rendering posture -- dev and production render exceptions identically
    (plain, scrubbed, no rich), since `format_exc_info` runs unconditionally.
    `production` is still threaded through from `settings.is_production` in
    case a future difference needs it; today it affects nothing here.
    """
    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.stdlib.ExtraAdder(),
        structlog.processors.TimeStamper(fmt="iso", utc=True),
    ]

    # fix(#1485): resolve `exc_info` into a plain `exception` string inside
    # the processor chain, so no renderer is ever handed a traceback object
    # to pretty-print. Also the ProcessorFormatter's `foreign_pre_chain`
    # below, so it covers stdlib records (uvicorn.error) too.
    #
    # fix(#1746): runs BEFORE `_redact_sensitive_fields`, since an
    # exception's own message can carry a credential
    # (`httpx.HTTPStatusError` quotes the failing URL verbatim) and the
    # redactor can only scrub a field that already exists.
    #
    # fix(#1746): now UNCONDITIONAL -- gating on `json_logs or
    # production` left dev printing raw, unscrubbed tracebacks. dev's
    # `ConsoleRenderer` below now always uses `plain_traceback` too.
    shared_processors.append(structlog.processors.format_exc_info)

    shared_processors += [
        # SEC-03: redact sensitive fields BEFORE rendering / stack-info.
        # Placed after TimeStamper (so the redactor runs on the final field
        # set, including a `format_exc_info`-rendered `exception` string
        # when one exists) and before StackInfoRenderer (which doesn't add
        # user-supplied values).
        _redact_sensitive_fields,
        structlog.processors.StackInfoRenderer(),
    ]

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
    else:
        # `plain_traceback` is required, not redundant, with the #1485 fix:
        # ConsoleRenderer warns on every exception when a non-plain formatter
        # meets an already-rendered `exception` field. fix(#1746):
        # dev and production share this construction now (see module
        # docstring).
        log_renderer = structlog.dev.ConsoleRenderer(
            exception_formatter=structlog.dev.plain_traceback
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

    apply_http_logger_levels(log_level.upper())
