# Quick Task 260524-o57 — GeoLens Dogfooding Findings

**Source:** Marketing-data ingest + map composition for ADK High Peaks AOI
**Map:** `c39be324-6815-40e5-8143-00a2723827b2`
**Date:** 2026-05-24

## 1. Endpoints Touched

| Endpoint | Calls | Notes |
|---------|-------|-------|
| `GET /api/health` | 1 | OK |
| `POST /api/auth/login` | 1+ | Form-encoded, rate-limited 5/min |
| `POST /api/auth/api-keys/` | 1 | Returns short-lived random token |
| `DELETE /api/auth/api-keys/{id}` | 1 | Requires re-login (JWT, not API key) |
| `GET /api/datasets/` | 1+ | Idempotency probe by `source_filename` |
| `GET /api/datasets/{id}` | 8+ | Per-dataset detail probe |
| `POST /api/ingest/upload` | 6 | Multipart file upload, 5xx for >500MB |
| `GET /api/ingest/jobs/{id}` | many | Polling, 0.5s intervals |
| `POST /api/maps/` | 1 | Map create with `terrain_config={enabled:false}` |
| `PATCH /api/maps/{id}/layers` | 1+ | Add 6 layers in one PATCH |
| `PUT /api/maps/{id}` | 1 | Reset `terrain_config` after frontend overwrote it |
| `GET /api/maps/{id}` | 3+ | Verify map state |
| `GET /tiles/raster-proxy/{id}/{z}/{x}/{y}.png` | many (browser) | DEM tiles for terrain |

## 2. Auth Friction

### `POST /api/auth/login` — form-encoded body required
The endpoint accepts only `application/x-www-form-urlencoded` (`username=admin&password=admin`), NOT JSON. The OpenAPI snapshot shows this correctly via the `OAuth2PasswordRequestForm` schema, but neither `/docs` nor the auto-generated examples mention that JSON is rejected — typical FastAPI consumers will try JSON first and get a 422 with an opaque error.

**Recommendation:** Add a docstring example showing `curl -d "username=...&password=..." -H "Content-Type: application/x-www-form-urlencoded"`. Optionally: accept JSON OR form with explicit Content-Type dispatch.

### `DELETE /api/auth/api-keys/{id}` requires JWT, not API key
A script that bootstrapped an API key for itself cannot use that key to delete itself. It must re-login with username+password (and burn another rate-limit quota slot). This is a chicken-and-egg cleanup problem.

**Recommendation:** Allow API-key self-deletion via the same API key, OR document the re-login dance clearly in the auth.md guide.

### Rate-limit on `POST /api/auth/login` (5/min)
Burning login attempts during debugging is easy. The 429 response carries no `Retry-After` header — the script has to manually wait 60s.

**Recommendation:** Set `Retry-After` on 429, OR exempt loopback / authenticated re-auth (where the caller already proved valid JWT).

## 3. Ingest Friction

### `POST /api/ingest/upload` returns 201 OR 202 inconsistently
Direct curl tests return 201 (Created). Some runs through httpx returned 202 (Accepted). The script's status-code check was originally `if resp.status_code != 200` — which rejected BOTH 201 and 202 as "failed".

**Recommendation:** Pick ONE return code and pin it. If the choice depends on whether the worker has picked up the job (synchronous vs queued), document that — but realistically `201` is always correct since the upload itself succeeded.

### `RequestBodyLimitMiddleware` reads `UPLOAD_MAX_SIZE_MB` ONLY at startup
The persistent config in DB (`catalog.app_settings.upload_max_size_mb`) can be updated via `PUT /settings/`, BUT the middleware (`backend/app/api/main.py:524-525`) reads the env-var-derived `settings.upload_max_size_mb` at app boot. So:
- Increasing the limit via `PUT /settings/` → 413 still fires from middleware → upload rejected
- The only way to actually raise the limit is to set `UPLOAD_MAX_SIZE_MB` in `.env` AND `docker compose up -d api` (NOT `restart`, which reuses old env)

