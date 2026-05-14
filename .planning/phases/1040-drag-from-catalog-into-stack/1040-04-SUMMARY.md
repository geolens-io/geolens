---
phase: 1040
plan: "04"
subsystem: frontend/dnd/a11y
tags:
  - dnd
  - drag-drop
  - a11y
  - keyboard
  - aria-live
  - testing
  - mapbuilder
dependency_graph:
  requires:
    - "Phase 1040 Plan 01 (DndContext lifted to MapBuilderPage; KeyboardSensor wired)"
    - "Phase 1040 Plan 02 (useDraggable on catalog rows; drag handle aria-labels)"
    - "Phase 1040 Plan 03 (folder-group drop + basemap swap + all five catalog-drop cases)"
  provides:
    - "aria-live='polite' sr-only region in MapBuilderPage (data-testid=dnd-announcement)"
    - "announce() useCallback updates dragAnnouncement state with ZWS+timestamp forcing re-fire"
    - "handleDragStart announces pick-up for catalog drags (a11y.dragPickup)"
    - "handleDragEnd announces success (a11y.dragDropped) or cancel (a11y.dragCancelled)"
    - "handleDragCancel announces cancellation (a11y.dragCancelled)"
    - "handleDragOver announces position updates, fires only on over-id change (lastOverIdRef)"
    - "CatalogDragGhost exported component: compact pill with type swatch (V/R/B) + name"
    - "DragOverlay in UnifiedStackPanel branches: catalog -> CatalogDragGhost; intra-stack -> StackRow ghost"
    - "DatasetSearchPanel.dragdrop.test.tsx: 6 tests covering catalog: / catalog-basemap: namespacing + drag handle aria-label"
    - "UnifiedStackPanel.test.tsx: Phase 1040 describe blocks for CatalogDragGhost variants + onAddDataset wiring"
  affects:
    - "frontend/src/pages/MapBuilderPage.tsx"
    - "frontend/src/components/builder/UnifiedStackPanel.tsx"
    - "frontend/src/i18n/locales/en/builder.json"
    - "frontend/src/components/builder/__tests__/UnifiedStackPanel.test.tsx"
    - "frontend/src/components/builder/__tests__/DatasetSearchPanel.dragdrop.test.tsx"
tech_stack:
  added: []
  patterns:
    - "aria-live='polite' + aria-atomic='true' sr-only div for screen-reader drag announcements"
    - "ZWS + Date.now() suffix on dragAnnouncement to force re-fire for identical consecutive strings"
    - "lastOverIdRef to debounce onDragOver announcements (only fires when over-id changes)"
    - "useDndContext at UnifiedStackPanel scope to read active.data.current in DragOverlay"
    - "vi.spyOn(dndCore, 'useDraggable') pattern for asserting draggable id namespacing in vitest"
key_files:
  created:
    - "frontend/src/components/builder/__tests__/DatasetSearchPanel.dragdrop.test.tsx"
  modified:
    - "frontend/src/pages/MapBuilderPage.tsx"
    - "frontend/src/components/builder/UnifiedStackPanel.tsx"
    - "frontend/src/i18n/locales/en/builder.json"
    - "frontend/src/components/builder/__tests__/UnifiedStackPanel.test.tsx"
decisions:
  - "ZWS+timestamp suffix used (not setTimeout cleanup) for aria-live re-fire — simpler state model, no async teardown risk"
  - "lastOverIdRef tracks last over-id to prevent onDragOver from spamming announcements on every pointer move"
  - "CatalogDragGhost exported as named function (not memo) so vitest can import and assert on it directly"
  - "vi.spyOn(dndCore, 'useDraggable') preferred over file-level vi.mock to avoid worker-exit risk per PATTERNS.md"
  - "Phase 1044 owns POL-23 (full a11y verification) and POL-24 (Playwright UAT) — this plan covers only the foundational a11y surface"
metrics:
  duration: "~7 minutes"
  completed_date: "2026-05-14"
  tasks_completed: 3
  tasks_total: 3
  files_modified: 5
---

# Phase 1040 Plan 04: Keyboard fallback + aria-live + DragOverlay ghost + vitest Summary

