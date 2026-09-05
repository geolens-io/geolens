"""fix(#1746): stdlib log records must not leak service tokens (findings 1, 13).

httpx (and its httpcore transport) logs the full outgoing request URL at INFO
for every call, e.g. ``HTTP Request: GET <url>?f=json&token=<value> "HTTP/1.1
200 OK"``. That line reaches every deployment's logs by default, because root
defaults to INFO (``app.core.config``), and it fires twice per refresh on the
credential-store path (finding 13). Procrastinate's worker separately logs
``task_kwargs`` rendered by ``Job.call_string`` (pinned procrastinate 3.9.0,
``procrastinate/jobs.py``): ``", ".join(f"{key}={value!r}" ...)`` — a bare
keyword-argument rendering, e.g.
``Starting job ingest_service[1270](token='...', credential_ref=None)``, NOT
a dict repr. That puts a token inside the MESSAGE STRING rather than a keyed
field, so the existing key-based ``_redact_sensitive_fields`` processor
cannot see it either way.

pytest's ``caplog`` sees zero structlog records in this repo (it hooks a
handler onto a logger that structlog's stdlib bridge does not use the same
way), so these tests attach an explicit ``logging.Handler`` to the stdlib
root logger instead and read back what it actually received.

``tests/_logging_state.configured_logging()`` saves and restores every
logger ``setup_logging()`` is documented to mutate — root, the three uvicorn
loggers, and (as of fix #1746 codex r5) ``httpx``/``httpcore`` (see
``_logging_state.py``'s own docstring). ``.disabled`` is outside that snapshot
because ``setup_logging()`` never touches it; fix(#1755 item 8) removed the
only thing that did, so this file no longer restores it either.
"""

import base64
import dataclasses
import json
import logging
import time
from collections import deque
from collections.abc import Mapping
from urllib.parse import urlsplit

import pytest
from procrastinate.jobs import Job

from app.core.logging_config import (
    _REDACTED_REPR_NAMES,
    _SENSITIVE_FIELDS,
    _redact_token_value_repr,
    _scrub_text,
)
from app.core.url_redaction import URL_LIKE_RE
from tests._logging_state import configured_logging

_TOKEN = "SECRETTOKEN123"
# fix(#1844): the throwaway credential the job-context tests below put on the
# wire. Deliberately unmistakable filler rather than anything that reads like a
# real credential, while still carrying every SHAPE the scrubber has to
# recognise: a finished basic header line, the base64 blob inside it, and the
# two cleartext halves that blob decodes to.
_BASIC_USER = "AAAAAAAAA"
_BASIC_SECRET = "BBBBBBBBB"
_BASIC_BLOB = base64.b64encode(f"{_BASIC_USER}:{_BASIC_SECRET}".encode()).decode()
_BASIC_LINE = f"Authorization: Basic {_BASIC_BLOB}"
_CREDENTIAL_REF = "REF00000000000001"
_ARCGIS_URL = f"https://services6.arcgis.com/x/FeatureServer/0?f=json&token={_TOKEN}"
# fix(#1746 codex r11): an apostrophe in the URL PATH (not the token) stops
# URL_LIKE_RE's match before the query ever starts -- see _QUERY_TAIL_RE's
# comment in logging_config.py.
_APOSTROPHE_URL = f"https://example.com/it'works/FeatureServer/0?f=json&token={_TOKEN}"


class _ListHandler(logging.Handler):
    """Captures the fully rendered line for every record it receives."""

    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(self.format(record))


def _emit_through_real_pipeline(
    logger_name: str,
    level: int,
    message: str,
    *,
    extra: dict | None = None,
    json_logs: bool = False,
    log_level: str = "INFO",
) -> list[str]:
    """Run `setup_logging()` for real and capture what reaches the root logger.

    The capturing handler is given the SAME formatter `setup_logging()`
    installed (a `structlog.stdlib.ProcessorFormatter` whose
    `foreign_pre_chain` includes `_redact_sensitive_fields`), so redaction is
    exercised exactly as it runs in production rather than by calling the
    processor function directly.

    fix(#1844): `extra` is passed straight through to the stdlib call.
    Every test written for #1746 emitted a message and nothing else, which is
    exactly why the P1-2 leak stayed green through that whole review: the
    processor chain's `structlog.stdlib.ExtraAdder()` lifts a stdlib record's
    `extra` mapping into the event dict, and no test here ever put anything
    there. `json_logs` / `log_level` are exposed for the same reason -- the
    worker's first job line is a DEBUG one, and the structured half of a
    record is far easier to assert on when the renderer emits JSON.
    """
    with configured_logging(json_logs=json_logs, log_level=log_level, production=True):
        root = logging.getLogger()
        capture = _ListHandler()
        capture.setFormatter(root.handlers[0].formatter)
        root.addHandler(capture)
        try:
            logging.getLogger(logger_name).log(level, message, extra=extra)
        finally:
            root.removeHandler(capture)
    return capture.lines


def _emit_json_with_extra(
    logger_name: str, level: int, message: str, extra: dict, log_level: str = "INFO"
) -> tuple[str, dict]:
    """`_emit_through_real_pipeline` with JSON output, returning (line, parsed)."""
    lines = _emit_through_real_pipeline(
        logger_name,
        level,
        message,
        extra=extra,
        json_logs=True,
        log_level=log_level,
    )
    assert len(lines) == 1
    return lines[0], json.loads(lines[0])


