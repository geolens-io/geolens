---
phase: 260508-lkz-rebuild-geolens-demo-themes-and-fixtures
reviewed: 2026-05-08T20:24:51Z
depth: quick
files_reviewed: 13
files_reviewed_list:
  - e2e/demo-smoke-shared.ts
  - scripts/demo/fetch_external.py
  - scripts/demo/fixtures/maps/1-grand-canyon.json
  - scripts/demo/fixtures/maps/1-nyc-zoning.json
  - scripts/demo/fixtures/maps/1-pop-density.json
  - scripts/demo/fixtures/maps/2-earthquakes.json
  - scripts/demo/fixtures/maps/2-wildfires.json
  - scripts/demo/raw/external/.gitignore
  - scripts/demo/raw/external/.gitkeep
  - scripts/demo/run-seeder.sh
  - scripts/demo/themes/theme1.py
  - scripts/demo/themes/theme2.py
  - scripts/demo/themes/theme3.py
findings:
  blocking: 0
  major: 2
  minor: 4
  nit: 2
  total: 8
status: issues_found
---

# Quick Review — 260508-lkz Demo Themes & Fixtures

**Depth:** quick (pattern-match + targeted code-trace)
**Stance:** adversarial
**Confidence threshold:** 80%+

## Summary

Reviewed 13 files. Two MAJOR defects found, both fixture↔runtime contract bugs:

1. The `1-pop-density.json` fixture promises 3D extruded "bars" at zoom 4 but the renderer's `fill-extrusion` companion layer is hard-coded to `minzoom: 14` in `fill-adapter.ts:74` — bars are invisible until you zoom in by ~10 levels.
2. `fetch_external.py` writes outputs in-place (no temp-file + atomic rename), and the idempotency check is `size >= 1024 bytes`, so a SIGKILL'd or network-truncated TIGER zip / JSON write that wrote >1 KB before dying gets treated as "present" on next run, silently locking the seeder into a broken state.

The remaining findings are minor: a wrong type annotation, fixture metadata drift (classCount=5 vs 4 colors), and a cosmetic empty-theme log line. No security vulnerabilities (no shell-injected paths, no SQL/SoQL with user input, no path traversal — all external URLs and AOIs are constants). No SSRF risk.

Out-of-scope items (per task brief): performance, comment density, refactor opportunities.

---

## Major Issues

### MA-01: Pop-density fixture's 3D extrusion is invisible at the configured initial zoom

**File:** `scripts/demo/fixtures/maps/1-pop-density.json:12-14, 41`
**Issue:** The fixture sets `"zoom": 4.0`, `"pitch": 50.0`, advertises `"_height_column": "_density"` in `paint`, and the user-facing name is `"Population Density: 4-State Bars"` — but the fill-adapter's companion `fill-extrusion` layer is hard-coded with `minzoom: 14` (`frontend/src/components/builder/layer-adapters/fill-adapter.ts:74`, asserted by `frontend/src/components/builder/__tests__/layer-adapters.test.ts:789-803`). At zoom 4 the extrusion layer is hidden entirely, so the user lands on a flat choropleth that contradicts both the fixture name and the e2e test description. The same minzoom rule applies in the viewer path because `ViewerMap.tsx:483` routes through the shared `getAdapter('fill')`.

The NYC fixture (zoom 14.5) sits just above this threshold and renders correctly; the pop-density fixture is the only one of the three "Land Speaks" maps affected.

**Fix:** Either (a) set the fixture's initial zoom into a state that's still meaningful at z14+ (e.g. zoom in over LA: `center_lng: -118.2, center_lat: 34.05, zoom: 11.5` — bars start appearing at 14, full at 16); (b) drop `_height_column` from this fixture and rename to "Population Density: 4-State Choropleth" if the 4-state framing is intentional; or (c) coordinate a separate code change to lower the minzoom (out of scope here). Option (a) is the smallest, on-brief fix.

Confidence: 95%. Verified by reading both `ViewerMap.tsx` and `fill-adapter.ts`, plus the existing test that asserts `minzoom === 14`.

---

### MA-02: Idempotency check trusts byte count, not write completion — partial files wedge subsequent runs

**File:** `scripts/demo/fetch_external.py:65-70, 254-256, 357, 399, 476`
**Issue:** `already_present(path, min_bytes=1024)` returns True as long as the file exists and is ≥1 KB. All five fetchers write outputs **directly to the final path**:
- TIGER zip: streamed via `out_zip.open("wb")` + `aiter_bytes` (line 254-256) — a connection drop after the first KB leaves a partial zip that passes `already_present` next run, then crashes the `/vsizip/...` ogr2ogr at line 264-271.
- JSON outputs (`pop_density_tracts.geojson`, `nyc_pluto_zoning.geojson`, `usgs_quakes_m5.geojson`, `nifc_fires_2020_2024.geojson`): all use `out.write_text(json.dumps(...))` (lines 357, 399, 476). A SIGTERM/OOM mid-write yields a truncated but >1 KB JSON that future runs skip; downstream `json.loads(out_tracts.read_text())` (line 333) raises `JSONDecodeError`, which is caught by the broad `except Exception` in `main` (line 528) and the stem is just marked `FAILED` without diagnosing the corrupt cache.

