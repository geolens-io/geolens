---
phase: 1051
plan: 05
type: execute
wave: 5
depends_on: ["1051-04"]
files_modified:
  - frontend/src/components/builder/SublayerConfigIndicators.tsx
  - frontend/src/components/builder/UnifiedStackPanel.tsx
  - frontend/src/components/builder/__tests__/SublayerConfigIndicators.test.tsx
  - frontend/src/i18n/locales/en/builder.json
  - frontend/src/i18n/locales/de/builder.json
  - frontend/src/i18n/locales/es/builder.json
  - frontend/src/i18n/locales/fr/builder.json
autonomous: false
requirements: [UX-02]
tags: [builder, ux, sublayer-indicators, opacity-relocation]

must_haves:
  truths:
    - "Basemap sublayer rows in UnifiedStackPanel have NO per-row opacity slider"
    - "Each sublayer row shows 0–4 config-state indicator badges (labels-present, filter-present, data-driven-paint, opacity-modified)"
    - "Indicators react to live config state on mount and on layer prop changes"
    - "Opacity editing remains accessible via the LayerEditorPanel flyout opened by clicking the sublayer row"
    - "Indicator copy is translated en/de/es/fr (locked at 4 locales per v1009 parity)"
  artifacts:
    - path: "frontend/src/components/builder/SublayerConfigIndicators.tsx"
      provides: "Net-new component rendering 0–4 Lucide-icon badges per UI-SPEC UX-02 contract"
      contains: "SublayerConfigIndicators"
    - path: "frontend/src/components/builder/UnifiedStackPanel.tsx"
      provides: "Sublayer row Cell 6 swapped from <Slider> to <SublayerConfigIndicators>"
      contains: "SublayerConfigIndicators"
    - path: "frontend/src/components/builder/__tests__/SublayerConfigIndicators.test.tsx"
      provides: "Unit tests for each indicator condition (label, filter, data-driven, opacity) + the no-config zero-badge case"
      contains: "SublayerConfigIndicators"
  key_links:
    - from: "UnifiedStackPanel.tsx sublayer row Cell 6"
      to: "SublayerConfigIndicators.tsx"
      via: "Render <SublayerConfigIndicators layer={layer} /> in the slot previously occupied by <Slider>"
      pattern: "SublayerConfigIndicators"
---

<objective>
Fix UX-02: Sublayer rows replace the per-row opacity slider with config-state indicators. Basemap sublayer rows in UnifiedStackPanel display 0–4 small Lucide-icon badges reflecting live config state (labels present, filter applied, data-driven paint, opacity modified). The per-row opacity slider is removed; opacity editing remains available via the LayerEditorPanel flyout opened by clicking the sublayer row.

Per PATTERNS.md Plan 05: introduces a NEW component `SublayerConfigIndicators.tsx`. The slider at `UnifiedStackPanel.tsx:490-512` (Cell 6 of the sublayer row grid) is the slot to swap. Visual contract is locked by UI-SPEC §UX-02 (h-4 w-4 badge, h-3 w-3 icon, `bg-[var(--primary-50)] text-[var(--primary-600)]`).

NOTE on `BasemapSublayerInfo` (PATTERNS.md line 326-336): the current sublayer info type carries only id/name/visible/opacity/kind — NOT label/filter/paint config. The indicators receive a `layer: MapLayerResponse | null` prop (NOT BasemapSublayerInfo). Executor must either (a) plumb the live MapLayerResponse through to the sublayer row OR (b) accept that v1011 basemap sublayers commonly have no editable filter/label so the indicator strip is typically empty (renders nothing) — both are acceptable per UI-SPEC §UX-02 footnote "if no config conditions are met, render nothing". The slider removal is the primary deliverable; the indicators are the polish.

Purpose: Reduce sublayer row clutter; surface high-impact configuration at a glance; centralize opacity editing in the flyout.
Output: New `SublayerConfigIndicators` component; slider removal from sublayer row; 4 indicator copy keys × 4 locales = 16 new i18n entries; unit tests for indicator logic.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/ROADMAP.md
@.planning/STATE.md
@.planning/phases/1051-map-builder-polish-bug-sweep/1051-CONTEXT.md
@.planning/phases/1051-map-builder-polish-bug-sweep/1051-PATTERNS.md
@.planning/phases/1051-map-builder-polish-bug-sweep/1051-UI-SPEC.md

<interfaces>
<!-- From PATTERNS.md — slot to replace + new component skeleton + i18n shape. -->

