# Phase 1041: multi-layer-selection-and-bulk-ops — Pattern Map

**Mapped:** 2026-05-14
**Files analyzed:** 7 new/modified files
**Analogs found:** 7 / 7

---

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `frontend/src/components/builder/UnifiedStackPanel.tsx` | component | event-driven | itself (existing) | exact |
| `frontend/src/components/builder/StackRow.tsx` | component | event-driven | itself (existing) | exact |
| `frontend/src/components/builder/BulkActionBar.tsx` (new) | component | event-driven | `FolderGroupRow.tsx` inline confirmingDelete pattern | role-match |
| `frontend/src/components/builder/hooks/use-builder-layers.ts` | hook | CRUD + batch | itself (existing) + `UploadForm.tsx` allSettled pattern | exact + pattern-match |
| `frontend/src/components/builder/BasemapGroupRow.tsx` | component | event-driven | itself (existing) + `BasemapGroupRow` disabled-state pattern | exact |
| `frontend/src/components/builder/FolderGroupRow.tsx` | component | event-driven | itself (existing) | exact |
| `frontend/src/i18n/locales/en/builder.json` | config | — | itself (existing) | exact |

---

## Pattern Assignments

### `UnifiedStackPanel.tsx` (modify — add selection state + listbox ARIA + outside-click)

**Analog:** `frontend/src/components/builder/UnifiedStackPanel.tsx` (self) + `frontend/src/components/map/BasemapToggle.tsx` for outside-click

**Selection state + outside-click pattern.**

Add these to the component body (after existing `useDndContext()` call):

```typescript
// Selection state — ephemeral, not zustand
const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
const [lastToggleAnchor, setLastToggleAnchor] = useState<string | null>(null);
const stackPanelRef = useRef<HTMLDivElement>(null);

// Outside-click clears selection (BasemapToggle.tsx lines 24-31 pattern)
useEffect(() => {
  if (selectedIds.size === 0) return;
  function handleMouseDown(e: MouseEvent) {
    if (stackPanelRef.current?.contains(e.target as Node)) return;
    setSelectedIds(new Set());
  }
  document.addEventListener('mousedown', handleMouseDown);
  return () => document.removeEventListener('mousedown', handleMouseDown);
}, [selectedIds.size]);

// DnD drag-start clears selection (POL-10 mutual-exclusion)
// Wire via onDragStart in the parent DndContext in MapBuilderPage, not here
```

**Outside-click analog** (`frontend/src/components/map/BasemapToggle.tsx` lines 24-31):
```typescript
useEffect(() => {
  if (!open) return;
  function handleClick(e: MouseEvent) {
    if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
  }
  document.addEventListener('mousedown', handleClick);
  return () => document.removeEventListener('mousedown', handleClick);
}, [open]);
```

**Listbox ARIA update** (`UnifiedStackPanel.tsx` line 725 — existing `aria-multiselectable="false"`):
```typescript
// Change from:
aria-multiselectable="false"
// To:
aria-multiselectable="true"
aria-label={t('unifiedStack.title', { defaultValue: 'Layers' })}
```

**BulkActionBar render condition** (insert just before the closing `</div>` of the scrollable list, around line 864):
```tsx
{selectedIds.size >= 2 && (
  <BulkActionBar
    selectedIds={selectedIds}
    layers={layers}
    onClearSelection={() => setSelectedIds(new Set())}
    onBulkVisibility={handleBulkVisibility}
    onBulkOpacity={handleBulkOpacity}
    onBulkGroup={handleBulkGroup}
    onBulkUngroup={handleBulkUngroup}
    onBulkDelete={handleBulkDelete}
  />
)}
```

**SortableStackRow — thread selection props.** The inner `SortableStackRow` wrapper (lines 124-181) needs two new props: `isMultiSelected` and `onCmdClick`. Pass them through from the parent loop where layers are mapped (lines 800-819).

---

### `StackRow.tsx` (modify — add checkbox, multi-selection visual state, keyboard handler)

