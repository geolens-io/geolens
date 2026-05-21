---
phase: 260508-lkz-rebuild-geolens-demo-themes-and-fixtures
verified: 2026-05-08T20:35:55Z
status: passed
score: 14/14 must-haves verified
overrides_applied: 0
re_verification:
  previous_status: issues_found
  previous_review: 260508-lkz-REVIEW.md
  findings_closed:
    - "MA-01: pop-density 3D extrusion invisible at z4 — repivoted to LA z14 (commit 58f9676a)"
    - "MA-02: idempotency check trusts byte count — atomic_write_text + atomic_gdal_output helpers added (commit 150fc5d6)"
    - "MI-01: callable used as type annotation — replaced with Callable from collections.abc (commit 150fc5d6)"
    - "MI-02: earthquakes classCount=5 vs 4 colors mismatch — set classCount=4, breaks=[6,7,8] (commit cb474308)"
    - "MI-03: NIFC empty-page silent failure — RuntimeError raised on zero features (commit 150fc5d6)"
    - "MI-04: tracts intermediates leak between runs — atomic-rename now wraps every intermediate (commit 150fc5d6)"
    - "NIT-01: theme3 produced '--- ---' log line — THEME_NAME='(unused)' (commit cb474308)"
    - "NIT-02: cp -rL masked real failures and copied .partial files — find with .partial exclusion (commit cb474308)"
  findings_remaining: []
---

# Quick Task 260508-lkz: Rebuild GeoLens Demo Themes and Fixtures — Verification Report

**Task Goal:** Rebuild GeoLens demo themes and fixtures with five visually arresting 3D and Map Builder showcase maps.

**Verified:** 2026-05-08T20:35:55Z
**Status:** passed
**Re-verification:** Yes — after REVIEW.md (8 findings) closed in commits 150fc5d6, 58f9676a, cb474308

## Goal Achievement

### Observable Truths

