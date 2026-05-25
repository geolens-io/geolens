# Phase 1112: Style Contract and Baseline Audit - Context

**Gathered:** 2026-05-25
**Status:** Ready for implementation
**Mode:** Autonomous technical audit

<domain>
## Phase Boundary

Phase 1112 defines the style mutation contract for v1026 before code migration. It covers map-builder manual style controls, render-as switches, data-driven styles, line gradients, labels, terrain, basemap overrides, save/reload, public/embed viewer rendering, AI chat style actions, and undo/history.

The hard invariant is convergence: after every migrated style edit, canonical builder state, live MapLibre state, persisted map JSON, and viewer/embed rendering must describe the same style.
</domain>

<decisions>
## Implementation Decisions

### D-01: Canonical State Owns the Truth

The canonical style state is the `MapLayerResponse` fields that persist through save/load: `paint`, `layout`, `style_config`, `label_config`, `opacity`, `visible`, `filter`, `layer_type`, and `is_dem`. MapLibre live state is an imperative projection of that state, not a second source of truth.

### D-02: Distinguish Patch, Replace, Clear, Reset, and Rebuild

Normal UI controls patch or intentionally replace a scoped slice of canonical state. Advanced JSON remains a replace path. Explicit clear semantics are required for stale MapLibre properties because an omitted key in the next object cannot reliably mean "clear this" unless the adapter declares ownership.

### D-03: AI `set_style` Is a Patch

Backend tool docs describe `set_style.paint` as "properties to set/override" (`backend/app/processing/ai/tools.py:134`), but the frontend currently forwards that object to `onPaintChange` as a full paint replacement (`frontend/src/components/builder/ChatPanel.tsx:211`). Phase 1115 must align chat application with patch semantics and add an explicit clear/replace path for intentional deletion.

### D-04: Adapter-Owned Properties Drive Live Clears

The durable fix is adapter-owned paint/layout declarations. The reconciler sets changed owned keys and clears owned keys that are missing or explicitly `undefined` in the canonical next state. Builder metadata such as `_outline-width`, `_heatmap-ramp`, and `_height_column` must stay out of direct MapLibre paint/layout calls.

### D-05: Rebuilds Stay Narrow

Paint/layout style changes must not recreate sources or refetch tiles. Rebuild is reserved for render-mode, source-type, raster/hillshade, cluster source, or companion-layer topology changes.
</decisions>

<code_context>
## Existing Code Insights

- `frontend/src/components/builder/hooks/use-layer-map-sync.ts:42` centralizes state mutation plus live MapLibre side effects. `handlePaintChange` replaces the layer `paint` object and calls `adapter.syncPaint` through rAF coalescing (`:95`). `handleStyleConfigChange` replaces both `style_config` and `paint`, with a raster rebuild branch (`:134`).
- `frontend/src/components/builder/layer-adapters/shared.ts:258` implements `syncVectorPaint`, which filters invalid/custom keys but only sets incoming keys. It never clears previously-set live properties that are absent from the next canonical paint.
- `frontend/src/components/builder/layer-adapters/line-adapter.ts:111` has `clearStaleLineGradient`, a bug-specific live clear for the gradient-to-solid issue. This proves the broader pattern and should be replaced by ownership-driven clearing.
- `frontend/src/components/builder/LineGradientControls.tsx:220` correctly removes `line-gradient` from the next paint object and emits a transition back to solid. The stale live behavior belongs in adapter sync, not this control.
- `frontend/src/components/builder/DataDrivenStyleEditor.tsx:303` and `:338` clear data-driven modes by building replacement paint snapshots. These are high-risk stale-expression transitions.
- `frontend/src/components/builder/renderAs.ts:409` computes render-as patches for point, symbol, heatmap, cluster, line, arrow, fill/stroke/fill-stroke/extrusion, image, and hillshade transitions.
- `frontend/src/components/builder/hooks/use-builder-layers.ts:943` applies render-as patches and `:860` rebuilds adapter layers when topology changes.
- `frontend/src/components/builder/map-sync.ts:594` is the shared builder/viewer layer sync path. It resolves adapters, manages vector/raster sources, labels, cluster companions, and cleanup. Viewer parity depends on saved canonical state flowing through the same adapter add/sync behavior.
- `frontend/src/components/builder/label-layer-utils.ts:65` syncs label layout/paint by setting present values; label-off is handled by companion-layer removal in `map-sync.ts:731`.
- `frontend/src/components/builder/layer-adapters/raster-adapter.ts:81` and `hillshade-adapter.ts:92` already normalize absent owned properties back to defaults. These are adapter-specific equivalents of clear semantics.
- `frontend/src/components/builder/hooks/use-builder-save.ts:316` diffs persisted layer fields and saves canonical `paint`, `layout`, `label_config`, `style_config`, `layer_type`, and opacity/visibility fields.
- `frontend/src/components/viewer/ViewerMap.tsx:670` builds adapter inputs from saved layers for public/embed viewer rendering. Viewer parity is mostly a canonical-state and adapter-add concern.
- `backend/app/processing/ai/schemas.py:329` defines `ChatAction` with `paint` and `style_config`, but no explicit clear or replace fields yet.
</code_context>

<specifics>
## Specific Ideas

- Build shared reconciliation helpers in `layer-adapters/shared.ts`, then migrate adapters incrementally.
- Keep a compatibility wrapper for existing additive sync while migrated adapters move to owned-property declarations.
- Test the helper directly with a fake MapLibre map: set changed values, no-op unchanged values, clear missing owned values, filter invalid/custom keys, preserve expression arrays, and isolate MapLibre errors.
- Use targeted Playwright MCP QA against `http://localhost:8080/maps/8dd6a129-8eb0-4ba9-b421-716c83b160dd` for Hiking trails gradient-to-solid, terrain exaggeration sanity, labels, render-mode swaps, and console/network capture.
</specifics>

<deferred>
## Deferred Ideas

- A fuller typed style transaction domain model may be worthwhile after v1026 if editor components remain noisy.
- A generated shared backend/frontend MapLibre paint-property allowlist would reduce AI schema drift, but is not required for the v1026 reconciler.
</deferred>
