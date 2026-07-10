"""Staging directory readiness checks used by startup and export paths."""

from __future__ import annotations

import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import structlog

log = structlog.get_logger()


# ING-04 (P2-04): exports temp-dir sweep age threshold. Only entries whose mtime
# is older than this many seconds are deleted on startup. In-flight large exports
# younger than 1 hour survive a rolling restart; truly orphaned crash-residue gets
# cleaned. Matches the 1-hour window used by worker stale-job recovery
# (`JOB_TIMEOUT_SECONDS` in jobs/router.py) so a 6-minute COG export that survives
# a rolling restart at the job layer also keeps its on-disk staging artifact.
EXPORTS_SWEEP_AGE_SECONDS = 3600  # 1 hour


def sweep_orphaned_exports(
    exports_dir: Path,
    *,
    age_threshold_seconds: int = EXPORTS_SWEEP_AGE_SECONDS,
) -> tuple[int, int]:
    """Sweep orphaned export temp entries older than ``age_threshold_seconds``.

    Entries whose ``stat.st_mtime`` is within the last ``age_threshold_seconds``
    are skipped (and logged) so an in-flight large export does not get truncated
    by a restart. Older entries are removed (``shutil.rmtree`` for directories,
    ``Path.unlink`` for files).

    fix(#435): the API lifespan used to delete every entry unconditionally, which
    could truncate an export owned by a *surviving* sibling Uvicorn worker sharing
    the staging volume (`docker-compose.prod.yml` runs two). Both the API and the
    worker now call this one age-aware sweeper.

    ponytail: no cross-process advisory lock. The sweep is idempotent and tolerates
    losing a race (``ignore_errors``/``missing_ok``/``FileNotFoundError``), and the
    age threshold — not mutual exclusion — is what protects in-flight exports. Add a
    lock only if a sweeper ever grows a non-idempotent step.

    Args:
        exports_dir: The ``<staging>/exports/`` directory to sweep. A missing
            directory is treated as a no-op (no error raised).
        age_threshold_seconds: Skip entries newer than this many seconds.

    Returns:
        ``(deleted_count, skipped_count)``.
    """
    if not exports_dir.exists():
        return (0, 0)

    entries = list(exports_dir.iterdir())
    if not entries:
        return (0, 0)

    now_ts = datetime.now(timezone.utc).timestamp()
    deleted_count = 0
    skipped_count = 0
    for item in entries:
        try:
            item_mtime = item.stat().st_mtime
        except FileNotFoundError:
            # Raced with another process / external cleanup — treat as already-gone.
            continue
        age_seconds = now_ts - item_mtime
        if age_seconds < age_threshold_seconds:
            log.info(
                "sweep_skipped_recent_export",
                path=str(item),
                age_seconds=round(age_seconds, 1),
                threshold_seconds=age_threshold_seconds,
            )
            skipped_count += 1
            continue
        if item.is_dir():
            shutil.rmtree(item, ignore_errors=True)
        else:
            item.unlink(missing_ok=True)
        deleted_count += 1

    if deleted_count or skipped_count:
        log.info(
            "exports_sweep_complete",
            deleted=deleted_count,
            skipped=skipped_count,
        )
    return (deleted_count, skipped_count)


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


def redirect_tempfile_to_staging(directory: str | Path) -> None:
    """Redirect stdlib `tempfile` rollover/scratch to the staging directory.

    Two contexts hit this:
      - api: Starlette's MultiPartParser rolls SpooledTemporaryFile to
        tempfile.tempdir; tmpfs `/tmp` (default 512 MiB in compose) fills on
        large uploads → opaque 400 (gh #101, fixed by 260508-rr5).
      - worker: COG conversion's pre-flight `shutil.disk_usage(tempfile.mkdtemp()).free`
        reads tmpfs /tmp (~512 MiB), not the multi-GB staging volume → spurious
        "Insufficient disk space for COG conversion" on rasters that would fit.

    Must run BEFORE FastAPI/Procrastinate/Starlette imports in the embedding
    module so the very first request handler / task uses the override.
    Defensive on OSError so unit-test / alembic-only containers without the
    staging volume mounted don't crash on import — the override is then a
    no-op until the directory exists.
    """
    target_dir = Path(directory)
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        if not target_dir.is_dir():
            return
    tempfile.tempdir = str(target_dir)
