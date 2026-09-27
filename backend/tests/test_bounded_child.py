"""A child's reply, however malformed, comes back as a failure category."""

from __future__ import annotations

import os
import sys
import tempfile
import time

import pytest

from app.platform.bounded_child import ChildFailure, run_child


@pytest.mark.parametrize(
    "reply",
    [
        pytest.param("json.dumps({'error': ['open']})", id="error-not-a-name"),
        pytest.param("'[' * 1_000_000 + ']' * 1_000_000", id="nested-past-the-stack"),
    ],
)
def test_a_malformed_reply_is_no_reply(reply) -> None:
    script = f"import json, sys\nprint({reply})\nsys.exit(1)\n"

    with pytest.raises(ChildFailure) as failure:
        run_child(
            [sys.executable, "-c", script],
            env={"PATH": os.environ["PATH"]},
            timeout=30,
            reported={"open": "open"},
        )

    assert failure.value.category == "no_reply"


def _open_fds() -> int:
    return len(os.listdir("/dev/fd"))


def test_a_child_that_never_reads_a_large_request_is_stopped_at_the_deadline(
    tmp_path,
) -> None:
    """The deadline holds whatever the request's size, even when the child never reads it."""
    pid_file = tmp_path / "child.pid"
    script = (
        "import os, time\n"
        f"open({str(pid_file)!r}, 'w').write(str(os.getpid()))\n"
        "time.sleep(30)\n"
    )

    started = time.monotonic()
    with pytest.raises(ChildFailure) as failure:
        run_child(
            [sys.executable, "-c", script],
            env={"PATH": os.environ["PATH"]},
            timeout=1,
            stdin="x" * 1_000_000,
            reported=(),
        )
    elapsed = time.monotonic() - started

    assert failure.value.category == "timeout"
    assert elapsed < 5, f"stopped after {elapsed:.1f}s on a 1s deadline"
    with pytest.raises(ProcessLookupError):
        os.kill(int(pid_file.read_text()), 0)


def test_a_large_request_reaches_the_child_whole(monkeypatch, tmp_path) -> None:
    """A request past any pipe's buffer arrives intact, and leaves no file or fd behind."""
    scratch = tmp_path / "tmp"
    scratch.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(scratch))
    request = "PROJCRS[78°W]" * 100_000
    script = "import json, sys\nprint(json.dumps({'result': sys.stdin.read()[-13:]}))\n"
    fds = _open_fds()

    result = run_child(
        [sys.executable, "-c", script],
        env={"PATH": os.environ["PATH"]},
        timeout=30,
        stdin=request,
        reported=(),
    )

    assert result == "PROJCRS[78°W]"
    assert list(scratch.iterdir()) == []
    assert _open_fds() == fds
