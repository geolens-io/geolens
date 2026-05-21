# Quick Task 260324-mo7: Map builder legend control - Context

**Gathered:** 2026-03-24
**Status:** Ready for planning

<domain>
## Task Boundary

Map builder legend control: show all visible layers in the legend (not just data-driven styled ones), add per-layer toggle to include/exclude from legend, persist show_in_legend setting on MapLayer model.

Currently only layers with categorical/graduated data-driven styles appear in the MapLegend. Simple single-color layers (points, lines, polygons) don't show up at all.

</domain>

<decisions>
## Implementation Decisions

### Legend Entry Design
- **Colorized icon + name**: Reuse the ColorizedGeometryIcon component from LayerItem.tsx for simple layers. Data-driven layers keep their existing categorical/graduated legend entries with color swatches per category.
- Simple layers: colorized geometry icon (filled circle/line/pentagon) + layer name
- Data-driven layers: existing behavior (category list with color dots)

### Toggle UX Placement
- **More actions menu**: Add "Show in legend" / "Hide from legend" as a toggle menu item in the layer's "More actions" dropdown. Positioned after the separator, before "Zoom to layer".
- Low visual clutter, consistent with other layer actions

### Default Behavior
- **Default ON**: `show_in_legend` defaults to `true`. All layers appear in legend unless explicitly hidden by the user.
- Backend: column default = true
- Migration: adds column with `server_default="true"`
- Existing maps: all layers will appear in legend after migration (backward-compatible enhancement)

</decisions>

<specifics>
## Specific Ideas

- Reuse `ColorizedGeometryIcon` from `frontend/src/components/builder/LayerItem.tsx` — extract to shared location or import
- Current legend: `frontend/src/components/map/MapLegend.tsx` + `frontend/src/components/viewer/LayerLegend.tsx`
- Legend data built in `MapBuilderPage.tsx` at line 138: `legendLayers = layers.localLayers.map(...)`
- Backend model: `backend/app/maps/models.py` MapLayer class
- Backend schemas: `backend/app/maps/schemas.py`
- Save flow: `frontend/src/hooks/use-builder-save.ts` includes layer fields in save payload
- Public viewer: `frontend/src/pages/PublicViewerPage.tsx` also renders a legend

</specifics>
