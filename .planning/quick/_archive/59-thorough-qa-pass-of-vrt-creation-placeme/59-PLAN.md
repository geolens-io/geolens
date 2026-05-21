---
phase: 59-thorough-qa-pass-of-vrt-creation-placeme
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - frontend/src/pages/VrtNewPage.tsx
  - frontend/src/components/import/VrtCreatorForm.tsx
  - frontend/src/components/layout/Navbar.tsx
  - frontend/src/pages/DatasetPage.tsx
  - frontend/src/i18n/locales/en/import.json
  - frontend/src/i18n/locales/de/import.json
  - frontend/src/i18n/locales/es/import.json
  - frontend/src/i18n/locales/fr/import.json
autonomous: false
requirements: [QT-59]

must_haves:
  truths:
    - "VRT creation page (/vrt/new) is visually consistent with other full-page forms in the app"
    - "Create dropdown Virtual Raster item looks consistent with other dropdown items"
    - "Create VRT button on raster detail page aligns with other action buttons"
    - "VrtCreatorForm has proper spacing, alignment, and responsive behavior"
    - "No accessibility issues (missing labels, poor contrast, keyboard navigation)"
    - "Mobile viewport shows VRT entry point correctly"
  artifacts:
    - path: "frontend/src/pages/VrtNewPage.tsx"
      provides: "VRT creation page with consistent layout"
    - path: "frontend/src/components/import/VrtCreatorForm.tsx"
      provides: "VRT form with proper UI/UX patterns"
    - path: "frontend/src/components/layout/Navbar.tsx"
      provides: "Create dropdown with VRT item"
  key_links:
    - from: "frontend/src/components/layout/Navbar.tsx"
      to: "/vrt/new"
      via: "Link in Create dropdown"
      pattern: "to=.*vrt/new"
    - from: "frontend/src/pages/DatasetPage.tsx"
      to: "/vrt/new?source="
      via: "Link from raster detail"
      pattern: "vrt/new\\?source="
---

<objective>
Thorough QA pass of the VRT creation placement refactoring (quick task 58) using Playwright MCP browser automation. Navigate to all affected pages, take screenshots, identify visual inconsistencies and UI/UX issues, then fix anything found.

Purpose: Ensure the VRT creation flow relocation looks polished and consistent with the rest of the GeoLens app.
Output: Fixed UI issues, screenshot-verified pages.
</objective>

<execution_context>
@/Users/ishiland/.claude/get-shit-done/workflows/execute-plan.md
@/Users/ishiland/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/quick/58-re-evaluate-the-placement-of-the-virtual/58-SUMMARY.md
@frontend/src/pages/VrtNewPage.tsx
@frontend/src/components/import/VrtCreatorForm.tsx
@frontend/src/components/layout/Navbar.tsx
@frontend/src/pages/DatasetPage.tsx

Key files from quick task 58:
- VrtNewPage.tsx: New dedicated page at /vrt/new using PageShell + PageHeader + VrtCreatorForm
- VrtCreatorForm.tsx: Accepts optional initialSourceId prop, max-w-2xl, space-y-6
- Navbar.tsx: CreateMenu has Virtual Raster with Layers icon after separator, gated by can('upload')
- DatasetPage.tsx: "Create VRT" button on raster detail pages (isRaster && isEditor)
- Import page: VRT tab removed, only 3 tabs remain
</context>

<tasks>

<task type="auto">
  <name>Task 1: Visual QA with Playwright MCP — screenshot all affected pages and identify issues</name>
  <files>none (read-only inspection)</files>
  <action>
Use Playwright MCP browser automation to perform a thorough visual QA of all pages affected by the VRT creation placement refactoring. The dev server should be running at http://localhost:8080.

**Login first:**
1. Navigate to http://localhost:8080
2. Login with admin/admin credentials if not already logged in

**Screenshot and inspect each area:**

1. **Navbar Create dropdown (desktop):**
   - Navigate to http://localhost:8080
   - Click the "Create" button in the navbar
   - Screenshot the dropdown open state
   - Check: Virtual Raster item has Layers icon, separator above it, consistent font/spacing with other items
   - Check: Permission gating (only visible for upload-capable users)

2. **VRT creation page (/vrt/new):**
   - Navigate to http://localhost:8080/vrt/new
   - Screenshot the full page
   - Check: PageHeader title "Create Virtual Raster" is styled consistently with other page headers (e.g., /import)
   - Check: Form spacing, max-width, alignment matches app conventions
   - Check: Mode toggle (Mosaic/Band Stack) is clear and accessible
   - Check: Search input has proper placeholder, icon alignment
   - Check: Resolution strategy dropdown appears only in mosaic mode
   - Check: Title and Summary fields have proper labels and spacing
   - Check: Submit button styling consistent with other forms

3. **Import page (/import):**
   - Navigate to http://localhost:8080/import
   - Screenshot the page
   - Check: Only 3 tabs visible (Upload File, Register Table, Service URL)
   - Check: No orphaned VRT references

