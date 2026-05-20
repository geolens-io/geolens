---
phase: 1063-low-followup-tickets
plan: "04"
subsystem: backend-security
tags: [security, hardening, stac, parse_bbox, ilike, sec-audit-20260519]
dependency_graph:
  requires: []
  provides:
    - SEC-FU-05: STAC GET /search intersects max_length=10000 cap
    - SEC-FU-06: parse_bbox math.isfinite guard rejecting NaN/Inf
    - SEC-FU-07: service_crud.py ILIKE escape matching service_public.py pattern
  affects:
    - backend/app/standards/stac/router.py
    - backend/app/modules/catalog/features/service.py
    - backend/app/modules/catalog/maps/service_crud.py
tech_stack:
  added: []
  patterns:
    - FastAPI Query max_length for DoS-amplifier caps
    - math.isfinite() guard for NaN/Inf coordinate rejection
    - ILIKE wildcard escape via str.replace before pattern composition
key_files:
  created:
    - backend/tests/test_stac_search_validation.py
    - backend/tests/test_parse_bbox_isfinite.py
    - backend/tests/test_maps_search_ilike_escape.py
  modified:
    - backend/app/standards/stac/router.py
    - backend/app/modules/catalog/features/service.py
    - backend/app/modules/catalog/maps/service_crud.py
decisions:
  - SEC-FU-05 max_length=10000 on GET intersects only; POST body bounded by uvicorn 1MB limit
  - SEC-FU-06 math.isfinite check fires before 6-to-4 envelope reduction so Z-axis NaN caught
  - SEC-FU-07 service_collections.py does not exist in current tree; only service_crud.py needed
  - No escape= argument on .ilike() needed; Postgres default backslash escape works correctly
metrics:
  duration: "~15 minutes"
  completed: "2026-05-20T22:26:02Z"
  tasks_completed: 3
  tests_added: 15
  files_modified: 6
---

# Phase 1063 Plan 04: SEC-FU-05 + SEC-FU-06 + SEC-FU-07 Summary

**One-liner:** Three backend input-validation hardenings — STAC intersects length cap, parse_bbox NaN/Inf guard, and ILIKE wildcard escape in maps search.

## Tasks Completed

| Task | Name | Commit (RED) | Commit (GREEN) |
|------|------|-------------|----------------|
| 1 | SEC-FU-05: STAC /search intersects max_length=10000 | d2890cc4 | 8be806d9 |
| 2 | SEC-FU-06: parse_bbox math.isfinite guard | f231f8c8 | 28e62237 |
| 3 | SEC-FU-07: service_crud.py ILIKE escape | 30efc4f5 | e9d85522 |

## What Was Built

### SEC-FU-05 — STAC GET /search intersects length cap

`backend/app/standards/stac/router.py` line 1101–1108: changed `intersects: str | None = Query(None, ...)` to `Query(None, max_length=10000, ...)`. A multi-megabyte GeoJSON string would force JSON parse + ST_GeomFromGeoJSON before any DB index could short-circuit — a cheap DoS amplifier. 10000 chars fits ~150-vertex polygons at 2-decimal-place lat/lon. POST handler (`StacSearchBody.intersects: dict`) is unaffected; it is bounded by uvicorn's 1MB body limit.

Tests: 4 tests in `test_stac_search_validation.py` — over-limit 422, just-under-limit not 422, 9000-char polygon not 422, POST body unaffected.

### SEC-FU-06 — parse_bbox math.isfinite guard

`backend/app/modules/catalog/features/service.py` lines 63–70: added `import math` and a per-coordinate `math.isfinite()` check after `float()` conversion, before the 6-to-4 envelope reduction. Python's `float()` accepts `"nan"`, `"inf"`, `"-inf"` — PostGIS handles these inconsistently and can produce malformed geometries with downstream null-pointer or sequential-scan amplification. The check fires before envelope reduction so Z-axis NaN (position 2 in a 6-element bbox) is also caught.