def test_httpx_info_request_line_never_reaches_the_handler():
    """Finding 1: the routine per-request INFO line is silenced outright.

    httpx's own message is exactly this shape (`%s`-style args pre-merged by
    `record.getMessage()` before the record ever reaches our chain).
    """
    message = f'HTTP Request: GET {_ARCGIS_URL} "HTTP/1.1 200 OK"'
    lines = _emit_through_real_pipeline("httpx", logging.INFO, message)

    assert lines == []
    assert _TOKEN not in "".join(lines)


def test_httpx_warning_request_line_is_delivered_but_redacted():
    """A WARNING-or-above httpx record still reaches logs, minus the token.

    Silencing httpx to WARNING (finding 1's primary fix) must not become the
    only defense — an httpx warning (e.g. a retry log) carries the same URL
    shape, so the event-string scrub is the backstop this test pins.

    fix(#1746 codex r6): the query is now redacted WHOLE (`?<redacted>`)
    whenever it carries any credential, not just the token's value -- see
    `_redact_url_match()` for why a partial parse is not trustworthy enough
    to leave the rest of the query in place. `"token="` itself no longer
    survives here; the host and path do.
    """
    message = f'HTTP Request: GET {_ARCGIS_URL} "HTTP/1.1 200 OK"'
    lines = _emit_through_real_pipeline("httpx", logging.WARNING, message)

    assert len(lines) == 1
    assert _TOKEN not in lines[0]
    assert "?<redacted>" in lines[0]
    assert "services6.arcgis.com/x/FeatureServer/0" in lines[0]
    assert "HTTP Request: GET" in lines[0]
    assert '"HTTP/1.1 200 OK"' in lines[0]


def test_httpx_warning_userinfo_credential_is_redacted():
    """Codex round 5 P1: a userinfo credential the whole-event gate missed.

    `has_url_credentials()` (round 2's gate, since replaced) parses the
    WHOLE event as one URL, and a sentence like `HTTP Request: GET
    https://user:SECRET@host/path "HTTP/1.1 200 OK"` does not parse as a URL
    on its own -- the surrounding prose breaks `urlsplit`, so the gate
    returned False and the credential went out untouched. Round 5 matches
    `URL_LIKE_RE` first and redacts each matched URL individually, which
    finds the userinfo the whole-event parse missed.
    """
    secret_url = f"https://user:{_TOKEN}@example.com/path"
    message = f'HTTP Request: GET {secret_url} "HTTP/1.1 200 OK"'
    assert f"user:{_TOKEN}@" in message  # pin the premise before redacting it

    lines = _emit_through_real_pipeline("httpx", logging.WARNING, message)

    assert len(lines) == 1
    assert _TOKEN not in lines[0]
    assert "redacted@" in lines[0]


def test_httpx_warning_query_credential_with_hash_is_fully_redacted():
    """Codex round 6 P1: an un-escaped `#` in a token value breaks the parse.

    The token/source validators only reject whitespace/control characters,
    so a value containing `#` is reachable. `urlsplit` reads `#` as the
    start of a URL fragment, which query redaction never inspects, so
    `redact_url_credentials()` alone left everything after the `#` -- the
    bulk of the secret -- untouched. `_redact_url_match()` now escalates to
    redacting the whole query once the ORIGINAL query is known to carry a
    credential, so the host and path stay legible but the query does not.
    """
    secret_url = (
        f"https://services6.arcgis.com/x/FeatureServer/0?f=json&token=#{_TOKEN}"
    )
    message = f'HTTP Request: GET {secret_url} "HTTP/1.1 200 OK"'
    assert _TOKEN in message  # pin the premise before redacting it

    lines = _emit_through_real_pipeline("httpx", logging.WARNING, message)

    assert len(lines) == 1
    assert _TOKEN not in lines[0]
    assert "services6.arcgis.com/x/FeatureServer/0" in lines[0]
    assert '"HTTP/1.1 200 OK"' in lines[0]


def test_httpx_warning_query_credential_with_ampersand_is_fully_redacted():
    """Codex round 6 P1: an un-escaped `&` in a token value breaks the parse.

    `parse_qsl` reads an un-escaped `&` inside a token value as the START of
    a NEW query parameter -- a bare name with no `=`, which matches no
    known-sensitive key, so the tail of the secret survived as an
    unredacted "parameter". Same escalation as the `#` case above.
    """
    secret_url = f"https://services6.arcgis.com/x/FeatureServer/0?token=abc&{_TOKEN}"
    message = f'HTTP Request: GET {secret_url} "HTTP/1.1 200 OK"'
    assert _TOKEN in message  # pin the premise before redacting it

    lines = _emit_through_real_pipeline("httpx", logging.WARNING, message)

    assert len(lines) == 1
    assert _TOKEN not in lines[0]
    assert "services6.arcgis.com/x/FeatureServer/0" in lines[0]
    assert '"HTTP/1.1 200 OK"' in lines[0]


def test_httpx_warning_query_without_a_credential_is_left_intact():
    """The round 6 escalation must not fire for a query with no credential.

    `where=1%3D1` is a plain (non-credential) query parameter; nothing here
    should trip `query_has_credentials()`, so the query survives whole.
    """
    plain_url = "https://services6.arcgis.com/x/FeatureServer/0?f=json&where=1%3D1"
    message = f'HTTP Request: GET {plain_url} "HTTP/1.1 200 OK"'

    lines = _emit_through_real_pipeline("httpx", logging.WARNING, message)

    assert len(lines) == 1
    assert plain_url in lines[0]


