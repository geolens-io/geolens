"""Prometheus metrics module for GeoLens.

Provides HTTP request instrumentation, job queue gauges, and connection pool gauges.

fix(#1240, #651): under UVICORN_WORKERS>=2 (the prod compose default), each
worker used to answer /metrics from its own local prometheus_client registry,
so successive scrapes sawtoothed between per-process values and Prometheus
read every downward step as a counter reset -- fabricating rate() traffic and
collapsing latency averages to a worker's lifetime mean. `init_metrics` itself
needs no multiprocess-specific code: prometheus_fastapi_instrumentator's
`expose()` already serves a fresh CollectorRegistry wrapped by
multiprocess.MultiProcessCollector whenever PROMETHEUS_MULTIPROC_DIR is set
(see its `metrics()` closure), and falls back to the plain default registry
otherwise. Both docker-compose.yml and docker-compose.prod.yml set
PROMETHEUS_MULTIPROC_DIR for the api service by default, so multiprocess mode
is active in dev too, not just prod -- deliberately, so bumping
UVICORN_WORKERS locally to reproduce #651 (per its own verification recipe)
needs no extra env wiring. It works correctly at UVICORN_WORKERS=1: there is
just one process's files for MultiProcessCollector to merge.
"""

import asyncio
import glob
import os
from collections.abc import Iterator

import structlog
from fastapi import FastAPI

from .instrumentator import create_instrumentator

logger = structlog.stdlib.get_logger(__name__)

# How often every worker sweeps PROMETHEUS_MULTIPROC_DIR for gauge files left
# by a sibling that died without running its own shutdown hook.
_SWEEP_INTERVAL_SECONDS = 60


def init_metrics(app: FastAPI):
    """Instrument the FastAPI app and expose /metrics endpoint."""
    instrumentator = create_instrumentator()
    instrumentator.instrument(app)
    instrumentator.expose(app, include_in_schema=False, should_gzip=True)
    return instrumentator


def shutdown_worker_metrics() -> None:
    """Mark this worker process's multiprocess metric files dead.

    fix(#1240, #651): under UVICORN_MAX_REQUESTS recycling (#643) a worker
    exits and is respawned mid-lifetime, not just at container shutdown.
    Without this, the exited worker's mmap files linger under
    PROMETHEUS_MULTIPROC_DIR and keep being summed into every future scrape
    as a stale series. No-op when multiprocess mode isn't active -- both
    compose files set PROMETHEUS_MULTIPROC_DIR by default (dev included), so
    this is live in normal local development too; it only stays unset for a
    bespoke deployment that runs the api image directly, outside these
    compose files, without setting the var itself.

    This only runs on a graceful lifespan shutdown -- see
    sweep_dead_worker_metrics() for the OOM-kill/SIGKILL case, where this
    function never gets a chance to run at all.
    """
    if "PROMETHEUS_MULTIPROC_DIR" not in os.environ:
        return
    from prometheus_client import multiprocess

    multiprocess.mark_process_dead(os.getpid())


def _dead_worker_pids() -> Iterator[int]:
    """PIDs with a live-mode multiprocess file but no longer running.

    Reads pids off of gauge_live*_<pid>.db filenames (prometheus_client's own
    naming scheme) and checks each with a signal-0 kill, the same liveness
    probe prometheus_client's own docs recommend for this exact reaping
    pattern. A pid that gets reused by an unrelated process before the next
    sweep would be skipped as "alive" -- an accepted, documented limitation
    of pid-based reaping, not something this sweep can close from inside a
    dying process.
    """
    multiproc_dir = os.environ.get("PROMETHEUS_MULTIPROC_DIR")
    if not multiproc_dir:
        return
    seen: set[int] = set()
    for path in glob.glob(os.path.join(multiproc_dir, "gauge_live*_*.db")):
        pid_str = os.path.basename(path).rsplit("_", 1)[-1].removesuffix(".db")
        try:
            pid = int(pid_str)
        except ValueError:
            continue
        if pid in seen or pid == os.getpid():
            continue
        seen.add(pid)
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            yield pid
        except PermissionError:
            # Process exists (just not signalable by us) -- treat as alive.
            continue


