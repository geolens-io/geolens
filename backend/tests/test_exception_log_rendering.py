"""fix(#1485): production exception logging must never reach rich.

`structlog.dev.ConsoleRenderer` picks `RichTracebackFormatter(show_locals=True)`
as its exception formatter whenever rich is importable, and rich is in the
backend's transitive dependency set. Rendering a frame's locals costs time
proportional to the `repr()` of each one, and rich's line splitting is
quadratic in the length of a single long line — so an exception raised with
SQLAlchemy objects in scope spent minutes of synchronous CPU inside the
logging call. That call happens on the event loop in the request path, and
the production compose default is one uvicorn worker, so the whole API was
unavailable for the duration.

These tests pin both halves of the fix: the production configuration cannot
route an exception through rich, and what it emits for an exception does not
depend on the size of any local variable. Measured on the middleware case
below, the same request went from 83,062 bytes of log output to 3,675.

Nothing here asserts on elapsed time. The property under test is that the
work is not proportional to local size, which the emitted record shows
directly.
"""

from __future__ import annotations

import logging
import sys
from io import StringIO

import pytest
import structlog

import app.api.middleware.logging as logging_mw
from tests._logging_state import configured_logging

# Appears only inside the repr of a frame local — never in an exception
# message, a source line, or a field name — so finding it in log output means
# locals were rendered.
_LOCALS_SENTINEL = "LOCALS_SHOULD_NOT_BE_RENDERED"

# Rich draws its traceback frames inside a box; the plain formatter cannot
# produce any of these.
_BOX_DRAWING = "╭╮╰╯│─"


class _FatRepr:
    """Stands in for a session or ORM instance: one enormous non-str repr.

    Deliberately neither a `str` nor a container, because those are the only
    two things `RichTracebackFormatter`'s `locals_max_string` and
    `locals_max_length` truncate. An arbitrary object's `repr()` is emitted
    whole, which is why those knobs are not a fix for this.
    """

    def __init__(self, repeats: int) -> None:
        self._repeats = repeats

    def __repr__(self) -> str:
        return f"<_FatRepr {_LOCALS_SENTINEL * self._repeats}>"


def _raise_with_fat_local(repeats: int = 200) -> None:
    _orm_ish = _FatRepr(repeats)
    raise ValueError("audit_details.date is not a date")


def _current_formatter() -> structlog.stdlib.ProcessorFormatter:
    """The ProcessorFormatter `setup_logging()` installed on the root handler."""
    formatter = logging.getLogger().handlers[0].formatter
    assert isinstance(formatter, structlog.stdlib.ProcessorFormatter)
    return formatter


def _processors_in_play() -> list[object]:
    """Every processor a record can pass through under the running config.

    Structlog's own chain, plus both halves of the ProcessorFormatter — its
    `foreign_pre_chain` (stdlib records, e.g. uvicorn.error) and its render
    chain (structlog's own records).
    """
    formatter = _current_formatter()
    return [
        *structlog.get_config()["processors"],
        *(formatter.foreign_pre_chain or ()),
        *formatter.processors,
    ]


def _rich_formatters_in_play() -> list[object]:
    """Anything in the running config that would render a traceback with rich."""
    found: list[object] = []
    for processor in _processors_in_play():
        if isinstance(processor, structlog.dev.RichTracebackFormatter):
            found.append(processor)
        exception_formatter = getattr(processor, "exception_formatter", None)
        if isinstance(exception_formatter, structlog.dev.RichTracebackFormatter):
            found.append(exception_formatter)
    return found


# ---------------------------------------------------------------------------
# Structural: what the production configuration is built out of
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("json_logs", [False, True])
def test_production_config_has_no_rich_traceback_renderer(json_logs: bool) -> None:
    """No production log format may route an exception through rich.

    Both formats are covered because ENVIRONMENT and LOG_JSON are independent
    settings. The reported incident ran with ENVIRONMENT=production and the
    compose default LOG_JSON=false, which is the console branch.
    """
    with configured_logging(json_logs=json_logs, production=True):
        assert _rich_formatters_in_play() == []


def test_production_console_renderer_uses_plain_traceback() -> None:
    """The console renderer's exception formatter is structlog's plain one.

    `plain_traceback` defers to the stdlib `traceback` module, which prints
    source lines and no locals, so its cost tracks stack depth rather than the
    size of anything the frames happen to hold.
    """
    with configured_logging(json_logs=False, production=True):
        renderer = _current_formatter().processors[-1]

        assert isinstance(renderer, structlog.dev.ConsoleRenderer)
        assert renderer.exception_formatter is structlog.dev.plain_traceback