The user must `rm -rf scripts/demo/raw/external/*` to recover. This is a real failure mode for a long-running container that gets `docker compose down`'d mid-fetch — and the script advertises itself as idempotent in the docstring (line 27-29).

**Fix:** Write to a `.tmp` sibling and rename atomically once the body is fully on disk. Pattern:
```python
def write_atomic(path: Path, data: str | bytes) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    if isinstance(data, bytes):
        tmp.write_bytes(data)
    else:
        tmp.write_text(data)
    tmp.replace(path)  # atomic on POSIX
```
For the streamed TIGER zip, write into `out_zip.with_suffix(".zip.tmp")` inside the `async with client.stream(...)` block, then `tmp.replace(out_zip)` after the loop completes successfully. Same pattern for the four `write_text` callsites.

Confidence: 90%. The failure is inherent to the write pattern; only the trigger frequency varies with deployment.

---

## Minor Issues

### MI-01: `callable` used as a type annotation — should be `typing.Callable` / `collections.abc.Callable`

**File:** `scripts/demo/fetch_external.py:485`
**Issue:** `FETCHERS: list[tuple[str, callable]] = [...]` references the **builtin function** `callable` in a type position. Runtime works only because `from __future__ import annotations` (line 40) defers evaluation; mypy/pyright will reject it. Other modules in the same module use lowercase `callable` would need rework if anyone ever calls `typing.get_type_hints()` on this module.

**Fix:**
```python
from collections.abc import Awaitable, Callable
FETCHERS: list[tuple[str, Callable[[httpx.AsyncClient], Awaitable[None]]]] = [...]
```
or use `typing.Callable` if you prefer not to add the import.

Confidence: 99%.

---

### MI-02: Earthquakes fixture's `style_config` has 5 classes but only 4 colors

**File:** `scripts/demo/fixtures/maps/2-earthquakes.json:55-65`
**Issue:** The graduated metadata claims `"classCount": 5` with `"breaks": [6, 7, 8, 9]` (4 thresholds → 5 bins) but `"colors"` has only 4 entries (`#fde725, #f39c12, #e74c3c, #7d3c98`). The actual `circle-radius` paint expression has 5 stops at magnitudes 5,6,7,8,9. The legend's `GraduatedRadiusLegend` (`frontend/src/components/map/LegendEntries.tsx:133-154`) iterates `sizes.map`, so a 5-bin radius scale paired with 4 colors will render 5 circles where the 5th uses `colors[3]` (last color) due to the `Math.min(i, safeColors.length - 1)` clamp at line 144. Visually it looks like the top two mag bins share a color.

Additionally, `"target": "radius"` plus a populated `colors` array is inconsistent — the actual paint colors map by `depth_km` (a free-style choice not captured in `style_config`), so the legend's color array describes nothing the map displays.

**Fix:** Either align to 5 colors (e.g. `["#fde725","#f39c12","#e67e22","#e74c3c","#7d3c98"]`) and 5 breaks, or set `"classCount": 4` and `"breaks": [6, 7, 8]` so the legend matches the paint stops. If the depth coloring isn't representable in `style_config`, drop `colors` entirely and let the legend show plain circles.

Confidence: 85%.

---

### MI-03: NIFC pagination doesn't validate that the first page returned features

**File:** `scripts/demo/fetch_external.py:447-452`
**Issue:** If the NIFC server returns `{"features": [], "properties": {"exceededTransferLimit": false}}` on page 0 (e.g. because the `where` clause matched zero rows after a schema change, or attr_POOState filter failed), the loop terminates with `all_features = []` and `out.write_text` writes a valid-but-empty FeatureCollection (>1 KB? actually no — `{"type":"FeatureCollection","features":[]}` is ~50 bytes, so this specific case won't trip MA-02's idempotency hazard; subsequent runs will retry). However, the orchestrator will happily ingest a zero-feature GeoJSON without any "did you mean…" hint, and the resulting fixture map will render an empty layer.

**Fix:** Raise if `len(all_features) == 0` after the loop, or at least emit a `logger.warning("NIFC returned 0 features for the configured where clause — check attr_POOState schema")`. The NYC fetcher already does similar validation implicitly via `ACS rows < 2` check at line 303-304.

Confidence: 80%.

---

### MI-04: `tracts_4state.geojson` and zip-extracted `.shp` directory are never cleaned up — re-runs reuse possibly-corrupt intermediates

**File:** `scripts/demo/fetch_external.py:260-290`
**Issue:** `out_tracts = OUT_DIR / "tracts_4state.geojson"` is created once and gated by `if not already_present(out_tracts)` (line 261). If a previous run produced a truncated `tracts_4state.geojson` (same root cause as MA-02, but specifically for this intermediate), the next run skips re-extracting and the JSON-load at line 333 fails with the corrupt cache. Same hazard for the `cb_2024_us_tract_500k_extracted/` directory created at line 274-275 — if the unzip got interrupted, the `.shp` set may be incomplete and `ogr2ogr` will produce a partial output.

