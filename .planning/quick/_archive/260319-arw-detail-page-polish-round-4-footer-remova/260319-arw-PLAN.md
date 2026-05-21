---
phase: 260319-arw
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - frontend/src/components/layout/AppLayout.tsx
  - frontend/src/components/layout/AppLayout.test.tsx
  - frontend/src/components/layout/PageShell.tsx
  - frontend/src/pages/DatasetPage.tsx
  - frontend/src/components/dataset/AiAssistButton.tsx
  - frontend/src/components/dataset/tabs/OverviewTab.tsx
autonomous: true
requirements: [POLISH-R4]
must_haves:
  truths:
    - "Detail pages have no 'Powered by GeoLens' footer"
    - "Visibility badge appears in header stats line second row"
    - "AI Assist buttons use muted ghost styling, not purple"
    - "Vertical spacing between sections is tighter"
  artifacts:
    - path: "frontend/src/components/layout/AppLayout.tsx"
      provides: "Conditionally hidden footer on dataset detail pages"
    - path: "frontend/src/pages/DatasetPage.tsx"
      provides: "Visibility badge in stats line + tighter PageShell spacing"
    - path: "frontend/src/components/dataset/AiAssistButton.tsx"
      provides: "Muted ghost AI button styling"
  key_links:
    - from: "AppLayout.tsx"
      to: "datasets/:id route"
      via: "useMatch to hide footer"
      pattern: "useMatch.*datasets"
---

<objective>
Detail page polish round 4: hide footer on detail pages, add visibility badge to header stats line, tone down AI Assist styling, tighten vertical spacing.

Purpose: Reduce visual noise and wasted space on dataset detail pages while surfacing important visibility info.
Output: Cleaner, denser detail page layout with visibility in header.
</objective>

<execution_context>
@/Users/ishiland/.claude/get-shit-done/workflows/execute-plan.md
@/Users/ishiland/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@frontend/src/components/layout/AppLayout.tsx
@frontend/src/pages/DatasetPage.tsx
@frontend/src/components/dataset/AiAssistButton.tsx
@frontend/src/components/dataset/tabs/OverviewTab.tsx
@frontend/src/components/layout/PageShell.tsx
</context>

<tasks>

<task type="auto">
  <name>Task 1: Footer hide, visibility badge, spacing, AI Assist tone-down</name>
  <files>
    frontend/src/components/layout/AppLayout.tsx,
    frontend/src/components/layout/__tests__/AppLayout.test.tsx,
    frontend/src/components/layout/PageShell.tsx,
    frontend/src/pages/DatasetPage.tsx,
    frontend/src/components/dataset/AiAssistButton.tsx,
    frontend/src/components/dataset/tabs/OverviewTab.tsx
  </files>
  <action>
**1. Hide footer on dataset detail pages** (`AppLayout.tsx`):
- Add `const isDatasetDetail = useMatch('/datasets/:id');` (import useMatch already present)
- Change footer condition from `{!isMapBuilder && (` to `{!isMapBuilder && !isDatasetDetail && (`
- Update the test in `__tests__/AppLayout.test.tsx` to account for this — the existing test checks footer renders, so either adjust it to test a non-dataset route or skip the dataset-specific hiding in test context.

**2. Add visibility badge to header stats line** (`DatasetPage.tsx`):
- Import `Eye, EyeOff, ShieldAlert` from lucide-react (Eye for public, ShieldAlert for restricted, EyeOff for private)
- Import `Badge` from `@/components/ui/badge`
- Import `visibilityColors` from `@/lib/status-colors`
- In the second `<div>` of `statsLine` (line 482-486, the "Published . Updated X ago" line), add a visibility badge between the record status label and the separator:
  ```tsx
  <span>{getRecordStatusLabel(t, dataset.record_status)}</span>
  <Sep />
  <Badge variant="outline" className={cn('text-xs capitalize', visibilityColors[dataset.visibility] ?? '')}>
    {dataset.visibility === 'public' ? <Eye className="mr-1 h-3 w-3" /> : dataset.visibility === 'restricted' ? <ShieldAlert className="mr-1 h-3 w-3" /> : <EyeOff className="mr-1 h-3 w-3" />}
    {dataset.visibility}
  </Badge>
  <Sep />
  <span>Updated {formatRelativeDate(dataset.updated_at)}</span>
  ```
- Import `cn` from `@/lib/utils` if not already imported.

**3. Tone down AI Assist button** (`AiAssistButton.tsx`):
- Change the AiAssistButton className from `"text-violet-600 dark:text-violet-400 hover:text-violet-700 dark:hover:text-violet-300"` to `"text-muted-foreground hover:text-foreground"`
- In `AiDraftPreview`, change `border-l-4 border-violet-400 bg-violet-50 dark:bg-violet-950/20` to `border-l-4 border-muted bg-muted/30`
- In `AiKeywordSuggestions`, same border/bg change from violet to muted

**4. Tighten vertical spacing**:
- In `PageShell.tsx`: Change `space-y-6` to `space-y-4` in the className. This affects the main content gaps between all sections in detail pages (map, tabs, cards).
- In `OverviewTab.tsx`: The Card components use default CardHeader/CardContent padding. No change needed there as p-6 is the shadcn default and individual cards look fine — the gap *between* cards (controlled by PageShell) is what was too large.
- In `DatasetPage.tsx`: The PageShell already wraps everything. The `py-6` can be reduced to `py-4` as well — change in PageShell from `px-6 py-6` to `px-6 py-4`.

**5. Collapse empty containers**: The OverviewTab health block already conditionally renders (lines 133-173). The collections card already has `{dataset.collections && dataset.collections.length > 0 && (` guard. RelatedDatasets and UsedInMaps components should already handle empty state internally. No changes needed here — the existing guards are sufficient.
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens/frontend && npx tsc --noEmit 2>&1 | tail -5</automated>
  </verify>
  <done>
    - Footer hidden on dataset detail pages (still visible on search, admin, etc.)
    - Visibility badge with icon shows in header stats second line
    - AI Assist buttons use muted/ghost styling instead of violet
    - PageShell spacing reduced from space-y-6 to space-y-4, py-6 to py-4
    - TypeScript compiles without errors
  </done>
</task>

</tasks>

<verification>
- `npx tsc --noEmit` passes
- Visual: dataset detail page has no footer, shows visibility badge in stats line, AI buttons are subtle
- Visual: search page still shows footer
</verification>

<success_criteria>
- Footer absent on /datasets/:id pages, present elsewhere
- Visibility badge visible inline in header stats second row with appropriate icon
- AI Assist buttons visually recede (muted foreground, no purple)
- Tighter spacing between all major sections on detail page
</success_criteria>

<output>
After completion, create `.planning/quick/260319-arw-detail-page-polish-round-4-footer-remova/260319-arw-SUMMARY.md`
</output>