Tests: 6 tests in `test_parse_bbox_isfinite.py` — happy path, NaN/Inf in positions 0/1/2, 3D bbox all-finite pass, 3D bbox NaN-in-Z raises.

### SEC-FU-07 — ILIKE escape in service_crud.py

`backend/app/modules/catalog/maps/service_crud.py` lines 141–143: added `escaped = search.replace("%", r"\%").replace("_", r"\_")` before composing the ILIKE pattern. An unescaped `%` search becomes `%%` — matching every row. The same escape pattern was already in `service_public.py:407-409` from prior phases; this lifts it to the CRUD listing path.

No `escape=` argument on `.ilike()` needed — Postgres's documented default backslash escape interprets `\%` as a literal `%`.

Tests: 5 integration tests in `test_maps_search_ilike_escape.py` via `GET /maps/?search=...` — normal search, `%` literal not wildcard, `_` literal not wildcard, combined `%a_b`, normal text unchanged.

## Decisions Made

1. **POST body unaffected by SEC-FU-05**: `StacSearchBody.intersects: dict` is bounded by uvicorn's 1MB request-body limit. Only the GET query-string variant needs the explicit `max_length` cap.
2. **isfinite before envelope reduction**: Placing the `math.isfinite()` loop before the `if len(values) == 6` reduction ensures NaN in the Z position (index 2) is caught before the 6-to-4 slice discards it.
3. **service_collections.py absent**: `CONTEXT.md` referenced `service_collections.py:29-35` but `find backend/app/modules/catalog/maps -name "service_collections.py"` returned no results. The file does not exist in the current tree — likely removed or renamed during v13.6 Catalog Maps/Search Service Decomposition. The audit flagged two sites (Subagent J LOW-3 = service_crud.py, LOW-4 = service_public.py); LOW-4 (service_public.py:407-409) was already correct. Only `service_crud.py:140-147` needed the fix.
4. **No escape= on .ilike()**: PostgreSQL's documented default escape character for LIKE/ILIKE is `\`. SQLAlchemy passes the pattern verbatim; no `escape=` argument is needed. Tests confirmed the plain `.ilike(pattern)` call correctly matches literal `%` only.

## Test Results

```
15/15 new tests pass:
  test_stac_search_validation.py   4 passed
  test_parse_bbox_isfinite.py      6 passed
  test_maps_search_ilike_escape.py 5 passed

Regression tests:
  test_stac_api.py        all passed (no regressions from intersects change)
  test_ogc_features.py    all passed (no regressions from parse_bbox change)
  Total: 36 passed
```

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Test used wrong response key `items` instead of `maps`**
- **Found during:** Task 3 RED phase execution
- **Issue:** `GET /maps/` returns `{"maps": [...], "total": N}` not `{"items": [...]}`. The initial test used `resp.json()["items"]` causing `KeyError`.
- **Fix:** Changed `_search_maps()` helper to use `resp.json()["maps"]`.
- **Files modified:** `backend/tests/test_maps_search_ilike_escape.py`

**2. [Rule 2 - Cleanup] SyntaxWarnings in test docstrings (Python 3.14 stricter escape handling)**
- **Found during:** Task 3 test runs
- **Issue:** Docstring text `"\%"` and `"\_"` triggered `SyntaxWarning: invalid escape sequence` in Python 3.14.
- **Fix:** Rewrote docstring prose to avoid literal backslash-percent/backslash-underscore sequences.
- **Files modified:** `backend/tests/test_maps_search_ilike_escape.py`

## Threat Surface Scan

No new network endpoints, auth paths, file access patterns, or schema changes introduced. All changes are narrowly scoped to input validation on existing routes and helpers.

## Self-Check: PASSED

All 7 artifact files found. All 6 per-task commits verified. Key content patterns confirmed:
- `max_length=10000` present in stac/router.py (2 hits: declaration + docstring)
- `math.isfinite` present in features/service.py (1 hit)
- `replace.*%.*replace.*_` present in maps/service_crud.py (1 hit)
