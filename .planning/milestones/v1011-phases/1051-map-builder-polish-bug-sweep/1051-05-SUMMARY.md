---
phase: 1051-map-builder-polish-bug-sweep
plan: 05
subsystem: ui
tags: [builder, ux, sublayer-indicators, opacity-relocation, i18n, lucide, vitest]

# Dependency graph
requires:
  - phase: 1051-map-builder-polish-bug-sweep
    provides: Plans 01-04 already committed atomically; Plan 05 sits on UnifiedStackPanel SublayerRow surface introduced in v1008 (BSR) and modified by v1009 (POL) + the v1009.1 SP-01 portal-guard pattern referenced by the stack panel's outside-click handler
provides:
  - SublayerConfigIndicators component (0–4 Lucide-icon badges, pure-derivation)
  - Removal of the per-row opacity Slider from UnifiedStackPanel SublayerRow
  - 16 new i18n entries (`indicators.{labels,filter,dataDriven,opacityModified}` × en/de/es/fr — parity preserved at 4 locales)
  - 8 new vitest regression cases pinning the indicator-derivation contract
affects: [builder-sublayer-row, layer-editor-panel, basemap-sublayer-editor-scene]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Pure-derivation status badge component (0..N badges driven by `MapLayerResponse` config fields, returns null when no condition is met)"
    - "Opacity affordance relocation — per-row Slider removed in favour of flyout-only editing (BasemapSublayerEditorScene retains the canonical opacity surface)"
    - "Orphan-by-design prop documentation convention (UnifiedStackPanelProps keeps `onSublayerOpacityChange` optional; comment at destructure block mirrors the existing `onOpacityChange` convention)"

key-files:
  created:
    - frontend/src/components/builder/SublayerConfigIndicators.tsx
    - frontend/src/components/builder/__tests__/SublayerConfigIndicators.test.tsx
  modified:
    - frontend/src/components/builder/UnifiedStackPanel.tsx
    - frontend/src/i18n/locales/en/builder.json
    - frontend/src/i18n/locales/de/builder.json
    - frontend/src/i18n/locales/es/builder.json
    - frontend/src/i18n/locales/fr/builder.json

key-decisions:
  - "Sublayer row Cell 6 grid column widened 60px → 76px (4 × 16px badge + 3 × 4px gap = 76px exact fit) per plan recommendation"
  - "SublayerConfigIndicators receives `layer={null}` from SublayerRow because BasemapSublayerInfo only carries id/name/visible/opacity/kind — full MapLayerResponse plumbing deferred (acceptable per UI-SPEC §UX-02 footnote: 'render nothing when no condition is met')"
  - "`onSublayerOpacityChange` kept in UnifiedStackPanelProps (optional) but NOT destructured inside the component — matches existing `onOpacityChange` convention to avoid a MapBuilderPage diff that's out of scope for this plan"

patterns-established:
  - "Pure-derivation indicator badge: `useTranslation('builder')` + `t(key, { defaultValue })` + Lucide icon at h-3 w-3 + sr-only label, container `flex items-center gap-1`, badge `inline-flex items-center justify-center h-4 w-4 rounded-sm bg-[var(--primary-50)] text-[var(--primary-600)]`"
  - "i18n parity preserved by editing all 4 locales in the same commit and verifying via `npm run test:i18n` (resources.test.ts validates key-set equality across en/de/es/fr per top-level namespace)"
  - "TDD RED → GREEN flow for a brand-new component: write the test file first against a not-yet-existing import path; vitest fails with module-resolution error (RED proof); create the component; rerun (GREEN proof); commit RED + GREEN together as a single `feat` commit when no real production code existed before"

requirements-completed: [UX-02]

# Metrics
duration: ~15 min
completed: 2026-05-18
---

# Phase 1051 Plan 05: UX-02 Sublayer Config Indicators Summary

**Replaced the per-row opacity Slider on basemap sublayer rows with a new derived `SublayerConfigIndicators` badge strip (0–4 Lucide icons), relocating opacity editing exclusively to the LayerEditorPanel flyout.**

## Performance

