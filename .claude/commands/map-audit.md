# /map-audit — Saved Map Quality, Style & Access Audit

Audit a specific saved map by its UUID — covering style quality, data integrity, performance concerns, design quality, MapLibre Style Spec compliance, and sharing/access configuration. Every finding must reference the specific layer or property and include a concrete fix.

**Usage:** `/map-audit <map-id>` (full audit) or `/map-audit <map-id> <scope>` where scope is `style`, `data`, `perf`, `design`, `spec`, or `access`

Arguments: $ARGUMENTS

- First token → `MAP_ID` (UUID of the map to audit)
- Second token (optional) → scope keyword:
  - `style` → Subagent 1 only (style quality)
  - `data` → Subagent 2 only (data integrity)
  - `perf` → Subagent 3 only (performance)
  - `design` → Subagent 4 only (design quality)
  - `spec` → Subagent 5 only (MapLibre spec compliance)
  - `access` → Subagent 6 only (sharing & access)
- Empty `$ARGUMENTS` → print usage and abort

If a scope keyword is provided, run only the corresponding subagent(s). Still run the full INTAKE — subagents need the context. In the SYNTHESIS, grade only the relevant dimension(s) and note the scoped execution.

---

## INTAKE (Serial — do this first)

> **Note:** Use the Read tool (not `cat` or Bash) to read source files. Use Bash only for curl requests. The INTAKE loads the map data into the main context for SYNTHESIS. Subagents will reference the same data.

### Step 1: Parse arguments

```bash
MAP_ID=$(echo "$ARGUMENTS" | awk '{print $1}')
SCOPE=$(echo "$ARGUMENTS" | awk '{print $2}')
```

If `MAP_ID` is empty, print usage and abort:
```
Usage: /map-audit <map-id> [scope]
  scope: style | data | perf | design | spec | access
  omit scope for full audit
```

### Step 2: Fetch map via live API

```bash
MAP_JSON=$(curl -s -w "\n%{http_code}" http://localhost:8000/api/maps/${MAP_ID}/)
HTTP_CODE=$(echo "$MAP_JSON" | tail -1)
MAP_BODY=$(echo "$MAP_JSON" | sed '$d')
```

If `HTTP_CODE` is not 200, abort with:
```
Error: Could not fetch map ${MAP_ID} (HTTP ${HTTP_CODE})
- Is the dev server running? (docker compose up -d)
- Is the map ID correct? (check /api/maps/ for the list)
```

Parse and display the map summary:
```bash
echo "$MAP_BODY" | python3 -c "
import json, sys
m = json.load(sys.stdin)
print(f\"Map: {m['name']} ({m['id']})\")
print(f\"Description: {m.get('description')}\")
print(f\"Notes: {m.get('notes')}\")
print(f\"Visibility: {m['visibility']}\")
print(f\"Layers: {m['layer_count']}\")
print(f\"Basemap: {m['basemap_style']}\")
print(f\"Basemap labels: {m.get('show_basemap_labels', True)}\")
print(f\"Viewport: [{m['center_lng']}, {m['center_lat']}] z{m['zoom']}\")
print(f\"Bearing: {m['bearing']}, Pitch: {m['pitch']}\")
print(f\"Widgets: {m.get('widgets', [])}\")
print(f\"Forked from: {m.get('forked_from_name') or m.get('forked_from_id') or 'None'}\")
print(f\"Created: {m['created_at']}\")
print(f\"Updated: {m['updated_at']}\")
"
```

### Step 3: Extract layer catalog

For each layer in the response, extract and catalog:

```bash
echo "$MAP_BODY" | python3 -c "
import json, sys
m = json.load(sys.stdin)
for i, l in enumerate(m.get('layers', [])):
    print(f\"--- Layer {i} ---\")
    print(f\"  id: {l['id']}\")
    print(f\"  dataset: {l['dataset_name']} ({l['dataset_id']})\")
    print(f\"  geometry: {l.get('dataset_geometry_type')}\")
    print(f\"  layer_type: {l['layer_type']}\")
    print(f\"  display_name: {l.get('display_name')}\")
    print(f\"  sort_order: {l['sort_order']}\")
    print(f\"  visible: {l['visible']}, opacity: {l['opacity']}\")
    print(f\"  table_name: {l.get('dataset_table_name')}\")
    print(f\"  record_type: {l.get('dataset_record_type')}\")
    cols = l.get('dataset_column_info') or []
    print(f\"  columns: {[(c['name'], c.get('type')) for c in cols]}\")
    print(f\"  paint keys: {list(l.get('paint', {}).keys())}\")
    print(f\"  paint: {l.get('paint', {})}\")
    print(f\"  layout keys: {list(l.get('layout', {}).keys())}\")
    print(f\"  layout: {l.get('layout', {})}\")
    print(f\"  filter: {l.get('filter')}\")
    print(f\"  label_config: {l.get('label_config')}\")
    print(f\"  style_config: {l.get('style_config')}\")
    print(f\"  feature_count: {l.get('dataset_feature_count')}\")
    print(f\"  extent_bbox: {l.get('dataset_extent_bbox')}\")
    print(f\"  show_in_legend: {l.get('show_in_legend')}\")
    print(f\"  is_3d: {l.get('is_3d')}\")
    print()
"
```

### Step 4: Check share/access state

