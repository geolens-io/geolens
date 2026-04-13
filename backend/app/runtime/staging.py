"""Staging directory readiness checks used by startup and export paths."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4


class StagingRuntimeError(RuntimeError):
    """Raised when a staging directory cannot be created or written to."""

    def __init__(self, path: Path, detail: str, error: OSError) -> None:
        self.path = str(path)
        self.detail = detail
        self.error = error
        super().__init__(
            f"Staging directory check failed for '{path}': {detail}. "
            f"System error: {error}. "
            "Remediation: ensure this path is writable by uid:gid 1001:1001 "
            "or set UPLOAD_STAGING_DIR to a writable directory."
        )


def _probe_writable_dir(directory: str | Path) -> None:
    """Perform a real write/delete probe in the target directory."""
    target_dir = Path(directory)
    probe_file = target_dir / f".geolens-write-probe-{uuid4().hex}"
    try:
        probe_file.write_text("probe", encoding="utf-8")
    finally:
        try:
            probe_file.unlink()
        except FileNotFoundError:
            pass


def ensure_staging_ready(directory: str | Path) -> Path:
    """Ensure a staging directory exists and is writable."""
    target_dir = Path(directory)
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise StagingRuntimeError(
            target_dir, "unable to create directory", exc
        ) from exc

    try:
        _probe_writable_dir(target_dir)
    except OSError as exc:
        raise StagingRuntimeError(target_dir, "directory is not writable", exc) from exc

    return target_dir
