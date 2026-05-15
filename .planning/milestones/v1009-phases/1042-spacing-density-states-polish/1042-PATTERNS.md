---
phase: 1042
slug: spacing-density-states-polish
status: ready_for_planning
mapped: 2026-05-14
---

# Phase 1042: spacing-density-states-polish — Pattern Map

**Mapped:** 2026-05-14
**Files analyzed:** 16 modified files (no new files)
**Analogs found:** 16 / 16 (all files have internal analogs — this is a polish pass on existing code)

---

## File Classification

| Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `frontend/src/index.css` | config/tokens | transform | itself (lines 512–547, existing drag blocks) | exact |
| `frontend/src/components/builder/UnifiedStackPanel.tsx` | component | event-driven | itself (lines 817–841, header buttons); `SidebarRail.tsx` (focus-visible pattern) | exact |
| `frontend/src/components/builder/StackRow.tsx` | component | event-driven | itself (line 174, focus-visible ring pattern) | exact |
| `frontend/src/components/builder/BasemapGroupRow.tsx` | component | event-driven | `StackRow.tsx` (drag handle + useSortable pattern) | role-match |
| `frontend/src/components/builder/FolderGroupRow.tsx` | component | event-driven | `LayerEditorPanel.tsx` (caret transition pattern, line 449) | role-match |
| `frontend/src/components/builder/LayerEditorPanel.tsx` | component | event-driven | itself (lines 447–519, collapsible caret + `px-4 py-2` content divs) | exact |
| `frontend/src/components/builder/BasemapGroupEditorScene.tsx` | component | event-driven | `LayerEditorPanel.tsx` (section `px-4 py-2` pattern, line 291); `UnifiedStackPanel.tsx` (7-cell grid, line 427) | role-match |
| `frontend/src/components/builder/BasemapSublayerEditorScene.tsx` | component | event-driven | `LayerEditorPanel.tsx` (section padding pattern) | role-match |
| `frontend/src/components/builder/SettingsEditorScene.tsx` | component | event-driven | `LayerEditorPanel.tsx` (section padding pattern) | role-match |
| `frontend/src/components/builder/DEMEditorScene.tsx` | component | event-driven | `LayerEditorPanel.tsx` (section padding pattern) | role-match |
| `frontend/src/components/builder/DatasetSearchPanel.tsx` | component | request-response | `MapCardSkeleton.tsx` (Skeleton usage pattern); itself (lines 220–237, drag row outer div) | role-match |
| `frontend/src/components/builder/SidebarRail.tsx` | component | event-driven | `StackRow.tsx` (hover token `bg-[var(--surface-2)]` at line 429) | role-match |
| `frontend/src/components/builder/EmptyStackState.tsx` | component | event-driven | itself (lines 80–86, suggest card; lines 192–221, inline search) | exact |
| `frontend/src/components/builder/BulkActionBar.tsx` | component | event-driven | itself (lines 107–120, container; line 145, Cancel button) | exact |
| `frontend/src/i18n/locales/en/builder.json` | config | transform | itself (lines 884–998, surviving block) | exact |
| `frontend/src/components/builder/hooks/use-builder-layers.ts` | hook | event-driven | itself (lines 597–, `handleAddDataset` callback) | exact |

---

## Cluster A: index.css additions

### `frontend/src/index.css` — motion tokens + bloom + group-children wash

**Analog:** Existing drag-polish blocks in `frontend/src/index.css` (lines 512–547).

**AUD-08 — Motion tokens (add to `:root`, MUST LAND FIRST):**

Confirmed: `--motion-fast` and `--motion-base` are **absent** from `index.css` `:root`. Neither grep match appears. The two tokens must be added. All subsequent `duration-[--motion-fast]` Tailwind classes depend on this landing first.

```css
/* Phase 1042 AUD-08: motion timing tokens */
--motion-fast: 150ms;
--motion-base: 250ms;
```

**Insertion point:** After the existing token block (`:root` closes around line 210 in dark-mode section). Add to both `:root` and `.dark` selectors, or just `:root` since these are universal timing values.