```bash
# Share token status
curl -s http://localhost:8000/api/maps/${MAP_ID}/share/ | python3 -m json.tool 2>/dev/null || echo "No share token"

# Visibility check (are all referenced datasets compatible with the map's visibility?)
curl -s http://localhost:8000/api/maps/${MAP_ID}/visibility-check/ | python3 -m json.tool 2>/dev/null || echo "Visibility check not available"
```

### Step 5: Read source references for cross-checking

Read each of these files:

- `frontend/src/components/builder/layer-adapters/registry.ts` — adapter type → geometry mapping
- `frontend/src/components/builder/layer-adapters/shared.ts` — resolveAdapterType, simplifyPaint, stripCustomProps
- `frontend/src/components/builder/layer-adapters/types.ts` — adapter interface
- `frontend/src/lib/layer-capabilities.ts` — which features each layer type supports
- `frontend/src/lib/basemap-utils.ts` — valid basemap IDs and style resolution
- `frontend/src/lib/color-ramps.ts` — available color ramp definitions

---

## MAP AUDIT REFERENCE (Embedded)

These are the expected behaviors and valid values. Deviations are findings.

### Valid paint properties by layer type

| Layer Type | Valid Paint Properties |
|------------|----------------------|
| `circle` (Point) | `circle-color`, `circle-radius`, `circle-opacity`, `circle-stroke-color`, `circle-stroke-width`, `circle-stroke-opacity`, `circle-blur`, `circle-translate`, `circle-translate-anchor`, `circle-pitch-scale`, `circle-pitch-alignment` |
| `fill` (Polygon) | `fill-color`, `fill-opacity`, `fill-outline-color`, `fill-antialias`, `fill-translate`, `fill-translate-anchor`, `fill-pattern` |
| `fill-extrusion` (3D Polygon) | `fill-extrusion-color`, `fill-extrusion-height`, `fill-extrusion-base`, `fill-extrusion-opacity`, `fill-extrusion-vertical-gradient`, `fill-extrusion-translate`, `fill-extrusion-translate-anchor`, `fill-extrusion-pattern` |
| `line` (LineString) | `line-color`, `line-width`, `line-opacity`, `line-dasharray`, `line-gap-width`, `line-offset`, `line-blur`, `line-translate`, `line-translate-anchor` |
| `heatmap` (Point, render_mode=heatmap) | `heatmap-radius`, `heatmap-weight`, `heatmap-intensity`, `heatmap-color`, `heatmap-opacity` |
| `raster` (Raster) | `raster-opacity`, `raster-hue-rotate`, `raster-brightness-min`, `raster-brightness-max`, `raster-saturation`, `raster-contrast`, `raster-fade-duration`, `raster-resampling` |

### Valid layout properties by layer type

| Layer Type | Valid Layout Properties |
|------------|----------------------|
| `line` | `line-cap`, `line-join`, `line-miter-limit`, `line-round-limit`, `line-sort-key`, `visibility` |
| `symbol` (labels) | `text-field`, `text-size`, `text-font`, `text-anchor`, `text-justify`, `text-offset`, `text-max-width`, `text-letter-spacing`, `text-line-height`, `text-allow-overlap`, `symbol-placement`, `symbol-spacing`, `symbol-sort-key`, `icon-allow-overlap`, `visibility` |
| All types | `visibility` |

**Note:** The line adapter stores `line-dasharray` in the `layout` JSON for UI convenience and extracts it to paint at render time. Finding `line-dasharray` in `layout` in saved map data is expected — do not flag as a spec violation.

### Custom properties (GeoLens-specific, stripped before MapLibre rendering)

These properties are stored in `paint` or `layout` JSON but are NOT passed to MapLibre. They are used by the builder UI. Do not flag any of these as spec violations:

- `_outline-color` — fill outline color for UI controls
- `_outline-width` — fill outline width for UI controls
- `_outline-width-saved` — preserved outline width when toggling
- `outline-color` — legacy alias (non-underscore form, also in CUSTOM_PAINT_PROPS set)
- `outline-width` — legacy alias (non-underscore form, also in CUSTOM_PAINT_PROPS set)
- `_fill-opacity-saved` — preserved opacity when toggling visibility
- `_fill-disabled` — flag indicating fill is disabled (transparent)
- `_stroke-disabled` — flag indicating stroke is disabled
- `_heatmap-ramp` — ramp name reference for heatmap color UI
- `_heatmap-weight-column` — column name used for heatmap weight
- `_height_column` — 3D extrusion column reference

**Rule:** Skip any paint/layout key that starts with `_` or matches `outline-color` / `outline-width` when checking spec compliance.

### Geometry type → adapter type mapping

| Geometry Type | Adapter Type |
|---------------|-------------|
| `POINT`, `MULTIPOINT` | `circle` |
| `LINESTRING`, `MULTILINESTRING` | `line` |
| `POLYGON`, `MULTIPOLYGON` | `fill` (+ `fill-extrusion` companion when `is_3d: true` or `paint._height_column` is set) |
| (any, with `style_config.render_mode === "heatmap"`) | `heatmap` |
| (raster_geolens / vrt layer_type) | `raster` |

### Valid enum values

| Property | Valid Values |
|----------|-------------|
| `line-cap` | `butt`, `round`, `square` |
| `line-join` | `bevel`, `round`, `miter` |
| `text-anchor` | `center`, `left`, `right`, `top`, `bottom`, `top-left`, `top-right`, `bottom-left`, `bottom-right` |
| `symbol-placement` | `point`, `line`, `line-center` |
| `text-justify` | `auto`, `left`, `center`, `right` |
| `visibility` | `visible`, `none` |

