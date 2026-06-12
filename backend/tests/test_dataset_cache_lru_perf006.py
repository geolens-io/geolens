"""PERF-006 regression — vector-tile dataset metadata cache must be a bounded LRU.

``backend/app/processing/tiles/router.py`` cached dataset metadata in
``_dataset_cache``, an unbounded plain ``dict``. Entries were only ever
added/overwritten; expired entries were never purged and there was no max size,
so a long-lived tile worker grew one entry per distinct ``table_name`` ever tiled
and never shrank. The adjacent ``_band_stats_cache`` was deliberately bounded as
``cachetools.LRUCache(maxsize=256)`` (HYG-01) — this finding closes the
inconsistent gap.

The fix swaps ``_dataset_cache`` to ``cachetools.LRUCache(maxsize=256)`` while
keeping the per-entry TTL check on read. These tests pin the structural change:
the cache is a bounded ``LRUCache`` with a maxsize, and inserting maxsize+1
distinct keys evicts the oldest.

Pure unit test — no DB required.

Verify fail-before: revert ``_dataset_cache`` back to ``{}`` and both
``isinstance`` / eviction assertions FAIL.
"""

from cachetools import LRUCache

import app.processing.tiles.router as tiles_router


def test_dataset_cache_is_bounded_lru():
    """_dataset_cache must be a cachetools.LRUCache with a finite maxsize."""
    cache = tiles_router._dataset_cache
    assert isinstance(cache, LRUCache), (
        "_dataset_cache must be a bounded cachetools.LRUCache, not an unbounded "
        "dict (PERF-006 regression)"
    )
    assert cache.maxsize is not None and cache.maxsize > 0
    # Mirror the sibling _band_stats_cache bound.
    assert cache.maxsize == tiles_router._band_stats_cache.maxsize


def test_dataset_cache_evicts_past_capacity():
    """Inserting maxsize+1 distinct keys evicts the oldest (LRU bound holds)."""
    cache = tiles_router._dataset_cache
    maxsize = cache.maxsize

    # Snapshot + restore so we never leak test keys into the shared module cache.
    saved = dict(cache)
    try:
        cache.clear()
        for i in range(maxsize):
            cache[f"perf006_table_{i}"] = (float(i), None)
        assert len(cache) == maxsize

        # One more distinct key must evict, not grow past the bound.
        cache["perf006_table_overflow"] = (float(maxsize), None)
        assert len(cache) == maxsize, (
            "cache grew past maxsize — eviction did not fire (PERF-006 regression)"
        )
        # The oldest-inserted key is the one evicted.
        assert "perf006_table_0" not in cache
        assert "perf006_table_overflow" in cache
    finally:
        cache.clear()
        for k, v in saved.items():
            cache[k] = v