**Analog:** `frontend/src/components/builder/StackRow.tsx` (self)

**New props to add** (extend `StackRowProps` interface at line 26):
```typescript
interface StackRowProps {
  // ... existing props ...
  isMultiSelected?: boolean;        // row is in selectedIds
  isMultiSelectionActive?: boolean; // any row is in selectedIds (shows checkboxes)
  onCmdClick?: (id: string) => void;        // Cmd/Ctrl+click handler
  onShiftClick?: (id: string) => void;      // Shift+click handler
  onCheckboxClick?: (id: string) => void;   // checkbox toggle (= Cmd-click)
}
```

**Existing single-selection visual** (lines 152-154 — reference, do not change):
```typescript
selected && 'bg-[var(--primary-50,theme(colors.accent.DEFAULT))] shadow-[inset_2px_0_0_var(--primary)]',
```
Multi-selected rows use the IDENTICAL CSS classes. Checkbox is the only visual differentiator.

**Updated onClick handler** (replace `handleRowClick` at line 137):
```typescript
function handleRowClick(e: React.MouseEvent) {
  if (e.metaKey || e.ctrlKey) {
    e.preventDefault();
    onCmdClick?.(layer.id);
    return;
  }
  if (e.shiftKey) {
    e.preventDefault();
    onShiftClick?.(layer.id);
    return;
  }
  onSelectLayer(layer.id);
}
```

**Updated onKeyDown handler** (replace existing at lines 157-162):
```typescript
onKeyDown={(e) => {
  if (e.key === 'Enter') {
    e.preventDefault();
    onSelectLayer(layer.id);
  }
  if (e.key === ' ') {
    e.preventDefault();
    onCmdClick?.(layer.id); // Space = Cmd-click (toggles multi-selection)
  }
  if (e.key === 'Escape') {
    // Parent (UnifiedStackPanel) handles Escape via onKeyDown on the container
  }
  if (e.shiftKey && e.key === 'ArrowUp') {
    e.preventDefault();
    // Fire shift-click on the previous sibling — parent must wire this
  }
  if (e.shiftKey && e.key === 'ArrowDown') {
    e.preventDefault();
    // Fire shift-click on the next sibling — parent must wire this
  }
}}
```

**Cell 1 (Caret column) — Checkbox swap** (replace the existing hidden caret span at lines 164-171):
```tsx
{/* Cell 1: Caret column — hidden span at rest; Checkbox during multi-selection mode */}
{isMultiSelectionActive ? (
  <Checkbox
    className="h-3.5 w-3.5"
    checked={isMultiSelected}
    aria-checked={isMultiSelected}
    aria-label={`Select ${displayName}`}
    onClick={(e) => {
      e.stopPropagation();
      onCheckboxClick?.(layer.id);
    }}
    onPointerDown={(e) => e.stopPropagation()} // prevent row drag
  />
) : (
  <span aria-hidden="true" style={{ visibility: 'hidden' }} className="text-xs text-muted-foreground">▸</span>
)}
```

**Checkbox import** (add to existing imports at top of file):
```typescript
import { Checkbox } from '@/components/ui/checkbox';
```

**Checkbox component** (`frontend/src/components/ui/checkbox.tsx` lines 1-30 — already installed):
```typescript
import * as React from "react"
import { CheckIcon } from "lucide-react"
import { Checkbox as CheckboxPrimitive } from "radix-ui"
import { cn } from "@/lib/utils"

function Checkbox({ className, ...props }: React.ComponentProps<typeof CheckboxPrimitive.Root>) {
  return (
    <CheckboxPrimitive.Root
      data-slot="checkbox"
      className={cn(
        "peer border-input dark:bg-input/30 data-[state=checked]:bg-primary data-[state=checked]:text-primary-foreground ...",
        className
      )}
      {...props}
    >
      <CheckboxPrimitive.Indicator ...>
        <CheckIcon className="size-3.5" />
      </CheckboxPrimitive.Indicator>
    </CheckboxPrimitive.Root>
  )
}
```