def test_httpx_warning_percent_encoded_reserved_chars_are_fully_redacted():
    """Codex round 7: the OTHER half of the fix.

    Once the ArcGIS adapter percent-encodes a token before concatenating it
    into a URL (`adapters/arcgis.py`, `quote(token, safe="")`), the raw
    `'`/`#`/`&` a token could otherwise contain never reaches the log line
    at all. This pins that the existing whole-query redaction already
    covers the encoded form end-to-end: a percent-encoded token no longer
    ends the `URL_LIKE_RE` match early, so the match runs to the end of the
    URL and `query_has_credentials()` still sees the `token=` key.
    """
    secret_url = (
        "https://services6.arcgis.com/x/FeatureServer/0"
        "?f=json&token=AA%27%23%26ULTRASECRET"
    )
    message = f'HTTP Request: GET {secret_url} "HTTP/1.1 200 OK"'
    assert "ULTRASECRET" in message  # pin the premise before redacting it

    lines = _emit_through_real_pipeline("httpx", logging.WARNING, message)

    assert len(lines) == 1
    assert "ULTRASECRET" not in lines[0]
    assert "?<redacted>" in lines[0]


def test_procrastinate_worker_task_kwargs_token_is_redacted():
    """Finding 13: a credential-store token survives inside `Job.call_string`.

    Built from a REAL `procrastinate.jobs.Job`, mirroring
    `procrastinate/worker.py:285`'s `f"Starting job {job.call_string}"`
    exactly, so this test breaks if Procrastinate ever changes how it
    renders `task_kwargs` rather than silently staying green against a
    hand-typed guess. `call_string` renders each kwarg as `key=value!r` —
    NOT a dict repr — so the token sits next to a `credential_ref` field
    that must stay visible for operators debugging a stuck job.
    """
    job = Job(
        id=1270,
        queue="default",
        lock=None,
        queueing_lock=None,
        task_name="ingest_service",
        task_kwargs={
            "token": _TOKEN,
            "credential_ref": None,
            "dataset_id": "abc",
        },
    )
    message = f"Starting job {job.call_string}"
    assert f"token='{_TOKEN}'" in message  # pin the premise before redacting it

    lines = _emit_through_real_pipeline("procrastinate.worker", logging.INFO, message)

    assert len(lines) == 1
    assert _TOKEN not in lines[0]
    assert "credential_ref=None" in lines[0]
    assert "dataset_id='abc'" in lines[0]


def test_procrastinate_worker_token_with_escaped_quotes_is_redacted():
    """Codex round 3 P1: a token containing both quote styles survives `repr()`.

    `repr()` of a string with BOTH a single and a double quote in it picks
    one quote character as the delimiter and ESCAPES that character where it
    recurs in the value (and always escapes a literal backslash), e.g.
    `repr("pre'SECRET\"post")` is `'pre\'SECRET"post'`. A lazy `.*?` value
    match stops at that escaped delimiter instead of the real closing quote,
    leaving the rest of the token in the log. ArcGIS tokens only pass a weak
    validator, so a value shaped like this is reachable. Built from a REAL
    `Job.call_string`, with a backslash in the value as well, so both escape
    forms `_TOKEN_VALUE_RE` has to consume are exercised together.
    """
    tricky_token = "pre'" + _TOKEN + '"post\\end'
    job = Job(
        id=1270,
        queue="default",
        lock=None,
        queueing_lock=None,
        task_name="ingest_service",
        task_kwargs={
            "token": tricky_token,
            "credential_ref": None,
            "dataset_id": "abc",
        },
    )
    message = f"Starting job {job.call_string}"
    assert _TOKEN in message  # pin the premise before redacting it

    lines = _emit_through_real_pipeline("procrastinate.worker", logging.INFO, message)

    assert len(lines) == 1
    assert _TOKEN not in lines[0]
    assert "credential_ref=None" in lines[0]
    assert "dataset_id='abc'" in lines[0]


def test_event_without_a_credential_url_is_never_mangled():
    """Codex round 2 P2, mechanism updated in round 5.

    `redact_url_credentials()`'s `_URLSPLIT_STRIPS` step deletes
    `\t`/`\r`/`\n` unconditionally -- correct for a string already known to
    be URL-shaped, wrong for an arbitrary log `event`. Round 2 gated the
    whole-event call on `has_url_credentials()`; round 5 replaced that with
    matching `URL_LIKE_RE` and redacting each match, which keeps this
    property for a different reason: a message with no URL-shaped substring
    at all has nothing for `URL_LIKE_RE` to match, so it is never handed to
    `redact_url_credentials()` in the first place and survives byte-for-byte.
    """
    message = "first line\nsecond\tline"
    assert URL_LIKE_RE.search(message) is None  # pin the premise: no URL at all

    lines = _emit_through_real_pipeline("procrastinate.worker", logging.INFO, message)

    assert len(lines) == 1
    assert message in lines[0]


def test_multiline_event_with_a_credential_url_still_gets_the_token_scrubbed():
    """A credential URL embedded in a multi-line message is still caught.

    Round 2 accepted flattening the WHOLE message here, because the old
    whole-event gate could only call `redact_url_credentials()` on
    everything or nothing. Round 5's per-`URL_LIKE_RE`-match redaction
    removes that trade-off entirely: `URL_LIKE_RE`'s character class already
    excludes whitespace, so the matched URL substring can never contain the
    leading `\n`, and text outside the match is never touched at all. Both
    the token and the newline are asserted now -- neither has to be given up
    for the other.
    """
    message = f'retrying request\nHTTP Request: GET {_ARCGIS_URL} "HTTP/1.1 200 OK"'
    assert URL_LIKE_RE.search(message) is not None  # pin the premise: a URL is there

    lines = _emit_through_real_pipeline(
        "procrastinate.worker", logging.WARNING, message
    )

    assert len(lines) == 1
    assert _TOKEN not in lines[0]
    assert "retrying request\n" in lines[0]


