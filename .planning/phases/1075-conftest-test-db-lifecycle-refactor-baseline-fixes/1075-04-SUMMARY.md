---
phase: 1075-conftest-test-db-lifecycle-refactor-baseline-fixes
plan: 04
subsystem: testing
tags: [pytest, test-maps-style-json, builder-key-canonicalization, phase-1060-drift, test-only-fix]

requires: [1075-01]
provides:
  - "test_maps_style_json.py: 32/32 PASSED under both `pytest -x` and `pytest -n 2`"
  - "MapLibre style-JSON round-trip pin restored — parse-import assertions now match the post-Phase-1060 snake_case persistence canonical form"
affects: [1075-05]

tech-stack:
  added: []
  patterns:
    - "Build-vs-parse asymmetry detection: when 5 tests in a single style-JSON file all fail at `parse_maplibre_style_import` assertions (not `build_maplibre_style`), suspect a Pydantic model_validator on the import-side schema (here, MapLayerInput) that canonicalizes a sub-field at the persistence boundary. The wire format (export) and the storage format (import) are intentionally allowed to diverge — a frontend-visible camelCase contract can coexist with a snake_case DB contract — but tests need to know which side they're asserting against."
    - "Single-commit-for-shared-root-cause precedent (consistent with Plan 02): when N tests in the same file fail with the same exception class + same underlying drift commit, one atomic commit fixing all N is more honest than N separate commits. The commit message must enumerate every fixed test name for traceability."

key-files:
  created: []
  modified:
    - "backend/tests/test_maps_style_json.py (+37 / -18 = 19 net lines: 5 assertion blocks updated to snake_case, each prefaced by a 3-line comment block citing Phase 1060 commit a400eb89 and explaining the wire-vs-storage asymmetry)"

key-decisions:
  - "Test-only fix, no production-code touched. Phase 1060's `canonicalize_builder_style_config` is intentional hardening (fixes a duplicate-layer schema-split-brain bug) and stays. The 5 tests' camelCase assertions were stale relative to the post-1060 import contract."
  - "Single atomic commit for all 5 fixes (mirrors Plan 02's TestReuploadOrphanGuard precedent). The 5 failures share one drift source (commit a400eb89) and one fix shape (snake_case assertion). Splitting into 5 commits would obscure the shared root cause and clutter the log without isolation benefit. Plan 03's two-commit pattern was correct THERE because the 3 tests had two independent root causes; here, all 5 share one."
  - "Arrow size/spacing values become floats post-Phase-1060 because `_builder_from_arrow_companion` (style_json.py:1028-1048) runs the layout values through `_finite_number`, which `float()`s integer inputs. Updated assertion uses `18.0`/`120.0` rather than `18`/`120`. This is orthogonal to the snake_case canonicalization but surfaces alongside it because both happen in the same parse-import code path."
  - "`symbol.iconImage` stays camelCase. The Phase 1060 `_BUILDER_CAMEL_TO_SNAKE_KEYS` map only covers `builder.*` keys (outlineColor, heightColumn, clusterRadius, etc.). The `symbol` block is not in the map, so iconImage/iconSize/iconRotation/iconAnchor/iconOffset persist as-is. Verified by the still-passing test_parse_maplibre_style_import_matches_geolens_sources_and_warns_external assertion at line 868: `symbol: {iconImage: bus}` is unchanged."

patterns-established:
  - "Build-vs-parse asymmetry as a deliberate contract: GeoLens's MapLibre style-JSON layer has a one-way canonicalization — the WIRE format (build) is camelCase (frontend convention), the STORAGE format (parse → MapLayerInput → DB) is snake_case (Python convention). Tests asserting on one side cannot reuse the other side's casing. When a new test is written, decide first which boundary it pins, then choose the casing accordingly."
  - "Inventory-first triage applied a third time (after Plans 02 + 03): run-then-decide remains the right protocol. The plan's HYPOTHESIS framework correctly enumerated 5 possible causes (lifecycle, ORM drift, Pydantic drift, schema drift, cluster/DEM/3D drift) — the actual cause was HYPOTHESIS 2 (style-JSON schema drift) with a Phase 1060 source. The triage step (read 5 tracebacks, identify the shared failure shape) collapsed 5 separate investigations into a single fix."

