"""Cover the autouse logging guard in conftest.py (#1066).

The guard exists because a leaked logging config makes later log assertions
pass vacuously, so these tests are written to fail rather than to pass quietly:
the leaking test asserts that its leak REALLY happened before the follow-on
test asserts the guard cleaned it up. A leak that stopped reproducing would go
red here instead of turning the guard into untested dead code.
"""

import logging

import pytest
import structlog
from structlog.testing import capture_logs

from app.core.logging_config import setup_logging
from tests.conftest import (
    _UNCLAMPED_STRUCTLOG_CONFIGURE,
    _global_logging_repair,
    _is_pytest_owned_handler,
    _LOGGING_MUTATED_LOGGERS,
)

# A module-level lazy proxy, the shape every app module's `logger` has. It is
# what freezes: `structlog.get_logger()` returns a BoundLoggerLazyProxy, and
# emitting through one while caching is armed replaces its `bind` with a
# closure over the processor list in force at that moment.
module_logger = structlog.get_logger("tests.logging_conftest_guard")


def _snapshot():
    return {
        name: (
            logging.getLogger(name).handlers[:],
            logging.getLogger(name).propagate,
            logging.getLogger(name).level,
        )
        for name in _LOGGING_MUTATED_LOGGERS
    }


def test_guard_repairs_a_setup_logging_leak():
    """Drive the guard's own window around a real ``setup_logging()``.

    Order-independent and xdist-independent, unlike the pair below: it runs the
    guard's own body, so it pins the contract even if this module's tests get
    shuffled or split across workers.
    """
    before = _snapshot()
    with _global_logging_repair():
        setup_logging(json_logs=True, log_level="DEBUG")
        # Arm caching THROUGH the clamp, so the flag backstop still has
        # coverage. Nothing reaches this state while the clamp is installed;
        # the point is that the guard repairs it if anything ever does.
        _UNCLAMPED_STRUCTLOG_CONFIGURE(cache_logger_on_first_use=True)

        # The leak is real: assert it INSIDE the window, so this test cannot
        # pass by the leak having quietly stopped happening.
        assert structlog.get_config()["cache_logger_on_first_use"] is True
        assert logging.getLogger("uvicorn.access").propagate is False
        assert logging.getLogger().level == logging.DEBUG
        assert logging.getLogger().handlers != before[""][0]

    assert structlog.get_config()["cache_logger_on_first_use"] is False
    after = _snapshot()
    for name in _LOGGING_MUTATED_LOGGERS:
        assert after[name] == before[name], f"{name or '<root>'} not restored"


def test_mid_test_setup_logging_does_not_blind_capture_logs():
    """The vacuous pass this whole issue exists to prevent (#1127 codex P1).

    A test calls ``setup_logging()`` mid-body, emits through a module-level
    logger, and something calls ``setup_logging()`` again. Without the clamp
    the first call arms caching, the emit freezes the proxy against that call's
    processor list, and the second call rebinds the live list to a fresh one,
    so ``capture_logs()`` mutating the new list in place is invisible to the
    frozen logger: the assertion below sees zero records and a credential-leak
    check written this way would pass while asserting nothing.

    Both halves are needed to reproduce it. On structlog 25.5.0 a freeze alone
    does NOT blind ``capture_logs()``, because it clears and extends the live
    list in place rather than replacing it.
    """
    setup_logging(json_logs=True, log_level="DEBUG")
    module_logger.info("warm up")  # freezes the proxy if caching is armed
    setup_logging(json_logs=True, log_level="DEBUG")  # rebinds the live list

    with capture_logs() as events:
        module_logger.info("sentinel", password="hunter2")

    assert [e["event"] for e in events] == ["sentinel"], (
        "capture_logs() went blind: the proxy froze against a stale processor "
        "list, so a log assertion here could never fail"
    )


def test_configure_cannot_arm_caching_during_the_test_session():
    """The clamp itself, at the choke point, independent of who calls it."""
    structlog.configure(cache_logger_on_first_use=True)
    assert structlog.get_config()["cache_logger_on_first_use"] is False

    setup_logging(json_logs=True, log_level="DEBUG")
    assert structlog.get_config()["cache_logger_on_first_use"] is False


def test_guard_restores_the_processor_list_object_not_a_copy():
    """Identity matters: bound loggers hold a reference to the live list.

    Handing structlog a copy is itself the second half of the blinding
    conjunction above, so the guard must put the same object back.
    """
    before = structlog.get_config()["processors"]
    with _global_logging_repair():
        setup_logging(json_logs=True, log_level="DEBUG")
        assert structlog.get_config()["processors"] is not before

    assert structlog.get_config()["processors"] is before


