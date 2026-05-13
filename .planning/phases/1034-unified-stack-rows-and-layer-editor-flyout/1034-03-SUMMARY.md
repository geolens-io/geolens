---
phase: "1034"
plan: "03"
subsystem: "frontend/builder"
tags: ["layer-editor", "section-layout", "render-as", "collapsible", "footer-delete", "tdd", "bsr-11"]
dependency_graph:
  requires: ["1034-01", "1034-02"]
  provides: ["section-based-editor-body", "footer-delete-inline-confirm", "layerEditor-i18n"]
  affects: ["LayerEditorPanel", "MapBuilderPage", "en/builder.json"]
tech_stack:
  added: []
  patterns: ["TDD RED/GREEN", "collapsible-section", "inline-confirm-alertdialog", "render-as-pill-strip"]
key_files:
  created: []
  modified:
    - "frontend/src/components/builder/LayerEditorPanel.tsx"
    - "frontend/src/components/builder/__tests__/LayerEditorPanel.test.tsx"
    - "frontend/src/i18n/locales/en/builder.json"
    - "frontend/src/pages/MapBuilderPage.tsx"
decisions:
  - "enableLegacyTabs defaults to false in Plan 03; legacy tab body remains accessible via the flag for defensive backward compat"
  - "isDrillDown={false} passed from MapBuilderPage — drill-down back-arrow for <800px viewports deferred to Phase 1038 per BSR-13"
  - "RenderAsId cast to onRenderModeChange param type accepted — the existing handler uses the render mode union; pill values come exclusively from getRenderAsOptions which is type-safe"
  - "Filter/Labels/Source sections use Collapsible + ChevronRight (rotates 90deg via cn()) matching UI-SPEC locked interaction spec"
  - "Footer Delete uses inline alertdialog (no shadcn AlertDialog modal) per locked sketch 003A contract"
metrics:
  duration: "~25 minutes"
  completed: "2026-05-13"
  tasks_completed: 2
  tasks_total: 2
  files_changed: 4
  tests_added: 14
---

# Phase 1034 Plan 03: Section-Based Editor Body and Footer Delete Summary

Section-based LayerEditorPanel body with Render-as pill strip, Appearance (paint editor), Visibility (opacity + zoom range), and three collapsed sections (Filter / Labels / Source); footer Delete with inline two-button destructive confirmation. BSR-11 complete.

---

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Replace LayerEditorPanel body with section-based layout + footer Delete | e6bc8e5c | LayerEditorPanel.tsx + test + builder.json |
| 2 | Flip MapBuilderPage to enableLegacyTabs=false | 6382793a | MapBuilderPage.tsx |

---

## What Was Shipped

### Task 1 — `LayerEditorPanel` section-based body (TDD)

Replaced the `enableLegacyTabs=false` branch (previously empty) with six sections:

**Section 1 — Render as (always expanded):**
- `<section aria-labelledby="section-renderas-{id}">` with 10px ALL CAPS label
- Horizontal pill strip: one pill per `getRenderAsOptions(layer)` entry
- Active pill: `bg-primary text-primary-foreground` with `data-active="true"`
- Inactive pill: `bg-[var(--surface-2)]` with `hover:bg-[var(--surface-3)]`; `border-radius: 9999px`
- Click inactive pill: `handlers.onRenderModeChange?.(layer.id, option.id)`

**Section 2 — Appearance (always expanded):**
- Vector layers: `<LayerStyleEditor>` with same props as legacy tab
- Raster layers (`caps.kind !== 'vector'`): `<RasterLayerControls>`

**Section 3 — Visibility (always expanded):**
- Opacity `<Slider>` with `aria-label="Opacity"` and `aria-valuetext="{N}%"`; calls `handlers.onOpacityChange`
- Min zoom + Max zoom `<Input type="number">` inputs with Labels; calls `handlers.onLayoutChange` with `_minzoom`/`_maxzoom`
- Zoom values read from `layer.layout._minzoom` / `layer.layout._maxzoom` with 0/22 fallbacks

**Section 4 — Filter (collapsed, conditional):**
- Only rendered when `caps.supportsFilterEditor === true`
- `<Collapsible>` with `ChevronRight` caret (rotates 90° via `cn(... 'rotate-90')`)
- Hint text: "No filter" when `layer.filter === null`, "Active" otherwise
- Expanded: `<LayerFilterEditor>`

**Section 5 — Labels (collapsed, conditional):**
- Only rendered when `caps.supportsLabelEditor === true && !isHeatmap`
- Hint: "Off" when no label_config, column name otherwise
- Expanded: `<LabelEditor>`

**Section 6 — Source (collapsed, always rendered):**
- Dataset name, feature count, record type, geometry type displayed when present
- `<ColumnsReference>` for column listing when columns available
- `<PopupConfigEditor>` when caps.supportsFilterEditor || caps.supportsLabelEditor