**aria-selected update** — the existing `aria-selected={selected}` at line 146 must expand to:
```typescript
aria-selected={selected || isMultiSelected}
```

---

### `BulkActionBar.tsx` (new — sticky footer, confirmation state machine)

**Primary analog:** `frontend/src/components/builder/FolderGroupRow.tsx` — the `confirmingDelete` inline state machine (lines 64, 311-346) and `StackRow.tsx` inline alertdialog (lines 357-389).

**Secondary analog:** `frontend/src/components/builder/StackRow.tsx` — Button ghost + destructive text pattern (line 318-323):
```tsx
<DropdownMenuItem
  className="text-destructive focus:text-destructive"
  onSelect={() => setConfirmingDelete(true)}
>
  {t('stackRow.kebabDeleteLayer', { defaultValue: 'Delete layer' })}
</DropdownMenuItem>
```

**FolderGroupRow inline confirm pattern** (lines 311-346 — base for BulkActionBar confirmation state):
```tsx
{confirmingDelete && (
  <div
    role="alertdialog"
    aria-labelledby={`confirm-delete-${groupId}`}
    className="mx-2 mb-2 p-3 rounded-md border bg-popover space-y-2"
    onClick={(e) => e.stopPropagation()}
  >
    <p id={`confirm-delete-${groupId}`} className="text-sm text-destructive text-center">
      {t('folderGroup.deleteConfirmMessage', ...)}
    </p>
    <div className="flex gap-2">
      <Button type="button" variant="destructive" className="flex-1"
        onClick={() => { onDeleteGroup(groupId); setConfirmingDelete(false); }}>
        {t('folderGroup.deleteConfirmAction', ...)}
      </Button>
      <Button type="button" variant="secondary" className="flex-1"
        onClick={() => setConfirmingDelete(false)}
        autoFocus>  {/* ← autoFocus on safe choice per AUD-09 */}
        {t('folderGroup.deleteConfirmCancel', ...)}
      </Button>
    </div>
  </div>
)}
```

**BulkActionBar skeleton** (new file — copy structure from FolderGroupRow + StackRow):
```typescript
import { memo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Eye, EyeOff, FolderPlus, FolderMinus, Trash2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Slider } from '@/components/ui/slider';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { cn } from '@/lib/utils';
import type { MapLayerResponse } from '@/types/api';

interface BulkActionBarProps {
  selectedIds: Set<string>;
  layers: MapLayerResponse[];
  onClearSelection: () => void;
  onBulkVisibility: (ids: Set<string>) => void;
  onBulkOpacity: (ids: Set<string>, opacity: number) => void;
  onBulkGroup: (ids: Set<string>) => void;
  onBulkUngroup: (ids: Set<string>) => void;
  onBulkDelete: (ids: Set<string>) => void;
}

export const BulkActionBar = memo(function BulkActionBar({ ... }: BulkActionBarProps) {
  const { t } = useTranslation('builder');
  const [confirmingDelete, setConfirmingDelete] = useState(false);

  const N = selectedIds.size;
  const selectedLayers = layers.filter((l) => selectedIds.has(l.id));
  const avgOpacity = selectedLayers.reduce((sum, l) => sum + (l.opacity ?? 1), 0) / N;
  const majorityVisible = selectedLayers.filter((l) => l.visible).length > N / 2;

  return (
    <div
      role="toolbar"
      aria-label={t('bulkActions.toolbarLabel', { count: N })}
      aria-live="polite"
      className={cn(
        'sticky bottom-0 flex items-center gap-1 px-3',
        'h-12 bg-[var(--surface-2)] border-t border-[var(--border)]',
        'rounded-bl-[var(--radius-md)] rounded-br-[var(--radius-md)]',
        'transition-all duration-150',
      )}
    >
      {/* ... bar content or confirmation state ... */}
    </div>
  );
});
```

