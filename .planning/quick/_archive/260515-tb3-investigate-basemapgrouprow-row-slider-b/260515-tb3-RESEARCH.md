---
quick_id: 260515-tb3
type: quick-task-research
status: complete
researched: 2026-05-15
mode: investigation-only-no-implementation
confidence: HIGH
---

# Quick Task 260515-tb3: BasemapGroupRow + Master Opacity — Investigation Findings

**Researched:** 2026-05-15
**Confidence:** HIGH (live Playwright verification + source trace + backend schema check)

---

## Summary

The two concerns raised in CONTEXT.md are BOTH real and BOTH confirmed by live + source evidence.

| Concern | Status | Evidence |
|---|---|---|
| **C1: Row slider is broken (no-op)** | CONFIRMED | Playwright keyboard + synthetic + real-mouse drags all left `aria-valuenow="1"` unchanged. Source-level trace shows `applyLayerUpdate("basemap-group", …)` short-circuits because no layer with that id exists. |
| **C2: Master opacity not persisted (Phase-1038 TODO)** | CONFIRMED | Master slider DOES move runtime (1 → 0.55 in test) but `Save` stays "Saved" → no dirty flag. Backend `BasemapConfig` schema has NO `opacity` field AND `extra="forbid"` would reject it. |

These are independent: C1 is a broken control; C2 is missing persistence.

---

## C1: Row slider is broken — evidence

### Live Playwright verification (test map dfbe4fd8-…)

| Test | Result |
|---|---|
| Initial state: `aria-label="Opacity for Basemap · Positron"` | `aria-valuenow="1"`, focused after `.focus()`, `tabindex="0"`, no `disabled` attr |
| Press `Home` (jump to min) | value stayed at `"1"`, no change |
| Press `ArrowLeft` (decrement by step=0.05) | value stayed at `"1"`, no change |
| Synthetic `pointerdown/move/up` drag thumb 30 px left | value stayed at `"1"`, no change |
| **Real Playwright `page.mouse.down/move/up`** drag thumb 30 px left | value stayed at `"1"`, no change, Save stayed "Saved" |

The slider thumb has focus, accepts hover/keyboard navigation, but the value never changes. **Evidence is incontrovertible.**

### Source-level root cause

**`BasemapGroupRow.tsx:188-202`** — controlled Radix Slider:
```tsx
<Slider
  aria-label={t('stackRow.opacitySlider', { name: rowName })}
  value={[safeOpacity]}            // controlled
  min={0} max={1} step={0.05}
  onValueChange={([value]) => {
    onOpacityChange(groupId, ...);  // groupId === "basemap-group"
  }}
/>
```

**`UnifiedStackPanel.tsx:282`** forwards `onOpacityChange={onOpacityChange}` (the top-level prop) into `BasemapGroupRow`.

**`MapBuilderPage.tsx:230`** wires `onOpacityChange: layers.handleOpacityChange` (from `use-builder-layers.ts:944` re-export of `use-layer-map-sync.ts`).

**`use-layer-map-sync.ts:185-220`** — `handleOpacityChange(layerId, newOpacity)`:
```ts
applyLayerUpdate(layerId, (l) => ({ ...l, opacity: newOpacity }), (map, layer) => { ... });
```

**`use-layer-map-sync.ts:41-61`** — `applyLayerUpdate`:
```ts
setLocalLayers((prev) =>
  prev.map((l) => {
    if (l.id !== layerId) return l;   // <-- "basemap-group" never matches
    const next = updater(l);
    updated = next;
    return next;
  }),
);
setHasUnsavedChanges(true);             // <-- still called!
if (!applyFn) return;
const map = mapInstanceRef.current;
if (!map || !map.isStyleLoaded()) return;
if (!updated) return;                   // <-- updated stays undefined
applyFn(map, updated);                  // <-- skipped
```

### Failure mode trace

