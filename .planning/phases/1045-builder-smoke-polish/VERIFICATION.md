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

## Plan C (1045-03)

SP-13: PASS — BasemapGroupRow renders a non-interactive `<span>` glyph with the "Basemap is always visible — use Remove basemap to hide." tooltip when `visibilityDisabled` is true. Disabled `<button>` removed. 2 new tests in `BasemapGroupRow.test.tsx`. Commit `6cbd61ae`.

SP-14: PASS — StackRow row container retains `cursor-pointer` and `hover:bg-[var(--surface-2)]`; legacy `theme()` fallback dropped for clarity. Hover affordance is now discoverable across the whole row body, not just child controls. Commit `6cbd61ae`.

SP-15: PASS — `BulkActionBar` render in `UnifiedStackPanel.tsx` is gated on `!isSettingsOpen` in addition to `selectedIds.size >= 2`. Selection state persists in the parent, so closing Settings brings the bar back unchanged. 3 new SP-15 tests cover open / closed / re-render. Commit `4bc0e293`.

SP-16: PASS — `captureThumbnail` is wrapped in a 500ms trailing-edge debounce keyed by mapId, so two back-to-back saves coalesce into exactly one `PUT /maps/<id>/thumbnail/`. 2 new SP-16 vitest cases + 4 updated captureThumbnail tests + module-level `__resetThumbnailDebounceForTests()` helper. Commits `2f1c3476` (RED test) and `d523f03d` (GREEN impl).

SP-17: PASS — Full-width "＋" U+FF0B character stripped from `unifiedStack.addData` across en/de/es/fr. Lucide `<Plus />` icon stays as the sole visual plus; bumped from `h-3 w-3` to `h-4 w-4` per plan spec. `SidebarRail` aria-label / tooltip defaults updated to match. Commit `6cbd61ae`.

SP-12: SKIPPED — non-trivial layout integration; deferred to follow-up.

Rationale: `<ScaleControl position="bottom-left" maxWidth={100} unit="metric" />`
already renders in both `BuilderMap.tsx:854` and `ViewerMap.tsx:746`, so a
MapLibre scale **bar** is already on screen — the original plan's recommended
implementation path (`new maplibregl.ScaleControl(...) → map.addControl(...)`)
is already satisfied. What the smoke check's `p-01` actually asked for ("A
second pane (current scale or '1:288k') would aid users coming from desktop
GIS") is a different feature: a *representative-fraction* readout (e.g. "1:288k")
in the top-right next to the coord pane. That requires (a) a meters-per-pixel
calculation accounting for the cosine-of-latitude meridian factor, (b) a new
UI slot inside MapCoordReadout, and (c) i18n strings for the "1:N" formatting
and locale-appropriate digit grouping. That's a small feature, not a polish
fix — deferred so this phase stays a tight smoke-polish closeout.

SP-18: PASS — test maps deleted:
- `a00b7e96-95b7-48d6-a911-57b97b767ebc` (Smoke Check 2026-05-15): DELETE → 204, GET → 404.
- `58149b92-4086-4241-94ce-719a5e9e09fb` (SP-03 verify map, marked safe to delete in Plan A note): DELETE → 204, GET → 404.

The trailing-slash forms (`/maps/<uuid>/`) returned 307; the canonical no-slash forms (`/maps/<uuid>`) returned the expected 204/404. Both shapes ultimately resolve to 404, confirming deletion. No code commit (operational housekeeping).

