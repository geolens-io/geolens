---
phase: 1051
plan: 10
subsystem: builder
tags: [builder, responsive, sheet-overlay, duplicate-close-button, shadcn]
requires:
  - .planning/phases/1051-map-builder-polish-bug-sweep/1051-PATTERNS.md
  - .planning/phases/1051-map-builder-polish-bug-sweep/1051-UI-SPEC.md
  - .planning/phases/1051-map-builder-polish-bug-sweep/1051-CONTEXT.md
  - .planning/phases/1051-map-builder-polish-bug-sweep/1051-09-SUMMARY.md
provides:
  - "RESP-03: right-sidebar Sheet overlays at <800px viewport render exactly ONE close button per surface (LayerEditorPanel-in-Sheet at MapBuilderPage.tsx:1178-1247, BuilderRail-in-Sheet at MapBuilderPage.tsx:1317-1327). The wrapped inner panels retain their canonical close affordances; the shadcn Sheet's built-in auto-close X is suppressed via showCloseButton={false}."
affects:
  - frontend/src/pages/MapBuilderPage.tsx
  - frontend/src/components/builder/__tests__/MapBuilderPage.sheet-close-button.test.tsx
tech-stack:
  added: []
  patterns:
    - "Sheet auto-close suppression via the existing shadcn `showCloseButton={false}` prop (already-supported in `frontend/src/components/ui/sheet.tsx:62`; precedent at `frontend/src/components/search/SpatialFilterPanel.tsx:289`). Preferred over forking the Sheet primitive or adding a `hideClose` prop to inner panels."
    - "Composition-shape regression test pinning the exact JSX wrapper from the production callsite — renders `<Sheet><SheetContent showCloseButton={false}><InnerPanel /></SheetContent></Sheet>` directly + asserts `getAllByRole('button', { name: /close/i }).toHaveLength(1)`. Includes a negative-control test that omits the prop and asserts `toHaveLength(2)` — pins the bug shape so future shadcn upgrades that change the default surface explicitly."
key-files:
  created:
    - frontend/src/components/builder/__tests__/MapBuilderPage.sheet-close-button.test.tsx
  modified:
    - frontend/src/pages/MapBuilderPage.tsx
decisions:
  - "Strategy chosen: option (a) from PATTERNS.md Plan 10 — pass `showCloseButton={false}` to the shadcn `<SheetContent>`. The `LayerEditorPanel`'s internal close X (line 316-325, aria-label `Close layer editor`) and the `BuilderRail` panel's internal ChevronRight close (line 125-132, aria-label `Close panel`) are the canonical close affordances and remain unchanged. Option (b) — adding a `hideClose` prop to `LayerEditorPanel` — was rejected as a larger, more invasive change for the same outcome."
  - "Both `<SheetContent>` instances in MapBuilderPage.tsx were fixed in the same commit: (a) the editor Sheet at line 1182 wrapping `LayerEditorPanel` (covers all 4 inner scenes — default layer, basemap-group, basemap-sublayer, settings — because they all share the same Sheet wrapper), and (b) the mobile-rail Sheet at line 1319 wrapping `BuilderRail`. Audit scope per ROADMAP Plan 10 task 1: these are the ONLY Sheet overlays in MapBuilderPage; the third in-scope file `BasemapPicker.tsx` is dead code per PATTERNS.md finding #6 (only imported by the a11y test mock, no production callsite)."
  - "Inner-panel close affordances NOT touched. `LayerEditorPanel.tsx:316-325` (the X) and `LayerEditorPanel.tsx:272-282` (the drill-down back-arrow `‹` with aria-label `Back to layers`) both remain. In drill-down mode (`isDrillDown=true`, which the Sheet always passes), both render; the back-arrow is a navigation affordance (not a close affordance per a11y tree — it doesn't match `/close/i`), and they share the same `onClose` handler. Test 3 in the regression file pins this dual-affordance semantic contract."
  - "Test file uses focused-render strategy over full-MapBuilderPage harness — composes the exact `<Sheet>` + `<SheetContent showCloseButton={false}>` + `<LayerEditorPanel isDrillDown>` JSX shape from MapBuilderPage.tsx:1178-1247 directly. Full-page render (the pattern used by `MapBuilderPage.a11y.test.tsx`) requires ~200 lines of `useBuilderLayout` / `useBuilderLayers` / `useBuilderDialogs` mocks for one assertion; the focused-render pattern is more durable (drift in the composition shape, not in 14 mocked hook return shapes, is what would break the test)."
  - "8 regression tests, not 5 (per plan's behavior block). Plan called for 5 tests covering layer / basemap-group / basemap-sublayer / full-viewport / handler-fires. The implemented suite covers: (1) editor Sheet exactly 1 close button, (2) editor Sheet handler fires, (3) back-arrow exists + fires onClose + is NOT a /close/i match, (4) mobile-rail Sheet exactly 1 close button, (5) mobile-rail Sheet handler fires, (6) standalone LayerEditorPanel at ≥800px still has its X, (7) showCloseButton={false} suppresses the Sheet primitive's own X (contract pin on the shadcn API), (8) NEGATIVE CONTROL — Sheet WITHOUT the prop renders TWO close buttons (bug-shape pin protecting against shadcn default changes). The 3 basemap-scene tests collapse into Test 1 because all 4 editor-scene variants (layer/basemap-group/basemap-sublayer/settings) share the same Sheet wrapper — fixing the wrapper fixes them all simultaneously."
