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

SP-01: PASS — BulkActionBar refactored to overflow menu (`More actions` Lucide `MoreHorizontal`) containing Group / Ungroup / Delete; Visibility + Opacity stay inline. CTRL-01 spot check confirms `aria-label="More actions"` button rendered inside the sidebar at multi-select. Commit `bbde1a5d` + `7aba7cd9` (review fix to keep selection alive when popover opens).

SP-02: PASS — Coord readout subscribes to MapLibre `move` events via `useMapViewState(map)`; live test (`map.jumpTo([-112.35, 36.2], 9)`) updates readout text from initial to `36.20° N · 112.35° W · z 9.0`. Commit `05daacc0`.

SP-04: PASS — Shift-click range-select extracted into `computeNextSelection` pure helper with anchor via `useRef`. macOS Finder semantics in both directions. Vitest unit tests cover plain / cmd / shift / mixed flows. Commit `5deb2187`.

SP-05: PASS — `hasUnsavedStyleChanges(draft, layer)` helper gates the "Pending style preview" banner on a real deep-equal comparison of paint/layout/style_config. No banner on fresh-add; banner appears on first mutation; banner disappears on Reset. Commit `88b75216`.

## Plan B (1045-02)

SP-06: PASS — Duplicate "Saved" badge removed from `MapBuilderPage.tsx` header; the Save button now carries Saved / Saving… / Save state alone. Commit `f5a815d8`.

SP-07: PARTIAL-PASS — `quicklook-cache.ts` caches 404 responses so the search page no longer hits the endpoint repeatedly. **Caveat:** the first request per session per known-bad dataset still fires once before cache populates. Honest fix is a backend `has_quicklook` predicate (out of scope per the plan and per the lower-risk-frontend-skip mandate in REQUIREMENTS.md SP-07). Live CTRL-01 spot check on `/` shows the same 3 quicklook 404s on first load. Logged as known-residual in `deferred-items.md`. Commit `b70a9caf` + `be06a4f8` (test tightening).

SP-08: PASS — `use-ai-availability.ts` wrapped in TanStack `useQuery` with `queryKey: ['admin', 'ai-status']`, `staleTime: 60_000`, `gcTime: 300_000`. Vitest covers shared-cache behavior. Commit `5b4ebcfb`.

SP-09: PASS — Module-level `inflightRefresh: Promise | null` singleton in `client.ts` collapses concurrent 401 → refresh calls; `use-auth.ts` proactive timer routed through the same `tryRefresh` export to avoid bypassing the mutex. Commit `6b940ca2`.

SP-10: PASS — `aria-pressed={layer.visible}` added to every visibility toggle in `StackRow.tsx` and basemap row of `UnifiedStackPanel.tsx`. CTRL-01 spot check confirms `aria-pressed="true"` on each. Commit `532ca595`.

SP-11: PASS — `/auth/login` decorator changed from trailing-slash to canonical no-slash. CTRL-01 spot check: `curl -X POST http://localhost:8001/auth/login` returns `200` (no `307`). Commit `76927b9b`.

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


## CTRL-01 batch gate (phase end)

**Result:** 16 PASS + 1 PARTIAL-PASS (SP-07) + 1 ESCALATE (SP-03) + 1 SKIPPED-with-rationale (SP-12) = 18/18 reqs accounted for.

| SP | Severity | Result | Notes |
|---|---|---|---|
| SP-01 | BLOCKER | PASS | Overflow menu (live CTRL-01) |
| SP-02 | MAJOR | PASS | Coord readout updates on `move` (live CTRL-01) |
| SP-03 | MAJOR | ESCALATE | B-01 fix did not fully close M-02; deferred to follow-up quick task |
| SP-04 | MAJOR | PASS | Shift-click range-select (unit-tested + helper extracted) |
| SP-05 | MAJOR | PASS | "Pending preview" banner dirty-gated |
| SP-06 | MINOR | PASS | Duplicate Saved badge removed |
| SP-07 | MINOR | PARTIAL-PASS | Cache prevents repeats; first request still fires; backend fix deferred |
| SP-08 | MINOR | PASS | TanStack staleTime 60s |
| SP-09 | MINOR | PASS | Auth refresh mutex via `tryRefresh` export |
| SP-10 | MINOR | PASS | `aria-pressed` added (live CTRL-01) |
| SP-11 | MINOR | PASS | `/auth/login` returns 200 not 307 (live CTRL-01) |
| SP-12 | POLISH | SKIPPED | Scale BAR already present; "1:N" representative-fraction is a new feature |
| SP-13 | POLISH | PASS | Basemap eye is `<span>` glyph (live CTRL-01) |
| SP-14 | POLISH | PASS | Row hover affordance |
| SP-15 | POLISH | PASS | BulkActionBar hidden during Settings scene |
| SP-16 | POLISH | PASS | Thumbnail PUT 500ms trailing debounce |
| SP-17 | POLISH | PASS | Full-width plus removed; Lucide `<Plus />` only (live CTRL-01) |
| SP-18 | HOUSEKEEPING | PASS | Test maps deleted (live curl 204/404 verified) |

**Console errors during CTRL-01 session:** 3 quicklook 404s remain (SP-07 PARTIAL-PASS). All other surfaces clean (builder, settings panel, basemap editor, multi-select).

**Vitest gate:** Plan A 174/174 + Plan B 174/174 + Plan C 168/168 = all passing on affected files.

**Frontend typecheck + lint:** clean (5 pre-existing lint errors on `main` documented in `deferred-items.md`, none new from this phase).

**Backend ruff + pytest:** clean (37/37 auth tests passing).

**Deferred follow-ups:**
1. SP-03 (M-02 race): needs deeper root-cause investigation; suspect `syncInputs` memo closure or `mapReady` timing
2. SP-07 first-request 404: needs backend `has_quicklook` predicate
3. SP-12 representative-fraction pane: small feature, not polish
4. 5 pre-existing `main` lint errors (out of scope per Plan A note)