1. User drags row slider → Radix calls `onValueChange([0.55])`.
2. Component calls `onOpacityChange("basemap-group", 0.55)`.
3. `handleOpacityChange("basemap-group", 0.55)` calls `applyLayerUpdate("basemap-group", updater, applyFn)`.
4. Inside `setLocalLayers`: `prev.map(l => l.id !== "basemap-group" ? l : updater(l))` — no layer matches the synthetic id, every layer is returned unchanged. `updated` stays `undefined`.
5. `setHasUnsavedChanges(true)` IS called — but since `localLayers` reference didn't actually change content, React's downstream setLocalLayers may bail out via reference equality (depends on implementation).
6. Map paint side-effect skipped because `updated` is undefined.
7. Slider snaps back to `safeOpacity` (still 1) because the controlled `value={[safeOpacity]}` prop never updated.

### Secondary observation

The `setHasUnsavedChanges(true)` call at `use-layer-map-sync.ts:52` runs unconditionally — even when `applyLayerUpdate` is called with a non-existent layerId. In live testing the Save button stayed "Saved" through multiple drag attempts on the broken row slider, so React likely bails out via referential equality of `localLayers`. Worth a defensive guard (only set dirty when the layer actually exists), but not strictly required for the row-slider fix.

---

## C2: Master opacity not persisted — evidence

### Live Playwright verification

| Test | Result |
|---|---|
| Click basemap row → editor opens | OK; "Master opacity" slider visible at value=1 |
| Drag master slider thumb 150 px left (real Playwright mouse) | `aria-valuenow="1"` → `"0.55"` (works runtime) |
| Save button after drag | text stays "SavedSaved", aria-label "Save (⌘S)" → **NOT marked dirty** |
| Visual map effect | not screenshot-checked, but Phase-1038 TODO + source flow indicate runtime visual change should occur via setMasterOpacity → BasemapGroupEditorScene re-render |

### Source-level confirmation

**`MapBuilderPage.tsx:755-761`** — explicit TODO:
```tsx
onMasterOpacityChange={(opacity) => {
  setMasterOpacity(opacity);
  // TODO(Phase 1038): persist masterOpacity via basemap_config.opacity field
  // (requires backend MapBasemapConfig schema addition). Spreading `opacity`
  // directly into basemapConfig bypasses the type system and is stripped on
  // the next API round-trip, so markDirty() is omitted until persistence is wired.
}}
```

**`MapBuilderPage.tsx:258`** — `const [masterOpacity, setMasterOpacity] = useState(1);` (local React state, not in localLayers, never POSTed).

**`MapBuilderPage.tsx:469`** — `setMasterOpacity(1);` is reset to 1 on map load — confirms there's no persistence read-back either.

### Backend schema check (the Phase-1038 blocker)

**`backend/app/modules/catalog/maps/schemas.py:182-209`** — `BasemapConfig`:
```python
class BasemapConfig(BaseModel):
    label_mode: BasemapLabelMode = ...
    road_visibility: BasemapSublayerVisibility = ...
    boundary_visibility: BasemapSublayerVisibility = ...
    building_visibility: bool = ...
    land_water_tone: BasemapLandWaterTone = ...
    relief_contrast: BasemapReliefContrast | None = ...
    
    model_config = ConfigDict(extra="forbid")   # <-- rejects unknown keys
```

**No `opacity` field. `extra="forbid"`** means the backend will 422 any payload that includes `basemap_config: { opacity: 0.55 }`. So the frontend cannot persist master opacity even if it tried — the Phase-1038 TODO is real and the backend schema is the prerequisite.

### Estimated cost of Path B (full persistence fix)