@pytest.mark.parametrize("json_logs", [False, True])
def test_production_resolves_exc_info_before_the_renderer(json_logs: bool) -> None:
    """`format_exc_info` runs in the chain, so no renderer is handed a traceback.

    This is the structural half of the fix. It also covers stdlib records,
    because the same list is the ProcessorFormatter's `foreign_pre_chain`.
    """
    with configured_logging(json_logs=json_logs, production=True):
        chain = structlog.get_config()["processors"]
        foreign_chain = _current_formatter().foreign_pre_chain

        assert structlog.processors.format_exc_info in chain
        assert structlog.processors.format_exc_info in foreign_chain


def test_development_console_renderer_uses_plain_traceback_too() -> None:
    """fix(#1746 codex r10): dev no longer keeps rich at all, locals-off or not.

    Superseded by a stronger fix, not merely a stricter test: round 10
    retired dev's rich-with-locals-off compromise (the previous version of
    this test) entirely. `format_exc_info` now runs unconditionally, so an
    `exception` field is always pre-rendered before any renderer sees it --
    and a non-plain formatter meeting a pre-rendered `exception` field is
    the exact case the `plain_traceback` comment in `setup_logging` warns
    about, not merely a perf compromise. Dev and production now build this
    renderer identically.
    """
    with configured_logging(json_logs=False, production=False):
        renderer = _current_formatter().processors[-1]

        assert isinstance(renderer, structlog.dev.ConsoleRenderer)
        assert renderer.exception_formatter is structlog.dev.plain_traceback


# ---------------------------------------------------------------------------
# Behavioral: what a request-path exception actually emits
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_middleware_exception_logs_plain_traceback(capsys) -> None:
    """An unhandled exception logs type, message and frames — and no locals.

    The sentinel is reachable only through a frame local's `repr()`, so its
    absence is what makes the emitted record independent of local size.
    """
    from httpx import ASGITransport, AsyncClient
    from starlette.applications import Starlette
    from starlette.routing import Route

    async def boom(_request):
        _raise_with_fat_local()

    app = Starlette(routes=[Route("/boom", boom)])
    app.add_middleware(logging_mw.RequestLoggingMiddleware)

    with configured_logging(json_logs=False, log_level="INFO", production=True):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as http:
            with pytest.raises(ValueError):
                await http.get("/boom")

        captured = capsys.readouterr()

    out = captured.out + captured.err

    # The exception stays debuggable: type, message, and the raising frame.
    assert "Unhandled exception" in out
    assert "Traceback (most recent call last)" in out
    assert "ValueError" in out
    assert "audit_details.date is not a date" in out
    assert "_raise_with_fat_local" in out

    # ...but nothing whose cost is a frame local's repr was rendered.
    assert _LOCALS_SENTINEL not in out
    assert "_FatRepr" not in out
    assert not any(char in out for char in _BOX_DRAWING)


def test_emitted_traceback_is_independent_of_local_size() -> None:
    """The same exception with a 500x larger local emits an identical traceback.

    This is the incident's property stated directly, and without a stopwatch:
    both runs go through the real production handler, the only difference
    between them is the size of one frame local, and what lands in the log is
    byte-for-byte the same.
    """

    def render_traceback(repeats: int) -> str:
        stream = StringIO()
        with configured_logging(json_logs=False, log_level="INFO", production=True):
            logging.getLogger().handlers[0].setStream(stream)
            try:
                _raise_with_fat_local(repeats)
            except ValueError:
                structlog.stdlib.get_logger("api.error").exception(
                    "Unhandled exception"
                )
        emitted = stream.getvalue()
        assert _LOCALS_SENTINEL not in emitted
        # Drop the key/value prefix: its timestamp is the one field that
        # legitimately differs between the two runs.
        return emitted[emitted.index("Traceback (most recent call last)") :]

    assert render_traceback(1) == render_traceback(500)


def test_rich_formatter_would_have_rendered_the_locals() -> None:
    """Pins the premise the two tests above rest on.

    Without this, `_LOCALS_SENTINEL not in out` could pass because the
    sentinel never reaches any formatter at all, and both regression tests
    would be vacuous. structlog's stock rich formatter does emit it.
    """
    if not isinstance(
        structlog.dev.default_exception_formatter, structlog.dev.RichTracebackFormatter
    ):
        pytest.skip("rich is not installed, so the rich default is not in play")

    try:
        _raise_with_fat_local()
    except ValueError:
        exc_info = sys.exc_info()

    sio = StringIO()
    structlog.dev.RichTracebackFormatter(width=200)(sio, exc_info)

    assert _LOCALS_SENTINEL in sio.getvalue()
