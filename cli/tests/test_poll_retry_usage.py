# SPDX-License-Identifier: Apache-2.0
"""fix(#1778 review round 8): structural gate — every --wait poll loop in
this package must call call_sdk() with reraise_timeout=True (routed through
_sdk_helpers.poll_until), not the plain default that treats a per-request
httpx.TimeoutException as immediately fatal.

wait_for_refresh() (refresh.py) still called plain call_sdk() with no
reraise_timeout, so one slow status GET made `geolens refresh --wait` exit
EXIT_NETWORK immediately even with the operation's own deadline nowhere
near reached (or, for the default unbounded --wait, with no deadline at
all). resolve_dataset_id() (publish.py, shared by `publish --wait` and
`analysis materialize --wait`) was fixed for this in round 7.

Uses ``ast`` rather than a bare text grep so a match inside a comment or a
docstring (this module's own docstring included) cannot produce a false
positive or negative.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

_PACKAGE_DIR = Path(__file__).resolve().parent.parent / "geolens_cli"

#: Every function in this package that runs a `--wait`-style poll loop
#: (a `while` around a job-status GET). New poll loops must be added here
#: — the point of this gate is that a NEW one can't quietly skip the
#: retry path.
POLL_LOOP_FUNCTIONS: dict[str, str] = {
    "publish.py": "resolve_dataset_id",
    "refresh.py": "wait_for_refresh",
}


def _find_function(tree: ast.AST, name: str) -> ast.FunctionDef:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"no top-level `def {name}` found")


def _call_sdk_calls(node: ast.AST) -> list[ast.Call]:
    calls: list[ast.Call] = []
    for child in ast.walk(node):
        if (
            isinstance(child, ast.Call)
            and isinstance(child.func, ast.Name)
            and child.func.id == "call_sdk"
        ):
            calls.append(child)
    return calls


def _has_reraise_timeout_true(call: ast.Call) -> bool:
    for kw in call.keywords:
        if kw.arg == "reraise_timeout":
            return isinstance(kw.value, ast.Constant) and kw.value.value is True
    return False


def test_every_poll_loop_calls_call_sdk_with_reraise_timeout() -> None:
    offenders: list[str] = []
    total_calls = 0

    for filename, function_name in POLL_LOOP_FUNCTIONS.items():
        path = _PACKAGE_DIR / filename
        tree = ast.parse(path.read_text(), filename=str(path))
        fn = _find_function(tree, function_name)
        calls = _call_sdk_calls(fn)
        assert calls, (
            f"{filename}::{function_name} no longer calls call_sdk() at "
            "all — update POLL_LOOP_FUNCTIONS or this gate is checking "
            "nothing."
        )
        total_calls += len(calls)
        for call in calls:
            if not _has_reraise_timeout_true(call):
                offenders.append(f"{filename}:{call.lineno}")

    assert offenders == [], (
        "A --wait poll loop calls call_sdk() without reraise_timeout=True "
        f"at: {offenders}. A per-request timeout there is immediately "
        "fatal (EXIT_NETWORK) even when the operation's own deadline "
        "still has time left — route it through _sdk_helpers.poll_until "
        "instead."
    )
    # Positive control: if this drops to 0, the AST walk (or every
    # registered poll loop) broke silently and the assertion above would
    # pass vacuously.
    assert total_calls >= len(POLL_LOOP_FUNCTIONS)


class TestPollUntilDeadlineDiscipline:
    """fix(#1778 review round 16): poll_until()'s loop checked the
    deadline only AFTER a timeout, then slept the FULL interval
    regardless of how much time actually remained, and looped straight
    back into fetch() with no recheck at all -- only the NEXT timeout
    would have caught a deadline that had already passed. Two bugs from
    that one gap: a request that timed out less than `interval` before
    the deadline overslept past it and then fired another request
    anyway, so a SUCCESS on that request was accepted after the
    caller's own advertised deadline; and a stall straddling the
    deadline paid for a full extra per-request timeout it never needed
    to.

    Pins the four timing invariants enumerated in poll_until()'s own
    docstring (_sdk_helpers.py):
    (a) no fetch() call ever starts after the deadline
    (b) total wall time <= deadline + at most one request's own timeout
    (c) unbounded mode (deadline=float("inf")) retries forever with the
        full interval
    (d) a fetch() that succeeds returns immediately, even if it
        straddled the deadline
    """

    def test_a_timeout_just_shy_of_the_deadline_does_not_start_a_second_fetch(
        self,
    ) -> None:
        """Reproduces the exact scenario the finding names: a timeout
        lands 0.5s before a 10s-out deadline, with a 1s interval. The
        old code would sleep the full 1s (overshooting the deadline by
        0.5s) and then fetch() again anyway. The fixed loop must sleep
        only the 0.5s actually remaining, and the very next deadline
        check must catch the now-passed deadline WITHOUT another
        fetch()."""
        import httpx

        from geolens_cli._sdk_helpers import PollDeadlineExceeded, poll_until

        fetch_calls = 0

        def fetch():
            nonlocal fetch_calls
            fetch_calls += 1
            raise httpx.TimeoutException("stalled")

        sleeps: list[float] = []
        # clock: 0.0 (pre-fetch #1 check, remaining=10) -> 9.5 (post-
        # timeout check, remaining=0.5, triggers sleep(min(1, 0.5))) ->
        # 10.0 (pre-fetch #2 check, remaining=0 -> raise, no 2nd fetch)
        clock = iter([0.0, 9.5, 10.0])

        with pytest.raises(PollDeadlineExceeded):
            poll_until(
                fetch,
                deadline=10.0,
                interval=1.0,
                sleep=sleeps.append,
                monotonic=lambda: next(clock),
            )

        assert fetch_calls == 1, "a second fetch must never be attempted"
        assert sleeps == [0.5], "sleep must be capped to the time remaining, not the bare interval"

    def test_a_success_returned_just_before_the_deadline_is_accepted(self) -> None:
        """The mirror of the overshoot test: the retry after a
        near-deadline timeout must still be ATTEMPTED while time
        remains, and a success on that attempt is honored."""
        import httpx

        from geolens_cli._sdk_helpers import poll_until

        responses = iter([httpx.TimeoutException("stalled"), "the-result"])

        def fetch():
            item = next(responses)
            if isinstance(item, Exception):
                raise item
            return item

        sleeps: list[float] = []
        # clock: 0.0 (pre-fetch #1, remaining=10) -> 9.9 (post-timeout,
        # remaining=0.1, sleep(min(1, 0.1))) -> 9.99 (pre-fetch #2,
        # remaining=0.01 > 0 -> fetch() attempted and succeeds)
        clock = iter([0.0, 9.9, 9.99])

        result = poll_until(
            fetch,
            deadline=10.0,
            interval=1.0,
            sleep=sleeps.append,
            monotonic=lambda: next(clock),
        )

        assert result == "the-result"
        assert sleeps == pytest.approx([0.1])

    def test_a_stall_straddling_the_deadline_exits_after_that_one_request(
        self,
    ) -> None:
        """The in-flight request that was already running when the
        deadline arrived is allowed to finish (its own per-request
        timeout, not poll_until's own sleep) -- but nothing after it:
        no sleep, no second request."""
        import httpx

        from geolens_cli._sdk_helpers import PollDeadlineExceeded, poll_until

        fetch_calls = 0

        def fetch():
            nonlocal fetch_calls
            fetch_calls += 1
            # Simulates the request's own timeout firing AFTER the
            # deadline had already passed mid-flight.
            raise httpx.TimeoutException("stalled past the deadline")

        sleeps: list[float] = []
        # clock: 0.0 (pre-fetch check, remaining=10 -- request starts
        # BEFORE the deadline) -> 10.5 (post-timeout check, the request
        # itself consumed enough wall time that the deadline is now
        # behind us -- remaining=-0.5 -> raise immediately, no sleep)
        clock = iter([0.0, 10.5])

        with pytest.raises(PollDeadlineExceeded):
            poll_until(
                fetch,
                deadline=10.0,
                interval=1.0,
                sleep=sleeps.append,
                monotonic=lambda: next(clock),
            )

        assert fetch_calls == 1
        assert sleeps == [], "no sleep once the deadline has already passed"

    def test_unbounded_mode_retries_forever_with_the_full_interval(self) -> None:
        """deadline=float("inf") (the convention wait_for_refresh's
        default --wait and analysis.POLL_FOREVER both already use) must
        never raise PollDeadlineExceeded, and must sleep the FULL
        interval every time -- min(interval, inf) == interval."""
        import httpx

        from geolens_cli._sdk_helpers import poll_until

        fetch_calls = 0

        def fetch():
            nonlocal fetch_calls
            fetch_calls += 1
            if fetch_calls <= 3:
                raise httpx.TimeoutException("stalled")
            return "eventually"

        sleeps: list[float] = []
        # A real, ever-increasing clock stands in fine here: with an
        # infinite deadline, `remaining` is always positive no matter
        # how far the clock advances, so there is no near-deadline edge
        # to engineer.
        clock = iter([0.0, 100.0, 200.0, 300.0, 400.0, 500.0, 600.0, 700.0])

        result = poll_until(
            fetch,
            deadline=float("inf"),
            interval=1.0,
            sleep=sleeps.append,
            monotonic=lambda: next(clock),
        )

        assert result == "eventually"
        assert fetch_calls == 4
        assert sleeps == [1.0, 1.0, 1.0], "unbounded mode must always sleep the full interval"

    def test_a_fetch_that_succeeds_on_the_first_try_returns_immediately(self) -> None:
        """No deadline arithmetic overhead beyond the one pre-fetch
        check -- a success is returned as-is, with no post-hoc deadline
        check and no sleep."""
        from geolens_cli._sdk_helpers import poll_until

        sleeps: list[float] = []
        clock = iter([0.0])

        result = poll_until(
            lambda: "immediate",
            deadline=10.0,
            interval=1.0,
            sleep=sleeps.append,
            monotonic=lambda: next(clock),
        )

        assert result == "immediate"
        assert sleeps == []
