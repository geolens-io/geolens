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


# ING-04 (P2-04): exports temp-dir sweep age threshold. Only entries whose mtime
# is older than this many seconds are deleted on startup. In-flight large exports
# younger than 1 hour survive a rolling restart; truly orphaned crash-residue gets
# cleaned. Matches the 1-hour window used by worker stale-job recovery
# (`JOB_TIMEOUT_SECONDS` in jobs/router.py) so a 6-minute COG export that survives
# a rolling restart at the job layer also keeps its on-disk staging artifact.
EXPORTS_SWEEP_AGE_SECONDS = 3600  # 1 hour

# fix(#1435 codex round 1): the API's periodic sweeper (inside
# _stale_jobs_sweeper) calls this sweep on a short, continuous cadence (every
# few minutes) rather than only at a restart/deploy, unlike the two boot-time
# callers above. A directory's mtime is set once when the export is created
# and never advances again while ogr2ogr keeps writing the file inside it or a
# client keeps streaming it out — only an entry ADD/removal in the directory
# bumps it, not writes to an existing file's contents. Reusing
# EXPORTS_SWEEP_AGE_SECONDS there would turn "an in-flight export survives A
# restart" into "any export whose ogr2ogr run plus zip plus client-download
# time exceeds 1 hour gets deleted out from under it on the very next cycle" —
# guaranteed, not just an unlucky restart coincidence. A wider margin keeps
# the periodic pass catching only residue from a process that is truly gone.
EXPORTS_PERIODIC_SWEEP_AGE_SECONDS = 4 * EXPORTS_SWEEP_AGE_SECONDS  # 4 hours


# fix(#1532 review r7): the scratch-file pattern `LocalStorageProvider.put`
# writes through — `<name>.<32 hex>.tmp` beside its destination. An ordinary
# failure removes it, but a SIGKILL, an OOM or a power loss does not, and the
# residue sits at full or partial size under whatever prefix was being written:
# COGs, uploaded originals, VRTs, map assets. Only the export cache knew the
# pattern and it only scans its own prefix, so everything else leaked forever
# and repeated crashes ate the shared staging volume.
_LOCAL_TMP_RE = re.compile(r"\.[0-9a-f]{32}\.tmp$")

# fix(#1746 B2b review r28): the local extract of a protected OGC API
# collection. `materialise_oapif_items` removes it in a `finally` and on every
# exception, but a SIGKILL or an OOM skips both and leaves up to `MAX_BYTES`
# (2 GiB) of it in the shared staging directory forever. It carries no
# credential -- the header never becomes a file on that path -- but it is data
# read with one, and it is the largest thing this codebase writes there.
#
# The writer imports these rather than spelling the prefix again, so the sweep
# and the `mkstemp` call cannot describe different files; `test_layering`'s
# sibling suite pins that.
OAPIF_ITEMS_SCRATCH_PREFIX = "oapif_items_"
OAPIF_ITEMS_SCRATCH_SUFFIX = ".geojson"
_OAPIF_ITEMS_RE = re.compile(
    rf"^{re.escape(OAPIF_ITEMS_SCRATCH_PREFIX)}.*{re.escape(OAPIF_ITEMS_SCRATCH_SUFFIX)}$"
)

# Every scratch name this codebase creates under the staging root. A new one
# belongs HERE, in the same commit that starts writing it, rather than being
# found later as a leak: that is the sibling-site class r28 asked to close, and
# the reason this is a list rather than a second sweeper.
#
# NOT included, deliberately: `gdal_auth_*.hdr`. Those live on the container
# tmpfs under `GDAL_HEADER_DIR`, never under the staging root, and
# `sweep_stale_gdal_header_files` reclaims them on a one-hour horizon because
# they hold a credential and this one waits four.
_STAGING_SCRATCH_RES = (_LOCAL_TMP_RE, _OAPIF_ITEMS_RE)


def _is_staging_scratch(name: str) -> bool:
    return any(pattern.search(name) for pattern in _STAGING_SCRATCH_RES)


