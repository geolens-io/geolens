"""Tests for the Prometheus metrics module."""

import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from prometheus_client import Counter, Gauge
from prometheus_fastapi_instrumentator import Instrumentator

from app.observability.metrics import (
    _sweep_dead_worker_metrics_once,
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
