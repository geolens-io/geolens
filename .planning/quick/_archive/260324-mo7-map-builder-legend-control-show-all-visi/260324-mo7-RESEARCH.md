# Quick Task 260324-mo7: Map Builder Legend Control - Research

**Researched:** 2026-03-24
**Domain:** Map builder legend, backend model extension
**Confidence:** HIGH

## Summary

The current `MapLegend` component (used in the builder) only shows layers that have a data-driven style (`l.styleConfig?.column` check on line 14). Simple single-color layers are invisible in the legend. The task adds `show_in_legend` to the backend model, passes it through the full save/load pipeline, modifies the legend to show all visible layers (with a simple swatch for non-data-driven layers), and adds a toggle in the layer's "More actions" menu.

All touchpoints are well-understood. The `ColorizedGeometryIcon` component in `LayerItem.tsx` (lines 49-90) plus `getLayerColors` (lines 92-101) already solve the "render a color swatch for any geometry type" problem and should be extracted to a shared location.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **Legend Entry Design**: Colorized icon + name for simple layers; data-driven layers keep existing categorical/graduated legend entries with color swatches per category.
- **Toggle UX Placement**: "Show in legend" / "Hide from legend" as a toggle menu item in "More actions" dropdown, after separator, before "Zoom to layer".
- **Default Behavior**: `show_in_legend` defaults to `true`. Backend column with `server_default="true"`. All existing layers appear in legend after migration.

### Claude's Discretion
None specified.

### Deferred Ideas (OUT OF SCOPE)
None specified.
</user_constraints>

## Current State Analysis

### MapLegend Component (`frontend/src/components/map/MapLegend.tsx`)

**Props:**
```typescript
interface MapLegendLayer {
  name: string;
  styleConfig?: StyleConfig | null;
  visible: boolean;
}
```

**Filter logic (line 14):** `layers.filter((l) => l.visible && l.styleConfig?.column)` -- this is the root cause. Only layers with a `styleConfig.column` (data-driven) pass through.

**What needs to change:**
1. Add `show_in_legend` to the `MapLegendLayer` interface
2. Change filter to: `layers.filter((l) => l.visible && l.show_in_legend !== false)`
3. For layers WITHOUT `styleConfig?.column`, render a simple colorized icon + name
4. For layers WITH `styleConfig?.column`, keep existing categorical/graduated rendering

### MapLegendLayer data shape (built in `MapBuilderPage.tsx:138-142`)

```typescript
const legendLayers = layers.localLayers.map((l) => ({
  name: l.display_name ?? l.dataset_name,
  styleConfig: l.style_config,
  visible: l.visible,
}));
```

**What needs to change:** Add `show_in_legend`, `geometryType`, `paint`, and `layerType` to enable icon rendering:
```typescript
const legendLayers = layers.localLayers.map((l) => ({
  name: l.display_name ?? l.dataset_name,
  styleConfig: l.style_config,
  visible: l.visible,
  show_in_legend: l.show_in_legend ?? true,
  geometryType: l.dataset_geometry_type,
  paint: l.paint,
  layerType: l.layer_type,
}));
```

### ColorizedGeometryIcon (`frontend/src/components/builder/LayerItem.tsx:49-90`)

Currently a private function in `LayerItem.tsx`. Renders Circle/Minus/Pentagon icons with fill or gradient based on geometry type and color array. Also uses `getLayerColors` (lines 92-101) to extract colors from paint/style_config.

**Extraction plan:** Move `ColorizedGeometryIcon` and `getLayerColors` to a shared file (e.g., `frontend/src/components/map/layer-icons.tsx`). Both `LayerItem.tsx` and `MapLegend.tsx` import from there.

### LayerItem "More Actions" Menu (`LayerItem.tsx:271-325`)

Current menu structure:
1. Rename
2. Move Up
3. Move Down
4. --- separator ---
5. Zoom to layer
6. Open dataset (external link)
7. --- separator ---
8. Remove layer (destructive)

Per CONTEXT.md decision, the toggle goes **after the first separator, before "Zoom to layer"** (position 5, pushing others down).

### LayerItem Props

