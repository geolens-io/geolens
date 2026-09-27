"""The runner's deadline, the request it hands a child, and the replies it reads."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import tracemalloc
from pathlib import Path

import pytest

from app.platform import bounded_child
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


def test_a_request_reaches_a_child_intact_under_the_c_locale() -> None:
    """Python reads stdin as UTF-8 under the C locale, so the request is written as UTF-8."""
    echo = "import json, sys; print(json.dumps({'result': sys.stdin.read()}))"
    script = (
        "import json, os, sys\n"
        "from app.platform.bounded_child import run_child\n"
        f"print(json.dumps(run_child([sys.executable, '-c', {echo!r}], "
        "env=dict(os.environ), timeout=30, stdin='78\\u00b0W', reported=())))\n"
    )

    done = subprocess.run(
        [sys.executable, "-c", script],
        env={**os.environ, "LC_ALL": "C"},
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout) == "78°W"


@pytest.mark.parametrize(
    "writes",
    [
        pytest.param("print(json.dumps({'result': 'x' * 64 * 2**20}))", id="stdout"),
        pytest.param(
            "sys.stderr.write('x' * 64 * 2**20); print(json.dumps({'result': 1}))",
            id="stderr",
        ),
    ],
)
def test_output_past_the_cap_is_refused_without_being_read(
    monkeypatch, tmp_path, writes
) -> None:
    monkeypatch.setattr(bounded_child, "_MAX_OUTPUT_BYTES", 2**20)
    scratch = tmp_path / "tmp"
    scratch.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(scratch))
    pid_file = tmp_path / "child.pid"
    script = (
        "import json, os, sys\n"
        f"open({str(pid_file)!r}, 'w').write(str(os.getpid()))\n"
        f"{writes}\n"
    )
    fds = _open_fds()

    tracemalloc.start()
    try:
        with pytest.raises(ChildFailure) as failure:
            run_child(
                [sys.executable, "-c", script],
                env={"PATH": os.environ["PATH"]},
                timeout=30,
                reported=(),
            )
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    assert failure.value.category == "oversized"
    assert peak < 8 * 2**20, f"the parent held {peak / 2**20:.0f} MiB"
    with pytest.raises(ProcessLookupError):
        os.kill(int(pid_file.read_text()), 0)
    assert list(scratch.iterdir()) == []
    assert _open_fds() == fds


def test_output_up_to_the_cap_is_read(monkeypatch) -> None:
    reply = json.dumps({"result": "x" * 1000}) + "\n"
    monkeypatch.setattr(bounded_child, "_MAX_OUTPUT_BYTES", len(reply))

    result = run_child(
        [sys.executable, "-c", f"import sys; sys.stdout.write({reply!r})"],
        env={"PATH": os.environ["PATH"]},
        timeout=30,
        reported=(),
    )

    assert result == "x" * 1000
