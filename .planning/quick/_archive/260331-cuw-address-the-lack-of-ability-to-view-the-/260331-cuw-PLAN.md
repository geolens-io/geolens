---
phase: 260331-cuw
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - frontend/src/components/dataset/AttributeTable.tsx
  - frontend/src/components/dataset/tabs/DataTab.tsx
  - frontend/src/components/dataset/panels/DetailPanel.tsx
  - frontend/src/pages/DatasetPage.tsx
autonomous: false
requirements: [QTASK-01]

must_haves:
  truths:
    - "Table scrolls horizontally when columns exceed container width"
    - "User can expand the data tab to fill the page (map collapses)"
    - "User can collapse the expanded table to restore the map"
    - "Expanded table fills viewport height with internal vertical scroll"
    - "Pagination footer stays visible in both normal and expanded modes"
    - "Table rows have alternating stripe backgrounds for readability"
    - "Columns are sortable (client-side, current page)"
    - "Column visibility can be toggled via a dropdown menu"
  artifacts:
    - path: "frontend/src/components/dataset/AttributeTable.tsx"
      provides: "Horizontal scroll fix, row striping, sorting, column visibility, cell truncation tooltips"
    - path: "frontend/src/components/dataset/tabs/DataTab.tsx"
      provides: "Expand/collapse toggle, toolbar with column visibility and density controls"
    - path: "frontend/src/pages/DatasetPage.tsx"
      provides: "isTableExpanded state, conditional map/tab hiding when expanded"
    - path: "frontend/src/components/dataset/panels/DetailPanel.tsx"
      provides: "Passes onExpandTable callback through to DataTab"
  key_links:
    - from: "frontend/src/pages/DatasetPage.tsx"
      to: "frontend/src/components/dataset/panels/DetailPanel.tsx"
      via: "isTableExpanded state + onExpandTable callback prop"
      pattern: "isTableExpanded|onExpandTable"
    - from: "frontend/src/components/dataset/panels/DetailPanel.tsx"
      to: "frontend/src/components/dataset/tabs/DataTab.tsx"
      via: "expanded + onToggleExpand props"
      pattern: "expanded|onToggleExpand"
    - from: "frontend/src/components/dataset/AttributeTable.tsx"
      to: "frontend/src/components/ui/table.tsx"
      via: "Single overflow-x-auto container (Table component's built-in wrapper)"
      pattern: "overflow-x-auto"
---

<objective>
Fix horizontal scroll on the dataset attribute table, add expand/collapse to fill viewport, and polish table UX (striping, sorting, column visibility, density, truncation tooltips).

Purpose: Users with wide datasets cannot see all columns. The table is trapped in a constrained card with broken horizontal scroll due to double overflow containers. The expand mechanism lets users dedicate the full page to data exploration.

Output: Fully scrollable, expandable attribute table with production-quality UX.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@frontend/src/components/dataset/AttributeTable.tsx
@frontend/src/components/dataset/tabs/DataTab.tsx
@frontend/src/components/dataset/panels/DetailPanel.tsx
@frontend/src/pages/DatasetPage.tsx
@frontend/src/components/ui/table.tsx
@frontend/src/components/ui/card.tsx
@frontend/src/components/ui/tooltip.tsx
@frontend/src/components/ui/dropdown-menu.tsx
@frontend/src/components/layout/PageShell.tsx

<interfaces>
<!-- Key types and contracts the executor needs -->

From ui/table.tsx:
- Table component wraps `<table>` in `<div className="relative w-full overflow-x-auto">` — this is the ONLY scroll container needed
- Table has `w-full` on the `<table>` element — this MUST be changed to allow horizontal overflow
- TableRow has `hover:bg-muted/50` already (hover states exist)
- TableHead has `whitespace-nowrap` already

From AttributeTable.tsx:
- Props: `{ datasetId: string; canEdit?: boolean }`
- Uses `useReactTable` with `getCoreRowModel()` — needs `getSortedRowModel()` added
- Line 223: outer `<div className="rounded-md border overflow-auto">` — ROOT CAUSE of broken horizontal scroll (double overflow nesting)
- Column definitions built from `data.columns` array of `{ name, type }`

From DataTab.tsx:
- Props: `{ datasetId: string; canEdit: boolean }`
- Simple Card wrapper around AttributeTable — needs expand toolbar added

From DetailPanel.tsx:
- Renders `<DataTab>` inside `<TabsContent value="data">` for vector datasets (line 100-104)
- `showData = isVector && !isTable` (line 47)

From DatasetPage.tsx:
- Already has `isHeroExpanded` state (line 97) — pattern to follow for table expand
- Hero map section: lines 494-541 (`!isTable && ...`)
- DetailPanel rendered at line 566
- Already imports `Minimize2, Maximize2` from lucide-react
- PageShell wraps everything with `max-w-7xl mx-auto px-6 py-4 space-y-4`
</interfaces>
</context>

