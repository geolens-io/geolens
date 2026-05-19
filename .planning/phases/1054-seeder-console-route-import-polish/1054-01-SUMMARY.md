---
phase: 1054-seeder-console-route-import-polish
plan: "01"
subsystem: backend-ingest
tags: [seeder, ogr2ogr, gdal, timeout, error-handling, python]
dependency_graph:
  requires: []
  provides:
    - ingest_http_timeout_seconds setting (SEED-02)
    - _strip_ogr_driver_list helper (SEED-04)
    - seeder timeout retry (SEED-02)
    - seeder data-quality skip counter (SEED-03)
  affects:
    - backend/app/processing/ingest/ogr.py
    - scripts/seed-ago-data.py
tech_stack:
  added: []
  patterns:
    - "Module-scope compiled regex for line filtering (_OGR_DRIVER_LIST_LINE_RE)"
    - "Optional trailing-group regex to handle both 'NAME (modes)' and bare 'NAME' forms"
    - "Single timeout-retry branch gated by attempt < 2 (independent of MAX_RETRIES)"
    - "Accumulator list threaded through discover_layers return tuple (no module state)"
key_files:
  created:
    - (none)
  modified:
    - backend/app/core/config.py
    - backend/app/processing/ingest/ogr.py
    - backend/tests/test_ingest_ogr_pure.py
    - scripts/seed-ago-data.py
decisions:
  - "Regex extended to optional mode-group: plan spec used r\"^\\s*->\\s*'[^']+'.*\\)\\s*$\" requiring closing ) but test input 'PCIDSK' has no mode suffix; corrected to r\"^\\s*->\\s*'[^']+'\\'s*(\\([^)]*\\))?\\s*$\""
  - "print_summary data_quality_skips parameter is optional (default None) for backward compatibility with any direct callers"
  - "discover_layers return extended to 3-tuple: (manifest, org_name, data_quality_skips)"
metrics:
  duration_seconds: 225
  completed_date: "2026-05-19"
  tasks_completed: 2
  files_changed: 4
---

# Phase 1054 Plan 01: Backend ogr2ogr Timeout Config + Driver-List Strip + Retry/Skip-Counter Summary

Closed SEED-02 (configurable GDAL HTTP timeout + per-layer timeout retry), SEED-03 (data-quality skip counter in Import Summary), and SEED-04 (strip 150-line GDAL driver enumeration from IngestionError messages) in a single backend + seeder plan.

## What Was Built

**SEED-02 — Configurable GDAL HTTP timeout:**

Added `ingest_http_timeout_seconds: int = 300` to `Settings` in `backend/app/core/config.py`. Pydantic auto-binds `INGEST_HTTP_TIMEOUT_SECONDS` from env. `run_ogr2ogr_service` in `backend/app/processing/ingest/ogr.py` now passes `str(settings.ingest_http_timeout_seconds)` as `GDAL_HTTP_TIMEOUT` instead of the hardcoded `"120"` that caused 50% timeout failure rate in the M001-7n8vpc audit.

**SEED-02 — Seeder single retry on timeout:**

`process_one` in `scripts/seed-ago-data.py` adds a timeout-shaped detection branch: when `result.status == "failed"` and the error message matches `timed? ?out|Operation timed out` (case-insensitive) and `attempt < 2`, the layer is retried once with a `Retry 1/1 for <layer> after timeout (server raised GDAL_HTTP_TIMEOUT — retrying once)` log line. The retry cap is `attempt < 2` (one retry max), independent of `MAX_RETRIES=3` for 5xx HTTP errors. A comment at the retry site explains that the seeder cannot adjust the server-side timeout — only the api service env var does that.

**SEED-03 — Data-quality skip counter:**

`discover_layers` signature extended to `-> tuple[list[dict], str, list[str]]`. A `data_quality_skips: list[str]` accumulator is populated at all three discovery-phase Skipping emission points (no service URL, failed layer probe, empty layer list). `main` unpacks the third element. `print_summary` accepts an optional `data_quality_skips` parameter and prints `Data quality skips: N (AGO upstream — see log above)` after the Failed count when non-empty.

**SEED-04 — Strip GDAL driver list from error output:**

