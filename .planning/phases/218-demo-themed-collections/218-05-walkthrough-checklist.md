# Phase 218 Walkthrough Checklist

The walkthrough simulates a fresh operator landing on the GeoLens repo for the
first time and running the themed demo. It is the final acceptance gate for
Phase 218 — the phase does not ship until every checkbox is checked and the
operator signs off at the bottom.

## Setup

- [ ] Stop and remove all running containers and volumes for the dev stack:
      `docker compose down -v`
- [ ] (optional) Pull a fresh checkout in a temporary directory, OR `git stash`
      any local changes so the build runs against committed state only
- [ ] Copy `.env.demo` → `.env` (if `.env.demo` exists; otherwise verify
      `.env` has `GEOLENS_ADMIN_USERNAME` / `GEOLENS_ADMIN_PASSWORD` set)

## Build + Seed

- [ ] `docker compose -f docker-compose.yml -f docker-compose.demo.yml up -d --build`
- [ ] Wait for the seeder service to exit successfully:
      `docker compose -f docker-compose.yml -f docker-compose.demo.yml logs -f seeder`
  - First build dominated by GEBCO 2024 download (~6.7 GB → 50 MB COG, ~10–15
    minutes on a fast pipe). Subsequent builds are much faster thanks to
    BuildKit layer caching.
- [ ] Confirm: no `ERROR` or `FAIL` lines in the seeder logs
- [ ] Confirm: the seeder reports 3 collections created
- [ ] Confirm: the seeder reports ~42 datasets ingested across the three themes
  (Theme 1 ≈ 11+ datasets including the VRT mosaic, Theme 2 = 9 datasets,
  Theme 3 = 21 datasets)
- [ ] Confirm: the seeder applied all 8 fixtures successfully (or 9 if Theme 1
  Maps 1.1 + 1.2 are present in this build)

## Browse the Demo

- [ ] Open http://localhost:8080 and log in as admin/admin
- [ ] Navigate to **Maps**. Confirm all 8 (or 9) demo maps are listed
- [ ] Open each map in turn and verify visual quality:
  - [ ] **Map 1.1 Earth as Seen from Space** — looks like a NASA still on a
    dark ocean basemap; VRT mosaic of GEBCO bathymetry + NE shaded relief
  - [ ] **Map 1.2 Global Bathymetry** — viridis_r colormap on GEBCO; deep
    ocean trenches visible in dark purples
  - [ ] **Map 2.1 Population at a Glance** — proportional symbol map with
    visible megacity dots in dark red (Tokyo, Mumbai, Cairo, Lagos, etc.)
  - [ ] **Map 2.2 GDP per Capita PPP 2023** — country choropleth with rich
    countries in viridis yellow, poor countries in dark purple
  - [ ] **Map 3.1 The World's Disputed Places** — Western Sahara, Kashmir,
    and Somalia visible in disputed-area orange; Antarctic claims in pale blue
  - [ ] **Map 3.2 One Territory, Multiple Official Maps** — Kashmir centered
    at ~76°E 34°N. Toggling the Pakistan, India, and China view layers shows
    visibly different border positions (the conversation-starter effect)
  - [ ] **Map 3.3 Conflict Events 2024 (UCDP GED)** — dark basemap, red dots
    on active conflict regions (Ukraine, Sudan, Sahel, Yemen, Myanmar, DRC,
    Syria); year=2024 filter applied
  - [ ] **Map 3.4 Refugees by Country of Origin 2023** — Reds choropleth with
    Syria, Ukraine, Afghanistan, Venezuela, Pakistan in deep crimson
- [ ] For each map, no console errors in browser devtools (filter out the known
  `ResizeObserver`, favicon, and basemap sprite noise — see the test's
  `CONSOLE_NOISE_PATTERNS`)
- [ ] No tile requests return 4xx/5xx in the browser network tab

## Collection Pages

- [ ] **Planet Earth (2025 Snapshot)** — 11+ datasets, includes
  `gebco_2024_30arcmin`, `ne_10m_shaded_relief`, `srtm_himalayas`, plus the
  VRT mosaic and 8 NE physical vector layers
