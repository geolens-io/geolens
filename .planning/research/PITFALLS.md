# Pitfalls Research

**Domain:** GeoLens v1034 — raster stretch/colormap completion (multi-band stretch, configurable bounds, single-band fixture)
**Researched:** 2026-05-29
**Confidence:** HIGH (sourced entirely from live codebase inspection of `router.py`, `cog.py`, `RasterEditor.tsx`, `raster-adapter.ts`, `test_raster_colormap_proxy.py`, `test_raster_tiles.py`)

---

## Critical Pitfalls

### Pitfall 1: `_band_stats_cache` keyed on `open_path` only — stale when configurable bounds change

**What goes wrong:**
`_fetch_band_statistics` in `router.py:250` caches on `open_path` alone. Today all stretch runs are hardcoded p2–p98 / ±2σ so there is no per-call variation. Once RASTER-STRETCH-UI-01 adds user-configurable percentile bounds (e.g. p5–p95 instead of p2–p98), the cache will return the p2/p98 slice for every request regardless of what the user set. The rendered tile will appear correct (cached fast) but will silently apply the wrong stretch bounds.

**Why it happens:**
The cache predates configurable bounds. The key was correct when the only variable was "which asset". Adding user control of `pmin`/`pmax` or `sigma` adds a second cache dimension that the current key does not capture.

**How to avoid:**
Change the cache key to `f"{open_path}:pmin={pmin}:pmax={pmax}"` (percentile) or `f"{open_path}:sigma={sigma}"` (stddev) before any configurable-bounds UI lands. The backend endpoint must receive the bounds as query params and pass them through to both the statistics call and the cache key.

Additionally: Titiler's `/cog/statistics` endpoint returns fixed percentile breakpoints (`percentile_2`, `percentile_98`). Configurable bounds may require a different Titiler endpoint call or manual percentile interpolation from the returned histogram. Verify what Titiler's statistics API actually supports for arbitrary percentile requests before wiring the UI. If Titiler returns only p2/p98, configurable bounds require a completely different approach (e.g. `rescale=pmin%,pmax%` Titiler param if it exists, or frontend-side percentile selection from the full stats histogram).

**Warning signs:**
- Changing the percentile slider in the UI has no effect on tile appearance.
- Network tab shows tile URL with `stretch=percentile` but the rescale values in the Titiler URL never change between slider moves.
- `test_stretch_statistics_cached_across_tiles` passes but a new test asserting different rescale values for different bounds values fails.

**Phase to address:**
The configurable-bounds backend phase (whichever phase implements RASTER-STRETCH-UI-01). Must land before or alongside the slider UI. The cache key fix is a one-liner but the audit of what Titiler actually supports may take a spike session — do the spike first.

---

### Pitfall 2: Single-band float32 fixture is auto-classified as DEM candidate — colormap/stretch UI hidden

**What goes wrong:**
`cog.py:85` sets `is_dem_candidate = src.count == 1 and _is_float_dtype(src.dtypes[0])`. Any single-band float32/float64 GeoTIFF ingested through the normal pipeline will have `is_dem=True` written to `raster_assets`. In `raster_tile_proxy` (`router.py:477–480`) the `is_dem` flag causes `render_params = "algorithm=terrainrgb"`, which bypasses all colormap and stretch logic (the `not render_params.startswith("algorithm=")` guard at lines 565 and 578). In `RasterEditor.tsx:186` the colormap section is gated on `layer.band_count === 1`, but the DEM guard is on the backend. If the fixture is ingested as a DEM, the frontend colormap/stretch UI will appear (correct band_count=1) but the backend will silently ignore both params and serve terrainrgb tiles. The acceptance test "verify colormap/stretch UI against the fixture" would appear to pass (HTTP 200, tile returned) but would actually be testing nothing.

**Why it happens:**
The ingest pipeline has no way to distinguish a DEM elevation grid from a single-band float32 optical product (NDVI, SAR coherence, single-band Landsat). The `is_dem_candidate` heuristic is `band_count==1 AND float dtype` — any float single-band file matches. Common redistributable single-band rasters (Copernicus DEM, SRTM, NLCD impervious surface as float) are all float32.

