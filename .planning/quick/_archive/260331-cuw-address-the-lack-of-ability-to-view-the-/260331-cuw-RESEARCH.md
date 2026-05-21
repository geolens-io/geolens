# Quick Task 260331-cuw: Full Table View on Dataset Details Page - Research

**Researched:** 2026-03-31
**Domain:** Frontend CSS layout, table UX, React component patterns
**Confidence:** HIGH

## Summary

The horizontal scroll issue has a clear root cause: the `AttributeTable` wraps its `<Table>` in a `<div className="rounded-md border overflow-auto">`, but the `<Table>` component (`ui/table.tsx`) already wraps the `<table>` in its own `<div className="relative w-full overflow-x-auto">`. This creates nested overflow containers -- the inner one scrolls but is constrained by the outer one, which has no explicit width constraint to trigger scrollbar appearance. The fix is to remove the outer `overflow-auto` wrapper in `AttributeTable` and let the `Table` component's built-in scroll container handle it, OR remove the inner wrapper from the `Table` component usage and keep the outer one with `min-w-0` on flex parents.

The expand/collapse mechanism for vector datasets (map collapse + table fill) can follow the existing pattern already used for table-type datasets on `DatasetPage.tsx` (lines 470-491), which already has a `Minimize2`/`Maximize2` toggle for the hero data grid.

**Primary recommendation:** Fix the double-overflow nesting, add expand toggle to DataTab for vector datasets, and apply table polish (striping, hover, density, truncation tooltips).

<user_constraints>
## User Constraints (from CONTEXT.md)

### Implementation Decisions
- Expand button on the data tab that collapses the map and expands the table to fill the page
- Map can be toggled back (collapse/expand toggle)
- Expanded table fills available viewport height with internal scroll
- Pagination footer stays pinned at bottom
- Column visibility: Claude's discretion
- Table polish: row striping, hover states, better column headers, cell alignment, truncation handling
- Interaction gaps: missing features like sort, export, row click-to-detail, keyboard navigation
- Visual density: compact/comfortable row heights, font sizing, spacing between elements
</user_constraints>

## Root Cause Analysis: Horizontal Scroll

### The Problem (HIGH confidence -- verified by reading source)

**Double overflow container nesting:**

1. `AttributeTable.tsx` line 223: `<div className="rounded-md border overflow-auto">`
2. `ui/table.tsx` line 11: Table component wraps `<table>` in `<div className="relative w-full overflow-x-auto">`

The inner div has `overflow-x-auto` but `w-full` -- it sizes to its parent, not its content. The outer div has `overflow-auto` but no width constraint forcing it smaller than the table content. The `<table>` has `w-full` which means it sizes to container, not to natural column width.

Additionally, `CardContent` has `px-6` padding but no `overflow-hidden` or `min-w-0`, so in a flex context the card may not constrain width properly.

### The Fix

1. Remove the outer `<div className="rounded-md border overflow-auto">` wrapper from `AttributeTable.tsx` (or change to just `rounded-md border` without overflow).
2. The `Table` component's built-in `overflow-x-auto` container will handle horizontal scrolling.
3. Add `min-w-0` to `CardContent` wrapper or the DataTab's Card to prevent flex blowout.
4. Remove `w-full` from the `<table>` element OR keep it but ensure columns have `min-width` set so the table can grow beyond container width.
5. Consider adding `className="min-w-[800px]"` or similar to the `<table>` to force it wider than container when many columns exist, triggering the scrollbar.

**Key insight:** The `<table>` needs to be wider than its scroll container for a scrollbar to appear. With `w-full` it always matches the container. Either use `w-max` / `min-w-max` on the table, or set explicit `min-width` on columns.

## Architecture: Expand/Collapse Pattern

### Recommended Approach (HIGH confidence)

The DatasetPage already manages hero expand state (`isHeroExpanded` state, line 97). Extend this pattern:

1. **Add `isTableExpanded` state** to `DatasetPage` (or reuse `isHeroExpanded` inverted).
2. **When table is expanded:**
   - Hide the hero map section (`!isTable && !isTableExpanded`)
   - Render DataTab outside the DetailPanel tabs, filling viewport: `h-[calc(100vh-<header>)]`
   - Pagination footer pinned with `sticky bottom-0`
3. **Toggle button:** Place in DataTab's CardHeader or as a floating button. Use `Maximize2`/`Minimize2` icons (already imported in DatasetPage).
4. **State management:** Local `useState` is sufficient -- no URL param needed since this is a transient view preference.

### Component Structure Change

```
DatasetPage
  |-- Hero Map (hidden when table expanded)
  |-- DetailPanel tabs (hidden when table expanded)
  |-- ExpandedTableView (shown when table expanded)
       |-- toolbar (collapse button, column visibility, density toggle)
       |-- table container (flex-1, overflow-y-auto)
       |-- pagination footer (sticky/pinned)
```

Alternatively, keep it simpler: pass `expanded` prop to DataTab and let it conditionally render with full-height styles. The expand button lives in the DataTab header area.

## Table UX Improvements

