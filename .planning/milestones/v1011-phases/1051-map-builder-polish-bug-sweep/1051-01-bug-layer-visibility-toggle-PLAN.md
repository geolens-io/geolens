---
phase: 1051
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - frontend/src/components/builder/hooks/use-layer-map-sync.ts
  - frontend/src/components/builder/hooks/use-builder-layers.ts
  - frontend/src/components/builder/UnifiedStackPanel.tsx
  - frontend/src/components/builder/StackRow.tsx
  - frontend/src/components/builder/hooks/__tests__/use-layer-map-sync.test.ts
autonomous: false
requirements: [BUG-01]
tags: [builder, bugfix, visibility-toggle]

must_haves:
  truths:
    - "Clicking the visibility eye on a regular (non-basemap, non-sublayer) layer at http://localhost:8080/maps/c868cc3a-a3a0-4714-b559-67b3f2b478e2 toggles MapLibre visibility between 'visible' and 'none' on every click"
    - "Tiles disappear from map when visibility toggled off; reappear when toggled on"
    - "No regression to basemap-sublayer visibility toggles or v1009 POL-multi-select bulk visibility toggle"
  artifacts:
    - path: "frontend/src/components/builder/hooks/use-layer-map-sync.ts"
      provides: "handleToggleVisibility that dispatches setLayoutProperty for all layer companions"
      contains: "setLayoutProperty"
    - path: "frontend/src/components/builder/hooks/__tests__/use-layer-map-sync.test.ts"
      provides: "vitest regression case asserting visible→hidden→visible round-trip dispatches twice"
      contains: "setLayoutProperty"
  key_links:
    - from: "frontend/src/components/builder/StackRow.tsx"
      to: "frontend/src/components/builder/hooks/use-layer-map-sync.ts"
      via: "onToggleVisibility prop wired through UnifiedStackPanel → MapBuilderPage → handleToggleVisibility"
      pattern: "onToggleVisibility"
---

<objective>
Fix BUG-01: regular layer visibility eye toggle is a no-op. User can toggle a regular (non-basemap, non-sublayer) layer's visibility on/off and the map reflects the change immediately. Repro at `http://localhost:8080/maps/c868cc3a-a3a0-4714-b559-67b3f2b478e2` (Layer 1) no longer reproduces.

Purpose: Visibility toggle is the most-used affordance on the layer row; broken since unknown commit. User has cited a specific reproducible map URL.
Output: Fix in the wiring between StackRow.tsx onToggleVisibility prop and use-layer-map-sync.ts setLayoutProperty dispatch; vitest regression case proving the dispatch fires on each click.
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
<!-- From PATTERNS.md — current wiring of the visibility toggle chain. -->

From frontend/src/components/builder/StackRow.tsx (lines 235-253):
```tsx
<button
  type="button"
  aria-label={t('stackRow.toggleVisibility', { ... })}
  aria-pressed={layer.visible}
  onClick={(e) => {
    e.stopPropagation();
    onToggleVisibility(layer.id);
  }}
>
  {layer.visible ? <Eye ... /> : <EyeOff ... />}
</button>
```

From frontend/src/components/builder/hooks/use-layer-map-sync.ts (lines 68-93):
```ts
const handleToggleVisibility = useCallback(
  (layerId: string, visible?: boolean) => {
    const current = layersRef.current.find((l) => l.id === layerId);
    const nextVisible = visible !== undefined ? visible : !current?.visible;
    applyLayerUpdate(
      layerId,
      (l) => ({ ...l, visible: nextVisible }),
      (map) => {
        const newVis = nextVisible ? 'visible' : 'none';
        // ... 6 companion layer setLayoutProperty calls
      },
    );
  },
  [applyLayerUpdate],
);
```

From frontend/src/components/builder/hooks/use-builder-layers.ts (lines 218-244):
```ts
const layersRef = useRef(localLayers);
useLayoutEffect(() => { layersRef.current = localLayers; }, [localLayers]);
```
</interfaces>
</context>

<tasks>

