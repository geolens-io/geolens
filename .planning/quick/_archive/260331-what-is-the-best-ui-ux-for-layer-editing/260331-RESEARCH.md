# Quick Task 260331: Layer Editing UI/UX Assessment

**Researched:** 2026-03-29  
**Scope:** Current map creator layer editing UX, future extensibility, Mapbox style-spec alignment  
**Methods:** Code review, Playwright review of the sample map, official style-spec references  
**Confidence:** High

## Executive Summary

The best long-term UI for GeoLens layer editing is a **two-pane model**:

1. A **layer stack** optimized for ordering, visibility, quick state cues, and bulk management.
2. A **layer inspector** optimized for editing one selected layer with sections that mirror the style spec: `General`, `Filter`, `Paint`, `Layout`, `Labels/Symbol`, `Legend`, and `Advanced JSON`.

The current UX is solid for an MVP with 1-3 simple layers. It becomes strained as soon as a map carries more layers, more properties, or more advanced rendering behavior. The main issue is that the product currently edits layers through a compact row accordion with three fixed tabs, while the future authoring model needs to act more like a structured style inspector.

The good news is that the data model already has the right low-level foundation in several places:

- `paint` and `layout` are stored as generic dictionaries.
- `filter` is already persisted as a style-spec-like expression.
- Runtime layer adapters exist, which is the right direction for per-layer-type behavior.

The main constraint is the **UI abstraction**, not the renderer. Current abstractions like a single `style_config`, a single `label_config`, a fixed set of editor tabs, and hard-coded layer-type unions will make future work on `symbol`, `fill-extrusion`, `heatmap`, richer raster controls, or style-slot placement unnecessarily expensive.

## What Works Well Today

### 1. The layer list is scannable for simple maps

The current layer row gives quick access to visibility, drag reorder, rename, zoom-to-layer, dataset link, legend inclusion, and remove. Filter and label state are surfaced with compact glyphs, which is useful for fast scanning.

### 2. The product already has progressive escape hatches

The filter editor has a useful `JSON` mode for opaque expressions. That is a good pattern and should be reused for style-spec-oriented advanced editing.

### 3. Live preview feedback is strong

The sidebar is directly coupled to the map preview and legend widget, which gives authors immediate confidence when basic paint or filter changes are made.

### 4. Adapter work has improved the runtime architecture

The runtime no longer relies only on one giant switch statement. The adapter pattern is the right primitive if the UI eventually exposes more layer types and more paint/layout properties.

## Key Findings

### Finding 1: The current editing model is row-first, not inspector-first

The editor allows only one expanded layer and one active tab at a time. This keeps the MVP simple, but it increases interaction cost when the author needs to compare layers, inspect multiple settings, or work on maps with many layers.

Observed implementation:

- `expandedLayerId` and `activeEditorTab` are single global states.
- The panel renders editing UI inline beneath a row rather than in a dedicated inspector.

UX impact:

- Good for quick edits.
- Poor for multi-layer comparison, long-form editing, and advanced workflows.
- Crowds the same narrow sidebar with both list management and detailed authoring.

### Finding 2: The current UI is not yet aligned to the style-spec layer model

Mapbox style layers are defined around `type`, `filter`, `layout`, `paint`, `minzoom`, `maxzoom`, `source`, and optionally `slot`. The current editor exposes pieces of that model, but it splits them across bespoke abstractions:

- geometry styling via `paint`
- labels via `label_config`
- data-driven styling via a single `style_config`

This works for the current feature set but does not scale cleanly to richer layer types or multiple concurrent style rules.

### Finding 3: `style_config` is too narrow for future styling depth

`StyleConfig` represents one mode, one column, one ramp, and one target. That is fine for a single thematic styling decision, but not for a future where authors will want multiple independent rules:

- color by category and radius by magnitude
- line color plus line width plus line gap width
- fill color plus opacity ramp plus sort key

The actual source of truth should move toward **property-scoped style rules** or a style-layer authoring model, with `paint`/`layout` staying canonical.

### Finding 4: Labels need to become first-class style passes, not an auxiliary tab

In the style spec, labels live in `symbol` layers and support many layout/paint properties. GeoLens currently treats labels as an optional add-on to vector layers. That is practical for MVP authoring, but it makes future symbol work awkward.

The current label editor exposes only:

- text field
- font size
- text color
- halo color
- halo width
- min/max zoom

It does not expose symbol-placement options beyond the internal point/line default, nor collision/anchor controls such as `text-variable-anchor`, `text-radial-offset`, `text-padding`, or ordering controls like `symbol-sort-key`.

### Finding 5: The filter editor is intentionally limited and will hit a ceiling

The current filter builder only round-trips:

- flat single expressions
- top-level `all` / `any`
- simple comparisons
- `contains`
- `is_null`

Anything more complex falls back to opaque JSON. This is a reasonable MVP compromise, but not a durable UX if advanced map authoring becomes a priority.

### Finding 6: There is a live correctness gap in the label editor

The label editor exposes `minZoom` and `maxZoom`, and the full `map-sync.ts` path applies those values to the label layer. But the interactive `useBuilderLayers` path does not call `setLayerZoomRange()` or otherwise apply those values during live edits. That makes the zoom controls unreliable in-session.

The Playwright review also showed raw i18n keys for `labels.zoomRange`, `labels.minZoom`, and `labels.maxZoom` in the live UI, which is a visible polish bug.

### Finding 7: The style tab is too dense for complex datasets

The current style tab places:

- data-driven controls
- scalar paint controls
- a long read-only column list