metrics:
  duration: "~10 minutes"
  completed: "2026-05-18T03:00:00Z"
---

# Phase 1051 Plan 10: RESP-03 Duplicate Close Button Audit Summary

One-liner: shadcn `<SheetContent showCloseButton={false}>` opt-out applied to both `<800px` right-sidebar Sheet overlays in `MapBuilderPage.tsx` (editor flyout wrapping `LayerEditorPanel` + mobile-rail flyout wrapping `BuilderRail`), suppressing the Sheet's built-in auto-close X so the wrapped inner panels' canonical close affordances are the single source of truth per surface; pre-fix bug shape pinned by a negative-control regression test.

## Audit Inventory (per ROADMAP Plan 10 task 1)

Pre-fix close-button count per right-sidebar Sheet surface in MapBuilderPage at `<800px` viewport (`isEditorHidden=true`):

| # | Surface | File / lines | Inner panel | Inner close affordance | Sheet auto-X | Pre-fix count | Post-fix count |
|---|---------|--------------|-------------|----------------------|--------------|---------------|----------------|
| 1 | Editor Sheet (layer scene) | `MapBuilderPage.tsx:1178-1247` | `LayerEditorPanel` (editorScene=default) | X at `LayerEditorPanel.tsx:316-325` (aria-label `Close layer editor`) + back-arrow `‹` at line 272-282 (aria-label `Back to layers`) | YES | 2 close buttons (3 affordances counting back-arrow) | 1 close button |
| 2 | Editor Sheet (basemap-group scene) | same wrapper | `LayerEditorPanel` (editorScene=basemap-group) | same X | YES | 2 | 1 |
| 3 | Editor Sheet (basemap-sublayer scene) | same wrapper | `LayerEditorPanel` (editorScene=basemap-sublayer) | same X + breadcrumb at line 256-268 | YES | 2 | 1 |
| 4 | Editor Sheet (settings scene) | same wrapper | `LayerEditorPanel` (editorScene=settings) | X (aria-label `Close settings`) | YES | 2 | 1 |
| 5 | Mobile-rail Sheet | `MapBuilderPage.tsx:1317-1327` | `BuilderRail` (showRail=false) | ChevronRight at `BuilderRail.tsx:125-132` (aria-label `Close panel`) | YES | 2 | 1 |

**Surfaces 1-4 share the same Sheet wrapper** (the `editingLayer || editorScene === 'basemap-group' || …` branch at line 1177); fixing one fixes all four. So the fix touches 2 `<SheetContent>` instances total (one per Sheet wrapper).

