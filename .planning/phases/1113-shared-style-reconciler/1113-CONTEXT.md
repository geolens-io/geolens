# Phase 1113: Shared Style Reconciler - Context

**Gathered:** 2026-05-25
**Status:** Ready for execution
**Mode:** Autonomous technical implementation

<domain>
## Phase Boundary

Implement the shared reconciler primitive defined in Phase 1112. Scope is `frontend/src/components/builder/layer-adapters/shared.ts` and focused unit tests. Adapter migration is intentionally deferred to Phase 1114.
</domain>

<decisions>
## Implementation Decisions

### D-01: Additive Sync Remains Available

Keep `syncVectorPaint` compatible for existing adapter call sites during this phase. Add new owned-property helpers beside it so Phase 1114 can migrate adapters incrementally.

### D-02: Reconciler Clears Only Declared Owned Keys

The new helper should only clear keys in an explicit owned list. This prevents unrelated MapLibre properties, basemap style mutations, or companion-layer internals from being cleared by accident.

### D-03: Filtering and Error Isolation Are Shared

The reconciler should reuse the existing custom/cross-geometry filtering and `paintValueChanged` comparison behavior, while wrapping `get*Property` and `set*Property` calls so MapLibre errors remain isolated to the individual property.
</decisions>

<code_context>
## Existing Code Insights

- `shared.ts` already has `CUSTOM_PAINT_PROPS`, `filterPaintForLayerType`, `stripCustomProps`, `setLayerProperty`, `syncLayerFilter`, and `paintValueChanged`.
- `syncVectorPaint` currently sets only incoming paint keys and is the compatibility API adapters already use.
- `frontend/src/components/builder/layer-adapters/__tests__/shared.test.ts` is the focused test home for shared adapter utilities.
</code_context>

<specifics>
## Specific Ideas

- Export `syncOwnedPaintProperties` and `syncOwnedLayoutProperties`.
- Support geometry-aware paint filtering for vector adapters.
- Treat `undefined` and `null` as clear signals for owned keys.
- Preserve expression arrays by passing the same value reference to MapLibre.
- Add unit tests for set, no-op, clear, invalid-key filtering, custom metadata filtering, expression identity, layout sync, missing layer no-op, and MapLibre error isolation.
</specifics>

<deferred>
## Deferred Ideas

- Adapter-owned property constants live in Phase 1114 with the adapter migration.
- AI/UI mutation helper wiring lives in Phase 1115.
</deferred>
