# /builder-audit — Map Builder Functionality, UX & Conventions Audit

Audit the GeoLens map builder end-to-end: layer management, style editing, filter building, labels, basemaps, share/embed, AI chat, terrain, map persistence, and the viewer. Covers functional correctness, UI/UX quality, state management hygiene, MapLibre Style Spec compliance, design token compliance, accessibility, responsive behavior, and error resilience. Every finding must reference a specific `file:line` and include a concrete fix.

**Usage:** `/builder-audit` (full audit) or `/builder-audit <area>` where area is `layers`, `styles`, `filters`, `labels`, `share`, `viewer`, `terrain`, `chat`, `ux`, `perf`, or `conventions`

Arguments: $ARGUMENTS

- Empty → full audit (all 9 audit dimensions)
- `layers` → Dimension 1 only (layer management)
- `styles` → Dimension 2 only (style editing)
- `filters` → Dimension 3 only (filter building)
- `labels` → Dimension 4 only (label configuration)
- `share`, `viewer`, or `terrain` → Dimension 5 only (share, embed, viewer, terrain)
- `chat` → Dimension 6 only (AI chat integration)
- `ux` → Dimension 7 only (UI/UX & accessibility)
- `perf` → Dimension 8 only (performance & rendering)
- `conventions` → Dimension 9 only (code conventions & patterns)

If `$ARGUMENTS` matches a scope keyword above, run only the corresponding dimension(s). Still run the full INTAKE — each dimension needs enough context to avoid false positives. In the SYNTHESIS, grade only the relevant dimension(s) and note the scoped execution.

**Codex execution note:** The subagent section below is Claude's parallel execution model. When running under Codex without explicit user approval for agents/delegation, do not skip coverage. Execute the same 9 dimensions in-process, using `rg --files`, `rg`, and parallel file reads where possible. Keep a coverage checklist and explicitly mark any dimension skipped with the reason.

---

## INTAKE (Serial — do this first)

> **Note:** Use the Read tool in Claude, or targeted Codex file reads in Codex. Prefer `rg --files` and `rg` for inventory/search. Do not rely on this historical file list alone; first confirm the current repository layout and adjust reads to active files.

### Step 0: Inventory the current builder surface

Run these searches before reading files so stale file names do not hide active code:

```bash
rg --files frontend/src/pages frontend/src/components/builder frontend/src/components/viewer frontend/src/hooks frontend/src/api backend/app/modules/catalog/maps backend/app/modules/embed_tokens backend/app/processing/ai e2e \
  | rg 'MapBuilder|Public.*Viewer|builder|viewer|maps|embed_tokens|processing/ai|builder.*spec|showcase|perf'

rg --files frontend/src/components/builder/layer-adapters frontend/src/components/builder/LayerStyleEditor
```

If a file named later in this command no longer exists, map it to the current equivalent and note the mapping in the audit report only when it affected scope.

### Step 1: Read the builder surface (frontend)

Discover with `rg --files`, then read in full — read what exists now, not a static list.

- **All `.tsx`/`.ts` in** `frontend/src/components/builder/` and its subdirs `hooks/`, `layer-adapters/`, `LayerStyleEditor/` (exclude `__tests__/`). This covers the unified stack + rows, layer/style/filter/label/popup editors, adapters, basemap/settings/DEM scenes, share, chat, and the sync/controller/contract modules.
- **Page, API, lib, tokens:** `frontend/src/pages/MapBuilderPage.tsx`; `frontend/src/api/maps.ts`; `frontend/src/hooks/use-maps.ts`; `frontend/src/lib/layer-capabilities.ts`, `lib/builder/basemap-style-mutation.ts`, `lib/color-ramps.ts`, `lib/basemap-utils.ts`, `lib/tile-utils.ts`; design tokens in `frontend/src/index.css` (first ~200 lines).

Load-bearing cross-cutting files an auditor should not overlook:

- `basemap-state-controller.ts` — canonical basemap/background/terrain/sublayer transitions
- `map-composition-sync.ts` + `map-sync.ts` — shared builder/viewer source/layer/background/terrain ordering
- `builder-action-contract.ts` — typed layer-action boundary shared by manual UI and AI chat
- `hooks/builder-layer-mutations.ts` (duplicate-rendering + companion cleanup); `hooks/use-builder-editor-scene.ts` (editor-scene routing + synthetic basemap/settings layers)
- `map-stack.ts` / `folder-groups.ts` / `selection-utils.ts` — stack grouping, persistence, multi-select
- `color-relief-sync.ts` (DEM color-relief, live). DEM contour was **cut in v1032** — there is no `contour-sync.ts` file and no `CONTOUR_CONTROL_ENABLED` flag; an absent contour control is expected, not a finding (see WHAT NOT TO FLAG)

### Step 2: Read the backend map + AI-chat services

- **Maps:** all of `backend/app/modules/catalog/maps/` (`models`, `router`, `service*`, `schemas`, `style_json`, `sprites`).
- **Embed tokens + edition:** all of `backend/app/modules/embed_tokens/` (`models`, `router`, `service`, `schemas`); `frontend/src/hooks/use-edition.ts`; `frontend/src/api/edition.ts`.
- **AI chat (builder-integration scope only):** `backend/app/processing/ai/` — `router.py`, `chat_service.py`, `chat_actions.py`, `chat_validation.py`, `chat_styles.py`, `chat_geojson.py`, `chat_constants.py`, `tools.py`, `schemas.py`, `streaming.py`, `llm_loop.py`. Generation-quality files (`sql_generator.py`, `metadata_*`, `service.py`, `token_usage.py`, prompts) belong to `/ai-optimize`, not this audit.

### Step 3: Read the viewer / embed surface

- Pages: `frontend/src/pages/MapViewerGate.tsx`, `PublicViewerPage.tsx`, `PublicMapViewerPage.tsx`
- Viewer: all of `frontend/src/components/viewer/` — `ViewerMap.tsx`, `LayerLegend.tsx`, `layer-identity.ts`, and `hooks/use-viewer-layers.ts`, `use-viewer-tokens.ts`, `use-viewer-terrain.ts`

### Step 4: Map the API surface

Use `rg` for these searches:

```bash
# All map/builder endpoints
rg -n "@router\\.(get|post|put|patch|delete)" backend/app/modules/catalog/maps/router.py

# Tile endpoints (used by builder layers)
rg -n "@router" backend/app/processing/tiles/ -g "*.py"

# Share/embed token endpoints
rg -n "share|embed" backend/app/modules/catalog/maps/router.py backend/app/modules/embed_tokens/ -g "*.py"

# AI chat endpoints (used by builder chat panel)
rg -n "@router\\.(get|post|put|patch|delete)" backend/app/processing/ai/router.py

# Thumbnail endpoints
rg -n "thumbnail" backend/app/modules/catalog/maps/router.py
```

---

## MAP BUILDER REFERENCE (Embedded)

These are the expected behaviors and patterns. Deviations are findings.

### v1027 architecture contracts

- Basemap/background/terrain/sublayer edits SHOULD flow through `basemap-state-controller.ts`; direct partial `basemap_config` object surgery is a finding when it can drop sibling fields such as `background_color`, `basemap_position`, or `sublayer_overrides`
- Builder and viewer composition changes SHOULD use `map-composition-sync.ts` or its underlying shared `map-sync` primitives; duplicating source/layer/background/terrain ordering in one surface only is a parity risk
- Editor scene routing SHOULD use `use-builder-editor-scene.ts`; duplicated synthetic basemap/settings layer descriptors in desktop/mobile editor paths are a maintainability finding
- Layer mutations SHOULD flow through the typed action boundary — the `BuilderLayerAction` union/types live in `builder-action-contract.ts`, while the `dispatchLayerAction` dispatcher is implemented in `hooks/use-builder-layers.ts`; manual remove must stay persisted, while AI/chat remove must stay draft-only until global map Save
- Duplicate rendering SHOULD use `buildDuplicateRenderingInput()` so sibling renderings keep collision-free names/sort order and do not copy transient live-only state
- Layer editor save semantics are immediate preview plus global map Save. A missing per-layer "Save style" button is not automatically a bug; instead verify dirty-state clarity, pending preview messaging, save/reload fidelity, and user expectation risk
- Backend `ChatAction` schemas are not automatically touched by frontend action-boundary work. If chat schemas/tools change, refresh OpenAPI/SDK; if they do not, document the no-backend-change decision

### MapLibre Style Spec compliance

All generated paint, layout, and filter properties MUST conform to the MapLibre Style Spec (compatible with Mapbox Style Spec v8). Specifically:

