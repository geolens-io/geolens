---
phase: 1051
plan: 06
type: execute
wave: 6
depends_on: ["1051-05"]
files_modified:
  - frontend/src/components/builder/UnifiedStackPanel.tsx
  - frontend/src/components/builder/BasemapGroupRow.tsx
  - frontend/src/components/builder/hooks/use-builder-layers.ts
  - frontend/src/components/builder/hooks/use-builder-save.ts
  - frontend/src/components/builder/map-sync.ts
  - frontend/src/components/builder/__tests__/UnifiedStackPanel.basemap-drag.test.tsx
autonomous: false
requirements: [UX-03]
tags: [builder, ux, dnd, basemap-drag, saved-map-persistence]

must_haves:
  truths:
    - "Basemap group row participates in the UnifiedStackPanel DnD sort (no longer locked to bottom)"
    - "Dragging the basemap group moves ALL basemap sublayers as a single unit (group-drag semantics from sketch 007 A preserved)"
    - "Basemap position is encoded in MapBasemapConfig.basemap_position ('top' | 'bottom' — derived from layer-order index at save time per Out-of-Scope row 6: no new schema fields on the backend MapDoc)"
    - "Saved-map round-trip preserves basemap position: drag to top → save → reload → still at top"
    - "MapLibre layer order reflects the drag: basemap at top renders ABOVE data geometry layers; basemap at bottom renders BELOW (existing behavior)"
    - "Legacy maps without explicit basemap_position default to 'bottom' (no regression)"
    - "Drag is disabled during multi-selection mode (gate on !isMultiSelectionActive per UI-SPEC cross-plan check)"
  artifacts:
    - path: "frontend/src/components/builder/UnifiedStackPanel.tsx"
      provides: "BasemapGroupRowWrapper uses useSortable (mirrors FolderGroupRowWrapper); basemap id added to sortableIds"
      contains: "useSortable"
    - path: "frontend/src/components/builder/BasemapGroupRow.tsx"
      provides: "Real GripVertical button replacing hidden span (BasemapGroupRow.tsx:107)"
      contains: "GripVertical"
    - path: "frontend/src/components/builder/hooks/use-builder-save.ts"
      provides: "Save flow encodes basemap_position in MapBasemapConfig before PATCH"
      contains: "basemap_position"
    - path: "frontend/src/components/builder/map-sync.ts"
      provides: "reorderDataGeometry or reorderBasemapLabels augmented so basemap fill/raster layers move ABOVE data when basemap_position='top'"
      contains: "moveLayer"
  key_links:
    - from: "UnifiedStackPanel.tsx BasemapGroupRowWrapper"
      to: "@dnd-kit/sortable useSortable"
      via: "Same hook shape as FolderGroupRowWrapper (UnifiedStackPanel.tsx:312-389)"
      pattern: "useSortable"
    - from: "use-builder-save.ts save flow"
      to: "MapBasemapConfig.basemap_position field"
      via: "Derive from layer-order index where basemap-group appears (top vs bottom of unified stack)"
      pattern: "basemap_position"
---

<objective>
Fix UX-03: Basemap row is draggable in the layer order. User can position the basemap at top of stack (so basemap context renders ABOVE data layers — useful for 3D maps showing elevation through a translucent basemap) OR bottom (default 2D map). Drag preserves the basemap-as-group semantics (sublayers move with parent). Saved-map JSON encodes the basemap position via a new `basemap_position: 'top' | 'bottom'` field on the existing `MapBasemapConfig` jsonb (per PATTERNS.md Plan 06 recommendation — no backend MapDoc schema migration).

Per PATTERNS.md Plan 06 + critical_planning_directive #3: lift `BasemapGroupRowWrapper` from `useDroppable` to `useSortable` (mirror `FolderGroupRowWrapper` at UnifiedStackPanel.tsx:312-389). Replace the hidden grip `<span>` at BasemapGroupRow.tsx:107 with a real `<button>` containing a `GripVertical` icon, copying the pattern from `FolderGroupRow.tsx:183-197`. Persistence: prefer extending the existing `MapBasemapConfig` jsonb with a single `basemap_position` key (no migration) over a new backend column.

Purpose: 3D maps need basemap rendered above data; current basemap-locked-to-bottom blocks the use case.
Output: Drag-enabled basemap row; group-as-unit drag; saved-map round-trip; MapLibre layer order respects position; regression test covering drag + persistence.
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
<!-- From PATTERNS.md — current basemap droppable + reference sortable wrapper + grip pattern. -->

