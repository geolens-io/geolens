---
quick_id: 260515-tb3
type: quick-task-summary
status: complete
mode: investigation-only-no-implementation
date: 2026-05-15
---

# Quick Task 260515-tb3: BasemapGroupRow Investigation — Summary

**Mode:** RESEARCH ONLY (no code changes, no commits beyond docs).

## Outcome

Two pre-investigation concerns were both CONFIRMED by live Playwright + source trace + backend schema check.

### C1: BasemapGroupRow row slider is broken (no-op)
Real Playwright mouse drag, synthetic pointer drag, ArrowLeft, and Home all left `aria-valuenow` unchanged at 1. Source-level cause: `applyLayerUpdate("basemap-group", …)` short-circuits because no layer in `localLayers` has that synthetic id; the controlled `<Slider value={[safeOpacity]}>` snaps back.

### C2: Master opacity not persisted (Phase-1038 TODO)
Master slider DOES move runtime (1 → 0.55 in test) but Save button stays "Saved" (no dirty flag). `MapBuilderPage.tsx:755-761` has an explicit TODO. Backend `BasemapConfig` schema has NO `opacity` field AND `model_config = ConfigDict(extra="forbid")` would reject any payload sent. Phase-1038 backend prerequisite is real.

## Decision matrix delivered (RESEARCH.md §"Decision Matrix")

- **Path A** (recommended): Remove row slider only — mirrors 260515-rdn/sqf, ~−25 LOC, low risk, removes a confirmed-broken control.
- **Path B**: Path A + ship master-opacity persistence (backend additive Pydantic field on JSONB column, no Alembic DDL needed, ~+30-50 LOC across stack + 1 round-trip test).
- **Path C**: Rewire row slider to setMasterOpacity — NOT recommended (preserves redundancy + persistence gap).
- **Path D**: Defer — NOT recommended (leaves a broken control in production UI).

## Deliverables

- `260515-tb3-CONTEXT.md` — investigation framing
- `260515-tb3-RESEARCH.md` — full findings + evidence + decision matrix
- This SUMMARY.md

## Next step

User picks a path. If Path A or B, kick off a new `/gsd-quick --full` task using 260515-rdn/sqf as the established playbook. If Path B, scope a backend schema addition + Alembic-skip migration confirmation + frontend wire-up + round-trip test.

## Side-finding worth noting

`applyLayerUpdate` in `use-layer-map-sync.ts:52` calls `setHasUnsavedChanges(true)` unconditionally — even when the layerId doesn't match any layer. In live testing the dirty state did NOT propagate (likely React's referential equality bailout on the unchanged `localLayers` array), but it's a defensive-cleanup opportunity to gate the `setHasUnsavedChanges` call on whether `updated` was actually set. Worth folding into Path A or B's task scope.