**AUD-03 confirm (lines 526–529):**

Already present at `index.css:527`:
```css
/* Phase 1040 AUD-03: hide any .kebab element during catalog→stack drag */
.dragging-active .kebab {
  opacity: 0 !important;
}
```
No change needed. Planner should verify only.

**Carry-over: Insertion line bloom (add to existing `[data-dnd-over="true"]` block at line 515–517):**

Current state at lines 514–517:
```css
[data-dnd-over="true"] {
  border-top: 2px solid var(--primary);
}
```

Target state (add `border-radius` + `box-shadow`):
```css
[data-dnd-over="true"] {
  border-top: 2px solid var(--primary);
  border-radius: 9999px;
  box-shadow: 0 0 0 2px oklch(0.55 0.18 250 / 25%);
}
```

Note: `--radius-full` does not exist in `index.css`. Use `9999px` literal per UI-SPEC.

**Carry-over: Group-children wash (add after line 546):**

Current `[data-group-drop-target="true"]` block at lines 542–546 only styles the target row itself. A sibling/descendant rule for the children container is missing.

```css
/* Phase 1042: folder group-children wash when parent is drop target */
[data-group-drop-target="true"] + .folder-group-children,
[data-group-drop-target="true"] .folder-group-children {
  background: oklch(0.97 0.02 250 / 60%);
  border-radius: var(--radius-md);
}
```

Note: The correct combinator (`+` sibling vs descendant `.`) depends on the DOM structure in `UnifiedStackPanel.tsx`. The planner must verify whether `.folder-group-children` is a next sibling or a descendant of `[data-group-drop-target]`. Check `UnifiedStackPanel.tsx` around line 362–390.

---

## Cluster B: BulkActionBar fixes

### `frontend/src/components/builder/BulkActionBar.tsx`

**Analog:** Itself.

**Current container (lines 107–116):**
```tsx
<div
  role="toolbar"
  className={cn(
    'sticky bottom-0 flex items-center gap-1 px-3',
    'h-12 bg-[var(--surface-2)] border-t border-[var(--border)]',
    'rounded-bl-[var(--radius-md)] rounded-br-[var(--radius-md)]',
    'transition-all duration-150',
  )}
>
```

**Fix 1 — gap (line 112):** Change `gap-1` → `gap-2`.

**Fix 2 — mount animation (no-op pattern):** The current `transition-all duration-150` on line 115 is a no-op because there is no initial-state class to transition FROM. The container renders fully visible immediately.

Apply mount animation using `useState` + `useEffect` + `requestAnimationFrame`:
```tsx
const [mounted, setMounted] = useState(false);
useEffect(() => {
  requestAnimationFrame(() => setMounted(true));
}, []);
```

Then modify the container `className`:
```tsx
className={cn(
  'sticky bottom-0 flex items-center gap-2 px-3',
  'h-12 bg-[var(--surface-2)] border-t border-[var(--border)]',
  'rounded-bl-[var(--radius-md)] rounded-br-[var(--radius-md)]',
  'transition-all duration-[--motion-fast]',
  mounted ? 'translate-y-0 opacity-100' : 'translate-y-2 opacity-0',
)}
```

**Fix 3 — Cancel button variant (line 145):**

Current:
```tsx
<Button
  type="button"
  variant="secondary"
  size="sm"
  autoFocus
  ...
>
```

Change `variant="secondary"` → `variant="ghost"`.

**Fix 4 — Button label breakpoints (lines 203, 213, 244, 264, 291, 311, 337):**

All label `<span>` elements use `hidden xl:inline`. Example:
```tsx
<span className="hidden xl:inline text-xs">
```

At 340px sidebar width, `xl` (1280px viewport) never triggers. Fix options in priority order:
1. Change to `hidden sm:inline` — still won't trigger at 340px sidebar in isolation, but is more correct
2. Wrap each enabled button's label in a `<Tooltip>` identical to the pattern already used for disabled buttons (same disabled-button tooltip pattern present in file). Use same copy as the `<span>` text.

