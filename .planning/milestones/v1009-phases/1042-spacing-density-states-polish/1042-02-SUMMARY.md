---
phase: 1042-spacing-density-states-polish
plan: "02"
subsystem: builder-ui
tags:
  - builder
  - bulk-actions
  - catalog
  - loading
  - polish
  - tdd
dependency_graph:
  requires:
    - 1042-01 (motion tokens --motion-fast / --motion-base in :root)
  provides:
    - BulkActionBar with real mount animation, ghost Cancel, gap-2, Tooltip labels
    - DatasetSearchPanel with skeleton-loading, progress-band refetch, cursor-grab, ChevronRight rotate
  affects:
    - frontend/src/components/builder/BulkActionBar.tsx
    - frontend/src/components/builder/DatasetSearchPanel.tsx
tech_stack:
  added: []
  patterns:
    - requestAnimationFrame mount animation (useState false → rAF setMounted(true))
    - Skeleton placeholder rows (5x h-[58px]) for first-fetch loading state
    - Progress band (h-0.5 animate-pulse bg-primary) for refetch state
    - ChevronRight rotate-90 transition instead of icon swap
    - Tooltip wrapping enabled action buttons for AT reachability at narrow viewports
    - useQuery override pattern in tests via vi.mock factory with module-scope let
key_files:
  created: []
  modified:
    - frontend/src/components/builder/BulkActionBar.tsx
    - frontend/src/components/builder/__tests__/BulkActionBar.test.tsx
    - frontend/src/components/builder/DatasetSearchPanel.tsx
    - frontend/src/components/builder/__tests__/DatasetSearchPanel.test.tsx
decisions:
  - "Label visibility strategy: hidden sm:inline + Tooltip wrapper on each enabled action button. Both layers are intentional — sm:inline shows the label at medium+ viewports, Tooltip exposes the label to AT at all viewports. The Tooltip copy reuses the same t() call as the visible span (no new i18n keys)."
  - "ChevronDown import removed entirely. All disclosure carets in DatasetSearchPanel now use single ChevronRight with cn() rotate-90 conditional."
  - "useQuery override pattern: module-scope `let useQueryOverride = null` + vi.mock factory that delegates to real module when null; new tests set override in beforeEach. Avoids ESM spyOn limitation without file-level mock contamination of existing tests."
metrics:
  duration: "~7 minutes"
  completed: "2026-05-15T00:22:04Z"
  tasks_completed: 2
  files_modified: 4
  tests_added: 8
  tests_total_green: 43
---

# Phase 1042 Plan 02: BulkActionBar fixes + DatasetSearchPanel cursor-grab + skeleton + progress

**One-liner:** BulkActionBar mount transition (translate-y + opacity via rAF), ghost Cancel, gap-2, Tooltip labels at 340px; DatasetSearchPanel 5-row skeleton on first fetch, progress band on refetch, cursor-grab on full row, ChevronRight rotate-90.

## Tasks

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Fix BulkActionBar (gap, Cancel variant, mount animation, label visibility) | 61c307eb | BulkActionBar.tsx, BulkActionBar.test.tsx |
| 2 | DatasetSearchPanel — skeleton + progress band + filter heights + chevron + cursor-grab | 15f30aa2 | DatasetSearchPanel.tsx, DatasetSearchPanel.test.tsx |

## What Was Built

### Task 1: BulkActionBar (POL-14)

Four carry-over fixes from Phase 1041 UI review applied atomically:

1. **gap-2**: Container `gap-1` → `gap-2` (sketch sm=8px spec).
2. **Mount animation**: Added `useState(false)` + `useEffect(() => { const id = requestAnimationFrame(() => setMounted(true)); return () => cancelAnimationFrame(id); }, [])`. Container className now conditionally applies `translate-y-0 opacity-100` (mounted) vs `translate-y-2 opacity-0` (unmounted). Duration switched to `duration-[--motion-fast]` (Plan 01 token).
3. **Ghost Cancel**: Delete-confirm Cancel button changed from `variant="secondary"` to `variant="ghost"` (aligns with destructive-confirm pattern used elsewhere in builder; `autoFocus` preserved).
4. **Label visibility**: All 4 enabled action buttons (Visibility, Group, Ungroup, Delete) wrapped in `<Tooltip><TooltipTrigger asChild>...</TooltipTrigger><TooltipContent>{label}</TooltipContent></Tooltip>`. Label spans lowered from `hidden xl:inline` to `hidden sm:inline`. Disabled buttons retain their existing Tooltip wrapper structure unchanged.

