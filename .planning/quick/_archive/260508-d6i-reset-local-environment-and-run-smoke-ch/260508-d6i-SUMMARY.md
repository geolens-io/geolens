---
quick_id: 260508-d6i
type: summary
completed: 2026-05-08
commit: 7bac058b641f3aa88f1f0965195fdf99db45c27e
status: complete
---

# Quick Task 260508-d6i: Reset env + thematic demo + full smoke — Summary

All three tasks ran end-to-end: clean stack reset, thematic seeder ran with exit 0 (23 datasets + 9 fixture maps applied), full smoke suite executed across all three sub-suites. **6 smoke failures** captured below — `e2e:smoke:core` returned 4 failures + chain short-circuited; remaining sub-suites were re-run independently per RESEARCH.md guidance, surfacing 2 more in `e2e:smoke:builder` and 0 in `e2e:smoke:fixtures`. No source/test/env/compose files modified — failures are user triage per CONTEXT.md "Report only, stop".

## Reset

- **Volumes destroyed:** `geolens_pgdata`, `geolens_upload_staging` removed by `docker compose down -v`. Two additional named volumes from prior runs (`geolens_backup_data`, `geolens_tile_cache`) were not declared in the current compose file and were explicitly removed via `docker volume rm` to satisfy the "all four absent" must-have. Post-reset state: zero `geolens_*` volumes.
- **Stack startup:** `docker compose up -d --build` — `db`, `migrate`, `api`, `worker`, `frontend`, `titiler` all rebuilt or pulled.
- **Build status:** All image layers cached; build phase ~5s wall (no cold-pull). Total `up` wall: ~50s.
- **Time-to-healthy:** `/health` returned 200 immediately after `up` returned (api healthcheck is a precondition of `up -d` exit). All services reached `healthy` except `frontend` which stayed at `unhealthy` (Vite dev container's healthcheck is flaky during initial dep optimization, but `/health` and `/login` proxy correctly — proxy verified via `curl`).
- **Migrate exit:** `Exited (0)` — alembic migrations applied cleanly.
- **Network:** `geolens_default` confirmed.
- **Volumes recreated:** Compose declares `pgdata`, `upload_staging`, `backup_data` — only `pgdata` and `upload_staging` were actually attached to running services and recreated. `backup_data` is declared but only mounted on a service that's not in the default profile; not recreated. The pre-existing `tile_cache` volume from a previous compose generation is no longer in the compose file.

## Seed

- **Image:** `geolens-seeder:latest` (cached, Path A — no rebuild).
- **Network:** ran on `geolens_default` with `GEOLENS_BASE_URL=http://api:8000`.
- **Exit code:** **0** (full success — best case).
- **Wall time:** ~3 minutes.
- **Datasets in catalog post-seed:** **23** (verified via `GET /api/datasets/?limit=50`).
- **Maps applied:** **9** fixture maps (verified via `GET /api/maps/?limit=100`).
- **Per-theme outcomes:** all 3 themes succeeded with zero failures.
  - Planet Earth (2025 Snapshot): 9 ok, 0 failed; 2 fixtures applied.
  - How the World Lives (2024): 4 ok, 0 failed; 3 fixtures applied.
  - Lines on the Map (2024 Snapshot): 10 ok, 0 failed; 4 fixtures applied.

Tail of `/tmp/seed.log`:

```
=== GeoLens Thematic Demo Seeder ===
Existing datasets: 0

--- Planet Earth (2025 Snapshot) ---
  ne_10m_ocean: succeeded
  ne_10m_coastline: succeeded
  ne_10m_rivers_lake_centerlines: succeeded
  ne_10m_lakes: succeeded
  ne_10m_glaciated_areas: succeeded
  gebco_2024_30arcmin: succeeded
  gebco_2024_viridis: succeeded
  ne_10m_shaded_relief: succeeded
  srtm_himalayas: succeeded
  Summary: 9 ok, 0 failed
  Collection Planet Earth (2025 Snapshot): 9 datasets assigned (status 200)
  Applied fixture 1-earth-from-space.json → map 7d3e4004-5477-41aa-8440-4e0b8da7f6a5
  Applied fixture 1-global-bathymetry.json → map 101833d1-70c4-4ac1-8e85-4024eee03795

--- How the World Lives (2024) ---
  ne_10m_populated_places_simple: succeeded
  gdp_per_capita_ppp_2023: succeeded
  life_expectancy_2021: succeeded
  manhattan_buildings: succeeded
  Summary: 4 ok, 0 failed
  Collection How the World Lives (2024): 4 datasets assigned (status 200)
  Applied fixture 2-gdp-per-capita.json → map c2369a06-0fae-44ca-a2da-73d828a14b46
  Applied fixture 2-manhattan-skyline.json → map e9841237-23fa-4504-9489-c98a4760138f
  Applied fixture 2-population-at-a-glance.json → map 7bc6f336-b55c-4880-a36d-4eca0dd9ee9a

--- Lines on the Map (2024 Snapshot) ---
  ne_10m_admin_0_countries: succeeded
  ne_10m_admin_0_boundary_lines_land: succeeded
  ne_10m_admin_0_disputed_areas: succeeded
  ne_10m_admin_0_boundary_lines_disputed_areas: succeeded
  ne_10m_admin_0_antarctic_claims: succeeded
  ne_10m_admin_0_countries_chn: succeeded
  ne_10m_admin_0_countries_ind: succeeded
  ne_10m_admin_0_countries_pak: succeeded
  ucdp_ged_v25_1: succeeded
  refugees_by_origin_2023: succeeded
  Summary: 10 ok, 0 failed
  Collection Lines on the Map (2024 Snapshot): 10 datasets assigned (status 200)
  Applied fixture 3-conflict-events-2024.json → map 8a00687d-16d0-4e5e-b11f-913db33b9aeb
  Applied fixture 3-disputed-places.json → map 403de2e3-3ba1-4957-bab2-12d36b386eac
  Applied fixture 3-kashmir-toggle.json → map 2a4f0b10-991a-4bb0-8938-75b8169d3f2f
  Applied fixture 3-refugees-by-origin.json → map 31fff53f-5f08-44b2-b402-5ddc4c83c81a

=== Demo seed complete ===
```

## Smoke results

- **Scope:** `full` — `npm run e2e:smoke` chained `e2e:smoke:core && e2e:smoke:builder && e2e:smoke:fixtures`.
- **Chain behavior:** `e2e:smoke:core` returned exit 1 (4 failures), so the chain short-circuited. Per RESEARCH.md "complete failure picture" guidance, `e2e:smoke:builder` and `e2e:smoke:fixtures` were re-run independently to surface their results.
- **Combined exit:** **non-zero** (chain failed at core).
- **Wall time:** ~78s for core run, ~14s for builder, ~25s for fixtures = ~2m total.
- **Combined counts:** 30 passed, 6 failed, 17 did not run (in failed sub-suites builder/styling: 15 of 17 failed-or-skipped because both `beforeAll` setup tests failed; collections.spec also had `did not run` cascade after the failure).

### Smoke check FAILED (full)

Failures:

1. **`[chromium] › e2e/admin.spec.ts:67:7 › Admin Panel › audit log: view entries and table structure`** — `getByRole('heading', { name: 'Audit Logs' })` not visible after navigating to admin audit log page (10s timeout). The page didn't render the expected heading; no `/admin/audit-logs` request appeared in api logs at all, suggesting the frontend never made the call (page render failure or routing issue).
2. **`[chromium] › e2e/admin.spec.ts:181:7 › Admin Panel › sidebar navigation works across current admin sections`** — same root cause: `getByRole('heading', { name: 'Audit Logs' })` not visible after sidebar nav click. Same Audit Logs page render issue cascading into the sidebar walkthrough.
3. **`[chromium] › e2e/collections.spec.ts:91:7 › Collections › add dataset to collection`** — `getByRole('button', { name: 'Add' }).first()` not visible (15s timeout). Add-dataset-to-collection dialog never showed an Add button. Likely UI structure changed or a precondition (collection page state) didn't load in time. Cascaded `did not run` into specs 19/29 and 20/29 (`remove dataset from collection`, `delete collection`) since collections describe block is `serial`.
4. **`[chromium] › e2e/dataset-detail.spec.ts:49:7 › Dataset Detail › map renders, attribute table loads, export triggers download`** — strict mode violation: `getByText('FEATURES')` resolved to 6 elements (one heading + 5 link text matches like "75 features"). The test asserts visibility of the literal uppercase "FEATURES" heading but Playwright's strict-mode locator matches all substring occurrences. **Spec brittleness against the post-seed catalog**: the seeded catalog includes datasets named `Admin 0 Countries Ind`, `Coastline (10m)`, etc., whose card text contains substrings like "248 features" — those didn't exist in whatever empty/sparse test fixture this assertion was originally written against.
5. **`[chromium] › e2e/builder-styling.spec.ts:85:7 › Builder Data-Driven Styling › expands layer and configures categorical data-driven styling`** — `TypeError: fetch failed; cause: Error: getaddrinfo ENOTFOUND api`. **Server-side bug**: the test's `beforeAll` does `fetch('http://localhost:8080/api/maps/{id}/layers/', { method: 'POST' })`. The server returns a 307 redirect with `Location: http://api:8000/maps/{id}/layers` (in-container hostname, no `/api` prefix, trailing slash dropped). Node 25 `fetch()` follows the redirect, tries to resolve `api`, fails. Cascaded the test plus 15 `did not run` for the rest of the builder/styling suites since they also have `describe.serial` and either share `beforeAll` setup or run in the same project.
6. **`[chromium] › e2e/builder.spec.ts:87:7 › Map Builder › loads existing map and canvas is visible`** — same `getaddrinfo ENOTFOUND api` root cause as #5. The builder spec's `beforeAll` also calls `POST /api/maps/{id}/layers/` and hits the same 307→`http://api:8000/maps/...` redirect.

**Reproduction commands** (for #5/#6):

```bash
TOKEN=$(curl -sf -X POST http://localhost:8080/api/auth/login/ \
  -H 'Content-Type: application/x-www-form-urlencoded' \
  -d 'username=admin&password=admin' | python3 -c 'import sys,json; print(json.load(sys.stdin)["access_token"])')
curl -i -X POST "http://localhost:8080/api/maps/<some-map-id>/layers/" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"dataset_id":"<some-ds-id>"}'
# Returns: HTTP/1.1 307 Temporary Redirect
# Location: http://api:8000/maps/<id>/layers
```

Counts: 30 passed, 6 failed, ~17 did not run, ~2m total.

### Sub-suite breakdown

| Sub-suite | Tests | Passed | Failed | Did not run | Notes |
|-----------|-------|--------|--------|-------------|-------|
| `e2e:smoke:core` | 29 | 23 | 4 | 2 | Chain short-circuited; 2 cascaded skips inside `collections.spec.ts:115` and `:130` after failure of `:91` due to `describe.serial`. |
| `e2e:smoke:builder` (re-run) | 18 | 1 | 2 | 15 | Both `beforeAll` setup tests failed on the API redirect bug; 15 dependent tests skipped. |
| `e2e:smoke:fixtures` (re-run) | 6 | 6 | 0 | 0 | All passing — these specs are self-contained, don't use the broken layers-create endpoint. |

## Blockers / next steps

User triage queue (no Claude action — per "Report only, stop"):

1. **HIGH — Trailing-slash redirect bug on `POST /api/maps/{id}/layers/`** (failures #5, #6): the FastAPI route is defined without trailing slash; 307 redirects expose the in-container hostname `http://api:8000/...` to the host browser/Node fetch, breaking any non-redirecting client. This is a real product bug with the same signature as `MEMORY.md` "FastAPI trailing slashes" entry. Worth opening a ticket. Affects 17 of 18 builder smoke tests and any future programmatic layer-creation client.
2. **MEDIUM — `dataset-detail.spec.ts:49` strict-mode mismatch on `FEATURES`** (failure #4): test was written against a smaller catalog where 'FEATURES' didn't appear in card text. Now the seeded catalog has multiple datasets whose feature counts (`75 features`, `99 features`, `248 features`, `1473 features`, `4133 features`) match `getByText('FEATURES')` case-insensitive substring search. The test selector should use `getByText('FEATURES', { exact: true })` or scope to the detail panel only.
3. **MEDIUM — `admin.spec.ts:67` and `:181` Audit Logs page heading missing** (failures #1, #2): the audit log page never rendered the expected `Audit Logs` heading. No `/admin/audit-logs` request hit the api per logs — page-load or route-state issue, not an API issue. Recommend investigating client-side, e.g., a feature flag or UI rename. Could also be that the heading is now structured differently (not an h1/h2 with that text).
4. **LOW — `collections.spec.ts:91` Add button not visible** (failure #3): UI flow may have changed (button moved, renamed, or collection-detail page structure refactored). Manual reproduction recommended before patching the test.
5. **Frontend container `unhealthy` status**: cosmetic — the Vite dev healthcheck is flaky at startup. Service responds correctly via the proxy, just the docker healthcheck script is over-strict. Pre-existing condition; not a blocker for this run.

## Notes

- HTML report: `playwright-report/index.html` (generated by Playwright config's `reporter: 'html'`). Test screenshots in `test-results/` were overwritten by subsequent sub-suite runs (Playwright clears between projects); only the screenshot from the last-run sub-suite persists.
- Per CONTEXT.md "Report only, stop" — **no source/test/env/compose files were modified to address any failure**. `git status --short` shows zero non-planning modifications.
- During catalog verification, two probe maps (`E2E Test Probe`, `E2E Probe2`) were temporarily created via `POST /api/maps/` to debug the redirect issue, then deleted. Final catalog state matches the canonical 9 seeded maps.
- Login: the catalog-verification probe initially used `Content-Type: application/json` for `/api/auth/login/` and got a 422; switched to `application/x-www-form-urlencoded` per the route's actual schema. Worth flagging in a future research pass since RESEARCH.md's example reproduction commands use JSON.
- Commit at task completion: `7bac058b641f3aa88f1f0965195fdf99db45c27e`.
- Raw logs preserved at `/tmp/seed.log` (303 lines), `/tmp/smoke.log` (228 lines), `/tmp/api-logs-full.txt` (887 lines).

## Self-Check: PASSED

- SUMMARY.md exists at the canonical path.
- `/tmp/seed.log` (303 lines) and `/tmp/smoke.log` (228 lines) preserved.
- Frontmatter `status: complete`.
- All 4 required sections present (`## Reset`, `## Seed`, `## Smoke results`, `## Blockers / next steps`).
- `git status --short` confirms zero modifications outside `.planning/`.
- Stack still healthy post-task (`/health` returns 200).
