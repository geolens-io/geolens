# Phase 1045 — Verification Log

## Plan A (1045-01)

SP-03: **ESCALATE** — B-01 fix at `85738f1c` did NOT fully close M-02. Live Playwright re-check on 2026-05-15 against a fresh map (UUID `58149b92-4086-4241-94ce-719a5e9e09fb`) showed:

- Server: vector layer (QA Canyon Overlays, dataset `b483327e-…`) persisted via `POST /api/maps/<id>/layers` ✓
- Network: `POST /api/tiles/tokens/` returned 200 ✓
- MapLibre style after add: `userSources=[]`, `userLayers=[]` ✗
- After hard reload: `userSources=["source-1926df64-…"]`, `userLayers=["layer-1926df64-…"]` ✓

The new tokenMap-keyed gate at `BuilderMap.tsx:687` is correct but a separate race remains. Hypothesis (not yet root-caused):
- On fresh layer-add, `structuralKey` flips (layers 0→1) → effect fires
- Token fetch in flight → `tokenMap` is empty for this dataset → gate short-circuits
- Token resolves → `tokenMap` reference updates → effect re-runs
- BUT at that moment either `map.isStyleLoaded()` returns false (early bail) OR `syncInputs` is closed over stale `layers` (memoized on `structuralKey` only — same structuralKey value when tokens arrive, so memo doesn't recompute, but the memo body `layers.map(toSyncInput)` uses the same `layers` reference)

Follow-up ticket needed. Defer to a B-01-followup quick task after v1009.1 ships; not blocking the rest of the milestone since:
- Reload-then-edit works fine
- All v1009.1 fixes are independent of M-02
- Workaround: refresh the page after adding a layer

VERIFICATION evidence captured in this session's transcript. Test map `58149b92-4086-4241-94ce-719a5e9e09fb` left in place for the followup investigator; safe to delete.
