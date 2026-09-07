"""Staging directory readiness checks used by startup and export paths."""

from __future__ import annotations

import os
import re
import shutil
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import structlog

log = structlog.get_logger()


# ING-04 (P2-04): exports temp-dir sweep age threshold. Entries older than this
# are deleted on startup; matches worker stale-job recovery's
# `JOB_TIMEOUT_SECONDS` (jobs/router.py) so an export surviving a rolling
# restart at the job layer also keeps its on-disk staging artifact.
EXPORTS_SWEEP_AGE_SECONDS = 3600  # 1 hour

# fix(#1435): the periodic sweeper (inside _stale_jobs_sweeper)
# runs every few minutes, unlike the two boot-time callers. A directory's
# mtime is set once at creation and not bumped by writes to files already
# inside it, so reusing EXPORTS_SWEEP_AGE_SECONDS here would guarantee
# deleting any export whose run+download time exceeds 1 hour on the very next
# cycle. The wider margin limits the periodic pass to residue from a dead
# process.
EXPORTS_PERIODIC_SWEEP_AGE_SECONDS = 4 * EXPORTS_SWEEP_AGE_SECONDS  # 4 hours


# fix(#1532): `LocalStorageProvider.put`'s write-through scratch
# pattern (`<name>.<32 hex>.tmp`). A SIGKILL/OOM/power loss skips the normal
# cleanup and leaves residue under any prefix (COGs, originals, VRTs, map
# assets); only the export cache used to know this pattern and only scanned
# its own prefix, so everything else leaked.
_LOCAL_TMP_RE = re.compile(r"\.[0-9a-f]{32}\.tmp$")

# fix(#1746): the local extract of a protected OGC API
# collection. `materialise_oapif_items` removes it in `finally`/on exception,
# but a SIGKILL/OOM skips both and leaks up to `MAX_BYTES` (2 GiB). Carries no
# credential itself, but is data read with one.
#
# The writer imports these constants rather than respelling the prefix, so the
# sweep and the `mkstemp` call cannot describe different files; `test_layering`
# pins that.
OAPIF_ITEMS_SCRATCH_PREFIX = "oapif_items_"
OAPIF_ITEMS_SCRATCH_SUFFIX = ".geojson"
_OAPIF_ITEMS_RE = re.compile(
    rf"^{re.escape(OAPIF_ITEMS_SCRATCH_PREFIX)}.*{re.escape(OAPIF_ITEMS_SCRATCH_SUFFIX)}$"
)

# Every scratch name this codebase creates under the staging root. A new one
# belongs HERE, in the same commit that starts writing it (the leak class r28
# closed).
#
# NOT included: `gdal_auth_*.hdr` — lives on the container tmpfs under
# `GDAL_HEADER_DIR`, never the staging root; `sweep_stale_gdal_header_files`
# reclaims it on a one-hour horizon (it holds a credential) vs. four here.
_STAGING_SCRATCH_RES = (_LOCAL_TMP_RE, _OAPIF_ITEMS_RE)


def _is_staging_scratch(name: str) -> bool:
    return any(pattern.search(name) for pattern in _STAGING_SCRATCH_RES)


def sweep_orphaned_write_scratch(
    root: Path,
    *,
    age_threshold_seconds: int = EXPORTS_PERIODIC_SWEEP_AGE_SECONDS,
) -> int:
    """Reclaim orphaned scratch files anywhere under ``root``. Returns how many.

    Covers every name in ``_STAGING_SCRATCH_RES``. Aged by mtime since these
    files never move and carry no timestamp of their own; the periodic horizon
    ensures an in-progress multi-GB write is never swept mid-write. Per-entry
    errors are swallowed — an entry that won't stat/unlink is the next pass's
    problem.
    """
    if not root.is_dir():
        return 0
    cutoff = time.time() - age_threshold_seconds
    removed = 0
    for entry in root.rglob("*"):
        if not _is_staging_scratch(entry.name):
            continue
        try:
            if entry.is_file() and entry.stat().st_mtime < cutoff:
                entry.unlink(missing_ok=True)
                removed += 1
        except OSError:
            continue
    return removed


