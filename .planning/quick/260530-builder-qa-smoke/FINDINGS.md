---
slug: builder-qa-smoke
date: 2026-05-30
driver: orchestrator-live-mcp (Playwright MCP)
maps_tested: 4
duration: ~1h
---

# Map Builder QA Smoke — Findings

Thorough live Playwright-MCP QA pass across all 4 current maps. Orchestrator drove all
MCP directly (subagents lack `mcp__playwright__*`). Tested: builder load, map render,
configuration editing, layer editing (raster + vector), the save→reload round-trip,
layer-stack ops, Settings flyout, and console/network health.

## Verdict

Builder is **functionally healthy**. One blocking symptom was found — and traced to a
**stale dev bundle, not a code defect** (resolved by restarting the frontend). Two minor
state-tracking UX gaps were found. All round-trips persist correctly.

---

## F1 — BLOCKER symptom, RESOLVED (environmental, not a code bug)

**Raster colormap/stretch silently reverted to grayscale on reload.**

- Symptom: On the v1034 Raster Stretch QA map, setting Colormap=Viridis + Stretch=Percentile
  applied live and saved correctly to the DB (`style_config.builder = {colormap:"viridis",
  stretch:"percentile"}`, PATCH/PUT both 200). But after reload the map rendered **grayscale**,
  the editor dropdowns showed **Grayscale/Min-Max**, and raster tile requests carried **no
  `colormap`/`rescale` query params**.
- Root cause: The running frontend container started **2026-05-29 15:29**, ~16h *before*
  commit `de9d1f8d` (**2026-05-30 07:51**, "fix(1155): make raster colormap/stretch UI
  reachable + persistent"). That commit added the `style_config.builder` → `_colormap`/
  `_stretch` paint re-hydration block in `normalizeLayerStyleState`
  (`frontend/src/lib/normalize-style-config.ts:327-339`). Vite's file watcher (unreliable
  across macOS Docker bind mounts) never picked up the change, so the live bundle served the
  OLD function:
  ```js
  // running (stale): no re-hydration
  return { style_config: normalizeStyleConfig(...), paint: stripLegacyBuilderPaint(paint) };
  ```
  Confirmed by dynamically importing the live module in-browser and running it against the
  real persisted data → returned `paint: {}` (no `_colormap`).
- Resolution: `docker compose restart frontend`. After restart, the live module has the
  re-hydration block and the **full round-trip works**: editor shows Viridis/Percentile and
  the map renders Viridis on a cold reload (verified). The committed code is correct.
- Takeaway: **a 21h-old Vite container can serve a stale bundle.** Live-MCP QA against a
  long-running dev frontend can test code that no longer matches disk. Restart the frontend
  (or verify `normalizeLayerStyleState.toString()` matches disk) before trusting a QA result.

Evidence: `screenshots/qa-01..04`.

---

## F2 — MINOR: Settings widget toggles don't mark the map dirty

- Repro: open Settings (⚙) → toggle **Measure** on. The save-status indicator stays
  **"Saved"**, and **no PUT/PATCH fires**. Persisted `widgets` stays `null`.
- Data is NOT lost on explicit save: pressing **Cmd+S** persists `widgets:
  ['legend','measurement']` correctly (the save handler reads the widget store directly).
- But the dirty flag never sets, so:
  - the user gets no visual cue that a save is needed, and
  - any unsaved-changes navigation guard won't fire for a widget-only change → silent loss
    if the user navigates away without manually saving.
- Root cause: widget toggles go through a separate global store —
  `toggleWidget = useWidgetStore((s) => s.toggle)` (`MapBuilderPage.tsx:331`,
  wired to `SettingsEditorScene` `onToggleWidget`) — which never calls
  `setHasUnsavedChanges(true)`.
- Suggested fix: have the widget toggle (or a MapBuilderPage effect watching
  `activeWidgets`) call `setHasUnsavedChanges(true)` so the indicator + nav-guard track
  widget changes like layer/paint edits already do.

---

## F3 — MINOR / INFO: Projection toggle is runtime-only, no persistence cue

- Switching Mercator→Globe applies live but the save button stays "Saved", and the choice
  **reverts to Mercator on reload** (there is no `projection` field in the map schema).