**Pattern for Tooltip wrapping (existing disabled button pattern around line 254–268):**
```tsx
<Tooltip>
  <TooltipTrigger asChild>
    <Button ...>
      <Icon />
      <span className="hidden sm:inline text-xs">{label}</span>
    </Button>
  </TooltipTrigger>
  <TooltipContent>{label}</TooltipContent>
</Tooltip>
```

---

## Cluster C: DatasetSearchPanel — cursor-grab + skeleton loading

### `frontend/src/components/builder/DatasetSearchPanel.tsx`

**Analog:** `frontend/src/components/maps/MapCardSkeleton.tsx` (Skeleton import pattern); `StackRow.tsx` lines 222–224 (cursor-grab/grabbing pattern on drag handle).

**Skeleton component:** `frontend/src/components/ui/skeleton.tsx` is installed. It uses `animate-shimmer` (defined in `index.css:355`). Import: `import { Skeleton } from '@/components/ui/skeleton';`.

**Skeleton pattern (from MapCardSkeleton.tsx lines 7–15):**
```tsx
<Skeleton className="h-5 w-2/3" />
<Skeleton className="h-3 w-full" />
```

**AUD-10 — Skeleton rows for first load:** Replace the current single-spinner block (lines 640–644):
```tsx
{/* State: Loading */}
{activeTab !== 'basemap' && !isError && (isLoading || isFetching) && (
  <div className="flex items-center justify-center py-3">
    <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
  </div>
)}
```

With conditional split: skeletons on `isLoading`, progress band on `isFetching && !isLoading`:
```tsx
{/* State: Loading — first fetch skeleton */}
{activeTab !== 'basemap' && !isError && isLoading && (
  <div className="mt-3 space-y-1 px-1">
    {Array.from({ length: 5 }).map((_, i) => (
      <Skeleton key={i} className="h-[58px] w-full rounded-md" />
    ))}
  </div>
)}
{/* State: Refetching — progress band */}
{activeTab !== 'basemap' && !isError && isFetching && !isLoading && (
  <div className="h-0.5 w-full bg-[var(--primary)] animate-pulse" />
)}
```

The existing `pointer-events-none opacity-50` at line 687 handles the dimmed list during refetch — keep it.

**AUD-12 — Filter chip heights:** Current filter chips at lines 585, 597, 608, 620 use `h-6` (24px). ToggleGroupItem at lines 564–574 already use `h-7` (28px, correct). Fix filter chip buttons to `h-7`:
```tsx
className="h-7 rounded px-2 text-xs"
```

**AUD-13 — Progress band:** Handled above in AUD-10 combined fix.

**AUD-15 — Disclosure icon swap (line 258):**

Current:
```tsx
{expanded ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
```

Target (matches `LayerEditorPanel.tsx:449` pattern):
```tsx
<ChevronRight className={cn('h-3.5 w-3.5 transition-transform duration-[--motion-fast]', expanded && 'rotate-90')} />
```

Remove `ChevronDown` import if no other usage remains.

**Carry-over — cursor-grab on full row body (line 231–236):**

Current outer div for `DraggableDatasetRow` (line 231):
```tsx
<div
  ref={setNodeRef}
  className={cn(
    'group/row rounded-md border border-border/60 bg-background',
    isDragging && 'opacity-40 bg-[var(--surface-2)]',
  )}
>
```

Add cursor classes to the outer div (not just the handle button):
```tsx
className={cn(
  'group/row rounded-md border border-border/60 bg-background',
  isDragging && 'opacity-40 bg-[var(--surface-2)]',
  !isDragging && 'cursor-grab',
  isDragging && 'cursor-grabbing',
)}
```

Same fix applies to `DraggableBasemapRow` outer div at line 322.

---

## Cluster D: LayerEditorPanel + Settings spacing/density

### `frontend/src/components/builder/LayerEditorPanel.tsx`

**AUD-05 — Header padding (line 203):**