**Recommendation:** Either (a) sync the middleware to read the persistent config on each request (perf cost is negligible since it's an in-memory cached value), or (b) remove the persistent config and rely only on the env var (since it's pretend-configurable today).

### `docker compose restart` does not pick up `.env` changes
This caught us twice. `docker compose restart api` ran the SAME container with the SAME env. Only `docker compose up -d api` actually re-reads `.env`.

**Recommendation:** Add a note to `docs/docker-compose-architecture.md` explaining when to use `restart` vs `up -d`.

### 1.3 GB DEM upload write-timeout
`httpx.Timeout(600.0, connect=30.0)` resolves to `write=600`. For a 1.3 GB upload over local-loopback at ~50 MB/s, that's `1300/50 = 26s` — fine — but with bursty pauses or compose-proxy buffering, occasional bursts can extend writes past the 600s budget. Worse, the proxy at port 8080 was dropping large-body connections entirely.

**Recommendation:** The upload-client recipe should be `httpx.Timeout(connect=30, write=None, read=600, pool=30)` for large bodies. Document this in any "uploading large files" guide.

### Vite proxy at port 8080 drops large-body connections silently
For uploads > ~500 MB, the Vite dev proxy at `localhost:8080` closes the connection mid-stream with `httpx.ReadError`. There's no 413 response, no log message — just a disconnect. The script had to switch to the direct FastAPI port 8001.

**Recommendation:** Document this limitation in `frontend/README.md` or the Vite proxy config. Long-term, add a Vite proxy config flag to bump the body-size limit.

### Upload endpoint doesn't auto-process the upload after success
After `POST /api/ingest/upload` returns 201, a `POST /api/ingest/preview/` and `POST /api/ingest/commit/` are required to actually run the GDAL conversion + register the dataset. BUT in our session, the Procrastinate worker auto-processed our uploads through some other path (jobs were created and ran the COG conversion without explicit preview/commit calls). The mechanism is unclear and resulted in duplicate datasets when our script retried.

**Recommendation:** Document the upload → preview → commit lifecycle clearly. If there's a fast-path that auto-processes, name it. Otherwise, surface the auto-processing as a 422 / 409 with "Dataset already being processed" rather than silently creating duplicates.

## 4. Map Composition Friction

### Issue 6 — Builder UI cannot reorder vectors above rasters (CRITICAL)

**Repro steps:**
1. Create a map containing 1+ raster layers and 1+ vector layers (e.g., this map: `c39be324-6815-40e5-8143-00a2723827b2`).
2. Open the map in the builder at `http://localhost:8080/maps/{id}`.
3. In the layer stack panel (right side), attempt to drag a vector layer above a raster layer.
4. Observe: the visual layer order in the MapLibre canvas does NOT update. The drag may appear to succeed in the panel, but the underlying map keeps the old stacking.

**Diagnosis:**
The frontend's drag handler (`MapBuilderPage.tsx:640-754` `handleDragEnd` + `use-builder-layers.ts:257 handleReorder`) does NOT type-check or restrict by `layer_type`. The dnd-kit `useSortable` configuration in `UnifiedStackPanel.tsx:185, 292, 393` is unconditional — every layer (vector OR raster) is both draggable AND droppable. **There is no hard block at the dnd-kit level.**

However, the API state and the MapLibre visual state can diverge:
- The API was updated with the new sort_order via `PATCH /api/maps/{id}/layers`.
- The MapLibre stack should be reordered by `reorderDataLayers(map, reorderedLayers)` in `handleReorder` (`use-builder-layers.ts:263`).
- The MapLibre reorder is invoked, but `reorderDataGeometry` in `map-sync.ts:866-885` uses `prefixed('layer', layers[i].id, idPrefix)` to look up layer IDs. **If the raster layer's MapLibre layer-id format differs from the vector layer's format**, or if either's `getLayer()` lookup returns `undefined`, the `moveLayer` call silently no-ops.

