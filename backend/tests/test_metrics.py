"""Tests for the Prometheus metrics module."""

import asyncio
import os
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from prometheus_client import Counter, Gauge
from prometheus_fastapi_instrumentator import Instrumentator

from app.observability.metrics import (
    _consolidate_dead_counter_and_histogram_files,
    _sweep_dead_worker_metrics_once,
    _sweep_lock_path,
    init_metrics,
    shutdown_worker_metrics,
)
from app.observability.metrics.instrumentator import create_instrumentator
from app.observability.metrics.jobs import (
    _refresh_job_metrics,
    jobs_active,
    jobs_completed_total,
    jobs_failed_total,
    jobs_queue_depth,
)
from app.observability.metrics.pool import (
    _refresh_pool_metrics,
    db_pool_checkedout,
    db_pool_checkedin,
    db_pool_overflow,
    db_pool_size,
)


def test_create_instrumentator_returns_instrumentator():
    """Instrumentator factory returns configured instance."""
    inst = create_instrumentator()
    assert isinstance(inst, Instrumentator)
    # excluded_handlers are compiled regex patterns
    handler_patterns = [p.pattern for p in inst.excluded_handlers]
    assert "/metrics" in handler_patterns
    assert "/health" in handler_patterns


def test_job_metrics_registered():
    """Job metrics are proper Prometheus types with correct names."""
    assert isinstance(jobs_queue_depth, Gauge)
    assert isinstance(jobs_active, Gauge)
    assert isinstance(jobs_completed_total, Counter)
    assert isinstance(jobs_failed_total, Counter)

    assert "geolens_jobs_queue_depth" in jobs_queue_depth._name
    assert "geolens_jobs_active" in jobs_active._name
    # Counter._name strips _total suffix; check the base name
    assert "geolens_jobs_completed" in jobs_completed_total._name
    assert "geolens_jobs_failed" in jobs_failed_total._name


def test_pool_metrics_registered():
    """Pool metrics are all Gauge instances."""
    assert isinstance(db_pool_checkedout, Gauge)
    assert isinstance(db_pool_checkedin, Gauge)
    assert isinstance(db_pool_overflow, Gauge)
    assert isinstance(db_pool_size, Gauge)


@pytest.mark.asyncio
async def test_refresh_job_metrics_handles_db_error():
    """Job metrics collector swallows database errors without raising."""
    mock_engine = MagicMock()
    mock_conn = MagicMock()
    mock_conn.execute = AsyncMock(side_effect=Exception("connection refused"))
    mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_conn.__aexit__ = AsyncMock(return_value=False)
    mock_engine.connect = MagicMock(return_value=mock_conn)

    with patch("app.core.db.engine", mock_engine):
        # Should not raise
        await _refresh_job_metrics()


def _mock_engine_returning(rows):
    result = MagicMock()
    result.fetchall.return_value = rows
    mock_conn = MagicMock()
    mock_conn.execute = AsyncMock(return_value=result)
    mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_conn.__aexit__ = AsyncMock(return_value=False)
    mock_engine = MagicMock()
    mock_engine.connect = MagicMock(return_value=mock_conn)
    return mock_engine


@pytest.mark.asyncio
async def test_refresh_job_metrics_zeroes_drained_queues():
    """fix(#655): a queue whose todo/doing rows vanish reads 0, not its last value."""
    rows = [("todo", "q655", 7), ("doing", "q655", 2)]
    with patch("app.core.db.engine", _mock_engine_returning(rows)):
        await _refresh_job_metrics()
    assert jobs_queue_depth.labels(queue="q655")._value.get() == 7.0
    assert jobs_active.labels(queue="q655")._value.get() == 2.0

    with patch("app.core.db.engine", _mock_engine_returning([])):
        await _refresh_job_metrics()
    assert jobs_queue_depth.labels(queue="q655")._value.get() == 0.0
    assert jobs_active.labels(queue="q655")._value.get() == 0.0