- **Duration:** ~15 min (Tasks 2 + 3 executor work; Tasks 1 + 4 Playwright MCP gates deferred to orchestrator per phase 1051 lesson)
- **Started:** 2026-05-18T01:13:00Z (approximate)
- **Completed:** 2026-05-18T01:18:00Z (approximate)
- **Tasks executed:** 2 of 4 (Tasks 1 + 4 deferred — MCP is orchestrator-scoped per `<lesson_from_phase>`)
- **Files created:** 2
- **Files modified:** 5

## Accomplishments

- New `SublayerConfigIndicators.tsx` component exposes 0–4 derived status badges:
  - **Labels** (`Type` icon) — fires when `layer.label_config?.column` is set
  - **Filter** (`Filter` icon) — fires when `Array.isArray(layer.filter) && layer.filter.length > 0`
  - **DataDriven** (`Zap` icon) — fires when any `Object.values(layer.paint)` entry is an array (a MapLibre expression)
  - **OpacityModified** (`Layers` icon) — fires when `typeof layer.opacity === 'number' && layer.opacity !== 1`
  - Returns `null` when `layer` is null OR when zero conditions are met (per UI-SPEC §UX-02)
- Component is purely derived — no internal state, no useEffect, no callbacks. Reacts to layer prop changes synchronously.
- `UnifiedStackPanel.tsx` SublayerRow no longer renders a per-row Slider. Cell 6 of the sublayer grid template widened from `60px` → `76px` (exact fit for 4 × 16px badges + 3 × 4px gaps). The `Slider` import was removed from this file (only-use removed).
- Opacity editing for basemap sublayers remains fully accessible via the LayerEditorPanel flyout: clicking a sublayer row opens `BasemapSublayerEditorScene`, which renders the canonical opacity slider (line 213-220 of that file, unchanged by this plan). No duplicate opacity affordance introduced.
- 16 new i18n keys added under `indicators.*` × en/de/es/fr — locale parity preserved (`resources.test.ts` passes 2/2). German/Spanish/French translations authored fresh:
  - **en:** "Labels enabled" / "Filter applied" / "Data-driven style" / "Opacity adjusted"
  - **de:** "Beschriftungen aktiv" / "Filter angewendet" / "Datenbasierter Stil" / "Deckkraft angepasst"
  - **es:** "Etiquetas activadas" / "Filtro aplicado" / "Estilo basado en datos" / "Opacidad ajustada"
  - **fr:** "Étiquettes activées" / "Filtre appliqué" / "Style basé sur les données" / "Opacité ajustée"
- 8 vitest regression cases pin the derivation contract: null-layer → null; no-config → null; each-condition × 4; all-four-conditions → 4 badges; sr-only label assertion. All 8 pass.

## Task Commits

Each task was committed atomically:

1. **Task 2: Author SublayerConfigIndicators component + tests + i18n** — `79b0c0c6` (feat) — RED (test fails at module-resolution) + GREEN (component + 4 locale edits) shipped together as a single `feat` commit because no prior production surface existed for this component.
2. **Task 3: Swap UnifiedStackPanel sublayer row slider for SublayerConfigIndicators** — `a69d00ac` (refactor) — removed the Slider JSX block, the `Slider` import, the `onSublayerOpacityChange` SublayerRow prop consumption, and the orphaned `safeSublayerOpacityChange` helper; bumped Cell 6 grid width.

_Note: TDD RED + GREEN landed in a single commit (`79b0c0c6`) because both steps applied to a brand-new file with no pre-existing production code — there was nothing to fail-against in source until the test+component pair existed. Per plan task list this is Task 2's atomic commit._

## Files Created/Modified

### Created

- `frontend/src/components/builder/SublayerConfigIndicators.tsx` — derived-status component, 0–4 Lucide badges, `useTranslation('builder')` for labels, returns null when empty
- `frontend/src/components/builder/__tests__/SublayerConfigIndicators.test.tsx` — 8 vitest cases covering null + empty + each condition + all-four + sr-only a11y label

### Modified