- [ ] **How the World Lives (2024)** — 9 datasets, includes
  `gdp_per_capita_ppp_2023`, `life_expectancy_2021`, `manhattan_buildings`;
  SEDAC GPWv4 is **not** present (intentionally dropped per CONTEXT.md)
- [ ] **Lines on the Map (2024 Snapshot)** — 21 datasets, includes all 9 NE
  country-specific shapefiles (`ne_10m_admin_0_countries_chn`/`ind`/`pak`/
  etc.), the UCDP GED v25.1 point dataset, and the UNHCR refugees pre-join.
  ACLED is **not** present (three-EULA-conflict per CONTEXT.md)

## Editorial Review

- [ ] Open the **UCDP GED** dataset detail page. Description includes language
  like "Source: Uppsala Conflict Data Program. Contents shown per UCDP's
  editorial stance, not GeoLens. License: CC-BY 4.0"
- [ ] Open the **UNHCR refugees** dataset detail page. Description includes
  the same language-discipline pattern
- [ ] Spot-check 5 Theme 3 layer descriptions: none use "aggression",
  "occupation", "invasion", or "terrorism" as editorial framing
- [ ] Open the **GEBCO** and **SRTM** dataset detail pages. Both include the
  "3D-ready" / "Phase 999.1" forward-compat note
- [ ] Open the **Manhattan buildings** dataset detail page. Includes
  "© OpenStreetMap contributors, ODbL 1.0" and the 3D forward-compat note

## Smoke Test

- [ ] `E2E_DEMO_SEEDED=1 npx playwright test e2e/demo-smoke.spec.ts` passes
  (6 required tests green; Theme 1 maps skipped if not yet seeded by this
  build, otherwise also green)

## Reset Verification

- [ ] `docker compose -f docker-compose.yml -f docker-compose.demo.yml exec reset /scripts/reset-demo.sh`
- [ ] `docker compose -f docker-compose.yml -f docker-compose.demo.yml restart seeder`
- [ ] Wait for re-seed to complete (no GEBCO download this time — the data
  layer is cached in the seeder image; only the API calls run)
- [ ] Confirm collection counts match the initial seed
- [ ] Re-run the Playwright smoke suite — passes again

## Final Sign-Off

- [ ] All checkboxes above are checked
- [ ] No follow-up issues blocking Phase 218 ship
- [ ] Operator: ___________
- [ ] Date: ___________

---

## Known Caveats (logged at Plan 218-05 ship time)

1. **GEBCO download dominates first build.** The `data-fetcher` Dockerfile
   stage downloads the full ~6.7 GB GEBCO 2024 GeoTIFF and downsamples it
   to a 30 arc-min COG. This RUN layer is cached aggressively by Docker
   BuildKit but the URL must remain stable for the cache to hit.
2. **Theme 1 fixtures (Maps 1.1 + 1.2) deferred by Plan 218-02.** The
   manual local-stage commands for the Theme 1 rasters were never run in
   the dev environment because the agent could not download GEBCO inside
   its sandbox. Plan 218-05 absorbs the staging into the Dockerfile, so
   the first successful Docker build will create the Theme 1 datasets in
   the live API. Building Maps 1.1 + 1.2 fixtures from there is a
   post-build follow-up — the operator can either use the map builder UI
   to construct them and re-export via `strip_for_fixture`, or wait for
   a follow-up commit that ships the fixtures.
3. **Smoke spec WebGL setup.** The Playwright config sets
   `--use-gl=swiftshader` so MapLibre's WebGL canvas works in headless
   Chromium. Without this flag the spec fails with `webglcontextcreationerror`.
4. **CHECKSUMS.sha256 not yet enforced.** The Dockerfile's `sha256sum -c`
   verification block is commented out and the file is populated with
   placeholders. After the first successful build, run
   `sha256sum /data/demo/*.tif /data/demo/*.csv /data/demo/*.geojson`
   from inside the seeder image and paste the real values, then uncomment
   the verification block.
