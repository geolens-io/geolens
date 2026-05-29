---
phase: 1148-render-mode-persistence-fix
plan: 1
subsystem: ui
tags: [react, maplibre, raster, dem, style-config, normalize]

requires:
  - phase: 1147-builder-carry-forward
    provides: BuilderMap.tsx applyTerrainConfig() consumer at :392 that needs render_mode==='terrain'

provides:
  - RENDER_MODES Set in normalize-style-config.ts now includes 'terrain' and 'image' (7 members)
  - StyleConfig['render_mode'] union in api.ts includes 'terrain' | 'image'
  - DEMEditorScene.tsx DemRenderMode assignable to StyleConfig['render_mode'] without cast
  - Round-trip unit tests pinning terrain/image/hillshade and RENDER_MODES completeness guard

affects: [1149-label-indicator, 1150-point-control, 1151-close-gate]

tech-stack:
  added: []
  patterns:
    - "RENDER_MODES export pattern: export const to allow test-level guard assertions"
    - "Round-trip allowlist test: RENDER_MODES.toContain per-mode loop catches silent drops"

key-files:
  created: []
  modified:
    - frontend/src/lib/normalize-style-config.ts
    - frontend/src/types/api.ts
    - frontend/src/components/builder/DEMEditorScene.tsx
    - frontend/src/lib/__tests__/normalize-style-config.test.ts

key-decisions:
  - "Frontend-only fix: api.ts is hand-maintained; no OpenAPI/SDK regen; backend style_config already persists render_mode:'terrain' correctly"
  - "Export RENDER_MODES to allow unit test guard without additional indirection"
  - "Keep DemRenderMode as domain alias in DEMEditorScene.tsx; now assignable without cast"

requirements-completed: [RMODE-01, RMODE-02, RMODE-03]

duration: 12min
completed: 2026-05-29
---

# Phase 1148 Plan 1: Render-Mode Persistence Fix Summary

**Extended RENDER_MODES allowlist and StyleConfig union to include 'terrain' and 'image', fixing the root cause that caused applyTerrainConfig() to receive undefined render_mode and call setTerrain(null) on every map load.**

## Performance

- **Duration:** ~12 min
- **Completed:** 2026-05-29
- **Tasks:** 2/2
- **Files modified:** 4

## Accomplishments

### Task 1: Extend RENDER_MODES, StyleConfig union, and remove DEMEditorScene boundary cast

**Commit:** `17daaabd`

**Changes:**

- `frontend/src/lib/normalize-style-config.ts:92` — Changed `const RENDER_MODES = new Set([...5 modes...])` to `export const RENDER_MODES = new Set([...'terrain', 'image'])` (7 members total). The `normalizeRenderMode()` logic is unchanged — the Set extension is the only modification needed for `RENDER_MODES.has(direct)` to preserve `'terrain'` and `'image'` instead of returning `undefined`.

- `frontend/src/types/api.ts:863` — Extended `render_mode?:` union from `'heatmap' | 'hillshade' | 'symbol' | 'arrow' | 'cluster'` to add `| 'terrain' | 'image'`. Hand-maintained file; no codegen touched.

- `frontend/src/components/builder/DEMEditorScene.tsx:22-29` — Removed the 7-line JSDoc block containing `"Note: 'terrain' is not currently in StyleConfig.render_mode union"` and `"BSR-09 follow-up"`. Replaced with a single-line docstring `/** DEM render mode union. Assignable to StyleConfig['render_mode'] without cast. */`. The `DemRenderMode = 'image' | 'hillshade' | 'terrain'` type itself is kept as a domain alias; with the union now containing `'terrain'` and `'image'`, it is directly assignable without cast.

**Verification output:**
```
> frontend@1.0.2 typecheck
> tsc -b --noEmit
EXIT: 0
```

### Task 2: Add round-trip regression tests for terrain/image/hillshade and RENDER_MODES guard

**Commit:** `053dfbf5`

**Changes:**

- `frontend/src/lib/__tests__/normalize-style-config.test.ts` — Added import of `RENDER_MODES` from the normalize module. Added 3 new test blocks:
  1. `'preserves render_mode terrain for DEM/raster adapters'` — inside existing `normalizeLayerStyleState` describe block.
  2. `'preserves render_mode image for DEM/raster adapters'` — inside existing `normalizeLayerStyleState` describe block.
  3. `describe('RENDER_MODES allowlist') > 'contains all editor-emittable modes'` — loops over all 7 expected modes calling `expect(RENDER_MODES).toContain(mode)`.

**Verification output:**
```
 RUN  v4.1.5 /Users/ishiland/Code/geolens/frontend

 Test Files  1 passed (1)
      Tests  10 passed (10)
   Start at  20:50:56
   Duration  733ms (transform 73ms, setup 123ms, import 83ms, tests 3ms, environment 435ms)
```

10 tests pass (7 pre-existing + 3 new).

## Deviations from Plan

None — plan executed exactly as written. The `export` keyword addition to `RENDER_MODES` was specified in Task 2 action: "If `RENDER_MODES` is not currently exported, add `export` in front of the const declaration in `normalize-style-config.ts`" — done in Task 1 (same commit) per that instruction.

## Verification Commands Run

```bash
# 1. Typecheck — EXIT 0
cd /Users/ishiland/Code/geolens/frontend && npm run typecheck
# Result: tsc -b --noEmit exited 0 (no output = no errors)

# 2. Unit tests — 10/10 pass
cd /Users/ishiland/Code/geolens/frontend && npx vitest run src/lib/__tests__/normalize-style-config.test.ts
# Result: 1 file passed, 10 tests passed

# 3. BSR-09 gone — 0 occurrences
grep -c "BSR-09" frontend/src/components/builder/DEMEditorScene.tsx
# Result: 0

# 4. RENDER_MODES spot-check
grep "RENDER_MODES" frontend/src/lib/normalize-style-config.ts
# Result: export const RENDER_MODES = new Set(['heatmap', 'hillshade', 'symbol', 'arrow', 'cluster', 'terrain', 'image']);

# 5. api.ts union spot-check
grep "render_mode" frontend/src/types/api.ts | grep -E "terrain|image"
# Result: render_mode?: 'heatmap' | 'hillshade' | 'symbol' | 'arrow' | 'cluster' | 'terrain' | 'image';

# 6. openapi-check — DEFERRED
# make openapi-check timed out (backend uv venv rebuild during check); per plan: deferred to 1151 close-gate
```

## Known Stubs

None — no stubs, placeholders, or hardcoded empty values introduced.

## Threat Flags

None — no new network endpoints, auth paths, file access patterns, or schema changes introduced. The union extension is frontend-type-only (confirmed by plan threat model T-1148-01 and T-1148-02 both `accept`).

## Self-Check: PASSED

- `17daaabd` exists in git log ✓
- `053dfbf5` exists in git log ✓
- `frontend/src/lib/normalize-style-config.ts` modified ✓
- `frontend/src/types/api.ts` modified ✓
- `frontend/src/components/builder/DEMEditorScene.tsx` modified ✓
- `frontend/src/lib/__tests__/normalize-style-config.test.ts` modified ✓
