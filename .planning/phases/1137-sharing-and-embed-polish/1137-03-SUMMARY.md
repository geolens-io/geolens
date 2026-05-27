---
phase: 1137-sharing-and-embed-polish
plan: "03"
subsystem: viewer-branding
tags: [share, embed, branding, i18n, vitest]
dependency_graph:
  requires: []
  provides: [SHARE-07, SHARE-09]
  affects: [ViewerMap, PublicViewerPage, use-builder-save]
tech_stack:
  added: []
  patterns: [useEdition-in-ViewerMap, showInlineBranding-prop-gate, TDD-red-green]
key_files:
  created:
    - frontend/src/components/viewer/__tests__/ViewerMap.branding.test.tsx
  modified:
    - frontend/src/components/viewer/ViewerMap.tsx
    - frontend/src/pages/PublicViewerPage.tsx
    - frontend/src/pages/__tests__/PublicViewerPage.test.tsx
    - frontend/src/components/builder/hooks/__tests__/use-builder-save.test.ts
    - frontend/src/i18n/locales/en/common.json
    - frontend/src/i18n/locales/de/common.json
    - frontend/src/i18n/locales/es/common.json
    - frontend/src/i18n/locales/fr/common.json
decisions:
  - "export.poweredBy i18n key added to all 4 locales; brand name stays English across de/es/fr per convention"
  - "useBranding imported into ViewerMap alongside useEdition to mirror AppLayout.tsx:16 gate (show_badge !== false)"
  - "Test file uses vi.mock shorthand (no async) for @vis.gl/react-maplibre since no React.useEffect needed in mock"
  - "SHARE-09 pins use mockEdition.isEnterprise hoisted control; added to useBuilderSave beforeEach reset"
  - "i18n test mock returns key-as-is; SHARE-09 branding pin matches /export.poweredBy|Powered by GeoLens/ to stay resilient"
metrics:
  duration: "~20min"
  completed: "2026-05-27T23:18:24Z"
  tasks_completed: 4
  files_changed: 9
---

# Phase 1137 Plan 03: ViewerMap Embed-Mode Branding + Export PNG Pins Summary

Embed-mode viewers now show "Powered by GeoLens" branding via a new `showInlineBranding` prop on ViewerMap; the export PNG branding path is pinned by 4 regression tests.

## What Was Built

### Task 1: ViewerMap showInlineBranding prop + branding overlay

Added `showInlineBranding?: boolean` (default `false`) to `ViewerMapProps`. When `true` AND edition conditions are met, renders a `<span data-testid="viewer-branding-overlay">` anchored at `absolute bottom-2 left-2 z-10 text-xs text-muted-foreground bg-background/70 rounded px-2 py-1 pointer-events-none`.

Gate condition: `showInlineBranding && (!isEnterprise || branding?.show_badge !== false)` — mirrors the existing AppLayout.tsx:16 contract.

New imports in ViewerMap: `useEdition` (from `@/hooks/use-edition`) and `useBranding` (from `@/hooks/use-settings`).

4 regression pins in `ViewerMap.branding.test.tsx`:
- (1) community + `showInlineBranding=true` → overlay present
- (2) enterprise + `show_badge=false` + `showInlineBranding=true` → overlay absent
- (3) enterprise + `show_badge=true` + `showInlineBranding=true` → overlay present
- (4) `showInlineBranding=false` (default) → overlay absent regardless of edition

### Task 2: PublicViewerPage wiring

Added `showInlineBranding={isEmbed}` to the `<ViewerMap>` callsite at `PublicViewerPage.tsx:154`. The `{!isEmbed && <AppFooter ... />}` gate at line 181 is unchanged — non-embed branding still rides through AppFooter.

2 new SHARE-07 routing pins appended to `PublicViewerPage.test.tsx`:
- embed mode → `viewerMapMock.props.showInlineBranding === true`
- non-embed mode → `showInlineBranding === false` AND AppFooter in DOM

### Task 3: SHARE-09 export PNG regression pins