Added `_OGR_DRIVER_LIST_LINE_RE = re.compile(r"^\s*->\s*'[^']+'\s*(\([^)]*\))?\s*$")` at module scope in `ogr.py`. Added `_strip_ogr_driver_list(stderr_text: str) -> str` pure helper that iterates lines, skips driver-list matches, collapses resulting blank-line runs. The `run_ogr2ogr_service` error path wraps `stderr.decode()` through this helper before raising `IngestionError`. The `run_ogr2ogr` (file-ingest) path is unchanged per plan scope.

## Files Changed

| File | Change |
|------|--------|
| `backend/app/core/config.py` | Added `ingest_http_timeout_seconds: int = 300` |
| `backend/app/processing/ingest/ogr.py` | Added `_OGR_DRIVER_LIST_LINE_RE`, `_strip_ogr_driver_list()`; replaced hardcoded `"120"` with `str(settings.ingest_http_timeout_seconds)`; wrapped service error path through `_strip_ogr_driver_list` |
| `backend/tests/test_ingest_ogr_pure.py` | Added `TestStripOgrDriverList` (5 tests); added `_strip_ogr_driver_list` to imports |
| `scripts/seed-ago-data.py` | `discover_layers` returns 3-tuple with `data_quality_skips`; 3 skip emission points append to accumulator; `process_one` adds timeout-retry branch; `print_summary` accepts and displays skip count; `main` unpacks new return value and passes to summary |

## Tests Added

`TestStripOgrDriverList` in `backend/tests/test_ingest_ogr_pure.py` (5 tests):

1. `test_strips_driver_list_lines_and_keeps_error` — core case: driver-list removed, ERROR line preserved
2. `test_no_driver_list_returns_unchanged` — passthrough when no driver lines present
3. `test_empty_string_returns_empty` — empty-string safety
4. `test_strips_leading_blank_line_between_driver_list_and_error` — blank lines between list and error collapsed; result starts with ERROR
5. `test_settings_has_ingest_http_timeout_seconds_default_300` — settings field exists, defaults to 300

All 80 tests in `test_ingest_ogr_pure.py` pass.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Plan regex required trailing `)` but test input lacks mode suffix**

- **Found during:** Task 1 GREEN phase (first test run)
- **Issue:** Plan specified `_OGR_DRIVER_LIST_LINE_RE = re.compile(r"^\s*->\s*'[^']+'.*\)\s*$")` which requires a closing `)` at line end. The plan's own Test 1 input includes `-> 'PCIDSK'` (bare name, no `(modes)` suffix). Some GDAL builds emit driver names without the mode annotation.
- **Fix:** Changed regex to `r"^\s*->\s*'[^']+'\s*(\([^)]*\))?\s*$"` — the mode group `(...)` is optional. This matches both `-> 'FITS' (read-only)` and bare `-> 'PCIDSK'` while remaining conservative (still requires the `-> 'NAME'` prefix shape).
- **Files modified:** `backend/app/processing/ingest/ogr.py`
- **Commit:** `14b45d16`

## Requirements Closed

- **SEED-02** — `ingest_http_timeout_seconds` setting (default 300); `run_ogr2ogr_service` uses it as `GDAL_HTTP_TIMEOUT`; seeder retries once on timeout-shaped failure
- **SEED-03** — `discover_layers` accumulates `data_quality_skips`; `print_summary` displays `Data quality skips: N`
- **SEED-04** — `_strip_ogr_driver_list` helper strips 150-line driver enumeration; service ingest error path uses it

## Self-Check

Verifying claims:

- `backend/app/core/config.py` — ingest_http_timeout_seconds: present (1 occurrence)
- `backend/app/processing/ingest/ogr.py` — settings.ingest_http_timeout_seconds: 1 usage; _strip_ogr_driver_list: 2 occurrences (definition + call site)
- `backend/tests/test_ingest_ogr_pure.py` — TestStripOgrDriverList: 5 tests, 80/80 pass
- `scripts/seed-ago-data.py` — data_quality_skips: 12 occurrences; Retry 1/1 for: 1 occurrence; py_compile: OK; --help: exit 0
- Commits: 8fd2fa24 (RED), 14b45d16 (GREEN feat), 8ce7ed76 (Task 2)

## Self-Check: PASSED