**How to avoid:**
Choose a fixture with integer dtype, NOT float. uint8 and uint16 single-band GeoTIFFs (Landsat QA band, NLCD land cover classification as uint8, ESA WorldCover) pass `is_dem_candidate=False` because `_is_float_dtype("uint8")` returns False. After ingest, immediately verify `SELECT is_dem FROM catalog.raster_assets WHERE dataset_id = '...'` returns `false` before any further testing. Do not proceed to colormap/stretch verification until this check passes.

**Warning signs:**
- `SELECT is_dem FROM catalog.raster_assets WHERE dataset_id = '<fixture-id>'` returns `true`.
- The raster proxy serves tiles with `algorithm=terrainrgb` in the Titiler URL (visible in network tab or backend logs).
- `stretch=percentile` request to `/tiles/raster-proxy/{id}/...` does NOT trigger a `/cog/statistics` call (the DEM guard skips it).
- The colormap select renders in the UI but changing it has no visible effect on the map.

**Phase to address:**
The fixture-selection/seeding phase (TESTDATA-01). This is the primary pre-condition for all subsequent colormap/stretch verification. Must be resolved before the "verify colormap/stretch UI" acceptance criterion can be claimed PASS.

---

### Pitfall 3: Colormap forwarded to multi-band raster, or n_bands left at 1 for multi-band stretch

**What goes wrong:**
Two related bugs, same root surface.

**Bug A — colormap on multi-band:** `buildColormapTileUrl` in `raster-adapter.ts` appends `colormap_name` without checking band count. `RasterEditor.tsx:186` gates the colormap section on `layer.band_count === 1`, but `band_count` on the layer object may be `null` for datasets where `RasterAsset.band_count` was not populated (e.g. VRT or legacy ingest). If `layer.band_count` is `null`, `null === 1` is false, so the colormap section is hidden — safe. But if a multi-band dataset has `band_count` incorrectly stored as `1`, the UI shows the colormap control and Titiler receives `colormap_name=viridis` on a 3-band RGB raster — Titiler returns a 500.

**Bug B — n_bands=1 hardcoded:** `router.py:581` passes `n_bands=1` to `_compute_stretch_rescale`. This is currently correct (single-band scope per the comment at line 229). When RASTER-STRETCH-03 (multi-band stretch) is added, this call site must be updated to `n_bands=min(row["band_count"] or 1, 3)` to match `_titiler_render_params`'s own logic. If forgotten, multi-band stretch silently applies only b1's rescale to all three displayed bands, producing wrong colors with no error.

**Why it happens:**
The `n_bands=1` constant is a placeholder that documents its own future-work scope via a comment, but a reader implementing RASTER-STRETCH-03 must find and update this specific line. There is no compile-time guard. Bug A is a VRT data-quality edge case.

**How to avoid:**
- Backend-level colormap guard: if `colormap_name` is present AND `band_count > 1`, return HTTP 422 immediately (before forwarding to Titiler). Belt-and-suspenders against `null` band_count edge cases.
- RASTER-STRETCH-03 implementation plan must explicitly list updating `router.py:581` from `n_bands=1` to `n_bands=min(row["band_count"] or 1, 3)` as a named deliverable. Add a unit test that verifies 3 `rescale=` fragments in the Titiler URL for a 3-band stretch.

**Warning signs:**
- Titiler returns 500 on tile requests where `colormap_name` is set.
- For multi-band stretch: the b2/b3 tile bands appear stretched identically to b1 despite having different value ranges.
- Backend logs show `colormap_name=viridis` in a Titiler URL that also has `bidx=1&bidx=2&bidx=3`.

**Phase to address:**
- Colormap-on-multiband guard: the backend validation phase or the first phase touching `raster_tile_proxy` param handling.
- n_bands call-site fix: the RASTER-STRETCH-03 implementation phase. Must be a named deliverable, not an implicit assumption.

---

### Pitfall 4: Per-band statistics fetched N times instead of once — tail latency on first tile

