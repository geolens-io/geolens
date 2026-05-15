---
phase: 1042-spacing-density-states-polish
plan: 04
subsystem: builder
tags:
  - builder
  - i18n
  - empty-state
  - entry-animation
  - eyebrow

dependency_graph:
  requires:
    - 1042-01  # motion tokens (--motion-fast) must land first
  provides:
    - eyebrowClassName constant (shared between EmptyStackState + UnifiedStackPanel)
    - freshLayerId state lifecycle in use-builder-layers
    - StackRow isFresh entry animation
    - Deduplicated builder.json with canonical listboxLabel key
  affects:
    - frontend/src/components/builder/UnifiedStackPanel.tsx
    - frontend/src/components/builder/EmptyStackState.tsx
    - frontend/src/components/builder/StackRow.tsx
    - frontend/src/components/builder/hooks/use-builder-layers.ts
    - frontend/src/i18n/locales/en/builder.json

tech_stack:
  added: []
  patterns:
    - "vi.useFakeTimers() for setTimeout lifecycle tests"
    - "module-scope export constant shared between co-located components"
    - "useRef timeout ref for single-flight timer cleanup"

key_files:
  created: []
  modified:
    - frontend/src/i18n/locales/en/builder.json
    - frontend/src/components/builder/hooks/use-builder-layers.ts
    - frontend/src/components/builder/StackRow.tsx
    - frontend/src/components/builder/EmptyStackState.tsx
    - frontend/src/components/builder/UnifiedStackPanel.tsx
    - frontend/src/components/builder/__tests__/EmptyStackState.test.tsx
    - frontend/src/components/builder/__tests__/UnifiedStackPanel.test.tsx
    - frontend/src/components/builder/hooks/__tests__/use-builder-layers.add-dataset.test.ts

decisions:
  - "eyebrowClassName exported from EmptyStackState (not a shared utils file) — simpler since EmptyStackState is the defining component and UnifiedStackPanel already imports from it"
  - "freshLayerId wired as prop to UnifiedStackPanel (not via hook) — UnifiedStackPanel is purely presentational; hook state lives in MapBuilderPage"
  - "Pre-existing i18n parity test failure (DE/FR/ES missing newer keys) treated as out-of-scope; Phase 1044 owns locale fill"
  - "Basemap dock eyebrow uses cn(eyebrowClassName, 'px-3 pt-1 pb-0') to override px-1 with px-3 — correct override pattern"

metrics:
  duration: "~20 minutes"
  completed_date: "2026-05-14"
  tasks_completed: 3
  files_modified: 8
---

# Phase 1042 Plan 04: i18n dedup + freshLayerId + UnifiedStackPanel + EmptyStackState polish Summary

**One-liner:** Deduplicated builder.json duplicate key block (lines 715-826 deleted), added freshLayerId 200ms lifecycle with single-flight timeout, wired StackRow entry animation, normalized UnifiedStackPanel header buttons to h-8 with 18px icon, and extracted eyebrowClassName constant as shared source of truth.

## Tasks Completed

| Task | Name | Commit | Key Files |
|------|------|--------|-----------|
| 1 | i18n duplicate-key dedup | 7bba3694 | builder.json |
| 2 RED | freshLayerId failing tests | 11bd8856 | use-builder-layers.add-dataset.test.ts |
| 2 GREEN | freshLayerId lifecycle + StackRow animation | ccdd46bb | use-builder-layers.ts, StackRow.tsx |
| 3 RED | AUD-01/02/19/23/24 failing tests | e8488535 | EmptyStackState.test.tsx, UnifiedStackPanel.test.tsx |
| 3 GREEN | UnifiedStackPanel header + EmptyStackState polish | 56357e20 | EmptyStackState.tsx, UnifiedStackPanel.tsx, UnifiedStackPanel.test.tsx |

## Task 1: i18n Dedup

- **Lines deleted:** 715-826 (first copy of 8 namespaces — missing `listboxLabel`)
- **Surviving block:** lines 884-998 (second copy with canonical `listboxLabel: "Map layers"` at original line 896)
- **Post-dedup top-level key count:** 51 (no duplicates)
- **Verification:** `python3 -c "..."` confirms zero duplicates, listboxLabel present
- **8 builder namespaces all present:** unifiedStack, rail, stackRow, basemapGroup, basemapSublayer, demEditor, folderGroup, layerEditor

