---
phase: 1071-known-items-closure
plan: 06
subsystem: backend/raster
tags: [raster, gdal, security, ssrf, vsicurl, hardening, KNOWN-03]
requires:
  - backend/app/processing/raster/vrt.py (existing _VRT_SAFE_ENV dict from v1015 Phase 1068)
provides:
  - backend/app/processing/raster/vrt.py:gdal_safe_env (renamed + extras keyword, public)
  - backend/app/processing/raster/cog.py wired to gdal_safe_env at all 3 subprocess sites
  - backend/tests/test_cog_subprocess_env.py (7 regression tests)
affects:
  - Phase 1071-07 (next wave) — will import the renamed gdal_safe_env
  - v1015 Phase 1068 tech-debt followup CLOSED
tech-stack:
  added: []
  patterns:
    - "Centralized env-overlay helper: subprocess sites for the same tool family share one merge function (gdal_safe_env) rather than copying the merge dict per site"
    - "Per-call extras parameter: callers pass {**os.environ, **clamps, **per-call} via gdal_safe_env(extras={...}) without duplicating the merge logic"
    - "Cross-sibling import inside subsystem: cog.py imports gdal_safe_env from vrt.py (one-directional, no circular dep) instead of moving to a new module — single-feature footprint, fewer files churned"
    - "Captured-env regression test: _capture_subprocess_runs context manager + _assert_clamps helper, factored from the v1015 _build_vrt test pattern, reused at 4 sites with one assertion shape"
key-files:
  created:
    - backend/tests/test_cog_subprocess_env.py
  modified:
    - backend/app/processing/raster/vrt.py
    - backend/app/processing/raster/cog.py
