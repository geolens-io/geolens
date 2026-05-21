---
phase: quick-260325-egu
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - frontend/src/components/dataset/AttributeTable.tsx
  - frontend/src/pages/DatasetPage.tsx
  - frontend/src/lib/constants.ts
  - frontend/src/i18n/locales/en/dataset.json
  - frontend/src/i18n/locales/fr/dataset.json
  - frontend/src/i18n/locales/es/dataset.json
  - frontend/src/i18n/locales/de/dataset.json
autonomous: true
requirements: [FIX-PAGINATION, EXPANDABLE-HERO, PAGE-SIZE-SELECTOR]

must_haves:
  truths:
    - "Small tables (< 50 rows) display correct row count, not 'Showing 0-N of ~0 rows'"
    - "Hero data grid for table datasets has a collapse/expand toggle between compact and tall views"
    - "User can select page size of 25, 50, or 100 from a dropdown in the pagination bar"
  artifacts:
    - path: "frontend/src/components/dataset/AttributeTable.tsx"
      provides: "Fixed pagination display, page size selector dropdown"
    - path: "frontend/src/pages/DatasetPage.tsx"
      provides: "Expandable hero data grid with toggle"
    - path: "frontend/src/lib/constants.ts"
      provides: "PAGE_SIZE_OPTIONS array"
  key_links:
    - from: "frontend/src/components/dataset/AttributeTable.tsx"
      to: "frontend/src/lib/constants.ts"
      via: "PAGE_SIZE_OPTIONS import"
      pattern: "PAGE_SIZE_OPTIONS"
    - from: "frontend/src/pages/DatasetPage.tsx"
      to: "frontend/src/components/dataset/tabs/DataTab.tsx"
      via: "Hero grid wrapper with expand toggle"
      pattern: "isHeroExpanded"
---

<objective>
Fix three non-spatial data table UX issues: pagination display bug showing "0 of ~0" for small tables, add expandable hero data grid height toggle, and add user-configurable page size selector.

Purpose: Small non-spatial tables show incorrect row counts and the grid has a fixed height with no page size control, degrading the data browsing experience.
Output: Corrected pagination, expandable hero grid, page size dropdown.
</objective>

<execution_context>
@~/.claude/get-shit-done/workflows/execute-plan.md
@~/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@frontend/src/components/dataset/AttributeTable.tsx
@frontend/src/pages/DatasetPage.tsx
@frontend/src/lib/constants.ts
@frontend/src/components/dataset/tabs/DataTab.tsx
@frontend/src/i18n/locales/en/dataset.json
</context>

<tasks>

<task type="auto">
  <name>Task 1: Fix pagination display bug and add page size selector</name>
  <files>
    frontend/src/components/dataset/AttributeTable.tsx,
    frontend/src/lib/constants.ts,
    frontend/src/i18n/locales/en/dataset.json,
    frontend/src/i18n/locales/fr/dataset.json,
    frontend/src/i18n/locales/es/dataset.json,
    frontend/src/i18n/locales/de/dataset.json
  </files>
  <action>
**constants.ts**: Add `export const PAGE_SIZE_OPTIONS = [25, 50, 100] as const;` alongside the existing `DEFAULT_ROWS_PAGE_SIZE`.

**AttributeTable.tsx**:

1. **Fix pagination bug** (lines 197-199): When `approximateTotal === 0` but `data.rows.length > 0`, the display shows "Showing 0-N of ~0 rows". Fix by computing an `effectiveTotal`:
   ```
   const rowCount = data?.rows?.length ?? 0;
   const effectiveTotal = approximateTotal > 0 ? approximateTotal : rowCount;
   const isExact = approximateTotal === 0 && rowCount > 0;
   const rangeStart = rowCount > 0 ? (cursorHistory.length - 1) * pageSize + 1 : 0;
   const rangeEnd = rangeStart > 0 ? rangeStart + rowCount - 1 : 0;
   ```
   Update the "showing" display: when `isExact` is true, show exact count (no tilde). Add a new i18n key `attributes.showingExact` = "Showing {{start}}-{{end}} of {{total}} rows" (no ~ prefix on total). Use `isExact ? t('attributes.showingExact', ...) : t('attributes.showing', ...)`.

2. **Also fix the empty-state guard** (line 209): Change `approximateTotal === 0` to `effectiveTotal === 0` so small tables with rows are not incorrectly shown as empty.

