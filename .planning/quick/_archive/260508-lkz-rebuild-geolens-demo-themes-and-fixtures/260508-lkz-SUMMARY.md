---
phase: 260508-lkz
plan: 01
status: complete
completed: 2026-05-08
duration: ~12m
commits:
  - d3f5f0ad: "feat(260508-lkz): add fetch_external.py + run-seeder bridge for demo external data"
  - aa085916: "refactor(260508-lkz): rewrite theme1/theme2 + stub theme3 for new demo lineup"
  - 6bd794b8: "feat(260508-lkz): replace 9 demo fixtures with 5 new theme-aligned maps + e2e"
requirements: [DEMO-LKZ-01, DEMO-LKZ-02, DEMO-LKZ-03]
---

# Quick Task 260508-lkz: Rebuild GeoLens Demo Themes and Fixtures

## One-liner

Replaced the 3-theme / 9-fixture demo with a 2-theme / 5-fixture lineup driven by a new external-data pre-fetch script, rewritten theme modules, and updated e2e map-name assertions — all code-only, no live-network and no seeder run.

## Files changed

**Created**
- `scripts/demo/fetch_external.py`
- `scripts/demo/raw/external/.gitkeep`
- `scripts/demo/raw/external/.gitignore`
- `scripts/demo/fixtures/maps/1-grand-canyon.json`
- `scripts/demo/fixtures/maps/1-nyc-zoning.json`
- `scripts/demo/fixtures/maps/1-pop-density.json`
- `scripts/demo/fixtures/maps/2-earthquakes.json`
- `scripts/demo/fixtures/maps/2-wildfires.json`

**Modified**
- `scripts/demo/run-seeder.sh` — added pre-fetch invocation + host->container bridge
- `scripts/demo/themes/theme1.py` — rewritten as "When the Land Speaks" (4 datasets)
- `scripts/demo/themes/theme2.py` — rewritten as "When the Earth Moves" (2 datasets)
- `scripts/demo/themes/theme3.py` — converted to empty stub (preserves orchestrator import)
- `e2e/demo-smoke-shared.ts` — DEMO_MAP_NAMES updated to 5 new map names; OPTIONAL_DEMO_MAPS emptied

## Files deleted

- `scripts/demo/fixtures/maps/1-earth-from-space.json`
- `scripts/demo/fixtures/maps/1-global-bathymetry.json`
- `scripts/demo/fixtures/maps/2-gdp-per-capita.json`
- `scripts/demo/fixtures/maps/2-manhattan-skyline.json`
- `scripts/demo/fixtures/maps/2-population-at-a-glance.json`
- `scripts/demo/fixtures/maps/3-conflict-events-2024.json`
- `scripts/demo/fixtures/maps/3-disputed-places.json`
- `scripts/demo/fixtures/maps/3-kashmir-toggle.json`
- `scripts/demo/fixtures/maps/3-refugees-by-origin.json`

## Verify gates (static)

| Gate | Result |
| --- | --- |
| `py_compile scripts/demo/fetch_external.py` | PASS |
| `python3 scripts/demo/fetch_external.py --help \| grep --only` | PASS |
| `bash -n scripts/demo/run-seeder.sh` | PASS |
| `py_compile theme1.py + theme2.py + theme3.py` | PASS |
| theme constants (`THEME_NAME`, `DATASETS` lengths) | PASS |
| stem underscoring + `local_path` filename match | PASS |
| 5 fixtures `JSON.parse` | PASS |
| `name` == `_meta.name` per fixture | PASS |
| 3 Theme-1 fixtures pitch >= 45 | PASS |
| 2 vector 3D fixtures expose `paint._height_column` | PASS |
| `_meta.theme` exact match against THEME_NAME | PASS |
| Cross-file stem reconciliation (theme stems == fixture stems) | PASS — 6/6 |
| 9 old fixtures absent from disk and git index | PASS |
| Exactly 5 fixture `.json` files in `scripts/demo/fixtures/maps/` | PASS |
| `e2e/demo-smoke-shared.ts` carries 5 new map names + empty OPTIONAL_DEMO_MAPS | PASS |
| Frozen orchestrator (`seed-thematic-demo.py`) untouched | PASS |
| `docker-compose.demo.yml` untouched (file may not exist) | PASS |

## Theme/fixture map