4. **Raster dataset detail page:**
   - Navigate to a raster dataset detail page (find one from the catalog at http://localhost:8080)
   - Screenshot the header/actions area
   - Check: "Create VRT" button placement, size, styling consistent with other action buttons
   - Check: Button uses Layers icon, outline variant, sm size

5. **VRT dataset detail page:**
   - Navigate to a VRT dataset detail page
   - Check: "Create VRT" button does NOT appear (only for raster_dataset, not vrt_dataset)

6. **Mobile viewport:**
   - Resize to mobile width (375px)
   - Open hamburger menu
   - Screenshot the mobile nav
   - Check: Virtual Raster appears in Create section with proper styling
   - Check: Separator between Map and Virtual Raster items

7. **Pre-selection flow:**
   - From a raster detail page, click "Create VRT" button
   - Screenshot /vrt/new?source={id} page
   - Check: Source is pre-selected and displayed in the selected sources list

**Document all issues found** with specific details: what's wrong, which file, what needs to change. Be specific about CSS classes, spacing values, and component props.
  </action>
  <verify>
    <automated>echo "Visual QA is manual via Playwright MCP — issues documented in task output"</automated>
  </verify>
  <done>All affected pages screenshotted and reviewed. Issues documented with specific fix instructions.</done>
</task>

<task type="auto">
  <name>Task 2: Fix all visual and UI/UX issues identified in QA</name>
  <files>
    frontend/src/pages/VrtNewPage.tsx,
    frontend/src/components/import/VrtCreatorForm.tsx,
    frontend/src/components/layout/Navbar.tsx,
    frontend/src/pages/DatasetPage.tsx,
    frontend/src/i18n/locales/en/import.json,
    frontend/src/i18n/locales/de/import.json,
    frontend/src/i18n/locales/es/import.json,
    frontend/src/i18n/locales/fr/import.json
  </files>
  <action>
Fix all issues identified in Task 1. Common areas to check and fix:

**Known patterns to verify against (from existing app pages):**
- PageShell provides consistent max-width and padding — VrtNewPage should use it the same way as ImportPage
- PageHeader provides consistent title styling — verify same usage pattern
- Form fields in the app use Label + Input/Select with space-y-1.5 between label and input, space-y-6 between field groups
- Buttons in action bars use variant="outline" size="sm" with icon + text pattern
- Dropdown items use icon (h-4 w-4) + text pattern consistently
- Mobile nav items use the mobileNavLinkClass pattern

**Specific things to fix if found:**
1. VrtCreatorForm textarea uses raw HTML classes instead of the Textarea component from ui/textarea — replace with proper component if it exists
2. Ensure consistent Label htmlFor attributes on all form fields
3. Verify the search section has a Label like other form sections (currently it has no Label, just the input)
4. Check if the submit button should be full-width or left-aligned to match other forms
5. Verify i18n keys are consistent across all 4 locale files (en, de, es, fr) — the non-English files need the new keys added in task 58

**After fixes:**
- Run TypeScript check: `cd frontend && npx tsc --noEmit`
- Run existing VrtCreatorForm tests: `cd frontend && npx vitest run --reporter=verbose src/components/import/__tests__/VrtCreatorForm.test.tsx`
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens/frontend && npx tsc --noEmit 2>&1 | tail -5 && npx vitest run --reporter=verbose src/components/import/__tests__/VrtCreatorForm.test.tsx 2>&1 | tail -20</automated>
  </verify>
  <done>
    - All visual inconsistencies from QA are fixed
    - VrtCreatorForm uses proper UI components (Textarea if available)
    - Form accessibility: all inputs have associated labels
    - i18n keys are consistent across all locale files
    - TypeScript compiles without errors
    - Existing tests pass
  </done>
</task>

<task type="checkpoint:human-verify" gate="blocking">
  <name>Task 3: Visual verification of QA fixes</name>
  <files>none</files>
  <action>Human verifies the visual QA fixes are correct by checking all affected pages for consistency with app design.</action>
  <what-built>
    Fixed all visual and UI/UX issues found during Playwright QA of the VRT creation placement refactoring. This includes layout consistency, spacing, accessibility, and i18n completeness.
  </what-built>
  <how-to-verify>
    1. Visit http://localhost:8080/vrt/new — verify the page looks polished and consistent with the rest of the app
    2. Click the Create dropdown in the navbar — verify Virtual Raster item styling is consistent
    3. Navigate to a raster dataset detail page — verify Create VRT button looks right alongside other actions
    4. Open mobile nav (resize to narrow viewport) — verify Virtual Raster entry looks correct
    5. Visit http://localhost:8080/import — confirm only 3 tabs, no VRT artifacts
  </how-to-verify>
  <verify>Human visual inspection of all affected pages</verify>
  <done>User confirms all pages look polished and consistent</done>
  <resume-signal>Type "approved" or describe issues</resume-signal>
</task>

</tasks>

<verification>
- `cd frontend && npx tsc --noEmit` passes
- `cd frontend && npx vitest run src/components/import/__tests__/VrtCreatorForm.test.tsx` passes
- All affected pages visually consistent with app design system
- No accessibility issues (labels, contrast, keyboard nav)
- i18n keys present in all 4 locale files
</verification>

<success_criteria>
- VRT creation pages and entry points are visually polished and consistent with the GeoLens app
- No spacing, alignment, or styling inconsistencies
- Form accessibility meets baseline standards (labels, aria attributes)
- All locale files have matching keys
- Human approves visual state
</success_criteria>

<output>
After completion, create `.planning/quick/59-thorough-qa-pass-of-vrt-creation-placeme/59-SUMMARY.md`
</output>