<task type="checkpoint:orchestrator">
  <name>Task 1: Playwright MCP pre-fix repro</name>
  <files>(no files modified)</files>
  <read_first>
    - .planning/phases/1051-map-builder-polish-bug-sweep/1051-PATTERNS.md (BUG-01/02 root cause tracing sequence)
  </read_first>
  <action>
    Orchestrator drives Playwright MCP against the live `http://localhost:8080` stack. Steps: (1) Navigate to `http://localhost:8080/maps/c868cc3a-a3a0-4714-b559-67b3f2b478e2`. (2) Wait for builder to load, sidebar to render with ≥1 layer. (3) Locate "Layer 1" row in UnifiedStackPanel. (4) Locate the visibility eye button on that row (Eye icon when visible, EyeOff when hidden). (5) Click the eye button. (6) Capture: console logs, network calls (look for any PATCH to /api/maps/{id}/layers/{layerId}), and the layer's MapLibre `getLayoutProperty(layerId, 'visibility')` value via `mcp_browser_evaluate`. (7) Click again. Confirm pre-fix behavior: no MapLibre visibility change OR no observable map tile change. Record the layer ID and the exact handler chain that fails. Surface findings to orchestrator running scratch list for EMRG-01.
  </action>
  <verify>
    <automated>Playwright MCP screenshot of map showing tiles unchanged after 2 visibility toggle clicks; orchestrator records layer ID + observed handler-chain breakpoint.</automated>
  </verify>
  <acceptance_criteria>
    - Orchestrator confirms the visibility toggle is currently a no-op on the cited URL
    - Layer ID captured for use in regression test
    - Console + network output captured for root-cause analysis
    - Any incidental issues observed during repro added to scratch list for EMRG-01
  </acceptance_criteria>
  <done>Pre-fix behavior confirmed; root-cause hypothesis recorded for Task 2 trace.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Trace handler chain and fix the broken dispatch</name>
  <files>frontend/src/components/builder/hooks/use-layer-map-sync.ts, frontend/src/components/builder/hooks/use-builder-layers.ts, frontend/src/components/builder/UnifiedStackPanel.tsx, frontend/src/components/builder/StackRow.tsx</files>
  <read_first>
    - frontend/src/components/builder/StackRow.tsx (visibility button onClick handler around lines 235-253)
    - frontend/src/components/builder/UnifiedStackPanel.tsx (SortableStackRow prop pass-through around lines 151-218)
    - frontend/src/components/builder/hooks/use-builder-layers.ts (handleToggleVisibility delegation and layersRef stable-callback pattern around lines 218-244)
    - frontend/src/components/builder/hooks/use-layer-map-sync.ts (handleToggleVisibility dispatch chain lines 68-93, applyLayerUpdate guard lines 42-66)
    - frontend/src/pages/MapBuilderPage.tsx (UnifiedStackPanel props wiring — search for `onToggleVisibility`)
    - .planning/phases/1051-map-builder-polish-bug-sweep/1051-PATTERNS.md (BUG-01/02 root cause tracing sequence section)
  </read_first>
  <behavior>
    - Test 1: handleToggleVisibility from use-layer-map-sync.ts dispatches `map.setLayoutProperty('layer-{layerId}', 'visibility', 'none')` when called on a visible layer
    - Test 2: A second call dispatches `map.setLayoutProperty('layer-{layerId}', 'visibility', 'visible')` (round-trip)
    - Test 3: All 6 companion layer suffixes (`''`, `-outline`, `-label`, `-extrusion`, `-cluster`, `-cluster-count`) receive the setLayoutProperty when they exist in the map (test with mocked `map.getLayer` returning truthy)
    - Test 4: applyLayerUpdate early-exit (`if (!existing) return`) does NOT block valid updates — guard only fires for unknown layer IDs
  </behavior>
  <action>
    Trace `onToggleVisibility` from StackRow.tsx (line ~245) → SortableStackRow in UnifiedStackPanel.tsx (lines 151-218) → UnifiedStackPanel prop receipt → MapBuilderPage.tsx wiring. Per PATTERNS.md "Key Tracing Notes for Planner", the most likely root cause is a stale closure on `mapInstanceRef` in `use-layer-map-sync.ts` OR a missing `map.isStyleLoaded()` guard OR the layersRef.current lookup returns undefined (e.g., layer ID mismatch — `layer.id` vs `layer-{layer.id}` prefix). Confirm the actual break-point. Implement the minimum fix that restores the setLayoutProperty dispatch chain. Do NOT add new error toasts or refactor the hook architecture — symptom-fix only per REQUIREMENTS.md Out-of-Scope row 3. Update or add the vitest test file `frontend/src/components/builder/hooks/__tests__/use-layer-map-sync.test.ts` (create if missing — mirror the test setup pattern from `frontend/src/components/builder/hooks/__tests__/use-builder-layers.test.ts` or similar). Tests must fail BEFORE the fix and pass AFTER.
  </action>
  <verify>
    <automated>cd frontend && npx vitest run src/components/builder/hooks/__tests__/use-layer-map-sync.test.ts</automated>
  </verify>
  <acceptance_criteria>
    - `grep -n 'setLayoutProperty' frontend/src/components/builder/hooks/use-layer-map-sync.ts` returns ≥6 matches (one per companion layer suffix)
    - New/updated regression test asserts setLayoutProperty is called with 'none' on first toggle and 'visible' on second toggle
    - `cd frontend && npx tsc --noEmit` returns 0 errors
    - No new error-handling code added (symptom-fix only — root-cause is wiring, not error handling)
    - Diff to use-layer-map-sync.ts, use-builder-layers.ts, UnifiedStackPanel.tsx, and StackRow.tsx is minimal — only changes required to restore the dispatch chain
  </acceptance_criteria>
  <done>handleToggleVisibility setLayoutProperty dispatch chain restored; regression test fails on pre-fix HEAD and passes on post-fix.</done>