def sweep_orphaned_write_scratch(
    root: Path,
    *,
    age_threshold_seconds: int = EXPORTS_PERIODIC_SWEEP_AGE_SECONDS,
) -> int:
    """Reclaim orphaned scratch files anywhere under ``root``. Returns how many.

    Covers every name in ``_STAGING_SCRATCH_RES``: the atomic-write pattern
    ``LocalStorageProvider.put`` leaves behind, and the OGC API extract
    `service_items` writes for a protected collection.

    Aged by MTIME, which is the right signal here and not everywhere: these
    files never move, so nothing resets it, and unlike the export cache's keys
    they carry no timestamp of their own to read. The horizon is the periodic
    one for the reason ``EXPORTS_PERIODIC_SWEEP_AGE_SECONDS`` documents — a
    write still in progress must not be swept out from under itself, and a
    multi-gigabyte COG takes as long as it takes.

    Errors per entry are swallowed: a scratch file that will not stat or unlink
    is the next pass's problem, not this one's.
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


# fix(#1532 review r14): when this process last walked the tree. Module-level and
# per-process, exactly like `artifact_cache._last_sweep_at`; nothing coordinates
# replicas and nothing needs to, since each is bounding its own work.
_last_scratch_sweep_at = 0.0


def sweep_orphaned_write_scratch_occasionally(
    root: Path,
    *,
    age_threshold_seconds: int = EXPORTS_PERIODIC_SWEEP_AGE_SECONDS,
) -> int:
    """``sweep_orphaned_write_scratch``, at most once per horizon per process.

    fix(#1532 review r14): the unguarded call rode the credential sweeper's
    300 s cadence, so every API replica did a full recursive walk of the staging
    root every five minutes. That root holds originals, COGs, quicklooks, VRTs
    and map assets, so the cost is O(everything stored) and grows with the
    catalog, while what it looks for cannot be reclaimed until it is four hours
    old. Almost every pass was reading the whole tree to find nothing eligible.

    The interval IS the horizon, taken from the same argument rather than from a
    constant of its own, so the two cannot drift apart. The cost is retention:
    a file that turns eligible just after a pass waits for the next one, so the
    worst case is two horizons rather than one. That is the right trade for
    residue from a process that has already died.
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

    fix(#1435 codex round 2): a directory's own mtime is bumped only by an
    entry being added, removed, or renamed inside it — NOT by writes to an
    already-created file's contents. ogr2ogr opens its output file once and
    then writes to it for the rest of the run, so the export directory's own
    mtime freezes at file-creation time while ogr2ogr is still actively
    writing. Checking the contained file(s) too means a still-growing export
    keeps reading as fresh for as long as ogr2ogr keeps writing, regardless
    of the age threshold in force.
    """
    latest = entry.stat().st_mtime
    if entry.is_dir():
        try:
            children = list(entry.iterdir())
        except OSError:
            # fix(#1435 codex round 3): a directory that cannot be listed
            # (e.g. root-owned residue left behind by a container UID
            # change across a deploy) must not crash sweep_orphaned_exports
            # — both boot-time callers run this with no guard of their own,
            # so one unreadable entry would otherwise take down startup.
            # Fall back to the entry's own mtime.
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

    Entries whose ``stat.st_mtime`` is within the last ``age_threshold_seconds``
    are skipped (and logged) so an in-flight large export does not get truncated
    by a restart. Older entries are removed (``shutil.rmtree`` for directories,
    ``Path.unlink`` for files).

    fix(#435): the API lifespan used to delete every entry unconditionally, which
    could truncate an export owned by a *surviving* sibling Uvicorn worker sharing
    the staging volume (`docker-compose.prod.yml` runs two). Both the API and the
    worker now call this one age-aware sweeper.

    No cross-process advisory lock. The sweep is idempotent and tolerates
    losing a race or hitting unreadable residue (``ignore_errors``/
    ``missing_ok``/``OSError``), and the age threshold — not mutual exclusion
    — is what protects in-flight exports. Add a lock only if a sweeper ever
    grows a non-idempotent step.

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
            # fix(#1435 codex round 3): FileNotFoundError (raced with
            # another process / external cleanup) or PermissionError
            # (unreadable residue) — either way, skip rather than crash the
            # sweep and take down API/worker startup with it.
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


# fix(#1746): the GDAL bearer-header tempfile ogr.py and preview.py write for
# a WFS/OGC API preview/ingest (GDAL_HTTP_HEADER_FILE, 0600) is unlinked in a
# `finally` block, but a SIGKILL/OOM on the subprocess skips it, leaking the
# token-bearing file. Matched by exact prefix/suffix (mirrors
# `tempfile.mkstemp(prefix="gdal_auth_", suffix=".hdr", ...)` at both sites).
_GDAL_AUTH_HEADER_PREFIX = "gdal_auth_"
_GDAL_AUTH_HEADER_SUFFIX = ".hdr"

# fix(#1746 codex r2): the container tmpfs, deliberately NOT
# `settings.upload_staging_dir`. Both the api and the worker mount /tmp as a
# 512m tmpfs (docker-compose.yml and docker-compose.prod.yml), so it is private
# to the container, gone on restart, and never read by
# `scripts/backup-entrypoint.sh` — which tars the staging volume every cycle
# and would otherwise archive a crash-orphaned Authorization header into the
# backups. A hardcoded path rather than a setting: an operator who repointed it
# at a persistent volume would silently undo exactly that.
GDAL_HEADER_DIR = Path("/tmp/gdal-auth")


# feat(#1746) plan section 5 rule A. Measured on GDAL 3.10.3 (the worker
# image) and re-verified on 3.13.0: on a cross-host 302 libcurl under GDAL
# drops `Authorization` and forwards every other header name verbatim. Two
# things follow, and only one of them is fixable from inside the process.
# Prefer `Authorization` framing wherever the provider accepts it, because a
# service-chosen API-key header IS forwarded across a cross-host redirect and
# no GDAL option exists that would stop that; that residual is bounded
# operationally (AGENTS.md Rule 2, worker egress firewall), and it is why the
# httpx probe path refuses a cross-origin redirect outright for a header-key
# credential. And state the `Authorization` half here rather than inherit it.
#
# fix(#1746 B2b review r4): the value is IF_SAME_HOST, not NO. NO blocks
# forwarding after ANY redirect, so a protected WFS or OAPIF endpoint that
# redirects to its own canonical path -- adding a trailing slash is the common
# one -- would lose the header and answer 401. That would have regressed
# bearer imports that work today, for no gain: a same-host redirect reaches
# the host that was already validated at submission time, which is the host
# the credential is for. IF_SAME_HOST is also GDAL's current default, and it
# is set explicitly so a later change to that default cannot silently widen
# what this credential follows.
#
# This is NOT `GDAL_HTTP_FOLLOWLOCATION`, which is not a GDAL option at all
# (#937), never stopped a redirect, and must never be re-added anywhere: it
# reads as a defense and is a no-op. This one is a real config option, read by
# GDAL's /vsicurl and http drivers.
GDAL_HEADER_FILE_REDIRECT_ENV: dict[str, str] = {
    "CPL_VSIL_CURL_AUTHORIZATION_HEADER_ALLOWED_IF_REDIRECT": "IF_SAME_HOST",
}


def gdal_header_dir() -> Path:
    """The 0700 directory GDAL bearer-header files are written into.

    Created on demand by the two ``mkstemp(dir=...)`` call sites, and by
    nothing else — an install that never fetches a protected WFS/OGC layer
    never grows the directory. The chmod matters because the container's /tmp
    is mode 1777: "already there" is not "already ours".

    ``redirect_tempfile_to_staging`` does not reach these files and is not
    meant to: both call sites pass ``dir=`` explicitly, which overrides
    ``tempfile.tempdir``. That is the point — the rest of the process's
    scratch belongs on the multi-GB staging volume, and this one file, which
    holds a credential, does not.
    """
    directory = GDAL_HEADER_DIR
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(directory, 0o700)
    return directory


def sweep_stale_gdal_header_files(
    header_dir: Path | None = None, max_age_seconds: int = 3600
) -> int:
    """Reclaim orphaned GDAL bearer-header tempfiles under ``header_dir``.

    Defaults to ``GDAL_HEADER_DIR``, and deliberately reads it rather than
    calling ``gdal_header_dir()``: this sweep reclaims, it does not provision.
    A missing directory means nothing has ever written a header in this
    container and there is nothing to reclaim, so it returns 0 — creating the
    directory from here would make every boot leave an empty 0700 directory
    behind for a feature the install may never use. The explicit argument
    exists so the unit tests can point it somewhere writable.

    Only direct children named ``gdal_auth_*.hdr`` are considered, and the
    sweep never recurses. A file younger than ``max_age_seconds`` is left alone
    (still in use by a running ogr2ogr/ogrinfo subprocess).

    The tmpfs already bounds the damage — a container restart empties it — so
    this is what reclaims a leaked header inside a long-running container.

    Never raises: a file that disappears between listing and stat/unlink
    (a race with the process that owns it, or with another sweep pass) is
    silently skipped, not an error.

    Returns the number of files removed.
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