**Fix:** Either roll up under MA-02's atomic-write pattern (writing intermediates to `.tmp` first), or delete intermediates on entry into the function so each run starts clean. The function's "skip if final output present" guard (line 240-242) already covers idempotency at the public boundary, so the intermediates can be ephemeral.

Confidence: 85%.

---

## Nits

### NIT-01: theme3 produces a `--- ---` log line for every full-stack run

**File:** `scripts/demo/themes/theme3.py:20`, consumed at `scripts/demo/seed-thematic-demo.py:422`
**Issue:** `THEME_NAME = ""` is intentionally empty, but the orchestrator's `print(f"\n--- {tm.THEME_NAME} ---")` at line 422 produces `--- ---` followed by `(no datasets registered for  yet)` (note double space, empty name). Cosmetic only.

**Fix:** Either filter out empty themes in `THEMES = [...]` at the orchestrator side (would require a frozen-orchestrator change — out of scope), or set `THEME_NAME = "(unused theme 3 stub)"` so the log line at least makes sense. The current behavior is harmless but noisy.

Confidence: 99%.

---

### NIT-02: `cp -rL` will silently succeed even when the source dir is empty (no fetched files)

**File:** `scripts/demo/run-seeder.sh:75`
**Issue:** `cp -rL /scripts/demo/raw/external/* /data/demo/external/ 2>/dev/null || true` masks two distinct conditions: (a) glob expansion fails because `raw/external/` only contains `.gitignore` + `.gitkeep`, and (b) cp fails because of permission errors. With `set -euo pipefail` the `|| true` is needed to keep the script alive when `fetch_external.py` skipped everything via cache; but it also means a real cp failure (e.g. read-only mount on `/data/demo/external/`) is invisible until the orchestrator tries to ingest a missing file 30 seconds later and fails with a confusing "local file missing" message at `seed-thematic-demo.py:215`.

**Fix:** Tighten the loop so it only copies files that actually exist:
```sh
shopt -s nullglob
files=(/scripts/demo/raw/external/*)
if [ ${#files[@]} -gt 0 ]; then
    cp -rL "${files[@]}" /data/demo/external/
fi
```
This lets a real cp failure surface via `set -e` without masking the empty-source-dir case.

Confidence: 75% (judgement call — current behavior is fine if you trust the orchestrator's `local_path missing` error to be discovered downstream).

---

## Items considered and dismissed

- **SQL/SoQL injection in Socrata + ArcGIS URLs:** All `where` clauses, AOIs, and field filters are hardcoded constants. No user input flows into the URL. Dismissed.
- **Path traversal in `OUT_DIR`:** `Path(__file__).parent / "raw" / "external"` is a fixed relative path; no user-controlled component. Dismissed.
- **`subprocess.run(cmd, check=True)` with `cmd: list[str]`:** No `shell=True`, so no shell metachar interpretation. The interpolated values (`vsizip_path`, `out_zip`, `out_dem`) come from constants under `OUT_DIR`. No injection risk. Dismissed.
- **Memory consumption of `r.json()` for ~50k-feature responses:** Could be 200-500 MB peaks, but not a correctness bug. The seeder runs in a sized container, and the task brief excluded performance from scope. Dismissed.
- **`async def fetch_grand_canyon_dem` doing only blocking subprocess calls:** Wasteful but not incorrect — the orchestration loop is sequential anyway. Dismissed.
- **Trap fires `delete-key` on every EXIT including success:** That's the documented intent ("rotate the demo-seed key away on exit (graceful or abnormal)") at line 42-44. Working as designed. Dismissed.
- **`_meta.theme` byte-for-byte match:** Verified. theme1 fixtures all `"When the Land Speaks"`; theme2 fixtures all `"When the Earth Moves"`. Theme module `THEME_NAME` constants match exactly. Pass.
- **e2e `DEMO_MAP_NAMES` byte-for-byte match to fixture `name`:** Verified all 5 names match identically (case, punctuation, spacing). Pass.
- **`local_path` consistency with `stem`:** Verified all 6 entries across theme1/theme2 — basename of `local_path` = `stem` + ext. Match `fetch_external.py` output paths. Pass.
- **Pitch ≥ 45 on 3D maps:** Grand Canyon 60, NYC 60, Pop-density 50, Wildfires 30 (2D), Earthquakes 0 (2D points). The 3 fixtures advertised as 3D all clear the threshold. Pass.
- **Raster fixture has DEM + hillshade stacked:** `1-grand-canyon.json` has both `grand_canyon_dem` (sort_order 0, opacity 0.85) and `grand_canyon_hillshade` (sort_order 1, opacity 0.5). DEM below, hillshade on top. Correct per the docstring rationale at `fetch_external.py:91-94`. Pass.
- **License metadata completeness:** All 6 dataset entries in theme1/theme2 carry `license`. Pass.
- **TypedDict shape compliance:** All theme entries use only keys defined in `ThemeDataset` (stem, type, source, local_path, summary, snapshot_date, license). Pass.

---

_Reviewed: 2026-05-08T20:24:51Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: quick_