**Bar container CSS** — copied exactly from UI-SPEC (no new tokens):
```css
position: sticky; bottom: 0;
height: 48px;               /* h-12 */
display: flex; align-items: center; gap: 4px;
padding: 0 12px;            /* px-3 */
background: var(--surface-2);
border-top: 1px solid var(--border);
border-bottom-left-radius: var(--radius-md);
border-bottom-right-radius: var(--radius-md);
```

**Tooltip disabled-button pattern** (from `UnifiedStackPanel.tsx` lines 685-706 — existing Tooltip usage):
```tsx
<Tooltip>
  <TooltipTrigger asChild>
    <button
      type="button"
      aria-label={t('unifiedStack.settings', { defaultValue: 'Settings' })}
      className={cn('flex h-[22px] w-[22px] items-center justify-center rounded ...', ...)}
      onClick={onSettingsClick}
    >
      <Settings className="h-4 w-4" aria-hidden="true" />
    </button>
  </TooltipTrigger>
  <TooltipContent side="bottom">
    {t('unifiedStack.settings', { defaultValue: 'Settings' })}
  </TooltipContent>
</Tooltip>
```

---

### `use-builder-layers.ts` (modify — add handleBulkOp with allSettled + rollback)

**Primary analog:** `frontend/src/components/builder/hooks/use-builder-layers.ts` (self) — existing single-layer remove pattern with optimistic update (lines 261-275):
```typescript
const handleRemove = useCallback((layerId: string) => {
  if (!mapId) return;
  setExpandedLayerId((prev) => prev === layerId ? null : prev);
  removeLayerMutation.mutate(
    { mapId, layerId },
    {
      onSuccess: () => {
        toast.success(t('toasts.layerRemoved'));
      },
      onError: () => {
        toast.error(t('toasts.layerRemoveFailed'));
      },
    },
  );
}, [mapId, removeLayerMutation, t]);
```

**Promise.allSettled pattern** (`frontend/src/components/import/UploadForm.tsx` lines 109-131):
```typescript
await Promise.allSettled(
  newEntries.map(async (entry) => {
    try {
      const result = await uploadFile(entry.file!);
      updateEntry(entry.id, { status: 'previewing' });
    } catch (err) {
      updateEntry(entry.id, { status: 'upload-failed', error: buildErrorDisplay(err, ...) });
    }
  }),
);
```

**handleBulkOp skeleton** (new addition to `use-builder-layers.ts` — place after `handleRemove`):
```typescript
const handleBulkVisibility = useCallback(async (selectedIds: Set<string>) => {
  const previousLayers = layersRef.current;
  const selectedLayers = previousLayers.filter((l) => selectedIds.has(l.id));
  const majorityVisible = selectedLayers.filter((l) => l.visible).length > selectedIds.size / 2;
  const nextVisible = !majorityVisible;

  // 1. Optimistic update — single setState call
  setLocalLayers((prev) =>
    prev.map((l) => selectedIds.has(l.id) ? { ...l, visible: nextVisible } : l),
  );
  setHasUnsavedChanges(true);

  // 2. Fire N parallel PATCHes
  const results = await Promise.allSettled(
    selectedLayers.map((l) =>
      // use the same per-layer callback that handleToggleVisibility uses internally:
      // applyLayerUpdate fires setLocalLayers + setHasUnsavedChanges again — avoid double-firing.
      // Instead call the underlying API function directly (removeLayerFromMapApi pattern):
      removeLayerFromMapApi(mapId!, l.id), // placeholder — swap for actual visibility PATCH
    ),
  );

  // 3. Any rejection → rollback + one error toast
  const anyFailed = results.some((r) => r.status === 'rejected');
  if (anyFailed) {
    setLocalLayers(previousLayers);
    setHasUnsavedChanges(false);
    toast.error(t('bulkActions.errorUpdateRolledBack'));
  }
  // Success: no toast — optimistic update IS the confirmation
}, [mapId, t]);
```

**Rollback pattern** — uses `previousLayers` snapshot (captured before optimistic update) via `layersRef.current`. This is the same pattern already used throughout `use-builder-layers.ts` with `layersRef`.