| Theme module | THEME_NAME | Fixtures |
| --- | --- | --- |
| `theme1.py` | "When the Land Speaks" | `1-grand-canyon.json`, `1-nyc-zoning.json`, `1-pop-density.json` |
| `theme2.py` | "When the Earth Moves" | `2-earthquakes.json`, `2-wildfires.json` |
| `theme3.py` | "" (stub) | none — orchestrator prints "(no datasets registered for ...)" |

Declared theme stems = fixture `_stem` set, byte-identical:
`grand_canyon_dem`, `grand_canyon_hillshade`, `nyc_pluto_zoning`, `pop_density_tracts`, `usgs_quakes_m5`, `nifc_fires_2020_2024`.

## Manual next step (deferred per CONTEXT.md scope)

The seeder run + Playwright smoke check is OUT of scope for this code-only task. To validate end-to-end, run from a developer host:

```bash
# 1. Fetch external data + seed the demo. fetch_external.py runs first
#    (idempotent), then the orchestrator ingests + applies fixtures.
docker compose -f docker-compose.yml -f docker-compose.demo.yml run --rm --no-deps seeder

# 2. Run the e2e demo-smoke specs (which include demo-smoke.spec.ts and
#    demo-smoke-anonymous.spec.ts via the audit suite).
E2E_DEMO_SEEDED=1 npm run e2e:smoke:audit
```

The first run will pull ~120 MB across 5 sources (USGS 3DEP S3, NYC Open Data Socrata, Census TIGER + ACS, USGS FDSN, NIFC ArcGIS) and produce ~50 MB of fixed output in `/data/demo/external/` inside the container. Subsequent runs short-circuit on the `already_present` checks.

## Deviations from plan

None — plan executed exactly as written. Stems are underscored throughout per the plan's locked decision (CONTEXT.md said kebab-case but the planner caught and corrected this before execution). The optional `tsc --noEmit` gate failed to bootstrap via `npx -y typescript@5` (npm bootstrap error — unrelated to fixture content); plan permits skipping when JSON parse + grep gates pass, which they do.

## Decisions for memory

- `_height_column` paint convention: vector 3D fixtures (`1-nyc-zoning.json` extruding on `height`, `1-pop-density.json` extruding on `_density`) set `paint._height_column` to opt into the frontend's companion fill-extrusion layer (per `frontend/src/components/maps/hooks/use-map-layers.ts:91-97`).
- Stem casing: all dataset stems are underscored end-to-end (theme `stem` = fetch_external.py output filename = fixture `_stem`). Fixture filenames stay kebab-case.
- `theme3.py` is intentionally an empty stub because the frozen orchestrator imports it by name at line 67 — deletion would break ingest startup.

## Self-Check: PASSED

Verified files exist:
- FOUND: scripts/demo/fetch_external.py
- FOUND: scripts/demo/run-seeder.sh
- FOUND: scripts/demo/raw/external/.gitkeep
- FOUND: scripts/demo/raw/external/.gitignore
- FOUND: scripts/demo/themes/theme1.py
- FOUND: scripts/demo/themes/theme2.py
- FOUND: scripts/demo/themes/theme3.py
- FOUND: scripts/demo/fixtures/maps/1-grand-canyon.json
- FOUND: scripts/demo/fixtures/maps/1-nyc-zoning.json
- FOUND: scripts/demo/fixtures/maps/1-pop-density.json
- FOUND: scripts/demo/fixtures/maps/2-earthquakes.json
- FOUND: scripts/demo/fixtures/maps/2-wildfires.json
- FOUND: e2e/demo-smoke-shared.ts

Verified files absent (intentionally git-removed):
- ABSENT: scripts/demo/fixtures/maps/1-earth-from-space.json
- ABSENT: scripts/demo/fixtures/maps/1-global-bathymetry.json
- ABSENT: scripts/demo/fixtures/maps/2-gdp-per-capita.json
- ABSENT: scripts/demo/fixtures/maps/2-manhattan-skyline.json
- ABSENT: scripts/demo/fixtures/maps/2-population-at-a-glance.json
- ABSENT: scripts/demo/fixtures/maps/3-conflict-events-2024.json
- ABSENT: scripts/demo/fixtures/maps/3-disputed-places.json
- ABSENT: scripts/demo/fixtures/maps/3-kashmir-toggle.json
- ABSENT: scripts/demo/fixtures/maps/3-refugees-by-origin.json

Verified commits exist (chained from 07ae01b4):
- FOUND: d3f5f0ad
- FOUND: aa085916
- FOUND: 6bd794b8