def test_redact_token_value_repr_also_handles_a_dict_repr_shape():
    """The dict-repr shape (`{'token': '...'}`) is a separate, real shape.

    Not how Procrastinate renders `task_kwargs` (see the test above), but a
    shape other code logs a raw dict as (`%r` on a plain dict, or a
    debug-only `logger.info(str(payload))`), so it stays covered directly on
    the helper rather than only through one caller's rendering choice.
    """
    text = f"payload: {{'token': '{_TOKEN}', 'credential_ref': None}}"

    redacted = _redact_token_value_repr(text)

    assert _TOKEN not in redacted
    assert "'token': '[REDACTED]'" in redacted
    assert "'credential_ref': None" in redacted


def test_redact_token_value_repr_handles_a_dict_repr_escaped_quote():
    """The dict-repr branch needs the same escape-consuming fix as the keyword one.

    `repr()` of a token with both quote styles in it escapes the delimiter
    quote inside the value, so a bare lazy `.*?` would stop early here too.
    """
    tricky_token = "pre'" + _TOKEN + '"post\\end'
    text = f"payload: {{'token': {tricky_token!r}, 'credential_ref': None}}"
    assert _TOKEN in text  # pin the premise before redacting it

    redacted = _redact_token_value_repr(text)

    assert _TOKEN not in redacted
    assert "'token': '[REDACTED]'" in redacted
    assert "'credential_ref': None" in redacted


@pytest.mark.parametrize(
    ("log_level", "expected_httpx_level"),
    [
        ("ERROR", logging.ERROR),
        ("INFO", logging.WARNING),
        ("DEBUG", logging.WARNING),
    ],
)
def test_setup_logging_derives_httpx_floor_from_root(log_level, expected_httpx_level):
    """Codex round 8 P2: httpx's WARNING floor must track root, not override it.

    A FIXED WARNING silently reverses itself the moment root is raised past
    it: `LOG_LEVEL=ERROR` at boot (`app.core.config`) previously left httpx
    sitting AT WARNING -- more verbose than the deployment asked for.
    `apply_http_logger_levels()` makes WARNING a floor rather than a fixed
    point: root stricter than WARNING (ERROR here) raises httpx to match;
    root laxer than WARNING (INFO, DEBUG) leaves httpx pinned at WARNING.
    """
    with configured_logging(json_logs=False, log_level=log_level, production=True):
        assert logging.getLogger("httpx").level == expected_httpx_level
        assert logging.getLogger("httpcore").level == expected_httpx_level


def test_redact_token_value_repr_stays_linear_on_unterminated_input():
    """Codex round 4 P2: the two value-body alternatives must not overlap.

    `(?:\\.|.)*?` let `.` also match a backslash, so an unterminated
    `token='` followed by N backslashes had N different ways to split into
    `\\.` pairs versus lone `.` characters -- and the regex engine tried all
    of them before concluding there is no closing quote, which is
    exponential in N. That ran synchronously on every log record, so
    malformed third-party error text (no code here has to intend it) could
    stall the whole process. `[^\\]` in place of the second `.` makes the
    two alternatives partition the input instead of overlapping it: for any
    given position there is exactly one alternative that can consume it, so
    an unterminated match now fails in time linear in the input length.

    200 backslashes is comfortably past the ~34 where the old pattern's
    runtime was already visible in a manual timing check; a generous 1
    second bound is asserted so this fails loudly (not by hanging) if the
    linear property regresses.
    """
    message = "token='" + "\\" * 200

    start = time.perf_counter()
    redacted = _redact_token_value_repr(message)
    elapsed = time.perf_counter() - start

    assert elapsed < 1.0, f"took {elapsed:.3f}s -- no longer linear"
    assert redacted == message  # no closing quote: nothing to redact, unchanged


def _emit_exception_through_real_pipeline(exc: Exception) -> tuple[str, dict]:
    """Raise/catch *exc*, log it with `exc_info=True` through the real
    JSON/production pipeline, and return (captured line, parsed JSON dict).

    Uses the same capturing-handler approach as `_emit_through_real_pipeline`
    above, but with `exc_info=True` so `format_exc_info` actually renders an
    `exception` field, and `json_logs=True` so the captured line is parseable
    JSON rather than an ANSI-colored console line.
    """
    with configured_logging(json_logs=True, log_level="INFO", production=True):
        root = logging.getLogger()
        capture = _ListHandler()
        capture.setFormatter(root.handlers[0].formatter)
        root.addHandler(capture)
        try:
            try:
                raise exc
            except type(exc):
                logging.getLogger("test.exception_scrub").error("boom", exc_info=True)
        finally:
            root.removeHandler(capture)
    assert len(capture.lines) == 1
    return capture.lines[0], json.loads(capture.lines[0])


def test_exception_field_url_credential_is_scrubbed():
    """Codex round 9 P1: `format_exc_info` ran AFTER the redactor.

    `_redact_sensitive_fields` only ever saw `event`; `format_exc_info` was
    appended to the chain AFTER it (only when `json_logs or production`), so
    the `exception` string it renders -- which can itself quote a credential,
    e.g. `httpx.HTTPStatusError`'s message quoting the failing request URL --
    was created after redaction and reached JSON/production logs verbatim.
    `format_exc_info` now runs before `_redact_sensitive_fields`, so
    `exception` exists as a plain string in time to be scrubbed the same way
    `event` always was.
    """
    exc = ValueError(f"request failed: {_ARCGIS_URL}")
    assert _TOKEN in str(exc)  # pin the premise before redacting it

    line, data = _emit_exception_through_real_pipeline(exc)

    assert _TOKEN not in line
    assert "ValueError" in data["exception"]
    assert "?<redacted>" in data["exception"]