From frontend/src/components/builder/UnifiedStackPanel.tsx (lines 490-512 — current Slider in Cell 6 to REMOVE):
```tsx
{/* Cell 6: Opacity slider */}
<div className="flex items-center" onPointerDown={(e) => e.stopPropagation()} onClick={(e) => e.stopPropagation()}>
  <Slider
    aria-label={`Opacity for ${sublayer.name}`}
    value={[safeOpacity]}
    min={0} max={1} step={0.05}
    className="w-[60px]"
    onValueChange={([value]) => { onSublayerOpacityChange(sublayer.id, ...); }}
  />
</div>
```

UI-SPEC UX-02 indicator contract:

| Indicator | Trigger | Icon | i18n key |
|-----------|---------|------|----------|
| Has labels | `layout['text-field']` set AND non-empty | Type | `indicators.labels` |
| Has filters | `filter` array non-empty | Filter | `indicators.filter` |
| Data-driven | any paint property is array | Zap | `indicators.dataDriven` |
| Opacity modified | `opacity !== 1` | Layers | `indicators.opacityModified` |

Badge style: `inline-flex items-center justify-center h-4 w-4 rounded-sm bg-[var(--primary-50)] text-[var(--primary-600)]` + icon `h-3 w-3` + `<span className="sr-only">{label}</span>`.

Existing i18n locale files (en/de/es/fr) at `frontend/src/i18n/locales/{en,de,es,fr}/builder.json` — parity locked at 770 keys per v1009 MEMORY note.
</interfaces>
</context>

<tasks>