# fix(#1532): when this process last walked the tree. Module-level
# and per-process, like `artifact_cache._last_sweep_at`; each replica bounds
# only its own work.
_last_scratch_sweep_at = 0.0


def sweep_orphaned_write_scratch_occasionally(
    root: Path,
    *,
    age_threshold_seconds: int = EXPORTS_PERIODIC_SWEEP_AGE_SECONDS,
) -> int:
    """``sweep_orphaned_write_scratch``, at most once per horizon per process.

    fix(#1532): unguarded, this rode the credential sweeper's 300s
    cadence, so every replica did a full O(everything stored) recursive walk
    every five minutes to find nothing eligible before the four-hour horizon.
    The interval IS the horizon (from the same argument, so they can't drift
    apart); worst-case retention is two horizons instead of one.
    """
    global _last_scratch_sweep_at
    now = time.time()
    if now - _last_scratch_sweep_at < age_threshold_seconds:
        return 0
    _last_scratch_sweep_at = now
    return sweep_orphaned_write_scratch(
        root, age_threshold_seconds=age_threshold_seconds
    )


def _latest_mtime(entry: Path) -> float:
    """The most recent mtime of ``entry`` itself, or (one level deep) any
    file directly inside it.

    fix(#1435): a directory's own mtime is bumped only by
    add/remove/rename of an entry, not by writes to an already-created file's
    contents, so an export dir's mtime freezes at creation while ogr2ogr keeps
    writing to its output file. Checking the contained file(s) too keeps a
    still-growing export reading as fresh.
    """
    latest = entry.stat().st_mtime
    if entry.is_dir():
        try:
            children = list(entry.iterdir())
        except OSError:
            # fix(#1435): a directory that can't be listed (e.g.
            # root-owned residue from a UID change) must not crash
            # sweep_orphaned_exports — both boot-time callers run this
            # unguarded. Fall back to the entry's own mtime.
            return latest
        for child in children:
            try:
                latest = max(latest, child.stat().st_mtime)
            except OSError:
                continue  # unreadable, or raced with a concurrent write/rename
    return latest