From frontend/src/components/builder/UnifiedStackPanel.tsx (lines 244-287 — current BasemapGroupRowWrapper uses useDroppable):
```tsx
const BasemapGroupRowWrapper = memo(function BasemapGroupRowWrapper({...}) {
  const { setNodeRef, isOver } = useDroppable({
    id: group.id,
    data: { source: 'stack', kind: 'basemap-group' },
  });
  ...
  return (
    <div ref={setNodeRef} data-basemap-drop-target={isOver ? 'true' : undefined}>
      <BasemapGroupRow ... dragHandleProps={{ attributes: {} as DraggableAttributes, listeners: undefined, setActivatorNodeRef: NOOP }} ... />
    </div>
  );
});
```

From frontend/src/components/builder/UnifiedStackPanel.tsx (lines 312-389 — reference FolderGroupRowWrapper uses useSortable):
```tsx
const FolderGroupRowWrapper = memo(function FolderGroupRowWrapper({...}) {
  const { attributes, listeners, setActivatorNodeRef, setNodeRef, transform, transition, isDragging, isOver } = useSortable({ id: layer.id });
  ...
  return (
    <div ref={setNodeRef} style={{ transform: CSS.Transform.toString(transform), transition }} ...>
      <FolderGroupRow ... dragHandleProps={{ attributes, listeners, setActivatorNodeRef }} ... />
    </div>
  );
});
```

From frontend/src/components/builder/BasemapGroupRow.tsx (line 107 — current hidden grip):
```tsx
{/* Cell 2: Grip — hidden: basemap group is not user-draggable (AUD-04) */}
<span aria-hidden="true" className="h-[14px] w-[14px]" />
```

From frontend/src/components/builder/FolderGroupRow.tsx (lines 183-197 — reference real grip button):
```tsx
<button
  ref={dragHandleProps.setActivatorNodeRef}
  type="button"
  {...dragHandleProps.attributes}
  {...dragHandleProps.listeners}
  aria-label={t('stackRow.dragHandle', { defaultValue: 'Drag to reorder {{name}}', name: groupName })}
  className="flex items-center justify-center cursor-grab opacity-35 group-hover/row:opacity-70 text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring rounded active:cursor-grabbing"
  onPointerDown={(e) => e.stopPropagation()}
  onClick={(e) => e.stopPropagation()}
>
  <GripVertical className="h-3.5 w-3.5" aria-hidden="true" />
</button>
```

From frontend/src/components/builder/UnifiedStackPanel.tsx (lines 722-730 — current sortableIds excludes basemap):
```tsx
const sortableIds = useMemo(() => {
  // basemap-group is intentionally excluded (AUD-04 comment) — UX-03 reverses this
  return [...folderIds, ...layerIds];
}, [folderIds, layerIds]);
```

From frontend/src/components/builder/map-sync.ts (lines 757-776 — reorderDataGeometry over data layers; basemap style layers handled by reorderBasemapLabels at 188-205):
```ts
// Existing reorder loop applies to 'layer-{id}' prefixed entries — does NOT touch
// basemap-loaded style layers (which have other prefixes like 'fill-extrusion-*').
// UX-03 must extend or wrap this to moveLayer the basemap fill/raster ABOVE data when basemap_position='top'.
```
</interfaces>
</context>

<tasks>

