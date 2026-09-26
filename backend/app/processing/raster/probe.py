"""Raster reads that parse a file's CRS, run in a child process with a timeout.

A CRS taken from a raster file can make PROJ open other files, and a thread
blocked on one can't be stopped. So every read of an uploaded raster, of the
COG made from it, or of a VRT over such COGs runs in a child started with
``python -m app.processing.raster.probe``. The parent waits a set time and
kills the child when it runs over. Only a typed error comes back: nothing the
child printed, and no text from the file. The operator log records which
operation failed and how, from a fixed set of categories.
"""

from __future__ import annotations

import base64
import json
import re
import signal
import subprocess
import sys
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

# Below the proxies in front of the API (nginx allows 600 s on /api,
# Cloudflare 100 s), so the client gets this refusal rather than a 504.
PREVIEW_TIMEOUT_SECONDS = 60
READ_TIMEOUT_SECONDS = 120
# Quicklooks read pixels, and a VRT's reads reach object storage, where each
# read is bounded at 300 s by GDAL_HTTP_TIMEOUT.
RENDER_TIMEOUT_SECONDS = 900
CRS_FACTS_TIMEOUT_SECONDS = 30

_BACKEND_ROOT = Path(__file__).resolve().parents[3]

# The child's verdicts, and the kind each surfaces as. "invalid" is a raster
# GDAL or PROJ refused to read; "internal" is any other failure in the child.
_CHILD_KINDS = {"open": "open", "invalid": "read", "internal": "internal"}

# An exception's class name, the one part of a traceback the log may carry:
# its message can quote the file.
_EXCEPTION_NAME = re.compile(r"[A-Za-z_][\w.]{0,99}(?:Error|Exception|Exit|Interrupt)")


class RasterProbeError(Exception):
    """A probe that didn't answer.

    ``kind`` is "open", "read" (the raster's content couldn't be read),
    "internal" (the child failed, not the file) or "timeout".
    """

    def __init__(self, kind: str, *, timeout: float) -> None:
        self.kind = kind
        if kind == "open":
            message = "The raster could not be opened."
        elif kind == "timeout":
            message = (
                f"Reading the raster took longer than {timeout:g} seconds, "
                "so it was stopped."
            )
        elif kind == "internal":
            message = "Reading the raster failed unexpectedly."
        else:
            message = "The raster's metadata could not be read."
        super().__init__(message)


def inspect_raster(
    path: str,
    *,
    expected_compression: str | None = None,
    timeout: float | None = None,
) -> dict:
    """Metadata, COG compliance and predictor support of one raster file."""
    return _run(
        "inspect",
        path,
        expected_compression or "",
        timeout=timeout or READ_TIMEOUT_SECONDS,
    )


def read_raster_metadata(path: str, *, timeout: float | None = None) -> dict:
    """``extract_raster_metadata`` of one raster file."""
    return _run("metadata", path, timeout=timeout or READ_TIMEOUT_SECONDS)


def render_quicklook(path: str, size: int, *, timeout: float | None = None) -> bytes:
    """A PNG quicklook of one raster file."""
    encoded = _run(
        "quicklook", path, str(size), timeout=timeout or RENDER_TIMEOUT_SECONDS
    )
    return base64.b64decode(encoded)


def crs_facts(wkt: str, *, timeout: float | None = None) -> dict:
    """Whether a CRS is geographic, in degrees, and its metres per unit."""
    return _run("crs-facts", stdin=wkt, timeout=timeout or CRS_FACTS_TIMEOUT_SECONDS)


def crs_facts_many(wkts: list[str], *, timeout: float | None = None) -> list[dict]:
    """:func:`crs_facts` of each text, in one child."""
    return _run(
        "crs-facts-many",
        stdin=json.dumps(wkts),
        timeout=timeout or CRS_FACTS_TIMEOUT_SECONDS,
    )


def crs_matches(wkts: list[str], *, timeout: float | None = None) -> list[bool | None]:
    """Whether each CRS text names the same CRS as the first text PROJ can read.

    None marks a text PROJ refused.
    """
    return _run(
        "crs-same", stdin=json.dumps(wkts), timeout=timeout or CRS_FACTS_TIMEOUT_SECONDS
    )


def _command(op: str, *args: str) -> list[str]:
    return [sys.executable, "-m", __name__, op, *args]