- This is **by design** — `SettingsEditorScene` labels it "Projection (runtime-only, v1)"
  and the UI shows "Globe projection is experimental." Lower priority than F2 because it's
  intentional and labeled. Same UX gap as F2 (no hint the toggle won't persist), so a future
  fix could either persist projection or add a "not saved" affordance.

Evidence: `screenshots/qa-08`.

---

## PASS — verified working (no issues)

| Area | Result |
|------|--------|
| Raster colormap/stretch set→save→reload (post-restart) | editor + cold-load render both correct ✓ |
| Vector fill-opacity set→save→reload | 0.45→1.0 persisted, restored to 0.45 ✓ |
| Layer visibility toggle | correctly marks dirty ("Unsaved changes") ✓ |
| Save mechanism | PATCH `/layers` + PUT `/maps` both 200, **no 422s** ✓ |
| 3D / terrain map (9 layers) | renders tilted relief + aerial drape + labels, 0 console errors ✓ |
| Marketing map (5 layers: raster+vector+DEM) | renders correctly, 0 errors ✓ |
| Empty map (0 layers) | catalog-first empty state correct, 0 errors ✓ |
| Settings flyout | appearance / terrain / widgets / projection sections all present ✓ |
| Raster editor controls | brightness/contrast/sat/hue/fade/opacity/resampling/colormap/stretch all live ✓ |
| Vector fill editor | data-driven mode, color, opacity, outline, fill-pattern, zoom range ✓ |

---

## F4 — BUG (latent, found while fixing F3), FIXED

**Saving a map after dragging the basemap above data → 422 (silent save failure).**

- While wiring projection persistence I found the backend `BasemapConfig`
  (`extra="forbid"`) was **missing the `basemap_position` field** that the frontend has
  sent wholesale inside `basemap_config` since Phase 1051 (use-builder-save.ts:475-487,
  "round-trips through the wholesale pass-through"). So any save carrying a non-default
  `basemap_position` (i.e. after the user drags the basemap above data — a shipped v1011
  feature) returned **422 `Extra inputs are not permitted`**. Corroborated: no map in the DB
  had ever persisted `basemap_position` (all `null`).
- Fix: added `basemap_position` (+ `projection`) to the backend `BasemapConfig` schema
  (`schemas.py`, jsonb-additive, no migration) with proper enums. Verified: PUT with
  `basemap_position:'top'` now → **200** and round-trips.

---

## Fixes applied (this session)

| Finding | Fix | Verified |
|---------|-----|----------|
| **F2** | `handleToggleWidget` wraps the widget store toggle to call `setHasUnsavedChanges(true)` (`MapBuilderPage.tsx`) | Toggling Measure now shows "Unsaved changes" ✓ |
| **F3** | Projection persists on `basemap_config.projection`: backend field added; `normalizeBasemapConfig` preserves it (`basemap-utils.ts`); `setBasemapProjection` helper + seed-on-load + apply-on-map-ready effects (`MapBuilderPage.tsx`) | Globe → save → reload: map renders globe + Settings shows Globe + DB has `projection:"globe"` ✓ |
| **F4** | Added `basemap_position` + `projection` to backend `BasemapConfig` (`schemas.py`) | PUT `basemap_position:'top'` → 200 (was 422), round-trips ✓ |

Tests: backend `test_maps.py` + 2 new regression tests (non-default round-trip + invalid-enum
reject); `test_maps_style_json.py` expectations updated for additive fields; frontend
`BuilderMap.unit.test.ts` projection-preservation case. Frontend typecheck 0; vitest
1473/1473; backend maps suites green; ruff + eslint clean. OpenAPI snapshot regenerated.

---

## Note (not a finding)

JWT expired mid-session (~1h15m in) → a 401/404 console burst (`/auth/refresh`, `/auth/me`,
`/admin/ai-status` 401s + 404 on the private map). Known long-session behavior; re-login
(admin/admin) resolved it. Not a regression.

## QA-induced state changes

- `98f89306` (v1034 Raster Stretch QA, scratch): now Viridis/Percentile (was Grayscale/Min-Max). Left as-is — it's the QA scratch map.
- `c39be324` (marketing, public): fill-opacity changed then **restored to 0.45**. Clean.
- `75d86487` (test map, scratch): `widgets` now `['legend','measurement']` (was null). Left as-is — scratch map.