<task type="checkpoint:orchestrator">
  <name>Task 1: Playwright MCP pre-fix capture</name>
  <files>(no files modified)</files>
  <read_first>
    - .planning/phases/1051-map-builder-polish-bug-sweep/1051-PATTERNS.md (Plan 06 — full PATTERNS.md Plan 06 section)
    - .planning/phases/1051-map-builder-polish-bug-sweep/1051-UI-SPEC.md (UX-03 contract)
  </read_first>
  <action>
    Orchestrator drives Playwright MCP. Steps: (1) Open a map. (2) Try to drag the basemap group row in the sidebar. (3) Confirm: no drag affordance is visible (grip is invisible/hidden); pointerdown on the basemap row does not start a drag. (4) Inspect the basemap row DOM — confirm `Cell 2: Grip` is the `aria-hidden span` at the current path. (5) Open the saved map JSON via DevTools (network response from GET /api/maps/{id}) — confirm there is NO `basemap_position` key on the basemap config currently. (6) Screenshot stack with basemap at bottom. Add incidental issues to scratch list for EMRG-01.
  </action>
  <verify>
    <automated>Playwright MCP captures: basemap row is not draggable; saved-map JSON does not yet have basemap_position field.</automated>
  </verify>
  <acceptance_criteria>
    - Pre-fix confirms basemap row is NOT draggable
    - Saved-map JSON shape captured for backend confirmation that basemap_position field does not exist
  </acceptance_criteria>
  <done>Pre-fix state captured.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Lift BasemapGroupRowWrapper to useSortable + add real GripVertical button + sortableIds</name>
  <files>frontend/src/components/builder/UnifiedStackPanel.tsx, frontend/src/components/builder/BasemapGroupRow.tsx, frontend/src/components/builder/__tests__/UnifiedStackPanel.basemap-drag.test.tsx</files>
  <read_first>
    - frontend/src/components/builder/UnifiedStackPanel.tsx (BasemapGroupRowWrapper lines 244-287, FolderGroupRowWrapper lines 312-389, sortableIds lines 722-730, DndContext setup)
    - frontend/src/components/builder/BasemapGroupRow.tsx (hidden grip span line 107, top imports for Lucide icons)
    - frontend/src/components/builder/FolderGroupRow.tsx (real grip button lines 183-197 + GripVertical import)
    - .planning/phases/1051-map-builder-polish-bug-sweep/1051-PATTERNS.md (Plan 06 — Fix strategy steps 1-5)
    - .planning/phases/1051-map-builder-polish-bug-sweep/1051-UI-SPEC.md (UX-03 drag handle + multi-select gate)
  </read_first>
  <behavior>
    - Test 1: BasemapGroupRowWrapper renders without error when wrapped in DndContext + SortableContext (smoke)
    - Test 2: Drag handle exists on BasemapGroupRow when isMultiSelectionActive=false (query a button by aria-label /drag.*reorder/i)
    - Test 3: When isMultiSelectionActive=true, the drag listener is suppressed (button is non-functional OR not rendered — choose one per UI-SPEC)
    - Test 4: BasemapGroupRow grip uses GripVertical Lucide icon
    - Test 5: sortableIds includes the basemap group id
  </behavior>
  <action>
    Edit `frontend/src/components/builder/UnifiedStackPanel.tsx`: (a) refactor `BasemapGroupRowWrapper` (current lines 244-287) to use `useSortable({ id: group.id })` instead of `useDroppable` — copy the hook destructure shape from `FolderGroupRowWrapper` (lines 312-389): `attributes, listeners, setActivatorNodeRef, setNodeRef, transform, transition, isDragging, isOver`. Apply `style={{ transform: CSS.Transform.toString(transform), transition }}`. Pass real `dragHandleProps={{ attributes, listeners, setActivatorNodeRef }}` to BasemapGroupRow. (b) Update sortableIds at lines ~722-730 to INCLUDE the basemap group id (e.g., `[basemapGroup.id, ...folderIds, ...layerIds]` — choose insertion position consistent with how the panel renders). Remove or update the AUD-04 comment. (c) Gate the drag listener on `!isMultiSelectionActive` per UI-SPEC §"Cross-Plan Visual Conflict Check". One implementation: pass `isMultiSelectionActive` through to BasemapGroupRow and conditionally spread the listeners on the grip button. (d) Ensure the existing drop-target semantic (`data-basemap-drop-target`) is preserved or removed cleanly — useSortable's isOver replaces the useDroppable isOver.
    
    Edit `frontend/src/components/builder/BasemapGroupRow.tsx`: (a) ensure `GripVertical` is imported from `lucide-react`. (b) Replace the hidden span at line 107 with the real grip button JSX (copy verbatim from `FolderGroupRow.tsx:183-197`, with translation key adapted to e.g. `t('basemapGroup.dragHandle', { defaultValue: 'Drag to reorder basemap' })`). When `isMultiSelectionActive` is true, do NOT spread the listeners onto the button (or render a disabled button with reduced opacity per UI-SPEC). (c) Add the i18n key `basemapGroup.dragHandle` to all 4 locales (en/de/es/fr) under `builder.json` — match parity.
    
    Create `frontend/src/components/builder/__tests__/UnifiedStackPanel.basemap-drag.test.tsx` with the 5 behavior tests. Use the existing UnifiedStackPanel test harness as a reference (or render BasemapGroupRow + FolderGroupRowWrapper wrapped in DndContext/SortableContext fixtures).
  </action>
  <verify>
    <automated>cd frontend && npx vitest run src/components/builder/__tests__/UnifiedStackPanel.basemap-drag.test.tsx && cd frontend && npx tsc --noEmit</automated>
  </verify>
  <acceptance_criteria>
    - `grep -n 'useSortable' frontend/src/components/builder/UnifiedStackPanel.tsx | grep -i basemap` returns ≥1 match (BasemapGroupRowWrapper now sortable)
    - `grep -n 'GripVertical' frontend/src/components/builder/BasemapGroupRow.tsx` returns ≥1 match (real icon in grip cell)
    - sortableIds at UnifiedStackPanel.tsx includes the basemap group id
    - The AUD-04 hidden span at line 107 of BasemapGroupRow.tsx is removed/replaced
    - i18n key `basemapGroup.dragHandle` added to all 4 locales
    - vitest tests pass
    - `cd frontend && npx tsc --noEmit` returns 0 errors
  </acceptance_criteria>
  <done>Basemap row is now sortable and has a real grip button; tests green; multi-select gate honored.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 3: Encode basemap_position in MapBasemapConfig + reorder MapLibre layers</name>
  <files>frontend/src/components/builder/hooks/use-builder-save.ts, frontend/src/components/builder/hooks/use-builder-layers.ts, frontend/src/components/builder/map-sync.ts</files>
  <read_first>
    - frontend/src/components/builder/hooks/use-builder-save.ts (save flow around line 439)
    - frontend/src/components/builder/hooks/use-builder-layers.ts (handleReorder line 249-259, setBasemapConfig line 114-120)
    - frontend/src/components/builder/map-sync.ts (reorderDataGeometry line 757-776, reorderBasemapLabels line 188-205, applyBasemapConfigToMap line 222)
    - frontend/src/types/api.ts (find MapBasemapConfig type — grep `MapBasemapConfig` in frontend/src)
    - .planning/phases/1051-map-builder-polish-bug-sweep/1051-PATTERNS.md (Plan 06 — Saved-map round-trip section)
  </read_first>
  <behavior>
    - Test 1: On save, if basemap-group's index in localLayers is 0 (top), MapBasemapConfig.basemap_position = 'top' is sent in the PATCH payload
    - Test 2: If basemap-group's index is the last position (bottom — typical default), basemap_position = 'bottom'
    - Test 3: On load, a saved map with basemap_position='top' positions the basemap-group row at top of unified stack
    - Test 4: Legacy maps (no basemap_position field) default to 'bottom'
    - Test 5: After basemap reorder, map-sync.ts reorderDataGeometry (or augmented helper) ensures basemap MapLibre layers are moved ABOVE data layers when position='top' (assert via mocked map.moveLayer with `null` beforeId for top)
  </behavior>
  <action>
    (a) `frontend/src/types/api.ts` (or wherever `MapBasemapConfig` is defined): add optional `basemap_position?: 'top' | 'bottom'` field. This is a TypeScript-only change for now since the backend stores the field as jsonb — no migration. (b) `frontend/src/components/builder/hooks/use-builder-save.ts` (around line 439): when building the PATCH payload, derive `basemap_position` from the index of the basemap-group entry in the unified stack — if it appears at index 0, set 'top'; otherwise 'bottom'. Include it on `basemap_config.basemap_position` in the request body. (c) `frontend/src/components/builder/hooks/use-builder-layers.ts` (after the initial load + normalization, around the `setBasemapConfig` defaults): if the loaded `basemap_config.basemap_position` is undefined, default to 'bottom' (legacy compat). Propagate the loaded position into the unified-stack render order. (d) `frontend/src/components/builder/map-sync.ts`: augment `reorderDataGeometry` (line 757-776) OR add a new sibling helper that runs AFTER the data layer reorder pass and, if `basemap_position='top'`, walks the basemap-loaded style layers (use the style ids surfaced by `applyBasemapConfigToMap`) and calls `map.moveLayer(basemapLayerId)` with NO beforeId so they end up at the top of the MapLibre stack. If 'bottom' (default), leave the existing order alone. (e) Add unit tests for the 5 behaviors. Mock `mapInstance.moveLayer` and `mapInstance.getStyle` to verify the layer order intent.
    
    NOTE: per Out-of-Scope row 6, no new backend schema field on `MapDoc`. The `MapBasemapConfig` jsonb already accepts free-form keys — adding `basemap_position` does not require a migration.
  </action>
  <verify>
    <automated>cd frontend && npx vitest run src/components/builder/hooks/__tests__/use-builder-save.test.ts 2>/dev/null; cd frontend && npx vitest run src/components/builder/__tests__/map-sync.test.ts 2>/dev/null; cd frontend && npx tsc --noEmit</automated>
  </verify>
  <acceptance_criteria>
    - `grep -n 'basemap_position' frontend/src/components/builder/hooks/use-builder-save.ts frontend/src/components/builder/hooks/use-builder-layers.ts frontend/src/components/builder/map-sync.ts` returns ≥3 matches (one per file)
    - MapBasemapConfig type includes optional basemap_position
    - Legacy default of 'bottom' verified
    - MapLibre moveLayer dispatched when basemap_position='top'
    - `cd frontend && npx tsc --noEmit` returns 0 errors
    - No backend schema files modified (`git diff --name-only` should NOT include backend/)
  </acceptance_criteria>
  <done>basemap_position round-trips through save + load; MapLibre order respects position.</done>