**WORKAROUND** (verified during this dogfooding session): Bypass the builder UI and use the API directly:
```bash
JWT="..."
curl -X PATCH "http://localhost:8001/api/maps/{id}/layers" \
  -H "Authorization: Bearer $JWT" -H "Content-Type: application/json" \
  -d '{"added":[],"updated":[],"removed":[],"order":["<aerial_id>","<dem_id>","<vec1>","<vec2>"]}'
```
After this PATCH, refresh the browser and the layers render in the requested order.

**Recommendation:**
- Audit `reorderDataGeometry` in `map-sync.ts` — confirm raster layer-ids follow the same `layer-<id>` pattern that vectors use.
- Add an integration test: "a vector layer dragged above a raster layer renders above it on the map canvas (not just the panel)".
- Consider adding an explicit `map.moveLayer(rasterLayerId, beforeLayerId)` re-anchor when raster layers are reordered, since `setStyle` re-anchors all layers but `moveLayer` only moves one.

### Issue 2 — `terrain_config={enabled: false}` is not preserved (MEDIUM)

**Repro steps:**
1. `POST /api/maps/` with body:
   ```json
   {
     "name": "Test",
     "description": "Test",
     "terrain_config": {"enabled": false}
   }
   ```
2. `GET /api/maps/{id}` immediately after — verify `terrain_config = {"enabled": false, "source_dataset_id": null, "exaggeration": 1.0}` ✓.
3. `PATCH /api/maps/{id}/layers` adding a layer with `is_dem=true` (a DEM raster).
4. Open `http://localhost:8080/maps/{id}` in the builder.
5. Wait ~5-10 seconds for the builder to settle.
6. `GET /api/maps/{id}` again — observe `terrain_config = {"enabled": true, "source_dataset_id": "<dem_id>", "exaggeration": 1.9}`.

**Diagnosis:**
The frontend's terrain auto-detect (likely on map load when a DEM layer is detected) silently overwrites the user's `enabled: false` choice. The user's POST intent was "create the map with terrain disabled" — the frontend essentially says "but you have a DEM, let me enable terrain for you" without surfacing the change or asking.

The "Updated_at" timestamp (`22:45:12`) was 8 minutes after create (`22:36:47`), aligning with the user opening the map at ~22:45.

**Recommendation:**
- Honor an explicit `terrain_config.enabled: false` — never auto-enable when the API was explicitly told to disable.
- Optionally: surface auto-detect via a toast "Detected a DEM layer — enable terrain?" with an explicit user click.
- Document the auto-detect behavior in the API docs so script authors don't get confused.

### Issue 3 — DEM dimension mismatch (HIGH)

**Verbatim browser console errors:**
```
installHook.js:1 Uncaught Error: cannot load terrain, because there exists no source with ID: dem-2931c262-0e86-4e23-b14d-55763854e004
    at onExaggerationChange (MapBuilderPage.tsx:968:40)
    at onValueChange (SettingsEditorScene.tsx:69:33)

installHook.js:1 cannot calculate elevation if elevation maxzoom > source.maxzoom

(54×) maplibre-gl.js?v=faa6bdd4:33024 Uncaught Error: cannot load terrain, because there exists no source with ID: dem-2931c262-0e86-4e23-b14d-55763854e004

installHook.js:1 Error: dem dimension mismatch
installHook.js:1 [BuilderMap] Map error: Error: dem dimension mismatch
```

**Repro steps:**
1. Enable terrain on a map with a DEM raster.
2. Open the map in the browser at a zoom level > 16.
3. Observe the console errors above.

**Diagnosis:**

**Root cause: `_build_tile_token_for_dataset` in `backend/app/processing/tiles/router.py:464-472` hardcodes `minzoom=0, maxzoom=18` for ALL raster tile tokens, regardless of the COG's actual overview pyramid.**

The frontend's `ensureRasterDemTerrainSource` in `map-sync.ts:79-124` uses these values to configure the MapLibre `raster-dem` source:
```js
map.addSource(sourceId, {
  type: 'raster-dem',
  tiles: [absoluteTileUrl],
  tileSize: options.tileSize ?? 256,
  minzoom: options.minzoom ?? 0,    // ← from token = 0
  maxzoom: options.maxzoom ?? 18,   // ← from token = 18
  ...
});
```

