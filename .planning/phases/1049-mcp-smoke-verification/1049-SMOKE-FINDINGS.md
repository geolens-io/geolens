---
phase: 1049
status: clean
findings_total: 8
severity:
  p0: 2
  p1: 2
  p2: 4
dispositions:
  shipped_inline: 3   # SF-01, SF-02, SF-03
  deferred_with_rationale: 1   # SF-04
  deferred_p2_tech_debt: 4   # SF-05, SF-06, SF-07, SF-08
post_fix_re_smoke: passed
date: 2026-05-16
runner: Playwright MCP (Chromium, localhost:8080)
test_map: c868cc3a-a3a0-4714-b559-67b3f2b478e2 (v1010.1 Smoke Map, 8 layers)
---

# Phase 1049 — MCP Smoke Findings (v1010.1)

Fresh-stack interactive Playwright MCP smoke against the five v1010 win surfaces. All passes A–E executed on the v1010 tag baseline. Surface verdicts and per-finding dispositions below; final dispositions resolved during Task 9.

## Surface verdicts (one-liner each)

- **Pass A — Auth + Builder route:** ✅ Clean. Login form-encoded redirects through `/login` → `/` → `/maps/{id}` correctly. Builder mounts with 8 layers + basemap + legend widget. Two non-blocking observations (SF-05 thumbnail blob lifecycle, SF-06 pre-auth probes).
- **Pass B — Lazy-load (PERF-05):** ⚠ Mostly clean. `SettingsEditorScene` and `BasemapGroupEditorScene` confirmed lazy-fetched on first open (Vite module requests #397 + #398). **SF-03 (P1):** `StyleJsonDialog` `lazy()` is defective — chunk loads on initial builder mount because the parent always renders the `<Suspense>` regardless of `open=showStyleJson` state.
- **Pass C — Debounce + rAF (PERF-04):** ✅ Clean. Opacity slider drag (10 ArrowLeft + Home) → zero `PUT` requests during drag; dirty flag set deep-equal correctly; zero console errors. Filter editor typing also fires zero saves during input. (Save model is manual `⌘S` not auto-save — confirmed expected behavior.)
- **Pass D — Bulk-delete (PERF-03):** 🚨 **BROKEN (P0).** The "Delete N layers" confirm button click does not invoke `POST /api/maps/{id}/layers/bulk-delete` — no API request, no toast, no deletion, no optimistic UI update. Backend endpoint verified working via direct fetch (200 + `{deleted:[...], failed:[]}` shape). UI wiring is the regression.
- **Pass E — LayerStyleEditor split + popup_config:** Mixed. **SF-02 (P0):** Render-mode swap Line→Arrow on MultiLineString layer throws MapLibre validation errors (`layout.line-cap` / `layout.line-join` "unknown property"). Layer add fails — render-mode swap is non-functional for Line→Arrow. ✅ `popup_config` invalid template (`{{NONEXISTENT_COLUMN}}`) → named error toast `Cannot save: layer "Layer 2" has an invalid popup expression.` and zero save fired; clear template → success toast + PATCH + PUT — works as v1010 FOLLOWUP-01 designed.

## Findings

### SF-01 — Bulk-delete confirm does nothing (P0, BULK-DELETE)

**Observed:** With 3 layer rows selected (Layer 6/7/8 originally, then Layer 3/4/5 after reload), opening the BulkActionBar overflow popover → clicking "Delete 3 selected layers" → clicking inline "Delete 3 layers" confirm button: (1) BulkActionBar dismisses, (2) selection clears, (3) **no `POST */layers/bulk-delete` request is made**, (4) no toast, (5) layer count unchanged. The optimistic local-state filter that `handleBulkDelete` does at `use-builder-layers.ts:560-564` does not run either — confirmed via `document.querySelectorAll('[role="option"]').length` staying at 9 before/after.

**Evidence:** Verified twice (once with stale dirty state, once with fresh reload + clean Saved state). `window.__fetchSeen.filter(r => r.method !== 'GET')` returns only `/api/tiles/tokens/` POSTs — no bulk-delete. A capture-phase `document.addEventListener('click', …, true)` recorded the menuitem click (CAPTURE 4: `bulk-action-delete Delete`) but did **not** record a 5th capture for the inline "Delete N layers" confirm button — suggesting the click either never reaches the document or hits a different element. Backend endpoint proven good: direct `fetch('/api/maps/{id}/layers/bulk-delete', { method: 'POST', body: { layer_ids: [...] } })` returns 200 with all 3 layers in `deleted`.

**Likely cause:** Closure/identity issue in `BulkActionBar` confirm button at `frontend/src/components/builder/BulkActionBar.tsx:202-216`. The button's `onClick` calls `onBulkDelete(selectedIds)`, but `selectedIds` is the prop captured at render time. Suspect: the dropdown closure between menuitem click and confirm button click causes a stale closure or a setSelectedIds clear from another handler. The setState pattern in MapBuilderPage clears selection on multiple paths (line 403/414/428/433/439/586).

**Screenshots:** `01-D-01-multi-select.png`, `01-D-02-overflow-popover.png`, `01-D-03-confirm-bar.png`, `01-D-04-post-confirm-still-8.png`, `01-D-05-fresh-confirm-state.png`.

**Recommended fix (applied):** Diagnosis was different than the initial hypothesis — `selectedIds` was being cleared by the `UnifiedStackPanel.tsx:656-668` outside-click guard. `stackPanelRef` only scopes the inner `<div role="listbox">`, while the BulkActionBar is rendered as a sibling sticky footer. A mousedown inside the BulkActionBar fired the document-level listener, called `onClearSelection()`, set `selectedIds` to `new Set()`, and unmounted the bar via the `selectedIds.size >= 2` gate at `UnifiedStackPanel.tsx:1027` *before* React's click handler could dispatch `onBulkDelete(selectedIds)`. The container's own `onPointerDown={(e) => e.stopPropagation()}` (`BulkActionBar.tsx:137`) does not help because document-level listeners receive events in capture phase regardless of synthetic-event stopPropagation. **Applied fix:** add `data-bulk-action-bar="true"` to the toolbar root (`BulkActionBar.tsx:134`) and extend the guard's portal-exception in `UnifiedStackPanel.tsx:658-666` to also treat clicks inside `[data-bulk-action-bar="true"]` as in-bounds — mirrors the SP-01 (Phase 1045) hatch for the Radix DropdownMenu portal.

**Disposition:** `shipped-inline` (commit `c4576717`).

---

### SF-02 — Render-mode swap Line→Arrow throws MapLibre validation (P0, LAYER-STYLE-SPLIT)

**Observed:** On Layer 1 (MultiLineString), clicking "Render as → Arrow" in the LayerEditorPanel produces two console errors:
- `Error: layers.layer-{id}.layout.line-cap: unknown property "line-cap"`
- `Error: layers.layer-{id}.layout.line-join: unknown property "line-join"`

Stack: `circle-adapter.ts:11 → use-builder-layers.ts:712 → onRenderModeChange (use-builder-layers.ts:835) → LayerEditorPanel.tsx:300`. The `line-cap`/`line-join` layout properties (carried over from the previous Line render-mode) are not stripped before `addLayer()` for the new render mode (which goes through the circle adapter — implying Arrow rendering uses circle/symbol style under the hood). MapLibre's `_validate()` rejects the addLayer, so the swap silently fails — the old line layer remains.

**Evidence:** `01-E-01-line-mode.png`, `01-E-02-arrow-mode.png`. Console errors captured by `browser_console_messages` after the toggle click.

**Likely cause:** `frontend/src/components/builder/hooks/use-builder-layers.ts:712` (the `onRenderModeChange` handler that delegates to the new mode's adapter) does not call the previous adapter's `removeLayers` cleanly OR does not strip the previous mode's `layout`/`paint` keys when synthesizing the new layer spec. Suggest sanitizing the `layout` object based on the destination adapter's allow-list before `addLayers()`.

**Recommended fix (applied):** Root cause was different than first guess. `LayerEditorPanel.tsx:354-358` unsafely cast `option.id as 'points' | 'heatmap' | 'symbol' | 'cluster'` even though `getRenderAsOptions()` surfaces the full `RenderAsId` union (incl. `arrow`, `line`, `fill`, `stroke`, `fill-stroke`, `extrusion-3d`, `image`, `hillshade`). `handleRenderModeChange` then fell through to its default `swapLayerOnMap(layer, 'circle', updatedPaint)` branch for `arrow`, re-emitting the layer through the circle adapter while passing the previous Line layout (line-cap / line-join) untouched. MapLibre rejected the addLayer. **Applied fix:** widen the `onRenderModeChange` prop type to `RenderAsId`, drop the unsafe cast, and dispatch the non-circle renderAs ids (arrow / line / fill / stroke / fill-stroke / extrusion-3d / image / hillshade — alongside the pre-existing cluster) through `handleRenderAsChange`, which uses `buildRenderAsPatch()` to compute the correct adapter + paint/layout for the destination.

**Disposition:** `shipped-inline` (commit `8713b73f`).

---

### SF-03 — StyleJsonDialog defective `lazy()` (P1, LAZY-LOAD)

**Observed:** Network log on initial builder mount shows `src/components/builder/StyleJsonDialog.tsx` fetched at request #243 — eagerly, before the user opens the Style JSON button. The `lazy()` wrapper at `MapBuilderPage.tsx:55` has zero PERF effect because line 1342 mounts `<StyleJsonDialog>` unconditionally inside `<Suspense>` (only gated on `id` truthy, not on `showStyleJson` open state). React.lazy() resolves the dynamic import the moment the component is mounted, even if the component itself returns `null`.

**Evidence:** Network filter on `StyleJsonDialog|DEMEditor|BasemapSublayer`. StyleJsonDialog loaded eagerly at #243 alongside BuilderMap (#242), whereas BasemapGroupEditorScene (#398) and SettingsEditorScene (#397) loaded only after their respective click — those work correctly.

**Recommended fix (applied):** Wrap the StyleJsonDialog render in `{id && showStyleJson && (...)}` at `MapBuilderPage.tsx:1339`. Suspense child now only mounts on first open of the dialog.

**Disposition:** `shipped-inline` (commit `3df84554`).

---

### SF-04 — Duplicate tile source per layer (P1, GENERAL)

**Observed:** Initial map load fires the SAME tile URLs 4–5 times each (same MVT path + same signed token) on the test map. The map has 8 layers but only 2 unique source datasets (`reefs_10m_2` × 4, `admin_0_countries_10m_2` × 4). Network log shows ~80 vector tile requests for what should be ~16-24. Each layer appears to register its own MapLibre source instead of sharing one source per dataset.

**Evidence:** Network log requests 299–394 in `01-A-02-builder-loaded` baseline (filter `data\\.`). Identical `sig=...` and tile coords repeated for each duplicate-source layer.

**Recommended fix:** In the layer-add path (likely `frontend/src/components/builder/hooks/use-builder-layers.ts` mount-add or `BuilderMap.tsx` source registration), check `map.getSource(sourceId)` before `addSource()` and reuse existing sources when multiple layers share the same `dataset_table_name`. This is a `defaults` bug (PB-04 / PB-05 territory in the v1010 perf inventory) — measurable PERF win.

**Disposition:** `deferred-with-rationale`. Reusing MapLibre sources across layers that share the same `dataset_table_name` would change the source-id keying contract used by `swapLayerOnMap` (`use-builder-layers.ts:760`), the per-layer `removeSource` path, the dataset/tile-token signing scope, and the cluster-source override at `cluster-source.ts`. Each of those touches its own test surface and likely needs a coordinated migration of saved-map layer rows. Effort >> 1hr, regression surface high, and the symptom is purely a per-tile network duplication on initial map load — not blocking any v1010.1 win. Tracked as a new tech-debt item: `BUILDER-PERF-DEDUPE-SOURCES`.

---

### SF-05 — Thumbnail blob ERR_FILE_NOT_FOUND on post-login redirect (P2, GENERAL)

**Observed:** Immediately after the login form POST and redirect to `/`, 4 console errors:
```
Failed to load resource: net::ERR_FILE_NOT_FOUND @ blob:http://localhost:8080/<uuid>:0
```
Each is a `blob:` URL — likely thumbnail blob URLs being `revokeObjectURL()`-ed before the `<img src>` finishes loading. No user impact (thumbnails were probably from cached search results just before login).

**Evidence:** `browser_console_messages` Pass A.

**Recommended fix:** Defer `URL.revokeObjectURL(blob)` to an unmount cleanup OR use a longer revoke timeout. Locate by `git grep "revokeObjectURL" frontend/src`.

**Disposition:** `deferred-with-rationale` — P2 tech-debt; non-blocking polish noise. Tracked under tech-debt for a future hygiene sweep.

---

### SF-06 — Anonymous pre-auth probes to authed endpoints (P2, GENERAL)

**Observed:** Visiting `/login` (unauthenticated) fires 4–5 401-noise requests to `/api/auth/me/`, `/api/auth/me/permissions/`, `/api/admin/ai-status/`, `/api/search/saved/`, `/api/auth/refresh/`. The `/api/admin/ai-status/` endpoint hitting from an anonymous page is especially suspicious — the admin endpoint shouldn't be probed unless the user is admin-authed. All return 401 (correct backend behavior); the noise is console error spam.

**Recommended fix:** Gate the auth/me/admin probes behind `auth.isAuthenticated` (or at least suppress error-level logging on these specific 401s in the React Query global error handler).

**Disposition:** `deferred-with-rationale` — P2 tech-debt; non-blocking polish noise. Tracked under tech-debt for a future hygiene sweep.

---

### SF-07 — Two PUT /thumbnail/ on initial map load (P2, GENERAL)

**Observed:** Initial map mount fires TWO `PUT /api/maps/{id}/thumbnail/` requests (network log entries 395, 396). v1009.1 SP-16 explicitly added a 500ms debounce for thumbnail PUTs, expecting exactly 1. The doubling is small but reproducible — possibly an effect dep that fires once on initial paint and once after first tile-paint settle.

**Recommended fix:** Audit `frontend/src/components/builder/hooks/use-builder-save.ts` (or wherever thumbnail PUT lives) to confirm the 500ms debounce is wrapping the *effect* rather than the click handler — initial-mount paint events may bypass the debounce.

**Disposition:** `deferred-with-rationale` — P2 tech-debt; non-blocking polish noise. Tracked under tech-debt for a future hygiene sweep.

---

### SF-08 — Basemap connection issue toast on save (P2, POPUP-CONFIG)

**Observed:** When saving the map with the popup template fix (Pass E), a toast appeared: `Basemap connection issueYour data layers are still editable. Check the basemap service or choose another basemap if the background stays blank.` The basemap (openfreemap-positron) had loaded successfully on map mount (we saw it render correctly). The toast appears to be a false positive triggered by a transient style-fetch error on save, not a real basemap outage.

**Evidence:** Pass E `evaluate(toasts)` returned this toast alongside the `Map saved` toast.

**Recommended fix:** Re-evaluate the basemap connection check on save — should NOT fire if the basemap was previously confirmed loaded. Likely in `frontend/src/components/builder/hooks/use-builder-save.ts` or `BuilderMap.tsx` error handler.

**Disposition:** `deferred-with-rationale` — P2 tech-debt; non-blocking polish noise. Tracked under tech-debt for a future hygiene sweep.

---

## Post-fix re-smoke

Run after commits `c4576717` (SF-01), `8713b73f` (SF-02), `3df84554` (SF-03) — same Playwright MCP session, hot-reloaded Vite.

| Surface | Verdict | Evidence |
|---|---|---|
| SF-01 bulk-delete | ✅ PASS | Selected Layer 3/4/5 via meta+shift dispatch, opened overflow, clicked Delete in dropdown, clicked inline "Delete 3 layers" confirm. Network log shows exactly **1** `POST /api/maps/{id}/layers/bulk-delete`. Toast: `"3 layers deleted"`. Listbox went from 5 → 2 layers. Screenshot: `02-A-bulk-delete-success.png`. |
| SF-02 render-mode swap | ✅ PASS | Layer 1 (MultiLineString) clicked Arrow → zero new console errors (previously: 2× `unknown property line-cap/line-join`). Toggled back to Line → still zero errors. Round-trip clean. `data-active` confirmed swap state. Screenshot: `02-B-arrow-mode-no-errors.png`. |
| SF-03 StyleJsonDialog lazy | ✅ PASS | Hard reload of `/maps/{id}`. Network filter for `StyleJsonDialog` returned **0 hits** on initial mount (previously: request #243). Clicked Style JSON toolbar button → chunk fetched at request #322 — lazy load now correctly deferred to first open. Screenshot: `02-C-style-json-lazy-confirmed.png`. |

No regressions observed in the verified surfaces. Touched code: `BulkActionBar.tsx`, `UnifiedStackPanel.tsx`, `LayerEditorPanel.tsx`, `use-builder-layers.ts`, `MapBuilderPage.tsx`. Frontend typecheck clean; targeted vitest suites: 42/42 (`BulkActionBar.test.tsx` + `UnifiedStackPanel.multi-select.test.tsx`), 20/20 (`renderAs.test.ts`), 86/86 (`LayerEditorPanel.test.tsx` + `LayerStyleEditor.test.tsx`).

## v1010 surface coverage matrix (post-fix)

| Surface | Win promise | Initial verdict | Final verdict |
|---|---|---|---|
| Lazy-load (PERF-05) | 5 scenes fetch on demand | ⚠ 2/5 + SF-03 defective | ✅ 3/5 verified (Settings, BasemapGroup, StyleJsonDialog post-fix); DEM / BasemapSublayer not exercised (no DEM layer seeded) |
| Debounce + rAF (PERF-04) | No save / paint churn during drag | ✅ Working | ✅ Working — zero PUTs during drag, no jank, no console errors |
| Bulk-delete (PERF-03) | 1 batched POST replaces N DELETEs | 🚨 BROKEN (SF-01) | ✅ Fixed inline (`c4576717`) — exactly 1 `POST /layers/bulk-delete` per confirm; "3 layers deleted" toast |
| LayerStyleEditor split (CODE-02/CB-07) | Per-mode child editors swap cleanly | ⚠ Line→Arrow threw MapLibre validation (SF-02) | ✅ Fixed inline (`8713b73f`) — Line↔Arrow round-trip clean, zero console errors |
| popup_config error (FOLLOWUP-01) | Named error toast on invalid template | ✅ Working | ✅ Working — named toast on invalid; success toast on clear |

## Screenshots reference

All in `.planning/phases/1049-mcp-smoke-verification/screenshots/` (gitignored).
- Pass A: `01-A-01-login-baseline.png`, `01-A-02-builder-loaded.png`
- Pass B: `01-B-01..04*.png`
- Pass C: `01-C-01..04*.png`
- Pass D: `01-D-01..05*.png`
- Pass E: `01-E-01..06*.png`

## Test environment

- Docker stack rebuilt fresh (`down -v && up -d --build`) prior to this session — 5/5 services healthy.
- Admin JWT obtained via form-encoded POST `/auth/login` on backend port 8001.
- Test map seeded with 8 alternating reef + admin-countries layers from `~/.geolens/cache/` NaturalEarth fixtures.
- Browser: Chromium via Playwright MCP. Viewport: 1440×900.
- Frontend: localhost:8080 (Vite dev mode through nginx proxy).