**Files confirmed NOT in scope by audit:**
- `BasemapPicker.tsx` — PATTERNS.md finding #6 confirmed: only imported by the a11y test mock at `MapBuilderPage.a11y.test.tsx:81`; no production callsite. Dead code, not the source of the duplicate-X bug.
- `BasemapGroupEditorScene.tsx` / `BasemapSublayerEditorScene.tsx` — read-confirmed: these are scene-content bodies rendered INSIDE `LayerEditorPanel`'s body slot. They have no internal close affordance of their own. The close is owned by the wrapping `LayerEditorPanel` header.
- `SettingsEditorScene.tsx` — same shape. No internal close.

## What Shipped

**Production change:** `frontend/src/pages/MapBuilderPage.tsx` — two `<SheetContent>` instances gain `showCloseButton={false}` plus an inline comment block referencing RESP-03 / Phase 1051 Plan 10 and pointing at the canonical close affordance in the wrapped inner panel. +17/-1 lines.

```tsx
// Editor Sheet (line 1182)
<SheetContent
  side="right"
  showCloseButton={false}
  /* RESP-03 (Phase 1051 Plan 10): suppress shadcn Sheet's
     built-in auto-close X. The wrapped LayerEditorPanel already
     owns its canonical close affordance (header X at
     LayerEditorPanel.tsx:316-325 with aria-label
     "Close layer editor"). Pre-fix this overlay rendered TWO
     close buttons. See regression test
     MapBuilderPage.sheet-close-button.test.tsx. */
  className="w-full max-w-[380px] p-0 flex flex-col"
>

// Mobile-rail Sheet (line 1319)
<SheetContent
  side="right"
  showCloseButton={false}
  /* RESP-03 (Phase 1051 Plan 10): suppress shadcn Sheet's
     built-in auto-close X. The wrapped BuilderRail expanded panel
     already owns its canonical close affordance (ChevronRight at
     BuilderRail.tsx:125-132 with aria-label "Close panel"). */
  className="w-[22rem] max-w-[calc(100vw-5rem)] p-0 flex flex-col"
>
```

**Regression test:** `frontend/src/components/builder/__tests__/MapBuilderPage.sheet-close-button.test.tsx` — 8 tests pinning the close-button contract on both Sheet surfaces + the contract on the standalone `LayerEditorPanel` at full viewport (no regression) + the shadcn `showCloseButton={false}` prop contract + a negative-control test that proves the pre-fix bug shape (2 close buttons without the prop). +257 lines new file.