inside the same narrow panel. On the sample map, the fields list is long enough that it dilutes the main editing task. The fields reference is useful, but it should not compete with the active editing controls.

### Finding 8: Current capability unions will slow down future layer-type expansion

The runtime and capability layers still explicitly enumerate only `fill`, `line`, `circle`, and `raster`. The official style spec supports many more layer types, including `symbol`, `fill-extrusion`, `heatmap`, `hillshade`, `model`, `background`, `sky`, and `slot`.

If GeoLens wants to stay aligned with the style spec, the UI should move toward a registry-driven system:

- supported layer types
- supported paint/layout properties
- default controls
- expression support
- runtime support flags
- experimental flags

## Best Target UX

### Recommended structure

#### Left rail: Layer Stack

Keep this focused on list management:

- visibility
- reorder
- select
- rename
- quick badges
- group/folder support later
- bulk actions later

It should not be the primary home for full editing UI.

#### Main inspector: Selected Layer

On desktop and tablet, the selected layer should open in a dedicated inspector. Suggested sections:

1. `General`
   - display name
   - layer type
   - visibility
   - zoom range
   - legend inclusion
   - placement / slot when supported

2. `Filter`
   - visual rule builder
   - nested groups later
   - raw JSON escape hatch

3. `Paint`
   - property controls grouped by spec property families
   - color, opacity, stroke, width, ramps
   - data-driven rules per property

4. `Layout`
   - dash patterns
   - line join/cap
   - sort keys
   - visibility
   - collision/placement controls where relevant

5. `Labels / Symbol`
   - treat as symbol styling, not an auxiliary checkbox section
   - placement presets
   - advanced symbol controls

6. `Advanced JSON`
   - `paint`
   - `layout`
   - `filter`
   - future full style-layer JSON

### Authoring model

Use the style spec as the mental model and the UI organization model:

- top-level layer concerns stay top-level
- `paint` stays paint
- `layout` stays layout
- `filter` stays filter
- `minzoom`/`maxzoom` become general layer properties
- labels are symbol-style authoring, not a one-off side abstraction

### Progressive disclosure

Avoid dropping authors directly into raw spec properties. The right pattern is:

- `Basic` controls first
- `Style by data` as an opt-in section
- `Advanced` property sections after that
- `JSON` as the last-resort or power-user escape hatch

That keeps the product friendly for most users while preserving a clean path to expert workflows.

## Extensibility Recommendations

### 1. Make `paint` and `layout` canonical, and keep helper metadata secondary

`paint`, `layout`, and `filter` already match the style-spec shape. Future UI metadata should be derived from or attached to those structures, not treated as the primary authoring model.

### 2. Replace single `style_config` with per-property style rules

Move toward a structure like:

```ts
style_rules: [
  { property: 'circle-color', mode: 'categorical', field: 'class', ... },
  { property: 'circle-radius', mode: 'graduated', field: 'pop_max', ... },
]
```

That supports multiple concurrent data-driven rules and maps directly to expression-enabled style properties.

### 3. Introduce a property registry

Each supported property should be described in metadata:

- layer types
- section (`paint`, `layout`, `filter`, `general`)
- UI control
- default value
- expression support
- runtime compatibility
- label text / help text

This avoids hand-coding every new property in bespoke components.

### 4. Treat labels as nested style layers or style passes

A vector dataset layer can own multiple render passes:

- geometry pass
- outline pass
- label pass

Expose that concept in the UI as nested sublayers or styling passes so the model stays understandable when symbol authoring grows.

### 5. Carry a runtime compatibility matrix

If GeoLens wants a Mapbox-style-spec-oriented editor while running MapLibre, the registry should distinguish:

- authoring spec property
- supported in GeoLens now
- supported by current runtime
- experimental / hidden

That allows the editor to grow without pretending every spec property is available immediately.

## Easy Wins

### Immediate

1. Fix the missing label i18n keys so the UI stops rendering raw translation tokens.
2. Fix live label zoom-range syncing in `useBuilderLayers` so `minZoom` and `maxZoom` work immediately.
3. Move the giant `Columns` list behind a collapsible or searchable fields reference panel.
4. Add short style summary badges to the layer row, for example `Graduated pop_max` or `Radius by pop_max`.
5. Reuse the filter editor’s `JSON` escape-hatch pattern for `paint` and `layout` in an advanced section.

### Next

6. Split wide-screen editing into `Layer Stack` + `Inspector` instead of stacking everything in the same narrow sidebar.
7. Add `Basic` / `Advanced` editing modes inside the inspector.
8. Promote labels into a proper `Symbol` section with presets for common placement strategies.
9. Add general per-layer zoom range controls, not just label zoom range.
10. Add property search in the advanced inspector so future layer-property growth stays manageable.

## Evidence

### Live sample review

- URL reviewed: `http://localhost:8080/maps/83ef732f-31b8-4c64-9740-4576dcd640f6`
- Result: the current sample confirms the compact row-accordion model and exposed the untranslated label zoom labels in the live UI.

### Codebase evidence

- Single-layer expansion and shared editor tab state
- Fixed three-tab editor surface (`Style`, `Filter`, `Labels`)
- Narrow `StyleConfig` model
- Limited filter AST round-tripping
- Label live-sync mismatch between `useBuilderLayers` and `map-sync.ts`
- Hard-coded capability / adapter layer type unions

## Sources

- Mapbox Style Spec guide: https://docs.mapbox.com/style-spec/guides/
- Mapbox Style Spec layers reference: https://docs.mapbox.com/style-spec/reference/layers/
- Mapbox Style Spec slots reference: https://docs.mapbox.com/style-spec/reference/slots/
