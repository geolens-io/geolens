# Phase 1114: Adapter Migration - Context

**Gathered:** 2026-05-25
**Status:** Ready for execution
**Mode:** Autonomous technical implementation

<domain>
## Phase Boundary

Migrate layer adapters and companion-layer sync paths onto the Phase 1113 owned-property reconciler where practical. Raster and hillshade adapters may keep their existing default-reset loops as documented adapter-specific equivalents because they already iterate all owned properties and restore defaults for absent values.
</domain>

<decisions>
## Implementation Decisions

### D-01: Migrate High-Risk Vector Paths First

Line, fill, circle, heatmap, cluster, and symbol are the stale-style risk centers because they sync live MapLibre state without source rebuilds.

### D-02: Remove Bug-Specific Line Gradient Cleanup

`clearStaleLineGradient` should be replaced by line adapter ownership over `line-gradient`.

### D-03: Companion Layers Use Constructed Canonical Paint/Layout

Outline, arrow, cluster-count, cluster-circle, unclustered cluster point, and symbol text/icon layers should sync from adapter-derived canonical paint/layout objects through the shared helper when possible.
</decisions>

<code_context>
## Existing Code Insights

- `line-adapter.ts` has a one-off `clearStaleLineGradient` after `syncVectorPaint`.
- `fill-adapter.ts` manually mutates fill parent, outline, and extrusion companion layers.
- `circle-adapter.ts`, `heatmap-adapter.ts`, and cluster unclustered points replay only incoming paint keys.
- `symbol-adapter.ts` sets present layout/paint keys only, which can leave text keys live when `label_config` is removed.
- `raster-adapter.ts` and `hillshade-adapter.ts` already iterate their full owned property sets and set missing values back to defaults.
</code_context>

<specifics>
## Specific Ideas

- Add adapter-local owned property constants.
- Use `syncOwnedPaintProperties` for vector parent paint and companion paint.
- Use `syncOwnedLayoutProperties` for symbol/arrow/cluster-count layout owned keys.
- Preserve existing explicit opacity compounding after generic paint sync where needed.
- Run focused adapter tests after migration.
</specifics>

<deferred>
## Deferred Ideas

- Centralizing ownership constants in one registry may be useful later, but adapter-local constants keep this migration small.
</deferred>
