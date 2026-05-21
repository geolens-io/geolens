---
phase: 1071-known-items-closure
plan: 07
subsystem: ingest
tags: [vrt, gdal, vsi, allow-list, ssrf-defense, single-source-of-truth, refactor]

# Dependency graph
requires:
  - phase: 1068-service-ingest-hardening
    provides: 3-layer VRT hardening — validate_vrt_body + _VRT_SAFE_ENV + startswith() allow-list against 7 GDAL VSI prefixes
  - phase: 1071-known-items-closure (Plan 06)
    provides: gdal_safe_env public name (leading underscore dropped); shared GDAL env-overlay surface in raster/vrt.py
provides:
  - VRT_VSI_ALLOWED_PREFIXES exported as module-level tuple from app.processing.raster.vrt — single source of truth for the GDAL VSI prefix allow-list
  - validate_vrt_body imports the shared constant rather than maintaining a function-local copy
  - 4-test regression suite pinning constant shape, tuple type, shared-consumer wiring, and unknown-scheme rejection
affects: [future-vsi-scheme-addition, env-overlay-extensions, openapi-examples, vrt-source-classifiers]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Shared-constant proof via monkey-patch — proves consumer references shared symbol, not a private copy, by extending the constant at test time"
    - "Self-documenting deletion intent — replaced inline list with comment referencing the source-of-truth location for grep-discoverability"

key-files:
  created:
    - backend/tests/test_vrt_vsi_allowlist.py
  modified:
    - backend/app/processing/raster/vrt.py
    - backend/app/processing/ingest/validation.py

key-decisions:
  - "Constant lives in raster/vrt.py (not ingest/validation.py) — VSI prefixes are VRT semantics, co-located with _VRT_SAFE_ENV and gdal_safe_env; one-way import edge ingest → raster (no circular risk)"
  - "Alphabetically sorted (vsiaz/vsicurl/vsigs/vsimem/vsis3/vsitar/vsizip) — str.startswith() is order-agnostic so this is purely a grepability / 'looks deliberate' choice"
  - "Tuple type pinned via test_constant_is_a_tuple — str.startswith() requires tuple semantics specifically (not list/set/frozenset)"

patterns-established:
  - "Single-source-of-truth refactor pattern: extract function-local constant → module-level export → import at consumer + replace inline reference → comment block at deletion site pointing to source"
  - "Shared-constant proof test: monkey-patch the constant in BOTH modules (source + consumer-via-from-import) and assert the validator picks up the change — catches future re-inlining"

requirements-completed: [KNOWN-04]

# Metrics
duration: 12min
completed: 2026-05-21
---

# Phase 1071 Plan 07: VRT VSI allow-list consolidation Summary

**Consolidated the 7-prefix VRT VSI allow-list from a function-local tuple inside `validate_vrt_body` to a module-level `VRT_VSI_ALLOWED_PREFIXES` constant exported from `raster/vrt.py`, closing the v1015 Phase 1068 tech-debt dual-edit risk.**

## Performance

- **Duration:** ~12 min
- **Started:** 2026-05-21T13:09Z
- **Completed:** 2026-05-21T13:22Z
- **Tasks:** 3
- **Files modified:** 2 + 1 created

## Accomplishments

- Added `VRT_VSI_ALLOWED_PREFIXES: tuple[str, ...]` at module level in `backend/app/processing/raster/vrt.py` (line 80) — alphabetically sorted, fully documented with per-handler purpose comments and a leading note that future VSI scheme additions must edit this constant ONLY.
- Rewired `validate_vrt_body` in `backend/app/processing/ingest/validation.py` to `from app.processing.raster.vrt import VRT_VSI_ALLOWED_PREFIXES` and reference it directly at the `raw_path.startswith()` call site (line 134). Function-local `vsi_prefixes` tuple is gone. Docstring updated to point at the constant rather than enumerating examples that would drift.
- Created `backend/tests/test_vrt_vsi_allowlist.py` with 4 regression tests: shape pin, tuple type pin, shared-constant proof via monkey-patch, unknown-scheme rejection.
- Combined gate `test_vrt_vsi_allowlist.py + test_vrt_hardening.py` is 18/18 PASS — no regression in the existing VRT defense surface.

## Task Commits

Each task was committed atomically:

1. **Task 1: Export VRT_VSI_ALLOWED_PREFIXES from raster/vrt.py** — `447df82d` (refactor)
2. **Task 2: Wire validate_vrt_body to consume the shared constant** — `e1b49b94` (refactor)
3. **Task 3: Pin the constant's value and wiring with a regression test** — `f7c4c669` (test)

## Files Created/Modified

- `backend/app/processing/raster/vrt.py` — added `VRT_VSI_ALLOWED_PREFIXES` module-level constant (32 lines: 24-line doc-comment + 9-line tuple) positioned between `gdal_safe_env` and `_RES_MAP`.
- `backend/app/processing/ingest/validation.py` — added import (line 17), deleted 9-line function-local `vsi_prefixes` tuple, updated docstring (lines 84-87), updated consumer to `VRT_VSI_ALLOWED_PREFIXES` (line 134). Net: 10 insertions, 12 deletions.
- `backend/tests/test_vrt_vsi_allowlist.py` — 99-line test file with 4 tests in a single `TestVrtVsiAllowedPrefixes` class.