**What goes wrong:**
Today `_fetch_band_statistics` makes one `/cog/statistics` call and returns all bands in a single response. For RASTER-STRETCH-03, if the implementation fires one statistics call per band (`/cog/statistics?url=...&bidx=1`, then `&bidx=2`, then `&bidx=3` sequentially), the first tile request for a 3-band dataset blocks for 3× the Titiler statistics latency (often 500ms–2s on cold COG). Users see a delayed first tile load that looks like a broken raster.

**Why it happens:**
A natural implementation loops over bands and fetches stats individually. The Titiler `/cog/statistics` endpoint returns ALL bands in one response with no `bidx` filter needed — the current code already correctly fetches one-shot and orders bands by numeric suffix (`router.py:259–265`). The pitfall is a regression where RASTER-STRETCH-03 adds a per-band loop instead of reusing the existing one-shot fetch.

**How to avoid:**
Keep the one `_fetch_band_statistics(open_path)` call for all multi-band stretches. Pass `n_bands=min(band_count, 3)` to `_compute_stretch_rescale`. The existing function already returns a list ordered b1, b2, b3 — no per-band loop is needed. The RASTER-STRETCH-03 plan should cite `router.py:244` as the reuse point explicitly.

**Warning signs:**
- Backend logs show 3 sequential `/cog/statistics` requests for the same open_path on a 3-band dataset.
- First tile load time is 3× longer than a single-band asset.
- `_band_stats_cache` is not hit on the second and third band calls because each uses a per-band key instead of the shared open_path key.

**Phase to address:**
RASTER-STRETCH-03 implementation phase. Include a unit test asserting `_titiler_client.get` is called exactly once for a 3-band stretch request (mirrors the existing `test_stretch_statistics_cached_across_tiles` pattern).

---

### Pitfall 5: `bidx` ordering off-by-one — wrong color channel mapping in multi-band stretch

**What goes wrong:**
Titiler expects 1-indexed band selectors (`bidx=1`, `bidx=2`, `bidx=3`). `_compute_stretch_rescale` indexes `bands[i]` for `i in range(n_bands)` (0-indexed). The ordering invariant is: `bands[0]` = b1 stats, `bands[1]` = b2 stats, etc. This works because `_fetch_band_statistics` sorts by `int(k[1:])` (the numeric suffix of `"b1"`, `"b2"`). The risk is that a Titiler version change or a different stat key format (e.g. `"band_1"` instead of `"b1"`, or named bands like `"coastal_aerosol"`) silently scrambles the band→rescale mapping, causing red-channel rescale applied to blue band.

**Why it happens:**
The `k[1:]` parsing in `router.py:263` is brittle: it assumes the key format is always exactly `"b" + integer`. If Titiler adds descriptive band keys or changes its response format, the sort breaks and bands are ordered arbitrarily.

**How to avoid:**
Add a defensive log or assertion after sorting: verify that the first key was `"b1"` and the last was `"b{n}"`. At minimum, a unit test should verify that a 3-band response with keys provided out of order (`"b3"`, `"b1"`, `"b2"`) is sorted correctly. The existing test suite tests only single-band — add a 3-band variant for RASTER-STRETCH-03.

**Warning signs:**
- Multi-band raster renders with swapped colors (red and blue channels visually inverted).
- Titiler stats response format changes in Titiler release notes.
- `int(k[1:])` raises a `ValueError` for any non-numeric suffix key (e.g. `"b1_extra"`).

**Phase to address:**
RASTER-STRETCH-03 implementation phase. Must include a 3-band round-trip test that checks which `rescale=` fragment appears for each band in the Titiler tile URL.

---

### Pitfall 6: Fixture fails COG compliance or lacks overviews

**What goes wrong:**
The ingest pipeline's `check_cog_compliance()` runs at commit time but returns a warning, not a hard block, on compliance failure. A fixture that is a plain GeoTIFF (not a Cloud-Optimized GeoTIFF with blocking/tiling and overviews) will ingest successfully but Titiler may produce degraded tiles or do full-resolution reads at every zoom level. Without overviews, Titiler reads the full pixel grid even at low zoom — any fixture larger than a few hundred pixels will cause slow tile loads or Titiler memory pressure in CI.

