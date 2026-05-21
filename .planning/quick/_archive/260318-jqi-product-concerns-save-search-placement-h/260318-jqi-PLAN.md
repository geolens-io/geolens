---
phase: 260318-jqi
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - frontend/src/components/search/SavedSearches.tsx
  - frontend/src/components/search/FilterPanel.tsx
  - frontend/src/pages/SearchPage.tsx
autonomous: true
requirements: [SAVE-SEARCH-DEMOTE, HERO-COMPRESS, RESULT-COUNT-SPATIAL]

must_haves:
  truths:
    - "Save Search button appears as ghost variant, positioned after sort/view controls"
    - "Active search mode shows a compact toolbar-like bar, not a hero"
    - "Result count is visible near top of results when spatial filter is active, showing contextual text"
  artifacts:
    - path: "frontend/src/components/search/SavedSearches.tsx"
      provides: "Ghost variant Save Search button"
      contains: 'variant="ghost"'
    - path: "frontend/src/components/search/FilterPanel.tsx"
      provides: "Save Search moved after sort, result count with spatial context"
    - path: "frontend/src/pages/SearchPage.tsx"
      provides: "Compact sticky toolbar in active mode with filters inline"
  key_links:
    - from: "frontend/src/pages/SearchPage.tsx"
      to: "frontend/src/components/search/FilterPanel.tsx"
      via: "totalResults prop and isLanding state"
      pattern: "totalResults.*numberMatched"
    - from: "frontend/src/components/search/FilterPanel.tsx"
      to: "frontend/src/stores/search-store.ts"
      via: "bbox and geometry for spatial-active detection"
      pattern: "useSearchStore.*bbox"
---

<objective>
Address three product concerns: demote Save Search button, compress hero into toolbar in active mode, and show result count with spatial context.

Purpose: Improve the search working surface so filtering actions have clear hierarchy and users get feedback when spatial filters affect results.
Output: Updated SearchPage, FilterPanel, and SavedSearches components.
</objective>

<execution_context>
@/Users/ishiland/.claude/get-shit-done/workflows/execute-plan.md
@/Users/ishiland/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@frontend/src/pages/SearchPage.tsx
@frontend/src/components/search/FilterPanel.tsx
@frontend/src/components/search/SavedSearches.tsx
@frontend/src/stores/search-store.ts
@frontend/src/hooks/use-search.ts
</context>

<tasks>

<task type="auto">
  <name>Task 1: Demote Save Search and reorder in FilterPanel</name>
  <files>frontend/src/components/search/SavedSearches.tsx, frontend/src/components/search/FilterPanel.tsx</files>
  <action>
1. In SavedSearches.tsx, change the SaveSearchButton's variant from "outline" to "ghost" (line 48). This makes it visually secondary to the filter buttons which use "outline".

2. In FilterPanel.tsx desktop primary filter row (line 342-484):
   - Remove the SaveSearchButton from its current position (line 477: `{token && <SaveSearchButton />}`)
   - Move it AFTER the sort Select (after line 461), but BEFORE the Clear filters button. Place it in the same flex group or adjacent. It should read: sort select, then save search (ghost), then clear filters, then result count on ml-auto.
   - The mobile layout (line 263) can keep SaveSearchButton where it is since mobile has different layout constraints.

3. In FilterPanel.tsx, enhance the desktop result count display (currently line 479-483, `ml-auto text-sm text-muted-foreground`):
   - Read `bbox` and `geometry` from the search store (already subscribed at lines 69, no extra needed for bbox; geometry is not currently subscribed).
   - Add `const geometry = useSearchStore((s) => s.geometry);` subscription.
   - When bbox OR geometry is truthy AND totalResults is defined, show contextual text: "Showing {count} in selected area" instead of just the count. Use the existing i18n pattern with a new key `filters.spatialResultCount` with defaultValue `Showing {{count}} in selected area`.
   - When no spatial filter is active, keep the existing `filters.datasetCount` text.
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens/frontend && npx vitest run src/components/search/__tests__/FilterPanel.test.tsx --reporter=verbose 2>&1 | tail -20</automated>
  </verify>
  <done>Save Search is ghost variant, positioned after sort control. Result count shows spatial context when bbox/geometry active.</done>
</task>

<task type="auto">
  <name>Task 2: Compress hero into compact toolbar in active search mode</name>
  <files>frontend/src/pages/SearchPage.tsx, frontend/src/components/search/FilterPanel.tsx</files>
  <action>
In SearchPage.tsx, the current active-mode layout still shows FilterPanel as a separate section below the sticky search bar. The goal is to make the active state feel like a compact toolbar, not a hero with separate filter rows.

Current structure when `!isLanding`:
- Sticky bar with SearchBar (lines 61-70)
- PageShell with SavedSearches + FilterPanel as separate blocks

Changes to SearchPage.tsx:
1. When `!isLanding` (active search mode), integrate the FilterPanel into the sticky bar instead of keeping it separate in the page body. Move FilterPanel inside the sticky bar div (after SearchBar), so filters appear directly below the search input in the same sticky container.

2. Update the sticky bar layout (lines 61-70):
   - When `showStickyBar` is true, the sticky bar should contain:
     a. SearchBar (already there, max-w-2xl centered)
     b. FilterPanel (add below SearchBar, full width within max-w-7xl, only when `!isLanding`)
   - Add `totalResults={data?.numberMatched}` prop to this FilterPanel instance.

3. In the page body (inside PageShell), conditionally render FilterPanel:
   - When `isLanding`: show FilterPanel in page body (current behavior)
   - When `!isLanding`: do NOT show FilterPanel in page body (it's in the sticky bar now)
   - This avoids duplicate FilterPanels.

4. Tighten the sticky bar padding: when `!isLanding`, use `py-2` instead of `py-2.5` and add a subtle `shadow-sm` to reinforce that it's a toolbar.

5. Keep the hero (title + subtitle + SearchBar) only for `isLanding` — this is already correct.

6. When `!isLanding`, also hide `<SavedSearches />` to reduce visual noise in working mode. The saved searches row is useful on landing but clutters the active search surface.
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens/frontend && npx tsc --noEmit 2>&1 | tail -10</automated>
  </verify>
  <done>Active search mode shows a compact sticky toolbar containing search bar and filters inline. Landing mode unchanged. No duplicate FilterPanels.</done>
</task>

</tasks>

<verification>
1. TypeScript compiles without errors
2. FilterPanel tests pass
3. Visual check: landing page shows hero with large search bar; typing a query collapses into compact sticky toolbar with filters inline; Save Search appears as ghost button after sort; spatial filter shows contextual result count
</verification>

<success_criteria>
- Save Search button uses ghost variant and appears after sort control, before clear filters
- Active search mode renders FilterPanel inside the sticky toolbar bar
- Landing mode unchanged (hero with title, subtitle, search bar)
- Result count shows "Showing N in selected area" when spatial filter is active
- No TypeScript errors, existing tests pass
</success_criteria>

<output>
After completion, create `.planning/quick/260318-jqi-product-concerns-save-search-placement-h/260318-jqi-SUMMARY.md`
</output>
