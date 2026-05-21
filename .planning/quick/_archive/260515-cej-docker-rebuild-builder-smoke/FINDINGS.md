---
quick_id: 260515-cej
slug: docker-rebuild-builder-smoke
date: 2026-05-15
type: smoke-check
---

# Map Builder Smoke Check — Findings

**Date:** 2026-05-15
**Environment:** Local Docker stack, post-rebuild (`docker compose build --no-cache` + `up -d`)
**Stack versions:** geolens-api, geolens-worker, geolens-migrate, geolens-frontend, geolens-db (all rebuilt from scratch); titiler 2.0.2 (pulled image)
**Tooling:** Playwright MCP (Chromium), 1440 × 900 viewport
**Auth:** Logged in as `admin` via persisted session
**Test map:** Freshly created `Smoke Check 2026-05-15` (UUID `a00b7e96-95b7-48d6-a911-57b97b767ebc`) with one vector + one raster (DEM) layer; pre-existing `Phase 1002 Builder Audit Baseline` also probed for control comparison.

---

## Rebuild — PASSED

| Step | Result |
|---|---|
| `docker compose down` | Clean exit, network removed |
| `docker compose build --no-cache` | All 5 images rebuilt (db, api, worker, migrate, frontend) |
| `docker compose up -d` | Migrations completed, all 5 services healthy within ~30s |
| `curl /` (frontend `:8080`) | 200, ~16 ms |
| API discovery (`/openapi.json`) | 200, all routes present |
| Vector tile endpoint live | 200 OK on `/api/tiles/data.qa_canyon_overlays_*/{z}/{x}/{y}.pbf` |
| Containers steady | 5/5 healthy after 5 min idle |

No image build errors; no migration errors; no panics in container logs (spot-checked).

> **Note:** Volumes (db, uploads) were preserved (`down` without `-v`) so the existing 3 seeded maps + 6 datasets remained available for smoke testing. If a true "from zero" rebuild is required, repeat with `down -v`.

---

## Severity legend

| Tag | Meaning |
|---|---|
| 🟥 **BLOCKER** | Breaks a core user task; ships-stopping |
| 🟧 **MAJOR** | Functional regression or significant UX failure with workaround |
| 🟨 **MINOR** | Clear bug or polish gap; not blocking |
| 🟦 **POLISH** | Nit / inconsistency / a11y improvement |

---

## 🟥 BLOCKER findings

### B-01 — First-time layer-add does not push layers to MapLibre style (silent failure)

**Repro:**
1. Create a new empty map via `/maps` → Create Map.
2. Open Add Data modal → click "Add to map" on any catalog dataset.
3. Sidebar updates; legend updates; LayerEditorPanel flyout opens; map auto-zooms to layer bbox.
4. **But the map renders only the basemap — the user's data layer is not visible.**

**Evidence:** Direct inspection of the MapLibre `map.getStyle()` after adding 2 layers (1 vector, 1 raster DEM) showed:
- `sources: ["ne2_shaded", "openmaptiles"]` — only basemap sources.
- `layers: 55` — all basemap layers; **zero** `source-<uuid>` / `layer-<uuid>` entries.
- Zero tile requests to `/api/tiles/data.<table>/<z>/<x>/<y>.pbf` (vector) or any titiler/raster endpoint.

**After hard reload of the same URL**, the maplibre style does contain the user sources/layers — confirming this is specifically a "live add" sync regression.

**Impact:** First-run experience after creating a map looks completely broken. The user adds a layer, sees the panel say it succeeded, sees the map auto-pan to the data, and finds nothing rendered. The natural reaction is "this map builder is broken" — only an F5 reveals the data.

**Likely cause:** `BuilderMap.tsx:677` syncs on `[structuralKey, mapReady, tileConfig?.cdn_base_url, clusterGeoJsonVersion, tileTokensPending]`. On first add, either `mapReady` is still false when `structuralKey` flips, or the effect's `if (layers.length > 0 && tileTokensPending) return;` short-circuit fires before tokens land and is never re-triggered. Worth instrumenting that exact effect.