def test_exception_field_keyword_form_token_is_scrubbed():
    """Same fix, the keyword-rendered token shape (finding 13's shape).

    An exception raised while handling a credential-store token can just as
    easily quote it back in a `key=value!r` shape as Procrastinate's worker
    does -- the same `_scrub_text()` now applied to `event` and `exception`
    catches both shapes either way.
    """
    exc = ValueError(f"job failed with kwargs token='{_TOKEN}'")
    assert _TOKEN in str(exc)  # pin the premise before redacting it

    line, data = _emit_exception_through_real_pipeline(exc)

    assert _TOKEN not in line
    assert "ValueError" in data["exception"]
    assert "token='[REDACTED]'" in data["exception"]


def _raise_with_secret_local() -> None:
    secret = _TOKEN  # noqa: F841 -- deliberately unused; must never leak via locals rendering
    raise ValueError(f"request failed: {_ARCGIS_URL}")


def test_dev_console_exception_is_scrubbed_and_has_no_locals():
    """Codex round 10 P1: dev console mode leaked a token two different ways.

    Round 9 only fixed the JSON/production path: `format_exc_info` stayed
    conditional on `json_logs or production`, so in pure dev mode `exc_info`
    was still a raw tuple when `_redact_sensitive_fields` ran -- nothing to
    scrub yet -- and only got rendered afterward, by the console renderer,
    unscrubbed. Rich's own locals rendering was a SECOND, independent leak on
    top of that: even a scrubbed message would not have stopped a `secret`
    local variable from appearing verbatim, since `RichTracebackFormatter`
    prints every frame local's `repr()` regardless of what the message says.
    Both are closed now: `format_exc_info` runs unconditionally (so
    `exception` exists, scrubbed, before ANY renderer runs), and dev's
    renderer is `plain_traceback`, which never touches locals at all.
    """
    with configured_logging(json_logs=False, production=False, log_level="INFO"):
        root = logging.getLogger()
        capture = _ListHandler()
        capture.setFormatter(root.handlers[0].formatter)
        root.addHandler(capture)
        try:
            try:
                _raise_with_secret_local()
            except ValueError:
                logging.getLogger("test.dev_exception_scrub").error(
                    "boom", exc_info=True
                )
        finally:
            root.removeHandler(capture)

    assert len(capture.lines) == 1
    out = capture.lines[0]
    assert "ValueError" in out
    assert "?<redacted>" in out
    assert _TOKEN not in out


def test_httpx_warning_apostrophe_in_url_path_still_redacts_the_query():
    """Codex round 11 P1: URL_LIKE_RE's own match can hide the query from it.

    `URL_LIKE_RE`'s character class excludes `'`/`"`/`<`/`>` and whitespace,
    so a base URL with an apostrophe in its PATH -- accepted by validators
    that only reject whitespace/control characters, and kept literal by
    httpx -- makes the match stop BEFORE the query ever starts.
    `_redact_url_match()` then never runs on the real query at all, and
    `?token=...` survives untouched even though the token itself is
    perfectly well-formed. `_QUERY_TAIL_RE` in `_scrub_text()` finds the
    query independently of whether `URL_LIKE_RE` matched through it.
    """
    message = f'HTTP Request: GET {_APOSTROPHE_URL} "HTTP/1.1 200 OK"'
    assert _TOKEN in message  # pin the premise before redacting it

    lines = _emit_through_real_pipeline("httpx", logging.WARNING, message)

    assert len(lines) == 1
    assert _TOKEN not in lines[0]
    assert "?<redacted>" in lines[0]
    assert '"HTTP/1.1 200 OK"' in lines[0]


def test_exception_field_apostrophe_in_url_path_still_redacts_the_query():
    """Same gap, in a rendered exception message through the JSON pipeline.

    `_scrub_text()` is shared between `event` and `exception`, so the fix
    above covers both without a second implementation.
    """
    exc = ValueError(f"request failed: {_APOSTROPHE_URL}")
    assert _TOKEN in str(exc)  # pin the premise before redacting it

    line, data = _emit_exception_through_real_pipeline(exc)

    assert _TOKEN not in line
    assert "ValueError" in data["exception"]
    assert "?<redacted>" in data["exception"]


def test_scrub_text_leaves_a_non_credential_query_unchanged():
    """The new `_QUERY_TAIL_RE` pass must not fire on an ordinary query.

    `where=1%3D1` carries no credential-shaped parameter, so nothing here
    should trip `query_has_credentials()` either directly or with `#`
    treated as `&`.
    """
    text = "GET https://host/path?f=json&where=1%3D1 done"

    assert _scrub_text(text) == text


def test_scrub_text_leaves_a_bare_question_mark_in_prose_unchanged():
    """A `?` with nothing credential-shaped after it is just punctuation."""
    text = "are we done? yes, all set"

    assert _scrub_text(text) == text


def _worker_log_extra(job: Job, action: str) -> dict:
    """The `extra` mapping Procrastinate's worker actually attaches to a record.

    Mirrors `procrastinate/worker.py`'s `Worker._log_extra()` (pinned
    procrastinate 3.9.0): an `action`, a `worker` dict, and `job` set to
    `context.job.log_context()`. `log_context()` is the load-bearing part and
    is called for real here rather than hand-typed, so this breaks if
    Procrastinate ever changes what it puts in there instead of silently
    staying green against a guess.
    """
    return {
        "action": action,
        "worker": {
            "name": "worker-0",
            "worker_id": 0,
            "job_id": job.id,
            "queues": ["ingest"],
        },
        "job": job.log_context(),
    }


