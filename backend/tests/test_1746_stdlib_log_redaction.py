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

``tests/_logging_state.configured_logging()`` only saves and restores the
loggers ``setup_logging()`` is documented to mutate — root and the three
uvicorn loggers (see ``_logging_state.py``'s own docstring). httpx/httpcore
are outside that list, so this file restores their levels itself; otherwise
the first test below would leak a WARNING level into every later test in the
same worker.
"""

import logging
import time

import pytest
from procrastinate.jobs import Job

from app.core.logging_config import _redact_token_value_repr
from app.core.url_redaction import has_url_credentials
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
def _restore_httpx_logger_state():
    """Undo this file's own level change, and alembic's `fileConfig()`.

    `configured_logging()` only tracks the loggers `setup_logging()` is
    documented to mutate (see `_logging_state.py`'s own docstring), so it
    never restores httpx/httpcore's level -- without this, running this file
    would leave both pinned at WARNING for whatever test runs next on the
    same xdist worker.

    Separately: `alembic/env.py` calls `logging.config.fileConfig()` to run
    migrations, and that defaults to `disable_existing_loggers=True`, which
    disables every *already-registered* logger not named in alembic.ini's
    `[loggers]` section. By the time that runs, collection has already
    imported plenty of other test modules that import httpx, so the "httpx"
    logger object already exists and gets silently `.disabled = True` for
    the rest of the session -- independent of level, and independent of this
    file's own fix. Restoring the `disabled` flag too keeps this file
    exercising the real `setup_logging()` level change instead of that
    unrelated fixture's side effect.
    """
    loggers = [logging.getLogger(name) for name in ("httpx", "httpcore")]
    saved = [(lg.level, lg.disabled) for lg in loggers]
    for lg in loggers:
        lg.disabled = False
    yield
    for lg, (level, disabled) in zip(loggers, saved):
        lg.setLevel(level)
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
    """
    message = f'HTTP Request: GET {_ARCGIS_URL} "HTTP/1.1 200 OK"'
    lines = _emit_through_real_pipeline("httpx", logging.WARNING, message)

    assert len(lines) == 1
    assert _TOKEN not in lines[0]
    assert "token=" in lines[0]  # the field survives; only the value is scrubbed
    assert "HTTP Request: GET" in lines[0]


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
    """Codex round 2 P2: `redact_url_credentials()` must be gated, not blanket.

    That helper's `_URLSPLIT_STRIPS` step deletes `\t`/`\r`/`\n`
    unconditionally -- correct for a string already known to be URL-shaped,
    wrong for an arbitrary log `event`. `_redact_sensitive_fields` now calls
    it only when `has_url_credentials()` says the string actually carries a
    credential-shaped URL, so a plain multi-line / tab-delimited message with
    no credential in it survives byte-for-byte.
    """
    message = "first line\nsecond\tline"
    assert not has_url_credentials(message)  # pin the premise: nothing to redact

    lines = _emit_through_real_pipeline("procrastinate.worker", logging.INFO, message)

    assert len(lines) == 1
    assert message in lines[0]


def test_multiline_event_with_a_credential_url_still_gets_the_token_scrubbed():
    """A credential URL embedded in a multi-line message is still caught.

    Flattening the message is accepted here -- it DOES carry a credential, so
    running it through `redact_url_credentials()` is the right call. Only the
    no-credential case above is required to come back untouched.
    """
    message = f'retrying request\nHTTP Request: GET {_ARCGIS_URL} "HTTP/1.1 200 OK"'
    assert has_url_credentials(message)  # pin the premise before redacting it

    lines = _emit_through_real_pipeline(
        "procrastinate.worker", logging.WARNING, message
    )

    assert len(lines) == 1
    assert _TOKEN not in lines[0]


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