**Why it happens:**
Creating a real COG with correct block size, DEFLATE compression, and overview levels requires intentional GDAL steps (`gdal_translate -co TILED=YES -co COMPRESS=DEFLATE` + `gdaladdo`). A minimal test fixture created with plain `rasterio.open(..., 'w')` is not a COG.

**How to avoid:**
Generate the fixture using the GeoLens COG creation pipeline itself (i.e. let the ingest worker convert it) so `check_cog_compliance()` returns `(True, "")`. Alternatively, create the fixture manually with the correct COG profile and verify with `gdalinfo`/`check_cog_compliance()` before committing. For a tiny fixture (<256×256 pixels), overview levels are empty by design which is acceptable — document this explicitly.

**Warning signs:**
- `check_cog_compliance(fixture_path)` returns `(False, reason)`.
- `gdalinfo` output on the fixture does not show `Overview: N levels` when the fixture is larger than 256×256.
- Titiler returns unexpected tile content (e.g. all-nodata tiles) at low zoom levels.

**Phase to address:**
TESTDATA-01 fixture phase. Add `check_cog_compliance(fixture_path)` as an explicit test assertion.

---

### Pitfall 7: Seed script downloads fixture at CI time — flaky CI

**What goes wrong:**
If the seed script downloads the test fixture from an external URL (USGS, NASA EarthData, etc.) at CI time, the test run is dependent on external network availability. CI seed steps regularly fail or timeout on transient connectivity issues, especially with government data servers. The `seed-natural-earth.py` pattern uses HTTP downloads, but the seed is run manually before CI, not during CI. A new fixture that is downloaded ON DEMAND during the test suite itself breaks deterministic CI.

**Why it happens:**
Downloading during tests is convenient for large files. The distinction between "seed runs before tests" (existing pattern) and "fixture download happens during test execution" is easy to miss.

**How to avoid:**
Either (a) commit the fixture directly to the repo if it is small enough (< 1 MB for a representative single-band COG is practical), or (b) use the existing seed script pattern where the fixture download is a separate pre-CI step with retry logic and idempotency. Never fetch the fixture inside a pytest test or conftest. If the fixture must be downloaded, add `@pytest.mark.skip_if_no_fixture` or equivalent guard so tests requiring it are skipped cleanly when the fixture is absent rather than failing noisily.

**Warning signs:**
- A conftest or test function contains an HTTP fetch for the fixture path.
- CI failures on the fixture test are intermittent (not reproducible locally with cached fixture).

**Phase to address:**
TESTDATA-01 fixture phase. The fixture acquisition strategy (committed vs downloaded) must be decided before the seed script is written.

---

### Pitfall 8: Fixture seed is not idempotent — duplicate datasets on repeated runs

**What goes wrong:**
The existing `seed-natural-earth.py` uses a `BOOTSTRAP_KEY_NAME` idempotency key stored in the DB to skip re-running the seed. A new raster fixture that does not hook into this idempotency mechanism will create a duplicate dataset every time the seed script is run. Duplicate raster datasets with the same asset path will cause `_band_stats_cache` to serve stats from the first ingest indefinitely, and the test that "verifies colormap UI against the fixture" may hit the wrong dataset ID.

**How to avoid:**
Use a deterministic `source_filename` or a separate fixture-specific bootstrap key. The seed script must check if a dataset with the given `source_filename` already exists before uploading. Mirror the `idempotency map (source_filename -> dataset_id)` pattern already in `seed-natural-earth.py:1088`.

**Warning signs:**
- Running the seed twice creates two datasets in the catalog with the same name.
- The fixture dataset ID changes between runs, breaking hardcoded test references.

**Phase to address:**
TESTDATA-01 fixture phase. Run the seed script twice in CI and assert dataset count is unchanged.

---

### Pitfall 9: Fixture redistribution license is not verified

**What goes wrong:**
Using a fixture from a source with restrictive terms (e.g. NASA EarthData datasets that require registration, Copernicus data that requires attribution, commercial aerial imagery) exposes the project to license violations if the fixture is committed to a public repo. The error is not technical — CI and tests pass — but the licensing issue can force a fixture swap mid-milestone.