### Valid expression forms

```
Match:       ["match", input, label1, output1, label2, output2, ..., fallback]
Interpolate: ["interpolate", ["linear"] | ["exponential", base], input, stop1, output1, ...]
Step:        ["step", input, default, stop1, output1, stop2, output2, ...]
Case:        ["case", condition1, output1, condition2, output2, ..., fallback]
Get:         ["get", "property_name"]
Compare:     ["=="|"!="|">"|"<"|">="|"<=", ["get", "prop"], value]
All/Any:     ["all"|"any", condition1, condition2, ...]
Has/!Has:    ["has"|"!has", "property_name"]
```

### Numeric constraints

| Property | Range |
|----------|-------|
| `*-opacity` | 0.0 – 1.0 |
| `circle-radius` | >= 0 |
| `line-width` | >= 0 |
| `text-size` | > 0 |
| `heatmap-radius` | >= 1 |
| `heatmap-intensity` | >= 0 |
| `line-dasharray` | array of positive numbers |
| `zoom` (map viewport) | 0 – 24 |
| `bearing` | -180 – 180 |
| `pitch` | 0 – 85 |

---

## SUBAGENT DISPATCH (Parallel — 6 subagents)

Run these subagents in parallel using the Agent tool. Do NOT wait for one to finish before starting the next. Collect all results before proceeding to SYNTHESIS.

Each subagent must:

1. Analyze the fetched map JSON from INTAKE (layer catalog, share state, map metadata)
2. Cross-reference against source code where needed
3. Produce a numbered finding list with severity tags: `[CRITICAL]`, `[HIGH]`, `[MEDIUM]`, `[LOW]`
4. Include evidence (specific property values or configuration) for every finding
5. Include a concrete one-sentence fix for every finding
6. Reference findings by layer index and name (e.g., "Layer 2 (parcels): ...")
7. Cap output at **20 findings maximum** — if more exist, include the top 20 by severity and note how many were omitted

---

### Subagent 1: Style Quality

**Goal:** Verify every layer's paint/layout properties are well-formed, appropriate for the geometry type, and produce a reasonable visual result.

**Process:**

1. **Paint/geometry alignment:**
   - For each layer, determine the expected adapter type from `dataset_geometry_type` (use the geometry→adapter mapping table above)
   - Check that all paint property keys are valid for that adapter type (see valid paint properties table)
   - Flag paint properties that belong to a different layer type (e.g., `circle-color` on a Polygon layer)
   - Skip underscore-prefixed custom properties (`_outline-color`, `_outline-width`, etc.) — these are GeoLens-specific, not MapLibre properties

2. **Value validation:**
   - Check opacity values (any property ending in `-opacity`) are in 0.0–1.0
   - Check color values are valid CSS color strings: hex (`#rgb`, `#rrggbb`, `#rrggbbaa`), `rgb()`, `rgba()`, `hsl()`, `hsla()`, or named colors — NOT OKLCH
   - Check `circle-radius` > 0, `line-width` > 0, `text-size` > 0
   - Check `line-dasharray` values are all positive numbers (no zeros, no negatives)
   - If a paint value is a MapLibre expression (array), verify it's not checked as a literal (delegate to Subagent 5)

3. **Data-driven style validation:**
   - If `style_config` exists:
     - `mode: "categorical"` → check `categories` array is non-empty, each entry has `value` and `color`
     - `mode: "graduated"` → check `breaks` and `colors` arrays exist and have consistent lengths
     - Check `column` references a property in `dataset_column_info`
     - Check `ramp` name is a known color ramp (cross-reference with `color-ramps.ts`)
   - If paint properties contain expression arrays, verify they have fallback/default values

4. **Empty/missing style detection:**
   - Flag layers with empty paint objects `{}` (will render with MapLibre defaults — often invisible)
   - Flag visible layers with `opacity: 0` (invisible but consuming resources)
   - Flag layers where `visible: true` but all paint colors are transparent (e.g., `rgba(0,0,0,0)`)

5. **Heatmap-specific checks:**
   - If `style_config.render_mode === "heatmap"`:
     - Verify `heatmap-radius` is set and reasonable (1–100)
     - Verify `heatmap-intensity` is set (0–10 typical)
     - Verify `heatmap-color` expression produces a valid color ramp
   - Check that heatmap layers are only on Point/MultiPoint geometries
   - If `paint._heatmap-weight-column` is set, verify `paint.heatmap-weight` is a data-driven expression `["get", column_name]` matching the weight column — flag `[HIGH]` if it is a scalar (weight column silently ignored)
   - If `_heatmap-weight-column` is set, verify the referenced column exists in `dataset_column_info` and is numeric — flag `[HIGH]` if the column is a string type (MapLibre converts string to 0, effectively no weighting)

6. **3D extrusion checks (fill-extrusion):**
   - If `is_3d: true` or `paint._height_column` is set:
     - Verify `fill-extrusion-height` is present in paint (or will be generated from `_height_column` expression) — flag `[HIGH]` if missing (3D enabled but no height = flat extrusion)
     - Verify `fill-extrusion-base` is set or defaults to 0 (acceptable)
     - Verify `fill-extrusion-opacity` is in 0.0–1.0 if present
     - Verify `fill-extrusion-color` is set — flag `[MEDIUM]` if missing (will use default gray)
     - Check that `_height_column` references a numeric column in `dataset_column_info` — flag `[HIGH]` if column not found or not numeric
   - If `is_3d` layers exist but map `pitch` is 0: flag `[MEDIUM]` — flat camera on a 3D map undercuts the extrusion effect; recommend pitch 30–60