The `LayerItemProps` interface (lines 103-122) needs a new callback:
```typescript
onToggleLegend: (id: string) => void;
```

## Backend Changes

### Model (`backend/app/maps/models.py`, MapLayer class, line 58)

Add after `style_config` (line 82):
```python
show_in_legend: Mapped[bool] = mapped_column(
    Boolean, default=True, server_default="true"
)
```

### Migration

Create `0006_add_show_in_legend.py`. Pattern from existing migrations:
```python
op.add_column(
    "map_layers",
    sa.Column("show_in_legend", sa.Boolean(), server_default="true", nullable=False),
    schema="catalog",
)
```

### Schemas (`backend/app/maps/schemas.py`)

1. **MapLayerInput** (line 14): Add `show_in_legend: bool = True`
2. **MapLayerResponse** (line 46): Add `show_in_legend: bool = True`
3. **SharedLayerResponse** (line 118): Add `show_in_legend: bool = True`

### Service (`backend/app/maps/service.py`)

1. **`_replace_layers`** (line 311): Add `show_in_legend=layer_data.get("show_in_legend", True)` to `MapLayer()` constructor (line 357-371)
2. **`duplicate_map`** (line 470): Copy `show_in_legend` in the layer duplication block (line 517-530)
3. **`get_shared_map`** (line 723): Add `"show_in_legend": layer.show_in_legend` to the layer dict (line 802-821)

### Router (`backend/app/maps/router.py`)

**`_build_layer_response`** (line 74): Add `show_in_legend=layer.show_in_legend` to MapLayerResponse constructor.

## Frontend Save Flow

### `use-builder-save.ts` (line 92-104)

The save payload maps localLayers to API shape. Add `show_in_legend`:
```typescript
layers: localLayers.map((l) => ({
  // ...existing fields...
  show_in_legend: l.show_in_legend ?? true,
})),
```

### `use-builder-layers.ts`

Add handler:
```typescript
function handleToggleLegend(layerId: string) {
  setLocalLayers((prev) =>
    prev.map((l) =>
      l.id === layerId ? { ...l, show_in_legend: !l.show_in_legend } : l,
    ),
  );
  setHasUnsavedChanges(true);
}
```

### TypeScript types (`frontend/src/types/api.ts`)

Add to `MapLayerResponse` (line 644): `show_in_legend?: boolean;`
Add to `SharedLayerResponse` (line 743): `show_in_legend?: boolean;`

## Public Viewer Impact

The `LayerLegend` component (`frontend/src/components/viewer/LayerLegend.tsx`) shows ALL layers regardless of `show_in_legend` currently. It should filter by `show_in_legend` too. Since `SharedLayerResponse` will include the field, the filter is: `sorted.filter(l => l.show_in_legend !== false)`.

## File Change Summary

| File | Change |
|------|--------|
| `backend/app/maps/models.py` | Add `show_in_legend` column |
| `backend/alembic/versions/0006_*.py` | New migration |
| `backend/app/maps/schemas.py` | Add field to 3 schemas |
| `backend/app/maps/service.py` | Pass through in _replace_layers, duplicate_map, get_shared_map |
| `backend/app/maps/router.py` | Pass through in _build_layer_response |
| `frontend/src/types/api.ts` | Add to MapLayerResponse, SharedLayerResponse |
| `frontend/src/components/map/layer-icons.tsx` | **New file** - extract ColorizedGeometryIcon + getLayerColors |
| `frontend/src/components/builder/LayerItem.tsx` | Import from shared, add onToggleLegend prop + menu item |
| `frontend/src/components/map/MapLegend.tsx` | Add simple-layer rendering, filter by show_in_legend |
| `frontend/src/pages/MapBuilderPage.tsx` | Expand legendLayers shape, pass onToggleLegend |
| `frontend/src/hooks/use-builder-layers.ts` | Add handleToggleLegend |
| `frontend/src/hooks/use-builder-save.ts` | Include show_in_legend in save payload |
| `frontend/src/components/viewer/LayerLegend.tsx` | Filter by show_in_legend |

## Sources

### Primary (HIGH confidence)
- Direct code inspection of all listed files in the codebase
- Existing migration patterns from `0005_schema_fixes.py`
