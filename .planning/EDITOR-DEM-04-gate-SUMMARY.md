---
phase: v1031
plan: EDITOR-DEM-04-gate
subsystem: builder/dem-editor
tags: [dem, contour, gate, defer, v1032]
key-files:
  modified:
    - frontend/src/components/builder/DEMEditorScene.tsx
    - frontend/src/components/builder/__tests__/DEMEditorScene.test.tsx
    - CHANGELOG.md
decisions:
  - Gate CONTOUR_CONTROL_ENABLED=false rather than removing code so v1032 flip is a one-liner
metrics:
  completed: 2026-05-28
---

# EDITOR-DEM-04 Gate-Off Summary

One-liner: Gated off the CONTOUR LINES DEM editor section behind `CONTOUR_CONTROL_ENABLED=false` (v1032 dormant) after the close-gate MCP found maplibre-contour worker emits ~28 MapLibre error events on enable.

## What was gated

- The `CONTOUR LINES` `<section>` in `DEMEditorScene.tsx` (hillshade + terrain modes) is now wrapped in `CONTOUR_CONTROL_ENABLED && (mode === 'hillshade' || mode === 'terrain') && (...)`. With `CONTOUR_CONTROL_ENABLED = false` the section is completely absent from the DOM — the Switch toggle, Interval slider, Color picker, and Weight slider never render.
- The `contour-sync.ts` library and `maplibre-contour` npm dependency are **left intact** (dormant). No deletions.

## Files changed

| File | Change |
|------|--------|
| `frontend/src/components/builder/DEMEditorScene.tsx` | Added `CONTOUR_CONTROL_ENABLED = false` constant + gated section render |
| `frontend/src/components/builder/__tests__/DEMEditorScene.test.tsx` | "section present in hillshade/terrain" → assert absent; interaction tests → `it.skip` with v1032 label |
| `CHANGELOG.md` | Removed contour Added bullet from [1.6.0]; added Deferred to v1032 note in Verification |

## Test result

```
Test Files  2 passed (2)
     Tests  41 passed | 5 skipped (46)
```

5 skipped = the 4 contour interaction tests + the toggle-off test, all labelled `[v1032 — CONTOUR_CONTROL_ENABLED=false]`.

All hypsometric, render-mode, appearance, terrain, visibility, and delete tests pass unchanged.

## Verification

- `npx vitest run DEMEditorScene.test.tsx contour-sync.test.ts`: 41 pass / 5 skip
- `npx tsc -b --noEmit`: 0 errors
- `npm run lint`: 0 errors (1 pre-existing warning in `use-filtered-feature-count.ts`)

## How to re-enable in v1032

Flip line 22 of `DEMEditorScene.tsx`:

```ts
const CONTOUR_CONTROL_ENABLED = true;
```

Then un-skip the 5 `it.skip` tests in `DEMEditorScene.test.tsx` and remove `[v1032 — CONTOUR_CONTROL_ENABLED=false]` from their labels. The contour-sync.ts integration work and deeper maplibre-contour worker hardening should land before flipping the gate.

## Commit

`21feaf7f` — fix(dem): gate off CONTOUR LINES section (EDITOR-DEM-04 deferred to v1032)

## Self-Check: PASSED

- `21feaf7f` exists in git log
- All 3 modified files present and committed
- `CONTOUR_CONTROL_ENABLED = false` in DEMEditorScene.tsx
- CONTOUR LINES bullet removed from CHANGELOG.md [1.6.0] Added section
