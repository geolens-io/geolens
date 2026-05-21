---
quick_id: 260515-tb3
type: quick-task-context
status: investigation-only
gathered: 2026-05-15
mode: research-only-no-implementation
predecessors: 260515-rdn, 260515-sqf
---

# Quick Task 260515-tb3: BasemapGroupRow + Master Opacity Investigation — Context

**Gathered:** 2026-05-15
**Status:** Investigation only — produce findings, do NOT change code
**Predecessors:** 260515-rdn (StackRow row slider removed), 260515-sqf (FolderGroupRow row slider removed)

<domain>
## Task Boundary

After 260515-rdn and 260515-sqf removed the redundant per-row Opacity slider from non-group layer rows and folder-group rows, the **BasemapGroupRow** is the last row type that still renders a 60×6 px Opacity slider in its row body. Surface inspection during the audit raised TWO concerns specific to this row that did NOT apply to its siblings:

### Concern 1: Row slider may be wired to a no-op or unexpected path
- `BasemapGroupRow.tsx:200` calls `onOpacityChange(groupId, value)` where `groupId === "basemap-group"`.
- The `handleOpacityChange(layerId, opacity)` handler in `use-layer-map-sync.ts:185` writes `layer.opacity` AND mutates map paint properties via `applyLayerUpdate(layerId, ...)`.
- **The synthetic ID `"basemap-group"` is NOT a real layer in the layers store** (basemap is a separate config, `MapBasemapConfig`, not part of the layer list).
- Consequence: dragging the row slider may silently no-op (writes nothing), or worse, may trigger an `applyLayerUpdate` that fails or mutates an unintended layer.

### Concern 2: BasemapGroupEditorScene's "Master opacity" slider is not persisted
- `BasemapGroupEditorScene.tsx:228` renders a "Master opacity" slider that calls `onMasterOpacityChange(opacity)`.
- `MapBuilderPage.tsx:755-761` wires this to `setMasterOpacity(opacity)` (a local React useState hook).
- Inline TODO comment at MapBuilderPage.tsx:757-760: *"TODO(Phase 1038): persist masterOpacity via basemap_config.opacity field (requires backend MapBasemapConfig schema addition). Spreading opacity directly into basemapConfig bypasses the type system and is stripped on the next API round-trip, so markDirty() is omitted until persistence is wired."*
- Consequence: the editor slider works visually for the current session, but does NOT persist on save and does NOT mark the map dirty.

### Investigation goals
1. **Behavioral verification:** Reproduce both sliders in the live UI (Playwright MCP). Document what each does to the map. Specifically: does the row slider DO anything observable (map opacity change)? Does it cause errors/warnings?
2. **State trace:** Trace the data flow from row slider value → handleOpacityChange → store/state. Identify the exact failure mode (silent no-op, error, unintended mutation).
3. **Persistence gap:** Confirm the Phase-1038 TODO. Check if the `MapBasemapConfig` backend schema has the `opacity` field today (maybe it was added since the TODO was written?). Check if the frontend would persist if the field existed.
4. **Decision matrix:** Surface 3-4 distinct paths forward with tradeoffs, costs, and prerequisites. Examples (planner-friendly):
   - **Path A:** Remove row slider only (mirror 260515-rdn/sqf). Editor slider's runtime behavior + non-persistence stay as-is. Closes the consistency gap, leaves persistence gap.
   - **Path B:** Remove row slider AND fix master-opacity persistence (Phase-1038). Net: full closure of both concerns. Higher cost (backend schema change).
   - **Path C:** Keep row slider, fix what it actually does (route to setMasterOpacity instead of handleOpacityChange). Closes the wiring bug but keeps the redundancy. Doesn't address persistence.
   - **Path D:** Defer — surface as deferred items, do nothing now.

### Out of scope for this investigation
- Any code change to BasemapGroupRow, BasemapGroupEditorScene, MapBuilderPage, or backend schemas.
- LayerEditorPanel or non-basemap row behavior.
- Implementation of any path forward — the investigation produces RESEARCH.md only; user decides on a follow-up implementation task.

</domain>

<decisions>
## Investigation Decisions

### Mode
- **Decision:** RESEARCH ONLY. No PLAN.md, no executor spawn. The deliverable is `260515-tb3-RESEARCH.md` with findings + decision matrix. User picks next step.

### What to verify with Playwright MCP
- Navigate to test map: http://localhost:8080/maps/dfbe4fd8-56a0-46d0-a155-3256d2c35d37 (already authenticated).
- Identify the basemap group row and capture initial slider value.
- Drag/keyboard-adjust the basemap row slider (`aria-label="Opacity for Basemap · Positron"`). Observe:
  - Does the map's basemap layer change opacity?
  - Does the slider's `aria-valuenow` update?
  - Does any console warning/error appear?
  - Does the Save button transition to "Unsaved" state?
- Open the BasemapGroupEditorScene (click the basemap row). Locate the "Master opacity" slider in the Visibility section.
- Repeat the same observation for the master-opacity slider.

### Backend schema check
- Decision: Check `~/Code/geolens/backend/app/modules/maps/schemas.py` (or wherever `MapBasemapConfig` lives) to verify whether the `opacity` field exists today. If yes, the persistence TODO may already be obsolete and a small frontend wire-up would close it. If no, the TODO is real and Path B has a backend prerequisite.

### Decision matrix shape
- Decision: Frame 3-4 paths forward with explicit tradeoffs, blast radius estimates, and "what unblocks Path B" callouts.

</decisions>

<specifics>
## Specific Investigation Targets

- File: `frontend/src/components/builder/BasemapGroupRow.tsx:200` — `onValueChange={([value]) => { onOpacityChange(groupId, ...) }}`
- File: `frontend/src/components/builder/UnifiedStackPanel.tsx` — BasemapGroupRowWrapper instantiation passing onOpacityChange
- File: `frontend/src/components/builder/hooks/use-layer-map-sync.ts:185-220` — handleOpacityChange implementation (`applyLayerUpdate(layerId, ...)`)
- File: `frontend/src/components/builder/hooks/use-builder-layers.ts` — applyLayerUpdate implementation; check whether it short-circuits on missing layerId
- File: `frontend/src/pages/MapBuilderPage.tsx:755-761` — onMasterOpacityChange wiring + Phase-1038 TODO
- File: `frontend/src/components/builder/BasemapGroupEditorScene.tsx:228` — "Master opacity" slider definition
- File (backend): `backend/app/modules/maps/schemas.py` (or `models.py`) — `MapBasemapConfig` schema; does it have `opacity`?
- Live: Playwright MCP at http://localhost:8080/maps/dfbe4fd8-56a0-46d0-a155-3256d2c35d37

</specifics>

<canonical_refs>
## Canonical References

- 260515-rdn-RESEARCH.md — pattern for blast-radius investigation
- 260515-sqf-RESEARCH.md — pattern for "consumer count gate" verification
- MEMORY.md → `feedback_check_for_redundant_controls_at_sketch_merge.md` — explains the multi-sketch root cause
- MEMORY.md → `feedback_playwright_mcp_self_verify.md` — drives the live verification approach

</canonical_refs>