Added `describe('SHARE-09 export PNG composition')` block to `use-builder-save.test.ts`. No implementation changes to `use-builder-save.ts` — verify-only per plan.

Added `vi.mock('@/hooks/use-edition')` with hoisted `mockEdition.isEnterprise` control (reset in `beforeEach`). The 4 pins:
- (a) title + description rendered via `fillText` when `localName` non-empty
- (b) legend header + layer row + `fillRect` swatch for visible `show_in_legend` layers
- (c) branding footer renders when `isEnterprise=false` (matches `/export\.poweredBy|Powered by GeoLens/`)
- (d) branding footer suppressed when `isEnterprise=true`

### Task 4: i18n parity — export.poweredBy + export.legendHeader

Added `"export": { "poweredBy": "Powered by GeoLens", "legendHeader": "<locale>" }` to all 4 locales:
- en: `"legendHeader": "Legend"`
- de: `"legendHeader": "Legende"`
- es: `"legendHeader": "Leyenda"`
- fr: `"legendHeader": "Légende"`

`test:i18n` passes 2/2.

## Commits

| Hash | Type | Description |
|------|------|-------------|
| c231dc74 | feat | add showInlineBranding prop + branding overlay to ViewerMap |
| 5588359c | feat | wire PublicViewerPage to pass showInlineBranding={isEmbed} |
| 28fe38f9 | test | SHARE-09 export PNG composition regression pins |
| 037c65f2 | feat | add export.poweredBy + export.legendHeader i18n keys to 4 locales |
| 71750f47 | fix | TypeScript errors in ViewerMap.branding.test.tsx (readonly [], mock syntax) |

## Verification Results

| Check | Result |
|-------|--------|
| `npm test -- ViewerMap.branding --run` | 4/4 PASS |
| `npm test -- PublicViewerPage --run` | 8/8 PASS |
| `npm test -- use-builder-save --run` | 51/51 PASS |
| `npm run typecheck` | 0 errors |
| `npm run test:i18n` | 2/2 PASS |
| `grep -n "BuilderActionSource" ViewerMap.tsx` | 0 lines (HARD INVARIANT preserved) |
| `grep -n "SHARE-08\|og_image_uri" ViewerMap.tsx` | 0 lines (SHARE-08 DEFER respected) |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] TypeScript readonly[] / vi.mock syntax errors in test file**
- **Found during:** Task 1 typecheck
- **Issue:** `layers: []` with `as const` produced `readonly []` not assignable to `SharedLayerResponse[]`; `vi.mock` factory was left with `async`+`return {}` inconsistency when removing unused `React` import
- **Fix:** Added `as SharedLayerResponse[]` cast; changed mock to synchronous shorthand `() => ({...})`; removed unused React import
- **Files modified:** `frontend/src/components/viewer/__tests__/ViewerMap.branding.test.tsx`
- **Commit:** 71750f47

**2. [Rule 1 - Bug] SHARE-09 branding pin used `'Powered by GeoLens'` literal but i18n mock returns key**
- **Found during:** Task 3 first run (1 failing test)
- **Issue:** `t('export.poweredBy', { defaultValue: '...' })` returns `'export.poweredBy'` in tests (key-as-is mock)
- **Fix:** Changed assertion to match `/export\.poweredBy|Powered by GeoLens/` regex so it works both before and after i18n files ship
- **Files modified:** `frontend/src/components/builder/hooks/__tests__/use-builder-save.test.ts`
- **Commit:** 28fe38f9 (included in the same task commit)

## Known Stubs

None. All props are wired to live data sources (`useEdition`, `useBranding`, `isEmbed` from searchParams).

## Threat Flags

None — threat register entries T-1137-03-01 (static overlay), T-1137-03-02 (edition info public), T-1137-03-03 (enterprise branding gate mirrors AppLayout) all confirmed mitigated. `branding?.show_badge !== false` gate is present.

## Self-Check: PASSED

All 9 files exist. All 5 commits verified in git log. 63 tests pass. typecheck 0. i18n 2/2.