Test fix: Pre-existing Test 2 asserted `aria-live="polite"` on the `role="toolbar"` element, but the live region is a separate `<span className="sr-only">` inside it. Fixed assertion to check the sr-only span and verify the toolbar itself does NOT carry aria-live (ARIA spec: container roles must not carry live region attributes).

### Task 2: DatasetSearchPanel (POL-15 / AUD-10/12/13/15)

**AUD-10 (P0) + AUD-13**: Replaced single `<Loader2 className="animate-spin">` block with conditional split:
- `isLoading` (first fetch): `Array.from({ length: 5 }).map((_, i) => <Skeleton key={i} className="h-[58px] w-full rounded-md" />)` inside `div.mt-3.space-y-1.px-1`.
- `isFetching && !isLoading` (refetch): `<div className="h-0.5 w-full bg-[var(--primary)] animate-pulse" />` placed above the existing dimmed list. The `pointer-events-none opacity-50` on the stale list is preserved as the "data is loading" signal.

**AUD-12**: Filter chip buttons at lines 585/597/608/620 changed from `h-6` (24px) to `h-7` (28px) to match the ToggleGroupItem uniform height. Search Input stays `h-9`. Basemap RecordTypeBadge stays `h-5`.

**AUD-15**: Both `DraggableDatasetRow` and `DraggableBasemapRow` disclosure carets changed from conditional `{expanded ? <ChevronDown /> : <ChevronRight />}` swap to single `<ChevronRight className={cn('h-3.5 w-3.5 transition-transform duration-[--motion-fast]', expanded && 'rotate-90')} />`. `ChevronDown` import removed (verified no other references remain).

**cursor-grab carry-over**: `DraggableDatasetRow` and `DraggableBasemapRow` outer divs gain `!isDragging && 'cursor-grab'` and `isDragging && 'cursor-grabbing'` in their `cn()` call. The inner grip handle button retains its own cursor-grab so the visual affordance persists between handle and body.

Removed unused imports: `ChevronDown`, `Loader2`. Added: `Skeleton` from `@/components/ui/skeleton`.

## Test Results

| File | Before | After |
|------|--------|-------|
| BulkActionBar.test.tsx | 19 passing | 23 passing (+4 new) |
| DatasetSearchPanel.test.tsx | 10 passing | 14 passing (+4 new) |
| DatasetSearchPanel.dragdrop.test.tsx | 6 passing | 6 passing (regression gate) |
| **Total** | **35** | **43** |

Verification commands all green:
- `npx vitest run src/components/builder/__tests__/BulkActionBar.test.tsx` — 23/23
- `npx vitest run src/components/builder/__tests__/DatasetSearchPanel.test.tsx` — 14/14
- `npx vitest run src/components/builder/__tests__/DatasetSearchPanel.dragdrop.test.tsx` — 6/6
- `npx tsc --noEmit` — 0 errors
- `npx eslint src/components/builder/BulkActionBar.tsx src/components/builder/DatasetSearchPanel.tsx` — 0 errors

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed pre-existing incorrect aria-live test assertion**
- **Found during:** Task 1 GREEN phase
- **Issue:** BulkActionBar.test.tsx Test 2 asserted `toolbar.toHaveAttribute('aria-live', 'polite')` but the toolbar (`role="toolbar"`) does not carry aria-live — the live region is the `<span className="sr-only" aria-live="polite">` child. ARIA spec forbids live region attributes on container roles.
- **Fix:** Rewrote test to assert the toolbar does NOT have aria-live, and that a child `[aria-live="polite"]` with `sr-only` class exists.
- **Files modified:** BulkActionBar.test.tsx
- **Commit:** 61c307eb

## Known Stubs

None. Both components render real data from real API hooks in production.

## Threat Flags

No new network endpoints, auth paths, file access patterns, or schema changes introduced. All changes are pure UI-layer (className changes, import swaps, conditional rendering of client-local state).

## Self-Check: PASSED

- [x] `frontend/src/components/builder/BulkActionBar.tsx` — exists and modified
- [x] `frontend/src/components/builder/__tests__/BulkActionBar.test.tsx` — exists and modified
- [x] `frontend/src/components/builder/DatasetSearchPanel.tsx` — exists and modified
- [x] `frontend/src/components/builder/__tests__/DatasetSearchPanel.test.tsx` — exists and modified
- [x] Commit `61c307eb` — exists (BulkActionBar task)
- [x] Commit `15f30aa2` — exists (DatasetSearchPanel task)
- [x] 43/43 tests green across all three test files
- [x] TypeScript clean (0 errors)
- [x] ESLint clean on modified source files