<task type="checkpoint:orchestrator">
  <name>Task 1: Playwright MCP pre-fix capture</name>
  <files>(no files modified)</files>
  <read_first>
    - .planning/phases/1051-map-builder-polish-bug-sweep/1051-PATTERNS.md (Plan 05 — slot to swap + indicator visuals)
    - .planning/phases/1051-map-builder-polish-bug-sweep/1051-UI-SPEC.md (UX-02 contract)
  </read_first>
  <action>
    Orchestrator drives Playwright MCP. Steps: (1) Open a map with a basemap group that has ≥1 sublayer. (2) Expand the basemap group. (3) Confirm each sublayer row currently shows the per-row opacity slider in the trailing cell. (4) Click a sublayer row — confirm it opens the LayerEditorPanel flyout. (5) Confirm the flyout EXPOSES the opacity control (so removing the row slider does not orphan the affordance). (6) Screenshot the sublayer row UI for diff comparison. Add incidental issues to scratch list for EMRG-01.
  </action>
  <verify>
    <automated>Playwright MCP captures current sublayer row UI (with slider) and confirms LayerEditorPanel exposes opacity edit.</automated>
  </verify>
  <acceptance_criteria>
    - Current slider presence confirmed in sublayer rows
    - LayerEditorPanel opacity surface confirmed present (opacity affordance survives slider removal)
    - Pre-fix screenshot captured
  </acceptance_criteria>
  <done>Pre-fix UI captured.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Author SublayerConfigIndicators component + unit tests + i18n keys</name>
  <files>frontend/src/components/builder/SublayerConfigIndicators.tsx, frontend/src/components/builder/__tests__/SublayerConfigIndicators.test.tsx, frontend/src/i18n/locales/en/builder.json, frontend/src/i18n/locales/de/builder.json, frontend/src/i18n/locales/es/builder.json, frontend/src/i18n/locales/fr/builder.json</files>
  <read_first>
    - frontend/src/components/builder/LayerEditorPanel.tsx (LayerEditorTypePill around lines 84-109 — the inline rounded chip pattern to mirror)
    - frontend/src/types/api.ts or wherever MapLayerResponse type is defined (grep `export.*MapLayerResponse` in frontend/src/types and frontend/src/api)
    - frontend/src/components/builder/__tests__/BasemapAppearanceControls.test.tsx (reference for isolated component test with MapLayerResponse fixture)
    - frontend/src/i18n/locales/en/builder.json (and the 3 sibling locales — confirm 770-key parity is maintained)
    - .planning/phases/1051-map-builder-polish-bug-sweep/1051-PATTERNS.md (Plan 05 — new component skeleton + reference LayerEditorTypePill)
    - .planning/phases/1051-map-builder-polish-bug-sweep/1051-UI-SPEC.md (UX-02 indicator table + visual styles)
  </read_first>
  <behavior>
    - Test 1: layer=null → renders null (no DOM output)
    - Test 2: layer with no config (no label, no filter, opacity=1, paint values all scalar) → renders null
    - Test 3: layer with `layout['text-field'] = 'name'` → renders a 'labels' badge
    - Test 4: layer with `filter: ['==', 'foo', 1]` → renders a 'filter' badge
    - Test 5: layer with `paint: { 'fill-color': ['get', 'color'] }` (array → expression) → renders a 'dataDriven' badge
    - Test 6: layer with `opacity: 0.5` → renders an 'opacityModified' badge
    - Test 7: layer with all four conditions → renders 4 badges; max-render cap respected
    - Test 8: Each badge has aria-label from i18n key (assert sr-only text)
  </behavior>
  <action>
    Create `frontend/src/components/builder/SublayerConfigIndicators.tsx` per the UI-SPEC §UX-02 contract: accept `{ layer: MapLayerResponse | null }`, derive 0–4 indicators by the trigger conditions in the UI-SPEC table, render each as a `<span>` with `inline-flex items-center justify-center h-4 w-4 rounded-sm bg-[var(--primary-50)] text-[var(--primary-600)]` plus child Lucide icon at `h-3 w-3` + sr-only label. Use `useTranslation('builder')` for the four labels: `indicators.labels`, `indicators.filter`, `indicators.dataDriven`, `indicators.opacityModified`. Default values: `'Labels enabled'`, `'Filter applied'`, `'Data-driven style'`, `'Opacity adjusted'`. Render container: `<div className="flex items-center gap-1">{badges.slice(0, 4)}</div>`. If `indicators.length === 0`, return null.
    
    Add the four new i18n keys to EACH of `frontend/src/i18n/locales/{en,de,es,fr}/builder.json` under a new `indicators` namespace. English uses the UI-SPEC defaults; for de/es/fr provide reasonable translations (or copy the English string as a defaultValue if the locale already has the i18n parity-relaxed key pattern — verify by reading one sibling key's locale shape). Maintain the 770-key parity (adding 4 to each locale = 774 total per locale, all 4 locales in sync).
    
    Create `frontend/src/components/builder/__tests__/SublayerConfigIndicators.test.tsx` with the 8 behavior tests above. Use a minimal `MapLayerResponse` fixture (import the type or use a typed object literal). Wrap with the i18n test provider per the existing test pattern (see `__tests__/BasemapAppearanceControls.test.tsx`).
  </action>
  <verify>
    <automated>cd frontend && npx vitest run src/components/builder/__tests__/SublayerConfigIndicators.test.tsx</automated>
  </verify>
  <acceptance_criteria>
    - File `frontend/src/components/builder/SublayerConfigIndicators.tsx` exists, exports `SublayerConfigIndicators`
    - All 4 indicator branches covered by tests
    - `grep -c 'indicators\\.' frontend/src/i18n/locales/en/builder.json frontend/src/i18n/locales/de/builder.json frontend/src/i18n/locales/es/builder.json frontend/src/i18n/locales/fr/builder.json` returns ≥4 for each file
    - i18n key parity check passes (run `npm run i18n:check` if such script exists; otherwise manually verify all 4 locales have the same key set under `indicators.`)
    - `cd frontend && npx tsc --noEmit` returns 0 errors
  </acceptance_criteria>
  <done>Component + tests + i18n keys all green.</done>
</task>

<task type="auto">
  <name>Task 3: Swap UnifiedStackPanel sublayer row slider for SublayerConfigIndicators</name>
  <files>frontend/src/components/builder/UnifiedStackPanel.tsx</files>
  <read_first>
    - frontend/src/components/builder/UnifiedStackPanel.tsx (sublayer row rendering around lines 423 grid template + lines 490-512 Cell 6 Slider)
    - frontend/src/components/builder/SublayerConfigIndicators.tsx (the component just created)
    - .planning/phases/1051-map-builder-polish-bug-sweep/1051-PATTERNS.md (Plan 05 — grid-cols decision)
  </read_first>
  <action>
    Edit `frontend/src/components/builder/UnifiedStackPanel.tsx`: (a) add `import { SublayerConfigIndicators } from './SublayerConfigIndicators';` near the existing builder-component imports. (b) Locate the sublayer row grid template (around line 423) — current value is approximately `grid-cols-[16px_14px_22px_22px_1fr_60px_22px]`. Keep the 60px Cell 6 column width — the indicator strip max-width fits comfortably (4 × 16px + 3 × 4px gap = 76px would overflow; the existing 60px will need either expansion to 80px OR clipping). Choose: if indicator strip never exceeds 4 badges (UI-SPEC says max 4), bump the column to 76px to fit exactly OR keep 60px and accept truncation. Recommended: 76px (4 × 16 + 3 × 4 = 76). Document the choice in the commit. (c) Replace the Slider JSX block at lines ~490-512 with `<div className="flex items-center" onPointerDown={(e) => e.stopPropagation()} onClick={(e) => e.stopPropagation()}><SublayerConfigIndicators layer={layerForSublayer} /></div>`. (d) The component needs a `MapLayerResponse | null` — pass `null` if BasemapSublayerInfo cannot be expanded to MapLayerResponse in this code path (acceptable per PATTERNS.md Plan 05 note — UI-SPEC says indicators render empty when no config). If a plumbing pass-through is straightforward (e.g., the parent already has the full layer), pass the live layer. (e) Remove the `onSublayerOpacityChange` prop usage from this slot; verify the prop is still passed to the LayerEditorPanel flyout (or removed if unused after this swap — grep `onSublayerOpacityChange` to confirm orphan vs in-use).
    
    Do NOT change the LayerEditorPanel flyout opacity surface — opacity editing must remain there per UX-02 success criteria.
  </action>
  <verify>
    <automated>cd frontend && npx vitest run src/components/builder/__tests__/UnifiedStackPanel.test.tsx 2>/dev/null; cd frontend && npx tsc --noEmit</automated>
  </verify>
  <acceptance_criteria>
    - `grep -n '<Slider' frontend/src/components/builder/UnifiedStackPanel.tsx | grep -i sublayer` returns 0 matches (sublayer row Slider removed)
    - `grep -n 'SublayerConfigIndicators' frontend/src/components/builder/UnifiedStackPanel.tsx` returns ≥2 matches (import + JSX use)
    - If `onSublayerOpacityChange` is now orphaned in UnifiedStackPanel, remove the prop; otherwise leave it (passed through to LayerEditorPanel)
    - `cd frontend && npx tsc --noEmit` returns 0 errors
    - Diff is minimal: import + slot swap + grid-cols width tweak (if applied)
  </acceptance_criteria>
  <done>Slider replaced with indicators; sublayer row layout preserved.</done>
</task>

<task type="checkpoint:orchestrator">
  <name>Task 4: Playwright MCP post-fix re-verify + atomic commit</name>
  <files>(no files modified beyond commit)</files>
  <read_first>
    - .planning/phases/1051-map-builder-polish-bug-sweep/1051-PATTERNS.md
    - .planning/phases/1051-map-builder-polish-bug-sweep/1051-UI-SPEC.md
  </read_first>
  <action>
    Orchestrator drives Playwright MCP. Steps: (1) Reload page. (2) Open a map with a basemap group containing ≥1 sublayer. (3) Expand the basemap group. (4) Confirm each sublayer row has NO opacity slider in the trailing cell. (5) If any sublayer has filter/label/data-driven/opacity-modified config, confirm corresponding indicator badge is visible. (6) Click a sublayer row → confirm LayerEditorPanel flyout opens AND opacity control is reachable from the flyout. (7) Edit opacity in the flyout → confirm the value updates correctly + the sublayer row's `opacity-modified` indicator (if shown) reacts. After MCP verify passes, create atomic commit with subject: `refactor(builder): sublayer rows show config-state indicators instead of opacity slider (UX-02)`. Stage SublayerConfigIndicators.tsx + UnifiedStackPanel.tsx + the test file + the 4 i18n locale files.
  </action>
  <verify>
    <automated>git log --oneline -1 && git show --stat HEAD</automated>
  </verify>
  <acceptance_criteria>
    - Playwright MCP confirms no per-sublayer slider
    - Indicators render correctly when config conditions are met
    - LayerEditorPanel opacity editing still accessible
    - Commit exists with subject `refactor(builder): sublayer rows show config-state indicators instead of opacity slider (UX-02)`
    - `git diff HEAD~1 HEAD --stat` shows only the 7 in-scope files modified
  </acceptance_criteria>
  <done>UX-02 fix verified live + committed atomically.</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| client-only UI | Indicators derive from in-app layer state; no new API surface |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-1051-05 | (n/a) | indicator badges | accept | No security surface; pure visual |
| T-1051-05-i18n | Tampering | i18n key parity | accept | All 4 locales updated atomically in same commit; parity script (if any) enforces |
</threat_model>

<verification>
- Playwright MCP confirms slider removed + indicators react to config
- Vitest unit tests for SublayerConfigIndicators pass
- `npx tsc --noEmit` returns 0 errors
- i18n key parity preserved across en/de/es/fr
- LayerEditorPanel opacity editing remains intact
</verification>

<success_criteria>
- Basemap sublayer rows have NO opacity slider
- Each sublayer row shows config-state indicators (up to 4) reflecting live config
- Opacity editing remains accessible via LayerEditorPanel flyout
- Indicators react to config edits
- Vitest confirms indicator surface
- i18n parity at en/de/es/fr (4 new keys × 4 locales)
- Atomic commit on main with subject `refactor(builder): sublayer rows show config-state indicators instead of opacity slider (UX-02)`
</success_criteria>

<output>
Create `.planning/phases/1051-map-builder-polish-bug-sweep/1051-05-SUMMARY.md` with: chosen indicator set, slider removal scope, files modified, test result, MCP screenshots.
</output>