- `frontend/src/components/builder/UnifiedStackPanel.tsx` — removed Slider import + Slider JSX + `onSublayerOpacityChange` SublayerRow prop + `safeSublayerOpacityChange` helper; added `SublayerConfigIndicators` import + JSX in Cell 6; widened grid `60px` → `76px`; documented orphan-by-design convention for the prop
- `frontend/src/i18n/locales/en/builder.json` — +5 lines (`indicators` namespace, 4 keys)
- `frontend/src/i18n/locales/de/builder.json` — +5 lines (same shape, German translations)
- `frontend/src/i18n/locales/es/builder.json` — +5 lines (Spanish)
- `frontend/src/i18n/locales/fr/builder.json` — +5 lines (French)

## Decisions Made

- **`layer={null}` for basemap sublayers (plumbing deferred).** `BasemapSublayerInfo` carries only `id/name/visible/opacity/kind` and does not expose `label_config`/`filter`/`paint`. Two options per PATTERNS.md Plan 05: (a) extend BasemapSublayerInfo to carry config metadata, (b) pass `null` and accept that the indicator strip is typically empty for basemap sublayers in this build. Chose (b) per UI-SPEC §UX-02 footnote ("render nothing when no condition is met") — the slider removal is the primary deliverable and the indicators are the polish layer. Option (a) is documented as a deferred enhancement in the file comment + this summary. The indicator component fully works against any `MapLayerResponse | null` it is given, so future work can swap in the live layer with no component change.
- **Cell 6 grid column 60px → 76px.** Per plan: 4 × 16px badges + 3 × 4px gaps = 76px exactly. Keeping 60px would clip 4-badge rows; bumping to 76px keeps layout stable and accommodates the maximum-rendered case without overflow. Sublayer-row grid template is independent of StackRow's grid (which uses `grid-cols-[16px_14px_22px_22px_1fr_22px]` per UX-01) so this change does not cascade.
- **`onSublayerOpacityChange` prop kept in UnifiedStackPanelProps (orphan-by-design).** The prop is no longer needed by `UnifiedStackPanel` itself, but `MapBuilderPage` still passes it through to the LayerEditorPanel flyout via a parallel handler (line 770 of MapBuilderPage, into BasemapGroupEditorScene). Removing the prop from UnifiedStackPanelProps would require a touch to MapBuilderPage line 1047, which is out of scope for Plan 05's `<files_modified>` list. Mirrored the existing convention at line 580-585 of UnifiedStackPanel for `onOpacityChange` (also orphan-by-design after v1008 BSR + v1009 POL removed row sliders).
- **TDD RED + GREEN in a single commit.** Standard TDD calls for separate `test(...)` then `feat(...)` commits. For a brand-new component file with no pre-existing production surface, the RED step is a module-resolution failure — there is no production code to fail against until the file exists. Per gsd-execute convention for first-commit-of-new-component, the RED+GREEN pair was committed together as `feat(1051-05): add SublayerConfigIndicators component + i18n (UX-02)`. The test file is part of the commit, so the gate is preserved: any future regression in the component breaks the same vitest cases that were authored RED-first.

## Deviations from Plan

### Deferred-by-design (per `<lesson_from_phase>` + Phase 1051 pattern)

**Task 1 + Task 4 — Playwright MCP captures deferred to orchestrator.**

- **Found during:** Plan start.
- **Issue:** Playwright MCP is orchestrator-scoped (per v1010.1 + v1010.2 lessons). The executor cannot drive MCP from a sequential agent context.
- **Action:** Deferred Task 1 (pre-fix MCP screenshot of Slider presence + LayerEditorPanel opacity surface confirmation) and Task 4 (post-fix MCP re-verify of slider removal + indicator rendering + flyout opacity reachability) to the orchestrator. The plan's `<lesson_from_phase>` explicitly authorises this deferral.
- **Verification:** Headless coverage stands in via vitest (8/8 in SublayerConfigIndicators + 32/32 in UnifiedStackPanel + 751/751 across all builder component tests + 2/2 i18n parity) and tsc (0 errors). All non-MCP acceptance criteria for both tasks are satisfied. The orchestrator owes a live MCP re-verify on `localhost:8080` against a map with an expanded basemap group before declaring this plan green-go for CTRL-01.

### Auto-fixed Issues