But the actual DEM (`adk_high_peaks_dem_1m.tif`) has:
- Native resolution: 1.39 m/px → max usable zoom ~16.3 (z=17 is empty for most coords)
- Overview pyramid: levels 2, 4, 8, 16, 32, 64 → minimum usable zoom ~10.3 (z=9 falls outside lowest overview)

At zoom 17/18, MapLibre fetches DEM tiles. The Titiler service computes the tile and finds it's OUTSIDE the COG's bounds → returns 404. The proxy converts that to 204 No Content. MapLibre receives an empty PNG instead of the expected 256×256 RGBA terrain-RGB tile → throws "dem dimension mismatch".

The "elevation maxzoom > source.maxzoom" warning is a separate MapLibre internal check — terrain rendering wants `source.maxzoom >= elevation.maxzoom`, but the elevation system has a default maxzoom of `14`. With our source.maxzoom of 18, this warning fires immediately, BUT the actual rendering fails at zoom 17/18.

The `terrain source missing` errors come from `onExaggerationChange` in `MapBuilderPage.tsx:968` — when the user drags the exaggeration slider in the Settings panel, the handler calls `map.setTerrain({source: 'terrain-dem', exaggeration: N})`. If the source was removed (because the previous setTerrain hit an error path), the next call throws.

**Recommendation:**
1. Compute `maxzoom` from the dataset's native resolution at its bbox's latitude:
   ```python
   maxzoom = int(math.log2(40075016.686 * math.cos(lat * math.pi/180) / 256 / res_x))
   # e.g., 1.39 m/px at lat 44 → maxzoom=16
   ```
2. Compute `minzoom` from the lowest-resolution overview:
   ```python
   # res * 2^len(overviews)
   minzoom = int(math.log2(40075016.686 * math.cos(lat * math.pi/180) / 256 / (res_x * (2 ** len(overviews)))))
   ```
3. Pass these through `RasterTileToken`. The frontend already uses them.
4. Verify with this repro that terrain renders cleanly at the dataset's native max zoom.

### Issue 5 — "Basemap connection issue" toast triggered by terrain error (HIGH)

**Verbatim toast text:**
> Basemap connection issue.
> Your data layers are still editable. Check the basemap service or choose another basemap if the background stays blank.

**Repro steps:**
1. Open any map with terrain enabled (e.g., this map after re-enabling terrain).
2. Wait 3+ seconds (past the SF-08 suppression window).
3. Observe the toast appears at top-left, overlapping the NavigationControl.

**Diagnosis:**
The toast actually triggers because of Issue 3 (DEM dimension mismatch), NOT because of an actual basemap problem. In `BuilderMap.tsx:408-437`, the `errorHandlerRef` filters MapLibre errors by HTTP status:
```js
if (status && status >= 400 && status < 500) return;  // suppress client errors
if (!status || status >= 500) {
  // ... 3-second post-load suppression window ...
  setBasemapNotice('tiles');
  toast.error(t('builderMap.mapError', ...));
}
```

