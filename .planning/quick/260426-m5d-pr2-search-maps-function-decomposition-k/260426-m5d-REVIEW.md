---
name: PR2 Code Review (260426-m5d)
description: Review of KISS-1 + KISS-2 + PERF-6 changes
type: quick-task-review
status: issues_found
reviewed: 2026-04-26
depth: quick
findings:
  blocker: 0
  warning: 4
---

# PR2 Code Review: 260426-m5d (KISS-1, KISS-2, PERF-6)

**Reviewed:** 2026-04-26
**Files reviewed:** 6
**Status:** issues_found (no BLOCKERs; 4 WARNINGs)

## Summary

PR2's three commits land cleanly. KISS-1 brings `search_datasets` to 73 lines (target: <80). KISS-2 collapses 74 lines of inline bulk-fetch into a single helper call. PERF-6 eliminates the post-save re-fetch with the agreed 4-tuple/5-tuple service contract.

Most concerns surfaced below are quality observations, not correctness defects. No BLOCKER-class findings.

---

## Findings

### WR-01 — `get_map_with_layers` issues 4 queries instead of 2 (read-path regression)

**Severity:** WARNING
**File:** `backend/app/modules/catalog/maps/service.py:208-224`

**Issue:** The pre-refactor `get_map_with_layers` did a single `Map + ForkedMap (alias) + User` LEFT JOIN (one query) plus the layer SELECT (second query) — 2 queries total for `GET /maps/{id}`. The refactored version now calls `get_map(...)` (1), `_fetch_layer_rows_ordered(...)` (1), and `_resolve_forked_and_owner(...)` (up to 2: one for forked-map lookup, one for owner-user lookup). For the common case where both `forked_from` and `created_by` are populated, that is **4 queries instead of 2** on every map fetch.

The PERF-6 plan justified the trade as a *save-path* win, but the public read path is the more frequent caller. The change is observable behavior for anyone monitoring DB query counts.

**Fix:** Either (a) collapse `_resolve_forked_and_owner` into a single `select(Map.name, User.username).select_from(Map).outerjoin(...)` query, or (b) keep `get_map_with_layers` on the original aliased-join shape and have only `update_map`/`duplicate_map` use the two-helper pattern.

---

### WR-02 — `_run_rrf_merge` returns `([], total)` truthy-tuple — caller short-circuits standard sort path

**Severity:** WARNING
**File:** `backend/app/modules/catalog/search/service.py:728-795`

**Issue:** When `vector_ranks` is non-empty BUT `fts_ids` is empty, `_run_rrf_merge` returns `([], total)`. That tuple is **truthy** in Python, so the walrus pattern at `service.py:856` short-circuits and returns `([], total)` without hitting `_resolve_sort_order`. Pre-refactor behavior was identical, so **not a regression**, but the truthy-tuple contract is now hidden from the caller.

**Fix:** Add a docstring note in `_run_rrf_merge`: "Returns `([], total)` rather than `None` when FTS-cap is empty; caller will return that tuple as-is." This locks the contract so future maintainers don't change it to return `None` (which would change observable behavior).

---

### WR-03 — `_resolve_forked_and_owner` two separate SELECTs vs original atomic LEFT JOIN

**Severity:** WARNING
**File:** `backend/app/modules/catalog/maps/service.py:187-205`

**Issue:** Original code did `outerjoin(ForkedMap, Map.forked_from == ForkedMap.id)` — atomic single-statement LEFT JOIN. Refactor splits into two SELECTs. Under Postgres `READ COMMITTED` (default), two consecutive SELECTs within the same transaction CAN see different snapshots if a concurrent commit lands between them. Window is microseconds, but it's now real.

**Fix:** Inline both lookups into one combined `select(Map.name, User.username).select_from(...).outerjoin(...).outerjoin(...)` to match original atomic semantics. This also fixes WR-01.

---

### WR-04 — `assert filters.q is not None` stripped by `python -O`

**Severity:** WARNING
**File:** `backend/app/modules/catalog/search/service.py:740`

**Issue:** Under `python -O`, asserts are removed. If a future caller adds a code path that doesn't gate on `filters.q.strip()`, production hits `AttributeError` while test suite (no `-O`) doesn't catch it.

**Fix:** Replace `assert` with proper runtime check + raise:
```python
if filters.q is None:
    raise ValueError("_run_rrf_merge requires filters.q to be non-None")
q_stripped = filters.q.strip()
```

---

## Items Verified Clean

- **PR1 cache contract:** `cache.py` not modified; lookup/write-through unchanged; no top-level raster imports leaked.
- **`_attach_updated_actor_identities`:** Single call inside `_run_rrf_merge`; not double-called.
- **Block 2-then-3 ordering** inside `_bulk_fetch_dataset_metadata` preserved; no `asyncio.gather` collision.
- **`.order_by(MapLayer.sort_order)`** present in `_fetch_layer_rows_ordered`; new ordering test PUTs `[2,0,1]` and asserts `[0,1,2]` with dataset binding.
- **`db.commit()` placement** unchanged; `expire_on_commit=False` keeps `map_obj` attributes valid post-commit.
- **`get_map_with_layers`** public 4-tuple shape preserved.
- **`_run_rrf_merge` signature** matches CONTEXT.md verbatim; walrus caller pattern correct.
- **Conventional-commit messages** match PR1 precedent; no AI authorship.
- **`test_update_map_layers_round_trip_sort_order`** has strong assertions, not just smoke.
- **`test_vrt_catalog_175.py`** updates correctly extend introspection to both `_handle_search` and `_bulk_fetch_dataset_metadata`.

---

## Files Reviewed

- `backend/app/modules/catalog/search/service.py`
- `backend/app/modules/catalog/search/router.py`
- `backend/app/modules/catalog/maps/service.py`
- `backend/app/modules/catalog/maps/router.py`
- `backend/tests/test_maps.py`
- `backend/tests/test_vrt_catalog_175.py`