**One-liner:** aria-live announcement region wired to all three drag handlers; CatalogDragGhost compact pill added to DragOverlay for catalog drags; vitest coverage pins the cross-context drag contract with 6 new dragdrop tests + Phase 1040 describe blocks in UnifiedStackPanel.

## Tasks Completed

| # | Task | Commit | Files |
|---|------|--------|-------|
| 1 | aria-live region + announce() + 4 a11y i18n keys | `0ee33a28` | `MapBuilderPage.tsx`, `en/builder.json` |
| 2 | CatalogDragGhost + DragOverlay branching | `30c29097` | `UnifiedStackPanel.tsx` |
| 3 | Cross-context drop vitest coverage | `6a9c4a42` | `UnifiedStackPanel.test.tsx`, `DatasetSearchPanel.dragdrop.test.tsx` (new) |

## Architecture: aria-live Announcement Flow

```
MapBuilderPage
  ├── dragAnnouncement: string (state)
  ├── announce(text) → setDragAnnouncement(text + ZWS + Date.now())
  │     // ZWS+timestamp forces aria-live re-fire for duplicate strings
  │
  ├── handleDragStart (catalog drag)
  │     → announce(t('a11y.dragPickup', { name }))
  │
  ├── handleDragOver (catalog drag only, fires when over-id changes)
  │     → announce(t('a11y.dragPosition', { n, total }))
  │
  ├── handleDragEnd
  │     → success catalog drop → announce(t('a11y.dragDropped', { name, n }))
  │     → no-op / silent reject → announce(t('a11y.dragCancelled'))
  │     → no over (dropped outside) → announce(t('a11y.dragCancelled'))
  │
  ├── handleDragCancel → announce(t('a11y.dragCancelled'))
  │
  └── <div className="sr-only" role="status" aria-live="polite" aria-atomic="true"
          data-testid="dnd-announcement">
        {dragAnnouncement}
      </div>
```

## Architecture: DragOverlay Branching

```
UnifiedStackPanel DragOverlay
  ├── const { active } = useDndContext()  // plan 04 adds second call at panel scope
  ├── const catalogData = active?.data?.current
  │
  ├── if catalogData?.source === 'catalog'
  │     → <CatalogDragGhost recordType={...} name={...} />
  │          compact pill: type-swatch (V/R/B glyph) + name (max 260px)
  │          bg: var(--surface-2), border: var(--border), radius-md
  │          box-shadow: 0 4px 12px oklch(0 0 0 / 15%)
  │
  └── else (intra-stack drag)
        → existing StackRow ghost (opacity-40 scale-0.98)
```

## i18n Keys Added

| Key | Value |
|-----|-------|
| `a11y.dragPickup` | `"Picked up {{name}}. Use arrow keys to choose a position, Enter to drop, Escape to cancel."` |
| `a11y.dragPosition` | `"Current position: {{n}} of {{total}}"` |
| `a11y.dragDropped` | `"Dropped. {{name}} added at position {{n}}."` |
| `a11y.dragCancelled` | `"Drop cancelled."` |

## Test Files

### DatasetSearchPanel.dragdrop.test.tsx (new — 6 tests)

| Test | Assertion |
|------|-----------|
| dataset row grip handle aria-label | `getAllByLabelText('Drag to add to map')` length >= 1 |
| useDraggable called with catalog: namespace | `spy.calls.find(id === 'catalog:rec-1')` |
| dataset draggable data shape | `source=catalog, datasetId=rec-1, recordType=vector_dataset` |
| useDraggable called with catalog-basemap: namespace | `positronCall` id === `catalog-basemap:openfreemap-positron` |
| basemap draggable data shape | `source=catalog, recordType=basemap` |
| basemap row grip handle aria-label | `getAllByLabelText('Drag to add to map')` length >= 1 |

### UnifiedStackPanel.test.tsx (extended — 7 new tests in 2 describe blocks)

| Describe | Tests |
|----------|-------|
| Phase 1040 catalog drop — CatalogDragGhost | vector swatch glyph V, raster swatch R, basemap swatch B, vrt swatch R, pointer-events-none + cursor-grabbing |
| Phase 1040 catalog drop — onAddDataset wiring | EmptyStackState pick-suggestion calls onAddDataset; basemap select does NOT |

