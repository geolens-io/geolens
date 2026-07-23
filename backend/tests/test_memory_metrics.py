"""fix(#643): worker RSS sampling — gauge, watermark warning, rate limiting."""

import pytest

from app.observability.metrics import memory as mem


@pytest.fixture
def fixed_env(monkeypatch):
    """Pin RSS and cgroup limit so sampling is deterministic."""
    state = {"rss": 700 * 1024 * 1024, "limit": 2 * 1024 * 1024 * 1024}
    monkeypatch.setattr(mem, "read_rss_bytes", lambda: state["rss"])
    monkeypatch.setattr(mem, "read_cgroup_limit_bytes", lambda: state["limit"])
    return state


def test_sample_sets_gauge_labeled_by_pid(fixed_env):
    import os

    watch = mem.MemoryWatch()
    assert watch.sample(now=0.0) == fixed_env["rss"]
    child = mem.worker_rss_bytes.labels(pid=str(os.getpid()))
    assert child._value.get() == fixed_env["rss"]


def test_watermark_is_fraction_of_cgroup_limit(fixed_env):
    watch = mem.MemoryWatch()
    watch.sample(now=0.0)
    # 60% of the 2 GiB limit
    assert watch._warn_bytes == int(fixed_env["limit"] * 0.6)


def test_watermark_falls_back_without_limit(fixed_env, monkeypatch):
    monkeypatch.setattr(mem, "read_cgroup_limit_bytes", lambda: None)
    watch = mem.MemoryWatch()
    watch.sample(now=0.0)
    assert watch._warn_bytes == mem._WARN_DEFAULT_BYTES


def test_warning_fires_above_watermark_and_rate_limits(fixed_env, monkeypatch):
    warnings: list[dict] = []
    monkeypatch.setattr(mem.logger, "warning", lambda msg, **kw: warnings.append(kw))
    watch = mem.MemoryWatch()
    fixed_env["rss"] = int(fixed_env["limit"] * 0.7)  # above the 60% mark

    watch.sample(now=0.0)
    watch.sample(now=10.0)  # within repeat window: suppressed
    watch.sample(now=mem._WARN_REPEAT_SECONDS + 1.0)  # window elapsed: re-warns

    assert len(warnings) == 2
    assert warnings[0]["rss_mb"] == fixed_env["rss"] // (1024 * 1024)


def test_sample_noop_without_proc(monkeypatch):
    monkeypatch.setattr(mem, "read_rss_bytes", lambda: None)
    assert mem.MemoryWatch().sample(now=0.0) is None
