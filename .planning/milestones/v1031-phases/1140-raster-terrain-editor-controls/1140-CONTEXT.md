# Phase 1140: Raster & Terrain Editor Controls - Context

**Gathered:** 2026-05-28
**Status:** Ready for planning
**Mode:** Auto-generated (discuss skipped via workflow.skip_discuss)

<domain>
## Phase Boundary

Users can configure contour overlays, hypsometric tints, and single-band colormaps for DEM and raster layers directly in the editor.

Requirements:
- **EDITOR-DEM-04** — contour-line overlay on a DEM/terrain layer (toggle + line styling: interval, color, weight).
- **EDITOR-DEM-05** — hypsometric (elevation) tint color ramp for terrain/DEM from a preset ramp set.
- **EDITOR-RASTER-COLORMAP** — single-band stretch + colormap for a raster layer; tiles re-render on change.

</domain>

<decisions>
## Implementation Decisions

### Claude's Discretion
Implementation choices are at Claude's discretion — discuss was skipped per `workflow.skip_discuss`. Use the ROADMAP success criteria, REQUIREMENTS.md, and existing codebase conventions to guide decisions.

### Known constraints (from v1031 REQUIREMENTS.md + STATE.md HARD INVARIANTS — do NOT violate)
- Feature-add on the **v1026 style-reconciler + v1027 controller/action/sync** substrate and the **v1010/v1030 per-render-mode editor split**. New controls extend the existing owned-property contracts. Existing DEM/raster controls (hillshade sliders, opacity, etc.) MUST remain unaffected (success criterion 4 — behavior preservation).
- **No architecture rewrites:** no new files >500 LOC; no rename of >3 exported symbols; no controller/action-boundary widening without a Future Requirement entry first.
- **EDITOR-RASTER-COLORMAP depends on the backend single-band colormap render path (Titiler)** — research this at plan-phase: how the existing raster tile route passes params to Titiler, and the Titiler colormap surface (`colormap_name`, `rescale`, custom `colormap`). Any new backend query-param or response-schema change triggers an OpenAPI/SDK refresh in Phase 1143.
- DEM-04 contour and DEM-05 hypsometric tint operate on the DEM/terrain layer surface — prefer MapLibre-native paint/expression and the existing terrain/hillshade plumbing over new subsystems.

</decisions>

<code_context>
## Existing Code Insights

To be gathered during plan-phase research. Relevant surfaces likely include: the per-render-mode editor children (e.g., `RasterEditor`, DEM/terrain controls) under the builder editor scenes; the raster/DEM layer-adapters that own MapLibre paint/layout; and the backend raster tile route + Titiler integration. Confirm exact paths via research.

</code_context>

<specifics>
## Specific Ideas

- **DEM-05 hypsometric tint:** ship a curated preset ramp set (not arbitrary per-stop color authoring) per the success criterion ("select a preset hypsometric tint ramp").
- **RASTER-COLORMAP:** expose colormap + stretch-type selection; re-render tiles on change (success criterion 3). Reuse Titiler's built-in colormaps where possible.
- **DEM-04 contour:** toggle + line styling (interval, color, weight) per success criterion 1.

</specifics>

<deferred>
## Deferred Ideas

None — discuss skipped. Out-of-scope per REQUIREMENTS.md: editor-convenience (categorical icons, custom basemap URL) and layer-type expansion (text/draw/LiDAR) stay parked in 999.18.

</deferred>