def sweep_orphaned_exports(
    exports_dir: Path,
    *,
    age_threshold_seconds: int = EXPORTS_SWEEP_AGE_SECONDS,
) -> tuple[int, int]:
    """Sweep orphaned export temp entries older than ``age_threshold_seconds``.

    Entries newer than the threshold are skipped (and logged) so an in-flight
    export survives a restart; older ones are removed.

    fix(#435): the API lifespan used to delete every entry unconditionally,
    which could truncate an export owned by a surviving sibling Uvicorn worker
    sharing the staging volume. Both API and worker now call this age-aware
    sweeper instead.

    No cross-process lock: the age threshold, not mutual exclusion, is what
    protects in-flight exports, and the sweep tolerates losing a race.

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
            item_mtime = _latest_mtime(item)
        except OSError:
            # fix(#1435): FileNotFoundError (raced cleanup) or
            # PermissionError (unreadable residue) — skip rather than crash
            # the sweep and take down API/worker startup.
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


# fix(#1746): the GDAL bearer-header tempfile ogr.py/preview.py write for a
# WFS/OGC API preview/ingest (GDAL_HTTP_HEADER_FILE, 0600) is unlinked in
# `finally`, but a SIGKILL/OOM on the subprocess skips that, leaking the
# token-bearing file. Matched by exact prefix/suffix, mirroring
# `tempfile.mkstemp(prefix="gdal_auth_", suffix=".hdr", ...)` at both sites.
_GDAL_AUTH_HEADER_PREFIX = "gdal_auth_"
_GDAL_AUTH_HEADER_SUFFIX = ".hdr"

# fix(#1746): the container tmpfs, deliberately NOT
# `settings.upload_staging_dir`. Both api and worker mount /tmp as a 512m
# tmpfs, so it's private, gone on restart, and never archived by
# `scripts/backup-entrypoint.sh` (which tars the staging volume every cycle).
# Hardcoded rather than a setting so an operator can't silently repoint it at
# a persistent volume.
GDAL_HEADER_DIR = Path("/tmp/gdal-auth")


# feat(#1746) plan section 5 rule A. Measured on GDAL 3.10.3 and 3.13.0: on a
# cross-host 302, libcurl under GDAL drops `Authorization` but forwards every
# other header verbatim, so prefer `Authorization` framing wherever a
# provider accepts it (a header-key credential IS forwarded cross-host with
# no GDAL option to stop it; bounded operationally per AGENTS.md Rule 2).
#
# fix(#1746): IF_SAME_HOST, not NO — NO blocks forwarding after
# ANY redirect, so a protected endpoint redirecting to its own canonical path
# (e.g. adding a trailing slash) would 401. IF_SAME_HOST is also GDAL's
# current default; set explicitly so a later default change can't silently
# widen what the credential follows.
#
# NOT `GDAL_HTTP_FOLLOWLOCATION` (#937) — not a real GDAL option, never
# stopped a redirect, must never be re-added anywhere. This IS a real option,
# read by GDAL's /vsicurl and http drivers.
GDAL_HEADER_FILE_REDIRECT_ENV: dict[str, str] = {
    "CPL_VSIL_CURL_AUTHORIZATION_HEADER_ALLOWED_IF_REDIRECT": "IF_SAME_HOST",
}


def gdal_header_dir() -> Path:
    """The 0700 directory GDAL bearer-header files are written into.

    Created on demand only by the two ``mkstemp(dir=...)`` call sites; the
    chmod matters because the container's /tmp is mode 1777, so "already
    there" is not "already ours". ``redirect_tempfile_to_staging`` never
    reaches these files, since both call sites pass ``dir=`` explicitly,
    overriding ``tempfile.tempdir`` — this credential-bearing file stays off
    the shared staging volume.
    """
    directory = GDAL_HEADER_DIR
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(directory, 0o700)
    return directory


def sweep_stale_gdal_header_files(
    header_dir: Path | None = None, max_age_seconds: int = 3600
) -> int:
    """Reclaim orphaned GDAL bearer-header tempfiles under ``header_dir``.

    Defaults to ``GDAL_HEADER_DIR``, read directly rather than via
    ``gdal_header_dir()`` since this sweep reclaims, it does not provision —
    a missing directory just returns 0 rather than creating an empty 0700 dir
    on every boot. Only direct children named ``gdal_auth_*.hdr`` are
    considered, non-recursively; a file younger than ``max_age_seconds`` is
    left alone (may still be in use by ogr2ogr/ogrinfo). Never raises — a
    file that disappears mid-sweep is silently skipped. Returns the count
    removed.
    """
    header_dir = GDAL_HEADER_DIR if header_dir is None else Path(header_dir)
    if not header_dir.is_dir():
        return 0
    cutoff = time.time() - max_age_seconds
    removed = 0
    for entry in header_dir.iterdir():
        name = entry.name
        if not (
            name.startswith(_GDAL_AUTH_HEADER_PREFIX)
            and name.endswith(_GDAL_AUTH_HEADER_SUFFIX)
        ):
            continue
        try:
            if not entry.is_file():
                continue
            if entry.stat().st_mtime >= cutoff:
                continue
            entry.unlink(missing_ok=True)
            removed += 1
        except OSError:
            continue
    return removed


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

    Two contexts hit this: api (Starlette's MultiPartParser rolls
    SpooledTemporaryFile to tempfile.tempdir; the 512 MiB tmpfs `/tmp` fills
    on large uploads, gh #101) and worker (COG conversion's disk-space
    pre-flight reads tmpfs /tmp instead of the multi-GB staging volume,
    causing spurious "insufficient disk space" errors).

    Must run BEFORE FastAPI/Procrastinate/Starlette imports so the first
    request/task uses the override. Defensive on OSError so containers
    without the staging volume mounted don't crash on import.
    """
    target_dir = Path(directory)
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        if not target_dir.is_dir():
            return
    tempfile.tempdir = str(target_dir)