def _authenticated_service_job() -> Job:
    """A job shaped like the ones the default install actually queues.

    `credential_store_available()` is False whenever `REDIS_URL` is unset --
    which is how `.env.example` ships -- so `resolve_dispatch_credential()`
    returns the raw wire credential and it crosses the queue as the `token`
    kwarg of every authenticated service import and reupload.
    """
    return Job(
        id=1270,
        queue="ingest",
        lock=None,
        queueing_lock=None,
        task_name="ingest_service",
        task_kwargs={
            "job_id": "abc",
            "token": _BASIC_LINE,
            "credential_ref": _CREDENTIAL_REF,
            "dataset_id": "d-42",
        },
    )


# Every spelling of the throwaway credential that must not survive the
# pipeline: the finished header line, the base64 blob inside it, and the two
# cleartext halves an origin's own error text would name ("authentication
# failed for user AAAAAAAAA"). The store reference joins them because it is
# redeemable too.
_JOB_CREDENTIAL_SPELLINGS = (
    _BASIC_LINE,
    _BASIC_BLOB,
    _BASIC_USER,
    _BASIC_SECRET,
    _CREDENTIAL_REF,
)

# The three records `procrastinate/worker.py` emits per job, with the level and
# message text each one really uses: `_process_job()`'s DEBUG "Loaded job info"
# and INFO "Starting job", and `_log_job_outcome()`'s outcome line.
_WORKER_JOB_RECORDS = (
    ("loaded_job_info", logging.DEBUG, "Loaded job info, about to start job {call}"),
    ("start_job", logging.INFO, "Starting job {call}"),
    ("job_error", logging.ERROR, "Job {call} ended with status: Error, lasted 1.000 s"),
)


@pytest.mark.parametrize(
    ("action", "level", "template"),
    _WORKER_JOB_RECORDS,
    ids=[record[0] for record in _WORKER_JOB_RECORDS],
)
def test_worker_job_context_never_carries_a_credential(action, level, template):
    """fix(#1844): the structured half of every worker job line.

    #1746 scrubbed the `event` STRING of exactly these three records and
    stopped there, because `_redact_sensitive_fields` only looked at top-level
    keys and no test in this file ever passed an `extra=`. The worker's
    `extra["job"]` is `Job.log_context()`, which carries `task_kwargs`
    verbatim AND a second rendered copy in `call_string`, so the credential
    went out twice per line, at INFO, before the task body ran -- early enough
    that nothing the task does about its own log context can help.
    """
    job = _authenticated_service_job()
    extra = _worker_log_extra(job, action)
    message = template.format(call=job.call_string)

    # Pin the premise: the credential really is in this record, in both halves,
    # before the pipeline sees it.
    assert _BASIC_LINE in message
    assert extra["job"]["task_kwargs"]["token"] == _BASIC_LINE
    assert _BASIC_LINE in extra["job"]["call_string"]

    line, data = _emit_json_with_extra(
        "procrastinate.worker", level, message, extra, log_level="DEBUG"
    )

    for spelling in _JOB_CREDENTIAL_SPELLINGS:
        assert spelling not in line, spelling
    assert data["job"]["task_kwargs"]["token"] == "[REDACTED]"
    assert data["job"]["task_kwargs"]["credential_ref"] == "[REDACTED]"
    assert "[REDACTED]" in data["job"]["call_string"]
    assert "[REDACTED]" in data["event"]
    # The non-secret kwargs an operator debugging a stuck job actually needs
    # are untouched, in both the structured copy and the rendered one.
    assert data["job"]["task_kwargs"]["dataset_id"] == "d-42"
    assert data["job"]["task_name"] == "ingest_service"
    assert "dataset_id='d-42'" in data["job"]["call_string"]
    assert data["action"] == action


def test_an_extra_container_reaches_the_rendered_line_at_all():
    """Positive control for the assertions above.

    Every one of them is an ABSENCE claim, and an absence claim passes
    vacuously if `extra` never reaches the output in the first place -- a
    dropped record, an `ExtraAdder` that is not in the chain, a renderer that
    ignores unknown fields. This pins the opposite: a container under a
    non-sensitive key, holding a string with no credential shape, arrives
    whole.
    """
    extra = {"job": {"task_kwargs": {"dataset_id": "d-42"}, "attempts": 3}}

    _, data = _emit_json_with_extra("procrastinate.worker", logging.INFO, "hi", extra)

    assert data["job"] == {"task_kwargs": {"dataset_id": "d-42"}, "attempts": 3}


def test_the_same_job_context_leaks_through_a_shallow_key_pass():
    """Positive control on the MECHANISM, not just on delivery.

    Shows what the shallow pass this fix replaced would have emitted for the
    identical record: a top-level key-only walk leaves `job` untouched, so
    both copies of the credential survive. Written against the real
    `log_context()` so it measures the payload the worker sends rather than a
    restatement of the fix.
    """
    job = _authenticated_service_job()
    event_dict = dict(_worker_log_extra(job, "start_job"))
    event_dict["event"] = f"Starting job {job.call_string}"

    shallow = {
        key: ("[REDACTED]" if key.lower() in _SENSITIVE_FIELDS else value)
        for key, value in event_dict.items()
    }

    assert shallow["job"]["task_kwargs"]["token"] == _BASIC_LINE
    assert _BASIC_BLOB in shallow["job"]["call_string"]