**Files to investigate:** `frontend/src/components/builder/BuilderMap.tsx` (effect at line 677–686), `frontend/src/components/builder/map-sync.ts` (entry: `syncLayersToMap`), `frontend/src/hooks/use-tile-token.ts`.

---

### B-02 — BulkActionBar Delete / Group / Ungroup buttons clipped — bulk delete unreachable

**Repro:**
1. With ≥ 2 user layers in a map, ⌘-click two non-basemap rows in the sidebar.
2. The bulk bar appears at the bottom of the sidebar showing "2 selected · 👁 Visibility · Opacity ━●━".
3. Group / Ungroup / Delete buttons exist in the DOM at x=329, 413, 509 (CSS px) but the parent **`<aside class="border-e bg-background flex flex-col overflow-hidden">` clips at the 340 px sidebar boundary**, so only Visibility (x=99–188) and the opacity slider are visible.

**Evidence:** Programmatically queried `getBoundingClientRect()` for each button:

| Button | x | width | Visible in viewport? |
|---|---|---|---|
| Visibility | 99 | 89 | ✅ inside sidebar |
| Opacity slider | ~190 | – | ✅ inside sidebar |
| Group | 329 | 76 | ❌ x+w = 405, clipped by sidebar `overflow-hidden` |
| Ungroup | 413 | 89 | ❌ fully outside |
| Delete | 509 | 78 | ❌ fully outside |

**Impact:** The v1009 milestone explicitly delivered multi-select + bulk delete. In the shipped build, **bulk Delete is not reachable from the UI**. Group / Ungroup also unreachable. Workaround: single-select Delete via per-row LayerEditor. **No keyboard shortcut surfaced either** (no Delete/Backspace handler on `[role="option"]` selection).

**Likely cause:** The `BulkActionBar` is rendered inside the sidebar `<aside>` but its inner flex row exceeds the sidebar width. Either:
- the bar should span across the bottom of the entire builder (full width), OR
- the action buttons should collapse into an overflow menu when narrow.

