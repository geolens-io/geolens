# Phase 1116: Persistence and Viewer Parity - Context

**Gathered:** 2026-05-25
**Status:** Ready for execution
**Mode:** Autonomous verification and focused coverage

<domain>
## Phase Boundary

Prove reconciled canonical style state persists and renders outside the live builder. Scope covers save diffs, public viewer/embed viewer normalized sync inputs, and style JSON import/export compatibility.
</domain>

<decisions>
## Implementation Decisions

### D-01: No Transient Reconciler Metadata

The reconciler lives in adapter code and should not add any persisted metadata to `paint`, `layout`, or `style_config`.

### D-02: Viewer Uses Existing Shared Adapter Path

`ViewerMap` already converts `SharedLayerResponse` into `SyncLayerInput` and calls the same `syncLayersToMap`/adapter registry as builder. Parity verification should assert canonical paint survives that conversion.
</decisions>

<code_context>
## Existing Code Insights

- `use-builder-save.ts` persists `paint`, `layout`, `label_config`, `style_config`, `layer_type`, opacity, visibility, and filter through `buildLayerDiff`.
- `PublicMapViewerPage.toSharedLayer` carries saved `paint`, `layout`, `label_config`, and `style_config` into `SharedLayerResponse`.
- `ViewerMap.toViewerSyncInput` maps `SharedLayerResponse.paint/layout/style_config` into the shared `syncLayersToMap` input.
- `StyleJsonDialog` and backend map style JSON endpoints already have dedicated tests.
</code_context>

<specifics>
## Specific Ideas

- Add a save diff test for gradient-to-solid canonical paint so save/reload cannot resurrect `line-gradient`.
- Add a viewer sync-input test ensuring reconciled saved paint reaches `syncLayersToMap` unchanged and without transient fields.
- Run focused save/viewer/style JSON tests.
</specifics>

<deferred>
## Deferred Ideas

- Full browser save/reload UAT is reserved for Phase 1117 Playwright MCP.
</deferred>