Current:
```tsx
className="flex flex-col px-2 py-2 border-b shrink-0"
```

Target:
```tsx
className="flex flex-col px-4 py-3 border-b shrink-0"
```

**AUD-06 — Type pill color (lines 73–93, `LayerEditorTypePill` function):**

Current (line 90):
```tsx
<span className="inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-[0.08em] bg-[var(--surface-2)] text-muted-foreground">
```

Target — derive from `caps.kind` (which is already computed at line 74):
```tsx
<span className={cn(
  'inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-[0.08em]',
  caps.kind === 'vector' && 'bg-[var(--type-vector-bg)] text-[var(--type-vector)]',
  (caps.kind === 'raster' || caps.kind === 'vrt') && 'bg-[var(--type-raster-bg)] text-[var(--type-raster)]',
  caps.kind === 'basemap' && 'bg-[var(--primary-50)] text-[var(--primary-700)]',
  !['vector','raster','vrt','basemap'].includes(caps.kind) && 'bg-[var(--surface-2)] text-muted-foreground',
)}>
```

Note: Confirm `--type-vector-bg`, `--type-vector`, `--type-raster-bg`, `--type-raster`, `--primary-700` exist in `index.css`. These are used elsewhere in the codebase (e.g., `UnifiedStackPanel.tsx:473`).

**AUD-07 — Caret duration consistency:**

Collapsible section carets in `LayerEditorPanel.tsx` at lines 449, 484, 518:
```tsx
<ChevronRight
  className={cn('h-4 w-4 shrink-0 transition-transform duration-150', filterOpen && 'rotate-90')}
/>
```

Change `duration-150` → `duration-[--motion-fast]` on all three (after AUD-08 motion tokens land in index.css).

Row carets in `BasemapGroupRow.tsx:104` — currently `transition-transform` with no duration:
```tsx
'text-xs text-muted-foreground transition-transform focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring rounded',
```
Add `duration-[--motion-fast]`.

Row carets in `FolderGroupRow.tsx:180` — same issue:
```tsx
'text-xs text-muted-foreground transition-transform',
```
Add `duration-[--motion-fast]`.

### `frontend/src/components/builder/BasemapGroupEditorScene.tsx`

**AUD-16 — Section padding (lines 78, 128, 207):**

Current:
```tsx
<div className="px-4 py-3">
```

Target:
```tsx
<div className="px-4 py-2">
```

Apply to all three occurrences. Also `line 207` content wrapper. Source pattern: `LayerEditorPanel.tsx:291,335,372` which already uses `px-4 py-2`.

**AUD-17 — Sublayer row layout (lines 137–203):**

Current — inline-style flex row (line 145):
```tsx
<li
  key={sublayer.id}
  style={{ height: '32px', display: 'flex', alignItems: 'center', gap: '8px', padding: '0 4px' }}
>
```

Target — canonical 7-cell grid from `UnifiedStackPanel.tsx:427`:
```tsx
<li
  key={sublayer.id}
  className="group/row grid grid-cols-[16px_14px_22px_22px_1fr_60px_22px] gap-2 items-center py-2 px-2"
>
```

Grid columns: `[16px_14px_22px_22px_1fr_60px_22px]`
- Col 1 (16px): caret — use `<span style={{ visibility: 'hidden' }} className="h-[14px] w-[14px]" />` (sublayers are not collapsible from scene B)
- Col 2 (14px): grip — use `<span className="opacity-0 pointer-events-none" />` (not draggable from scene B)
- Col 3 (22px): eye toggle — existing `<button>` (keep)
- Col 4 (22px): type icon — existing `<SublayerTypeIcon>` (keep, ensure 22px width)
- Col 5 (1fr): name `<span>` — existing (keep)
- Col 6 (60px): opacity slider — existing `<Slider className="w-[60px]">` (keep)
- Col 7 (22px): empty spacer for kebab column alignment — `<span />`

### `frontend/src/components/builder/BasemapSublayerEditorScene.tsx`