3. **Add page size selector**: Import `Select, SelectContent, SelectItem, SelectTrigger, SelectValue` from `@/components/ui/select` and `PAGE_SIZE_OPTIONS` from constants. Replace the hardcoded `const pageSize = DEFAULT_ROWS_PAGE_SIZE` with `const [pageSize, setPageSize] = useState(DEFAULT_ROWS_PAGE_SIZE)`. When page size changes, reset cursor and cursorHistory to initial state. Add a Select dropdown in the pagination footer bar (left side, next to the showing text) with options 25/50/100. Add i18n key `attributes.rowsPerPage` = "Rows per page".

**i18n files**: Add two new keys to the `attributes` object in all 4 locale files:
- en: `"showingExact": "Showing {{start}}-{{end}} of {{total}} rows"`, `"rowsPerPage": "Rows per page"`
- fr: `"showingExact": "Affichage {{start}}-{{end}} sur {{total}} lignes"`, `"rowsPerPage": "Lignes par page"`
- es: `"showingExact": "Mostrando {{start}}-{{end}} de {{total}} filas"`, `"rowsPerPage": "Filas por pagina"`
- de: `"showingExact": "{{start}}-{{end}} von {{total}} Zeilen"`, `"rowsPerPage": "Zeilen pro Seite"`
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens && npx tsc --noEmit --project frontend/tsconfig.json 2>&1 | head -30</automated>
  </verify>
  <done>
    - Small tables with approximate_total=0 but rows present show "Showing 1-3 of 3 rows" (no tilde, exact count)
    - Tables with accurate approximate_total still show "Showing 1-50 of ~1234 rows" (with tilde)
    - Page size dropdown with 25/50/100 options appears in pagination bar
    - Changing page size resets to first page
    - All 4 locale files have the two new i18n keys
  </done>
</task>

<task type="auto">
  <name>Task 2: Add expandable hero data grid toggle for table datasets</name>
  <files>frontend/src/pages/DatasetPage.tsx</files>
  <action>
In DatasetPage.tsx, add an expand/collapse toggle for the hero data grid shown for table datasets (line 612-619).

1. Add state: `const [isHeroExpanded, setIsHeroExpanded] = useState(true)` (default expanded since this is the primary view for non-spatial data).

2. Import `ChevronsUpDown` (or `Minimize2` and `Maximize2`) from lucide-react for the toggle icon.

3. Replace the hero grid section (lines 612-619) with:
   ```tsx
   {isTable && (
     <div className="rounded-lg border shadow-sm overflow-hidden">
       <div className="flex items-center justify-between px-3 py-1.5 bg-muted/30 border-b">
         <span className="text-xs text-muted-foreground font-medium">
           {t('page.dataPreview', { defaultValue: 'Data Preview' })}
         </span>
         <Button
           variant="ghost"
           size="sm"
           className="h-6 w-6 p-0"
           onClick={() => setIsHeroExpanded(prev => !prev)}
           aria-label={isHeroExpanded ? 'Collapse data grid' : 'Expand data grid'}
         >
           {isHeroExpanded ? <Minimize2 className="h-3.5 w-3.5" /> : <Maximize2 className="h-3.5 w-3.5" />}
         </Button>
       </div>
       <div className={isHeroExpanded ? 'h-[60vh]' : 'h-64'}>
         <DataTab datasetId={id!} canEdit={isEditor} />
       </div>
     </div>
   )}
   ```

4. Add `Minimize2, Maximize2` to the lucide-react import at top of file.
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens && npx tsc --noEmit --project frontend/tsconfig.json 2>&1 | head -30</automated>
  </verify>
  <done>
    - Hero data grid for table datasets has a small toggle button in a header bar
    - Clicking toggle switches between h-64 (compact) and h-[60vh] (expanded)
    - Default state is expanded (h-[60vh]) since this is the primary content for non-spatial data
    - Toggle has accessible aria-label
  </done>
</task>

</tasks>

<verification>
1. TypeScript compilation passes with no errors
2. Navigate to a non-spatial table dataset with few rows (< 50) -- pagination shows correct count without tilde
3. Page size dropdown allows switching between 25/50/100
4. Hero data grid expand/collapse toggle works
</verification>

<success_criteria>
- No "Showing 0-N of ~0 rows" for small tables -- shows exact count fallback
- Page size selector visible and functional with 25/50/100 options
- Hero data grid toggles between compact (h-64) and expanded (h-[60vh])
- All changes compile without TypeScript errors
</success_criteria>

<output>
After completion, create `.planning/quick/260325-egu-fix-non-spatial-data-table-pagination-bu/260325-egu-SUMMARY.md`
</output>