- Add `opacity: float = Field(default=1.0, ge=0.0, le=1.0, description="...")` to `BasemapConfig`.
- Alembic migration: NONE — `BasemapConfig` is stored in a JSONB column (`maps.basemap_config`) so no DDL is needed.
- Frontend: replace the TODO body with `setMasterOpacity(opacity); layers.markDirty();` and add `opacity: masterOpacity` to the `basemap_config` payload sent on save.
- Frontend: read `mapData.basemap_config?.opacity ?? 1` on load and seed `setMasterOpacity` from it (replace the `setMasterOpacity(1)` reset at line 469).
- Tests: add an integration test for round-trip basemap opacity (POST → GET).
- Map runtime: confirm BasemapGroupEditorScene already applies masterOpacity to the rendered basemap (it appears to — slider drag changed `aria-valuenow` and the slider was controlled-component-stable, suggesting setMasterOpacity does propagate visually within the session).

**Net: ~30-50 LOC across backend + frontend + 1 test. Low-medium risk; pure additive change.**

---

## Decision Matrix

| Path | Description | Closes C1? | Closes C2? | Cost | Risk | Recommended? |
|---|---|---|---|---|---|---|
| **A** | Remove row slider only (mirror 260515-rdn/sqf) | YES | NO | LOW (~−25 LOC) | LOW | **YES** — clean, consistent with prior 2 tasks, removes a broken control, no backend dependency |
| **B** | Remove row slider AND ship master-opacity persistence | YES | YES | MEDIUM (~+30-50 LOC across backend + frontend + test) | LOW-MEDIUM (additive backend field, JSONB so no migration) | If user wants full closure in one shot, recommended |
| **C** | Keep row slider, rewire it to call `setMasterOpacity` instead of `handleOpacityChange` | NO (still redundant) | NO | LOW | LOW | NOT recommended — fixes the wiring bug but keeps redundancy and persistence gap |
| **D** | Defer entirely, document as known issues | NO | NO | NONE | NONE | NOT recommended — leaves a confirmed-broken control in production UI |

### Recommendation

**Path A** as the immediate cleanup (mirrors 260515-rdn/sqf exactly; closes the row-slider redundancy + removes a broken control), with Path B's master-opacity persistence as a separately-scoped follow-up that touches the backend.

**Why split:** Path A is a 5-minute mechanical change with the established playbook. Path B is a backend schema addition that should go through its own discuss/plan cycle (esp. for migration ordering, default behavior on load, and round-trip testing). Bundling them risks slowing the cleanup behind a feature.

If user prefers single-shot closure, Path B is also low risk because: no Alembic DDL (JSONB field), Pydantic field is additive, frontend wire-up is 2 lines + 1 test.

---

## What this investigation did NOT do

- **No code changes.** Per CONTEXT.md mode = `investigation-only-no-implementation`.
- **No PLAN.md.** Will be created by user-directed follow-up task.
- **No fix to the unconditional `setHasUnsavedChanges(true)` in `applyLayerUpdate`.** This is a defensive-cleanup opportunity (only set dirty when a layer was actually updated) but was not in scope. Worth flagging for inclusion if Path A or Path B is taken.

---

## Files inspected

- `frontend/src/components/builder/BasemapGroupRow.tsx` (lines 85-202)
- `frontend/src/components/builder/BasemapGroupEditorScene.tsx` (lines 195-242)
- `frontend/src/components/builder/UnifiedStackPanel.tsx` (lines 268-289 BasemapGroupRowWrapper instantiation)
- `frontend/src/components/builder/hooks/use-layer-map-sync.ts` (lines 41-61, 185-237)
- `frontend/src/components/builder/hooks/use-builder-layers.ts` (line 944, 980)
- `frontend/src/pages/MapBuilderPage.tsx` (lines 230, 258, 469, 745-769)
- `frontend/src/components/ui/slider.tsx` (full — confirmed Radix Slider primitive, controlled)
- `backend/app/modules/catalog/maps/schemas.py` (lines 182-210 BasemapConfig schema)

## Live verification

- http://localhost:8080/maps/dfbe4fd8-56a0-46d0-a155-3256d2c35d37 (test map, authenticated)
- 4 row-slider interaction tests (keyboard Home, ArrowLeft, synthetic pointer, real Playwright mouse) — all confirmed broken
- 1 master-opacity drag test — confirmed runtime works, persistence does not