**Why it happens:**
Agency-level licenses are assumed to be "open" when they are often "open for non-commercial research with attribution." USGS National Map, ESA WorldCover, and Copernicus DEM all have different license terms that require verification at the dataset level, not just the agency level.

**How to avoid:**
Choose a fixture that is explicitly CC0 / public domain / USGS public domain. Candidates: USGS 3DEP (public domain BUT float32 — use with integer band), ESA WorldCover (CC BY 4.0 — attribution required, check if acceptable), or generate a synthetic single-band uint8 COG programmatically using rasterio (no license issues). Document the license in a `FIXTURE-LICENSE.md` or inline comment near the fixture download URL.

**Warning signs:**
- Fixture source URL is behind a login wall or has "non-commercial use only" in the terms.
- The fixture was downloaded without checking the dataset-level (not agency-level) license.

**Phase to address:**
TESTDATA-01 fixture phase. License must be confirmed before the fixture URL is committed.

---

## Technical Debt Patterns

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|-----------------|
| Hardcode `n_bands=1` at stretch call site (router.py:581) | Single-band stretch ships faster | Must be found and updated for RASTER-STRETCH-03; no compile-time guard | Never — add a comment referencing the future multi-band phase explicitly |
| Cache `_band_stats_cache` on `open_path` only | Simple implementation | Stale cache when configurable bounds land (RASTER-STRETCH-UI-01) | Never past RASTER-STRETCH-UI-01 |
| Use a DEM float32 COG as the single-band test fixture | Convenient (ADK scripts already fetch one) | `is_dem=True` on ingest → colormap/stretch backend guards skip → test verifies nothing | Never |
| Skip overview generation in the test fixture COG | Faster to create | Titiler may do full-resolution reads; slow tiles in CI | Only if fixture is <256×256 pixels (overview levels empty by design) |
| Negative-cache `None` in `_band_stats_cache` on Titiler timeout | Prevents Titiler spam | Stats permanently wrong for a restarted/fixed asset until service restart | Acceptable — process-lifetime cache clears on restart (already the documented behavior) |
| Download fixture from external URL at CI test time | No committed binary | Intermittent CI failures on network issues | Never — download in seed script, not in test suite |

---

## Integration Gotchas

| Integration | Common Mistake | Correct Approach |
|-------------|----------------|------------------|
| Titiler `/cog/statistics` | Assume it accepts arbitrary `pmin`/`pmax` percentile params | Verify: Titiler returns `percentile_2` and `percentile_98` only by default. Configurable bounds require a Titiler API audit before wiring. |
| Titiler colormap on multi-band | Forward `colormap_name` for any raster | Gate on `band_count == 1`; add backend 422 if colormap + `band_count > 1` |
| Rasterio COG creation for fixture | Create a plain GeoTIFF with `rasterio.open(..., 'w')` | Must use COG profile (tiled, DEFLATE, overviews) so `check_cog_compliance()` passes |
| `_band_stats_cache` in tests | Forget to clear between tests sharing the same `open_path` mock | Use the `_clear_stats_cache` autouse fixture from `test_raster_colormap_proxy.py` — all new stretch tests MUST use it |
| Titiler tile-URL `p=` param | Use `p=2&p=98` on the tile URL for dynamic rescaling | Titiler tile endpoint does not support `p=` for dynamic percentile rescaling; statistics must be fetched separately from `/cog/statistics` and fed as explicit `rescale=lo,hi` |
| DEM guard bypass check | Check only frontend `band_count === 1` gate | Also verify backend `is_dem` column via direct DB check; frontend and backend guards are independent |

---

## Performance Traps

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|----------------|
| Per-tile statistics re-fetch (cache miss every request) | Every tile request takes 500ms+ extra; `/cog/statistics` in every tile network request | Verify `_band_stats_cache` is keyed correctly and not cleared between tiles | Invisible during testing due to cache; breaks on cold start |
| Per-band sequential statistics fetch (N HTTP calls for N bands) | First tile blocked for N × latency | Reuse single `_fetch_band_statistics` call; pass `n_bands` to `_compute_stretch_rescale` | Breaks on first 3-band uncached request |
| `/cog/statistics` cold-start on large COG without overviews | First tile after deploy takes 5–15s | Fixture COG must have valid overview levels | Always on any large non-overviewed COG |
| Configurable-bounds slider fires stats recompute on every tick | Cache miss per tick when bounds key changes | Front-end debounce (use `coalesceFrame` pattern); only send bounds on slider release | On every rapid slider drag |

