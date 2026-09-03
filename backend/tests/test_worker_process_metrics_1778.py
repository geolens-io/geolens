"""fix(#1778): the job worker must publish RSS and DB-pool metrics.

``main()`` started exactly three background tasks: the health server, the job
metrics collector and credential renewal. The memory collector exists for the
case this process is most exposed to -- #643 was an OOM kill visible only in
dmesg -- and the worker carries a 4 GB mem_limit against the API's 2 GB
precisely because GDAL/OGR buffers during a large raster ingest are
memory-hungry. It ran neither that nor the pool collector, so
``GeoLensDbPoolSaturated`` could never fire for the worker either: it runs its
own engine and its own pool.
"""

from __future__ import annotations

import inspect

from app.platform.jobs import worker as worker_module


def test_worker_starts_the_memory_and_pool_collectors():
    src = inspect.getsource(worker_module.main)
    assert "update_memory_metrics()" in src, (
        "the worker publishes no RSS gauge and no watermark warning"
    )
    assert "update_pool_metrics()" in src, (
        "the worker runs its own pool, so the API's gauges do not cover it"
    )


def test_worker_cancels_them_on_shutdown():
    """Every other background task here is cancelled and gathered; so are these."""
    src = inspect.getsource(worker_module.main)
    for name in ("memory_metrics_task", "pool_metrics_task"):
        assert f"{name}.cancel()" in src, f"{name} is never cancelled"
        assert src.count(name) >= 3, (
            f"{name} must be created, cancelled and gathered like its siblings"
        )


def test_both_collectors_are_safe_off_linux():
    """Neither loop needs /proc or multiprocess mode to be importable."""
    from app.observability.metrics.memory import read_rss_bytes
    from app.observability.metrics.pool import _refresh_pool_metrics

    # read_rss_bytes returns None rather than raising when /proc is absent.
    rss = read_rss_bytes()
    assert rss is None or isinstance(rss, int)
    assert inspect.iscoroutinefunction(_refresh_pool_metrics)