def test_guard_clears_caching_before_the_body_runs():
    """Cover the entry-side clear, which the teardown-side one does not imply.

    A worker's first test would otherwise run with the collection-time True
    still armed, because ``app/api/main.py`` calls ``setup_logging()`` at
    import. A module-level logger that emits in that window freezes against the
    chain in force and goes invisible to every later capture on the worker.
    """
    _UNCLAMPED_STRUCTLOG_CONFIGURE(cache_logger_on_first_use=True)
    assert structlog.get_config()["cache_logger_on_first_use"] is True

    with _global_logging_repair():
        assert structlog.get_config()["cache_logger_on_first_use"] is False


def test_guard_drops_a_leaked_handler_pytest_reattached_around(monkeypatch):
    """Presence of every saved handler is not proof nothing leaked.

    Reproduces the run shape where the snapshot holds only pytest's own
    capture handlers: the test clears them and installs its own, pytest
    reattaches the same objects for the next phase, and a leak signal based on
    "did a saved handler go missing" reports clean while the installed handler
    survives (#1127 codex P2).
    """
    root = logging.getLogger()
    pytest_owned = [h for h in root.handlers if _is_pytest_owned_handler(h)]
    assert pytest_owned, "expected pytest's capture handlers on root"
    monkeypatch.setattr(root, "handlers", list(pytest_owned))

    leaked = logging.StreamHandler()
    with _global_logging_repair():
        root.handlers.clear()  # what setup_logging() does
        root.addHandler(leaked)
        for handler in pytest_owned:  # what pytest does for the next phase
            root.addHandler(handler)

    assert leaked not in root.handlers
    assert root.handlers == pytest_owned


# Recorded by the leaker so its partner can compare against the state THIS
# worker started from. A hardcoded expectation does not work for the stdlib
# side: collection imports app/api/main.py, whose module-level
# `setup_logging()` call leaves uvicorn.access.propagate False and root at
# LOG_LEVEL before any test runs. Which modules get collected therefore decides
# the baseline, so the only stable comparison is against the leaker's own
# reading (#1066).
_PRE_LEAK: dict[str, object] = {}


@pytest.mark.xdist_group("logging_conftest_guard")
def test_a_setup_logging_leaks_process_global_state():
    """The leaker. Must stay defined ahead of its partner below.

    Marked into a group so ``--dist loadgroup`` keeps it on the same worker as
    that partner; without the marker the two can be scheduled apart and the
    partner asserts an invariant nothing disturbed.
    """
    _PRE_LEAK["propagate"] = logging.getLogger("uvicorn.access").propagate
    _PRE_LEAK["root_level"] = logging.getLogger().level

    # Leak a level that DIFFERS from whatever the collected app modules already
    # installed. Hardcoding DEBUG makes the stdlib half of the leak invisible
    # whenever LOG_LEVEL is already DEBUG, which turns the partner test below
    # into a check that cannot fail.
    leaked = "ERROR" if _PRE_LEAK["root_level"] != logging.ERROR else "DEBUG"
    setup_logging(json_logs=True, log_level=leaked)

    # setup_logging() asks for caching, and the clamp refuses on its behalf.
    assert structlog.get_config()["cache_logger_on_first_use"] is False
    assert logging.getLogger("uvicorn.access").propagate is False
    assert logging.getLogger().level != _PRE_LEAK["root_level"]


@pytest.mark.xdist_group("logging_conftest_guard")
def test_b_leak_does_not_survive_into_the_next_test():
    """End-to-end proof that the guard is actually registered as autouse.

    The caching flag is asserted unconditionally: the guard clears it on the
    way into every test as well as on the way out, so it holds at the start of
    any test anywhere in the suite, including the first one on a worker. That
    last case is why the entry-side clear exists — under a shuffled run this
    test landed first on its worker and saw the collection-time True.

    The stdlib facts are restored RELATIVE to each test's own snapshot, so they
    are only checked when the leaker really did run first on this worker;
    ``test_guard_repairs_a_setup_logging_leak`` above carries that half
    unconditionally.
    """
    assert structlog.get_config()["cache_logger_on_first_use"] is False
    if _PRE_LEAK:
        assert logging.getLogger("uvicorn.access").propagate == _PRE_LEAK["propagate"]
        assert logging.getLogger().level == _PRE_LEAK["root_level"]