---

## Security Mistakes

| Mistake | Risk | Prevention |
|---------|------|------------|
| Accepting `pmin`/`pmax` without range validation | `pmin=−∞` or `pmax=NaN` propagates into `rescale=`, causing NaN in Titiler URL or silent fallback | Validate: `0 < pmin < pmax < 100` for percentile; `sigma > 0` for stddev; return 422 on invalid |
| Accepting unbounded `sigma` | Very large sigma (e.g. `sigma=100`) computes rescale beyond dtype max — not a crash but semantically wrong | Validate: `0 < sigma <= 10` (or whatever UX max is) |
| Multi-band `bidx` params assembled by frontend | SSRF-adjacent if frontend constructs raw Titiler params | All Titiler URL construction stays server-side; frontend sends only `stretch`, `pmin`, `pmax`, `sigma` |

---

## UX Pitfalls

| Pitfall | User Impact | Better Approach |
|---------|-------------|-----------------|
| Configurable-bounds sliders update tile URL on every frame | Map flickers; backend stat cache miss on every tick if bounds key changes | Use `coalesceFrame` (already in `RasterEditor.tsx` for paint sliders) for `onValueChange`; only apply on slider release |
| Stretch dropdown visible for multi-band rasters before RASTER-STRETCH-03 | User selects percentile, sees no change (only b1 rescaled), confused | Keep stretch dropdown hidden when `band_count > 1` until RASTER-STRETCH-03 is complete — or show disabled with tooltip |
| Colormap section absent when `band_count` is null | User sees no colormap control and does not know why | Show disabled colormap section with tooltip "Band information unavailable" so the user knows the feature exists |

---

## "Looks Done But Isn't" Checklist

- [ ] **TESTDATA-01 fixture — not a DEM:** `SELECT is_dem FROM catalog.raster_assets WHERE dataset_id = '<fixture-id>'` returns `false`. A green UI smoke test alone does not prove colormap/stretch is exercised — the DEM guard silently bypasses it.
- [ ] **Multi-band stretch n_bands call site:** `router.py:581` passes `n_bands=min(band_count, 3)`, not `n_bands=1`. The constant `1` is a silent correctness bug that does not crash.
- [ ] **Cache key with configurable bounds:** If RASTER-STRETCH-UI-01 is in scope, the cache key in `_fetch_band_statistics` includes the bound params. A cache hit test alone will not catch a missing cache dimension.
- [ ] **Fixture COG validity:** `check_cog_compliance(fixture_path)` returns `(True, "")`.
- [ ] **Fixture has overviews (if >256×256):** `gdalinfo` shows `Overview: N levels` on the fixture.
- [ ] **Seed idempotency:** Seed script run twice leaves dataset count unchanged.
- [ ] **Fixture redistribution license:** Explicitly verified at dataset level (not just agency level), CC0 / public domain or equivalent.
- [ ] **Statistics call count for multi-band:** Unit test asserts `_titiler_client.get` called once for a 3-band stretch request (not N times).
- [ ] **Colormap NOT forwarded to multi-band:** Backend 422 test when `colormap_name` present AND `band_count > 1`.
- [ ] **DEM — colormap NOT forwarded:** Existing `test_dem_render_params_colormap_not_appended` still passes after any proxy changes.

---

## Recovery Strategies

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|----------------|
| Cache key missing bounds — wrong stretch shown | LOW | Clear `_band_stats_cache` (process restart) + deploy corrected key; no DB migration |
| Fixture ingested as DEM (`is_dem=True`) | LOW | `UPDATE catalog.raster_assets SET is_dem = false WHERE dataset_id = '<id>';` + re-verify via Playwright MCP; or re-ingest with non-float dtype fixture |
| n_bands=1 bug in multi-band stretch | MEDIUM | Backend fix + redeploy; no migration; existing single-band datasets unaffected |
| Fixture fails COG compliance | MEDIUM | Re-generate fixture with proper COG profile (`gdal_translate -co TILED=YES -co COMPRESS=DEFLATE -co COPY_SRC_OVERVIEWS=YES`); re-ingest; update seed script |
| Seed double-imports duplicate datasets | LOW | `DELETE FROM catalog.records WHERE id IN (SELECT r.id FROM catalog.records r JOIN catalog.datasets d ON d.record_id = r.id WHERE d.source_filename = '<fixture>')` (keep the first); fix seed idempotency |
| Fixture license problem | MEDIUM | Swap fixture for a CC0 source; re-ingest; update seed script and license docs |