7. **Data-driven expression structure:**
   - For categorical styles: verify the paint expression wraps in a null guard `["case", ["==", ["get", col], null], fallback_color, ["match", ...]]` — flag `[MEDIUM]` if the null guard is missing (null values render at the first category color instead of a neutral fallback)
   - For graduated styles: verify the paint expression wraps in a null guard `["case", ["==", ["get", col], null], fallback_color, ["step", ...]]` — flag `[MEDIUM]` if missing (same issue)

**Output:** Finding list — Layer index | Severity | Property | Issue | Fix.

---

### Subagent 2: Data Integrity

**Goal:** Verify layers reference valid datasets, configurations are internally consistent, and data relationships are intact.

**Process:**

1. **Dataset reference validity:**
   - Check each layer has a non-null, non-empty `dataset_name`
   - Check `dataset_geometry_type` is set for vector layers (null geometry → layer may fail to render)
   - Check `dataset_feature_count` is not 0 or null — flag as `[MEDIUM]` (layer renders nothing)
   - Check `dataset_extent_bbox` is not null — flag as `[LOW]` if missing (zoom-to-fit won't work for this layer)

2. **Sort order integrity:**
   - Check `sort_order` values are unique across all layers (duplicate sort orders = ambiguous z-order)
   - Check sort orders are sequential without large gaps (cosmetic, not functional)
   - Verify sort order aligns with visual intent (opaque polygon layers should be below point/line layers)

3. **Duplicate dataset detection:**
   - Check for the same `dataset_id` appearing in multiple layers
   - Flag as `[LOW]` for awareness — this is valid (same data, different styles) but worth noting

4. **Filter integrity:**
   - If `filter` is set, extract all property references (`["get", "prop"]` expressions)
   - Cross-check each referenced property against `dataset_column_info` — flag if property not found
   - Check filter references match column types (numeric comparison on a text column)

5. **Label integrity:**
   - If `label_config` is set, check `column` exists in `dataset_column_info`
   - Check label `placement` makes sense for the geometry type (e.g., `line` placement on a Polygon)
   - Flag labels without `haloColor`/`haloWidth` as `[LOW]` (readability concern, covered more in Subagent 4)

6. **Layer type consistency:**
   - Verify `layer_type` matches expectations:
     - `raster_geolens` should have null `dataset_geometry_type` (raster, not vector)
     - `vector_geolens` should have a non-null `dataset_geometry_type`
     - `geojson` layers should have geometry type set
   - Flag mismatches as `[HIGH]` — the layer may fail to render with the wrong adapter

**Output:** Finding list — Layer index | Severity | Check | Issue | Fix.

---

### Subagent 3: Performance

**Goal:** Identify map configuration choices that could cause slow rendering, excessive tile requests, or poor user experience.

**Process:**

1. **Layer count (effective):**
   - Count total logical layers from the map configuration
   - Estimate effective MapLibre layers: each fill layer generates 2–3 rendering layers (fill + outline + optional extrusion when `is_3d`), each labeled layer adds a symbol layer
   - Flag `[LOW]` if effective layers > 15, `[MEDIUM]` if > 25, `[HIGH]` if > 40
   - Each logical layer generates separate tile requests; many layers degrade pan/zoom performance

2. **Feature density:**
   - For each layer, check `dataset_feature_count`:
     - > 100,000 features without heatmap or clustering → flag `[MEDIUM]` (consider simplification at low zoom)
     - > 500,000 features → flag `[HIGH]` (will cause slow tile generation)
   - Check if high-feature-count layers have zoom constraints (label `minZoom`/`maxZoom` can help)

3. **Hidden layer waste:**
   - Count layers where `visible: false`
   - If > 50% of layers are hidden → flag `[MEDIUM]` (hidden layers don't load tiles but their sources remain registered, consuming memory; indicates poor map curation)
   - Suggest removing unused layers to reduce map complexity

4. **Expression complexity:**
   - Count the number of arms in data-driven `match` expressions
   - Flag `[LOW]` if > 15 categories, `[MEDIUM]` if > 30 (complex expressions slow style evaluation)
   - Check for deeply nested expressions (> 3 levels deep)

5. **Viewport appropriateness:**
   - Check initial `zoom` level vs. layer content:
     - Zoom 0–2 with dense point layers → flag `[MEDIUM]` (will render thousands of overlapping features)
     - Zoom > 18 with coarse data → flag `[LOW]` (user sees empty space between features)

6. **Heatmap performance:**
   - If heatmap layers exist, check `heatmap-radius`:
     - > 50px → flag `[MEDIUM]` (large radius = expensive GPU computation)
   - Check heatmap on datasets with < 100 features → flag `[LOW]` (too sparse for meaningful heatmap)

7. **Stacking overhead:**
   - Check for multiple polygon layers at opacity 1.0 — each fully occludes layers below it
   - Flag `[LOW]` — wasted rendering for occluded layers, or unintentional design

**Output:** Finding list — Severity | Concern | Evidence | Recommendation.

---

### Subagent 4: Design & Cartographic Quality

**Goal:** Assess whether this map is **well-designed and cartographically sound** — not just "are fields populated?" but "does this map communicate data effectively and look beautiful?" Evaluate visual hierarchy, color harmony, symbolization choices, label clarity, and overall polish.

**Process:**

1. **Visual hierarchy (most important check for beautiful maps):**
   - Determine the intended "hero" layer — the layer the map is about (usually the most prominent data layer)
   - Check: does the hero layer visually dominate via size, saturation, or contrast? If the hero layer is a subtle color while a background polygon layer is bright, the hierarchy is inverted → flag `[HIGH]`
   - Check: are supporting/contextual layers appropriately receded (lower opacity, less saturated, thinner strokes)?
   - Check: is the basemap subordinate to the data layers? (Bright basemap + subtle data = bad hierarchy)

2. **Cartographic layer order:**
   - Verify layers follow the cartographic stacking convention:
     - Bottom: raster/basemap layers
     - Middle: polygon (fill) layers
     - Upper: line layers
     - Top: point (circle) layers
     - Topmost: labels (symbol layers)
   - If point layers have lower `sort_order` than polygon layers → flag `[HIGH]` (points buried under polygons, invisible)
   - If `is_3d` extrusion layers are not above flat fill layers → flag `[MEDIUM]`

3. **Color palette quality:**
   - Extract the primary color from each layer's paint properties (`circle-color`, `fill-color`, `line-color`)
   - If all layers use the same default color (`#3b82f6`) → flag `[MEDIUM]` (uncustomized default palette — no visual differentiation)
   - If colors are too similar (same hue family, within ~30 degrees on the color wheel) → flag `[LOW]`
   - **Basemap contrast check:** If `basemap_style` is `openfreemap-positron` or any light basemap, flag layers with very light fill/circle colors (luminance > 0.7) as `[HIGH]` — nearly invisible. If dark basemap, flag very dark colors similarly.

4. **Color ramp semantic fit:**
   - For each layer with `style_config`:
     - If `mode: "graduated"` (choropleth/quantitative): check `ramp` is from `SEQUENTIAL_RAMPS` or `DIVERGING_RAMPS` — flag `[MEDIUM]` if using a qualitative ramp (e.g., `Set1`, `Set2`, `Accent`) for quantitative data (misleading — implies categories, not magnitude)
     - If `mode: "categorical"`: check `ramp` is from `QUALITATIVE_RAMPS` — flag `[LOW]` if using a sequential ramp (e.g., `Viridis`, `YlOrRd`) for categories (implies ordering where none exists)
   - Reference: `color-ramps.ts` exports `SEQUENTIAL_RAMPS`, `DIVERGING_RAMPS`, `QUALITATIVE_RAMPS`

5. **Color accessibility (colorblind safety):**
   - Check `style_config.ramp` against known colorblind-problematic ramps: `RdYlGn`, `RdGn`, `Set1` (red-green pairs), `YlOrRd` (in red-green context)
   - Flag `[LOW]` with recommendation: prefer `Viridis`, `Cividis`, `Plasma`, `Inferno` (perceptually uniform, colorblind-safe) or ColorBrewer palettes designed for accessibility
   - If multiple layers use red and green as distinguishing colors → flag `[MEDIUM]` (8% of males have red-green color vision deficiency)

6. **Label readability and hierarchy:**
   - For each layer with `label_config`:
     - Check `haloColor` and `haloWidth` are set → flag `[MEDIUM]` if missing (labels unreadable on varied backgrounds — this is the #1 label quality issue)
     - Check `fontSize` is reasonable (10–24 typical for web maps) → flag `[LOW]` if < 8 or > 32
     - Check `textColor` contrasts with likely basemap background
   - **Label size hierarchy:** If multiple layers have labels, check that font sizes are differentiated — the most important layer should have the largest labels. If all labeled layers use the same fontSize → flag `[LOW]` (flat hierarchy)
   - **Label density:** If `dataset_feature_count` > 10,000 and `label_config.minZoom` is absent → flag `[HIGH]` (MapLibre's collision detection discards most labels at low zoom, producing random-looking scattered labels)
   - **Basemap label interaction:** If `show_basemap_labels` is `false` and data labels exist, note this is intentional (avoids label competition). If `show_basemap_labels` is `true` and many data labels exist at similar zoom levels → flag `[LOW]` (potential label collision with basemap text)

7. **Basemap appropriateness:**
   - Check `basemap_style` against known preset IDs: `openfreemap-positron` (light), `openfreemap-dark` (dark), `openstreetmap` (standard), `openfreemap-bright` (colorful). Also check legacy keys in `LEGACY_KEY_MAP`: `positron`, `dark-matter`, `voyager`
   - If custom URL: verify it looks like a valid style URL (contains `://` or ends in `.json`)
   - If basemap is unrecognized and not a URL → flag `[MEDIUM]` (potentially invalid basemap ID)
   - Note: admin-configured custom basemaps use URL-style values and are valid

8. **Viewport defaults:**
   - If `center_lng`, `center_lat`, or `zoom` are null → flag `[MEDIUM]` (map opens at default world view instead of data extent)
   - If viewport is set but doesn't intersect any layer's `dataset_extent_bbox` → flag `[HIGH]` (map opens to empty area)
   - Check pitch/bearing — if `is_3d` layers exist and `pitch` is 0 → flag `[MEDIUM]` (3D extrusion invisible at flat pitch; recommend 30–60)
   - Non-zero pitch with 2D-only data is cosmetic (note but don't flag)

9. **Layer naming:**
   - Check each layer's `display_name`:
     - Null → uses dataset name (acceptable but may be a raw table name like `upload_abc123`)
     - Check if display_name equals `dataset_table_name` → flag `[LOW]` (raw table name, not a curated display label)
   - Check for duplicate display names across layers → flag `[LOW]` (confusing in legend)

10. **Legend configuration:**
    - Check `show_in_legend` for each layer:
      - All `true` (default) → fine, but note if any layers should probably be hidden
      - All `false` → flag `[MEDIUM]` (no legend content, viewers have no layer context)
      - Mix → fine (intentional curation)

11. **Widget configuration:**
    - If `widgets` array exists, check each widget ID against known valid IDs: `legend`, `measurement`, `scale`, `fullscreen`
    - Flag unknown widget IDs as `[LOW]`
    - If map has 3+ visible layers but no `legend` widget → suggest adding it

12. **Map metadata polish:**
    - Check `description` — null or empty → flag `[LOW]` (maps without descriptions are hard to find/understand in listings)
    - Check `notes` — useful for internal documentation but not required
    - Check `thumbnail_url` — null → flag `[LOW]` (map appears without preview in listings)

**Output:** Finding list — Severity | Aspect | Issue | Suggestion.

---

### Subagent 5: MapLibre Spec Compliance

**Goal:** Validate every paint, layout, and filter property against the MapLibre Style Spec. This is the strict technical compliance check — property names, expression syntax, enum values, and numeric ranges.

**Process:**

1. **Paint property validation:**
   - For each layer, enumerate every key in `paint` (excluding underscore-prefixed custom properties)
   - Verify each key is a valid MapLibre paint property for the target layer type (use the reference table)
   - Flag unknown or misspelled property names as `[HIGH]` (e.g., `fill-colour`, `circle-raduis`)

2. **Layout property validation:**
   - Enumerate every key in `layout`
   - Verify each is a valid MapLibre layout property (`visibility`, `line-cap`, `line-join`, `text-field`, `text-size`, `text-font`, `text-anchor`, `symbol-placement`, etc.)
   - Check enum values match the valid values table

3. **Expression syntax validation:**
   - For each paint/layout value that is an array (expression):
     - `["match", input, ...]` → verify even number of label/output pairs + 1 fallback
     - `["interpolate", interp, input, ...]` → verify `interp` is `["linear"]` or `["exponential", N]`; verify stop/output pairs are ordered
     - `["step", input, default, ...]` → verify stop/output pairs after default; stops must be ascending
     - `["case", ...]` → verify condition/output pairs + 1 fallback
     - `["get", "prop"]` → verify `"prop"` is a string
   - Flag expressions with incorrect arity as `[CRITICAL]` (map will fail to render the layer)

4. **Filter expression validation:**
   - If `filter` is set:
     - Check it uses the expression form `["==", ["get", "prop"], value]` not the deprecated `["==", "prop", value]`
     - Verify `["all", ...]` and `["any", ...]` contain valid sub-conditions
     - Verify comparison operators are valid: `==`, `!=`, `>`, `<`, `>=`, `<=`
     - Check `["has", "prop"]` and `["!has", "prop"]` have string arguments
     - Flag deprecated filter syntax as `[MEDIUM]` (still works but may break in future MapLibre versions)

5. **Numeric range validation:**
   - Check all opacity values are 0.0–1.0 (not 0–100)
   - Check `circle-radius` >= 0
   - Check `line-width` >= 0
   - Check `text-size` > 0 (if present)
   - Check `heatmap-radius` >= 1
   - Flag out-of-range values as `[HIGH]` (may cause rendering errors or invisible layers)

6. **Color format validation:**
   - For each color value in paint properties:
     - Must be a valid CSS color string: `#rgb`, `#rrggbb`, `#rrggbbaa`, `rgb()`, `rgba()`, `hsl()`, `hsla()`, named color
     - Must NOT be OKLCH (MapLibre does not support it)
     - Color values inside expressions (match/interpolate outputs) must also be valid
   - Flag invalid color formats as `[HIGH]`

**Output:** Finding list — Layer index | Severity | Property | Spec Violation | Fix.

---

### Subagent 6: Sharing & Access

**Goal:** Verify the map's sharing configuration is correct, secure, and functional.

**Process:**

1. **Visibility intent:**
   - Report the map's `visibility` setting: `private`, `internal`, or `public`
   - If `public`: check the visibility-check endpoint response — are all referenced datasets public-compatible?
   - Flag `[CRITICAL]` if public map references non-public datasets (data exposure risk)

2. **Share token health:**
   - From the share endpoint response:
     - If token exists: check expiry date — flag `[HIGH]` if already expired (broken share link)
     - If token exists: note any domain restrictions
     - If no token and map is public: flag `[LOW]` — no share link exists, viewers must know the direct URL
   - If share token exists, verify the shared view endpoint works: parse the `token` field from the share endpoint JSON response, then test it:
     ```bash
     # Extract SHARE_TOKEN from the share endpoint response JSON (the "token" field)
     curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/api/maps/shared/<token_value>/
     ```
     - Non-200 → flag `[HIGH]` (share link is broken)

3. **Thumbnail presence:**
   - Check if `thumbnail_url` is set
   - If set, verify the thumbnail is accessible:
     ```bash
     curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/api/maps/${MAP_ID}/thumbnail/
     ```
   - Missing thumbnail → flag `[LOW]` (map appears without preview in listings)

4. **Ownership:**
   - Check `created_by` — null → flag `[LOW]` (orphaned map, possibly from deleted user)
   - Check `created_by_username` — useful for audit trail

5. **Fork lineage:**
   - If `forked_from_id` is set (parse value from the INTAKE map summary output):
     - Verify source map still exists by fetching it:
       ```bash
       # Use the forked_from_id value from the INTAKE map summary
       curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/api/maps/<forked_from_id_value>/
       ```
     - Source deleted → flag `[LOW]` (orphaned fork, lineage broken — `forked_from_name` in INTAKE shows the original name)

6. **Update staleness:**
   - Check `updated_at` timestamp
   - If map has not been updated in > 90 days and has share tokens → flag `[LOW]` (stale shared map)

**Output:** Finding list — Severity | Check | Status | Fix.

---

## PLAYWRIGHT MCP VISUAL VERIFICATION (after subagents complete)

**Prerequisite:** The dev server must be running at `http://localhost:8080`. Before starting visual verification, check with `browser_navigate` to `http://localhost:8080`. If the server is not available, skip this section entirely and note: "Visual verification skipped — dev server not running at localhost:8080."

### Phase A: Authentication

1. Navigate to `http://localhost:8080`
2. If redirected to login, authenticate with admin credentials (`admin`/`admin`)
3. Verify login success by checking for the dashboard or maps list

### Phase B: Map Viewer Inspection

4. Navigate to the map viewer: `http://localhost:8080/maps/${MAP_ID}/view`
5. Wait for map to fully load (tiles rendered, layers visible):
   ```
   browser_wait_for("idle", timeout=10000)
   ```

6. **Full map screenshot:**
   - `browser_take_screenshot` — capture the rendered map
   - Verify: basemap loads, layers are visible (not blank), no error overlays
   - Check: are all layers from the configuration actually rendered?

7. **DOM inspection:**
   - `browser_snapshot` — inspect the accessibility tree
   - Check for console errors related to tile loading, style parsing, or missing sources
   - Verify: layer legend is present (if the map has a legend widget)
   - Verify: attribution text is visible

8. **Layer visibility verification:**
   - For each layer in the map configuration that has `visible: true`:
     - Check: is there visual evidence of the layer on the map? (colored features, raster tiles, heatmap gradient)
   - For layers with `visible: false`: verify they are NOT rendered

### Phase C: Theme Verification

9. **Dark mode:**
   - Toggle dark mode (click theme toggle in the header)
   - `browser_take_screenshot` — capture dark mode rendering
   - Check: map controls are readable (zoom buttons, attribution)
   - Check: no hardcoded white/black backgrounds bleeding through UI chrome
   - Check: legend text is readable against dark surface
   - Toggle back to light mode

### Phase D: Responsive Verification

10. **Mobile viewport:**
    - `browser_resize` to width=390px
    - `browser_take_screenshot` — capture mobile rendering
    - Check: map still fills the viewport
    - Check: controls are accessible (not overlapping, not cut off)
    - `browser_resize` back to width=1440px

### Phase E: Shared View (if applicable)

11. **Shared view verification (only if share token exists):**
    - Open a new tab or navigate to the shared URL: `http://localhost:8080/shared/${SHARE_TOKEN}`
    - `browser_take_screenshot` — capture shared view
    - Verify: map renders without authentication
    - Verify: no edit controls are visible (no builder UI, no save button)
    - Verify: layers and styles match the builder configuration

**Output:** Combine visual findings with `[VISUAL]` tag. Reference screenshots as evidence. Example: `[MEDIUM][VISUAL] Layer 2 (parcels) not rendering — map shows basemap only, no polygon features visible`

---

## SYNTHESIS (Serial — after all subagents and visual verification complete)

### Scoring

| Dimension | What it measures | Subagent |
|-----------|-----------------|----------|
| **Style Quality** | Paint/layout correctness, color validity, data-driven expressions, visual result | 1 |
| **Data Integrity** | Dataset references, column existence, sort order, filter/label validity | 2 |
| **Performance** | Layer count, feature density, expression complexity, viewport efficiency | 3 |
| **Design Quality** | Visual hierarchy, cartographic layer order, color harmony, ramp semantics, accessibility, label hierarchy, basemap contrast, viewport | 4 |
| **Spec Compliance** | MapLibre Style Spec conformance: property names, expressions, enums, ranges | 5 |
| **Sharing & Access** | Visibility, share tokens, data exposure, thumbnails, ownership | 6 |
| **Visual Verification** | Rendered state matches configuration, dark mode, responsive, shared view | MCP |

Grade each A–F:

- **A** — Excellent. No CRITICAL/HIGH findings, minimal LOW findings. Production-quality map.
- **B** — Good. No CRITICAL findings, <=2 HIGH, mostly LOW/MEDIUM. Ready to share.
- **C** — Adequate. <=1 CRITICAL or 3+ HIGH. Functional but needs polish before sharing.
- **D** — Poor. Multiple CRITICAL or HIGH. Map has rendering issues, broken layers, or access problems.
- **F** — Failing. Map does not render correctly, has data exposure risks, or is fundamentally misconfigured.

**Overall map health** = weighted average (Style Quality and Spec Compliance weighted 2x because they directly affect rendering correctness).

### Action Items

| Field | Description |
|-------|-------------|
| ID | Sequential (M-001, M-002, ...) |
| Priority | P0 (data exposure / rendering failure), P1 (incorrect output / broken feature), P2 (polish / optimization) |
| Severity | CRITICAL / HIGH / MEDIUM / LOW |
| Finding | One-sentence description |
| Layer | Which layer (index + name), or "Map" for map-level findings |
| Fix | One-sentence concrete fix |
| Dimension | Which audit dimension |

Sort by priority, then severity.

---

## DELIVERY

### Output format

Write the report to: `docs-internal/audits/map-audit-{MAP_ID_SHORT}-{YYYYMMDD}.md` where `MAP_ID_SHORT` is the first 8 characters of the map UUID. This prevents same-day collisions when auditing multiple maps.

### Report structure

```markdown
# Map Audit: {map_name} — {YYYY-MM-DD}

## Map Summary
<!-- ID, name, description, visibility, basemap, viewport, layer count, widgets, created/updated dates -->

## Scorecard
<!-- Letter grades per dimension + overall health -->

## Executive Summary
<!-- 3-5 sentences: map state, biggest gaps, top recommendation -->

## 1. Style Quality
<!-- Subagent 1 findings -->

## 2. Data Integrity
<!-- Subagent 2 findings -->

## 3. Performance
<!-- Subagent 3 findings -->

## 4. Design Quality
<!-- Subagent 4 findings -->

## 5. MapLibre Spec Compliance
<!-- Subagent 5 findings -->

## 6. Sharing & Access
<!-- Subagent 6 findings -->

## 7. Visual Verification
<!-- Playwright MCP screenshots + findings, organized by phase -->

## 8. Prioritized Action Items
<!-- Full action items table -->

## 9. Map Health Summary
<!-- Aggregate metrics:
  - Total findings by severity
  - Findings per dimension
  - Findings per layer
  - Top 3 recommendations
-->

## 10. Comparison to Prior Audit
<!-- If a previous map-audit-{MAP_ID_SHORT}-*.md exists for the SAME map in docs-internal/audits/:
  - Match findings by layer + property first, then by description similarity
  - Categorize: NEW, RESOLVED, REGRESSED, PERSISTENT
  - Summary: X new, Y resolved, Z persistent, W regressed
  - Only compare against audits for the same MAP_ID (matched by the MAP_ID_SHORT prefix)
-->
```

### Post-delivery

1. Print one-line summary: overall grade + P0 count + P1 count.
2. If any P0 findings exist, print them individually as a bulleted list.
3. If a previous `docs-internal/audits/map-audit-{MAP_ID_SHORT}-*.md` exists for the same map, note which findings are new vs resolved.

---

## WHAT NOT TO FLAG

Avoid false positives on these:

- **Hex colors in paint properties** — MapLibre cannot use CSS variables. Hex colors in paint properties are correct and expected.
- **GeoLens custom paint/layout properties** (all underscore-prefixed keys plus `outline-color` and `outline-width`) — see the full list in the Custom Properties reference table above. These are stripped before MapLibre rendering.
- **`line-dasharray` found in `layout`** — the line adapter stores dasharray in `layout` for UI convenience and extracts it to paint at render time. This is not a spec violation.
- **Default builder paint values** — standard defaults like `circle-color: "#3b82f6"`, `fill-color: "#3b82f6"`, `line-color: "#3b82f6"` are intentional default styling, not lazy configuration (unless all layers share the same default).
- **Empty layout objects** (`layout: {}`) — layout properties are optional in MapLibre; empty is valid.
- **`filter: null`** — no filter is a valid and common state.
- **`label_config: null`** — not all layers need labels.
- **`style_config: null`** — simple (non-data-driven) styling is the default and is fine.
- **`opacity: 1.0` for single layers** — only flag when multiple polygon layers stack and occlude each other.
- **`show_in_legend: true` for all layers** — this is the default; only flag if the legend is overwhelming.
- **Raster layers with minimal paint** (`raster-opacity` only) — raster layers use server-side rendering; client paint is typically opacity-only.
- **Missing `dataset_sample_values`** — this is optional enrichment data, not required for rendering.
- **`sort_order` starting from 0** — this is the default initial value.
- **Null `pitch` and `bearing`** — defaults to 0/0 (north-up, overhead view), which is standard.
- **Deprecated filter syntax in `filter` field** — if the filter was saved by an older version of the builder, legacy syntax is acceptable. Only flag if it causes functional issues.
- **`visibility: private`** — this is the default and most secure setting; do not suggest changing to public.

---

## RELATIONSHIP TO OTHER COMMANDS

- `/builder-audit` — audits the **builder UI code and implementation**. This command audits a **specific saved map's configuration data**. Builder-audit checks the tool; map-audit checks the output. Use builder-audit for code quality, use map-audit for map quality.
- `/design-audit` — audits design system conformance across the frontend. This command does not check UI design tokens, only map-specific paint/style values. No overlap.
- `/sec-audit` — audits the full application security surface. Subagent 6 of this command covers map-specific sharing and data exposure; `/sec-audit` covers OWASP, auth, injection, and infrastructure.
- `/post-impl` — audits code quality post-implementation. This command does not audit source code, only saved map data. No overlap.
- `/perf-profile` — profiles system-wide performance (queries, tiles, rendering). Subagent 3 of this command flags map-configuration-level performance concerns; `/perf-profile` measures actual response times and resource usage.
- `/ogc-compliance` — checks OGC/STAC endpoint standards. This command checks MapLibre Style Spec compliance for saved map data, not API standards. Different specs, no overlap.
