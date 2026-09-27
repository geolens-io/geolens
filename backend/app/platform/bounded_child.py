"""A Python module run in a child process that the parent kills at a deadline.

The child answers with one JSON object on stdout: ``{"result": ...}``, or
``{"error": <category>, "exception": <class name>}`` for a failure it can
name. Nothing else it printed comes back, so a failure reaches the caller as
a category and, for the operator log, an exception's class name.
"""

from __future__ import annotations

import contextlib
import json
import locale
import re
import signal
import subprocess
import tempfile
from collections.abc import Collection, Iterator, Sequence
from pathlib import Path
from typing import IO, Any

_BACKEND_ROOT = Path(__file__).resolve().parents[2]

# An exception's class name, the one part of a traceback the log may carry:
# its message can quote the file.
_EXCEPTION_NAME = re.compile(r"[A-Za-z_][\w.]{0,99}(?:Error|Exception|Exit|Interrupt)")

# The largest replies are a 512 px quicklook, under 1 MB even of noise, and
# the metadata of a GeoTIFF with the format's 65,535 bands, about 6 MB.
_MAX_OUTPUT_BYTES = 16 * 1024 * 1024


class ChildFailure(Exception):
    """A child that didn't answer.

    ``category`` is "timeout", "spawn" (it couldn't start), "undecodable"
    (its output wasn't text), "oversized" (it wrote more than the parent
    reads), "killed" (a signal ended it), "no_reply", or a category the child
    reported. ``details`` are the fields that describe the failure to an
    operator log, starting with the category.
    """

    def __init__(self, category: str, **details: Any) -> None:
        super().__init__(category)
        self.category = category
        self.details = {"category": category, **details}


def run_child(
    argv: Sequence[str],
    *,
    env: dict[str, str],
    timeout: float,
    stdin: str | None = None,
    reported: Collection[str],
) -> Any:
    """The child's ``result``, or ``ChildFailure``.

    ``reported`` are the categories the child may name itself; any other
    failure is "no_reply".
    """
    try:
        with (
            _stdin_file(stdin) as request,
            tempfile.TemporaryFile() as out,
            tempfile.TemporaryFile() as err,
        ):
            done = subprocess.run(
                argv,
                stdin=request,
                stdout=out,
                stderr=err,
                cwd=_BACKEND_ROOT,
                env=env,
                timeout=timeout,
            )
            stdout, stderr = _read_output(out, "stdout"), _read_output(err, "stderr")
    except subprocess.TimeoutExpired:
        raise ChildFailure("timeout") from None
    except (OSError, UnicodeDecodeError) as exc:
        # The child couldn't start, or its reply wasn't text: the failure is
        # ours, not the input's.
        raise ChildFailure(
            "spawn" if isinstance(exc, OSError) else "undecodable",
            exception=type(exc).__name__,
        ) from None
    try:
        reply = json.loads(stdout)
    except (ValueError, RecursionError):
        # RecursionError: JSON nested deeper than the parser's stack.
        reply = None
    if done.returncode == 0 and isinstance(reply, dict) and "result" in reply:
        return reply["result"]
    if not isinstance(reply, dict):
        reply = {}
    category, exception = reply.get("error"), reply.get("exception")
    if done.returncode < 0:
        category, exception = "killed", None
    elif not isinstance(category, str) or category not in reported:
        # No verdict: the child died before it could give one, as a failed
        # import or an interpreter crash does. Its traceback ends with the
        # exception's class name.
        category = "no_reply"
        lines = stderr.strip().splitlines()
        exception = lines[-1].split(":", 1)[0] if lines else None
    raise ChildFailure(
        category,
        returncode=done.returncode,
        signal=_signal_name(done.returncode),
        exception=exception
        if isinstance(exception, str) and _EXCEPTION_NAME.fullmatch(exception)
        else None,
    )


@contextlib.contextmanager
def _stdin_file(text: str | None) -> Iterator[IO[str] | int]:
    """``text`` in an unlinked temporary file for the child's stdin, or nothing.

    A file rather than a pipe: on macOS, writing a pipe the child never reads
    blocks the parent past the deadline. The text is encoded as ``subprocess``
    encodes text, which is how a child in the same locale reads its stdin.
    """
    if text is None:
        yield subprocess.DEVNULL
        return
    with tempfile.TemporaryFile(
        "w+", encoding=locale.getpreferredencoding(False)
    ) as request:
        request.write(text)
        request.seek(0)
        yield request


def _read_output(output: IO[bytes], stream: str) -> str:
    """What the child wrote to ``stream``, reading no more than the cap."""
    output.seek(0)
    data = output.read(_MAX_OUTPUT_BYTES + 1)
    if len(data) > _MAX_OUTPUT_BYTES:
        raise ChildFailure("oversized", stream=stream)
    return data.decode(locale.getpreferredencoding(False))


def _signal_name(returncode: int) -> str | None:
    if returncode >= 0:
        return None
    try:
        return signal.Signals(-returncode).name
    except ValueError:
        return str(-returncode)