**Group/ungroup bulk handlers** — copy `handleCreateGroupWithLayer` (lines 282-317) and `handleUngroup` (lines 330-345) but accept a `Set<string>` and iterate. The logic is identical; just loop over selectedIds instead of a single layerId.

**Bulk delete** — copy `handleRemove` (lines 261-275) but call `Promise.allSettled` over N `removeLayerMutation.mutate` calls. Note: `removeLayerMutation` is a TanStack useMutation — prefer calling the raw `removeLayerFromMapApi` directly for parallel batching without the mutation's built-in serial queue. Then invalidate the query once on success.

**API endpoint for visibility/opacity PATCH** — the existing per-layer PATCH is the map save: `patchMapLayers(id, diff)` at `api/maps.ts:103-119`. For bulk ops use `removeLayerFromMapApi` for delete (`api/maps.ts:143-150`) and the map-level optimistic approach (no per-layer PATCH endpoint exists — handlers mutate `localLayers` then the save persists). Re-read: `handleToggleVisibility` in `use-layer-map-sync.ts` calls `applyLayerUpdate` which only mutates local state. No API call fires per toggle — they are all deferred to Save. **Implication for bulk ops:** the "N parallel PATCHes" from the UI-SPEC means N local state updates (which are already batched via the single `setLocalLayers` call). The error path (rollback on failure) only applies to the eventual save, not per-toggle. Clarify this with the planner: the bulk op is optimistic local mutation; the save gate is the same `handleSave` the user calls. The `Promise.allSettled` step is only needed for bulk delete (which calls `removeLayerFromMapApi` per layer and is not deferred to save).

---

### `BasemapGroupRow.tsx` (modify — refuse multi-selection)

**Analog:** `frontend/src/components/builder/BasemapGroupRow.tsx` (self) — existing `visibilityDisabled` pattern (lines 31-35, 132-146):
```typescript
aria-disabled={visibilityDisabled || undefined}
tabIndex={visibilityDisabled ? -1 : undefined}
className={cn(
  '...',
  visibilityDisabled ? 'opacity-30 cursor-default' : 'hover:text-foreground',
)}
onClick={(e) => {
  e.stopPropagation();
  if (!visibilityDisabled) onToggleVisibility(groupId);
}}
```

**New prop + cursor pattern** (add to BasemapGroupRow):
```typescript
interface BasemapGroupRowProps {
  // ... existing ...
  isMultiSelectionActive?: boolean; // shows cursor-not-allowed when Cmd+hover
}
```

In the row's `className` on the outer div (lines 75-80), add:
```typescript
isMultiSelectionActive && 'cursor-not-allowed',
```

The `onCmdClick` and `onShiftClick` handlers are simply absent from `BasemapGroupRow` — it never receives them, so Cmd-click falls through to plain `onSelectGroup` which is the normal single-selection path and does NOT add to `selectedIds` (that guard lives in `UnifiedStackPanel`).

---

### `FolderGroupRow.tsx` (modify — checkbox swap in caret column during multi-selection)

**Analog:** `frontend/src/components/builder/FolderGroupRow.tsx` (self) — caret button (lines 132-148):
```tsx
{/* Cell 1: Caret — visible and functional for group rows */}
<button
  type="button"
  aria-expanded={isExpanded}
  aria-controls={`folder-group-children-${groupId}`}
  aria-label={t('folderGroup.toggleExpand', { defaultValue: 'Toggle folder group' })}
  onClick={(e) => {
    e.stopPropagation();
    onToggleExpand(groupId);
  }}
  className={cn(
    'text-xs text-muted-foreground transition-transform',
    'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring rounded',
    isExpanded && 'rotate-90',
  )}
>
  ▸
</button>
```