def _iter_dead_pid_files(prefix: str, multiproc_dir: str) -> Iterator[tuple[int, str]]:
    """Yield (pid, path) for prefix_<pid>.db files whose pid is no longer
    running. Used for counter/histogram files, which are named
    "<type>_<pid>.db" with no mode segment (unlike gauge's
    "gauge_<mode>_<pid>.db") -- see _dead_worker_pids() for that one.
    """
    for path in glob.glob(os.path.join(multiproc_dir, f"{prefix}_*.db")):
        pid_str = os.path.basename(path)[len(prefix) + 1 : -len(".db")]
        try:
            pid = int(pid_str)
        except ValueError:
            # Not a live pid's file -- e.g. the "_archived" consolidation
            # file this sweep itself writes below.
            continue
        if pid == os.getpid():
            continue
        try:
            os.kill(pid, 0)
            continue  # still alive
        except ProcessLookupError:
            pass
        except PermissionError:
            continue  # exists, just not signalable by us -- treat as alive
        yield pid, path


# fix(#1240, #651 review round 4): non-numeric suffix so _iter_dead_pid_files
# never mistakes this file itself for a dead worker's file.
_ARCHIVE_SUFFIX = "archived"


def _consolidate_dead_counter_and_histogram_files() -> None:
    """Fold dead workers' counter/histogram files into one running total per
    metric type, instead of leaving them to accumulate forever.

    mark_process_dead() (used by shutdown_worker_metrics() and the gauge
    reap above) deliberately never touches counter_<pid>.db /
    histogram_<pid>.db -- unlike a gauge, a Counter/Histogram's stored value
    is a cumulative total that the collector sums across every pid's file on
    every scrape, so simply deleting a dead pid's file would silently
    subtract its contribution and produce a downward step (a fabricated
    counter "decrease" -- exactly the sawtooth bug #1240 exists to fix).
    Under the prod default UVICORN_MAX_REQUESTS=10000, a long-running
    container recycles workers indefinitely, so those files would otherwise
    accumulate without bound, one per departed worker, and every scrape has
    to open and sum all of them.

    Folds each dead pid's file additively into a single "<type>_archived.db"
    file instead: read every (key, value, timestamp) triple straight out of
    the dead pid's raw mmap file (MmapedDict.read_all_values_from_file --
    the same binary format prometheus_client's own worker processes write,
    and the mechanism its multiprocess.MultiProcessCollector.merge() docstring
    points to for exactly this "write merged data back to mmap files" case),
    add it to whatever total is already stored under that same key in the
    archive file, and delete the source. The archive file is just another
    counter_*.db/histogram_*.db file as far as MultiProcessCollector.collect()
    is concerned (it globs "*.db" and only inspects the "counter"/"histogram"
    prefix, not the pid segment), so it keeps contributing to the summed
    total exactly as the dead files it absorbed would have. Net effect: the
    scraped total is unchanged, but file count stays O(live workers + 2)
    instead of growing with every worker ever recycled.

    Races itself safely across workers in TWO separate steps, because a
    single mutex can't cover both a per-source-file claim and a shared
    archive write:

    1. Claiming a dead pid's source file: os.rename() to a private,
       non-globbed name first -- POSIX rename is atomic, so only one
       worker's rename can succeed; the other gets FileNotFoundError on its
       own rename attempt and moves on. This alone guarantees a given dead
       pid's file is read by exactly one worker, but does NOT protect the
       archive file itself -- two workers can each successfully claim a
       DIFFERENT dead pid's file in the same pass and then both try to fold
       their value into the SAME "<type>_archived.db" at once. Without
       further synchronization that's a lost-update race (read, add, write
       is not atomic across processes): whichever worker's write lands last
       overwrites the other's, permanently under-counting the archive
       (fix(#1240, #651 review round 5)).
    2. Folding a claimed file into the archive: guarded by an exclusive
       fcntl.flock() on a dedicated "<type>_archived.db.lock" file (not the
       archive .db file itself, so the lock is independent of MmapedDict's
       own open/mmap lifecycle). The lock is held for this worker's entire
       claim-and-merge pass over ALL dead pid files for that metric type, so
       the read-modify-write of every key is fully serialized against every
       other worker. flock is released automatically by the kernel if this
       process dies while holding it, so a crash here can't deadlock a
       sibling worker's next sweep.

    If this process is killed after claiming (step 1) but before merging
    (step 2) completes, the renamed file is orphaned (invisible to both
    future scrapes and future sweeps) -- an accepted, documented residual
    risk of the same shape as the pid-reuse limitation in
    _dead_worker_pids(), not a correctness bug in the common case of a
    graceful sweep pass.
    """
    multiproc_dir = os.environ.get("PROMETHEUS_MULTIPROC_DIR")
    if not multiproc_dir:
        return
    import fcntl

    from prometheus_client.mmap_dict import MmapedDict

    for prefix in ("counter", "histogram"):
        claimed_paths = []
        for _pid, path in _iter_dead_pid_files(prefix, multiproc_dir):
            claimed_path = f"{path}.claimed"
            try:
                os.rename(path, claimed_path)
            except FileNotFoundError:
                continue  # another worker's sweep already claimed this one
            claimed_paths.append(claimed_path)

        if not claimed_paths:
            continue

        archive_path = os.path.join(multiproc_dir, f"{prefix}_{_ARCHIVE_SUFFIX}.db")
        lock_path = f"{archive_path}.lock"
        with open(lock_path, "a+b") as lock_file:
            fcntl.flock(lock_file, fcntl.LOCK_EX)
            try:
                archive = MmapedDict(archive_path)
                try:
                    for claimed_path in claimed_paths:
                        # read_all_values_from_file yields
                        # (key, value, timestamp, pos) -- the trailing byte
                        # offset is an implementation detail of the
                        # instance-level reader that write_value doesn't need.
                        for (
                            key,
                            value,
                            timestamp,
                            _pos,
                        ) in MmapedDict.read_all_values_from_file(claimed_path):
                            current, _ts = archive.read_value(key)
                            archive.write_value(key, current + value, timestamp)
                        os.remove(claimed_path)
                finally:
                    archive.close()
            finally:
                fcntl.flock(lock_file, fcntl.LOCK_UN)