def test_credential_ref_absence_stays_distinguishable_from_a_real_ref():
    """Redacting a ref must not cost the operator the one bit they need.

    "Did this job carry a credential at all" is the question a stuck-job
    triage actually asks, and `Job.call_string` renders `None` UNQUOTED. The
    rendered-value scrub only touches a QUOTED value, so absence still reads
    as `credential_ref=None` while a real ref reads as `[REDACTED]`.
    """
    job = Job(
        id=1271,
        queue="ingest",
        lock=None,
        queueing_lock=None,
        task_name="ingest_service",
        task_kwargs={"job_id": "abc", "token": None, "credential_ref": None},
    )
    extra = _worker_log_extra(job, "start_job")

    _, data = _emit_json_with_extra(
        "procrastinate.worker", logging.INFO, f"Starting job {job.call_string}", extra
    )

    assert "credential_ref=None" in data["job"]["call_string"]
    assert "credential_ref=None" in data["event"]


def test_nested_url_credential_in_an_extra_is_scrubbed():
    """The deep walk scrubs nested STRINGS, not only denylisted keys.

    A credential does not have to sit under a name the denylist knows.
    `call_string` is the case that matters in production -- a rendered copy of
    the kwargs, under a key that is not sensitive -- and this pins the same
    behaviour for the other shape a nested string can carry, a URL with a
    credential query. Key redaction cannot reach either one.
    """
    extra = {"job": {"detail": f"GET {_ARCGIS_URL} failed", "attempts": 1}}

    line, data = _emit_json_with_extra(
        "procrastinate.worker", logging.INFO, "outcome", extra
    )

    assert _TOKEN not in line
    # fix(#1844 audit round 1): compare the host EXACTLY, and the string as a
    # whole, rather than asserting the hostname is a substring of the scrubbed
    # detail. `"services6.arcgis.com" in <text>` is satisfied by
    # `services6.arcgis.com.evil.test` too, so as an assertion about a URL it
    # says less than it looks like it says -- and CodeQL flags the shape
    # (py/incomplete-url-substring-sanitization) whether or not the particular
    # use is a sanitiser. Deriving the expectation from `_ARCGIS_URL` keeps it
    # in step with the constant.
    scrubbed = data["job"]["detail"].removeprefix("GET ").removesuffix(" failed")
    assert urlsplit(scrubbed).hostname == "services6.arcgis.com"
    assert scrubbed == f"{_ARCGIS_URL.partition('?')[0]}?<redacted>"


def test_a_flat_record_is_left_alone_by_the_deep_walk():
    """The walk is gated on the value being a container.

    Over-redaction destroys log usefulness, and this is the hot path: every
    request-path line is flat. Scalars under non-sensitive keys must come
    through exactly as they went in.
    """
    extra = {"job_id": "abc", "task": "ingest_vrt", "attempts": 2, "ok": True}

    _, data = _emit_json_with_extra("app.worker", logging.INFO, "flat", extra)

    for key, value in extra.items():
        assert data[key] == value


# fix(#1857 item 9): exercised through the real pipeline rather than by
# calling redact_nested, because the processor decides whether to walk at all:
# a shape can be walkable and still never be handed to the walk.


@dataclasses.dataclass
class _JobContext:
    """A settings-shaped object of the kind a library hands to `extra`."""

    job_id: str
    token: str


@dataclasses.dataclass(slots=True)
class _SlottedContext:
    """The same, with no `__dict__` at all."""

    token: str


@pytest.mark.parametrize(
    "container",
    [
        pytest.param(lambda v: frozenset({v}), id="frozenset"),
        pytest.param(lambda v: deque([v]), id="deque"),
        pytest.param(lambda v: {"inner": frozenset({v})}, id="frozenset-nested"),
        pytest.param(lambda v: deque([{"secret": v}]), id="deque-of-mapping"),
    ],
)
def test_a_credential_inside_an_unwalked_container_is_scrubbed(container):
    """`frozenset` is not a `set` and `deque` is not a `list`.

    The nested variants matter separately: the gate decides whether the
    top-level value is walked, so a frozenset arrives both ways.
    """
    url = f"https://example.test/api?token={_TOKEN}"

    line, _data = _emit_json_with_extra(
        "app.worker", logging.INFO, "container", {"payload": container(url)}
    )

    assert _TOKEN not in line, line


def test_a_dataclass_in_extra_is_walked_by_field():
    """The shape a library is most likely to hand to `extra`.

    Reading it through `dataclasses.fields` puts the field NAMES through the
    denylist a mapping's keys go through, which is what redacts `token`.
    """
    line, data = _emit_json_with_extra(
        "app.worker",
        logging.INFO,
        "context",
        {"ctx": _JobContext(job_id="abc", token=_TOKEN)},
    )

    assert _TOKEN not in line, line
    assert data["ctx"]["job_id"] == "abc"
    assert data["ctx"]["token"] == "[REDACTED]"


def test_a_slotted_dataclass_is_walked_too():
    """`slots=True` leaves no `__dict__`, which is the reason for `fields()`.

    Reading `__dict__` raises here, and the guard would turn the whole payload
    into `[UNREDACTABLE]` on a shape that is perfectly readable.
    """
    line, data = _emit_json_with_extra(
        "app.worker", logging.INFO, "slotted", {"ctx": _SlottedContext(token=_TOKEN)}
    )

    assert _TOKEN not in line, line
    assert data["ctx"]["token"] == "[REDACTED]"