</task>

<task type="checkpoint:orchestrator">
  <name>Task 3: Playwright MCP post-fix re-verify + atomic commit</name>
  <files>(no files modified beyond commit)</files>
  <read_first>
    - .planning/phases/1051-map-builder-polish-bug-sweep/1051-PATTERNS.md
  </read_first>
  <action>
    Orchestrator drives Playwright MCP on fresh page reload: (1) Navigate to `http://localhost:8080/maps/c868cc3a-a3a0-4714-b559-67b3f2b478e2`. (2) Click Layer 1 visibility eye. (3) Confirm tiles disappear AND `map.getLayoutProperty('layer-{layerId}', 'visibility')` returns 'none'. (4) Click eye again. (5) Confirm tiles reappear AND visibility returns 'visible'. (6) Spot-check: basemap sublayer visibility toggle still works (preserved behavior from v1009 POL-multi-select). After MCP verify passes, create atomic commit. Use only the `frontend/src/components/builder/hooks/use-layer-map-sync.ts`, `frontend/src/components/builder/hooks/use-builder-layers.ts`, `frontend/src/components/builder/UnifiedStackPanel.tsx`, `frontend/src/components/builder/StackRow.tsx`, and the regression test file as the commit set. Commit message: `fix(builder): layer visibility toggle now dispatches to maplibre (BUG-01)`.
  </action>
  <verify>
    <automated>git log --oneline -1 && git show --stat HEAD</automated>
  </verify>
  <acceptance_criteria>
    - Playwright MCP confirms visibility toggle works on regular layer (tiles disappear/reappear)
    - Basemap sublayer visibility regression check passes
    - Commit exists with subject line `fix(builder): layer visibility toggle now dispatches to maplibre (BUG-01)`
    - `git diff HEAD~1 HEAD --stat` shows only the in-scope files modified
  </acceptance_criteria>
  <done>BUG-01 fix verified live + committed atomically.</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| client→MapLibre dispatch | UI handler converts user click into `map.setLayoutProperty` calls; no user-supplied data crosses this boundary |
| no API surface added | Fix is entirely client-side wiring — no new endpoint, no new request shape |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-1051-01 | Tampering | use-layer-map-sync.ts setLayoutProperty calls | accept | layerId comes from in-app state (not user input); cannot be tampered to reference an attacker-chosen MapLibre layer |
| T-1051-02 | Denial of Service | rapid visibility toggle | accept | MapLibre dispatch is debounced by rAF in v1010 coalesceFrame; no new throttling needed |
</threat_model>

<verification>
- Playwright MCP confirms visibility toggle works on regular layer at the cited repro URL
- Vitest regression case fails before fix and passes after
- `npx tsc --noEmit` returns 0 errors
- No regression to basemap sublayer or bulk-visibility toggle behavior
</verification>

<success_criteria>
- Clicking the visibility eye on a regular layer at the repro URL toggles MapLibre visibility between 'visible' and 'none' on every click
- Vitest regression case fails before fix and passes after fix
- No regression to basemap-sublayer visibility toggles or v1009 POL-multi-select bulk visibility toggle
- Atomic commit on main with subject `fix(builder): layer visibility toggle now dispatches to maplibre (BUG-01)`
</success_criteria>

<output>
Create `.planning/phases/1051-map-builder-polish-bug-sweep/1051-01-SUMMARY.md` when done with: root-cause analysis, fix description, files modified, test result, MCP verification screenshots/notes.
</output>