@pytest.mark.asyncio
async def test_refresh_pool_metrics_skips_non_queuepool():
    """Pool metrics collector skips when pool is not QueuePool."""
    mock_pool = MagicMock(spec=[])  # Empty spec -- not a QueuePool
    mock_engine = MagicMock()
    mock_engine.pool = mock_pool

    mock_settings = MagicMock()
    mock_settings.db_use_external_pooler = False

    with (
        patch("app.core.db.engine", mock_engine),
        patch("app.core.config.settings", mock_settings),
    ):
        await _refresh_pool_metrics()

    # Pool gauges should remain at their default (0)
    assert db_pool_checkedout._value.get() == 0.0
    assert db_pool_checkedin._value.get() == 0.0


# ---------------------------------------------------------------------------
# Multiprocess mode (fix #1240, #651)
#
# prometheus_client picks its value-storage backend (plain in-memory vs
# mmap-file-per-process) at the FIRST import of `prometheus_client.values` in
# a given interpreter, based on whether PROMETHEUS_MULTIPROC_DIR is already
# set. Every other test in this module has already imported prometheus_client
# in-process without that env var, so setting it here would do nothing --
# these tests spawn a fresh subprocess per simulated worker instead, which is
# the only way to exercise the real multiprocess write path.
# ---------------------------------------------------------------------------

_BACKEND_ROOT = Path(__file__).resolve().parent.parent