---

## Pitfall-to-Phase Mapping

| Pitfall | Prevention Phase | Verification |
|---------|------------------|--------------|
| Cache key missing bounds (Pitfall 1) | RASTER-STRETCH-UI-01 backend phase | Unit test: two requests with different `pmin`/`pmax` produce different cache keys and different rescale values in Titiler URL |
| Fixture misclassified as DEM (Pitfall 2) | TESTDATA-01 fixture phase | `SELECT is_dem FROM catalog.raster_assets WHERE dataset_id = '<id>'` returns `false`; Playwright MCP confirms colormap select changes tile appearance |
| Colormap on multi-band / n_bands=1 (Pitfall 3) | RASTER-STRETCH-03 or earlier backend guard phase | Backend 422 test for colormap+multiband; unit test for 3 `rescale=` fragments in 3-band tile URL |
| N per-band stats calls (Pitfall 4) | RASTER-STRETCH-03 | Unit test: `_titiler_client.get` called once for 3-band stretch |
| bidx ordering off-by-one (Pitfall 5) | RASTER-STRETCH-03 | Unit test: out-of-order 3-band stats response sorted correctly; integration test checks rescale per band slot |
| Fixture not a valid COG / no overviews (Pitfall 6) | TESTDATA-01 fixture phase | `check_cog_compliance(fixture_path)` returns `(True, "")`; `gdalinfo` shows overviews |
| Seed flakiness via CI-time download (Pitfall 7) | TESTDATA-01 fixture phase | No HTTP fetch inside pytest or conftest for the fixture |
| Seed not idempotent / duplicate datasets (Pitfall 8) | TESTDATA-01 fixture phase | Run seed twice; assert dataset count unchanged |
| Fixture license not verified (Pitfall 9) | TESTDATA-01 fixture phase | License source cited in seed script comment or FIXTURE-LICENSE.md |

---

## Sources

- Live code inspection: `backend/app/processing/tiles/router.py` — DEM guard at :477–480, stretch call site at :578–584 and :581 (`n_bands=1`), cache at :241–269, n_bands logic in `_titiler_render_params` at :195–212, `_compute_stretch_rescale` at :272–306
- Live code inspection: `backend/app/processing/raster/cog.py:85` — `is_dem_candidate = src.count == 1 and _is_float_dtype(src.dtypes[0])` heuristic; `_FLOAT_DTYPES` at line 11
- Live code inspection: `backend/tests/test_raster_colormap_proxy.py` — existing test patterns to extend for multi-band
- Live code inspection: `backend/tests/test_raster_tiles.py` — `_create_raster_dataset` helper pattern; `_band_stats_cache` unit tests
- Live code inspection: `frontend/src/components/builder/LayerStyleEditor/RasterEditor.tsx:186` — colormap section gate on `layer.band_count === 1`
- Live code inspection: `frontend/src/components/builder/layer-adapters/raster-adapter.ts:55–73` — `buildColormapTileUrl` with no multi-band guard
- Live code inspection: `backend/app/processing/raster/models.py:72` — `is_dem` field on `RasterAsset`
- PROJECT.md v1033/v1032/v1031 milestone notes — stretch architecture, DEM guard history, cache bounds decisions
- Milestone context: `_band_stats_cache` keyed on path only today; DEM algorithm guard; colormap single-band-only by design; RASTER-STRETCH-03 deferred from v1033

---
*Pitfalls research for: GeoLens v1034 raster stretch/colormap completion — multi-band per-band stretch, configurable bounds, single-band raster test fixture*
*Researched: 2026-05-29*
