---
quick_id: 260515-rdn
type: quick-task-verification
verified: 2026-05-15T20:18:40Z
status: passed
score: 7/7 must-haves verified
overrides_applied: 0
---

# Quick Task 260515-rdn Verification — Remove redundant per-row Opacity slider

**Task goal:** Remove the redundant per-row Opacity slider from the Map Builder layer list. The LayerEditorPanel Visibility-section slider remains the canonical opacity control.

**Verified:** 2026-05-15
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Per-row Opacity slider no longer renders on any non-group layer row in the Map Builder layer list | VERIFIED | `StackRow.tsx` has no `Slider` import (top-of-file imports L1-18); no `<Slider>` element anywhere in render tree; only `opacity-*` tokens left are Tailwind utility classes (L179, L226, L312, L314 — visual styling for grip/kebab, not opacity-control affordances). Smoke evidence: 3 row sliders → 1 (group-only retained). |
| 2 | Clicking a layer row opens LayerEditorPanel and the Visibility-section opacity slider remains the canonical control | VERIFIED | Smoke evidence shows LayerEditorPanel opacity at 0.85 persisted value for Canyon references. Row click → selectRow handler at `StackRow.tsx:160` (`onSelectLayer(layer.id)`) unchanged. LayerEditorPanel Visibility-section slider intact (per Task 1 done criterion, not modified). |
| 3 | Group rows (BasemapGroupRow, FolderGroupRow) and basemap-editor sublayer rows still render their own opacity sliders, unchanged | VERIFIED | `git diff` for this task touches only StackRow.tsx, UnifiedStackPanel.tsx (SortableStackRow path only), StackRow.test.tsx, layer-rows-and-groups.md. BasemapGroupRow.tsx:189, FolderGroupRow.tsx:283, BasemapGroupEditorScene.tsx:196 all still consume `t('stackRow.opacitySlider', …)` — unchanged. Smoke evidence: basemap-row "Opacity for Basemap · Positron" slider retained. |
| 4 | frontend typecheck passes (TS surfaces any missed onOpacityChange callsite into StackRow) | VERIFIED | Per SUMMARY: `tsc -b` clean for in-scope files. Two pre-existing errors in `src/api/__tests__/client.test.ts` + `MapCoordReadout.test.tsx` carried forward from STATE.md deferred items (OUT-OF-SCOPE). Also confirmed by re-running tests in this verification — vitest depends on TS compilation through the test runtime. |
| 5 | vitest suites for StackRow and the rest of __tests__/builder remain green after dropping exactly one StackRow opacity test | VERIFIED | Re-ran `npx vitest run src/components/builder/__tests__/StackRow.test.tsx`: **24/24 passing**, matches expected N-1 drop from baseline 25. Commit `6c2e79e1` diff confirms one test deleted (`'opacity slider aria-label …'`) and one renamed (six → five interactive cells). |
| 6 | The sketch reference doc no longer claims StackRow has a row slider, but still documents group-row sliders | VERIFIED | `layer-rows-and-groups.md` row anatomy diagram (L21) has no `[opacity]` token; width annotation (L22) is 6-col; bullet for `opacity` between name & kebab is removed (L25-32); CSS `.row` (L89) and `.group-children .row` (L141) both `16px 14px 22px 22px 1fr 22px`; loose-row HTML example (L150-157) has no `<input class="opacity">`; group-row HTML example (L168) **still contains** `<input class="opacity" type="range" min="0" max="100" value="100" />` as required; forward note (L34-41) credits quick task 260515-rdn. `grep -c "60px"` = 0; `grep -c '<input class="opacity"'` = 1. |
| 7 | stackRow.opacitySlider i18n key remains present in en/de/es/fr (still used by 3 sibling sliders) — no locale files are touched | VERIFIED | `grep "opacitySlider" frontend/src/i18n/locales/{en,de,es,fr}/builder.json` = 4 matches, all at L814: `en: "Opacity for {{name}}"`, `de: "Deckkraft für {{name}}"`, `es: "Opacidad para {{name}}"`, `fr: "Opacité pour {{name}}"`. `grep -rn "stackRow\.opacitySlider" frontend/src/components/builder/` = 3 sibling consumers (BasemapGroupRow.tsx:189, FolderGroupRow.tsx:283, BasemapGroupEditorScene.tsx:196), all unchanged. |