def _run_multiprocess_writer(multiproc_dir: str, script: str, *args: str) -> None:
    """Run `script` in a fresh subprocess with PROMETHEUS_MULTIPROC_DIR set.

    cwd=_BACKEND_ROOT so `import app...` inside the script resolves the same
    way it does for `uv run pytest` from backend/.
    """
    env = {**os.environ, "PROMETHEUS_MULTIPROC_DIR": multiproc_dir}
    result = subprocess.run(
        [sys.executable, "-c", script, *args],
        cwd=str(_BACKEND_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, (
        f"multiprocess writer subprocess failed:\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )


_HTTP_HISTOGRAM_WRITER = """
import sys
from prometheus_client import Histogram

requests = int(sys.argv[1])
# Same name prometheus_fastapi_instrumentator's default instrumentation uses
# -- the exact metric behind the #1240 demo alert (see the diagnostic query
# in that issue: sum(http_request_duration_seconds_count{...})).
h = Histogram("http_request_duration_seconds", "request duration", ["handler"])
for _ in range(requests):
    h.labels(handler="/tiles/{z}/{x}/{y}").observe(0.05)
"""


def test_multiprocess_histogram_sums_across_simulated_workers(tmp_path):
    """fix(#1240): a scrape used to see one worker's counter, not the fleet's.

    Two subprocesses simulate two uvicorn workers recording HTTP requests
    against the SAME histogram name under one PROMETHEUS_MULTIPROC_DIR (7
    requests, then 3). Before the fix a scrape landed on whichever worker
    answered -- 7 or 3, sawtoothing between the two on successive scrapes,
    which Prometheus reads as a counter reset. Merging via
    multiprocess.MultiProcessCollector must report the true total, 10, and
    that total must be stable (idempotent) across repeated reads without new
    writes -- the monotonicity rate() depends on.
    """
    multiproc_dir = str(tmp_path)
    _run_multiprocess_writer(multiproc_dir, _HTTP_HISTOGRAM_WRITER, "7")
    _run_multiprocess_writer(multiproc_dir, _HTTP_HISTOGRAM_WRITER, "3")

    from prometheus_client import CollectorRegistry, multiprocess

    def _scrape_count() -> float:
        registry = CollectorRegistry()
        multiprocess.MultiProcessCollector(registry, path=multiproc_dir)
        families = {f.name: f for f in registry.collect()}
        counts = [
            s.value
            for s in families["http_request_duration_seconds"].samples
            if s.name == "http_request_duration_seconds_count"
        ]
        return sum(counts)

    first_scrape = _scrape_count()
    assert first_scrape == 10.0
    assert first_scrape not in (7.0, 3.0)

    # A second scrape with no new writes must read the same total -- the
    # multiprocess files are additive state, not consumed by reading them.
    assert _scrape_count() == first_scrape


# Uses the real production Gauge (not a synthetic stand-in) so this test
# actually exercises memory.py's multiprocess_mode="liveall" declaration --
# a synthetic Gauge would default to "all" and miss the exact bug Codex
# found in round 1 of review (see test_..._cleaned_up_after_shutdown below).
_RSS_GAUGE_WRITER = """
import os
from app.observability.metrics.memory import worker_rss_bytes

worker_rss_bytes.labels(pid=str(os.getpid())).set(int(os.environ["_TEST_RSS_BYTES"]))
"""

# Same Gauge, but calls shutdown_worker_metrics() immediately after writing
# a value -- simulates a worker recycled under UVICORN_MAX_REQUESTS.
_RSS_GAUGE_WRITER_THEN_SHUTDOWN = """
import os
from app.observability.metrics import shutdown_worker_metrics
from app.observability.metrics.memory import worker_rss_bytes

worker_rss_bytes.labels(pid=str(os.getpid())).set(int(os.environ["_TEST_RSS_BYTES"]))
shutdown_worker_metrics()
"""


def test_multiprocess_rss_gauge_shows_every_live_worker(tmp_path):
    """fix(#651) acceptance: `geolens_worker_rss_bytes` shows every live pid
    in one scrape, not whichever single worker answered it.
    """
    multiproc_dir = str(tmp_path)
    env_base = {**os.environ, "PROMETHEUS_MULTIPROC_DIR": multiproc_dir}

    values = (100 * 1024 * 1024, 150 * 1024 * 1024)
    for rss_bytes in values:
        result = subprocess.run(
            [sys.executable, "-c", _RSS_GAUGE_WRITER],
            cwd=str(_BACKEND_ROOT),
            env={**env_base, "_TEST_RSS_BYTES": str(rss_bytes)},
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, result.stderr

    from prometheus_client import CollectorRegistry, multiprocess

    registry = CollectorRegistry()
    multiprocess.MultiProcessCollector(registry, path=multiproc_dir)
    families = {f.name: f for f in registry.collect()}
    samples = [
        s
        for s in families["geolens_worker_rss_bytes"].samples
        if s.name == "geolens_worker_rss_bytes"
    ]

    # Two distinct worker processes, both visible in the one merged scrape.
    assert {s.labels["pid"] for s in samples}.__len__() == 2
    assert sorted(s.value for s in samples) == sorted(values)


def test_multiprocess_rss_gauge_series_cleaned_up_after_shutdown(tmp_path):
    """fix(#1240, #651 review round 1): a recycled worker's RSS series must
    actually disappear once shutdown_worker_metrics() marks it dead.

    prometheus_client's mark_process_dead() only unlinks mmap files for
    Gauges declared with a "live*" multiprocess_mode -- the default "all"
    keeps a dead pid's last value forever. worker_rss_bytes declares
    "liveall" specifically so this cleanup works; a regression back to the
    default would make this assertion fail (samples would still show the
    recycled worker's stale value).
    """
    multiproc_dir = str(tmp_path)
    env_base = {**os.environ, "PROMETHEUS_MULTIPROC_DIR": multiproc_dir}

    # Worker A: recycled (writes a value, then shuts down cleanly).
    result_a = subprocess.run(
        [sys.executable, "-c", _RSS_GAUGE_WRITER_THEN_SHUTDOWN],
        cwd=str(_BACKEND_ROOT),
        env={**env_base, "_TEST_RSS_BYTES": str(100 * 1024 * 1024)},
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result_a.returncode == 0, result_a.stderr

    # Worker B: still alive (no shutdown call).
    result_b = subprocess.run(
        [sys.executable, "-c", _RSS_GAUGE_WRITER],
        cwd=str(_BACKEND_ROOT),
        env={**env_base, "_TEST_RSS_BYTES": str(150 * 1024 * 1024)},
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result_b.returncode == 0, result_b.stderr

    from prometheus_client import CollectorRegistry, multiprocess

    registry = CollectorRegistry()
    multiprocess.MultiProcessCollector(registry, path=multiproc_dir)
    families = {f.name: f for f in registry.collect()}
    samples = [
        s
        for s in families["geolens_worker_rss_bytes"].samples
        if s.name == "geolens_worker_rss_bytes"
    ]

    # Only worker B's value survives -- worker A's recycled series is gone,
    # not merely stale.
    assert [s.value for s in samples] == [150 * 1024 * 1024]


_POOL_GAUGE_WRITER = """
import sys
from app.observability.metrics.pool import db_pool_checkedout

db_pool_checkedout.set(float(sys.argv[1]))
"""


def test_multiprocess_pool_gauge_uses_livesum_not_per_pid(tmp_path):
    """fix(#651): pool.py gauges declare multiprocess_mode='livesum' so a
    scrape keeps returning ONE series -- the fleet total across live workers
    -- instead of the default 'all' mode auto-labelling by pid and silently
    multiplying the metric's cardinality (which would break any existing
    alert/dashboard expression reading the bare metric name, e.g.
    GeoLensDbPoolSaturated in infra/monitoring/alerts.yml).
    """
    assert db_pool_checkedout._multiprocess_mode == "livesum"
    assert db_pool_checkedin._multiprocess_mode == "livesum"
    assert db_pool_overflow._multiprocess_mode == "livesum"
    assert db_pool_size._multiprocess_mode == "livesum"

    multiproc_dir = str(tmp_path)
    # Two workers each report their own connection pool's checked-out count.
    _run_multiprocess_writer(multiproc_dir, _POOL_GAUGE_WRITER, "3")
    _run_multiprocess_writer(multiproc_dir, _POOL_GAUGE_WRITER, "5")

    from prometheus_client import CollectorRegistry, multiprocess

    registry = CollectorRegistry()
    multiprocess.MultiProcessCollector(registry, path=multiproc_dir)
    families = {f.name: f for f in registry.collect()}
    samples = [
        s
        for s in families["geolens_db_pool_checkedout"].samples
        if s.name == "geolens_db_pool_checkedout"
    ]

    # One series (no pid label), summed across the two simulated workers.
    assert len(samples) == 1
    assert samples[0].value == 8.0
    assert "pid" not in samples[0].labels


_LIVEALL_RSS_WRITER = """
import os
import sys
import time
from app.observability.metrics.memory import worker_rss_bytes

worker_rss_bytes.labels(pid=str(os.getpid())).set(int(os.environ["_TEST_RSS_BYTES"]))
print(os.getpid(), flush=True)
if os.environ.get("_TEST_STAY_ALIVE"):
    time.sleep(10)
"""


def test_sweep_dead_worker_metrics_reaps_only_dead_pids(tmp_path):
    """fix(#1240, #651 review round 2): a worker that's OOM-killed/SIGKILLed
    never runs shutdown_worker_metrics() (it dies mid-request, not at a
    lifespan boundary), so its series would otherwise linger until the whole
    container restarts. The periodic sweep must reap ONLY pids that are no
    longer running -- a still-alive sibling's series must survive the same
    pass, or the sweep would be indistinguishable from just deleting
    everything on a timer.
    """
    multiproc_dir = str(tmp_path)
    env_base = {**os.environ, "PROMETHEUS_MULTIPROC_DIR": multiproc_dir}

    # "Dead" worker: writes a value and exits normally with no graceful
    # shutdown call -- from the sweep's point of view this is indistinguishable
    # from a SIGKILL, since both just leave a file behind for a pid that no
    # longer exists.
    dead = subprocess.run(
        [sys.executable, "-c", _LIVEALL_RSS_WRITER],
        cwd=str(_BACKEND_ROOT),
        env={**env_base, "_TEST_RSS_BYTES": str(111 * 1024 * 1024)},
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert dead.returncode == 0, dead.stderr
    dead_pid = int(dead.stdout.strip())

    # "Alive" worker: kept running past the sweep so its series can be
    # asserted untouched.
    alive_proc = subprocess.Popen(
        [sys.executable, "-c", _LIVEALL_RSS_WRITER],
        cwd=str(_BACKEND_ROOT),
        env={
            **env_base,
            "_TEST_RSS_BYTES": str(222 * 1024 * 1024),
            "_TEST_STAY_ALIVE": "1",
        },
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        alive_pid = int(alive_proc.stdout.readline().strip())

        with patch.dict(os.environ, {"PROMETHEUS_MULTIPROC_DIR": multiproc_dir}):
            _sweep_dead_worker_metrics_once()

        from prometheus_client import CollectorRegistry, multiprocess

        registry = CollectorRegistry()
        multiprocess.MultiProcessCollector(registry, path=multiproc_dir)
        families = {f.name: f for f in registry.collect()}
        samples = [
            s
            for s in families["geolens_worker_rss_bytes"].samples
            if s.name == "geolens_worker_rss_bytes"
        ]
        pids_present = {int(s.labels["pid"]) for s in samples}

        assert dead_pid not in pids_present
        assert alive_pid in pids_present
    finally:
        alive_proc.terminate()
        alive_proc.wait(timeout=10)


_COUNTER_HISTOGRAM_WRITER = """
import sys
from prometheus_client import Counter, Histogram

n = int(sys.argv[1])
c = Counter("test_consolidate_requests_total", "reqs", ["handler"])
h = Histogram("test_consolidate_duration_seconds", "dur", ["handler"])
for _ in range(n):
    c.labels(handler="/tiles").inc()
    h.labels(handler="/tiles").observe(0.05)
"""


def _scrape_consolidate_metrics(multiproc_dir: str):
    from prometheus_client import CollectorRegistry, multiprocess

    registry = CollectorRegistry()
    multiprocess.MultiProcessCollector(registry, path=multiproc_dir)
    return {f.name: f for f in registry.collect()}


def test_consolidate_dead_counter_and_histogram_files_preserves_totals(tmp_path):
    """fix(#1240, #651 review round 4): mark_process_dead() deliberately
    never removes counter_<pid>.db / histogram_<pid>.db (their cumulative
    values still need to count toward the total), so under
    UVICORN_MAX_REQUESTS recycling those files would otherwise accumulate
    without bound across a long-running container's lifetime. The
    consolidation sweep must fold three dead workers' files into ONE
    archive file per metric type while leaving the scraped total and
    histogram shape byte-for-byte the same as before consolidation --
    exercising the real binary mmap read/write round trip
    (MmapedDict.read_all_values_from_file / write_value), not a mock.
    """
    multiproc_dir = str(tmp_path)
    env = {**os.environ, "PROMETHEUS_MULTIPROC_DIR": multiproc_dir}

    # Three "dead" workers (write, then exit -- no graceful shutdown call).
    for n in (5, 3, 7):
        result = subprocess.run(
            [sys.executable, "-c", _COUNTER_HISTOGRAM_WRITER, str(n)],
            cwd=str(_BACKEND_ROOT),
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, result.stderr

    assert len(list(tmp_path.glob("counter_*.db"))) == 3
    assert len(list(tmp_path.glob("histogram_*.db"))) == 3

    before = _scrape_consolidate_metrics(multiproc_dir)
    total_before = sum(
        s.value
        for s in before["test_consolidate_requests"].samples
        if s.name == "test_consolidate_requests_total"
    )
    count_before = sum(
        s.value
        for s in before["test_consolidate_duration_seconds"].samples
        if s.name == "test_consolidate_duration_seconds_count"
    )
    sum_before = sum(
        s.value
        for s in before["test_consolidate_duration_seconds"].samples
        if s.name == "test_consolidate_duration_seconds_sum"
    )
    assert total_before == 15.0
    assert count_before == 15.0

    with patch.dict(os.environ, {"PROMETHEUS_MULTIPROC_DIR": multiproc_dir}):
        _consolidate_dead_counter_and_histogram_files()

    # File count is now bounded regardless of how many workers died.
    assert list(tmp_path.glob("counter_*.db")) == [tmp_path / "counter_archived.db"]
    assert list(tmp_path.glob("histogram_*.db")) == [tmp_path / "histogram_archived.db"]

    after = _scrape_consolidate_metrics(multiproc_dir)
    total_after = sum(
        s.value
        for s in after["test_consolidate_requests"].samples
        if s.name == "test_consolidate_requests_total"
    )
    count_after = sum(
        s.value
        for s in after["test_consolidate_duration_seconds"].samples
        if s.name == "test_consolidate_duration_seconds_count"
    )
    sum_after = sum(
        s.value
        for s in after["test_consolidate_duration_seconds"].samples
        if s.name == "test_consolidate_duration_seconds_sum"
    )
    assert total_after == total_before
    assert count_after == count_before
    assert sum_after == sum_before

    # Idempotent: a second pass with nothing new to consolidate must not
    # change the totals (proves the archive file is never mistaken for a
    # dead worker's own file and folded into itself).
    with patch.dict(os.environ, {"PROMETHEUS_MULTIPROC_DIR": multiproc_dir}):
        _consolidate_dead_counter_and_histogram_files()
    still = _scrape_consolidate_metrics(multiproc_dir)
    total_still = sum(
        s.value
        for s in still["test_consolidate_requests"].samples
        if s.name == "test_consolidate_requests_total"
    )
    assert total_still == total_before


def test_consolidate_dead_counter_files_is_race_safe_across_workers(tmp_path):
    """fix(#1240, #651 review round 4): every live worker runs this sweep, so
    two workers can race to consolidate the same dead pid's file in the same
    pass. The os.rename() mutual-exclusion step must let only one of them
    fold that file's value into the archive -- concurrent consolidation
    calls must never double-count.

    Forces genuine simultaneity (not just "launched close together", which
    process-startup jitter alone could make sequential in practice and would
    let a broken, unsynchronized implementation pass by accident): each
    subprocess writes a ready-marker as soon as it starts, then busy-polls
    for a go-file the test only creates once BOTH markers exist, so both
    processes call the consolidation function within microseconds of each
    other.
    """
    multiproc_dir = str(tmp_path)
    env = {**os.environ, "PROMETHEUS_MULTIPROC_DIR": multiproc_dir}

    result = subprocess.run(
        [sys.executable, "-c", _COUNTER_HISTOGRAM_WRITER, "10"],
        cwd=str(_BACKEND_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr

    ready_a, ready_b = tmp_path / "ready_a", tmp_path / "ready_b"
    go = tmp_path / "go"
    sweep_script = f"""
import os
import time

ready = {{"a": {str(ready_a)!r}, "b": {str(ready_b)!r}}}[__import__("sys").argv[1]]
open(ready, "w").close()

deadline = time.monotonic() + 10
while not os.path.exists({str(go)!r}):
    if time.monotonic() > deadline:
        raise TimeoutError("go file never appeared")
    time.sleep(0.001)

os.environ["PROMETHEUS_MULTIPROC_DIR"] = {multiproc_dir!r}
from app.observability.metrics import _consolidate_dead_counter_and_histogram_files

_consolidate_dead_counter_and_histogram_files()
"""
    procs = [
        subprocess.Popen(
            [sys.executable, "-c", sweep_script, label],
            cwd=str(_BACKEND_ROOT),
            env=env,
            stderr=subprocess.PIPE,
            text=True,
        )
        for label in ("a", "b")
    ]

    deadline = time.monotonic() + 10
    while not (ready_a.exists() and ready_b.exists()):
        assert time.monotonic() < deadline, "sweeper subprocesses never became ready"
        time.sleep(0.001)
    go.touch()

    for p in procs:
        stderr = p.communicate(timeout=30)[1]
        assert p.returncode == 0, stderr

    after = _scrape_consolidate_metrics(multiproc_dir)
    total_after = sum(
        s.value
        for s in after["test_consolidate_requests"].samples
        if s.name == "test_consolidate_requests_total"
    )
    assert total_after == 10.0


def test_consolidate_archive_writes_are_serialized_across_workers(tmp_path):
    """fix(#1240, #651 review round 5): the os.rename() claim step only
    guarantees a given dead pid's SOURCE file is read by one worker -- it
    says nothing about the SHARED "<type>_archived.db" two workers both
    write into. Two dead workers here get DIFFERENT counter values (10 and
    7), so two concurrent sweepers each claim a DIFFERENT source file (no
    rename collision at all) and then both try to fold their value into the
    same archive entry. Without serializing that merge, "read current, add,
    write" from two processes is a classic lost-update race: whichever
    write lands last silently overwrites the other's contribution, and the
    archive permanently under-counts (17 becomes 10 or 7, never a crash or
    an obviously-wrong value, which is what makes this bug class dangerous).
    The fix serializes the merge with fcntl.flock() on a dedicated lock
    file; this asserts the SUM survives, not just that both processes exit
    cleanly.
    """
    multiproc_dir = str(tmp_path)
    env = {**os.environ, "PROMETHEUS_MULTIPROC_DIR": multiproc_dir}

    # Two dead workers, deliberately different values so a lost update is
    # distinguishable from a correct merge (10, 7, or 17 are all different).
    for n in (10, 7):
        result = subprocess.run(
            [sys.executable, "-c", _COUNTER_HISTOGRAM_WRITER, str(n)],
            cwd=str(_BACKEND_ROOT),
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, result.stderr
    assert len(list(tmp_path.glob("counter_*.db"))) == 2

    ready_a, ready_b = tmp_path / "ready2_a", tmp_path / "ready2_b"
    go = tmp_path / "go2"
    sweep_script = f"""
import os
import time

ready = {{"a": {str(ready_a)!r}, "b": {str(ready_b)!r}}}[__import__("sys").argv[1]]
open(ready, "w").close()

deadline = time.monotonic() + 10
while not os.path.exists({str(go)!r}):
    if time.monotonic() > deadline:
        raise TimeoutError("go file never appeared")
    time.sleep(0.001)

os.environ["PROMETHEUS_MULTIPROC_DIR"] = {multiproc_dir!r}
from app.observability.metrics import _consolidate_dead_counter_and_histogram_files

_consolidate_dead_counter_and_histogram_files()
"""
    procs = [
        subprocess.Popen(
            [sys.executable, "-c", sweep_script, label],
            cwd=str(_BACKEND_ROOT),
            env=env,
            stderr=subprocess.PIPE,
            text=True,
        )
        for label in ("a", "b")
    ]

    deadline = time.monotonic() + 10
    while not (ready_a.exists() and ready_b.exists()):
        assert time.monotonic() < deadline, "sweeper subprocesses never became ready"
        time.sleep(0.001)
    go.touch()

    for p in procs:
        stderr = p.communicate(timeout=30)[1]
        assert p.returncode == 0, stderr

    # Both dead files consolidated into one archive, and its value is the
    # SUM of both -- not whichever write happened to land last.
    assert list(tmp_path.glob("counter_*.db")) == [tmp_path / "counter_archived.db"]
    after = _scrape_consolidate_metrics(multiproc_dir)
    total_after = sum(
        s.value
        for s in after["test_consolidate_requests"].samples
        if s.name == "test_consolidate_requests_total"
    )
    assert total_after == 17.0


def test_sweep_waits_for_inflight_scrape_before_renaming(tmp_path):
    """fix(#1240, #651 review round 6): MultiProcessCollector.collect() globs
    "*.db" and then opens each matched path one by one; it tolerates a path
    disappearing between those two steps only for gauge_live*.db (an
    explicit except-continue in prometheus_client's own code, because
    mark_process_dead() is expected to race a scrape). For
    counter_*.db/histogram_*.db it re-raises FileNotFoundError, so this
    function's os.rename() claim step must never fire while a scrape holds
    the shared (reader) lock on the same PROMETHEUS_MULTIPROC_DIR.

    Proves ordering, not just "no crash": a fake scrape holds the shared
    lock for a full second before releasing; the sweep (which starts only
    once it can see the scrape is already holding the lock) must not
    complete until AFTER that release. If it completed sooner, that would
    mean the exclusive/shared flock pairing isn't actually excluding the
    sweep while a scrape is in flight -- the exact gap round 6 found.
    """
    multiproc_dir = str(tmp_path)
    env = {**os.environ, "PROMETHEUS_MULTIPROC_DIR": multiproc_dir}

    result = subprocess.run(
        [sys.executable, "-c", _COUNTER_HISTOGRAM_WRITER, "10"],
        cwd=str(_BACKEND_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr

    holding_marker = tmp_path / "scrape_holding"
    released_marker = tmp_path / "scrape_released"
    done_marker = tmp_path / "sweep_done"

    fake_scrape_script = f"""
import fcntl
import time

from app.observability.metrics import _sweep_lock_path

with open(_sweep_lock_path({multiproc_dir!r}), "a+b") as lock_file:
    fcntl.flock(lock_file, fcntl.LOCK_SH)
    open({str(holding_marker)!r}, "w").close()
    time.sleep(1.0)
    fcntl.flock(lock_file, fcntl.LOCK_UN)

with open({str(released_marker)!r}, "w") as f:
    f.write(repr(time.time()))
"""
    sweeper_script = f"""
import os
import time

while not os.path.exists({str(holding_marker)!r}):
    time.sleep(0.001)

os.environ["PROMETHEUS_MULTIPROC_DIR"] = {multiproc_dir!r}
from app.observability.metrics import _consolidate_dead_counter_and_histogram_files

_consolidate_dead_counter_and_histogram_files()

with open({str(done_marker)!r}, "w") as f:
    f.write(repr(time.time()))
"""
    scrape_proc = subprocess.Popen(
        [sys.executable, "-c", fake_scrape_script],
        cwd=str(_BACKEND_ROOT),
        env=env,
        stderr=subprocess.PIPE,
        text=True,
    )
    sweep_proc = subprocess.Popen(
        [sys.executable, "-c", sweeper_script],
        cwd=str(_BACKEND_ROOT),
        env=env,
        stderr=subprocess.PIPE,
        text=True,
    )
    scrape_stderr = scrape_proc.communicate(timeout=30)[1]
    assert scrape_proc.returncode == 0, scrape_stderr
    sweep_stderr = sweep_proc.communicate(timeout=30)[1]
    assert sweep_proc.returncode == 0, sweep_stderr

    released_at = float(released_marker.read_text())
    done_at = float(done_marker.read_text())
    assert done_at >= released_at, (
        f"sweep finished at {done_at} before the scrape released its lock "
        f"at {released_at} -- the sweep's rename raced an in-flight scrape"
    )


@pytest.mark.asyncio
async def test_metrics_endpoint_survives_concurrent_sweep(tmp_path):
    """fix(#1240, #651 review round 6): the reported symptom end to end --
    a real GET /metrics request, issued while the sweep holds the exclusive
    lock and is mid-rename, must wait and then succeed (200, correct data),
    never surface a FileNotFoundError-driven 500. Exercises the actual
    middleware wired into init_metrics(), not just the raw lock file.
    """
    multiproc_dir = str(tmp_path)

    with patch.dict(os.environ, {"PROMETHEUS_MULTIPROC_DIR": multiproc_dir}):
        result = subprocess.run(
            [sys.executable, "-c", _COUNTER_HISTOGRAM_WRITER, "5"],
            cwd=str(_BACKEND_ROOT),
            env={**os.environ, "PROMETHEUS_MULTIPROC_DIR": multiproc_dir},
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, result.stderr

        import fcntl

        from fastapi import FastAPI
        from httpx import ASGITransport, AsyncClient

        app = FastAPI()
        init_metrics(app)

        order: list[str] = []
        release_event = asyncio.Event()

        def hold_writer_lock() -> None:
            with open(_sweep_lock_path(multiproc_dir), "a+b") as lock_file:
                fcntl.flock(lock_file, fcntl.LOCK_EX)
                order.append("writer_acquired")
                loop.call_soon_threadsafe(release_event.set)
                time.sleep(0.3)
                order.append("writer_released")
                fcntl.flock(lock_file, fcntl.LOCK_UN)

        loop = asyncio.get_event_loop()
        writer_future = loop.run_in_executor(None, hold_writer_lock)
        await release_event.wait()

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/metrics")
        order.append("scrape_completed")
        await writer_future

    assert resp.status_code == 200
    assert 'test_consolidate_requests_total{handler="/tiles"} 5.0' in resp.text
    # The scrape's shared-lock wait genuinely blocked until the writer let go.
    assert order == ["writer_acquired", "writer_released", "scrape_completed"]


def test_shutdown_worker_metrics_marks_process_dead_when_multiprocess_active():
    """fix(#1240, #651): a recycled worker (UVICORN_MAX_REQUESTS, #643) must
    drop its own multiprocess files on shutdown, or a respawn leaves a stale
    series that keeps being summed into every future scrape.
    """
    with (
        patch.dict(os.environ, {"PROMETHEUS_MULTIPROC_DIR": "/tmp/whatever"}),
        patch("prometheus_client.multiprocess.mark_process_dead") as mock_mark,
    ):
        shutdown_worker_metrics()
    mock_mark.assert_called_once_with(os.getpid())


def test_shutdown_worker_metrics_noop_without_multiprocess_dir():
    """A deployment that runs the api image directly, outside either compose
    file, without setting PROMETHEUS_MULTIPROC_DIR itself, has no such var --
    shutdown must not try to mark anything dead (mark_process_dead requires
    the directory to exist and would raise otherwise).
    """
    env_without_var = {
        k: v for k, v in os.environ.items() if k != "PROMETHEUS_MULTIPROC_DIR"
    }
    with (
        patch.dict(os.environ, env_without_var, clear=True),
        patch("prometheus_client.multiprocess.mark_process_dead") as mock_mark,
    ):
        shutdown_worker_metrics()
    mock_mark.assert_not_called()