def test_a_dataclass_CLASS_is_not_mistaken_for_an_instance():
    """`dataclasses.is_dataclass` answers True for the class object too.

    Walking one yields a dict of defaults that reads like logged data.
    """
    from app.core.logging_config import _is_dataclass_instance, _is_walkable

    assert _is_dataclass_instance(_JobContext(job_id="a", token="b"))
    assert not _is_dataclass_instance(_JobContext)
    assert not _is_walkable(_JobContext)


def test_the_walk_and_the_gate_agree_on_what_is_walkable():
    """One membership test, not two.

    A type in the walk's list but not the gate's is walkable and never walked.
    """
    from app.core.logging_config import _ITERABLE_CONTAINERS, _is_walkable

    for container_type in _ITERABLE_CONTAINERS:
        assert _is_walkable(container_type()), container_type
    assert _is_walkable({})


def test_a_cyclic_extra_terminates():
    """`extra` is third-party input, so the walk must not trust its shape.

    Procrastinate builds a plain JSON-able dict today, but the processor runs
    on whatever any library puts in `extra`. `redact_nested()`'s depth ceiling
    is what makes a self-referencing structure terminate; without it this
    hangs the logging call on the event loop rather than raising.
    """
    cyclic: dict = {"name": "loop"}
    cyclic["self"] = cyclic

    started = time.monotonic()
    _, data = _emit_json_with_extra(
        "app.worker", logging.INFO, "cycle", {"payload": cyclic}
    )

    assert time.monotonic() - started < 5
    assert "[TRUNCATED]" in json.dumps(data["payload"])


def test_repr_scrub_covers_every_denylisted_name():
    """fix(#1844 audit round 1): the key pass and the text pass must agree.

    The first cut of the rendered-value scrub knew `token` and
    `credential_ref` -- 2 of the 14 denylisted names -- so the other 12 were
    redacted as keys and then emitted verbatim in the `call_string` rendering
    beside them. That is the same key-pass/text-pass asymmetry that produced
    this PR's own finding, one level down. Pinning the two sets equal is what
    keeps adding a name to the denylist from covering only half a record.
    """
    assert set(_REDACTED_REPR_NAMES) == _SENSITIVE_FIELDS


@pytest.mark.parametrize("name", sorted(_SENSITIVE_FIELDS))
def test_every_denylisted_name_is_redacted_in_both_rendered_shapes(name):
    """Each denylisted name, in the kwarg shape and the dict-repr shape.

    Not a restatement of the set equality above: this exercises the compiled
    alternation, so a name the set contains but the regex cannot actually
    match (an unescaped metacharacter, a boundary that never falls where the
    name starts) fails here rather than passing on the set comparison alone.
    """
    kwarg = _scrub_text(f"call({name}='ULTRASECRET')")
    mapping = _scrub_text(f"{{'{name}': 'ULTRASECRET'}}")

    assert "ULTRASECRET" not in kwarg, kwarg
    assert "ULTRASECRET" not in mapping, mapping


def test_rendered_names_are_matched_case_insensitively():
    """The key pass has always compared `key.lower()`; the text pass now does too.

    `Token='...'` reaches a log line exactly as readily as `token='...'` --
    third-party code picks the casing -- and a case-sensitive text pass would
    reopen the same asymmetry in a narrower form.
    """
    assert "ULTRASECRET" not in _scrub_text("call(Token='ULTRASECRET')")
    assert "ULTRASECRET" not in _scrub_text("call(API_KEY='ULTRASECRET')")


def test_a_sub_word_name_is_still_left_alone():
    """Positive control for the two tests above.

    They are absence claims, and a scrub that simply redacted every quoted
    value would satisfy both. The word-boundary rule that keeps `token_hint`
    legible has to survive the switch to the full denylist.
    """
    text = "call(token_hint='ab', credential_reference='keepme')"

    assert _scrub_text(text) == text


def test_worker_job_context_is_redacted_in_the_console_renderer_too():
    """The JSON assertions have a console twin, because dev and prod differ.

    `setup_logging()` picks `ConsoleRenderer` when `json_logs` is false, and
    that renderer reaches the containers by a different path -- `repr()` of
    the already-walked structure rather than `json.dumps`. A fix verified only
    against the JSON renderer would be unverified for every self-hoster
    running the default console output.
    """
    job = _authenticated_service_job()
    extra = _worker_log_extra(job, "start_job")

    lines = _emit_through_real_pipeline(
        "procrastinate.worker",
        logging.INFO,
        f"Starting job {job.call_string}",
        extra=extra,
    )

    assert len(lines) == 1
    for spelling in _JOB_CREDENTIAL_SPELLINGS:
        assert spelling not in lines[0], spelling
    assert "[REDACTED]" in lines[0]
    # Positive control: the container really is rendered into this line, so the
    # absence assertions above are not passing on a dropped field.
    assert "dataset_id" in lines[0]


def test_a_container_that_raises_costs_the_payload_and_not_the_line():
    """fix(#1844 audit round 1): `extra` is third-party input all the way down.

    `redact_nested()` calls `.items()` on objects this module never built. A
    lazy Mapping that raises there would take the exception out through the
    processor chain and cost the entire record -- during an incident, on a
    line someone put a credential in. The payload is dropped instead.
    """

    class _Exploding(Mapping):
        def __iter__(self):
            raise RuntimeError("boom")

        def __len__(self):
            return 1

        def __getitem__(self, key):
            raise RuntimeError("boom")

    _, data = _emit_json_with_extra(
        "app.worker", logging.INFO, "hostile", {"payload": _Exploding()}
    )

    assert data["payload"] == "[UNREDACTABLE]"
    assert data["event"] == "hostile"