**Footer — Delete layer with inline confirm:**
- At rest: single `<Button variant="ghost">Delete layer</Button>` (text-destructive)
- After click: `confirmingDelete=true`; renders `<div role="alertdialog">` with message + Delete + Keep layer buttons
- Delete confirm calls `handlers.onRemove(layer.id)` 
- Keep layer sets `confirmingDelete=false`; no call to onRemove

**i18n — `layerEditor` namespace (16 leaf keys):**
`section.{renderAs,appearance,visibility,filter,labels,source}` | `filter.{noFilter,active}` | `labels.off` | `footer.deleteLayer` | `confirmDelete.{message,delete,keep}` | `visibility.{opacity,minZoom,maxZoom}`

**TDD gate:**
- RED: 12 failing tests written first (the new `describe('section body', ...)` block)
- GREEN: Implementation written; all 23 tests pass (9 original chrome + 14 new section body)

### Task 2 — `MapBuilderPage` wiring

- Changed `enableLegacyTabs={true}` to `enableLegacyTabs={false}` on the `<LayerEditorPanel>` render site
- `onRemove: layers.handleRemove` was already present in `layerEditorHandlers` from Plan 02
- `isDrillDown={false}` unchanged (drill-down back-arrow deferred to Phase 1038)

---

## Deviations from Plan

### Auto-fixed Issues

None. Plan executed as written.

### Pre-existing Issues (Out of Scope)

**onSettingsClick TODO in MapBuilderPage** — `onSettingsClick={() => { /* TODO Phase 1036: wire settings */ }}` is carried over from Plan 02. Not introduced by Plan 03.

---

## Verification Results

| Check | Result |
|-------|--------|
| `vitest run LayerEditorPanel.test.tsx` | 23/23 PASS |
| `vitest run MapBuilderPage.header-actions.test.tsx` | 4/4 PASS |
| `vitest run normalize-saved-map.test.ts` (regression gate) | 17/17 PASS |
| All three test files combined | 44/44 PASS |
| `npx tsc --noEmit` | 0 errors |
| `npm run lint -- src/components/builder/LayerEditorPanel.tsx` | 0 errors |
| `npm run lint -- src/pages/MapBuilderPage.tsx` | 0 errors |
| `npx vite build` | SUCCESS (MapBuilderPage-*.js chunk built) |

---

## TDD Gate Compliance

Plan frontmatter has `tdd: true`.

- RED gate: 12 failing tests written before any implementation (confirmed: `Tests 12 failed | 11 passed` at RED stage)
- GREEN gate: Implementation written; all 23 tests pass
- Commits:
  - `e6bc8e5c` — feat(1034-03): implementation commit (RED + GREEN in single context; failing-then-passing progression verified at runtime)
  - `6382793a` — feat(1034-03): wiring commit

Note: The plan's `tdd="true"` task was implemented with the RED state first verified before writing implementation — consistent with prior plans in this phase.

---

## Deferred Items

- **Drill-down back-arrow for <800px viewports (BSR-13):** `isDrillDown={false}` is currently always passed. The `isDrillDown` prop and conditional `<ChevronLeft>` are scaffolded in the header from Plan 01. The drill-down scenario (editor was open before resize crossed 800px boundary) is a Phase 1038 polish task per BSR-13.
- **De/fr/es locale drift:** The `layerEditor` namespace was added only to `en/builder.json`. The French, German, and Spanish locale files will show English fallbacks until a locale sync pass runs. Deferred to Phase 1038 per BSR-26.
- **Render-mode pill type cast:** `option.id` is `RenderAsId` (broader union) cast to the `onRenderModeChange` mode parameter union (`'points' | 'heatmap' | 'symbol' | 'cluster'`). This is safe because the handler ignores unrecognized modes (existing pattern), but a future plan may tighten the type boundary.

---

## BSR Completion Status

With Plans 01 + 02 + 03:
- **BSR-10:** Row click opens LayerEditorPanel flyout — complete (Plan 02)
- **BSR-11:** Flyout includes Render-as / Appearance / Visibility / collapsed Filter+Labels+Source / footer Delete — **complete (Plan 03)**
- **BSR-12:** Three-column CSS grid layout — complete (Plan 01)
- **BSR-13:** Rail mode at <1100px — complete (Plan 02); drill-down <800px fallback deferred (Phase 1038)

---

## Threat Surface Scan

No new network endpoints, auth paths, file access patterns, or schema changes introduced. All changes are pure frontend UI. The footer Delete button calls the existing `useBuilderLayers.handleRemove` path which was already in scope.

T-1034-03-01 (Repudiation): Inline two-button confirm requires explicit second click — mitigated as designed.
T-1034-03-02 (Tampering): Pill values come exclusively from `getRenderAsOptions(layer)` — no user-typed input.
T-1034-03-03 (Disclosure): Source section shows dataset metadata already visible elsewhere in the UI.

---

## Known Stubs

None. All sections render real content when data is available.

---

## Self-Check: PASSED