**AUD-16 — Section padding:** Same fix as BasemapGroupEditorScene. Grep `py-3` occurrences and change to `py-2`. Source pattern: `LayerEditorPanel.tsx:291`.

### `frontend/src/components/builder/SettingsEditorScene.tsx`

**AUD-16 — Section padding (lines 115, 167, 226, and collapsible section trigger buttons):**

Current collapsible button trigger (e.g., line 98):
```tsx
className="flex w-full items-center gap-2 px-4 py-3 hover:bg-[var(--surface-2,...)] border-b"
```

Change all `py-3` → `py-2` in section-level wrappers. Note: line 167 is a `<p>` — change its padding individually. Line 181 `h-9` row is a different control height — leave as-is.

### `frontend/src/components/builder/DEMEditorScene.tsx`

**AUD-16 — Section padding (lines 163, 203, 359):**

Current:
```tsx
<div className="px-4 py-3">
```

Change to `<div className="px-4 py-2">` at all three occurrences.

---

## Cluster E: i18n duplicate-key dedup

### `frontend/src/i18n/locales/en/builder.json`

**Structure confirmed:**

| Key block | First occurrence | Second occurrence |
|---|---|---|
| `"unifiedStack"` | line 715 | line 884 |
| `"rail"` | line 728 | line 898 |
| `"stackRow"` | line 731 | line 901 |
| `"basemapGroup"` | line 746 | line 916 |
| `"basemapSublayer"` | line 757 | line 927 |
| `"demEditor"` | line 773 | line 943 |
| `"folderGroup"` | line 790 | line 960 |
| `"layerEditor"` | line 798 | line 968 |

**Critical difference:** The second `"unifiedStack"` block (lines 884–896) contains one extra key — `"listboxLabel": "Map layers"` — that is ABSENT from the first block (lines 715–727). The surviving block must be lines 884–998 (the second copy).

**Action:** Delete lines 715–826 (first copy of the 8 namespaces). Keep lines 827–998 (includes `a11y`, `styleJson`, `bulkActions`, and the corrected second copy of the 8 namespaces).

After deletion, the JSON between `"unsavedChanges"` (line 710–714) and `"a11y"` must look like:
```json
  },
  "a11y": {
    "dragPickup": ...
```

**Verification command after dedup:**
```bash
cd frontend && npx vitest run src/i18n/__tests__/resources.test.ts
```

---

## Cluster F: State vocabulary unification

### `frontend/src/components/builder/UnifiedStackPanel.tsx` — AUD-01 + AUD-04

**AUD-01 — Header button sizes (lines 812–841):**

Settings cog button (lines 817–826):
```tsx
className={cn(
  'flex h-[22px] w-[22px] items-center justify-center rounded transition-colors',
  'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
  isSettingsOpen
    ? 'bg-[var(--primary-50,...)] text-primary'
    : 'text-muted-foreground hover:bg-accent hover:text-foreground',
)}
```

Change `h-[22px] w-[22px]` → `h-8 w-8`. Icon stays `h-4 w-4` (line 826). Also fix hover token `hover:bg-accent` → `hover:bg-[var(--surface-2)]` (aligns with AUD-21 pattern).

Add data button (line 836): Current `className="h-7 gap-1 px-2 text-xs"`. Change `h-7` → `h-8` for parity.

**AUD-04 — BasemapGroupRow grip:** The `useSortable` hook is invoked for the basemap row in `UnifiedStackPanel.tsx` but the basemap id is excluded from `sortableIds`. The grip button at `BasemapGroupRow.tsx:112–127` renders with `cursor-grab` but drag is a silent no-op.

Preferred fix: hide grip entirely in `BasemapGroupRow.tsx` at lines 112–127. Replace the grip button with:
```tsx
{/* Grip — hidden: basemap group is not user-draggable */}
<span aria-hidden="true" className="h-[14px] w-[14px]" />
```

Alternative (if `useSortable` props are needed for DnD collision detection): Add `opacity-0 pointer-events-none cursor-default` classes and `aria-hidden="true"`.