def _sweep_dead_worker_metrics_once() -> None:
    """Run one reap pass (no loop, no sleep) -- split out for tests."""
    if "PROMETHEUS_MULTIPROC_DIR" not in os.environ:
        return
    from prometheus_client import multiprocess

    for pid in _dead_worker_pids():
        multiprocess.mark_process_dead(pid)
    _consolidate_dead_counter_and_histogram_files()


async def sweep_dead_worker_metrics() -> None:
    """Background loop: reap and consolidate files left by dead workers.

    fix(#1240, #651 review round 2): shutdown_worker_metrics() only runs on a
    graceful lifespan shutdown. A worker OOM-killed or SIGKILLed (the #643
    scenario this whole gauge exists to catch) never reaches that shutdown
    path, while the uvicorn supervisor stays up and respawns a replacement in
    the same PROMETHEUS_MULTIPROC_DIR -- so the dead worker's RSS and pool
    gauges would otherwise linger, inflating /metrics, until the whole
    container restarts.

    fix(#1240, #651 review round 4): under the prod default
    UVICORN_MAX_REQUESTS=10000, a long-running container recycles workers
    indefinitely, and mark_process_dead() intentionally never removes a dead
    worker's counter_<pid>.db / histogram_<pid>.db (their cumulative values
    still need to count toward the total). Left alone those files grow
    without bound -- see _consolidate_dead_counter_and_histogram_files() for
    how they get folded into one running archive file per metric type
    instead.

    No-op when multiprocess mode isn't active. Safe to run in every worker:
    both the gauge reap and the counter/histogram consolidation are
    idempotent/self-excluding once a dead pid's files are gone, so a race
    between two workers sweeping the same dead pid is harmless.
    """
    while True:
        try:
            _sweep_dead_worker_metrics_once()
        except Exception:  # broad: sweep is non-fatal; must not crash the loop
            logger.warning("Failed to sweep dead worker metrics", exc_info=True)
        await asyncio.sleep(_SWEEP_INTERVAL_SECONDS)