requirements-completed: [TI-02 (partial — 5 of 11 baseline failures, the test_maps_style_json.py subset)]

duration: ~10min
completed: 2026-05-21
---

# Phase 1075 Plan 04: Fix test_maps_style_json.py 5 Failures (TI-02 partial) Summary

**All 5 v1015 baseline failures in `backend/tests/test_maps_style_json.py` shared a single root cause — Phase 1060 commit `a400eb89` ("fix(1060): e2e triage + fix — multi-select aria-selected drift + duplicate camelCase persistence") added a `model_validator(mode='after')` to `MapLayerInput` that canonicalizes `style_config.builder.*` keys to snake_case for storage parity. The five tests asserting the pre-1060 camelCase builder shape on the parse-side became stale on the same day; the build-side (`build_maplibre_style`) still emits camelCase to the wire because the export contract serves the frontend. Fix: update each of the 5 assertions to expect snake_case `builder.*` keys, matching the persistence canonical form. Single atomic commit (5 tests, 1 shape, 1 cause). Test-only diff (37+/18-). Zero production-code drift. 32/32 PASSED sequential AND parallel.**

## Performance

- **Duration:** ~10 min
- **Started:** 2026-05-21 (post Plan 03 metadata commit)
- **Completed:** 2026-05-21
- **Tasks:** 4 (Task 1 triage → Task 2 fix x1 commit → Task 3 N/A no skips → Task 4 verify)
- **Files modified:** 1 (test-only)

## Accomplishments

- **Identified the 5 failures' shared root cause from a single triage run.** All 5 raised assertions on `MapLayerInput.style_config.builder.*` where the imported value was snake_case but the test expected camelCase. The 5 tracebacks matched in shape (4× `AssertionError` on dict equality, 1× `KeyError` on the camelCase index) and all pointed to the same Pydantic post-validator added by `a400eb89`.
- **Confirmed Plan 01's lifecycle fix held.** `grep -c "InvalidCatalogNameError" /tmp/maps_run.log` → 0 on the initial triage run AND on both verify runs. The 5 failures are pure test-vs-production drift — the same negative-result data point Plans 02 + 03 reported.
- **Restored 32/32 PASSED in `test_maps_style_json.py`** under both `pytest -x` (sequential) and `pytest -n 2` (parallel). Zero `InvalidCatalogNameError`. Zero `FAILED`. Zero `ERROR`. Zero `SKIPPED`.
- **Zero production-code changes.** Phase 1060's canonicalization step stays — it fixes a duplicate-layer schema-split-brain bug that predates Phase 1075. Plan's hard scope gate respected (`git diff --stat backend/app/` → empty).
- **No GitHub issues filed and no `pytest.mark.skip` annotations needed.** All 5 failures were root-cause-fixable as a single shared assertion update; the skip-with-issue fallback path (Task 3) was not exercised.

## The 5 Originally-Failing Tests + Dispositions

