---
phase: 260515-ilt
plan: 01
subsystem: backend/search
tags: [quicklook, raster, vrt, has_quicklook, predicate, ogc]
requires: [260515-i45]
provides: [has_quicklook-raster-vrt-truthful]
affects: [service_records.py, queries.py, test_quicklook_predicate.py]
tech_stack:
  added: []
  patterns: [record_type dispatch, centralized raster projection]
key_files:
  modified:
    - backend/app/processing/raster/queries.py
    - backend/app/modules/catalog/search/service_records.py
    - backend/tests/test_quicklook_predicate.py
decisions:
  - "Dispatch has_quicklook on record_type (raster/vrt reads raster_meta; vector/table reads Dataset column)"
  - "Move record_type local before the ogc_record dict to eliminate duplicate getattr at the STAC block"
  - "quicklook_256_uri added unconditionally to _row_to_meta (no include_ toggle) — None when absent"
metrics:
  duration: ~10 minutes
  completed: "2026-05-15"
  tasks_completed: 2
  files_modified: 3
---

# Phase 260515-ilt Plan 01: Fix has_quicklook for raster_dataset and vrt_dataset Summary

**One-liner:** Dispatch `has_quicklook` on `record_type` so raster/VRT records read from `RasterAsset.quicklook_256_uri` via `raster_meta` instead of the always-null `Dataset.quicklook_256_uri`.

## What Was Built

### Task 1 — Thread `quicklook_256_uri` and dispatch the predicate (TDD)

**RED:** Added 5 new tests to `test_quicklook_predicate.py` (raster_dataset URI-set, raster_dataset URI-null, vrt_dataset URI-set, vrt_dataset URI-null, no-leak assertion). 2 new tests failed (True cases) before implementation — confirming RED state.

**GREEN:** Three surgical edits:

1. `backend/app/processing/raster/queries.py` (+3 lines):
   - `_row_to_meta`: added `"quicklook_256_uri": row.quicklook_256_uri` to the meta dict.
   - `fetch_raster_meta_one` columns: appended `RasterAsset.quicklook_256_uri`.
   - `fetch_raster_meta_bulk` columns: appended `RasterAsset.quicklook_256_uri`.

2. `backend/app/modules/catalog/search/service_records.py` (+18, -4):
   - Moved `record_type` local (same `getattr` fallback) before the `ogc_record` dict literal.
   - Replaced the hardcoded `"has_quicklook": dataset.quicklook_256_uri is not None` with a type-dispatched expression:
     - `raster_dataset` / `vrt_dataset` → `raster_meta is not None and raster_meta.get("quicklook_256_uri") is not None`
     - all other types → `dataset.quicklook_256_uri is not None` (unchanged)
   - Removed the duplicate `record_type = getattr(...)` at the STAC block (reuses the earlier local).
   - Did NOT add `quicklook_256_uri` to the STAC properties forwarding block (no leak).

3. `backend/tests/test_quicklook_predicate.py` (+190 lines):
   - New `_create_raster_quicklook_dataset()` helper (inserts Record + Dataset + RasterAsset).
   - 5 new tests (Tests 5–9); all PASS.

### Task 2 — Regression sweep

All suites clean. No code edits in this task.

## Diff Stat

```
backend/app/modules/catalog/search/service_records.py  | 18 +-
backend/app/processing/raster/queries.py               |  3 +
backend/tests/test_quicklook_predicate.py              | 190 ++++++++++++++++
3 files changed, 207 insertions(+), 4 deletions(-)
```

## Test Results

### test_quicklook_predicate.py — 9/9 PASS (4 existing + 5 new)

```
test_has_quicklook_false_when_uri_null                                 PASSED
test_has_quicklook_true_when_uri_set                                   PASSED
test_reconcile_clears_stale_uri                                        PASSED
test_reconcile_preserves_present_uri                                   PASSED
test_has_quicklook_true_for_raster_dataset_when_raster_asset_uri_set   PASSED
test_has_quicklook_false_for_raster_dataset_when_raster_asset_uri_null PASSED
test_has_quicklook_true_for_vrt_dataset_when_raster_asset_uri_set      PASSED
test_has_quicklook_false_for_vrt_dataset_when_raster_asset_uri_null    PASSED
test_raster_response_does_not_leak_quicklook_uri_property              PASSED
9 passed in 4.47s
```

### test_ogc_record_properties.py — 18/18 PASS

All OGC record property tests pass with no regressions.

### test_raster_tiles.py — 14/14 PASS

All raster tile auth-check tests pass.

### -k "search" sweep — 129/129 PASS (1 skip, 2491 deselected)

Includes `test_vrt_catalog_175.py::TestSearchEnrichmentVrt` which exercises `dataset_to_ogc_record` with raster_meta — clean.

### Ruff

`ruff check` + `ruff format --check` clean on all three modified files.

## Live Verification

Stack up at http://localhost:8080. DB query found one `raster_dataset` record with `RasterAsset.quicklook_256_uri IS NOT NULL`:

```
id: 93839c2a-ed2c-4bfb-8169-644bb1a0d427
```

OGC items endpoint response:
```
has_quicklook: True
quicklook_256_uri leak: absent
```

- `has_quicklook` is now `true` for a raster record with a non-null `RasterAsset.quicklook_256_uri`. Previously it returned `false`.
- `quicklook_256_uri` does not appear in the response properties — no storage key leak.

No null-URI raster records in the demo DB (all raster records have quicklooks), so the false-case was verified by the new unit tests instead.

## Commits

| Hash | Message |
|------|---------|
| `098f822c` | feat(quick-260515-ilt): fix has_quicklook for raster_dataset and vrt_dataset records |

## Deviations from Plan

None — plan executed exactly as written. The secondary cleanup (reusing the `record_type` local at the STAC block instead of re-computing) was called out in the plan as acceptable and applied.

## Known Stubs

None.

## Threat Flags

None. No new network endpoints, auth paths, or schema changes. The `quicklook_256_uri` key flows through an internal dict (`raster_meta`) and is explicitly excluded from the OGC response properties.

## Self-Check: PASSED

- `backend/app/processing/raster/queries.py` — modified and committed at `098f822c`
- `backend/app/modules/catalog/search/service_records.py` — modified and committed at `098f822c`
- `backend/tests/test_quicklook_predicate.py` — modified and committed at `098f822c`
- `git status` clean after commit (no untracked files)
- 9/9 tests pass
- Ruff clean
- Live curl confirms fix is active against running stack