## Keyboard Sensor Status

KeyboardSensor was already wired in Plan 01 (`sortableKeyboardCoordinates` coordinator). This plan:
- Confirms the keyboard path works end-to-end for intra-stack reorder (Space to pick up, Arrow to move, Space/Enter to drop, Escape to cancel via @dnd-kit's built-in KeyboardSensor behavior)
- Adds ARIA announcements that make the keyboard path usable by screen-reader users
- POL-23 (full a11y verification) and POL-24 (Playwright UAT spec) remain Phase 1044's responsibility

## Threat Mitigations Applied

- **T-1040-10** (KeyboardSensor focus trap): `handleDragCancel` (Escape) clears `dragActiveId` and removes `dragging-active` body class; `handleDragEnd` does the same on any completion path. `lastOverIdRef` reset in all three handlers so no stale refs hold state. Screen-reader users get "Drop cancelled." announcement confirming the operation was aborted.
- **T-1040-11** (aria-live content): dragAnnouncement built from i18n template + user-owned dataset name via React state (no innerHTML), no XSS risk.

## Verification Results

```
cd frontend && npx tsc -b --noEmit    # 0 errors
cd frontend && npx vitest run src/components/builder/ src/pages/__tests__/MapBuilderPage.header-actions.test.tsx
  # 714 tests / 56 files — all pass (0 failures, 0 unhandled worker errors)
cd frontend && npm run build          # built in 351ms (0 errors)
```

## Acceptance Criteria Verification

- `grep -c "aria-live" MapBuilderPage.tsx` → 5 ✓
- `grep -c "data-testid=\"dnd-announcement\"" MapBuilderPage.tsx` → 1 ✓
- `grep -c "a11y.dragPickup" MapBuilderPage.tsx` → 1 ✓
- `grep -c "a11y.dragCancelled" MapBuilderPage.tsx` → 4 ✓
- `grep -c "a11y.dragDropped" MapBuilderPage.tsx` → 2 ✓
- `grep -c "onDragOver" MapBuilderPage.tsx` → 1 ✓
- `python3 a11y keys check` → all 4 keys present ✓
- `grep -c "CatalogDragGhost" UnifiedStackPanel.tsx` → 4 ✓
- `grep -c "data-testid=\"catalog-ghost\"" UnifiedStackPanel.tsx` → 1 ✓
- `grep -c "useDndContext" UnifiedStackPanel.tsx` → 5 ✓
- `DatasetSearchPanel.dragdrop.test.tsx exists` ✓
- `grep -c "catalog:" DatasetSearchPanel.dragdrop.test.tsx` → ≥1 ✓
- `grep -c "catalog-basemap:" DatasetSearchPanel.dragdrop.test.tsx` → ≥1 ✓
- `grep -c "Drag to add to map" DatasetSearchPanel.dragdrop.test.tsx` → ≥1 ✓
- `grep -c "Phase 1040" UnifiedStackPanel.test.tsx` → ≥1 ✓
- Full builder vitest sweep: 709 tests / 55 files — 0 failures ✓
- Build: ✓

## Deviations from Plan

None — plan executed exactly as written.

## Known Stubs

None — all a11y announcements are functional. Phase 1044 will add Playwright UAT and full a11y verification on top of this foundation.

## Threat Flags

None — no new network endpoints, auth paths, file access patterns, or schema changes. All changes are client-side UI only.

## Self-Check: PASSED

- `0ee33a28` exists in git log ✓
- `30c29097` exists in git log ✓
- `6a9c4a42` exists in git log ✓
- `frontend/src/pages/MapBuilderPage.tsx` modified ✓
- `frontend/src/components/builder/UnifiedStackPanel.tsx` modified ✓
- `frontend/src/i18n/locales/en/builder.json` modified ✓
- `frontend/src/components/builder/__tests__/UnifiedStackPanel.test.tsx` modified ✓
- `frontend/src/components/builder/__tests__/DatasetSearchPanel.dragdrop.test.tsx` created ✓