| #  | Truth | Status | Evidence |
|----|-------|--------|----------|
| 1  | fetch_external.py exists, py_compile clean, --help shows --only flag, 5 fetcher functions match FETCHERS list | VERIFIED | `python3 -m py_compile` clean; `--help` output includes `--only {grand_canyon_dem,nyc_pluto_zoning,pop_density_tracts,usgs_quakes_m5,nifc_fires_2020_2024}`; FETCHERS at line 536-542 has 5 entries; 5 `async def fetch_*` definitions found |
| 2  | run-seeder.sh has bash -n clean syntax and invokes fetch_external.py before orchestrator | VERIFIED | `bash -n` clean; `python3 /scripts/demo/fetch_external.py` at line 62; orchestrator invocation at line 132 (after line 62 → correct ordering) |
| 3  | theme1.py exposes THEME_NAME='When the Land Speaks', THEME_IDX=0, DATASETS with 4 underscored entries, all licensed | VERIFIED | THEME_NAME='When the Land Speaks', THEME_IDX=0, len(DATASETS)=4 (grand_canyon_dem, grand_canyon_hillshade, nyc_pluto_zoning, pop_density_tracts) — all underscored, all carry license |
| 4  | theme2.py exposes THEME_NAME='When the Earth Moves', THEME_IDX=1, DATASETS with 2 underscored entries, all licensed | VERIFIED | THEME_NAME='When the Earth Moves', THEME_IDX=1, len(DATASETS)=2 (usgs_quakes_m5, nifc_fires_2020_2024) — all underscored, all carry license |
| 5  | theme3.py is an empty stub with DATASETS=[] (preserves frozen orchestrator import at line 67) | VERIFIED | DATASETS=[], THEME_NAME='(unused)' (NIT-01 fix), file present so orchestrator's `from themes import ... theme3` resolves |
| 6  | Exactly 5 fixture JSONs exist in scripts/demo/fixtures/maps/ | VERIFIED | `ls scripts/demo/fixtures/maps/*.json | wc -l` = 5; all 5 expected names present |
| 7  | Exactly 9 old fixtures absent from disk AND removed from git index | VERIFIED | `git ls-files scripts/demo/fixtures/maps/` shows only `.gitkeep` + 5 new fixtures; all 9 old fixture paths absent from disk |
| 8  | Each new fixture's _meta.theme matches its theme module's THEME_NAME byte-for-byte | VERIFIED | 1-grand-canyon, 1-nyc-zoning, 1-pop-density: `_meta.theme='When the Land Speaks'` (matches theme1); 2-earthquakes, 2-wildfires: `_meta.theme='When the Earth Moves'` (matches theme2) |
| 9  | Each new fixture's `name` and `_meta.name` are byte-equal | VERIFIED | All 5 fixtures: `name == _meta.name` confirmed |
| 10 | DEMO_MAP_NAMES (5 strings) match the 5 fixture name fields | VERIFIED | e2e set == fixture set: ['Grand Canyon: Land in 3D', 'NYC Zoning: Manhattan in 3D', 'Density Bars: Los Angeles', 'Global Earthquakes M5+ (Last 5 Years)', 'Western US Wildfires 2020-2024']; OPTIONAL_DEMO_MAPS=[]; no legacy names linger |
| 11 | Cross-file stem reconciliation: every fixture _stem matches a theme dataset stem | VERIFIED | declared = fixture stems = {grand_canyon_dem, grand_canyon_hillshade, nifc_fires_2020_2024, nyc_pluto_zoning, pop_density_tracts, usgs_quakes_m5}; missing=∅, extra=∅ |
| 12 | All 3D fixtures have pitch >= 45 | VERIFIED | 1-grand-canyon: 60.0, 1-nyc-zoning: 60.0, 1-pop-density: 50.0 |
| 13 | Vector 3D fixtures (1-nyc-zoning, 1-pop-density) set paint._height_column | VERIFIED | nyc-zoning: `paint._height_column='height'`; pop-density: `paint._height_column='_density'` |
| 14 | Frozen files unchanged: seed-thematic-demo.py, docker-compose.demo.yml, .env.demo, docker/seeder/Dockerfile | VERIFIED | `git diff 07ae01b4..HEAD` produces 0 lines for each frozen path |

**Score:** 14/14 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `scripts/demo/fetch_external.py` | Sequential httpx + GDAL pre-fetch script for 5 sources | VERIFIED | 583 lines; 5 fetcher coroutines; FETCHERS list; argparse with `--only`; atomic_write_text/atomic_gdal_output helpers (12 invocations); proper imports incl. `Callable from collections.abc` |
| `scripts/demo/run-seeder.sh` | Wrapper: fetch + bridge + orchestrator | VERIFIED | bash -n clean; invokes fetch_external.py at line 62; bridges via `find ... ! -name '*.partial' -exec cp -rL` at line 83; orchestrator at line 132 |
| `scripts/demo/raw/external/.gitkeep` | Tracked dir marker | VERIFIED | Present, empty |
| `scripts/demo/raw/external/.gitignore` | Excludes fetched data files | VERIFIED | Present; ignores *.tif, *.geojson, *.zip, *.json with `!.gitignore !.gitkeep` allowlist |
| `scripts/demo/themes/theme1.py` | "When the Land Speaks" (4 datasets) | VERIFIED | 66 lines; correct constants; 4 ThemeDataset entries with all required fields including license |
| `scripts/demo/themes/theme2.py` | "When the Earth Moves" (2 datasets) | VERIFIED | 39 lines; correct constants; 2 ThemeDataset entries |
| `scripts/demo/themes/theme3.py` | Empty stub | VERIFIED | DATASETS=[]; THEME_NAME='(unused)' (NIT-01 fix); preserves frozen orchestrator import |
| `scripts/demo/fixtures/maps/1-grand-canyon.json` | DEM raster + hillshade overlay | VERIFIED | 2 raster_geolens layers; pitch 60; theme match |
| `scripts/demo/fixtures/maps/1-nyc-zoning.json` | NYC PLUTO 3D extruded buildings | VERIFIED | 1 vector_geolens; pitch 60; `_height_column='height'`; categorical landuse paint |
| `scripts/demo/fixtures/maps/1-pop-density.json` | Pop-density 3D bars (LA repivot) | VERIFIED | 1 vector_geolens; center=(-118.24, 34.05) LA; zoom=14.0; pitch 50; `_height_column='_density'`; viridis ramp on _mhi |
| `scripts/demo/fixtures/maps/2-earthquakes.json` | Global M5+ point styling | VERIFIED | 1 vector_geolens; classCount=4 + 4 colors + 3 breaks (MI-02 fix); circle-radius/circle-color paint |
| `scripts/demo/fixtures/maps/2-wildfires.json` | Western US fires polygon by year | VERIFIED | 1 vector_geolens; categorical fire_year paint; smoke palette |
| `e2e/demo-smoke-shared.ts` | DEMO_MAP_NAMES = 5 fixture names; OPTIONAL=[] | VERIFIED | Lines 3-11; matches fixture names byte-for-byte; no legacy names |