### `frontend/src/components/builder/SidebarRail.tsx` — AUD-21

Hover token at line 121:
```tsx
: 'hover:bg-accent',
```

Change to:
```tsx
: 'hover:bg-[var(--surface-2)]',
```

This matches the `StackRow.tsx:429` pattern: `'hover:bg-[var(--surface-2,theme(colors.accent.DEFAULT))]'`.

### `frontend/src/components/builder/UnifiedStackPanel.tsx` — AUD-19 (Settings cog icon size)

The AUD-01 fix to `h-8 w-8` button is the primary change. The icon inside should update from `h-4 w-4` to `h-[18px] w-[18px]` per UI-SPEC AUD-19 note (18px glyph in 32px box, not 16px).

### Focus-visible ring — existing pattern to copy

The established ring pattern from `StackRow.tsx:174`:
```tsx
'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset'
```

And from `SidebarRail.tsx:118`:
```tsx
'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring'
```

Use `ring-inset` variant for row-level elements (prevents ring overflow), standard variant for floating controls (buttons not in a clipped container).

---

## Cluster G: Loading affordance matrix

### `frontend/src/components/builder/hooks/use-builder-layers.ts` — freshLayerId

**Carry-over:** `freshLayerId` tracking for new-stack-row entry animation.

Current `handleAddDataset` at line 597 — no `freshLayerId` tracking. Pattern to add:

```tsx
const [freshLayerId, setFreshLayerId] = useState<string | null>(null);

// Inside handleAddDataset callback, after successful layer add:
setFreshLayerId(newLayer.id);
setTimeout(() => setFreshLayerId(null), 200);
```

Return `freshLayerId` from the hook and pass it down to `UnifiedStackPanel` → `StackRow`.

### `frontend/src/components/builder/StackRow.tsx` — entry animation

Accepts `isFresh?: boolean` prop. Apply to outer div:
```tsx
className={cn(
  // ... existing classes
  isFresh && 'animate-in fade-in duration-[--motion-fast]',
)}
```

`animate-in` and `fade-in` are from `tw-animate-css`, already imported at `index.css:8`. After AUD-08 motion tokens land, `duration-[--motion-fast]` resolves to 150ms.

### `frontend/src/components/builder/EmptyStackState.tsx` — AUD-23 + AUD-24 + AUD-02

**AUD-23 — Suggest card background (line 82):**
```tsx
'bg-[var(--surface-1)] hover:bg-[var(--surface-2)]...'
```
Change `--surface-1` → `--surface-0`.

**AUD-24 — Transition durations:**

Inline search container (lines 191–197):
```tsx
'transition-colors',
```
Add `duration-[--motion-fast]` after motion tokens land: `'transition-colors duration-[--motion-fast]'`.

Search icon button (line 208):
```tsx
className="flex items-center justify-center text-muted-foreground hover:text-foreground focus-visible:outline-none"
```
Add `transition-colors duration-[--motion-fast]`.

**AUD-02 — Eyebrow label extraction:**

The eyebrow class string `"block text-[10px] font-semibold tracking-wide text-muted-foreground uppercase px-1"` appears at:
- `EmptyStackState.tsx:227` (SUGGESTED label)
- `UnifiedStackPanel.tsx:585-595` (BASEMAP eyebrow label in dock)

Extract to a shared constant or micro-component. Pattern: define in a shared utility file or as a `cn()` constant exported from one of the two files. Simplest: add at top of `EmptyStackState.tsx`:

```tsx
const eyebrowClassName = 'block text-[10px] font-semibold tracking-wide text-muted-foreground uppercase px-1';
```

Then import and use in `UnifiedStackPanel.tsx`.

---

## Shared Patterns

### Focus-visible ring
**Source:** `frontend/src/components/builder/StackRow.tsx` (lines 174, 223, 237, 331)
**Apply to:** All interactive builder controls

Row-level (inset, prevents ring overflow in clipped containers):
```tsx
'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset'
```

Button/floating (standard offset):
```tsx
'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring'
```