**Swap pattern** — during multi-selection mode (`isMultiSelectionActive === true`), replace the caret button with `Checkbox` (identical to `StackRow.tsx` Cell 1 pattern above). When selection clears, the caret returns:
```tsx
{isMultiSelectionActive ? (
  <Checkbox
    className="h-3.5 w-3.5"
    checked={isMultiSelected}
    aria-checked={isMultiSelected}
    aria-label={`Select ${groupName}`}
    onClick={(e) => { e.stopPropagation(); onCheckboxClick?.(groupId); }}
    onPointerDown={(e) => e.stopPropagation()}
  />
) : (
  <button /* ... existing caret button ... */ >▸</button>
)}
```

**New props to add** to `FolderGroupRowProps`:
```typescript
isMultiSelected?: boolean;
isMultiSelectionActive?: boolean;
onCmdClick?: (id: string) => void;
onCheckboxClick?: (id: string) => void;
```

---

### `frontend/src/i18n/locales/en/builder.json` (modify — add `bulkActions` namespace key)

**Analog:** `frontend/src/i18n/locales/en/builder.json` — existing `stackRow` namespace (lines 731-745):
```json
"stackRow": {
  "dragHandle": "Drag to reorder {{name}}",
  "toggleVisibility": "Toggle visibility for {{name}}",
  "opacitySlider": "Opacity for {{name}}",
  "kebabTrigger": "Layer options for {{name}}",
  "kebabRenameLayer": "Rename layer",
  "kebabDeleteLayer": "Delete layer"
}
```

**New `bulkActions` key to add** (flat namespace, same level as `stackRow`):
```json
"bulkActions": {
  "selectedCount": "{{count}} selected",
  "toolbarLabel": "Bulk actions for {{count}} selected layers",
  "liveAnnouncement": "{{count}} layers selected.",
  "visibility": "Visibility",
  "visibilityAriaLabel": "Toggle visibility for {{count}} selected layers",
  "opacity": "Opacity",
  "opacityAriaLabel": "Set opacity for {{count}} selected layers",
  "group": "Group",
  "groupAriaLabel": "Group {{count}} selected layers",
  "groupDisabledTooltip": "Select only loose layers to group",
  "ungroup": "Ungroup",
  "ungroupAriaLabel": "Ungroup {{count}} selected groups",
  "ungroupDisabledTooltip": "Select only groups to ungroup",
  "delete": "Delete",
  "deleteAriaLabel": "Delete {{count}} selected layers",
  "deleteConfirmLabel": "Delete {{count}} layers? This cannot be undone.",
  "deleteConfirmAction": "Delete {{count}} layers",
  "deleteConfirmCancel": "Cancel",
  "errorUpdateRolledBack": "Failed to update layers — changes rolled back.",
  "errorDeleteRolledBack": "Failed to delete {{count}} layers — no changes made."
}
```

Note: the file currently has a **duplicate key bug** — `"unifiedStack"`, `"rail"`, `"stackRow"`, `"basemapGroup"`, `"basemapSublayer"`, `"demEditor"`, `"folderGroup"`, and `"layerEditor"` keys appear twice (lines 715-727 duplicated at lines 860-973). The planner should add `bulkActions` only once, and may optionally de-duplicate the file as a housekeeping step.

---

## Shared Patterns

### Row selected visual (single-selection AND multi-selection)
**Source:** `frontend/src/components/builder/StackRow.tsx` lines 152-154
**Apply to:** `StackRow.tsx`, `FolderGroupRow.tsx`, `BasemapGroupRow.tsx`
```typescript
selected && 'bg-[var(--primary-50,theme(colors.accent.DEFAULT))] shadow-[inset_2px_0_0_var(--primary)]',
```
Multi-selected rows use the identical CSS. Checkbox in Cell 1 is the only visual differentiator.

### Drag-handle stopPropagation
**Source:** `frontend/src/components/builder/StackRow.tsx` lines 184-185
**Apply to:** All interactive controls inside BulkActionBar (slider, buttons) must `stopPropagation` on `onPointerDown` and `onClick` to prevent row selection changes when interacting with bar controls.
```typescript
onPointerDown={(e) => e.stopPropagation()}
onClick={(e) => e.stopPropagation()}
```