### Row Striping
Add to `TableBody` or via even/odd selector:
```tsx
// In AttributeTable, on TableRow:
<TableRow key={row.id} className={row.index % 2 === 0 ? '' : 'bg-muted/30'}>
```
Or use Tailwind's `even:bg-muted/30` on `<tr>`.

### Hover States
Already present in `ui/table.tsx` TableRow: `hover:bg-muted/50`. This is working.

### Cell Truncation with Tooltip
Current: `<TableCell className="max-w-xs truncate">` -- truncates but no way to see full value.

Fix: Wrap cell content in a `<Tooltip>` (component exists at `ui/tooltip.tsx`) that shows full value on hover. Only show tooltip when text is actually truncated (compare `scrollWidth > clientWidth`).

### Column Visibility Toggle
Use a `DropdownMenu` (exists at `ui/dropdown-menu.tsx`) with checkboxes for each column. TanStack Table has built-in column visibility: `table.getColumn(id)?.toggleVisibility()` and `table.getAllColumns().filter(c => c.getCanHide())`.

### Density Toggle
Two modes: compact (`py-1 text-xs`) and comfortable (current `py-3`). Store preference in a local state or localStorage. Apply via className toggle on Table/TableCell.

### Sorting
The current API uses cursor-based pagination and server-side filtering. Client-side sorting of the current page is possible with TanStack Table's `getSortedRowModel()`. Full server-side sort would require backend changes (out of scope for quick task -- recommend client-side sort of visible page only).

```tsx
import { getSortedRowModel } from '@tanstack/react-table';

const table = useReactTable({
  data: data?.rows ?? [],
  columns,
  getCoreRowModel: getCoreRowModel(),
  getSortedRowModel: getSortedRowModel(),
  state: { sorting },
  onSortingChange: setSorting,
});
```

## Existing Project Patterns

| Pattern | Location | Relevant |
|---------|----------|----------|
| Hero expand/collapse | `DatasetPage.tsx` lines 97, 470-491 | Yes -- reuse for vector table expand |
| Table component | `ui/table.tsx` | Base component, already has overflow-x-auto |
| Tooltip | `ui/tooltip.tsx` | Use for truncated cell values |
| DropdownMenu | `ui/dropdown-menu.tsx` | Use for column visibility toggle |
| Maximize2/Minimize2 icons | Already imported in DatasetPage | Reuse for expand toggle |
| Card wrapping | `DataTab.tsx` wraps in Card | May need to strip Card in expanded mode |

## Don't Hand-Roll

| Problem | Don't Build | Use Instead |
|---------|-------------|-------------|
| Column visibility | Custom checkbox list | TanStack Table built-in `columnVisibility` state |
| Sorting | Manual array sort | TanStack Table `getSortedRowModel()` |
| Tooltip for truncation | Custom hover div | shadcn `Tooltip` component |
| Column show/hide dropdown | Custom popover | shadcn `DropdownMenu` with `DropdownMenuCheckboxItem` |

## Common Pitfalls

### Pitfall 1: Nested Overflow Containers
**What goes wrong:** Two nested divs both with `overflow-auto/overflow-x-auto` where the inner one is `w-full` -- the inner div never overflows because it matches parent width.
**How to avoid:** Single overflow container. The scrolling div must be the direct parent of the element that exceeds its width.

### Pitfall 2: Table w-full Prevents Horizontal Scroll
**What goes wrong:** `<table className="w-full">` constrains table to container width. Columns compress instead of triggering scroll.
**How to avoid:** Use `w-max` or `min-w-max` on the table element, or set explicit `min-width` values on columns/table.

### Pitfall 3: Sticky Header in Scrollable Table
**What goes wrong:** `sticky top-0` on thead works for vertical scroll but breaks when the scroll container also has horizontal scroll -- the header cells scroll horizontally with content (correct) but may lose background on scroll.
**How to avoid:** Ensure the sticky header has `bg-muted/80 backdrop-blur-sm` (already present) and `z-10`.

### Pitfall 4: Expanded View Height Calculation
**What goes wrong:** Using `h-screen` or `100vh` without accounting for header/navbar height causes content to overflow below viewport.
**How to avoid:** Use `h-[calc(100vh-<header_height>)]` or CSS `dvh` units. Better: use `flex-1` within a flex column layout that has a known height.

## Sources

### Primary (HIGH confidence)
- Direct source code reading: `AttributeTable.tsx`, `ui/table.tsx`, `DataTab.tsx`, `DatasetPage.tsx`, `PageShell.tsx`, `card.tsx`, `DetailPanel.tsx`
- TanStack Table API (column visibility, sorting) -- from training data, well-established API

## Metadata

**Confidence breakdown:**
- Horizontal scroll fix: HIGH -- root cause verified in source code
- Expand/collapse pattern: HIGH -- existing pattern in codebase to extend
- Table UX improvements: HIGH -- standard shadcn/TanStack patterns
- Sorting (client-side): MEDIUM -- need to verify getSortedRowModel works with current TanStack version

**Research date:** 2026-03-31
**Valid until:** 2026-04-30