### Hover token
**Source:** `frontend/src/components/builder/StackRow.tsx:429`
**Apply to:** All row hover states, SidebarRail buttons (AUD-21)
```tsx
'hover:bg-[var(--surface-2,theme(colors.accent.DEFAULT))]'
```

### Section padding (default-scene)
**Source:** `frontend/src/components/builder/LayerEditorPanel.tsx:291,335,372`
**Apply to:** All scene section content wrappers (BasemapGroupEditorScene, BasemapSublayerEditorScene, SettingsEditorScene, DEMEditorScene)
```tsx
<div className="px-4 py-2">
```

### Caret transition (after motion tokens land)
**Source:** `frontend/src/components/builder/LayerEditorPanel.tsx:449-450`
**Apply to:** All collapsible carets in all builder components
```tsx
<ChevronRight
  className={cn('h-4 w-4 shrink-0 transition-transform duration-[--motion-fast]', isOpen && 'rotate-90')}
/>
```

### Skeleton import
**Source:** `frontend/src/components/maps/MapCardSkeleton.tsx:2`
**Apply to:** DatasetSearchPanel loading state
```tsx
import { Skeleton } from '@/components/ui/skeleton';
```

### Tooltip wrapping for icon buttons
**Source:** `frontend/src/components/builder/UnifiedStackPanel.tsx:810-832` (Settings cog Tooltip pattern)
**Apply to:** BulkActionBar buttons when labels are hidden
```tsx
<Tooltip>
  <TooltipTrigger asChild>
    <Button ...>
      <Icon />
      <span className="hidden sm:inline text-xs">{label}</span>
    </Button>
  </TooltipTrigger>
  <TooltipContent>{label}</TooltipContent>
</Tooltip>
```

---

## Key Confirmations

| Researcher Question | Confirmed Finding |
|---|---|
| `--motion-fast` / `--motion-base` exist in index.css? | **No** — absent from `:root`. Must be added (AUD-08). |
| `--radius-full` exists? | **No** — absent. Use `9999px` literal. |
| shadcn `<Skeleton>` installed? | **Yes** — `frontend/src/components/ui/skeleton.tsx` exists. Uses `animate-shimmer` (index.css:355). |
| `animate-in` / `fade-in` available? | **Yes** — `tw-animate-css` imported at `index.css:8`. |
| AUD-03 `.dragging-active .kebab` rule already present? | **Yes** — `index.css:527`. No change needed. |
| Existing focus-visible pattern in builder? | **Yes** — `ring-2 ring-ring` at `StackRow.tsx:174`, `SidebarRail.tsx:118`, `BasemapGroupRow.tsx:104`, `DatasetSearchPanel.tsx:246,336`. Pattern is consistent. |
| i18n duplicate key block exact lines? | First copy: lines 715–826 (8 namespaces, missing `listboxLabel`). Second copy: lines 884–998 (surviving block, has `listboxLabel`). Delete lines 715–826. |
| `unifiedStack.listboxLabel` key only in second block? | **Yes** — line 896 in second block only. |
| BulkActionBar Cancel button current variant? | `variant="secondary"` at line 145. Change to `variant="ghost"`. |
| BulkActionBar gap current value? | `gap-1` at line 112. Change to `gap-2`. |
| BulkActionBar mount animation current state? | `transition-all duration-150` but no initial-state class — no-op. Fix with `useState(false)` + `requestAnimationFrame`. |
| Button labels breakpoint? | `hidden xl:inline` throughout. Change to `hidden sm:inline` + add Tooltip wrappers. |

---

## No Analog Found

None. All 16 files are existing builder components with clear internal analogs or established sibling-component patterns. No net-new file types.

---

## Metadata

**Analog search scope:** `frontend/src/components/builder/`, `frontend/src/index.css`, `frontend/src/i18n/locales/en/builder.json`, `frontend/src/components/ui/skeleton.tsx`, `frontend/src/components/maps/MapCardSkeleton.tsx`
**Files scanned:** 22
**Pattern extraction date:** 2026-05-14