| Test | Disposition | Fix Shape | Commit |
|------|-------------|-----------|--------|
| `test_parse_maplibre_style_import_preserves_cluster_intent_metadata` | **fixed** | `clusterRadius/clusterMaxZoom/clusterColor/clusterTextColor/clusterTextSize` → `cluster_radius/cluster_max_zoom/cluster_color/cluster_text_color/cluster_text_size` (5 keys) | `022c5536` |
| `test_parse_maplibre_style_import_matches_geolens_sources_and_warns_external` | **fixed** | `fillDisabled` → `fill_disabled` (1 key; `symbol.iconImage` stays camelCase per the canonicalization map's scope) | `022c5536` |
| `test_parse_maplibre_style_import_restores_outline_and_extrusion_companions` | **fixed** | `outlineColor/outlineWidth/heightColumn` → `outline_color/outline_width/height_column` (3 keys) | `022c5536` |
| `test_parse_maplibre_style_import_restores_line_arrow_companion` | **fixed** | `arrowColor/arrowSize/arrowSpacing` → `arrow_color/arrow_size/arrow_spacing` (3 keys), values `18 → 18.0` and `120 → 120.0` (float promotion in `_builder_from_arrow_companion`) | `022c5536` |
| `test_build_maplibre_style_round_trip_preserves_terrain_and_builder_state` | **fixed** | `outlineColor/outlineWidth/heightColumn/heightScale/extrusionMinZoom/extrusionOpacity` → `outline_color/outline_width/height_column/height_scale/extrusion_min_zoom/extrusion_opacity` (6 keys) | `022c5536` |

## Task Commits

Per the plan, Tasks 1 and 4 are pure-inspection (write/verify the inventory + re-run), so the only behaviour-changing commit was Task 2's single shared-cause commit:

1. **Task 1 (triage):** No commit — output is `/tmp/1075-04-failures.md` (scratch artifact, not committed)
2. **Task 2 (root-cause fix, 5 tests, 1 shape, 1 cause):** `022c5536` — `fix(1075-04): canonicalize builder keys to snake_case in 5 parse-import assertions (TI-02)`
3. **Task 3 (skip-with-issue):** **Skipped — not needed.** All 5 failures were root-cause-fixable; the skip path is reserved for genuinely-uninvestigable cases. Zero `pytest.mark.skip` decorators added.
4. **Task 4 (verify):** No commit — verification output appended to `/tmp/1075-04-failures.md`.

**Plan metadata commit:** (to follow this SUMMARY) — `docs(1075-04): complete TI-02 partial (test_maps_style_json.py 5 fixes)`

## Files Created/Modified

- **`backend/tests/test_maps_style_json.py`** (modified, +37 / -18 net) — Five non-overlapping assertion edits, each prefaced by a 3-line comment block citing Phase 1060 commit `a400eb89` and explaining the wire-vs-storage canonicalization asymmetry. Line ranges (post-fix): 617-636 (cluster), 866-876 (fillDisabled+symbol), 1012-1022 (outline+extrusion), 1064-1078 (arrow), 1118-1126 (round-trip). No structural changes — no helper edits, no class restructuring, no fixture changes, no new imports.

## Failure Inventory Reference

Full triage capture lives at `/tmp/1075-04-failures.md` (local scratch, not committed per the plan). Key excerpt:

```
All 5 failures share:
  Exception class: AssertionError (4) + KeyError (1) — both forms of the same drift
  Trace pattern:   imported_layer.style_config.builder.<camelCase> ≠ <snake_case actual>
  Hypothesis: HYPOTHESIS 2 (style-JSON schema drift in production)
  Root cause: commit a400eb89 "fix(1060): e2e triage + fix — multi-select aria-selected drift + duplicate camelCase persistence" (2026-05-20)
  Drift location: backend/app/modules/catalog/maps/schemas.py:454
                  (MapLayerInput._normalize_paint_boundary post-validator)
                  via canonicalize_builder_style_config helper (schemas.py:72-100)
                  using _BUILDER_CAMEL_TO_SNAKE_KEYS map (schemas.py:48-69)
  Decision: fix all 5 in Task 2 — single atomic commit, snake_case assertion updates
```

## Mock-Signature / Contract Drift Encountered

**Single drift event, five affected tests (all parse-side assertions):**

- **Drift:** `MapLayerInput._normalize_paint_boundary` (model_validator) gained a call to `canonicalize_builder_style_config(self.style_config)` between the existing `split_legacy_builder_paint` step and the `_validate_style_dict` size-check. The new step rewrites `builder.<camelCase>` keys to `<snake_case>` using `_BUILDER_CAMEL_TO_SNAKE_KEYS` (the inverse of `_BUILDER_KEY_ALIASES` in style_json.py).
- **Source:** commit `a400eb89` (2026-05-20) — `fix(1060): e2e triage + fix — multi-select aria-selected drift + duplicate camelCase persistence`.
- **Why it's intentional production-code hardening:** Prior to Phase 1060, duplicating a layer in the builder UI sent the React state's camelCase keys back through the POST body, persisting the new layer with camelCase while the original (created via `generate_default_style`) kept snake_case. Result: schema split-brain at the DB level. The new validator forces a canonical snake_case shape at the persistence boundary, regardless of which client wrote the row.
- **Why the wire format stays camelCase:** `build_maplibre_style` is the export path that serves a frontend running `normalize-style-config.ts:normalizeBuilderStyleConfig`, which expects camelCase. Per the original Phase 1060 commit message: "Frontend `normalize-style-config.ts:normalizeBuilderStyleConfig` converts storage-canonical snake_case keys (outline_color, outline_width) to camelCase (outlineColor, outlineWidth) on layer LOAD." The wire-vs-storage asymmetry is intentional contract design.

**Audit value for Plan 05 / future hygiene:**
- Any other test that asserts on `MapLayerInput.style_config.builder.*` will be similarly stale. Grep candidates: `grep -rn "MapLayerInput" backend/tests/` and check each result for `builder.*` assertions in camelCase form. (Plan 04's scope is limited to test_maps_style_json.py; broader sweep is Plan 05's call.)
- Any frontend Cypress/Playwright fixture that POSTs a layer with camelCase `builder.*` keys will still work (the post-validator normalizes them on the way in) but the stored row will be snake_case — fine for round-trip but worth knowing if a future test inspects the DB row directly.

## Auto-Resolution from Plan 01

**None.** Consistent with Plans 02 + 03's negative results — the lifecycle fix has nothing to bind to here because the 5 failures are pure-unit Pydantic-model tests (no DB sessions, no async fixtures).

- Plan 01 eliminated the `InvalidCatalogNameError` race.
- `grep -c "InvalidCatalogNameError" /tmp/maps_run.log` → 0 on initial triage AND on both final verify runs.
- The plan's HYPOTHESIS 1 ("conftest cascade") was correctly ruled out at the inventory stage.

This makes three plans in a row (02, 03, 04) where lifecycle was a red herring and the failures were pure post-v1015 production-code drift. The triage protocol for Plan 05 (full-suite verification) should expect the same: any residual failures are genuine drift, not lifecycle fallout.

## GitHub Issues Filed

**None.** No skipped tests, no deferred root causes — all 5 failures were fixed in place.

## Final Tally

| Mode | PASSED | SKIPPED | FAILED | ERROR | Total | Exit |
|------|--------|---------|--------|-------|-------|------|
| `pytest -x` (sequential) | 32 | 0 | 0 | 0 | 32 | 0 |
| `pytest -n 2` (parallel via xdist) | 32 | 0 | 0 | 0 | 32 | 0 |
| InvalidCatalogNameError grep | 0 | — | — | — | — | — |

**Result: 32 passed, 0 failed, 0 errors, 0 skipped — both serial and parallel. Acceptance gates fully satisfied.**

## Scope Adherence

- `git diff --stat backend/app/` → empty (no production-code drift)
- `git diff --stat backend/tests/test_maps_style_json.py` → +37 / -18 (19 net delta, well under the 100-line ceiling)
- All other tests in `test_maps_style_json.py` that passed pre-Plan-04 (27 tests) still pass post-fix.
- No `pytest.mark.skip` decorators added — every disposition is FIXED.
- No new test files, no fixture extensions, no helper modules.
- The 5 originally-failing tests are dispositioned: 5 PASSED, 0 SKIPPED, 0 FAILED.

## Deviations from Plan

**None.** Plan executed exactly as written:

- Task 1 inventory ran, identified 5 specific failures with a single shared hypothesis (HYPOTHESIS 2) and a single decision (fix in Task 2 via shared snake_case assertion update).
- Task 2 applied the smallest-diff fix per hypothesis — single atomic commit because all 5 share one root cause (mirrors Plan 02's pattern). Plan acceptance allows a single commit when shared root cause is validated; this case fits exactly.
- Task 3 (skip-with-issue) was correctly NOT exercised — no failure required deferral.
- Task 4 verified both modes pass and InvalidCatalogNameError count is 0.

No Rule 1/2/3/4 deviations required. No scope creep — production-code untouched.

## Issues Encountered

**None.** The `.env.test` file at the repo root was already present (from Plan 01). `uv` environment ready. No setup blockers.

The plan's `<root_cause_hypothesis>` predicted HYPOTHESIS 1 (lifecycle cascade) as primary, then 2/3/4/5 as candidates. The actual cause was HYPOTHESIS 2 (style-JSON schema drift in production), with a specific Phase 1060 source not foreshadowed in the plan's hypothesis list (which named v1004/v1005 cluster metadata, v1008 basemap-position, v1011 paint._height_column). The lesson: the plan's hypothesis enumeration captures the SHAPE of likely drift (schema vs fixture vs lifecycle), but the SOURCE commit is best identified by `git log --all -S "<symbol>"` after running the file once and reading the traceback. The triage protocol — run → read tracebacks → git-log-the-suspect-symbol — held firm a fourth time across Plans 01-04.

## Self-Check: PASSED

**Files exist:**
- FOUND: backend/tests/test_maps_style_json.py (modified, 1428 lines — was 1409, +19 net)
- FOUND: /tmp/1075-04-failures.md (132 lines — inventory + final result section)
- FOUND: /tmp/maps_run.log (initial triage capture)
- FOUND: /tmp/maps_seq.log (sequential verify)
- FOUND: /tmp/maps_par.log (parallel verify)

**Commits exist:**
- FOUND: 022c5536 (Task 2 — fix(1075-04): canonicalize builder keys to snake_case in 5 parse-import assertions)

**Acceptance gates verified:**
- `cd backend && env $(grep -v '^#' ../.env.test | xargs) uv run pytest tests/test_maps_style_json.py -x` → exit 0 (32/32 PASS) ✓
- `cd backend && env $(grep -v '^#' ../.env.test | xargs) uv run pytest tests/test_maps_style_json.py -n 2` → exit 0 (32/32 PASS) ✓
- `grep -c InvalidCatalogNameError /tmp/maps_seq.log` → 0 ✓
- `grep -c InvalidCatalogNameError /tmp/maps_par.log` → 0 ✓
- `git diff --stat backend/app/` → empty (no production-code drift) ✓
- All skip annotations have `reason=<URL or filepath>` — vacuously true, zero skips added ✓
- 5 named tests all PASSED (verified by targeted `-k` re-run before full-file verify) ✓
- Total PASSED + SKIPPED == collect-only count (32 == 32) ✓

## Next Phase Readiness

- **Plan 1075-05 (full-suite verification)** unblocked. With Plans 02 + 03 + 04 all landing test-only fixes for genuine post-v1015 production drift (Phase 1065 IDOR, Phase 1066 max_size_bytes + SSRF, Phase 1060 builder canonicalization), the full backend/tests/ tree should now be cleanly comparable pre/post v1075. Plan 05's pre-run baseline expectation: 0 InvalidCatalogNameError + 0 of the 11 named baseline failures.
- **Diagnostic patterns reinforced:**
  1. **Inventory-first triage (4th time).** Plans 01-04 all benefited from running the file once before forming a fix hypothesis. The cost is ~30 seconds (one pytest invocation); the saved investigation time is ~5-10 minutes per misdirected hypothesis. Plan 04's HYPOTHESIS 1 (`Map` ORM drift) and HYPOTHESIS 3 (`MapLayerResponse` drift) were both candidates a-priori; one minute of traceback-reading ruled both out and surfaced HYPOTHESIS 2 + a specific Phase 1060 commit.
  2. **Single-atomic-commit for shared root cause (consistent with Plan 02).** When N tests in the same file fail with the same exception shape and the same drift commit, one commit fixing all N tracks the cause and the fix as a single change. Plan 03 split into 2 commits because the 2 root causes were independent (Phase 1066 IA-P0-02 vs Phase 1066 IA-P0-03). The discriminator is "same commit-of-origin?", not "same file?".
  3. **Wire-vs-storage asymmetry as deliberate contract.** Plan 04 surfaces a previously-undocumented convention: the MapLibre style-JSON layer has one-way canonicalization (camelCase on the wire, snake_case in the DB). Future tests on `MapLayerInput` builder fields must use snake_case; future tests on `build_maplibre_style` output must use camelCase. This is now documented in the SUMMARY's `key-decisions` and `patterns-established` sections for v1018+ readers.

**No blockers identified.** The test_maps_style_json.py round-trip pin is fully restored; future regressions in the style-JSON contract (either side) will surface immediately.

---
*Phase: 1075-conftest-test-db-lifecycle-refactor-baseline-fixes*
*Completed: 2026-05-21*