</task>

<task type="checkpoint:orchestrator">
  <name>Task 4: Playwright MCP post-fix re-verify (drag + persistence + render order) + atomic commit</name>
  <files>(no files modified beyond commit)</files>
  <read_first>
    - .planning/phases/1051-map-builder-polish-bug-sweep/1051-PATTERNS.md
    - .planning/phases/1051-map-builder-polish-bug-sweep/1051-UI-SPEC.md
  </read_first>
  <action>
    Orchestrator drives Playwright MCP. Steps: (1) Open a map (preferably one with terrain or 3D extrusion data layers — falls back to any saved map). (2) Hover the basemap row — confirm GripVertical icon is visible on hover. (3) Drag the basemap row to the top of the stack. (4) Confirm all basemap sublayers move with the basemap (group-drag semantics — sublayers do NOT detach). (5) Use `mcp_browser_evaluate` to read `map.getStyle().layers` order — confirm basemap fill/raster layer IDs appear AFTER data-prefixed layer IDs (i.e., basemap rendered above data in MapLibre's bottom-up stack). (6) Save the map (click Save button or trigger autosave). Confirm PATCH /api/maps/{id} includes `basemap_position: 'top'` in the payload. (7) Reload the page. Confirm basemap row is at top of stack again. (8) Confirm v1010.2 SF-08 basemap latch (3000ms save-flow window) is not regressed — no false-positive Basemap toast on save. (9) Drag basemap back to bottom; save; reload; confirm bottom position persists. (10) Spot-check: drag is disabled in multi-selection mode (shift-click ≥2 data layers, then attempt to drag basemap — confirm pointer cursor shows not-allowed OR grip non-functional). After MCP verify passes, create atomic commit with subject: `feat(builder): basemap row is draggable in layer order with saved-map persistence (UX-03)`. Stage only the in-scope files.
  </action>
  <verify>
    <automated>git log --oneline -1 && git show --stat HEAD</automated>
  </verify>
  <acceptance_criteria>
    - Playwright MCP confirms basemap row drag + group-as-unit semantics
    - PATCH payload includes basemap_position
    - Reload preserves position
    - MapLibre layer order changes match position
    - v1010.2 SF-08 basemap latch not regressed
    - Multi-select mode disables drag
    - Commit exists with subject `feat(builder): basemap row is draggable in layer order with saved-map persistence (UX-03)`
    - `git diff HEAD~1 HEAD --stat` shows only the 6 in-scope files modified
  </acceptance_criteria>
  <done>UX-03 fix verified live + committed atomically.</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| client→API PATCH | Client sends MapBasemapConfig with new basemap_position field; backend treats as opaque jsonb; no schema validation issue |
| client→MapLibre | moveLayer calls operate on basemap-style-loaded layer IDs; layer IDs from MapLibre internal style, not user input |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-1051-06-jsonb | Tampering | basemap_config jsonb new key | accept | Backend stores opaque jsonb; no validation surface added; legacy maps default 'bottom' safely |
| T-1051-06-mvOrder | Denial of Service | repeated drag triggering many moveLayer calls | accept | rAF coalesce from v1010 handles this; existing pattern |
</threat_model>

<verification>
- Playwright MCP confirms full drag + save + reload round-trip
- Vitest covers save payload + load default + MapLibre order intent
- `npx tsc --noEmit` returns 0 errors
- v1010.2 SF-04 source dedupe and SF-08 basemap latch not regressed
- No backend schema migration files added
</verification>

<success_criteria>
- Basemap row participates in unified stack DnD reorder
- Dragging the basemap row moves all sublayers as a unit
- Saved-map round-trip preserves basemap position
- MapLibre layer order reflects the drag (top → basemap above data; bottom → basemap below data)
- Vitest regression confirms persistence + group-drag semantics
- Legacy maps default to 'bottom'
- Drag disabled in multi-selection mode
- Atomic commit on main with subject `feat(builder): basemap row is draggable in layer order with saved-map persistence (UX-03)`
</success_criteria>

<output>
Create `.planning/phases/1051-map-builder-polish-bug-sweep/1051-06-SUMMARY.md` with: schema decision (basemap_position on MapBasemapConfig jsonb), files modified, MapLibre reorder strategy, test result, MCP screenshots showing drag + render-order changes.
</output>
