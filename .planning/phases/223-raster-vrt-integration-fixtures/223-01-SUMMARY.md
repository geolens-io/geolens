---
phase: 223-raster-vrt-integration-fixtures
plan: 01
subsystem: testing
tags: [pytest, rasterio, gdalbuildvrt, postgis, asyncpg, anyio, vrt, integration-test]

# Dependency graph
requires:
  - phase: existing
    provides: "LocalStorageProvider, _write_tmp_tif helper, test_db_session / client / clean_tables fixtures, regenerate_vrt task at backend/app/ingest/tasks.py:2093"
provides:
  - "Behavioral-anchor integration test for regenerate_vrt (backend/tests/test_regenerate_vrt_integration.py) — single happy-path test + 4 fixtures + 15 state-mutation assertions"
  - "Reusable pattern for wiring real LocalStorageProvider + DB rows + monkey-patched task imports in strict asyncio_mode / auto anyio_mode environment"
  - "Documented recipe for the 'different event loop' asyncpg pitfall when calling Procrastinate task functions directly via .func from async tests"
  - "RASTER-VRT-FIX-01 backfilled in REQUIREMENTS.md under Backend Ingest Quality"
affects:
  - "Phase 219 regenerate_vrt 3-helper refactor (_build_vrt_to_temp, _validate_and_extract_vrt_metadata, _update_vrt_dataset_geometry) — this test is the parity anchor that refactor must preserve"

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Monkey-patch module-level imports at app.ingest.tasks.* (get_storage, generate_quicklook, async_session) rather than the source module"
    - "Override settings.upload_staging_dir so resolve_vrt_source_path resolves source asset_uris under tmp_path/storage"
    - "Call Procrastinate tasks via Task.func to bypass the queue"
    - "Commit fixture DB rows (not just flush) so regenerate_vrt's separate async_session() sees them"
    - "Rely on AnyIO auto-mode for async integration tests — do NOT mark modules with pytest.mark.asyncio"

key-files:
  created:
    - "backend/tests/test_regenerate_vrt_integration.py (421 lines, 4 fixtures + 1 test + 33 assert statements)"
  modified:
    - ".planning/REQUIREMENTS.md (add RASTER-VRT-FIX-01 bullet + traceability row + updated coverage summary)"

key-decisions:
  - "Use AnyIO auto-mode (no pytestmark) to keep fixtures and test body on the same event loop, avoiding asyncpg 'different loop' errors"
  - "Monkey-patch app.ingest.tasks.async_session inside vrt_db_state to mirror the test session factory already installed by the client fixture"
  - "Keep overlapping global-bounds rasters from _write_tmp_tif (Pitfall #3 Option A) — simpler and exercises the same pipeline"
  - "Stub generate_quicklook at app.ingest.tasks.generate_quicklook to avoid PIL/matplotlib coupling in the test"

patterns-established:
  - "Integration tests that invoke tasks using `async_session()` internally must patch the tasks module's async_session binding, not just db_module.async_session"
  - "New integration tests should omit pytestmark = pytest.mark.asyncio since the project runs on anyio_mode = auto"

requirements-completed: [RASTER-VRT-FIX-01]

# Metrics
duration: ~45min
completed: 2026-04-11
---

# Phase 223 Plan 01: Raster VRT Integration Fixtures Summary

**Behavioral-anchor pytest integration test for `regenerate_vrt` — generates 2 real GeoTIFFs, creates the full DB row graph, wires a real `LocalStorageProvider` at `tmp_path`, invokes `await regenerate_vrt.func(...)`, and asserts on 15 state mutations across storage, `RasterAsset`, `IngestJob`, `VrtGeneration`, and `Record.spatial_extent`.**

## Performance

- **Duration:** ~45 min
- **Started:** 2026-04-11T19:30Z (approx, worktree agent spawn)
- **Completed:** 2026-04-11T20:13Z
- **Tasks:** 5
- **Files modified:** 2 (1 created, 1 modified)

## Accomplishments

- Shipped `backend/tests/test_regenerate_vrt_integration.py` (421 lines, 4 fixtures + 1 async test + 33 assert statements covering 15 numbered state mutations from CONTEXT.md D-03 + bonus rasterio bounds check).
- Test passes on **unmodified** `regenerate_vrt` code in ~2.5 seconds — proving the anchor is valid BEFORE Phase 219's refactor begins.
- Zero production code changes: `git diff 99e142ad..HEAD -- backend/app/` is empty.
- Zero regression: existing mocked `TestRegenerateVrtTask` (6 tests) in `test_vrt_source_management_174.py` still green.
- `RASTER-VRT-FIX-01` backfilled into `.planning/REQUIREMENTS.md` under Backend Ingest Quality (bullet + traceability row + coverage summary updated to "5 total").
- Resolved two non-obvious test-infrastructure pitfalls (AnyIO vs pytest-asyncio, module-level `async_session` re-binding) that the research document missed. Fixes are documented inline so future integration tests can avoid the same traps.

