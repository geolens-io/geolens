"""Compatibility adapter for legacy staging runtime imports."""

from pathlib import Path

from app.core.runtime.staging import StagingRuntimeError
from app.core.runtime.staging import _probe_writable_dir as _core_probe_writable_dir


def _probe_writable_dir(directory: str | Path) -> None:
    """Proxy the writable-directory probe for legacy monkeypatch targets."""
    _core_probe_writable_dir(directory)


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


__all__ = ["StagingRuntimeError", "_probe_writable_dir", "ensure_staging_ready"]
