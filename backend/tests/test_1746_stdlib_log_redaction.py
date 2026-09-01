"""fix(#1746): stdlib log records must not leak service tokens (findings 1, 13).

httpx (and its httpcore transport) logs the full outgoing request URL at INFO
for every call, e.g. ``HTTP Request: GET <url>?f=json&token=<value> "HTTP/1.1
200 OK"``. That line reaches every deployment's logs by default, because root
defaults to INFO (``app.core.config``), and it fires twice per refresh on the
credential-store path (finding 13). Procrastinate's worker separately logs a
dict-repr of ``task_kwargs`` (``Starting job x[1]({'token': '...'})``), which
puts a token inside the MESSAGE STRING rather than a keyed field, so the
existing key-based ``_redact_sensitive_fields`` processor cannot see it
either way.

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

import pytest

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


def test_procrastinate_worker_dict_repr_token_is_redacted():
    """Finding 13: a credential-store token survives inside a dict repr.

    Procrastinate's worker renders `task_kwargs` with Python's dict repr
    (`Job.call_string`), so the token sits inside free text next to a
    `credential_ref` field that must stay visible for operators debugging a
    stuck job.
    """
    message = (
        "Starting job "
        f"ingest_service[1270]({{'token': '{_TOKEN}', 'credential_ref': None}})"
    )
    lines = _emit_through_real_pipeline("procrastinate.worker", logging.INFO, message)

    assert len(lines) == 1
    assert _TOKEN not in lines[0]
    assert "credential_ref" in lines[0]
    assert "None" in lines[0]