## Task Commits

Each task was committed atomically with `--no-verify` (worktree-parallel mode):

1. **Task 1: File skeleton (docstring + imports + pytestmark)** — `49290f2f` (test)
2. **Task 2: 4 pytest fixtures (source_tifs, local_storage, quicklook_stub, vrt_db_state)** — `558a86be` (test)
3. **Task 3: Integration test body with 15 numbered assertions + bonus bounds check** — `c8a29b54` (test)
4. **Task 4: Backfill RASTER-VRT-FIX-01 into REQUIREMENTS.md** — `63d94849` (docs)
5. **Task 5: Fix event-loop & async_session binding issues uncovered during verification** — `b434b782` (test)

## Files Created/Modified

- `backend/tests/test_regenerate_vrt_integration.py` — New integration test. Module docstring references Phase 219 as downstream consumer. 4 fixtures: `source_tifs` (2x `_write_tmp_tif` under `tmp_path/storage/rasters/src-{1,2}/source.cog.tif`), `local_storage` (`LocalStorageProvider` + `app.ingest.tasks.get_storage` + `settings.upload_staging_dir` patches), `quicklook_stub` (`app.ingest.tasks.generate_quicklook` → fixed bytes), `vrt_db_state` (11 DB rows: 2 source `Record`+`Dataset`+`RasterAsset` + 1 VRT `Record`+`Dataset`+`RasterAsset` + 2 `vrt_source_links` rows + 1 `IngestJob`; commits so `regenerate_vrt`'s separate `async_session()` can see the rows; also re-patches `app.ingest.tasks.async_session`). One test `test_regenerate_vrt_happy_path_end_to_end` invokes `await regenerate_vrt.func(job_id, vrt_dataset_id)` and asserts on 15 numbered state mutations. 421 lines total.
- `.planning/REQUIREMENTS.md` — Added `RASTER-VRT-FIX-01` bullet under Backend Ingest Quality, added `| RASTER-VRT-FIX-01 | Phase 223 | Pending |` traceability row, updated coverage summary from "4 total" to "5 total". v14.0 launch total stays at 27.

## The 15 Assertions That Anchor Phase 219

From `test_regenerate_vrt_happy_path_end_to_end` body (all `# [N]` markers preserved):

1. `await storage.exists(vrt_key)` — VRT file written to storage
2. Storage read-back returns non-empty bytes AND rasterio re-opens with `count == 1` and `crs.to_epsg() == 4326`
3. `vrt_asset.status == "ready"` (was "regenerating")
4. `vrt_asset.crs_wkt` is non-None and contains "WGS" or "4326"
5. `vrt_asset.epsg == 4326`
6. `vrt_asset.band_count == 1`
7. `vrt_asset.width > 0` and `vrt_asset.height > 0`
8. `vrt_asset.sha256` is 64 hex chars AND matches `hashlib.sha256(vrt_bytes).hexdigest()`
9. `vrt_asset.size_bytes > 0`
10. `vrt_asset.last_regenerated_at is not None`
11. `vrt_asset.current_generation_id is None` (cleared after completion)
12. `job.status == "complete"`
13. `job.dataset_id == uuid.UUID(vrt_dataset_id)`
14. `VrtGeneration` row: `status == "completed"`, `duration_seconds > 0`, `completed_at is not None`, `source_count == 2`, `triggered_by == "system"`
15. `vrt_record.spatial_extent is not None` (PostGIS `ST_GeomFromText` update landed)

Plus a bonus rasterio re-open sanity check on the resulting VRT bounds (`bounds.right > bounds.left`, `bounds.top > bounds.bottom`).

## Proof of Test Pass on Unmodified Main

```
$ docker compose exec -T api uv run pytest tests/test_regenerate_vrt_integration.py::test_regenerate_vrt_happy_path_end_to_end -v
============================= test session starts ==============================
platform linux -- Python 3.13.12, pytest-9.0.2, pluggy-1.6.0
rootdir: /app
configfile: pyproject.toml
plugins: anyio-4.13.0, asyncio-1.3.0, cov-7.1.0
asyncio: mode=Mode.STRICT, ... asyncio_default_fixture_loop_scope=function

tests/test_regenerate_vrt_integration.py::test_regenerate_vrt_happy_path_end_to_end PASSED [100%]

============================== 1 passed in 2.49s ===============================
```

Existing mocked test regression check:

```
$ docker compose exec -T api uv run pytest tests/test_vrt_source_management_174.py::TestRegenerateVrtTask -q
......                                                                   [100%]
6 passed in 1.49s
```

Stability — 36 VRT-related tests run together, zero state leakage:

```
$ docker compose exec -T api uv run pytest tests/test_regenerate_vrt_integration.py tests/test_vrt_source_management_174.py tests/test_vrt_ingest_tasks.py -q
....................................                                     [100%]
36 passed in 2.71s
```

## Proof of Zero Production Code Changes

```
$ git diff 99e142ad..HEAD -- backend/app/ | wc -l
0
$ git diff 99e142ad..HEAD -- backend/app/ingest/tasks.py | wc -l
0
```

## Decisions Made

- **Use AnyIO auto-mode, not pytest-asyncio** — the project configures `anyio_mode = "auto"` alongside `asyncio_mode = "strict"` (pyproject.toml:61-67). AnyIO claims async integration fixtures; marking the module with `pytest.mark.asyncio` causes pytest-asyncio to hijack the test and run fixtures on a different event loop than the test body.
- **Patch `app.ingest.tasks.async_session` inline in `vrt_db_state`** — mirror the test session factory already installed by the `client` fixture into the `tasks` module so `regenerate_vrt`'s internal `async with async_session() as session:` uses the test engine on the right loop.
- **Kept overlapping global-bounds rasters** — `_write_tmp_tif` hard-codes `from_bounds(-180, -90, 180, 90, ...)`. Rather than duplicate the helper for distinct bounds, accepted the overlap (Option A in Research §Pitfall #3). `gdalbuildvrt` handles overlap fine and the pipeline exercises every line of `regenerate_vrt` identically.
- **Committed fixture rows** — `regenerate_vrt` opens its own `async_session()` and cannot see uncommitted rows, so `vrt_db_state` ends with `await session.commit()`.
- **Opted into `clean_tables`** — prevents the 11 fixture rows from polluting neighbor tests that list or count datasets; confirmed by running all VRT tests together (36 passed, zero state leakage).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Remove `pytestmark = pytest.mark.asyncio`**
- **Found during:** Task 5 (verification run)
- **Issue:** The plan (following Research §Pitfall #7) instructed to set `pytestmark = pytest.mark.asyncio` because `backend/pyproject.toml:66` has `asyncio_mode = "strict"`. But the same config file line 65 also sets `anyio_mode = "auto"`, with an inline comment explicitly stating that **AnyIO owns integration tests** and pytest-asyncio must NOT hijack DB-backed fixtures. Marking the module with `pytest.mark.asyncio` caused pytest-asyncio to run `client`, `test_db_session`, etc. on a fixture-scoped event loop DIFFERENT from the test body's loop, and asyncpg raised `RuntimeError: Task got Future attached to a different loop` on the very first `session.execute(...)`.
- **Fix:** Removed `pytestmark = pytest.mark.asyncio` and replaced it with a block-comment explaining the AnyIO rationale so future readers don't re-introduce it. Verified that existing integration tests (`backend/tests/test_vrt_ingest_tasks.py`) use the same no-pytestmark pattern and pass.
- **Files modified:** `backend/tests/test_regenerate_vrt_integration.py`
- **Verification:** `pytest tests/test_regenerate_vrt_integration.py -xvs` → 1 passed in 2.6s; existing mocked test still green (6 passed).
- **Committed in:** `b434b782`

**2. [Rule 3 - Blocking] Add `monkeypatch.setattr(app.ingest.tasks, "async_session", db_module.async_session)` in `vrt_db_state`**
- **Found during:** Task 5 (verification run, discovered while diagnosing the event-loop error)
- **Issue:** `backend/app/ingest/tasks.py:14` does `from app.database import async_session`, which creates a binding in the `tasks` module at import time that points at the production `async_sessionmaker`. The `client` fixture in `conftest.py:154` patches `db_module.async_session = test_session_factory`, but that does NOT update the already-bound name inside `app.ingest.tasks`. The `regenerate_vrt` function at `tasks.py:2142` does `async with async_session() as session:` which resolves to the still-production binding. Result: the task opens a session on the production engine (whose asyncpg pool was initialized lazily on a different loop), and asyncpg raises "different loop" even after fixing Deviation #1.
- **Fix:** Added `monkeypatch.setattr(tasks_module, "async_session", db_module.async_session)` at the top of `vrt_db_state` (which already depends on `test_db_session` → `client`, guaranteeing `db_module.async_session` is the test factory at this point). This mirrors the existing pattern that `test_vrt_source_management_174.py` uses for `app.ingest.tasks.build_vrt` and `app.ingest.tasks.async_session` — confirming the research's Pitfall #1 applies to `async_session` too, which the plan didn't call out.
- **Files modified:** `backend/tests/test_regenerate_vrt_integration.py`
- **Verification:** Combined with Fix #1, `pytest tests/test_regenerate_vrt_integration.py -xvs` passes in 2.6s. Test is stable across repeat runs (2.61s, 2.46s).
- **Committed in:** `b434b782`

---

**Total deviations:** 2 auto-fixed (both Rule 3 — blocking test-infrastructure issues)
**Impact on plan:** Both fixes were necessary for the anchor test to pass. They stemmed from research gaps (the research identified the `get_storage` and `generate_quicklook` module-level import pitfall but missed that `async_session` has the same issue, and cited `asyncio_mode = "strict"` without noticing that `anyio_mode = "auto"` coexists in the same config block). Fixes are documented inline so Phase 219 and future integration tests inherit the working pattern. No scope creep — both changes are confined to the new test file and add ~25 lines total.

## Issues Encountered

- **`RuntimeError: Task got Future attached to a different loop`** on first run against unmodified main. Diagnosed to two distinct root causes (see Deviations above). Neither is a bug in `regenerate_vrt`; both are test-infrastructure setup oversights.
- Initial research prescription (`pytestmark = pytest.mark.asyncio`) was wrong for this project's config. Resolved by inspecting `pyproject.toml` `[tool.pytest.ini_options]` block more carefully and comparing with existing `test_vrt_ingest_tasks.py` which uses no pytestmark.

## User Setup Required

None — the test runs entirely inside the backend container using existing fixtures, rasterio, numpy, and `gdalbuildvrt` (all already installed).

## Next Phase Readiness

**Phase 219 (`regenerate_vrt` 3-helper refactor) is unblocked.** Use `backend/tests/test_regenerate_vrt_integration.py` as the behavioral parity anchor. Run it before starting Phase 219 (to confirm the baseline) and after every refactor step (to confirm the 3-helper extraction produces the same 15 state mutations). Any drift in the observable outcome of `regenerate_vrt` will fail this test — that is the entire point.

**Suggested Phase 219 workflow:**
1. Checkout main, run `pytest tests/test_regenerate_vrt_integration.py` → confirm green.
2. Extract `_build_vrt_to_temp` helper, re-run → must still be green.
3. Extract `_validate_and_extract_vrt_metadata` helper, re-run → must still be green.
4. Extract `_update_vrt_dataset_geometry` helper, re-run → must still be green.
5. If any step fails, Phase 219's extraction introduced a behavioral regression — fix before proceeding.

## Self-Check: PASSED

- FOUND: `backend/tests/test_regenerate_vrt_integration.py` (421 lines)
- FOUND: `.planning/REQUIREMENTS.md` (modified with 3 RASTER-VRT-FIX-01 occurrences)
- FOUND commit: `49290f2f` (Task 1 — test skeleton)
- FOUND commit: `558a86be` (Task 2 — 4 fixtures)
- FOUND commit: `c8a29b54` (Task 3 — test body with 15 assertions)
- FOUND commit: `63d94849` (Task 4 — REQUIREMENTS.md backfill)
- FOUND commit: `b434b782` (Task 5 — event-loop & async_session fixes)
- VERIFIED: `git diff 99e142ad..HEAD -- backend/app/` → 0 lines
- VERIFIED: `git diff 99e142ad..HEAD -- backend/app/ingest/tasks.py` → 0 lines
- VERIFIED: `pytest tests/test_regenerate_vrt_integration.py::test_regenerate_vrt_happy_path_end_to_end` → 1 passed
- VERIFIED: `pytest tests/test_vrt_source_management_174.py::TestRegenerateVrtTask` → 6 passed (zero regression)
- VERIFIED: All 15 numbered assertion markers `# [1]`..`# [15]` present in test body
- VERIFIED: All 3 monkey-patch targets (`app.ingest.tasks.get_storage`, `app.ingest.tasks.generate_quicklook`, `settings.upload_staging_dir`) present
- VERIFIED: `Record` (not `DatasetRecord`) imported from `app.datasets.models`

---
*Phase: 223-raster-vrt-integration-fixtures*
*Plan: 01*
*Completed: 2026-04-11*