- Property names MUST be valid for the target layer type (e.g., `circle-*` only on type `"circle"`, `fill-*` only on type `"fill"`, `line-*` only on type `"line"`, `raster-*` only on type `"raster"`, `heatmap-*` only on type `"heatmap"`)
- DEM Hillshade controls MUST expose only MapLibre-supported hillshade paint properties. `hillshade-illumination-direction` and `hillshade-exaggeration` are supported; a Sun/Altitude control is a finding unless it is backed by a real supported render effect.
- Expression syntax MUST follow the spec grammar — `["match"]`, `["interpolate"]`, `["step"]`, and `["case"]` expressions must have correct arity and argument types
- Filter expressions MUST use the spec-compliant expression form (`["==", ["get", "prop"], value]`), not the deprecated legacy form (`["==", "prop", value]`)
- Color values in paint properties MUST be valid CSS color strings (hex, rgb, rgba, hsl, hsla, or named colors) — NOT OKLCH (MapLibre does not support OKLCH in paint/layout properties)
- Enum properties (e.g., `line-cap`, `line-join`, `text-anchor`, `symbol-placement`, `text-justify`) MUST use spec-defined values only
- Numeric ranges MUST respect spec limits (e.g., opacity 0–1, circle-radius ≥ 0, line-width ≥ 0)

### Layer management invariants

- Layer order in the sidebar MUST match MapLibre rendering order (top of list = top of map)
- Removing a layer MUST remove its MapLibre source AND all associated layers (fill, stroke, label, etc.)
- Toggling visibility MUST toggle all sublayers (fill + stroke + label + heatmap) atomically
- Layer rename MUST NOT cause a re-render or source reload
- Layer drag-reorder MUST update both UI state AND MapLibre `moveLayer()` calls
- Adding a duplicate dataset MUST be allowed (same source, independent style)
- Duplicating a layer MUST create an independently editable rendering, select the new layer, and leave the user in a useful editing context
- Removing the basemap MUST switch to the blank/no-basemap state, hide the basemap group row, close stale basemap editors, and preserve all user data layers
- Ephemeral (unsaved query) layers MUST be visually distinguished from persisted layers
- Ephemeral layers MUST be promotable to permanent layers or discardable without side effects
- Layer capability gates MUST be enforced — raster layers MUST NOT show filter/label/style editors

### Style editing invariants

- Color pickers MUST use the design system color format (OKLCH preferred for UI chrome, hex/rgb for MapLibre paint props)
- Opacity sliders MUST produce values in 0.0–1.0 range (not 0–100%)
- Data-driven style changes MUST update the MapLibre paint/layout property immediately (no save-then-reload)
- Style edits MUST mark the map dirty and persist through the global map Save control; do not assume a per-layer "save style" button unless the product contract changes
- Switching style modes MUST be reversible: solid → data-driven/gradient → solid must clear stale paint expressions, companion layers, and builder metadata from the previous mode
- Style mutation code SHOULD flow through adapters, normalizers, or explicit pure helpers; ad hoc object spreads are findings when they can drop sibling fields or leave stale MapLibre keys behind
- Circle radius MUST be in pixels (MapLibre default), not map units
- Stroke dash arrays MUST produce valid MapLibre `line-dasharray` values (array of positive numbers)
- Heatmap configuration MUST include radius, intensity, and color ramp controls
- Style changes MUST NOT cause the map to re-fetch tiles (paint properties are client-side)
- Each layer adapter MUST only produce paint/layout properties valid for its layer type per the Style Spec
- DEM Hillshade exaggeration MUST stay in MapLibre's 0-1 range; DEM Terrain exaggeration is separate, layer-owned, and clamps through `map.setTerrain` using terrain-safe bounds. Do not reuse one control path for both.
- DEM color-relief (hypsometric tint) MUST emit a native MapLibre `color-relief` layer with a `color-relief-color` elevation→color ramp; builder-internal `_hypso-*` control keys MUST be stripped before the paint reaches MapLibre. DEM contour was cut in v1032 (no `contour-sync.ts`, no `CONTOUR_CONTROL_ENABLED` flag) — an absent contour UI is not a finding.
- Fill pattern styling MUST register the sprite/image before referencing it in `fill-pattern`, and switching between solid fill and pattern fill MUST clear the unused property so no stale `fill-pattern`/`fill-color` is left behind.
- The per-layer raw JSON escape hatch (`LayerStyleEditor/AdvancedJsonEditor.tsx`) writes user-authored `paint`/`layout` directly back to the layer. It MUST validate input against the Style Spec for the target layer type, surface parse/validation errors inline (never silently swallow or corrupt the layer), and round-trip through save/reload. This is distinct from the read-only whole-style `StyleJsonDialog` (view + download).

### Label and symbol rendering invariants

- Point `render_mode: "symbol"` MUST be presented to users as **Symbols** (or equivalent icon/symbol wording), not as **Labels**. It controls the primary point renderer: icon layout, symbol sprite selection, and optional text within the same MapLibre `symbol` layer.
- Feature labels are independent layer decoration backed by `label_config`. Label controls MUST be available for label-capable vector layers based on `getLayerCapabilities()`, not only when a point layer is in symbol render mode.
- Non-symbol vector layers with `label_config.column` MUST render labels as a companion MapLibre `symbol` layer (`*-label`) and keep filters, visibility, ordering, save/reload, viewer, and embed rendering in parity with the parent layer.
- Symbol-rendered point layers with `label_config.column` MUST consolidate icon and text in the primary symbol layer rather than creating a duplicate companion label layer.
- Heatmap and raster/DEM render modes MUST NOT expose feature-label controls or emit feature-label layers.

### Filter building invariants

- Filters MUST produce valid MapLibre filter expressions (`["all", ...]` or `["any", ...]`)
- Removing all filter conditions MUST clear the filter entirely (not produce an empty `["all"]`)
- Filter values MUST be type-coerced to match the property type (string vs number vs boolean)
- Filters MUST survive save/load round-trips without mutation
- Filter preview count (if shown) MUST match actual filtered features
- Property dropdown MUST be populated from the dataset schema, not from visible features only

### MapLibre integration patterns

- `transformRequest` MUST be set imperatively via `map.setTransformRequest()` in `onLoad` callback (v8 bug: prop is ignored)
- Vector tile sources MUST be added imperatively via `map.addSource()` / `map.addLayer()` (declarative `<Source>/<Layer>` unreliable for vector tiles)
- GeoJSON sources MAY use declarative JSX
- Auth tokens MUST be injected into tile requests via `transformRequest`, not embedded in source URLs
- Layer IDs MUST be deterministic and stable across re-renders (no random suffixes that cause flicker)

### Basemap, terrain, and map settings invariants

- `MapBasemapConfig` is the canonical map-level persistence container for basemap appearance: labels, roads, boundaries, buildings, land/water tone, relief contrast, opacity, position, background color, and sublayer overrides
- Basemap config normalizers MUST preserve unrelated optional fields such as `basemap_position`, `background_color`, and `sublayer_overrides` when updating one setting
- Map Settings MUST expose map background color under Appearance; the setting must apply in builder and viewer, save/reload cleanly, and reset to the basemap default
- Explicit map background color MUST win over land/water tone for MapLibre `background` layers; wrapped raster and blank basemaps must still include a background layer so the setting has a target
- Terrain exaggeration UI and render-time clamps MUST share the same bounds; extreme slider values must not create unusable distortion and missing terrain sources must fail gracefully
- DEM Hillshade overlays must be audited against layer order and opacity: high-opacity raster imagery above hillshade can mask relief and make working controls appear broken. Verify maps intended for a relief/marketing look place hillshade above imagery or intentionally document the order.
- Viewer rendering MUST match builder rendering for basemap config, terrain config, layer styles, filters, labels, and widget availability <!-- v1036: "widget" → "plugin" rename pending (RENAME-TOOL-01, phase 1164) -->

### State management patterns

- Server state (map list, map data, datasets) → React Query with appropriate stale times
- Builder working state (layers, styles, filters) → colocated hook-local state (NOT zustand) until save
- Builder hooks are colocated at `frontend/src/components/builder/hooks/` (NOT `frontend/src/hooks/`)
- Global UI state (auth, theme) → zustand stores
- URL state (map ID, view params) → URL search params
- Optimistic updates for save operations → React Query mutation with `onMutate`/`onError` rollback
- Dirty state tracking → builder MUST warn before navigating away with unsaved changes
- Layer capabilities → centralized in `frontend/src/lib/layer-capabilities.ts` (UI must respect gates)

### Viewer/embed invariants