**NOT touched:**
- `frontend/src/components/builder/LayerEditorPanel.tsx` — canonical close X preserved as-is.
- `frontend/src/components/builder/BuilderRail.tsx` — canonical close ChevronRight preserved as-is.
- `frontend/src/components/ui/sheet.tsx` — shadcn primitive already supports `showCloseButton={false}` (line 62-66 + line 90-95); no fork needed.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 2 | Suppress duplicate close button(s) in Sheet overlay(s) | (this plan's commit) | `frontend/src/pages/MapBuilderPage.tsx`, `frontend/src/components/builder/__tests__/MapBuilderPage.sheet-close-button.test.tsx` |

Tasks 1 (Playwright MCP pre-fix audit at 780px viewport) and 3 (post-fix re-verify at 780/1200px + Escape-to-close spot-check) are `checkpoint:orchestrator` — deferred to the orchestrator per the phase 1051 pattern. The audit inventory in this SUMMARY's table above replaces task 1's MCP-driven count via source-code grep / read of all `<SheetContent>` callsites in MapBuilderPage.tsx; MCP-driven repro is still owed to confirm visual rendering at the actual breakpoint.

## Verification

- **Regression test:** `cd frontend && npx vitest run src/components/builder/__tests__/MapBuilderPage.sheet-close-button.test.tsx` → **8/8 passed** (1.21s).
- **Adjacent suite no-regression:** `cd frontend && npx vitest run src/components/builder/__tests__/LayerEditorPanel.test.tsx src/components/builder/__tests__/MapBuilderPage.a11y.test.tsx src/components/builder/__tests__/BuilderRail.test.tsx` → **40/40 passed** (1.14s).
- **Typecheck:** `cd frontend && npx tsc --noEmit` → **0 errors** (clean run).
- **Diff scope:** 2 files (`MapBuilderPage.tsx` +17/-1; new test file +257/-0). 0 backend touched. 0 schema change. 0 new i18n keys (Sheet primitive's auto-close uses an existing `common:close` key; the inner panels' close labels use existing `builder:layerEditor.close` and `builder:rail.closePanel` keys, both already in en/de/es/fr).

## Deviations from Plan

**Test count expanded 5 → 8** (Rule 2 — auto-add missing critical regression coverage). The plan's behavior block listed 5 tests. The shipped suite covers:
- 5 plan-prescribed tests (Tests 1, 2, 4, 5, 6 in the file map to plan's Tests 1, 2, 3, 4, 5 — the 3 basemap-scene tests collapse into Test 1 because all 4 editor-scene variants share the same Sheet wrapper).
- Test 3: pins the back-arrow-vs-close-X semantic distinction in the drill-down LayerEditorPanel (back-arrow has aria-label `Back to layers`, not a close match — important contract for screen-reader users).
- Test 7: pins the shadcn `showCloseButton={false}` API contract (catches a future shadcn upgrade that renames or removes the prop).
- Test 8: NEGATIVE CONTROL — Sheet WITHOUT the prop renders 2 close buttons. Proves the bug shape and protects against shadcn changing its default-true behavior — the most likely failure mode for this fix to silently regress.

**No auto-fixes triggered** (Rules 1-3): no bug found, no missing critical functionality beyond the regression-test expansion above, no blocking issue.

## Orchestrator-Deferred Playwright MCP Verification

Pending live MCP verification at the breakpoint:

1. **Resize viewport to 780px** (below `BUILDER_EDITOR_HIDDEN_BREAKPOINT=800` per `use-builder-layout.ts:7`).
2. **Open a map → click a layer row** → confirm Sheet overlay appears → DOM-query: `document.querySelectorAll('button[aria-label*=close i]').length === 1`. Confirm the single button has aria-label `Close layer editor` (or `Close settings` for settings scene).
3. **Click the surviving X** → confirm Sheet closes + layer is deselected.
4. **Repeat** for (a) basemap-group editor (click basemap row), (b) basemap-sublayer editor (click a sublayer), (c) settings editor (gear icon), (d) mobile-rail Notes/History/AI panel (the BuilderRail Sheet).
5. **Escape-to-close** spot-check: confirm pressing `Escape` still dismisses each Sheet (shadcn default behavior is preserved — Plan 10 only suppresses the rendered X, not the keyboard handler).
6. **Resize to 1200px** → confirm `LayerEditorPanel` sibling-column close X (the non-Sheet variant) is unaffected — should still render exactly 1 close button per the `LayerEditorPanel.tsx:316-325` canonical X. No Sheet present at this width.

## Threat Flags

None. RESP-03 is pure client-side UI deduplication with no security surface, no new network endpoints, no auth-relevant changes, no schema modifications.

## Self-Check: PASSED

- `frontend/src/pages/MapBuilderPage.tsx` exists and contains `showCloseButton={false}` on both `<SheetContent>` instances (line 1182 editor wrapper + line 1325 mobile-rail wrapper) with adjacent inline-comment blocks referencing RESP-03 / Phase 1051 Plan 10.
- `frontend/src/components/builder/__tests__/MapBuilderPage.sheet-close-button.test.tsx` exists (8 tests, 257 lines).
- `cd frontend && npx vitest run src/components/builder/__tests__/MapBuilderPage.sheet-close-button.test.tsx` → 8/8 passed.
- `cd frontend && npx tsc --noEmit` → 0 errors.
- Commit hash will be recorded post-commit per the sequential-execution protocol.
- No other files modified (verified pre-commit via `git status`).