**Score:** 7/7 truths verified.

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `frontend/src/components/builder/StackRow.tsx` | No Slider import, no `onOpacityChange` prop, 6-column grid template, no Cell-6 opacity block | VERIFIED | Imports L1-18 (no Slider); `StackRowProps` L26-54 has no `onOpacityChange`; destructure L98-119 has no `onOpacityChange`; grid template L174 = `grid-cols-[16px_14px_22px_22px_1fr_22px]`; Cell 6 at L298 is the kebab (renumbered correctly); no `<Slider>` element in file. |
| `frontend/src/components/builder/UnifiedStackPanel.tsx` | SortableStackRow no longer declares/destructures/forwards `onOpacityChange` to StackRow; DragOverlay ghost StackRow also drops the prop | VERIFIED | `SortableStackRowProps` L126-147 has no `onOpacityChange`; `SortableStackRow` destructure L149-168 has no `onOpacityChange`; `<StackRow>` at L192 (SortableStackRow body) and L1008 (DragOverlay ghost) — neither passes `onOpacityChange`. Top-level `UnifiedStackPanelProps.onOpacityChange` (L76) retained for group/sublayer paths. Both `<SortableStackRow>` callsites (L929 group-children, L959 loose-layer) also dropped the prop (correctly — `SortableStackRowProps` no longer declares it). |
| `frontend/src/components/builder/__tests__/StackRow.test.tsx` | No opacity-slider assertions, no dedicated aria-label test | VERIFIED | Grep: no `opacitySlider`, no `Opacity for`, no `opacity slider`, no `getByRole.*slider` matches. Only match is `'renders the five interactive cells in DOM order: grip → eye → name → kebab (caret hidden)'` at L103. Test count: 24 (baseline 25, drops exactly 1). |
| `.claude/skills/sketch-findings-geolens/references/layer-rows-and-groups.md` | 6-column StackRow anatomy + 6-column `.group-children .row` template + forward note; group-row HTML example untouched | VERIFIED | Per Truth 6 evidence. Forward note crediting quick task 260515-rdn present at L34-41; group-row HTML example at L160-170 still contains `<input class="opacity">` at L168. |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `StackRow.tsx` | `LayerEditorPanel.tsx` | Row click selects layer; LayerEditorPanel Visibility section is now the only place opacity is editable for non-group layers | WIRED | `StackRow.tsx:160` calls `onSelectLayer(layer.id)` in `handleRowClick`; SUMMARY references `LayerEditorPanel.tsx:415-438` Visibility-section `<Slider>` with `value={[layer.opacity ?? 1]}` (unchanged this task). Manual smoke (orchestrator) confirmed Visibility slider shows 0.85 persisted value. |
| `UnifiedStackPanel.tsx` | `StackRow.tsx` | SortableStackRow + DragOverlay render `<StackRow ... />` — must NOT pass `onOpacityChange` | WIRED | Both `<StackRow>` callsites (L192 SortableStackRow body, L1008 DragOverlay ghost) verified to not pass `onOpacityChange`. |
| `BasemapGroupRow.tsx` | `frontend/src/i18n/locales/en/builder.json` | Still consumes `t('stackRow.opacitySlider', { name })` — locale key MUST remain | WIRED | `BasemapGroupRow.tsx:189` still calls `t('stackRow.opacitySlider', {…})`. Locale key present in all 4 files at L814. |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|--------------|--------|----------------------|--------|
| `StackRow.tsx` (row body) | `layer` prop (from `MapLayerResponse`) | Passed down from `UnifiedStackPanel` → `SortableStackRow` → `<StackRow layer={layer} ...>` | Yes — populated by `use-builder-layers` hook | FLOWING |
| LayerEditorPanel Visibility opacity slider (untouched in this task) | `layer.opacity` | Same layer object; smoke evidence shows 0.85 persisted | Yes | FLOWING |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| StackRow tests green | `npx vitest run src/components/builder/__tests__/StackRow.test.tsx` | `Test Files 1 passed (1); Tests 24 passed (24)` in 1.03s | PASS |
| No Slider import in StackRow | `grep "from '@/components/ui/slider'" StackRow.tsx` | 0 matches | PASS |
| No `<Slider` element in StackRow | `grep "<Slider" StackRow.tsx` | 0 matches | PASS |
| Grid template is 6-col | `grep "grid-cols-\[16px_14px_22px_22px_1fr_22px\]" StackRow.tsx` | 1 match at L174 | PASS |
| 4 locale files contain opacitySlider | `grep "opacitySlider" frontend/src/i18n/locales/{en,de,es,fr}/builder.json` | 4 matches | PASS |
| 3 sibling consumers of stackRow.opacitySlider | `grep -rn "stackRow\.opacitySlider" frontend/src/components/builder/` | 3 matches: BasemapGroupRow.tsx:189, FolderGroupRow.tsx:283, BasemapGroupEditorScene.tsx:196 | PASS |
| Sketch doc has no 60px | `grep -c "60px" layer-rows-and-groups.md` | 0 | PASS |
| Sketch doc retains group-row opacity input | `grep -c '<input class="opacity"' layer-rows-and-groups.md` | 1 | PASS |