### autoFocus on safe confirm choice
**Source:** `frontend/src/components/builder/FolderGroupRow.tsx` line 340 (AUD-09 pattern)
**Apply to:** `BulkActionBar` confirmation state — `autoFocus` on `Cancel` button, NOT on destructive `Delete {N} layers` button.
```tsx
<Button type="button" variant="secondary" autoFocus onClick={() => setConfirmingDelete(false)}>
  {t('bulkActions.deleteConfirmCancel')}
</Button>
```

### useTranslation + toast pattern
**Source:** `frontend/src/components/builder/hooks/use-builder-layers.ts` lines 1-4, 63-64
**Apply to:** `use-builder-layers.ts` bulk handlers, `BulkActionBar.tsx`
```typescript
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
// ...
const { t } = useTranslation('builder');
// ...
toast.error(t('bulkActions.errorUpdateRolledBack'));
```

### memo + stable callbacks (layersRef pattern)
**Source:** `frontend/src/components/builder/hooks/use-builder-layers.ts` lines 83-87
**Apply to:** `handleBulkVisibility`, `handleBulkOpacity`, `handleBulkDelete` in `use-builder-layers.ts`
```typescript
const layersRef = useRef(localLayers);
useLayoutEffect(() => {
  layersRef.current = localLayers;
}, [localLayers]);
```
Bulk handlers should snapshot `layersRef.current` (not `localLayers`) at the start of each call to get the current state without adding `localLayers` to `useCallback` deps.

### NOOP stable reference
**Source:** `frontend/src/components/builder/UnifiedStackPanel.tsx` line 33
**Apply to:** Any new optional prop fallbacks in `SortableStackRow`, `FolderGroupRowWrapper`.
```typescript
const NOOP = () => {}; // module-scope stable reference
```

### Disable pattern (opacity + pointer-events)
**Source:** UI-SPEC `BulkActionBar` disabled button spec
**Apply to:** Group, Ungroup buttons in `BulkActionBar.tsx` when conditions not met.
```typescript
className={cn(
  'opacity-40 cursor-not-allowed pointer-events-none',
  // applied conditionally when !canGroup or !canUngroup
)}
```

---

## Key Architecture Notes for Planner

1. **No new API endpoints.** Visibility, opacity, group, ungroup ops are all in-memory mutations to `localLayers` that persist when the user hits Save (same as all other builder edits). Only bulk delete calls `removeLayerFromMapApi` directly (one call per selected layer) and is the only operation needing `Promise.allSettled` + rollback.

2. **Selection state location.** `useState<Set<string>>` in `UnifiedStackPanel` (not zustand). The set is threaded down as `selectedIds` + `isMultiSelectionActive` (derived: `selectedIds.size > 0`) props to `SortableStackRow`, `FolderGroupRowWrapper`, `SortableStackRow` inside folder children.

3. **DnD mutual exclusion.** The `onDragStart` callback already exists in `MapBuilderPage`. Add `setSelectedIds(new Set())` there — `UnifiedStackPanel` does not own the DndContext, so this guard lives one level up.

4. **i18n file has duplicate keys.** The `en/builder.json` file contains duplicate top-level keys (`unifiedStack`, `rail`, `stackRow`, etc. appear twice). Add `bulkActions` once at the end of the first occurrence block (before line 859). A cleanup pass to remove the duplicate block would be a bonus.

5. **Checkbox is already installed.** `frontend/src/components/ui/checkbox.tsx` exists (confirmed). No `npx shadcn add checkbox` needed.

---

## No Analog Found

All files have close analogs in the existing codebase. No files require falling back to RESEARCH.md patterns only.

---

## Metadata

**Analog search scope:** `frontend/src/components/builder/`, `frontend/src/components/map/`, `frontend/src/components/import/`, `frontend/src/api/`, `frontend/src/hooks/`, `frontend/src/components/ui/`
**Files scanned:** 15 source files read directly; 10 grep searches
**Pattern extraction date:** 2026-05-14
