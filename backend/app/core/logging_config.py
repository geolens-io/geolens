"""Structured logging configuration using structlog with stdlib bridge.

SEC-03 / M-65: a sensitive-field redactor processor is inserted into the
structlog chain so JWT / API-key / password values are replaced with
`[REDACTED]` before reaching stdout / log aggregators. Even if a developer
accidentally logs `logger.info("attempt", token=jwt)`, the token is
redacted at the structlog layer.

fix(#1485): exception rendering is never handed to rich, in production OR
dev (as of #1746 codex r10 -- see that fix note below for why dev joined).
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

fix(#1746 codex r2, replaced r5): `redact_url_credentials()` is built for a
string already known to be URL-shaped: its `_URLSPLIT_STRIPS` step deletes
`\t`, `\r`, `\n` unconditionally on that assumption, which is wrong for an
arbitrary log `event`. Round 2 gated the call on `has_url_credentials(event)`
to avoid that, but `has_url_credentials()` parses the WHOLE event as one URL
— a message like `HTTP Request: GET https://user:SECRET@example.com/path
"HTTP/1.1 200 OK"` does not parse as a URL on its own (the sentence around it
breaks `urlsplit`), so the gate returned False and the userinfo credential
was emitted verbatim.

`url_redaction.URL_LIKE_RE` already exists to find just the URL-shaped
SUBSTRING inside free text (it is what `redact_url_credentials()` itself
falls back to for non-URL input), so this instead matches every URL-shaped
substring and redacts each one individually. That both finds the real
credential (per-URL matching sees the userinfo the whole-event parse missed)
and keeps the earlier fix intact: `URL_LIKE_RE`'s own character class
excludes whitespace, so a matched substring can never contain `\t`/`\r`/`\n`
in the first place — `redact_url_credentials()`'s unconditional strip has
nothing to strip inside a match, and every character outside a match is
untouched.

fix(#1746 codex r10): round 9 only closed this for `json_logs or production`,
because `format_exc_info` stayed conditional on that and dev's renderer used
a rich-based formatter incompatible with a pre-rendered `exception` field
anyway. That left dev exactly as exposed as before: an unhandled exception
in a local API or worker run still printed a raw, unscrubbed traceback, and
rich's own locals rendering would print a secret held in a local variable
even if the message text were somehow already clean. `format_exc_info` now
runs UNCONDITIONALLY, and dev's `ConsoleRenderer` now takes the same
`plain_traceback` formatter production does — not a softer version of the
same idea, but the only formatter that is even compatible with a
pre-rendered `exception` field (a non-plain one meeting one warns and stops
rendering prettily; see the `plain_traceback` comment in `setup_logging`).
Locals are where a secret variable itself would leak regardless of any
string scrub, so removing rich from dev closes that path too, not only the
one the string scrub covers. Dev keeps every other `ConsoleRenderer` default
(colours included) — only the exception formatter changed.

fix(#1844): #1746 fixed the `event` string and left the STRUCTURED half of
the same record alone, because `_redact_sensitive_fields` only ever looked at
top-level keys. `structlog.stdlib.ExtraAdder()` lifts a stdlib record's whole
`extra` mapping in, and third-party code decides what that mapping holds:
Procrastinate's worker puts `context.job.log_context()` there, which is the
job's `task_kwargs` verbatim plus a rendered `call_string` copy of the same
kwargs. On a default install (no credential store configured) the wire
credential IS a task kwarg, so every authenticated service import and reupload
wrote it to the operator log twice per line, on three INFO lines, before the
task body ran. `_redact_sensitive_fields` now walks container values through
`redact_nested()`, which redacts denylisted keys at depth and applies the same
`_scrub_text` to nested strings.
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
        # capability with a TTL that the sweepers actively RENEW while the job
        # sits `todo`, so whoever reads it out of a log line before the worker
        # claims it can redeem it instead. It is a secret, not a correlation
        # id, and it travels beside the token in exactly the same places.
        "credential_ref",
    }
)

# Depth ceiling for redact_nested(). Audit payloads are two or three levels at
# most; this only exists so a caller-supplied cyclic structure terminates.
_MAX_REDACT_DEPTH = 8

# fix(#1844): keys `_redact_sensitive_fields` must never hand to
# `redact_nested()`. The deep walk returns a LIST for every sequence it
# rebuilds, and `exc_info` is a `(type, value, traceback)` TUPLE that a
# renderer downstream unpacks positionally. `format_exc_info` pops it before
# this processor runs today, so this is a guard against a chain reordering
# rather than a live case -- and it costs one set lookup per field. The rest
# of `ProcessorFormatter`'s meta keys (`_record`, `_from_structlog`) need no
# entry: a LogRecord is not a Mapping or a sequence, so the walk skips them on
# the isinstance check anyway.
_NEVER_WALKED_FIELDS: frozenset[str] = frozenset({"exc_info", "positional_args"})

# fix(#1778): share-link and embed paths carry a bearer capability as a PATH
# segment, so no keyed-field redactor can reach it -- `_redact_sensitive_fields`
# is key-based and the value is inside a string. The access-log middleware has
# scrubbed these since #821; the two 5xx handlers (api/main.py's operational-DB
# 503 and standards/ogc/errors.py's unhandled-error 500) logged
# `request.url.path` raw, so any server error on a shared-map request wrote the
# full token into the application log where it stays replayable. The helper
# lives here rather than in api/middleware/ so `standards/` can import it
# without reaching up into the API layer.
#
# `/m/` joins the two `maps/shared/` shapes because frontend/nginx.conf already
# redacts all three at the edge; the Python side had only the API ones.
_CAPABILITY_PATH_RE = re.compile(r"^(?P<prefix>/(?:api/)?maps/shared/|/m/)[^/]+")


def safe_access_log_path(path: str) -> str:
    """Remove bearer capability segments from paths written to logs."""
    return _CAPABILITY_PATH_RE.sub(r"\g<prefix>[REDACTED]", path, count=1)


# fix(#1844 audit round 1): the names whose RENDERED value this scrub redacts
# are `_SENSITIVE_FIELDS` itself, not a hand-kept subset of it.
#
# The first cut of this listed `token` and `credential_ref`, which is 2 of the
# 14 names on the denylist -- so the other 12 were redacted as KEYS and then
# emitted verbatim in the `call_string` rendering sitting beside them in the
# same record. That is precisely the asymmetry that produced this PR's own
# finding: a key pass and a text pass that disagree about what counts as a
# secret leave the difference in the log. Deriving both from one set is what
# stops the two halves drifting apart again;
# `test_repr_scrub_covers_every_denylisted_name` pins the equality so adding a
# name to the denylist can never again cover only half the record.
#
# Longest-first so the alternation is deterministic and a name that is a
# suffix of another cannot shadow it. `re.escape` because the denylist holds
# names with regex-significant characters (`x-api-key`). IGNORECASE for parity
# with the key pass, which has always compared `key.lower()`: `Token='...'`
# renders exactly as readily as `token='...'`.
#
# Matching is under a word boundary, so `token_hint=` and a hypothetical
# `credential_reference=` still do not match: a boundary never falls between
# two word characters, so a name that merely CONTAINS a denylisted one as a
# sub-word is left alone.
#
# Only a QUOTED value is redacted, which is what keeps the operator signal the
# #1746 note below wanted: `Job.call_string` renders `None` unquoted, so
# `credential_ref=None` stays legible and `credential_ref='...'` becomes
# `credential_ref='[REDACTED]'`. "Was a credential attached to this job" is
# still answerable from the log; "which one" is not.
_REDACTED_REPR_NAMES: tuple[str, ...] = tuple(
    sorted(_SENSITIVE_FIELDS, key=lambda name: (-len(name), name))
)
_REPR_NAME_ALTERNATION = "|".join(re.escape(name) for name in _REDACTED_REPR_NAMES)

# fix(#1746): catches a token value rendered either as a Python dict repr
# (`{'token': 'abc', ...}`) or as `key=value!r` keyword arguments — the shape
# `Job.call_string` actually produces, e.g.
# `ingest_service[1270](token='abc', credential_ref=None)`.
#
# fix(#1746 codex r3): the value body is `(?:\\.|[^\\])*?`, not a bare `.*?`.
# `repr()` of a string containing BOTH quote styles picks one as the
# delimiter and ESCAPES that character where it occurs in the value (and
# always escapes a literal backslash), e.g. `repr("pre'SECRET\"post")` is
# `'pre\'SECRET"post'`. A bare lazy `.*?` stops at that escaped delimiter
# instead of the real closing quote, leaving the rest of the token in the
# log. `\\.` consumes an escape (backslash + whatever follows it) as one
# unit before the closing-quote alternative gets a chance to match it.
#
# fix(#1746 codex r4): the non-escape alternative excludes the backslash
# (`[^\\]`, not `.`) so the two alternatives never overlap. `.` also
# matches `\\`, so a run of N backslashes with no closing quote had N ways
# to split into `\\.` pairs versus lone `.` characters, and the engine tried
# all of them before giving up -- exponential backtracking on malformed
# third-party text (36 backslashes took over three seconds), synchronously,
# on every log record. Excluding the backslash from the second alternative
# leaves exactly one way to consume each character, so an unterminated match
# fails in time linear in the input length instead.
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

    fix(#1746 codex r6): `redact_url_credentials()` only replaces KNOWN
    credential query-parameter VALUES, via `urlsplit`/`parse_qsl`. A token
    value containing an unescaped `#` or `&` (the validators only reject
    whitespace/control characters) breaks that: `urlsplit` reads a `#` as
    the start of a fragment, which query redaction never looks at, and
    `parse_qsl` reads an `&` as a new parameter -- a bare name with no
    value, which matches no known-sensitive key. Either way, part of the
    secret survives in the "redacted" output. This is a log line, so once
    the ORIGINAL query is known to carry a credential at all, dropping the
    whole query is cheaper than trusting a partial parse. Checked on the
    raw query and, since `#` is not a `parse_qsl` delimiter, again with `#`
    treated as `&` so a credential split across the fragment boundary is
    still caught.
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


# fix(#1746 codex r11): catches a credential-bearing query independent of
# whether URL_LIKE_RE matched the URL it belongs to. A base URL containing
# an apostrophe (or any other character URL_LIKE_RE's `[^\s"'<>]+` class
# excludes) in its PATH -- accepted by validators that only reject
# whitespace/control characters, and kept literal by httpx -- makes
# URL_LIKE_RE stop before the query ever starts, so `_redact_url_match()`
# above never runs on it and a trailing `?token=...` survives untouched.
# This scans for any `?`-led run of non-whitespace ANYWHERE in the text,
# independent of what precedes the `?`, and applies the same
# query-has-credentials check `_redact_url_match()` uses.
_QUERY_TAIL_RE = re.compile(r"\?[^\s]*")


def _redact_query_tail_match(match: re.Match[str]) -> str:
    """Redact one `?`-led run of non-whitespace if its tail carries a credential."""
    tail = match.group(0)[1:]
    if query_has_credentials(tail) or query_has_credentials(tail.replace("#", "&")):
        return "?<redacted>"
    return match.group(0)


def _scrub_text(value: str) -> str:
    """Redact URL credentials and rendered token values in free text.

    fix(#1746 codex r5): redact credentials PER URL-SHAPED SUBSTRING, not the
    whole string -- see the module docstring for why a whole-string gate
    missed a userinfo credential, and why matching on URL_LIKE_RE first is
    still whitespace-safe. fix(#1746 codex r6): `_redact_url_match()`
    escalates to the whole query when a partial parse would leave part of
    the credential behind -- see its own docstring.

    fix(#1746 codex r9): factored out of `_redact_sensitive_fields` so the
    exact same scrub applies to a rendered `exception` string as already
    applied to `event` -- an exception's own message can carry a credential
    just as easily as a log line can, e.g. `httpx.HTTPStatusError`'s message
    quotes the failing request URL verbatim, `?token=...` included.

    fix(#1746 codex r11): the `_QUERY_TAIL_RE` pass runs independently of the
    `URL_LIKE_RE` one above it, deliberately -- see its own comment for why
    the URL match alone is not reliable enough to gate a query redaction on.
    A trailing quote or bracket swallowed along with a credential-bearing
    query tail is acceptable in a log line; a bare `?` with no credential
    after it, or one already redacted by the pass above, is left alone
    either way.

    fix(#1770 round 43 P2): `scrub_registered_credentials` runs LAST, over
    the output of every pattern-based pass above. Every one of those passes
    still only recognises a credential by SHAPE -- a known query-parameter
    name, or userinfo -- so a same-origin redirect that reflects one into
    the URL path, or into a query key none of them knows to look for, still
    reached this far untouched. `register_credential_secret`
    (`core/service_tokens.py`) is called at the one place a credential
    header is ever composed, so by the time any log line reaches this
    processor every secret in play for the request or job is already
    registered, and this closes it by EXACT VALUE rather than by guessing
    one more shape.
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

    fix(#1844): a value that is itself a CONTAINER goes through
    `redact_nested()` instead of being emitted verbatim. Shallowness used to be
    the documented trade-off here -- structlog's idiomatic usage is flat
    key/value pairs, and recursing costs CPU on every line -- but
    `structlog.stdlib.ExtraAdder()` (see `setup_logging`) lifts a stdlib
    record's whole `extra` mapping into this event dict, and a third-party
    library decides what goes in there. Procrastinate's worker sets
    `extra["job"] = context.job.log_context()` on `Loaded job info`,
    `Starting job` and every outcome line, and `log_context()` is `asdict()`
    plus `call_string`, so it carries the job's `task_kwargs` verbatim AND a
    second rendered copy. On the service-import and reupload paths those
    kwargs are the wire credential itself whenever no credential store is
    configured, which is the default install. The `event` half of those three
    lines has been scrubbed since #1746; the `job` half was not, twice per
    line. It leaks before the task body runs, so nothing the task itself does
    can help.

    The walk is gated on the value actually being a container, so a flat
    record -- every request-path line -- still costs one `isinstance` per
    field and nothing else. `redact_nested()` keeps its own depth ceiling.

    fix(#1746): the key-based loop above only ever sees STRUCTURED fields, so
    it cannot catch a secret embedded in the rendered MESSAGE STRING itself —
    which is exactly how it reaches the log for a raw stdlib record (httpx's
    request-URL line, Procrastinate's keyword-rendered task_kwargs). `event`
    is the one field every record has by this point, so it is scrubbed here
    by pattern and by shape rather than by key.

    fix(#1746 codex r9): `exception` gets the identical scrub, when present
    and already a string. `format_exc_info` now runs BEFORE this processor
    (see `setup_logging`) precisely so `exception` exists as a plain string
    by the time this runs, instead of being rendered afterward and reaching
    JSON/production logs unscrubbed. `exc_info` itself (the raw tuple/bool,
    present only when `format_exc_info` did NOT run first -- dev mode) is
    never touched: it is not text, and dev's rich-based renderer is the one
    that turns it into text, after this processor.
    """
    for key in list(event_dict.keys()):
        if key.lower() in _SENSITIVE_FIELDS:
            event_dict[key] = "[REDACTED]"
            continue
        value = event_dict[key]
        if key in _NEVER_WALKED_FIELDS:
            continue
        if _is_walkable(value):
            # fix(#1844 audit round 1): a container in `extra` is third-party
            # input all the way down, and `redact_nested()` calls `.items()`,
            # iterates and takes `len()` on objects this module never
            # constructed. A lazy Mapping whose `.items()` raises would take
            # the exception out through the processor chain and cost the whole
            # log line -- during an incident, on a record someone put a
            # credential in. Falling back to the redacted placeholder loses the
            # payload and keeps the line, which is the right direction for both
            # failure modes.
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


# fix(#1857 item 9): the container types the walk knows how to take apart.
# `frozenset` is NOT a subclass of `set` and `deque` is not a subclass of
# anything listed, so both used to fall through to the value untouched and be
# rendered by repr, credential and all. A dataclass instance did the same. One
# predicate, because the walk and the processor that decides WHETHER to walk
# used to carry the membership test separately and a type added to one was a
# type missing from the other.
_ITERABLE_CONTAINERS = (list, tuple, set, frozenset, deque)
_WALKABLE_CONTAINERS = (Mapping, *_ITERABLE_CONTAINERS)


def _is_dataclass_instance(value: Any) -> bool:
    """A dataclass INSTANCE, never the class object itself.

    ``dataclasses.is_dataclass`` answers True for both, and a class has no
    field VALUES to redact.
    """
    return dataclasses.is_dataclass(value) and not isinstance(value, type)


def _is_walkable(value: Any) -> bool:
    return isinstance(value, _WALKABLE_CONTAINERS) or _is_dataclass_instance(value)


def redact_nested(value: Any, _depth: int = 0) -> Any:
    """Deep-redact denylisted keys and scrub nested strings in a payload.

    Two callers, one policy. ``platform/audit.py`` uses it for the audit event
    logged when a sink drops a row (fix(#1491)): ``persistent_config`` puts
    ``old_value``/``new_value`` into ``details``, and a ``basemaps`` setting
    carries an ``api_key`` inside a basemap entry — nested two levels down,
    where a shallow pass cannot see it, and ``details`` is not itself a
    denylisted key. ``_redact_sensitive_fields`` uses it for any container that
    reaches the event dict, which is how a third-party library's stdlib
    ``extra`` gets covered (see that function for the Procrastinate case).

    fix(#1844): every nested ``str`` also goes through ``_scrub_text``, the
    same scrub ``event`` and ``exception`` already get. A denylisted KEY is not
    the only way a credential travels inside a container: Procrastinate renders
    the job's kwargs a second time into ``call_string``, under a key
    (``call_string``) that is not sensitive and holds a value that is. Key
    redaction cannot reach the copy inside a string, and pattern scrubbing
    cannot reach a value stored under a key it does not recognise, so the two
    passes are complements rather than alternatives.

    Depth is capped because a payload here is caller-supplied and need not be
    JSON-derived; a self-referencing structure would otherwise not terminate.

    fix(#1857 item 9): ``frozenset``, ``deque`` and dataclass instances are
    walked too. The first two were missed because neither is a subclass of the
    types that were listed, so both were returned untouched and rendered by
    ``repr``. A dataclass was missed because it is not a container at all by
    type, only by content, and it is the shape a library is most likely to hand
    to ``extra``: a settings or context object holding a token as a field.

    A dataclass is read through ``dataclasses.fields`` rather than
    ``__dict__``, for two reasons. A ``slots=True`` dataclass has no
    ``__dict__`` at all, and ``__dict__`` would also sweep in attributes that
    are not fields, which is a wider promise than this can keep. The result is
    a plain dict of field name to redacted value, so the field NAMES go through
    the same denylist a mapping's keys do. That changes how the object renders;
    the alternative is rendering it by ``repr`` with the credential in it.
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

    fix(#1746): httpx (and its httpcore transport) logs the full request URL
    at INFO on every call, including a `?token=...` query string on the
    ArcGIS path — with or without a credential store. Root defaults to INFO
    (see core/config.py), so that line reached every deployment's logs by
    default, twice per refresh on the credential-store path. WARNING keeps
    connection failures visible while dropping the routine per-request echo;
    the `event`-string scrub in `_redact_sensitive_fields` is the backstop
    for whatever still gets through at WARNING or above.

    fix(#1746 codex r8): a FIXED WARNING silently reverses itself the moment
    root is raised past it. `Logger.isEnabledFor` uses the LOGGER'S OWN
    explicit level once one is set and never re-derives it from root, so
    `LOG_LEVEL=ERROR`/`CRITICAL` at boot, or a runtime change to either via
    the persistent-config log-level setter, left httpx sitting at WARNING —
    MORE verbose than the deployment asked for. Deriving from whichever
    level is stricter makes WARNING a floor rather than a fixed point:
    quieter than WARNING (ERROR, CRITICAL), httpx follows root; noisier
    (INFO or below), httpx stays at WARNING. Accepts the string form too,
    since both call sites (this module's own `setup_logging` and
    `persistent_config.py`'s runtime setter) hold the level as a string
    right before calling this.
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

    fix(#1746 codex r10): `production` no longer selects the
    exception-rendering posture -- dev and production now render exceptions
    identically (plain, scrubbed, no rich), because `format_exc_info` runs
    unconditionally and the redactor needs the SAME `exception` string to
    scrub regardless of console mode. `production` is still threaded through
    from `settings.is_production` at both call sites, in case a future
    difference needs it again; today it affects nothing inside this
    function.
    """
    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.stdlib.ExtraAdder(),
        structlog.processors.TimeStamper(fmt="iso", utc=True),
    ]

    # fix(#1485): resolve `exc_info` into a plain `exception` string inside the
    # processor chain, so no renderer is ever handed a traceback object to
    # pretty-print. This chain is also the ProcessorFormatter's
    # `foreign_pre_chain` below, so it covers stdlib records (uvicorn.error and
    # friends) as well as structlog's own.
    #
    # fix(#1746 codex r9): moved BEFORE `_redact_sensitive_fields` (it used to
    # run last, after `StackInfoRenderer`). An exception's own message can
    # carry a credential -- `httpx.HTTPStatusError` quotes the failing
    # request URL verbatim -- and the redactor can only scrub a field that
    # already exists when it runs.
    #
    # fix(#1746 codex r10): now UNCONDITIONAL. Gating this on `json_logs or
    # production` left dev exactly as exposed as before -- an unhandled
    # exception in a local run still printed a raw, unscrubbed traceback.
    # dev's `ConsoleRenderer` below now uses `plain_traceback`
    # unconditionally too, so there is no longer a renderer left that this
    # would be incompatible with.
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
        # `plain_traceback` is the second half of the #1485 fix, not a
        # redundant one: ConsoleRenderer warns on every exception when a
        # non-plain formatter meets an already-rendered `exception` field
        # ("Remove `format_exc_info` from your processor chain..."), and it
        # still owns any exc_info that reaches it by another route.
        #
        # fix(#1746 codex r10): dev and production share this construction
        # now -- see the module docstring and this function's docstring for
        # why `production` no longer needs to pick between them.
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