## Task 2: freshLayerId Lifecycle

- **State added:** `const [freshLayerId, setFreshLayerId] = useState<string | null>(null)`
- **Timeout ref:** `freshLayerTimeoutRef` for single-flight, clears prior timer before scheduling new one
- **Behavior:** set to `createdLayer.id` in `handleAddDataset` onSuccess; cleared after 200ms
- **Cleanup:** `useEffect(() => () => clearTimeout(freshLayerTimeoutRef.current), [])` cancels on unmount
- **Return:** `freshLayerId` added to hook return object
- **StackRow:** `isFresh?: boolean` prop; when true appends `animate-in fade-in duration-[--motion-fast]`
- **Tests:** 11/11 pass (I: set on success, J: cleared after 200ms, K: no setState-after-unmount)

## Task 3: UnifiedStackPanel Header + EmptyStackState Polish

### AUD-01 (Header buttons h-8):
- Settings cog button: `h-[22px] w-[22px]` → `h-8 w-8`
- + Add data button: `h-7` → `h-8`

### AUD-19 (Icon sizing):
- Settings icon: `h-4 w-4` → `h-[18px] w-[18px]`

### AUD-21 (Hover token):
- Settings cog hover: `hover:bg-accent` → `hover:bg-[var(--surface-2)]`

### AUD-02 (Eyebrow extraction):
- `export const eyebrowClassName = 'block text-[10px] font-semibold tracking-wide text-muted-foreground uppercase px-1'`
- Used in EmptyStackState SUGGESTED label and UnifiedStackPanel basemap dock eyebrow
- **Inline literal count in UnifiedStackPanel.tsx: 0** (grep verified)

### AUD-23 (Suggest card surface):
- `bg-[var(--surface-1)]` → `bg-[var(--surface-0)]` on suggest card rest state

### AUD-24 (Transition durations):
- Search container: `transition-colors` → `transition-colors duration-[--motion-fast]`
- Search icon button: added `transition-colors duration-[--motion-fast]`

### freshLayerId wiring:
- `freshLayerId?: string | null` prop added to `UnifiedStackPanelProps`
- Passed through `SortableStackRowProps` → `SortableStackRow` → `StackRow` as `isFresh={layer.id === freshLayerId}`
- Applied in both loose layer and folder group children render sites

## Test Results

| Test File | Tests | Result |
|-----------|-------|--------|
| use-builder-layers.add-dataset.test.ts | 11/11 | PASS |
| EmptyStackState.test.tsx | 14/14 | PASS |
| EmptyStackState.integration.test.tsx | 5/5 | PASS |
| UnifiedStackPanel.test.tsx | 29/29 | PASS |
| resources.test.ts | 1 failed (pre-existing) | PRE-EXISTING FAILURE |

**resources.test.ts failure:** Pre-existing issue — DE/FR/ES locales missing newer keys (a11y, bulkActions, freshLayerId-adjacent strings). Phase 1044 owns locale fill. This failure was present before this plan and is not caused by our changes.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] EmptyStackState mock in UnifiedStackPanel.test.tsx missing eyebrowClassName export**
- **Found during:** Task 3 GREEN
- **Issue:** `vi.mock('../EmptyStackState')` factory didn't export `eyebrowClassName`; UnifiedStackPanel imports it and vitest threw "No eyebrowClassName export is defined on the mock"
- **Fix:** Added `eyebrowClassName` string constant to the mock factory in UnifiedStackPanel.test.tsx
- **Files modified:** `src/components/builder/__tests__/UnifiedStackPanel.test.tsx`
- **Commit:** 56357e20

None other — plan executed as written for all other tasks.

## Known Stubs

None. All wired data flows are real: freshLayerId comes from the hook's real useState, eyebrowClassName is a real class string, surface tokens resolve to real CSS variables defined in index.css (Plan 01 territory).

## Self-Check: PASSED

- [x] `builder.json` has 51 unique top-level keys, listboxLabel present
- [x] `freshLayerId` in use-builder-layers.ts return object: confirmed
- [x] `isFresh` prop on StackRow: confirmed
- [x] `eyebrowClassName` exported from EmptyStackState.tsx: confirmed
- [x] Inline `text-[10px] font-semibold tracking-wide` count in UnifiedStackPanel.tsx: 0
- [x] All 5 plan commits exist in git log
- [x] TypeScript typecheck: clean (0 errors)