The terrain "dimension mismatch" error has no HTTP status (it's a MapLibre internal error). So `!status` is true → toast fires. The toast text wrongly attributes the problem to the basemap.

**Recommendation:**
- Filter by `error.message` content — terrain-related errors should NOT raise the basemap toast. Possible regex: `if (e.error?.message?.includes('terrain') || e.error?.message?.includes('dem')) return;`.
- OR rename the toast to "Map tile error — some layers may not render correctly" (this is already the actual `mapError` translation, but the heading `basemapIssueTitle` is misleading).
- Long-term: distinguish "basemap network failed" (specific check) from "any non-404 map error" (catch-all).

### Issue 4 — Basemap-error toast overlaps NavigationControl (MEDIUM)

**Repro steps:**
1. Trigger Issue 5 (any non-404 MapLibre error past 3-second window).
2. Observe the toast at top-left corner.
3. Note the NavigationControl (zoom in/out, compass) at the same position.

**Diagnosis:**
Both the toast (`BuilderMap.tsx:961-976`) and the NavigationControl (`BuilderMap.tsx:994`) are anchored to `top-left`. The toast has `absolute left-3 top-3 z-20 max-w-sm` (max 24rem = 384px width). The NavigationControl is positioned via MapLibre's CSS at `position: absolute; top: 10px; left: 10px`. Z-order: toast z-20 > NavigationControl default → toast covers the +/- buttons.

A previous Phase 1051 RESP-02-FOLLOWUP shifted the NavigationControl DOWN to clear the `MapCoordReadout` pill at 800px width, but didn't account for the basemap-error toast.

**Recommendation:**
- Move the toast to `bottom-left` or `top-right` (currently empty).
- OR add collision-detection that pushes the NavigationControl down when the toast is visible (similar to RESP-02-FOLLOWUP's mechanism).
- OR add `pointer-events: none` to the toast text + a smaller dismiss button so the user can interact with controls underneath.

### Issue 1 — Upstream Positron sprite refs broken (LOW)

**Verbatim browser console messages:**
```
Image "road_" could not be loaded.
Image "us-state_" could not be loaded.
```

**Repro steps:**
1. Open any builder map at zoom >= 11.
2. Observe console warnings for road shield icons.

**Diagnosis:**
This is an **upstream openfreemap Positron style bug**, NOT a GeoLens bug. The Positron style at `https://tiles.openfreemap.org/styles/positron` has layers like `road_shield_us`:
```json
{
  "layout": {
    "icon-image": ["concat", ["get", "network"], "_", ["get", "ref_length"]]
  }
}
```

When `ref_length` is null (e.g., for unsigned highways), the expression evaluates to `"us-state_"` or `"road_"` — bare prefixes with no number suffix. The sprite manifest doesn't have these bare entries, so MapLibre emits the "could not be loaded" warning.

**Recommendation:**
- File an upstream issue with openfreemap to add fallback sprites for null `ref_length`.
- Workaround: register a `styleimagemissing` listener that provides empty placeholder images for `road_*` and `us-state_*` patterns.
- This is cosmetic console noise — no visual impact on the map.

## 5. Catalog & Search Friction

- `GET /api/datasets/?search=adk-high-peaks-dem-1m` works fine.
- `GET /api/datasets/?include=mine` returned empty during the dogfooding session even though the API key was valid and the admin user owned the datasets. Switching to JWT (Authorization: Bearer) instead of X-Api-Key worked. Behavior of `include=mine` with API key auth needs documentation.

## 6. Error Message Quality

- The `?include=mine` empty-result-with-API-key case had no error — just silent zero results. Worth a friction note.
- `DELETE /api/datasets/{id}` requires `{"confirm_title": "..."}` body. The 422 error message includes the missing field name, which is helpful. The first-time discovery friction was 1 round-trip.
- `DELETE /api/jobs/{id}` returns `405 Method Not Allowed` — no documentation on how to cancel a job. The orphaned-job state must be manually swept by the operator.
- Login 429: no `Retry-After` header → caller has to guess.

## 7. Documentation Gaps

| Gap | Recommended fix |
|-----|-----------------|
| Login is form-encoded, not JSON | Add `curl` example in `/docs` and `docs/auth.md` |
| Upload endpoint status codes (201 vs 202) | Pin one; document which |
| `RequestBodyLimitMiddleware` vs persistent config | Pick one source of truth; document both if kept |
| Job lifecycle (cancellation, deletion) | Add to `docs/ingest.md` |
| Builder layer-stack drag mechanics (Issue 6) | Add a smoke test ensuring vectors-above-rasters works visually |
| `docker compose restart` vs `up -d` | Add to `docs/docker-compose-architecture.md` |

## 8. Performance Observations

- 1.3 GB DEM upload: ~10s on local loopback at port 8001 (direct FastAPI).
- COG conversion (worker): unclear — process ran async, status went `pending → processing → ready` over ~minutes.
- `GET /api/maps/{id}`: ~25ms with 6 layers.
- `PATCH /api/maps/{id}/layers`: ~15ms (added=6).
- DEM tile fetch (single tile): ~150-200ms first hit (cold cache), ~5-10ms warm.
- Map-builder first paint with 6 layers (2 rasters, 4 vectors): smooth — no FOUC observed.

## 9. Recommended API Improvements (Priority-Ordered)

1. **Compute raster tile token min/max zoom from COG metadata** (fixes Issue 3, ~half-day fix in `backend/app/processing/tiles/router.py:442-472`).
2. **Audit builder layer reorder to ensure raster + vector layers both move on the map canvas** (fixes Issue 6, likely a 1-2 day investigation in `frontend/src/components/builder/map-sync.ts`).
3. **Surface terrain errors as their own toast, not the basemap toast** (fixes Issue 5, ~2-hour fix in `BuilderMap.tsx:408-437`).
4. **Honor `terrain_config.enabled: false` on map open** (fixes Issue 2, ~half-day fix in frontend terrain auto-detect).
5. **Sync `RequestBodyLimitMiddleware` with persistent config OR remove the persistent toggle** (resolves the "raise limit, it still rejects" confusion, ~1 day).
6. **Document upload status code (201 only) + add `Retry-After` to 429** (~couple hours).
7. **Add a smoke test that proves dragging a vector above a raster updates the visual MapLibre stack** (defensive — catches Issue 6 regressions).
8. **Move basemap-error toast away from NavigationControl** (UI tweak, ~half-hour) (fixes Issue 4).
9. **`docker compose restart` vs `up -d` documentation** (~half-hour write-up).
10. **File upstream openfreemap Positron sprite bug** (Issue 1 — cosmetic, low priority).

## Bugs Found (in script — already fixed)

These were caught during the execution and fixed in commit `a9e28110`:

1. **APILogger truncated `api_issues_log.jsonl` on every script init**. Added `append: bool = False` parameter and `--append-log` CLI flag. Otherwise the log loses prior-session friction history (we recovered from a previously-killed run).
2. **`httpx.Timeout(600.0, connect=30.0)` resolves to `write=600`** — fires during streaming of 1.3 GB DEM. Fixed to `httpx.Timeout(connect=30.0, write=None, read=600.0, pool=30.0)`.
3. **Upload status check rejected non-200 codes** — endpoint returns 201/202. Broadened to `if not (200 <= resp.status_code < 300)`.
4. **Default base_url pointed to Vite proxy at port 8080** — large uploads drop. Changed to direct FastAPI at port 8001; added `--browser-url` so URLs in output still point to the user-facing port 8080.
5. **`compose_map()` returned a URL built from base_url** — putting `:8001` in URLs the user clicks. Added a `browser_url` parameter to override.

These bugs are inherent to the SCRIPT (not GeoLens), but the friction they revealed — multi-port deployment, upload-encoding choices, log-rotation defaults — are worth noting because they're failure modes any consumer of the GeoLens API would hit.

## Final Priority Ranking

| # | Issue | Severity | Effort | Fix Layer |
|---|-------|----------|--------|-----------|
| 6 | Builder UI cannot reorder vectors above rasters | CRITICAL | 1-2 day audit | Frontend (`map-sync.ts`) |
| 3 | DEM dimension mismatch (hardcoded maxzoom=18) | HIGH | ~half day | Backend (`tiles/router.py`) |
| 5 | Basemap connection toast triggers on terrain errors | HIGH | ~2 hours | Frontend (`BuilderMap.tsx`) |
| 2 | `terrain_config.enabled=false` is overwritten | MEDIUM | ~half day | Frontend (terrain auto-detect) |
| 4 | Toast position collides with NavigationControl | MEDIUM | ~30 min | Frontend (CSS) |
| 1 | Sprite refs `road_`, `us-state_` | LOW | upstream | Openfreemap |

## Self-Check

- [x] All 6 issues captured with verbatim repro + diagnosis
- [x] Bugs found in script documented
- [x] Cross-referenced to commit `a9e28110` for script fixes
- [x] Cross-referenced to SUMMARY.md for the marketing-data deliverable