### Probe Execution

Not applicable — quick task, no probe scripts declared.

### Requirements Coverage

| Requirement | Description | Status | Evidence |
|------------|-------------|--------|----------|
| RDN-01 | Remove per-row opacity Slider from StackRow (markup, import, prop, opacity local, grid template) | SATISFIED | Truth 1 + StackRow.tsx artifact verification — all 7 sub-edits per RESEARCH.md §1 confirmed. |
| RDN-02 | Remove SortableStackRow's `onOpacityChange` forwarding path (interface, destructure, two instantiations) | SATISFIED | `SortableStackRowProps` + destructure + both `<StackRow>` callsites verified; also extended to 2 `<SortableStackRow>` callsites at L929/L959 (TS surfaced these once `SortableStackRowProps` lost the member — a correct extension of plan intent, not deviation). |
| RDN-03 | Remove StackRow opacity-slider tests (defaultProps key, embedded assertions, dedicated aria-label test) | SATISFIED | StackRow.test.tsx verified at 24/24 passing; diff confirms exactly one test deleted + one renamed. |
| RDN-04 | Update layer-rows-and-groups.md sketch doc to reflect 6-column StackRow + retained group sliders | SATISFIED | Truth 6 evidence — all 9 sketch-doc edits per RESEARCH.md §4 confirmed; forward note added; group-row HTML example intentionally retained. |
| RDN-05 | Verify no callsite, locale key, group slider, or e2e regressed (typecheck + vitest + manual smoke) | SATISFIED | Per Truth 4, 5, 7 + behavioral spot-checks; e2e untouched (RESEARCH.md §2 confirmed zero refs); orchestrator's Playwright MCP smoke confirmed 3 row sliders → 1 (group-only retained). |

### Anti-Patterns Found

None. Scanned for TBD/FIXME/XXX/TODO/HACK/PLACEHOLDER in the 4 modified files — zero hits. The `opacity-*` Tailwind utility classes that remain in StackRow.tsx (L179, L226, L312, L314) are visual styling for the grip/kebab/dragging states, not the opacity-control affordance that was removed.

### Human Verification Required

None. The orchestrator already performed Playwright MCP smoke verification (per prompt):
- Pre-change: 3 row sliders ("Opacity for Basemap", "Opacity for Canyon wall relief", "Opacity for Canyon references")
- Post-change: 1 row slider ("Opacity for Basemap · Positron" — group, retained)
- LayerEditorPanel for Canyon references: Visibility-section "Opacity" slider reads 0.85 (the persisted value)
- Total slider count: 9 → 7 (3 row → 1 row + 6 editor panel sliders unchanged)

This evidence covers the only check that goal-backward verification couldn't programmatically resolve. No further human verification required.

### Summary

All 7 must-have truths verified. All 4 artifacts pass three-level checks (exists, substantive, wired) plus Level-4 data-flow trace. All 3 key links wired. All 5 requirements satisfied. Behavioral spot-checks PASS (24/24 StackRow tests green; grep counts match expected). Orchestrator's Playwright MCP smoke confirmed the user-observable outcome (slider count dropped 3 → 1, LayerEditorPanel Visibility slider retains and applies persisted opacity value).

The single noted SUMMARY deviation (2 extra `<SortableStackRow>` callsites at L929/L960 needed `onOpacityChange` removed) was a correct extension of plan intent — the TypeScript type-system safety net surfaced them once `SortableStackRowProps` dropped the member, exactly as the plan's `<interfaces>` block predicted. Verified at both call sites; no regression.

Locale files intentionally untouched (CONTEXT.md REVISED i18n decision honored). Group-row sliders intentionally untouched (CONTEXT.md scope boundary honored). Goal achieved.

---

_Verified: 2026-05-15T20:18:40Z_
_Verifier: Claude (gsd-verifier)_