- Viewer MUST render without authentication (public maps)
- Viewer MUST NOT expose edit controls
- Viewer MUST respect share token expiry (backend-enforced, frontend graceful)
- Share links MUST use the raw one-time share token in the `/m/{token}` route. `token_hint` is non-secret metadata for display/audit/admin lists only and MUST NOT be used to build open/copy/share URLs.
- Embed iframe MUST NOT include navigation chrome
- Embed MUST respect domain restrictions with backend enforcement. Validate Origin when present, fall back carefully to Referer when needed, apply CSP `frame-ancestors` on shared-map responses, and ensure tile requests carry the embed token through headers or an explicitly supported safe fallback.
- Embed iframe sandboxing MUST be deliberate and documented; do not weaken sandbox attributes to fix domain/origin issues without a security review.
- Attribution MUST be visible on all viewers (MapLibre, basemap, data source)
- Edition behavior MUST be explicit:
  - Community hides advanced sharing controls and backend rejects custom share expiration, custom embed token lifetimes, and non-empty domain restrictions
  - Community still preserves basic share link create/revoke, public/internal/private visibility changes, and default unrestricted embed token creation
  - Enterprise overlay permits advanced controls (custom expiration/lifetimes/domain restrictions) without changing Community source

### Regression smoke seeds

When a full audit has a live map available, run these UAT checks before synthesis; they exercise the invariants above (don't re-derive the rationale here). Record console errors, warnings, failed network requests, and screenshots for a representative high-res / tight-AOI map (e.g. the marketing/showcase map).

- Line color mode: data-driven/gradient → solid → data-driven (preview + save/reload + independent duplicates)
- Terrain exaggeration: low/default/high (clamp, no severe distortion, viewer restore after save)
- DEM hillshade: azimuth + exaggeration (canvas changes, no unsupported Altitude control, imagery doesn't mask relief)
- DEM terrain: layer-owned exaggeration low/default/high (distinct from hillshade exaggeration)
- DEM color-relief: enable hypsometric tint (native `color-relief` layer renders; `_hypso-*` keys stripped)
- Basemap removal: row hides, editor closes, data layers remain, re-add doesn't reset styles
- Layer duplication: new row selected, style editor opens, original unmutated
- Map background color: set, reset, save/reload, builder/viewer parity
- Labels vs Symbols: Render as offers Point/Symbols/Heatmap (+Cluster when eligible); Labels-tab availability per mode; badges distinguish Symbols from Labels
- AI chat compat: changed action/style/filter/label/basemap contracts still produce valid builder mutations via the frontend bridge; missing provider keys don't block non-AI workflows
- Save/reload close gate: after any basemap/background/terrain/style mutation → save → reload → spot-check viewer/embed when access permits

### Existing test gates to prefer before ad hoc checks

Use the narrowest relevant gate that matches the audit scope, and record exact results:

```bash
# Builder smoke flows
npm run e2e:smoke:builder
npm run e2e:smoke:builder-hardening

# Builder perf/large-map smoke
npm run e2e:smoke:perf

# Focused frontend tests
cd frontend && npm run test -- <relevant builder/viewer test files>

# Focused backend map/share/style tests
cd backend && uv run pytest <relevant tests> -q
```

If a gate cannot run because the stack, browser state, fixtures, or database are unavailable, record the blocker and use the best available unit/static checks.

---

## SUBAGENT DISPATCH (Parallel — 9 subagents when the runtime supports and the user allows agents)

Claude orchestration: run these subagents in parallel using the Agent tool. Do NOT wait for one to finish before starting the next. Collect all results before proceeding to SYNTHESIS.

Codex/no-agent execution: run the same dimensions in-process. Use the dimension headings below as a required checklist; do not downgrade a full audit to a partial audit just because subagents are unavailable.

Each subagent must:

1. Read all relevant source files (not just search hits — read the full implementation)
2. Produce a numbered finding list with `file:line` references
3. Label each finding with its severity tag: `[CRITICAL]`, `[HIGH]`, `[MEDIUM]`, `[LOW]`
4. Include evidence (code snippet or behavioral description) for every finding
5. Include a concrete one-sentence fix for every finding
6. Cap output at **30 findings maximum** — if more exist, include the top 30 by severity and note how many were omitted

---

### Subagent 1: Layer Management

**Goal:** Verify layer lifecycle correctness — add, remove, reorder, toggle, rename, duplicate, and undo.

**Process:**

1. **Layer addition flow:**
   - Read the dataset search/add workflow end-to-end (`DatasetSearchPanel.tsx` → `use-builder-layers.ts`)
   - Verify: adding a layer creates both the UI state entry AND the MapLibre source+layer
   - Verify: default style is applied based on geometry type (point→circle, line→line, polygon→fill)
   - Verify: adding a layer does not reset other layers' styles or filters
   - Check: does adding a dataset with no geometry type fail gracefully?

2. **Layer removal flow:**
   - Verify: removing a layer removes the MapLibre source AND all sublayers (fill, stroke, label, heatmap)
   - Check for orphaned sources or layers after removal (sources still registered but no layers reference them)
   - Verify: removing the last layer produces a clean empty state (no stale map artifacts)

3. **Layer reorder:**
   - Read the drag-reorder implementation in `UnifiedStackPanel.tsx`, `StackRow.tsx`, `map-stack.ts`, and `use-builder-layers.ts`
   - Verify: reorder updates both the UI array AND calls `map.moveLayer()` for every affected sublayer
   - Check: does reorder handle the case where sublayers (fill + stroke + label) must move together?
   - Verify: reorder is persisted on save

4. **Layer visibility toggle:**
   - Verify: toggling visibility sets `visibility: "none"` / `"visible"` on ALL sublayers atomically
   - Check: does toggling visibility affect filter state? (It shouldn't)
   - Check: does toggling back to visible restore the correct style? (Not a default style)

5. **Layer rename:**
   - Verify: rename updates UI label without causing a source reload or re-render flash
   - Check: rename with empty string — is it prevented?

6. **Duplicate dataset layers:**
   - Verify: adding the same dataset twice creates independent layers with independent styles
   - Check: do the two layers share a MapLibre source or have separate sources?

7. **Ephemeral (query) layers:**
   - Read `use-ephemeral-layers.ts` and `EphemeralBadge.tsx`
   - Verify: AI chat SQL query results create ephemeral layers (visually distinct from persisted layers)
   - Check: can an ephemeral layer be promoted to a permanent layer?
   - Check: can an ephemeral layer be discarded without affecting other layers?
   - Verify: ephemeral layers are not included in the save payload (until promoted)
   - Check: what happens to ephemeral layers on page refresh? (Should be lost, not persisted)

8. **Layer capability gates:**
   - Read `frontend/src/lib/layer-capabilities.ts`
   - Verify: raster layers do NOT show filter, label, or style editors (only opacity)
   - Verify: VRT layers behave the same as raster (opacity only)
   - Check: does `getLayerCapabilities()` correctly classify all layer_type values?

9. **Layer inspector orchestration:**
   - Read `LayerEditorPanel.tsx` and `use-builder-editor-scene.ts`
   - Verify: selecting a layer opens the inspector with the correct editor tabs (style, filter, label) based on layer capabilities
   - Verify: switching between layers updates the inspector content without stale state
   - Check: deselecting a layer closes the inspector cleanly

10. **Undo/redo:**
    - Check: is there an undo mechanism for layer operations (add, remove, style change, filter change)?
    - If undo exists: verify it restores both UI state and MapLibre map state
    - If undo does not exist: do not automatically flag it unless the UI promises undo or the operation is irreversible before global Save. Flag broken or incoherent undo behavior when an undo affordance exists.

11. **Folder groups and bulk actions:**
    - Read `folder-groups.ts`, `FolderGroupRow.tsx`, `BulkActionBar.tsx`, and related tests
    - Verify: grouping/ungrouping, bulk visibility, bulk opacity, and bulk delete preserve sort order, dirty state, selection state, and save/reload fidelity
    - Check: group rows never render as data layers and are excluded from tile/style operations

**Output:** Finding list — ID | Severity | Description | File:line | Fix.

---

### Subagent 2: Style Editing

**Goal:** Verify the style editing UI produces correct MapLibre paint/layout properties for every geometry type and data-driven mode. All properties must conform to the MapLibre Style Spec.

**Process:**

1. **Fill styling (polygons):**
   - Read `LayerStyleEditor/FillEditor.tsx`, `layer-adapters/fill-adapter.ts`, `FillPatternPicker.tsx`, and `layer-adapters/fill-pattern-images.ts`
   - Verify: fill-color, fill-opacity, fill-outline-color map to correct MapLibre properties
   - Check: does fill-opacity accept values outside 0–1? (Should clamp)
   - Verify: fill-antialias is handled
   - Verify: fill-pattern registers its sprite/image before use, and toggling solid↔pattern clears the unused `fill-pattern`/`fill-color`
   - Verify: adapter only produces properties valid for layer type `"fill"` per the Style Spec

2. **Stroke/line styling:**
   - Read `layer-adapters/line-adapter.ts`
   - Verify: line-color, line-width, line-opacity, line-dasharray produce valid MapLibre values
   - Check: dash array input — are invalid values (negatives, zeros, non-numbers) rejected?
   - Verify: line-cap and line-join options use spec-defined enum values only (`"butt"`, `"round"`, `"square"` for cap; `"bevel"`, `"round"`, `"miter"` for join)

3. **Circle styling (points):**
   - Read `layer-adapters/circle-adapter.ts`
   - Verify: circle-radius, circle-color, circle-opacity, circle-stroke-width, circle-stroke-color
   - Check: minimum circle radius — does the UI prevent radius=0?
   - Check: very large radius values — any guardrails?

4. **Data-driven styling:**
   - Read `DataDrivenStyleEditor.tsx`, `ColorRampPicker.tsx`, `ZoomExpressionEditor.tsx`, `LineGradientControls.tsx`, and color ramp utilities
   - Verify: categorical styles produce valid `["match", ...]` expressions with correct arity (match, input, label1, output1, ..., fallback)
   - Verify: graduated styles produce valid `["interpolate", ...]` or `["step", ...]` expressions with correct arity
   - Check: what happens when the selected property has null values? (Should handle gracefully)
   - Check: does changing the property reset the breaks/categories correctly?
   - Verify: color ramp preview matches applied map colors
   - Regression check: for line layers, switch from data-driven/gradient color back to solid color and then back to data-driven; stale expressions and builder metadata must not break subsequent edits

5. **Heatmap styling:**
   - Read `layer-adapters/heatmap-adapter.ts` and `HeatmapStyleControls.tsx`
   - Verify: heatmap-radius, heatmap-intensity, heatmap-opacity, heatmap-color are configurable
   - Check: is heatmap-weight supported for weighted heatmaps?
   - Verify: switching from heatmap to another style type cleans up heatmap layers

6. **Raster layer styling:**
   - Read `layer-adapters/raster-adapter.ts` and `RasterLayerControls.tsx`
   - Verify: raster-opacity is configurable
   - Check: are band selection or color mapping controls present for COG/raster sources?

7. **Symbol, cluster, hillshade, and DEM styling:**
   - Read `layer-adapters/symbol-adapter.ts`, `layer-adapters/cluster-adapter.ts`, `layer-adapters/hillshade-adapter.ts`, `LayerStyleEditor/SymbolEditor.tsx`, `LayerStyleEditor/ClusterEditor.tsx`, `DEMEditorScene.tsx`, and `color-relief-sync.ts`
   - Verify: symbol icon/text layout, cluster paint/layout, and hillshade paint properties are valid for their MapLibre layer types
   - Verify: mode switches remove incompatible companion layers and stale paint/layout keys
   - Verify: DEM image, DEM hillshade, DEM terrain, and DEM color-relief (hypsometric tint) modes stay distinct in UI state and render-time sync; builder-internal `_hypso-*` keys never reach the MapLibre paint
   - Note: DEM contour was cut in v1032 (no `contour-sync.ts` file, no `CONTOUR_CONTROL_ENABLED` flag) — do not flag the absent contour UI

8. **Layer adapter registry:**
   - Read `layer-adapters/registry.ts`, `layer-adapters/shared.ts`, and `layer-adapters/types.ts`
   - Verify: `getAdapter()` returns the correct adapter for every layer type (fill, line, circle, raster, heatmap, symbol, cluster, hillshade)
   - Verify: `resolveAdapterType()` in `shared.ts` correctly maps geometry types to adapter types
   - Verify: `simplifyPaint()` and `stripCustomProps()` don't discard valid MapLibre properties
   - Check: what happens if `getAdapter()` is called with an unknown layer type? (Should fail gracefully)

9. **Style color picker:**
   - Read `StyleColorPicker.tsx`
   - Verify: color values emitted to MapLibre paint properties are valid CSS color strings (hex, rgb, rgba), NOT OKLCH
   - Check: does the picker support opacity/alpha channel?

10. **Style JSON surfaces (read-only export + editable escape hatch):**
   - Read `StyleJsonDialog.tsx`, `backend/app/modules/catalog/maps/style_json.py`, and `LayerStyleEditor/AdvancedJsonEditor.tsx`
   - Verify: `StyleJsonDialog` renders a read-only view + download of the raw style spec; exported JSON is MapLibre-valid for builder-authored layers, companion layers, raster/DEM/hillshade, terrain blocks, sprites, and metadata
   - Verify: `AdvancedJsonEditor` (per-layer, editable) parses user `paint`/`layout`, validates against the Style Spec for the layer type, surfaces parse/validation errors inline, and does not silently corrupt the layer on bad input
   - Check: is each surface reachable from the UI (dev tool, hidden panel, layer-editor section)?

11. **Style persistence:**
    - Verify: every style property set in the UI is included in the save payload
    - Verify: loading a saved map restores every style property exactly
    - Check: are there any style properties that exist in the UI but are not persisted (or vice versa)?
    - Check: style edits use the global map Save/dirty-state model consistently; if users can mistake live preview for persisted state, flag the missing affordance as a UX finding rather than adding an implicit per-layer save

**Output:** Finding list with geometry type × property × correctness status.

---

### Subagent 3: Filter Building

**Goal:** Verify the filter builder produces correct, type-safe MapLibre filter expressions (per the Style Spec) that survive round-trips.

**Process:**

1. **Filter expression generation:**
   - Read `LayerFilterEditor.tsx`, `ActiveFilterChips.tsx`, and supporting utilities
   - Verify: AND mode produces `["all", condition1, condition2, ...]`
   - Verify: OR mode produces `["any", condition1, condition2, ...]`
   - Verify: each condition operator (`==`, `!=`, `>`, `<`, `>=`, `<=`, `in`, `!in`, `has`, `!has`) produces the correct MapLibre filter expression using the **expression form** (`["==", ["get", "prop"], value]`), not the deprecated legacy form (`["==", "prop", value]`)

2. **Type coercion:**
   - Check: if a property is numeric, are filter values coerced to numbers? (String "42" vs number 42)
   - Check: boolean properties — does the filter handle `true`/`false` vs `"true"`/`"false"`?
   - Check: null/empty values — can the user filter for null or missing properties?

3. **Property enumeration:**
   - Verify: the property dropdown is populated from the dataset schema (backend metadata), not from the first N visible features
   - Check: what happens for datasets with very many properties (100+)? Is the dropdown manageable?

4. **Edge cases:**
   - Removing all conditions: does the filter clear completely, or leave a stale empty wrapper?
   - Adding a condition with no value: is it prevented or ignored?
   - Switching between AND/OR: does it re-wrap existing conditions correctly?
   - Filters on properties with special characters in names (spaces, dots, brackets)

5. **Round-trip fidelity:**
   - Verify: saving a map with filters and reloading restores the exact same filter expressions
   - Check: does the visual filter builder parse an existing MapLibre filter expression back into UI state? (Important for edit mode)
   - Check: are there filter expressions the backend can produce that the visual builder cannot represent? (If so, is there a "code mode" fallback?)

6. **Filter application:**
   - Verify: filters are applied to the MapLibre layer via `setFilter()`, not by re-fetching tiles
   - Check: does applying a filter update immediately (no save required)?
   - Verify: filters apply to ALL sublayers of the logical layer (fill + stroke + label)

7. **Active filter chips:**
   - Read `ActiveFilterChips.tsx`
   - Verify: active filters are displayed as removable chips
   - Check: removing a chip updates the filter immediately (both UI state and MapLibre)
   - Check: chips display human-readable labels (not raw expression syntax)

**Output:** Finding list — operator coverage matrix + edge case results.

---

### Subagent 4: Label Configuration

**Goal:** Verify label editing produces correct MapLibre `text-*` and `symbol-*` layout/paint properties per the Style Spec.

**Process:**

1. **Label properties:**
   - Read `LabelEditor.tsx`, `label-layer-utils.ts`, `renderAs.ts`, and `layer-adapters/symbol-adapter.ts`
   - Verify: text-field references a valid dataset property
   - Verify: text-size, text-color, text-opacity map correctly
   - Verify: text-halo-color and text-halo-width are supported (critical for readability over varied backgrounds)
   - Check: text-font — does the builder specify a font stack available in the basemap glyphs?
   - Verify: point symbol render mode is labeled as Symbols/icon rendering, not as Labels

2. **Label placement:**
   - Verify: text-anchor options use spec-defined values only (`"center"`, `"left"`, `"right"`, `"top"`, `"bottom"`, `"top-left"`, `"top-right"`, `"bottom-left"`, `"bottom-right"`)
   - Verify: text-offset is configurable
   - Check: for point layers, does symbol-placement default to `"point"`?
   - Check: for line layers, does symbol-placement offer `"line"` and `"line-center"`?
   - Check: for polygon layers, is the label placed at centroid?

3. **Label collision:**
   - Verify: text-allow-overlap default (should be false for clarity, but user-configurable)
   - Check: icon-allow-overlap alignment if icons are present

4. **Label toggle:**
   - Verify: enabling/disabling labels on non-symbol vector layers adds/removes only the companion symbol layer, not the base layer
   - Verify: enabling/disabling labels on symbol-rendered point layers updates the primary symbol layer text properties without creating a duplicate companion label layer
   - Check: toggling labels off and back on preserves all label settings

5. **Label persistence:**
   - Verify: all label properties are saved and restored correctly

6. **Label UI availability:**
   - Verify: the Labels tab is available for point/line/polygon vector layers that support labels, independent of point symbol render mode
   - Verify: the Labels tab is hidden for heatmap, raster, DEM image, DEM hillshade, and DEM terrain render modes
   - Verify: stack badges distinguish Symbols render mode from Labels enabled state

**Output:** Finding list — property × supported × correct.

---

### Subagent 5: Share, Embed, Viewer & Terrain

**Goal:** Verify the share workflow, embed token management, public/embedded viewer, and terrain toggle render correctly and securely.

**Process:**

1. **Share workflow (frontend):**
   - Read `SharePanel.tsx` and associated components
   - Verify: share token creation flow — user creates token, gets a link, link works
   - Verify: raw share tokens are treated as one-time secrets; `token_hint` is display/audit metadata only and is never used for copy/open URLs
   - Check edition gates: in Community, token expiry UI is hidden and share creation does not send `expiresAt`; in Enterprise, token expiry UI is visible, validates no past dates, and persists successfully
   - Check: copy-to-clipboard functionality — does it give feedback on success?
   - Verify: share link uses the current route contract (`/m/{raw_token}` unless the product intentionally changes it)
   - Check: revoking a share token — is it reflected immediately in the UI and remains available in Community

2. **Embed workflow:**
   - Verify: embed code generation produces a valid `<iframe>` snippet
   - Check: embed iframe URL points to the correct viewer route
   - Check edition gates: in Community, domain restrictions UI is hidden, `allowedOrigins` is never sent, and default 30-day unrestricted embed tokens still generate; in Enterprise, allowed domains can be added/removed
   - Check custom lifetimes: if the UI exposes embed token lifetime controls, Community must hide/reject custom lifetimes while Enterprise permits them
   - Verify: embed preview shows what the iframe will look like

3. **Viewer rendering:**
   - Read the viewer page and ViewerMap component
   - Verify: viewer loads the map without authentication (for public maps)
   - Verify: viewer renders all layers, styles, filters, and labels exactly as the builder
   - Check: does the viewer include edit buttons? (Must NOT for shared/embedded views)
   - Verify: basemap and attribution display correctly in viewer
   - Check: viewer error state — expired token, deleted map, network failure

4. **Visibility modes:**
   - Verify: map visibility options (public, private, internal) are enforced
   - Check: can a viewer access a private map via URL guessing? (Must be blocked by backend)
   - Verify: visibility changes take effect immediately (no caching of old visibility)

5. **Backend enforcement:**
   - Read share token validation in the maps router/service
   - Read embed token validation in `backend/app/modules/embed_tokens/service.py`
   - Read `backend/app/modules/catalog/maps/schemas.py` and `backend/app/modules/embed_tokens/schemas.py`
   - Verify: share tokens are validated on every request (not just on initial load)
   - Verify: share tokens are hashed in the database and raw tokens are never persisted, logged, audited, or replaced by `token_hint` in usable URLs
   - Verify: expired tokens return 401/403 with a clear message
   - Verify: domain restriction checks use `Origin` when available and carefully fall back to `Referer` only when needed
   - Verify: shared-map responses set the expected CSP `frame-ancestors` policy for embed tokens and allowed origins
   - Verify: iframe sandbox attributes are deliberate and do not require `allow-same-origin` unless the security model is reviewed
   - Verify: embed tokens scope tile access to specific dataset IDs (`scoped_dataset_ids`)
   - Check: embed token cache invalidation — does revoking a token take effect within the cache TTL?
   - Verify edition enforcement is backend-backed, not UI-only:
     - `ShareTokenRequest.expires_at` rejects non-null values in Community
     - `create_share_token()` / `update_share_token()` reject custom expiration in Community
     - `EmbedTokenCreate.expires_in_days != 30` rejects in Community
     - `EmbedTokenCreate.allowed_origins` / `EmbedTokenUpdate.allowed_origins` reject non-empty origins in Community
     - `create_embed_token()` / `update_embed_token()` repeat the same Community rejection in service code

6. **Tile signing flow:**
   - Read `frontend/src/lib/tile-utils.ts` and `frontend/src/components/viewer/hooks/use-viewer-tokens.ts`
   - Verify: tile URLs are signed with HMAC tokens before requests
   - Verify: tile tokens are batch-fetched (`POST /tiles/tokens/`) rather than one-at-a-time
   - Check: what happens when a tile token expires mid-session? (Refresh or error?)
   - Verify: raster tile auth goes through the nginx `auth_request` path correctly
   - Verify: embedded raster/DEM layers either fetch embed-authorized raster tile descriptors or route shared-layer `tile_url`/metadata through the raster/hillshade sync path with `X-Embed-Token`

7. **Thumbnail upload:**
   - Verify: `PUT /maps/{map_id}/thumbnail/` accepts base64 and stores correctly
   - Verify: `GET /maps/{map_id}/thumbnail/` respects visibility (public maps only without auth)
   - Check: is the thumbnail captured automatically on save, or does the user trigger it?

8. **Terrain / 3D:**
   - Read `MapToolbar.tsx` for terrain toggle UI
   - Read `frontend/src/components/viewer/hooks/use-viewer-terrain.ts` for terrain implementation
   - Verify: terrain toggle adds/removes the DEM terrain source correctly
   - Verify: terrain exaggeration is configurable (if UI control exists)
   - Verify: terrain exaggeration is clamped consistently between UI and render-time application, and high values do not leave the map unusably distorted
   - Check: does enabling terrain work with all layer types? (Heatmap + terrain can conflict)
   - Check: does the viewer restore terrain state from the saved map?
   - Note: DEM terrain assumes meter-based elevation; non-meter SRIDs (US feet) produce exaggerated terrain — this is a known limitation, not a finding, but verify it's documented or handled gracefully

**Output:** Finding list — workflow step × works × secure.

---

### Subagent 6: AI Chat Integration

**Goal:** Verify the AI chat panel integrates correctly with the builder — tool calls produce valid map changes, streaming works, configured providers succeed, and missing-provider-key paths fail gracefully without blocking core builder workflows.

**Process:**

1. **Chat panel UI:**
   - Read `ChatPanel.tsx`, `ChatInput.tsx`, `MentionDropdown.tsx`, `ColumnsReference.tsx`, and `chat-suggestions.ts`
   - Verify: message input, send button, streaming response display
   - Verify: @-mention autocomplete for layer names and column names works in `ChatInput.tsx`
   - Verify: smart suggestion chips (`chat-suggestions.ts`) are contextual to current map state
   - Check: can the user send while a response is streaming? (Should queue or disable)
   - Check: error display — what happens when the AI endpoint fails?
   - Check: with no provider key configured, AI controls are disabled or explain the missing configuration; map editing, styling, save, share, and viewer workflows remain usable
   - Check: chat history persistence — is it per-map or per-session?

2. **Tool call integration:**
   - Read `backend/app/processing/ai/tools.py` for tool definitions (the contract the LLM sees)
   - Read `backend/app/processing/ai/chat_service.py` plus split helpers (`chat_actions.py`, `chat_validation.py`, `chat_styles.py`, `chat_geojson.py`) for tool execution logic
   - Read `backend/app/processing/ai/schemas.py` for `ChatAction` type definitions
   - Verify: every `ChatAction` type (`set_filter`, `set_style`, `set_data_driven_style`, `set_label`, `toggle_visibility`, `add_layer`, `remove_layer`, `show_query_result`, `set_opacity`) maps through `builder-action-contract.ts` to a valid builder state mutation
   - Verify: the frontend applies AI output safely — invalid/unknown properties from the bridge are rejected or clamped, not blindly written to the map
   - Scope boundary: deep audit of AI *generation* quality and backend spec-validation (`validate_paint_for_geometry()`) belongs to `/ai-optimize`. Here, verify only that the integration contract holds and that bad LLM output degrades gracefully in the builder.
   - Check: does the chat response show what changes were made? (Transparency)
   - Verify: tool call errors are surfaced to the user, not silently swallowed
   - Check: can the user undo a chat-initiated change? (Edit history or undo button)

3. **Ephemeral query results:**
   - Read how SQL query tool calls in `chat_service.py` produce GeoJSON results
   - Verify: query results are added as ephemeral layers (not persisted until user confirms)
   - Check: does the `EphemeralBadge` appear on chat-generated query layers?
   - Check: are SQL queries sandboxed (`validate_and_execute` in chat_service.py)?

4. **Context passing:**
   - Verify: the chat endpoint receives current map state (layers, styles, filters) as context
   - Check: does the chat know about available datasets? (So it can suggest layers to add)
   - Verify: the context does not leak sensitive data (other users' maps, API keys, etc.)

5. **Streaming:**
   - Read `backend/app/processing/ai/streaming.py`
   - Verify: server-sent events or streaming response renders incrementally
   - Check: does aborting a stream (navigating away, closing panel) clean up correctly?
   - Check: is there a loading indicator during streaming?

6. **Map generation (non-chat):**
   - Read `POST /ai/generate-map/` and `POST /ai/generate-map/stream/` in `backend/app/processing/ai/router.py`
   - Verify: generated maps produce valid MapLayerResponse arrays
   - Check: rate limiting is enforced (10/min per the router)

**Output:** Finding list — chat feature × functional × UX quality.

---

### Subagent 7: UI/UX & Accessibility

**Goal:** Audit the builder's user experience quality using a two-phase approach: (1) code review for structural issues, then (2) Playwright MCP visual verification against the live app for states, theming, and responsiveness.

**Prerequisite:** The dev server must be running at `http://localhost:8080`. Before starting visual verification, check with `browser_navigate` to `http://localhost:8080`. If the server is not available, fall back to code-only analysis and note which checks were skipped due to no running server.

**Process:**

#### Phase A: Code review (read source files)

1. **Layout and panel management:**
   - Read `MapBuilderPage.tsx` for layout structure
   - Verify: sidebar is resizable with a drag handle
   - Check: minimum/maximum sidebar width constraints (prevent collapsing to 0 or exceeding viewport)
   - Check: sidebar collapse/expand — is the state persisted across sessions?
   - Verify: map fills remaining viewport (no dead space or overflow)

2. **Empty states:**
   - Check: new map with no layers — is there a clear call-to-action to add a dataset?
   - Check: dataset search with no results — is there a helpful empty state? (`DatasetSearchPanel.tsx`)
   - Check: chat panel with no history — is there an onboarding message or prompt suggestions?
   - Check: share panel with no tokens — is there guidance?
   - Every empty state must have: illustration or icon, heading, body text, and CTA (if applicable)

3. **Loading states:**
   - Check: map initial load — is there a skeleton or spinner?
   - Check: layer addition — is there feedback while the source loads?
   - Check: save operation — is there feedback during save?
   - Check: chat response — is there a typing indicator or streaming skeleton?
   - No state should show a blank area during async operations

4. **Error states:**
   - Check: tile load failure — is the error surfaced per-layer (not a global crash)?
   - Check: save failure — is the error recoverable (user can retry, data not lost)?
   - Check: API errors — are they shown as user-friendly messages, not raw JSON?
   - Check: dataset deleted after being added as a layer — graceful degradation?
   - Verify: error boundaries exist around major builder sections (map, sidebar, chat)

5. **Keyboard navigation (code check):**
   - Check: are `tabIndex`, `role`, `aria-*` attributes present on interactive builder elements?
   - Check: Escape key handlers on modals, panels, dropdowns?
   - Check: keyboard reorder support (Up/Down arrow keys on layer items)?

6. **Basemap picker:**
   - Read `BasemapPicker.tsx`
   - Check: does the picker display available basemaps with previews?
   - Check: does switching basemaps preserve all user layers and styles?
   - Check: is the labels toggle functional (if present)?
   - Check: does the selected basemap persist on save and restore on load?
   - Check: does basemap attribution update when switching basemaps?
   - Check: removing a basemap uses the blank/no-basemap state, hides the basemap row, closes stale basemap editors, and keeps all user data layers intact

7. **Map settings:**
   - Read `SettingsEditorScene.tsx`
   - Check: Appearance exposes background color with a swatch picker and reset action
   - Check: background color changes preview immediately, mark the map dirty, save/reload through `MapBasemapConfig.background_color`, and render the same in viewer routes
   - Check: Terrain, Widgets, Projection, and Appearance sections fit without overlap on narrow sidebars <!-- v1036: "Widgets" → "Plugins" rename pending (RENAME-TOOL-01, phase 1164) -->

8. **Unsaved changes:**
   - Verify: navigating away with unsaved changes triggers a confirmation dialog
   - Check: browser back button — does it trigger the same guard?
   - Check: closing the tab — does `beforeunload` fire?

9. **Map toolbar:**
   - Read `MapToolbar.tsx`
   - Check: are all toolbar buttons labeled (tooltip or aria-label)?
   - Check: does the toolbar include zoom controls, terrain toggle, and any measurement tools?
   - Check: do toolbar actions provide visual feedback (active state, toggle indicator)?

#### Phase B: Playwright MCP visual verification (live app)

Use the Playwright MCP tools available in the current runtime (typically `browser_navigate`, `browser_snapshot`, `browser_take_screenshot`, `browser_click`, `browser_resize`, and `browser_fill_form`) to verify against the running dev server. Use an existing authenticated browser state or documented local test credentials from the current environment; do not assume credentials that are not configured. If keyboard tools are unavailable, mark keyboard-only live checks as skipped and fall back to code/a11y snapshot inspection.

10. **Builder initial state (screenshot):**
   - Navigate to the maps list, create a new map or open an existing one
   - `browser_take_screenshot` of the builder with no layers — verify empty state CTA is visible
   - `browser_snapshot` to inspect DOM structure for accessibility attributes

11. **Dark mode verification:**
   - Toggle dark mode (click theme toggle or use the settings)
   - `browser_take_screenshot` in dark mode — check for:
     - No hardcoded white/black backgrounds bleeding through
     - Color pickers visible and readable
      - Map controls (zoom, attribution) readable
      - Chat panel text contrast
     - Sidebar and inspector panels have correct surface colors
   - Toggle back to light mode, screenshot again for comparison

12. **Responsive behavior:**
   - `browser_resize` to 390px width (mobile) — screenshot and check:
     - Does the layout collapse to a mobile-friendly view?
     - Are panels accessible (sheet-based or tabs)?
      - Is the map still visible?
   - `browser_resize` to 768px width (tablet) — screenshot and check hybrid layout
   - `browser_resize` back to 1440px (desktop) — verify restoration
   - At each viewport, verify touch targets appear >= 44x44px via `browser_snapshot`

13. **Keyboard navigation (live test):**
   - Press Tab repeatedly with the available browser keyboard tool — verify focus moves through builder controls
   - Check: are focus rings/indicators visible on focused elements?
   - Press Escape on an open panel — verify it closes
   - Press Enter on a button — verify activation

14. **Interaction feedback (live test):**
   - If layers exist: click a layer item, verify the inspector opens
   - Click save button — verify loading indicator or toast appears
   - Open share panel — verify share token UI or empty state
   - Open chat panel — verify onboarding message or input placeholder

15. **Interaction feedback (code check):**
   - Check: button hover/active states present?
   - Check: drag operations show a preview or placeholder?
   - Check: color picker selection gives immediate map preview?
   - Check: slider changes update the map in real-time (not on release only)?
   - Check: success actions (save, copy link, create token) show a toast or confirmation?

**Output format for visual findings:** Include `[VISUAL]` tag alongside severity. Reference the screenshot or snapshot that evidences the finding. Example: `[MEDIUM][VISUAL] Dark mode: chat panel background is white (#fff) instead of surface-2 — screenshot-dark-mode.png`

**Output:** Finding list — UX aspect × state × severity.

---

### Subagent 8: Performance & Rendering

**Goal:** Identify performance bottlenecks in the builder — unnecessary re-renders, stale subscriptions, memory leaks, large bundle contributions, and MapLibre rendering inefficiencies.

**Process:**

1. **React re-render analysis:**

   ```bash
   # State updates that could cause cascading re-renders
   rg -n "useState|useReducer|useContext" frontend/src/components/builder/ -g "*.tsx" -g "*.ts"

   # Memoization usage
   rg -n "useMemo|useCallback|React\\.memo|memo\\(" frontend/src/components/builder/ -g "*.tsx" -g "*.ts"

   # useEffect with missing or broad dependencies
   rg -n "useEffect" frontend/src/components/builder/ -g "*.tsx" -g "*.ts"
   ```

   - Check: does changing one layer's style re-render ALL layers in the sidebar?
   - Check: does typing in the chat input re-render the map?
   - Check: are expensive computations (filter expression building, color ramp generation) memoized?

2. **MapLibre rendering efficiency:**
   - Check: style changes use `setPaintProperty()` / `setLayoutProperty()` (not full style replacement)
   - Check: filter changes use `setFilter()` (not source reload)
   - Check: are there any cases where `map.setStyle()` is called for minor changes? (Causes full re-render)
   - Check: tile request deduplication — adding/removing layers should not re-fetch existing tiles

3. **Memory leak patterns:**

   ```bash
   # Event listeners that might not be cleaned up
   rg -n "addEventListener|\\.on\\(" frontend/src/components/builder/ -g "*.tsx" -g "*.ts"

   # Map event listeners
   rg -n "map\\.on|map\\.off" frontend/src/components/builder/ -g "*.tsx" -g "*.ts"

   # Intervals/timeouts without cleanup
   rg -n "setInterval|setTimeout" frontend/src/components/builder/ -g "*.tsx" -g "*.ts"
   ```

   - Verify: all map event listeners registered in useEffect are cleaned up in the return function
   - Verify: map instance is properly destroyed on unmount
   - Check: ResizeObserver cleanup on sidebar resize handle

4. **Bundle contribution:**

   ```bash
   # Large imports that could be lazy-loaded
   rg -n "import.*from" frontend/src/pages/MapBuilderPage.tsx

   # Dynamic imports (code splitting)
   rg -n "lazy\\(|React\\.lazy|import\\(" frontend/src/pages/ -g "*.tsx"

   # Color ramp / style utilities — are they tree-shakeable?
   wc -l frontend/src/lib/color-ramps.ts frontend/src/components/builder/map-sync.ts frontend/src/lib/basemap-utils.ts 2>/dev/null
   ```

   - Check: is the chat panel lazy-loaded? (It includes AI dependencies)
   - Check: are color ramp definitions statically imported or dynamically loaded?

5. **Debouncing and throttling:**

   ```bash
   rg -n "debounce|throttle|useDebouncedValue|useThrottled" frontend/src/components/builder/ -g "*.tsx" -g "*.ts"
   ```

   - Check: slider changes (opacity, radius, width) — are map updates debounced?
   - Check: color picker changes — debounced or throttled?
   - Check: filter input — debounced before applying to map?
   - Check: sidebar resize — throttled?
   - Check: save thumbnail capture — debounced after map idle?

**Output:** Finding list — performance concern × impact × fix.

---

### Subagent 9: Code Conventions & Type Safety

**Goal:** Verify the builder code follows project conventions — API client patterns, auth handling, design tokens, component patterns, error handling, and TypeScript strictness.

**Process:**

1. **API client usage:**

   ```bash
   # Should use apiFetch() from api/client.ts
   rg -n "apiFetch|fetch\\(|axios|httpx" frontend/src/components/builder/ frontend/src/hooks/use-maps* -g "*.tsx" -g "*.ts"

   # Trailing slash compliance (FastAPI 307 redirect avoidance)
   rg -n '"/api/' frontend/src/components/builder/ frontend/src/hooks/use-maps* -g "*.tsx" -g "*.ts"
   ```

   Note: Builder hooks are colocated at `frontend/src/components/builder/hooks/` — the searches on `frontend/src/components/builder/` already cover them recursively.

   - Verify: all API calls use `apiFetch()`, not raw `fetch()` or `axios`
   - Verify: all API paths include trailing slashes (except OGC `/collections/datasets`)
   - Verify: error responses are handled consistently (not swallowed)

2. **Auth token injection:**

   ```bash
   # transformRequest pattern for tile auth
   rg -n "transformRequest|setTransformRequest|Authorization|Bearer|token|api_key" frontend/src/components/builder/ -g "*.tsx" -g "*.ts"
   ```

   - Verify: tile requests inject auth via `transformRequest` (set imperatively in `onLoad`)
   - Verify: the token comes from `useAuthStore.getState().token`, not a prop drill
   - Check: does the transformRequest handle token refresh? (If token expires mid-session)

3. **Design token compliance:**

   ```bash
   # Hardcoded colors in builder components (should use CSS vars or Tailwind tokens)
   rg -n "#[0-9a-fA-F]{3,8}" frontend/src/components/builder/ -g "*.tsx" -g "*.ts" | rg -v "\\.svg|color-ramps|map-colors"

   # Hardcoded spacing (should use Tailwind classes)
   rg -n "style=\\{" frontend/src/components/builder/ -g "*.tsx" | rg "[0-9]+px"

   # Raw Tailwind palette classes (should use semantic tokens)
   rg -n "bg-(gray|slate|zinc)-|text-(gray|slate|zinc)-|border-(gray|slate|zinc)-" frontend/src/components/builder/ -g "*.tsx"
   ```

   - Exempt: MapLibre paint property values (CSS vars don't work in MapLibre expressions)
   - Exempt: Color ramp definitions and map-specific color constants
   - Flag everything else as a token violation

4. **Component patterns:**

   ```bash
   # cn() usage for conditional classes (shadcn convention)
   rg -n "className=" frontend/src/components/builder/ -g "*.tsx" | rg -v "cn\\("

   # Template literals for classNames (should use cn())
   rg -n 'className=\{`' frontend/src/components/builder/ -g "*.tsx"
   ```

   - Check: are builder components using `cn()` for conditional class composition?
   - Check: are shadcn/ui primitives used where available (Button, Dialog, Select, etc.)?

5. **TypeScript strictness:**

   ```bash
   # Any type usage (builder hooks are under frontend/src/components/builder/hooks/)
   rg -n ": any|as any|<any>" frontend/src/components/builder/ -g "*.tsx" -g "*.ts"

   # Non-null assertions
   rg -n "!\\." frontend/src/components/builder/ -g "*.tsx" -g "*.ts"

   # Type assertions that could mask errors
   rg -n "as [A-Z]" frontend/src/components/builder/ -g "*.tsx" -g "*.ts"
   ```

   - Flag: `any` types that should be properly typed
   - Flag: non-null assertions (`!.`) on values that could genuinely be null
   - Flag: type assertions (`as X`) that bypass validation

6. **Error handling patterns:**

   ```bash
   # try/catch usage
   rg -n "try \\{" frontend/src/components/builder/ -g "*.tsx" -g "*.ts"

   # Unhandled promise rejections
   rg -n "\\.then\\(|await " frontend/src/components/builder/ -g "*.tsx" -g "*.ts" | rg -v "try|catch|\\.catch"
   ```

   - Check: are async operations wrapped in try/catch or .catch()?
   - Check: are errors logged or surfaced to the user (not silently swallowed)?

7. **Backend conventions (maps router):**

   ```bash
   # Auth dependency usage
   rg -n "Depends|require_permission|current_user|resolve_api_key" backend/app/modules/catalog/maps/router.py

   # Response model declarations
   rg -n "response_model|status_code" backend/app/modules/catalog/maps/router.py

   # Pydantic schema validation
   rg -n "class.*BaseModel|class.*Schema" backend/app/modules/catalog/maps/schemas.py
   ```

   - Verify: every mutating endpoint (POST, PUT, DELETE) requires authentication
   - Verify: read endpoints respect visibility (public maps readable without auth)
   - Verify: response models are declared (not returning raw dicts)
   - Verify: input schemas use Pydantic with proper validation

**Output:** Finding list — convention × compliance × severity.

---

## SYNTHESIS (Serial — after all subagents complete)

### Scoring

| Dimension | What it measures | Subagent |
| --------- | ---------------- | -------- |
| **Layer Management** | Layer lifecycle correctness: add, remove, reorder, toggle, rename, undo | 1 |
| **Style Editing** | Style property correctness across all geometry types, data-driven modes, and Style Spec compliance | 2 |
| **Filter Building** | Filter expression validity, type safety, and round-trip fidelity | 3 |
| **Label Config** | Label property correctness, placement, collision handling | 4 |
| **Share & Viewer** | Share/embed workflow, viewer rendering, terrain, security enforcement | 5 |
| **AI Chat** | Chat tool integration, streaming, error handling, UX | 6 |
| **UI/UX Quality** | Layout, states, dark mode, responsiveness, keyboard, interaction feedback | 7 |
| **Performance** | Re-renders, MapLibre efficiency, memory leaks, debouncing | 8 |
| **Code Conventions** | API patterns, auth, design tokens, types, error handling | 9 |

Grade each A–F:

- **A** — Excellent. No CRITICAL/HIGH findings, minimal LOW findings. Production-quality.
- **B** — Good. No CRITICAL findings, <=2 HIGH, mostly LOW/MEDIUM. Ship-ready with minor polish.
- **C** — Adequate. <=1 CRITICAL or 3+ HIGH. Functional but needs targeted fixes before release.
- **D** — Poor. Multiple CRITICAL or HIGH. Core workflows have correctness or UX problems.
- **F** — Failing. Builder has broken core workflows, data loss risks, or security issues.

**Overall builder health** = weighted average (Layer Management, Style Editing, and Share & Viewer weighted 2x because they are core user-facing workflows).

### Action Items

| Field | Description |
| ----- | ----------- |
| ID | Sequential (B-001, B-002, ...) |
| Priority | P0 (data loss / security), P1 (broken workflow / bad UX), P2 (polish / convention) |
| Severity | CRITICAL / HIGH / MEDIUM / LOW |
| Finding | One-sentence description |
| File:line | Exact location |
| Fix | One-sentence concrete fix |
| Dimension | Which audit dimension |
| Effort | S (< 1hr), M (1-4hr), L (4-8hr), XL (> 8hr) |

Sort by priority, then severity, then effort.

---

## DELIVERY

### Output format

Write the report to: `docs-internal/audits/builder-audit-{YYYYMMDD}.md`

### Report structure

```markdown
# Map Builder Audit — {YYYY-MM-DD}

## Scorecard
<!-- Letter grades per dimension + overall health -->

## Executive Summary
<!-- 3-5 sentences: builder state, biggest gaps, top recommendation -->

## Scope, Environment, and Verification
<!-- Args/scope, repo state caveats, dev-server availability, browser/session state, commands run, screenshots/snapshots, skipped checks and blockers -->

## 1. Layer Management
<!-- Subagent 1 findings -->

## 2. Style Editing
<!-- Subagent 2 findings, organized by geometry type -->

## 3. Filter Building
<!-- Subagent 3 findings, operator coverage matrix -->

## 4. Label Configuration
<!-- Subagent 4 findings -->

## 5. Share, Embed, Viewer & Terrain
<!-- Subagent 5 findings -->

## 6. AI Chat Integration
<!-- Subagent 6 findings -->

## 7. UI/UX & Accessibility
### 7a. Empty States
### 7b. Loading States
### 7c. Error States
### 7d. Keyboard Navigation
### 7e. Basemap Picker
### 7f. Unsaved Changes Guard
### 7g. Map Toolbar
### 7h. Dark Mode (Visual)
### 7i. Responsive Behavior (Visual)
### 7j. Keyboard Navigation (Visual)
### 7k. Interaction Feedback
<!-- Subagent 7 findings — code review + Playwright MCP visual verification -->

## 8. Performance & Rendering
### 8a. React Re-renders
### 8b. MapLibre Efficiency
### 8c. Memory Leaks
### 8d. Bundle Size
### 8e. Debouncing
<!-- Subagent 8 findings -->

## 9. Code Conventions & Type Safety
### 9a. API Client Patterns
### 9b. Auth Token Injection
### 9c. Design Token Compliance
### 9d. Component Patterns
### 9e. TypeScript Strictness
### 9f. Error Handling
### 9g. Backend Conventions
<!-- Subagent 9 findings -->

## 10. Prioritized Action Items
<!-- Full action items table -->

## 11. Tested Flows and Skipped Areas
<!-- Existing tests, E2E/Playwright/manual flows, and explicit skipped areas with reasons. Inputs: the INTAKE "Existing test gates to prefer" results + each Subagent's skipped-check notes. -->

## 12. Builder Health Summary
<!-- Aggregate metrics:
  - Total findings by severity
  - Findings per dimension
  - Estimated total effort for P0 + P1 items
  - Top 3 recommendations
-->

## 13. Comparison to Prior Audit
<!-- If a previous builder-audit exists, diff findings:
  - Match findings by file:line first, then by description similarity
  - Categorize each as: NEW (not in prior), RESOLVED (in prior but not current),
    REGRESSED (was resolved, now back), PERSISTENT (in both, unchanged)
  - Summary: X new, Y resolved, Z persistent, W regressed
-->
```

### Post-delivery

1. Print one-line summary: overall grade + P0 count + P1 count + total P0+P1 effort estimate.
2. If any P0 findings exist, print them individually as a bulleted list.
3. If a previous `docs-internal/audits/builder-audit-*.md` exists, note which findings are new vs resolved.

---

## WHAT NOT TO FLAG

Avoid false positives on these:

- **Hardcoded colors in MapLibre paint/layout properties** — CSS variables do not work inside MapLibre style expressions. Hex colors in paint properties are correct.
- **OKLCH in design tokens / UI chrome CSS** — correct, that's the design system. But OKLCH in MapLibre paint properties IS a finding (MapLibre doesn't support it).
- **Hardcoded colors in `color-ramps.ts` or `map-colors.ts`** — these are intentional centralized palettes for map-specific use.
- **Imperative `map.addSource()` / `map.addLayer()` for vector tiles** — this is the documented workaround for the `@vis.gl/react-maplibre` v8 bug where declarative `<Source>/<Layer>` silently fails for vector tile sources.
- **`setTransformRequest()` called in `onLoad` instead of as a prop** — this is the documented workaround for the v8 `transformRequest` prop being silently ignored.
- **Auth token in tile URL query params (`?api_key=`)** — this is the documented fallback when header auth is not available (e.g., MapLibre tile requests that cannot set custom headers). The backend supports this explicitly.
- **No root `docs/` design guide** — repository policy keeps root docs single-purpose. Do not create or require a root `docs/` directory; use existing design/token sources instead.
- **Missing tests for MapLibre rendering** — MapLibre requires WebGL which is unavailable in vitest/jsdom. Map rendering is tested via E2E, not unit tests.
- **`status-colors.ts` using raw Tailwind palette classes** — documented exception in the design guide for contrast on tinted backgrounds.
- **Style opinions not backed by the design guide** — only flag token/pattern violations that contradict a documented rule.
- **React Query cache times** — stale/cache configurations are intentional tuning decisions unless they cause visible staleness bugs.
- **Third-party component library limitations** — if a shadcn/ui or MapLibre component does not support a feature, that is an upstream limitation, not a finding (unless a workaround exists and is not applied).
- **Terrain exaggeration on non-meter SRIDs** — known limitation (US feet produce exaggerated terrain). Only flag if the UI gives no indication to the user.
- **Deprecated MapLibre filter syntax in existing saved maps** — legacy filters may use the old form; only flag if the builder *generates* new filters in deprecated form.
- **Absent DEM contour control** — DEM contour was cut in v1032 (no `contour-sync.ts`, no `CONTOUR_CONTROL_ENABLED`). A missing contour UI is expected, not a finding.

---

## RELATIONSHIP TO OTHER COMMANDS

- `/ai-optimize` — AI generation quality (prompts, SQL safety, model sizing, hallucination/grounding). Subagent 6 here audits the AI chat **integration** boundary — whether AI output flows through `builder-action-contract.ts` and renders valid builder mutations; `/ai-optimize` audits whether the AI **generates** good/safe/spec-valid output in the first place. Backend generation-side validation (`validate_paint_for_geometry()` in `ai/schemas.py`) is owned by `/ai-optimize`, not re-audited here.
- `/ux-plan` + `/ux-review` — general UX audit cycle. This command is builder-specific and includes functionality + MapLibre integration that `/ux-review` does not cover.
- `/design-audit` — design system conformance. Subagent 9 of this command overlaps for builder-specific token compliance; `/design-audit` covers the full frontend.
- `/post-impl` — general code quality. Subagents 8 and 9 of this command overlap for builder-specific performance and conventions; `/post-impl` covers the full codebase.
- `/sec-audit` — security. Subagent 5 of this command covers builder-specific share/embed security; `/sec-audit` covers the full attack surface.
- `/perf-profile` — system-wide performance profiling. Subagent 8 of this command focuses on builder-specific rendering and React performance; `/perf-profile` covers tile generation, queries, and infrastructure.
- `/plugin-audit` — the plugin **host** platform (registry, availability, host/panel contract, built-in plugins). This command audits only the builder-side surfacing of plugins (Settings "Plugins" section, viewer plugin availability); host internals are out of scope here.
- `/test-audit` — test coverage. This command does not audit test coverage; use `/test-audit` for that.