### Key Link Verification

| From | To | Via | Status | Details |
|------|-----|-----|--------|---------|
| 1-grand-canyon.json | theme1.py THEME_NAME | _meta.theme exact-string match | WIRED | `_meta.theme='When the Land Speaks'` == theme1.THEME_NAME |
| 2-earthquakes.json | theme2.py THEME_NAME | _meta.theme exact-string match | WIRED | `_meta.theme='When the Earth Moves'` == theme2.THEME_NAME |
| run-seeder.sh | fetch_external.py | subprocess invocation before orchestrator | WIRED | Line 62 (pre-fetch) precedes line 132 (orchestrator) |
| run-seeder.sh | /data/demo/external/ | cp via find from /scripts/demo/raw/external/ | WIRED | Line 83 with .partial exclusion |
| theme1.py local_path | fetch_external.py output stems | /data/demo/external/{stem}.{ext} match | WIRED | All 6 entries: basename(local_path) == stem + ext (.tif or .geojson); matches output filenames in fetch_external.py byte-for-byte |
| fixture _stem values | theme[12].py DATASETS[*].stem | resolve_fixture lookup | WIRED | Set equality: declared = fixture stems = 6 underscored stems |
| DEMO_MAP_NAMES | fixture name field | byte-for-byte match | WIRED | 5 strings match 5 fixture `name` values exactly (incl. "Density Bars: Los Angeles" replacing original "Population Density: 4-State Bars") |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| fetch_external.py compiles | `python3 -m py_compile scripts/demo/fetch_external.py` | exit 0 | PASS |
| --help exposes --only | `python3 scripts/demo/fetch_external.py --help \| grep -q -- '--only'` | exit 0 | PASS |
| run-seeder.sh shell syntax | `bash -n scripts/demo/run-seeder.sh` | exit 0 | PASS |
| All 3 theme modules compile | `python3 -m py_compile scripts/demo/themes/theme[123].py` | exit 0 | PASS |
| All 5 fixtures parse as JSON | `node -e "JSON.parse(require('fs').readFileSync(...))"` x5 | all OK | PASS |
| Cross-file stem reconciliation | Python set comparison | declared==fixture | PASS |
| Frozen files unchanged | `git diff 07ae01b4..HEAD -- <each frozen path>` | 0 diff lines | PASS |

### Code Review Remediation (REVIEW.md)

All 8 findings closed in the chained fix commits — verified inline:

| Finding | Severity | Status | Commit | Evidence in working tree |
|---------|----------|--------|--------|--------------------------|
| MA-01 | Major | CLOSED | 58f9676a | `1-pop-density.json`: name="Density Bars: Los Angeles", center (-118.24, 34.05), zoom 14.0; e2e DEMO_MAP_NAMES updated |
| MA-02 | Major | CLOSED | 150fc5d6 | `atomic_write_text` + `atomic_gdal_output` helpers in fetch_external.py:83-112 used 12 times across all 5 fetchers |
| MI-01 | Minor | CLOSED | 150fc5d6 | `from collections.abc import Awaitable, Callable` at line 49; `Fetcher = Callable[[httpx.AsyncClient], Awaitable[None]]` at line 535 |
| MI-02 | Minor | CLOSED | cb474308 | 2-earthquakes.json `style_config`: classCount=4, colors len=4, breaks=[6,7,8] (3 thresholds → 4 bins) |
| MI-03 | Minor | CLOSED | 150fc5d6 | NIFC fetcher: `if not all_features: raise RuntimeError(...)` at line 503-508 |
| MI-04 | Minor | CLOSED | 150fc5d6 | All intermediate writes use `atomic_write_text`/`atomic_gdal_output`; tracts_4state.geojson (line 322-329), TIGER zip (line 289-295) |
| NIT-01 | Nit | CLOSED | cb474308 | theme3.py THEME_NAME='(unused)' instead of '' |
| NIT-02 | Nit | CLOSED | cb474308 | run-seeder.sh:80-84 uses `find ... ! -name '*.partial' -exec cp -rL {} ...` with empty-source guard |

### Anti-Patterns Found

None. The codebase is clean of TODO/FIXME/placeholder markers in modified files. The `except Exception` in `fetch_external.py:579` is annotated `# noqa: BLE001 — wrap-and-continue is intentional` and matches the per-fetcher failure-isolation contract documented at lines 530-541.

### Requirements Coverage

| Requirement | Description | Status | Evidence |
|-------------|-------------|--------|----------|
| DEMO-LKZ-01 | Pre-fetch script for 5 external sources | SATISFIED | `scripts/demo/fetch_external.py` with 5 fetcher coroutines, argparse `--only`, atomic writes |
| DEMO-LKZ-02 | Theme module rewrite + theme3 stub | SATISFIED | theme1 (4 datasets), theme2 (2 datasets), theme3 (empty stub preserving frozen-orchestrator import) |
| DEMO-LKZ-03 | 5 new fixtures + 9 old removed + e2e update | SATISFIED | Exactly 5 fixtures in maps/; 9 old removed from disk + git index; DEMO_MAP_NAMES updated to 5 fixture names |

### Deferred (out-of-scope per CONTEXT.md)

| Item | Reason | When |
|------|--------|------|
| Live HTTP requests to USGS/NYC/Census/NIFC | External-service flakiness; deferred per CONTEXT.md scope decision | Manual seeder run |
| Docker seeder execution | Code-only quick task | Manual: `docker compose -f docker-compose.yml -f docker-compose.demo.yml run --rm --no-deps seeder` |
| Playwright browser smoke | Deferred to orchestrator after verification | Manual: `E2E_DEMO_SEEDED=1 npm run e2e:smoke:audit` |

### Human Verification Required

None. All 14 must-haves verified programmatically; the deferred items are explicitly out-of-scope per the locked CONTEXT.md decision. The next manual step (seeder run + Playwright smoke) sits outside this verification window.

### Gaps Summary

No gaps. All 14 must-haves verified, all 8 review findings closed in working tree, all 4 frozen files untouched, all cross-file invariants (theme name binding, stem reconciliation, e2e map name match) hold byte-for-byte. The plan deliverable — 2-theme/5-fixture demo with code-only scope — is achieved cleanly. Note: the plan's original must_have spec called for `theme3.THEME_NAME=''` but the actual value is `'(unused)'`; this is the intentional NIT-01 remediation explicitly required by the verification prompt and improves the orchestrator's empty-theme log line — verified as the correct closure rather than a deviation.

---

_Verified: 2026-05-08T20:35:55Z_
_Verifier: Claude (gsd-verifier)_