## Decisions Made

- **Constant location is raster/vrt.py (not ingest/validation.py):** VSI prefixes are VRT semantics — they belong alongside `_VRT_SAFE_ENV` (the GDAL env-overlay dict) and `gdal_safe_env` (the env-overlay constructor), which together form the "VRT subprocess hardening" surface. `ingest/validation.py` is broader (it validates ALL upload content types: shapefiles, GPKGs, raster, etc.), so the prefixes don't belong there. This also gives the import a clean one-way direction: `ingest.validation → raster.vrt`. Verified no circular import — `raster/vrt.py` imports only `app.core.config`, never anything from `ingest/`.
- **Alphabetical ordering:** Purely a grepability / "looks deliberate" choice. `str.startswith()` is order-agnostic, but a sorted list reads as a deliberate complete allow-list rather than "the order I happened to type". Locked by `test_constant_shape_and_value` which fails loudly if a future refactor accidentally re-orders.
- **Tuple type (not list/set/frozenset):** Pinned by `test_constant_is_a_tuple`. `str.startswith()` accepts tuple as a native overload — passing a list silently raises `TypeError`, but a frozenset would also fail. Tuple is the only correct type here.
- **Self-documenting deletion site:** Where the function-local tuple used to live, I left a 2-line comment block pointing at `raster/vrt.py` and citing KNOWN-04. Future maintainers grep-ing for `vsi_prefixes` will land on the comment rather than a "what happened to this?" empty space.

## Deviations from Plan

None — plan executed exactly as written. The plan's "verbatim block to insert" was preserved character-for-character (including the alphabetical ordering, per-handler doc comments, and the placement between `gdal_safe_env` and `_RES_MAP`). The plan's test file content was preserved structurally; only minor cleanup applied to imports (removed unused `os` and `Path` imports — pytest's `tmp_path` fixture provides path handling, and `os` was never referenced in the test body).

### Cosmetic adjustments

- **Removed unused imports from test file:** Plan's template included `import os` and `from pathlib import Path` — neither was referenced in any test body. Linting would flag these. Removed cleanly; doesn't affect behavior.

## Issues Encountered

None. Three smooth tasks, three smooth commits. Existing `test_vrt_hardening.py` (14 tests) continued to pass against the rewired validator; new `test_vrt_vsi_allowlist.py` (4 tests) added an explicit pin for the consolidation contract.

## Verification

Per the plan's `<verification>` block:

| Check | Result |
|-------|--------|
| `grep VRT_VSI_ALLOWED_PREFIXES backend/app/processing/raster/vrt.py` shows new constant | PASS — line 80 `VRT_VSI_ALLOWED_PREFIXES: tuple[str, ...] = (` |
| `grep VRT_VSI_ALLOWED_PREFIXES backend/app/processing/ingest/validation.py` shows import + consumer | PASS — line 17 (import), line 87 (docstring), line 134 (consumer) |
| Function-local `vsi_prefixes` tuple is GONE from validation.py | PASS — `grep vsi_prefixes` returns no matches |
| `uv run pytest backend/tests/test_vrt_vsi_allowlist.py` | PASS — 4/4 |
| `uv run pytest backend/tests/test_vrt_hardening.py` | PASS — 14/14 (no regression) |
| Combined gate | PASS — 18/18 |
| Adding a hypothetical 8th VSI scheme requires editing only `VRT_VSI_ALLOWED_PREFIXES` in vrt.py | PASS — by construction; `test_validate_vrt_body_consumes_shared_constant` proves the validator picks up monkey-patched additions without any local edit |

## Self-Check: PASSED

- `backend/app/processing/raster/vrt.py` — FOUND, contains the constant at line 80
- `backend/app/processing/ingest/validation.py` — FOUND, imports + references the constant at lines 17/134
- `backend/tests/test_vrt_vsi_allowlist.py` — FOUND (99 lines, 4 tests)
- Commit `447df82d` (Task 1) — FOUND in `git log`
- Commit `e1b49b94` (Task 2) — FOUND in `git log`
- Commit `f7c4c669` (Task 3) — FOUND in `git log`

## Next Phase Readiness

- **KNOWN-04 closed** — the v1015 Phase 1068 tech-debt followup "VRT VSI allow-list requires dual-edit when adding a new scheme" is now resolved. Future VSI scheme additions edit exactly one constant in `raster/vrt.py`; the documenting comment block and the regression test will guide the change.
- **No follow-up needed** — single-source-of-truth pattern complete. Any future env-overlay extension, source classifier, or OpenAPI example that needs the VSI prefix list now has one obvious place to import from.
- **Ready for the next plan in phase 1071** — this completes Plan 07. STATE.md / ROADMAP.md updates were explicitly out-of-scope for this executor per the orchestrator's instructions.

---
*Phase: 1071-known-items-closure*
*Plan: 07 (VRT VSI allow-list consolidation)*
*Completed: 2026-05-21*
