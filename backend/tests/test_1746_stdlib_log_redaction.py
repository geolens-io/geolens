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
``_logging_state.py``'s own docstring). ``setup_logging()`` never touches
``.disabled`` though, so this file still restores that one flag itself; see
the autouse fixture below for why it needs to.
"""

import logging
import time

import pytest
from procrastinate.jobs import Job

from app.core.logging_config import _redact_token_value_repr
from app.core.url_redaction import URL_LIKE_RE
from tests._logging_state import configured_logging

_TOKEN = "SECRETTOKEN123"
_ARCGIS_URL = f"https://services6.arcgis.com/x/FeatureServer/0?f=json&token={_TOKEN}"


class _ListHandler(logging.Handler):
    """Captures the fully rendered line for every record it receives."""

    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(self.format(record))


@pytest.fixture(autouse=True)
def _restore_httpx_logger_disabled_flag():
    """Undo alembic's `fileConfig()` disabling the "httpx" logger.

    `_logging_state._MUTATED_LOGGERS` and `conftest._LOGGING_MUTATED_LOGGERS`
    now include "httpx"/"httpcore" (fix #1746 codex r5), so `level` -- what
    this fixture used to also save and restore -- is covered by
    `configured_logging()` and the autouse guard already. `.disabled` is not:
    neither snapshot reads or writes it, because `setup_logging()` itself
    never touches it, so it was never in scope for either.

    `alembic/env.py` calls `logging.config.fileConfig()` to run migrations,
    and that defaults to `disable_existing_loggers=True`, which disables
    every *already-registered* logger not named in alembic.ini's `[loggers]`
    section. By the time that runs, collection has already imported plenty
    of other test modules that import httpx, so the "httpx" logger object
    already exists and gets silently `.disabled = True` for the rest of the
    session -- independent of this file's own fix, and independent of
    `setup_logging()` entirely. Restoring the flag here keeps this file
    exercising the real fix instead of that unrelated side effect.
    """
    loggers = [logging.getLogger(name) for name in ("httpx", "httpcore")]
    saved = [lg.disabled for lg in loggers]
    for lg in loggers:
        lg.disabled = False
    yield
    for lg, disabled in zip(loggers, saved):
        lg.disabled = disabled


def _emit_through_real_pipeline(
    logger_name: str, level: int, message: str
) -> list[str]:
    """Run `setup_logging()` for real and capture what reaches the root logger.

    The capturing handler is given the SAME formatter `setup_logging()`
    installed (a `structlog.stdlib.ProcessorFormatter` whose
    `foreign_pre_chain` includes `_redact_sensitive_fields`), so redaction is
    exercised exactly as it runs in production rather than by calling the
    processor function directly.
    """
    with configured_logging(json_logs=False, log_level="INFO", production=True):
        root = logging.getLogger()
        capture = _ListHandler()
        capture.setFormatter(root.handlers[0].formatter)
        root.addHandler(capture)
        try:
            logging.getLogger(logger_name).log(level, message)
        finally:
            root.removeHandler(capture)
    return capture.lines


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