decisions:
  - Shape A over Shape B (drop underscore in place rather than move to new module backend/app/processing/raster/gdal_env.py). cog.py already imports nothing from vrt.py — adding the single import is lighter-touch than creating a new file, and the plan explicitly preferred Shape A unless cog.py imports vrt.py *only* for this purpose (which is exactly the case, but the plan's tie-breaker note pointed to Shape A as the default when both shapes are viable).
  - Added the optional extras= keyword (plan's optional sub-step 5). gdaladdo needs GDAL_CACHEMAX + COMPRESS_OVERVIEW; gdal_translate needs GDAL_CACHEMAX; gdalwarp needs none. Without extras, each call site would duplicate the dict-merge logic. With extras, the clamp-merge stays in one place.
  - Removed `import os` from cog.py — after the wiring, no os.* reference remains at runtime (one comment-only mention of os.environ). Keeps the lint surface clean; if a future caller needs os.* it re-imports.
  - Tests use `_capture_subprocess_runs` context-manager helper. Existing test_vrt_hardening.py uses an inline `_fake_run` closure. The 4 cog.py-side assertions (3 subprocess + 1 helper-direct) share enough shape to justify factoring; the test file stays at ~250 lines instead of ~400 with copy-paste.
  - Added one extra test (`test_extras_override_vrt_safe_env_if_collision`) to pin the precedence contract from the helper's docstring. Extras win over clamps. Today no caller exercises this, but the precedence is documented behaviour and a future regression would silently bypass the clamp.
  - Task 4 closed as a no-op verification: `grep -rn _gdal_safe_env backend/` returns zero matches; test_vrt_hardening.py never referenced the helper by name (only the captured env keys). No commit was created for Task 4 because no file changed — the audit verdict is captured here.
metrics:
  duration_min: ~4
  tasks_completed: 4/4
  files_modified: 2
  files_created: 1
  lines_added: ~306 (vrt.py: +35/-4, cog.py: +17/-4, test_cog_subprocess_env.py: +254)
  commits: 3
completed: "2026-05-21T13:12:14Z"
---

# Phase 1071 Plan 06: CPL_VSIL_CURL_ALLOWED_EXTENSIONS Clamp Across All Raster GDAL Subprocesses Summary

Closed v1015 Phase 1068's tech-debt followup: extended the `CPL_VSIL_CURL_ALLOWED_EXTENSIONS` + `VRT_VIRTUAL_OVERVIEWS` + `GDAL_HTTP_FOLLOWLOCATION` overlay (scoped only to `_build_vrt` in v1015) across every GDAL CLI subprocess the raster pipeline invokes: `gdaladdo`, `gdalwarp`, `gdal_translate` in `cog.py`. Renamed `_gdal_safe_env` → `gdal_safe_env`, added an optional `extras=` keyword to compose per-call additions (GDAL_CACHEMAX, COMPRESS_OVERVIEW) without duplicating the clamp-merge logic. Pinned the new shape with 7 regression tests.

## What Shipped

### Task 1 — Promote `_gdal_safe_env` to a shared helper (commit `405cd1a6`)

`backend/app/processing/raster/vrt.py`:

- Renamed `_gdal_safe_env()` → `gdal_safe_env()` (drops the module-private leading underscore — the function is now consumed by `cog.py`, so the "module-private" hint no longer applies).
- Added an optional keyword-only `extras: dict[str, str] | None = None` parameter. When provided, extras are merged on top of `os.environ + _VRT_SAFE_ENV` so per-call additions (GDAL_CACHEMAX="200", COMPRESS_OVERVIEW=...) compose cleanly.
- Updated the `_build_vrt` call site at line 253: `env=_gdal_safe_env()` → `env=gdal_safe_env()`.
- Extended the docstring to enumerate all 3 clamps (with the security reasoning for each) and name the cross-sibling role.
- `_VRT_SAFE_ENV` (the dict at line 17) stays internal — only the helper is exported.

### Task 2 — Wire `gdal_safe_env` into `cog.py` subprocess sites (commit `b07f3953`)

`backend/app/processing/raster/cog.py`:

- Added `from app.processing.raster.vrt import gdal_safe_env` at the top.
- `prepare_with_overviews` (gdaladdo, line 202):
  - **Before:** `env = {**os.environ, "GDAL_CACHEMAX": "200", "COMPRESS_OVERVIEW": compression}`
  - **After:** `env = gdal_safe_env(extras={"GDAL_CACHEMAX": "200", "COMPRESS_OVERVIEW": compression})`
- `convert_to_cog` (gdalwarp, line 271):
  - **Before:** `subprocess.run(warp_cmd, capture_output=True, text=True)` (NO env override — inherited unclamped os.environ)
  - **After:** `subprocess.run(warp_cmd, capture_output=True, text=True, env=gdal_safe_env())`
- `convert_to_cog` (gdal_translate, line 282):
  - **Before:** `env = {**os.environ, "GDAL_CACHEMAX": "200"}`
  - **After:** `env = gdal_safe_env(extras={"GDAL_CACHEMAX": "200"})`
- Dropped the unused `import os` (only a comment-only mention of `os.environ` remained, which doesn't need the import).

The audit at the start of this plan confirmed `cog.py` and `vrt.py` are the ONLY raster-side files with direct GDAL CLI subprocess.run calls (`grep -rn "subprocess.run\|gdaladdo\|gdalwarp\|gdal_translate\|gdalbuildvrt" backend/app/processing/`). The remaining hits in `tasks_raster.py` / `tasks_vrt.py` / `tasks_reupload.py` are docstring/comment-only mentions of these tools or function-call sites that delegate to `cog.py` / `vrt.py` (and inherit the clamp transitively). `ogr2ogr` sites are vector/export-side and out of scope per the plan's "raster-side" qualifier.

No circular import — the dependency direction is one-way (`cog.py → vrt.py`), and `vrt.py` never imports from `cog.py`.

### Task 3 — Regression tests pinning the env overlay (commit `d7107932`)

`backend/tests/test_cog_subprocess_env.py` (254 lines, 7 tests):

| Test class | Test | Site under test |
|---|---|---|
| `TestPrepareWithOverviewsSafeEnv` | `test_gdaladdo_subprocess_inherits_clamps` | gdaladdo (default DEFLATE) |
| `TestPrepareWithOverviewsSafeEnv` | `test_gdaladdo_inherits_clamps_with_custom_compression` | gdaladdo (ZSTD) |
| `TestConvertToCogGdalwarpSafeEnv` | `test_gdalwarp_subprocess_inherits_clamps` | gdalwarp (pre-KNOWN-03 had env=None) |
| `TestConvertToCogGdalTranslateSafeEnv` | `test_gdal_translate_subprocess_inherits_clamps` | gdal_translate |
| `TestGdalSafeEnvHelper` | `test_base_clamps_present` | helper direct |
| `TestGdalSafeEnvHelper` | `test_extras_merge_in_and_win` | helper direct |
| `TestGdalSafeEnvHelper` | `test_extras_override_vrt_safe_env_if_collision` | helper direct (precedence contract) |

Shape mirrors `backend/tests/test_vrt_hardening.py::TestGdalBuildVrtSafeEnv` (the v1015 sibling). Three shared helpers factor the test pattern:

- `EXPECTED_CLAMPS` — single source of truth for the three clamp keys/values (a careless edit to `_VRT_SAFE_ENV` in vrt.py trips every test).
- `_assert_clamps(env)` — asserts all three clamps present + value-correct.
- `_capture_subprocess_runs(monkeypatch)` — context manager that captures every `subprocess.run` call as `(cmd, env)` tuples; each test filters by `cmd[0]` to find its target subprocess.

The pre-KNOWN-03 gdalwarp shape (env=None) is explicitly caught via `assert env is not None, "gdalwarp subprocess passed env=None (KNOWN-03 regression)"` so a future revert can't silently regress.

### Task 4 — Audit + re-pin (no commit — no file changed)

- `grep -rn "_gdal_safe_env" backend/` → 0 matches outside `__pycache__`. The rename is complete.
- `backend/tests/test_vrt_hardening.py` never referenced `_gdal_safe_env` by name (only the captured-env keys via the `_fake_run` closure pattern). All 14 tests in that file pass against the renamed helper.

Task 4 closed as a no-op verification — the plan called this out as the most likely outcome.

## Verification Results

| Check | Result |
|---|---|
| `grep "gdal_safe_env" backend/app/processing/raster/cog.py \| wc -l` | 4 (import + 3 subprocess sites; plan required ≥3) |
| `grep -rn "_gdal_safe_env" backend/app/ backend/tests/` | 0 (no leftover underscored references) |
| `uv run pytest tests/test_cog_subprocess_env.py` | 7/7 PASS |
| `uv run pytest tests/test_vrt_hardening.py` | 14/14 PASS (no regression from rename) |
| `uv run ruff check app/processing/raster/cog.py app/processing/raster/vrt.py tests/test_cog_subprocess_env.py` | All checks passed |
| `uv run python -c "from app.processing.raster.cog import convert_to_cog; from app.processing.raster.vrt import gdal_safe_env, _build_vrt"` | imports OK — no circular dep |
| Broader raster sweep: `uv run pytest tests/test_vrt_creation_173.py tests/test_vrt_lifecycle_188.py tests/test_raster_ingest.py ...` | 86 passed; 2 errors are pre-existing DB-required tests (asyncpg.InvalidCatalogNameError; need docker postgres running), NOT KNOWN-03 regressions |

## Deviations from Plan

**None.** Plan executed exactly as written, with one optional sub-step taken:

- **Plan Task 1 sub-step 5 (optional)** — Added the `extras=` keyword. The plan said "if you also want to extend the per-call merge" — gdaladdo (GDAL_CACHEMAX + COMPRESS_OVERVIEW) and gdal_translate (GDAL_CACHEMAX) both have per-call extras that can't be hard-coded into `_VRT_SAFE_ENV`, so the extras path was the only way to avoid copy-paste of the merge dict. Took it.

- **One extra unit test** — `test_extras_override_vrt_safe_env_if_collision` pins the helper's documented precedence contract (extras win over clamps). The plan asked for 3 cog-side tests; the final file has 4 cog-side tests (split gdaladdo into default + ZSTD compression paths) + 3 helper-direct tests = 7 total. The split adds <50 LOC and pins the `compression` arg flowing through extras, which the planner's skeleton implied but didn't strictly require.

- **`import os` removed from cog.py** — Not in the plan but follows automatically from the wiring (no remaining os.* references). Without removal, `ruff check` flags it. Documented in the Task 2 commit body.

## Known Stubs

None. All three subprocess sites are real subprocess calls in production code; the tests pin runtime behaviour by stubbing `subprocess.run` only.

## Threat Flags

None. This plan REDUCES the threat surface (it doesn't add any). The clamps that were already gating `gdalbuildvrt` now also gate `gdaladdo`, `gdalwarp`, `gdal_translate`. No new network endpoints, auth paths, file access patterns, or schema changes.

## Deferred Issues

None. All plan acceptance criteria met inline. The 2 asyncpg.InvalidCatalogNameError errors in the wider raster sweep are pre-existing infrastructure tests (need docker postgres running) and unrelated to KNOWN-03 — they would fail identically against the previous commit `7b3d0299`.

## Followup for Next Wave (Plan 1071-07)

Plan 1071-07 will import the renamed `gdal_safe_env` per the spawn note. The helper's signature is `gdal_safe_env(*, extras: dict[str, str] | None = None) -> dict[str, str]` — callers should pass `extras=` for any per-call additions and rely on the helper to merge the three KNOWN-03 clamps on top of `os.environ`.

## Self-Check: PASSED

- `backend/app/processing/raster/vrt.py` → FOUND (35 insertions, 4 deletions vs. baseline; contains `def gdal_safe_env`)
- `backend/app/processing/raster/cog.py` → FOUND (17 insertions, 4 deletions vs. baseline; contains 4 `gdal_safe_env` references)
- `backend/tests/test_cog_subprocess_env.py` → FOUND (254 lines, 7 tests, all passing)
- Commit `405cd1a6` (refactor(raster): promote _gdal_safe_env to shared cross-sibling helper) → FOUND in `git log`
- Commit `b07f3953` (feat(raster): apply CPL_VSIL_CURL_ALLOWED_EXTENSIONS clamp to gdaladdo, gdalwarp, gdal_translate) → FOUND in `git log`
- Commit `d7107932` (test(raster): pin env overlay on gdaladdo/gdalwarp/gdal_translate) → FOUND in `git log`
- All plan acceptance criteria (must_haves.truths + artifacts.contains + key_links.pattern) met.