<tasks>

<task type="auto">
  <name>Task 1: Fix horizontal scroll and add table UX polish to AttributeTable</name>
  <files>frontend/src/components/dataset/AttributeTable.tsx</files>
  <action>
Fix the horizontal scroll root cause and add table polish features:

**Horizontal scroll fix:**
1. Remove the outer `<div className="rounded-md border overflow-auto">` wrapper at line 223. Replace with just `<div className="rounded-md border">` (no overflow — let the Table component's built-in `overflow-x-auto` wrapper handle scrolling).
2. Pass `className="w-max min-w-full"` to the `<Table>` component so the table grows beyond container width when columns are wide, triggering the horizontal scrollbar. `min-w-full` ensures it fills the container when columns are few.

**Row striping:**
3. On the `<TableRow>` in the body (line 265), add alternating background: `className={row.index % 2 === 1 ? 'bg-muted/30' : ''}`.

**Client-side sorting (current page only):**
4. Import `getSortedRowModel` and `type SortingState` from `@tanstack/react-table`.
5. Add `const [sorting, setSorting] = useState<SortingState>([])` state.
6. Add `getSortedRowModel: getSortedRowModel()`, `state: { sorting }`, `onSortingChange: setSorting` to the `useReactTable` config.
7. Make column headers clickable for sorting: wrap header text in a `<button>` with `onClick: header.column.getToggleSortingHandler()`. Show sort direction indicator: `{header.column.getIsSorted() === 'asc' ? ' ↑' : header.column.getIsSorted() === 'desc' ? ' ↓' : ''}`. Import `ArrowUpDown` from lucide-react for unsorted state indicator (small, muted).

**Column visibility:**
8. Import `type VisibilityState` from `@tanstack/react-table`.
9. Add `const [columnVisibility, setColumnVisibility] = useState<VisibilityState>({})` state.
10. Add `state: { sorting, columnVisibility }`, `onColumnVisibilityChange: setColumnVisibility` to the `useReactTable` config.
11. Add a toolbar div before the table border div with: a `DropdownMenu` button labeled "Columns" (import from `@/components/ui/dropdown-menu`). Inside, render `DropdownMenuCheckboxItem` for each column from `table.getAllColumns().filter(col => col.getCanHide())`. Each item: `checked={col.getIsVisible()}`, `onCheckedChange={(v) => col.toggleVisibility(!!v)}`.
- Import `Settings2` icon from lucide-react for the columns button.

**Cell truncation with tooltip:**
12. For non-editing cells with text content, wrap in a Tooltip that shows full value on hover. Import `Tooltip, TooltipTrigger, TooltipContent, TooltipProvider` from `@/components/ui/tooltip`. Wrap the cell content: `<TooltipProvider><Tooltip><TooltipTrigger asChild><span className="block truncate">{cellValue}</span></TooltipTrigger><TooltipContent side="bottom" className="max-w-sm break-all">{cellValue}</TooltipContent></Tooltip></TooltipProvider>`. Only add tooltip when `cellValue.length > 30` to avoid unnecessary tooltips on short values.

**Density toggle:**
13. Accept an optional `compact?: boolean` prop (default false). When compact, apply `py-1 text-xs` to TableCell instead of default `py-3`. The toggle button will live in DataTab's toolbar.

**Expose props for parent control:**
14. Update the `AttributeTableProps` interface to add: `compact?: boolean`. The toolbar (columns dropdown, sort indicators) lives inside AttributeTable itself.
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens/frontend && npx tsc --noEmit 2>&1 | head -30</automated>
  </verify>
  <done>
- Table scrolls horizontally when columns exceed container width (single overflow container)
- Rows have alternating stripe backgrounds
- Column headers are clickable to sort (client-side, current page)
- Column visibility dropdown lets users show/hide columns
- Long cell values show tooltip on hover
- Compact prop controls row density
  </done>
</task>

<task type="auto">
  <name>Task 2: Add expand/collapse mechanism and wire DataTab toolbar</name>
  <files>
    frontend/src/components/dataset/tabs/DataTab.tsx
    frontend/src/components/dataset/panels/DetailPanel.tsx
    frontend/src/pages/DatasetPage.tsx
  </files>
  <action>
**DataTab.tsx — Full rewrite with expand toolbar:**
1. Add props: `expanded?: boolean`, `onToggleExpand?: () => void`.
2. Replace simple Card wrapper with a more functional layout:
   - When NOT expanded: Keep the Card wrapper but add a toolbar in CardHeader with: the existing title, a density toggle button (two states: comfortable/compact using `AlignJustify`/`List` icons), and the expand button (`Maximize2` icon) that calls `onToggleExpand`.
   - When expanded: Remove Card wrapper entirely. Render a full-height flex column layout:
     - Top toolbar: `flex items-center justify-between px-4 py-2 border-b bg-muted/30` with title "Attribute Data", density toggle, and collapse button (`Minimize2` icon calling `onToggleExpand`).
     - Table container: `flex-1 overflow-y-auto min-h-0` wrapping `<AttributeTable>`.
     - The pagination footer inside AttributeTable will scroll with the table (acceptable for now).
3. Manage `compact` state internally with `useState(false)`. Pass to `<AttributeTable compact={compact}>`.

**DetailPanel.tsx — Pass expand props through:**
4. Add to `DetailPanelProps`: `isTableExpanded?: boolean`, `onToggleTableExpand?: () => void`.
5. Pass these through to the `<DataTab>` render at line 102: `<DataTab datasetId={datasetId} canEdit={canEdit} expanded={isTableExpanded} onToggleExpand={onToggleTableExpand} />`.

**DatasetPage.tsx — Manage expanded state and conditional rendering:**
6. Add state: `const [isDataTabExpanded, setIsDataTabExpanded] = useState(false)`.
7. Add toggle handler: `const toggleDataTabExpand = useCallback(() => setIsDataTabExpanded(prev => !prev), [])`.
8. When `isDataTabExpanded` is true AND the active tab is 'data':
   - Hide the hero map section: wrap the `{!isTable && (` hero map block (lines 494-541) with `{!isDataTabExpanded && !isTable && (`.
   - Hide the raster quick facts strip similarly.
   - The DetailPanel still renders (it contains the DataTab), but the expanded DataTab will fill the space.
   - Add to the DetailPanel props: `isTableExpanded={isDataTabExpanded}`, `onToggleTableExpand={toggleDataTabExpand}`.
9. When expanded, the DataTab should take up most of the viewport. In DataTab, when `expanded` is true, render the wrapper with `h-[calc(100vh-10rem)]` (accounting for PageShell padding + header + tabs bar). The table container inside gets `flex-1 overflow-y-auto`.
10. If the user switches away from the 'data' tab, auto-collapse: add `useEffect(() => { if (activeTab !== 'data') setIsDataTabExpanded(false); }, [activeTab])`.
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens/frontend && npx tsc --noEmit 2>&1 | head -30</automated>
  </verify>
  <done>
- Expand button visible on DataTab header; clicking it hides the map and expands the table to fill viewport
- Collapse button restores normal layout with map visible
- Density toggle switches between comfortable and compact row heights
- Switching tabs auto-collapses the expanded view
- TypeScript compiles without errors
  </done>
</task>

<task type="checkpoint:human-verify" gate="blocking">
  <name>Task 3: Verify full table view UX</name>
  <action>Human verifies the complete table UX implementation visually and interactively.</action>
  <verify>Human approval of all 11 verification steps below.</verify>
  <done>User confirms all table features work correctly.</done>
  <what-built>Full table view with horizontal scroll fix, expand/collapse, sorting, column visibility, row striping, density toggle, and truncation tooltips on the dataset details page.</what-built>
  <how-to-verify>
    1. Navigate to http://localhost:8080/datasets/98240e38-136c-419e-9777-c5fbaf70a55d#data (or any vector dataset with multiple columns)
    2. Verify horizontal scroll: table should scroll left/right when columns exceed container width
    3. Verify row striping: alternating row backgrounds visible
    4. Click a column header — rows should sort ascending, click again for descending, third click clears sort
    5. Click the "Columns" dropdown — toggle a column off, verify it disappears from the table
    6. Hover over a long cell value — tooltip should appear showing full text
    7. Click the expand button (Maximize icon) in the DataTab header — map should disappear, table fills viewport
    8. Verify the table scrolls vertically in expanded mode with pagination visible
    9. Click the density toggle — rows should switch between comfortable and compact spacing
    10. Click the collapse button (Minimize icon) — map reappears, table returns to normal size
    11. Switch to a different tab (e.g., Overview) while expanded — should auto-collapse
  </how-to-verify>
  <resume-signal>Type "approved" or describe issues</resume-signal>
</task>

</tasks>

<verification>
- `cd frontend && npx tsc --noEmit` — TypeScript compiles cleanly
- Visual verification via checkpoint task
- Table with many columns scrolls horizontally
- Expand/collapse toggles map visibility and table height
</verification>

<success_criteria>
- Horizontal scroll works for wide tables (primary fix)
- Expand/collapse mechanism hides map and fills viewport with table
- Table UX polish: striping, sorting, column visibility, density, truncation tooltips
- No TypeScript errors, no regression in existing table functionality
</success_criteria>

<output>
After completion, create `.planning/quick/260331-cuw-address-the-lack-of-ability-to-view-the-/260331-cuw-SUMMARY.md`
</output>