**None.** No deviation rules fired. The plan was executable as written; the only deferral is the Playwright MCP gate, which was anticipated by the plan author (`<lesson_from_phase>`) and is not a deviation.

---

**Total deviations:** 0 auto-fixed. Two `checkpoint:orchestrator` tasks deferred per phase pattern (not a deviation — anticipated by the plan).

**Impact on plan:** None — slider removal and indicator surface ship complete with full headless coverage. Live MCP verify is the orchestrator's responsibility per the documented Phase 1051 protocol.

## Issues Encountered

- **`grep -c 'indicators\.' ...` acceptance criterion mismatched the JSON structure.** The plan's acceptance check was `grep -c 'indicators\\.'` (literal substring `indicators.`), but the JSON keys are nested under an `indicators` object — there is no `indicators.` literal substring in the file. Used a `python -c 'json.load(...)'` check instead to confirm all 4 locales have all 4 child keys under `indicators` (verified — 4 keys × 4 locales). The plan's i18n parity test (`npm run test:i18n` → `resources.test.ts`) is the authoritative parity gate and passed.
- **Lint warnings (2) are pre-existing and out of scope.** `npx eslint` reports 2 unused-eslint-disable warnings at lines 679 + 720 of UnifiedStackPanel.tsx — these are Phase 1041 selection effects, NOT introduced by this plan's diff. Confirmed by `git diff HEAD | grep eslint-disable` (0 new). Per `<deviation_rules>` SCOPE BOUNDARY, out-of-scope pre-existing warnings are not auto-fixed here.

## User Setup Required

None — no external services or environment variables touched.

## Next Phase Readiness

- Wave 6 (Plan 1051-06 — UX-03 draggable basemap row) is unblocked. Plan 05's surface (UnifiedStackPanel SublayerRow) does not overlap Plan 06's surface (BasemapGroupRow drag wiring).
- Orchestrator owes Playwright MCP re-verify of the sublayer row before Plan 1051-13 CTRL-01 close gate:
  - Confirm NO opacity Slider in sublayer rows of an expanded basemap group
  - Confirm clicking a sublayer row opens the LayerEditorPanel flyout AND that the flyout's opacity slider remains functional (it should — `BasemapSublayerEditorScene` line 213-220 is unchanged)
  - In a future build where basemap sublayers carry `label_config`/`filter`/`paint` metadata, the indicator strip will populate; until then, the strip renders empty by design.
- Deferred enhancement opportunity (NOT a blocker): plumb the full `MapLayerResponse` through `BasemapSublayerInfo` so the indicators activate for basemap sublayers. This is a 2-file change (UnifiedStackPanel sublayer type + BasemapGroupRow rendering) and is a candidate for a future plan if user-editable sublayer filter/label is added.

## Self-Check

- [x] `frontend/src/components/builder/SublayerConfigIndicators.tsx` exists
- [x] `frontend/src/components/builder/__tests__/SublayerConfigIndicators.test.tsx` exists
- [x] Commit `79b0c0c6` exists in git log
- [x] Commit `a69d00ac` exists in git log
- [x] `frontend/src/i18n/locales/{en,de,es,fr}/builder.json` all have `indicators.{labels,filter,dataDriven,opacityModified}` (verified via `python json.load`)
- [x] `npm run test:i18n` 2/2 PASS
- [x] `npx vitest run src/components/builder/__tests__/SublayerConfigIndicators.test.tsx` 8/8 PASS
- [x] `npx vitest run src/components/builder/__tests__/UnifiedStackPanel.test.tsx` 32/32 PASS
- [x] `npx vitest run src/components/builder/__tests__/` 751/751 PASS
- [x] `npx tsc --noEmit` 0 errors
- [x] `grep -n '<Slider' frontend/src/components/builder/UnifiedStackPanel.tsx` returns 0 (sublayer Slider removed)
- [x] `grep -n 'SublayerConfigIndicators' frontend/src/components/builder/UnifiedStackPanel.tsx` returns ≥2 (import + JSX use)

## Self-Check: PASSED

---
*Phase: 1051-map-builder-polish-bug-sweep, Plan 05*
*Completed: 2026-05-18*