def _run(op: str, *args: str, stdin: str | None = None, timeout: float) -> Any:
    from app.processing.raster.vrt import gdal_safe_env

    try:
        done = subprocess.run(
            _command(op, *args),
            input=stdin,
            stdin=subprocess.DEVNULL if stdin is None else None,
            capture_output=True,
            text=True,
            cwd=_BACKEND_ROOT,
            env=gdal_safe_env(extras={"PROJ_NETWORK": "OFF"}),
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        logger.warning("raster probe failed", op=op, category="timeout")
        raise RasterProbeError("timeout", timeout=timeout) from None
    except (OSError, UnicodeDecodeError) as exc:
        # The child couldn't start, or its reply wasn't text: the failure is
        # ours, not the raster's.
        logger.warning(
            "raster probe failed",
            op=op,
            category="spawn" if isinstance(exc, OSError) else "undecodable",
            exception=type(exc).__name__,
        )
        raise RasterProbeError("internal", timeout=timeout) from None
    try:
        reply = json.loads(done.stdout)
    except ValueError:
        reply = None
    if done.returncode == 0 and isinstance(reply, dict) and "result" in reply:
        return reply["result"]
    if not isinstance(reply, dict):
        reply = {}
    category, exception = reply.get("error"), reply.get("exception")
    if done.returncode < 0:
        category, exception = "killed", None
    elif category not in _CHILD_KINDS:
        # No verdict: the child died before it could give one, as a failed
        # import or an interpreter crash does. Its traceback ends with the
        # exception's class name.
        category = "no_reply"
        lines = done.stderr.strip().splitlines()
        exception = lines[-1].split(":", 1)[0] if lines else None
    logger.warning(
        "raster probe failed",
        op=op,
        category=category,
        returncode=done.returncode,
        signal=_signal_name(done.returncode),
        exception=exception
        if isinstance(exception, str) and _EXCEPTION_NAME.fullmatch(exception)
        else None,
    )
    raise RasterProbeError(_CHILD_KINDS.get(category, "internal"), timeout=timeout)


def _signal_name(returncode: int) -> str | None:
    if returncode >= 0:
        return None
    try:
        return signal.Signals(-returncode).name
    except ValueError:
        return str(-returncode)


def _inspect(path: str, expected_compression: str) -> dict:
    from app.processing.raster.cog import _predictor_supported, check_cog_compliance

    metadata = _metadata(path)
    compliant, reason = check_cog_compliance(
        path, expected_compression=expected_compression or None
    )
    return {
        "metadata": metadata,
        "compliant": compliant,
        "compliance_reason": reason,
        "predictor_supported": _predictor_supported(path),
    }


def _metadata(path: str) -> dict:
    """``extract_raster_metadata`` plus the facts of the CRS text it read."""
    from app.core.geo import wkt_crs_facts
    from app.processing.raster.cog import extract_raster_metadata

    metadata = extract_raster_metadata(path)
    return {**metadata, **wkt_crs_facts(metadata["crs_wkt"])}


def _quicklook(path: str, size: str) -> str:
    from app.processing.raster.quicklook import generate_quicklook

    return base64.b64encode(generate_quicklook(path, int(size))).decode("ascii")


def _crs_facts() -> dict:
    from app.core.geo import wkt_crs_facts

    return wkt_crs_facts(sys.stdin.read())


def _crs_facts_many() -> list[dict]:
    from app.core.geo import wkt_crs_facts

    return [wkt_crs_facts(wkt) for wkt in json.loads(sys.stdin.read())]


def _crs_same() -> list[bool | None]:
    from rasterio.crs import CRS
    from rasterio.errors import CRSError

    parsed = []
    for wkt in json.loads(sys.stdin.read()):
        try:
            parsed.append(CRS.from_wkt(wkt))
        except CRSError:
            parsed.append(None)
    reference = next((crs for crs in parsed if crs is not None), None)
    return [None if crs is None else crs.equals(reference) for crs in parsed]


def _category(exc: Exception) -> str:
    """ "open", "invalid" (GDAL or PROJ refused the raster) or "internal"."""
    from rasterio import errors
    from rasterio._err import CPLE_BaseError

    if isinstance(exc, errors.RasterioIOError):
        return "open"
    if isinstance(exc, (errors.EnvError, errors.GDALVersionError)):
        return "internal"
    if isinstance(exc, (errors.RasterioError, errors.CRSError, CPLE_BaseError)):
        return "invalid"
    return "internal"


def main(argv: list[str]) -> int:
    from app.processing.raster.vrt import gdal_safe_open_env

    op, args = argv[0], argv[1:]
    try:
        with gdal_safe_open_env():
            if op == "inspect":
                result = _inspect(args[0], args[1])
            elif op == "metadata":
                result = _metadata(args[0])
            elif op == "quicklook":
                result = _quicklook(args[0], args[1])
            elif op == "crs-facts":
                result = _crs_facts()
            elif op == "crs-facts-many":
                result = _crs_facts_many()
            elif op == "crs-same":
                result = _crs_same()
            else:
                raise ValueError(op)
    except Exception as exc:  # broad: every failure reaches the parent as a category
        print(json.dumps({"error": _category(exc), "exception": type(exc).__name__}))
        return 1
    # The parent parses this reply; stdout is not a log.
    # codeql[py/clear-text-logging-sensitive-data]
    print(json.dumps({"result": result}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