**Files to investigate:** `frontend/src/components/builder/BulkActionBar.tsx`, `frontend/src/components/builder/UnifiedStackPanel.tsx` (where it's mounted), `frontend/src/pages/MapBuilderPage.tsx` (sidebar shell).

---

## 🟧 MAJOR findings

### M-01 — Coordinate / zoom readout in builder header is stale or wrong

**Repro:**
1. In the builder, observe the top-right readout (`<lat>° N · <lng>° E · z <zoom>`).
2. Pan / zoom the map.

**Observed:**
- Readout starts at the map default (`20.00° N · 0.00° E · z 2.0`).
- After auto-fit-to-bbox, zoom updates (e.g. `z 9.7`, `z 11.0`) but **lat/lng never update** — stayed at `20.00° N · 0.00° E` even when the map was clearly centered over the Grand Canyon (≈ 36.2°N / 112.3°W).
- This persisted across the entire session, multiple zoom levels, and a manual `map.jumpTo()`.

**Impact:** The header readout is meant to give users situational awareness. Currently it is actively misleading. For an editor product this erodes trust.

**Likely cause:** The component reads from a default `viewState` source that isn't subscribed to `move`/`moveend` events. Worth searching for `°N` / `°E` formatter near map header in `MapBuilderPage.tsx` or a `MapStatus*` component.

---

### M-02 — DEM raster auto-add fails when initial zoom doesn't match minzoom

**Repro:** Add the QA Grand Canyon DEM as Image mode. Layer adds; map auto-zooms; nothing renders.

**Observed:** The DEM has a `minimum zoom` of 0 and `maximum zoom` of 22 in the panel, but after add, even at z 9–11 the only thing visible is faint basemap relief — no raster image overlay until the user pans/zooms (which in our run forced the maplibre style sync we noted in B-01).

**Likely entangled with B-01.** After page reload, navigating to z=11 over the bbox does render the DEM image (smoke-09 screenshot confirms colourful raster). The combination of B-01 + this fitBounds + render-after-reload pattern means users may interpret B-01 as "the DEM doesn't work".

---

### M-03 — Shift-click on layer rows replaces selection instead of extending range

**Repro:**
1. Click on row A → selected.
2. Shift-click on row B → expected: A + B both selected (typical Finder / list-box behavior).
3. Actual: only B selected; A deselected.

**Workaround:** ⌘/Ctrl-click (toggle individual). Works fine; bar appears.

**Impact:** Range-select is the more natural multi-select gesture for ordered list-boxes, especially with the v1009 multi-select feature being a flagship. Documenting "use ⌘-click" is a workaround; range-select should be added.

**File to investigate:** `frontend/src/components/builder/UnifiedStackPanel.tsx` (keyboard / mouse selection handler).

---

### M-04 — "Pending style preview" banner appears on layer that has no edits

**Repro:**
1. Add any vector layer.
2. Open the LayerEditorPanel by clicking the layer row.
3. Banner reads: **"Pending style preview — Reflects this layer before save"** with a **Reset** action — *immediately, on first open, with no user changes.*

**Impact:** Implies the layer is in a dirty/draft state when it isn't. The Reset action is also unclear — reset to what? The defaults? The server state (which is the current state)? Confuses the dirty-tracking mental model.

**File to investigate:** `frontend/src/components/builder/LayerStyleEditor.tsx` (the `stylePreviewStyle` helper + the banner copy). The banner should be gated on actual unsaved style mutations, not on the layer's existence.

---

## 🟨 MINOR findings

### m-01 — Header save state shows "Saved" twice (badge + button)

**Repro:** Open any saved map in the builder.

**Observed:** Top-right region shows `[✓ Saved]` badge **and** `[Save] Saved` button next to each other. Two redundant "Saved" labels.

**Suggested fix:** Show "Saved" via the button label only, or hide the badge when the button isn't in "Unsaved" state.

---

### m-02 — `/api/datasets/<id>/quicklook?size=256` returns 404 for 3 of 6 seeded datasets

**Console errors (search page, load):**
- `GET /api/datasets/9773fbcc-…/quicklook?size=256` → 404
- `GET /api/datasets/bbb61bdb-…/quicklook?size=256` → 404
- `GET /api/datasets/777ddb26-…/quicklook?size=256` → 404

These are 3 of the older "sample" MultiPoint vector datasets seeded into this dev environment. Records exist (200 on `/api/datasets/<id>`); only the thumbnail is missing.

**Impact:** Console error noise on every Search page load. Card placeholders render OK (graceful degradation). May indicate background thumbnail-generation Celery jobs failed for those datasets, or quicklook was never generated for them.

**Suggested fix:** Either backfill the quicklooks, or have the API return 204 (No Content) + a "no preview" sentinel instead of 404 — and skip the request in the UI when `thumbnail_status != 'ready'`.

---

### m-03 — `/api/admin/ai-status/` polled aggressively

**Observed:** During a single ~3-minute builder session, **`/api/admin/ai-status/` was hit 11+ times** (request indices 137, 257, 331, 340, 344, 347, 348, 349, 350, 361, 372). Bursts of 3+ within the same second on some screen transitions.

**Impact:** Wasted network + DB cycles; presumably an unmemoized hook used in a frequently-re-rendered ancestor (`AppLayout` likely).

**Suggested fix:** Cache `ai-status` in TanStack Query with a sensible `staleTime` (≥ 60 s), or hoist it to a single context.

---

### m-04 — `/api/auth/refresh/` fired 3× in quick succession (~same second)

**Observed:** Requests 352, 353, 354 — three POST `/api/auth/refresh/` calls within ms of each other. All returned 200.

**Impact:** Likely concurrent in-flight refreshes triggered by multiple tile-token requests racing through the 401 → refresh interceptor. Risk of refresh-token rotation race if rotation is enforced. Worth verifying the auth interceptor de-duplicates concurrent refreshes (`Promise` singleton pattern).

**Suggested fix:** Coalesce concurrent refresh attempts behind a single in-flight promise in `frontend/src/api/client.ts`.

---

### m-05 — Visibility toggle buttons missing `aria-pressed`

**Observed:** Buttons like `<button aria-label="Toggle visibility for QA Canyon Overlays …">` have `aria-pressed: null`. They're toggles but don't expose their toggled state to assistive tech.

**Suggested fix:** Add `aria-pressed={layer.visible}` to the eye buttons in `StackRow.tsx`. Same for the basemap row.

---

### m-06 — `/auth/login` 307 redirect to `/auth/login/` (trailing slash)

**Observed (server-side):** `curl -X POST http://localhost:8001/auth/login` → `307 Temporary Redirect` to `/auth/login/`.

This is consistent with the documented FastAPI trailing-slash gotcha in `CLAUDE.md`. Browser auth works because the frontend hits `/api/auth/login/` already. But any external integrator hitting `/auth/login` will see the redirect and (if their HTTP client doesn't follow 307 with body re-POST) lose the body. Worth either: (a) defining the route without trailing slash, or (b) documenting in the OpenAPI description.

---

## 🟦 POLISH

### p-01 — Coordinate readout doesn't include zoom unit / scale

Readout format `36.20° N · 112.33° W · z 9.7` is helpful but the zoom value is unitless. A second pane (current scale or "1:288k") would aid users coming from desktop GIS. Optional.

### p-02 — Layer panel basemap eye-toggle is disabled but rendered as a clickable button

The eye next to "Basemap · Positron" is `disabled` (per the snapshot) and its appearance is grayed. Functionally it can't be toggled (basemap visibility is governed differently). Suggest replacing with a non-button glyph or a tooltip explaining "basemap is always visible; use Remove basemap to hide".

### p-03 — Layer row hover affordance / cursor on the row body

When hovering a layer row, the cursor should clearly indicate it's clickable (selects + opens LayerEditor). Currently the cursor changes only over specific child controls. Click region works but discoverability suffers.

### p-04 — Settings panel persists multi-select bar on top of unrelated context

When ⌘-click multi-select is active and the user opens the global ⚙ Settings panel, the BulkActionBar remains pinned at the bottom of the sidebar showing "2 selected" — but the panel itself doesn't reference the selection. Either dismiss the selection on context switch or visually de-emphasize the bar.

### p-05 — Saved status race between thumbnail PUT and visible status

Two PUTs to `/api/maps/<id>/thumbnail/` (requests 313, 314 — both 204) fire back-to-back on layer add. Minor — but the second one could be coalesced (debounce thumbnail capture by ≥ 500 ms).

### p-06 — "Add data" button glyph is `＋ Add data` (full-width plus) rather than a real icon

Uses the U+FF0B character "＋" mixed with a Lucide icon nearby. Inconsistent typography. Standardize on Lucide `<Plus />`.

---

## What worked well (positive findings)

- ✅ Full Docker cold-rebuild succeeds; all containers healthy in ~30 s
- ✅ Login session persists; admin entry to builder works
- ✅ `Create Map` dialog (Manual + AI Generate tab) renders, validates, and POSTs cleanly (201)
- ✅ Empty-state catalog-first design (per v1008) is intact: "Add your first layer" + search + Browse all
- ✅ LayerEditorPanel flyout (380 px) opens on row click; close affordance works
- ✅ Layer adapters for vector + DEM + Hillshade + Terrain modes wired into one panel
- ✅ Per-row settings (⚙) opens basemap editor with sublayer toggles, opacity, presets
- ✅ Global ⚙ Settings panel shows terrain exaggeration, widget toggles, Mercator/Globe projection
- ✅ Multi-select via ⌘-click does engage selection state ("2 selected" bar appears)
- ✅ Layer DnD handles are in place (`Drag to reorder` aria-labels), basemap drag is correctly suppressed
- ✅ Layer visibility toggle works; map updates immediately on toggle (after first sync)
- ✅ Vector tile requests are signed with HMAC + expiry (`?sig=…&exp=…&scope=…`) — auth posture good
- ✅ Auto-fit-to-bbox on layer add fires correctly (though see B-01 / M-02 — view changes but layer not yet in style)
- ✅ Console error count from app code: **zero** (only the 3 thumbnail 404s)
- ✅ Network: no 5xx errors observed across the whole session
- ✅ No fatal MapLibre runtime errors / no React error-boundary triggers

---

## Reproduction artifacts

Screenshots captured during run (project-root relative):

| Step | File | Notes |
|---|---|---|
| Maps page | `smoke-01-maps-page.png` | List view, 3 existing maps |
| Builder, empty state | `smoke-02-builder-empty.png` | Catalog-first empty layout |
| Add Data modal | `smoke-03-add-data-modal.png` | Type filter chips, 6 datasets |
| After vector layer add | `smoke-04-vector-added.png` | Style editor open, "Pending preview" |
| After DEM layer add | `smoke-05-raster-dem-added.png` | DEM editor with Image/Hillshade/Terrain |
| Editor closed, map view | `smoke-06-no-editor.png` | Basemap only — **no user data** |
| Phase 1002 baseline map | `smoke-07-phase1002-map.png` | World view, layers in style but z=2 |
| After reload of fresh map | `smoke-08-after-reload.png` | Style now has layers (B-01 confirmed) |
| Flown to canyon (after reload) | `smoke-09-flown-to-canyon.png` | DEM raster IS rendering now |
| DEM visibility off | `smoke-10-dem-hidden.png` | 2 blue dots = MULTIPOINT vector renders |
| Vector style editor | `smoke-11-vector-style-editor.png` | Render-as tabs, data-driven section |
| Vector editor re-open | `smoke-12-vector-editor-open.png` | Same |
| Shift-click multi-select attempt | `smoke-13-multiselect.png` | Replace, not extend |
| Shift-click confirmation | `smoke-14-multiselect-real.png` | Only second row selected |
| ⌘-click multi-select | `smoke-15-cmd-multiselect.png` | Both rows; Bulk bar partially visible |
| BulkActionBar overflow | `smoke-16-full-bulkbar.png` | Delete/Group/Ungroup off-screen |
| Global Settings panel | `smoke-17-settings.png` | Terrain / Widgets / Projection |
| Basemap editor | `smoke-18-basemap-editor.png` | Presets + sublayers + master opacity |

All screenshots are at the repo root (`smoke-*.png`).

---

## Recommended next steps (ranked)

1. **Fix B-01** (layer-add → maplibre sync) — blocks the v1009 happy path; without it the builder is unusable for first-time map creation.
2. **Fix B-02** (BulkActionBar clipping) — bulk delete is the headline v1009 feature and it can't be reached.
3. **Fix M-01** (coords readout) — single-line fix likely; large trust win.
4. **Fix M-04** ("Pending style preview" banner false-positive) — actively misleading dirty state.
5. **Fix M-03** (shift-click range select) — completes the multi-select story.
6. **Address m-03 / m-04** (ai-status / auth refresh churn) — performance hygiene.
7. **Backfill quicklooks** for older sample datasets (m-02).
8. **A11y pass** for visibility toggle buttons (m-05) plus surrounding row controls.

---

## Methodology notes

- Smoke check used a real browser (Playwright Chromium), not headless mocks.
- All findings were verified against either (a) live DOM/network inspection, (b) MapLibre style introspection, or (c) the GeoLens server API responses.
- The pre-existing "Phase 1002 Builder Audit Baseline" map served as a control — it loaded with user layers correctly attached to the maplibre style, confirming B-01 is specifically a fresh-add regression rather than a global "layers don't render" bug.
- Only the admin user was tested; viewer / editor non-admin RBAC paths were not exercised.
- No mobile / narrow-viewport pass was done (1440 × 900 desktop only).
- The Docker rebuild preserved data volumes; "from absolute zero" rebuild (`down -v`) was not exercised in this session.
