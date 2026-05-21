---
name: 260508-d6i-RESEARCH
description: Operational research for the local-env-reset + thematic-demo + full smoke-check quick task
type: research
---

# Quick Task 260508-d6i: Reset local env + load demo data + run smoke-check.md - Research

**Researched:** 2026-05-08

## Summary

The thematic seeder (`scripts/demo/seed-thematic-demo.py`) is FROZEN to expect bundled data files at hard-coded paths under `/data/demo/` (e.g., `/data/demo/gebco_2024_30arcmin.tif`, `/data/demo/manhattan_buildings.geojson`). Those files only exist inside the **seeder image** built from `docker/seeder/Dockerfile`. They are NOT in the `api` image.

A pre-built `geolens-seeder:latest` image is already cached locally and already contains the full `/data/demo` payload (all .tif, .geojson.gz, .csv.gz) — verified via `docker run --rm --entrypoint ls geolens-seeder:latest /data/demo`. This is the simplest seed path: run the existing seeder image as a one-shot container against the running compose network. CONTEXT.md says don't *layer* `docker-compose.demo.yml` (which would also overlay api/worker/frontend with production-like images), but it does not forbid using the seeder image standalone — that's the recommended approach here.

**Primary recommendation:** Use the cached `geolens-seeder:latest` image as a one-shot `docker compose run` (or plain `docker run` on the compose network) with `GEOLENS_BASE_URL=http://api:8000` and the admin creds from `.env`. The image's ENTRYPOINT (`run-seeder.sh`) handles auth, API-key rotation, decompression, and orchestrator invocation.

## Stack startup sequencing

### Commands

```bash
# Reset (destroys 4 named volumes, preserves cache/ + image layers)
docker compose down -v

# Cold start — rebuilds api/worker/frontend, leaves remote images alone
docker compose up -d --build
```

### Dependency chain (verified from docker-compose.yml)

1. `db` (postgis) — `pg_isready` healthcheck, ~10s start_period
2. `migrate` — one-shot, `command: uv run --no-dev alembic upgrade head`, `restart: "no"`, `depends_on: db service_healthy`. **Migrations run automatically; do NOT invoke `make migrate` separately.**
3. `api` — `depends_on: db service_healthy AND migrate service_completed_successfully`. Healthcheck hits `http://localhost:8000/health` (in-container). 20s start_period, 10s interval, 3 retries → ~50s worst-case to healthy after migrate exits.
4. `worker` — same depends_on as api. Healthcheck on `:8001/health/live`.
5. `titiler` — `depends_on: db service_healthy`. Healthcheck on `:8000/healthz`.
6. `frontend` — `depends_on: api service_healthy`. Vite dev server, healthcheck on `:5173/`. start_period 30s, 30s interval — slowest service to mark healthy from cold (10-15s for vite to bundle the import graph + first HTTP probe).

### Healthy-state signal

The canonical "stack is ready" probe used by `smoke-check.md` is:

```bash
curl -sf http://localhost:8080/health
```

This goes through the Vite dev proxy (port 8080) → api (port 8000) `/health` endpoint, exercising both the frontend container AND the api container in one shot. **This is sufficient as the wait condition** — once it returns 200, the migrate has completed (api wouldn't be up otherwise) and frontend is ready (proxy works).

For belt-and-suspenders, also poll `docker compose ps --status running` to verify all 5 services (db, migrate-exited-success, api, worker, titiler, frontend) are present.

### Cold-build timing

Empirical from prior similar work in this repo: cold `docker compose up -d --build` with image layer cache present takes ~60-90s before `/health` returns 200. With layer cache cold (e.g., post `docker builder prune`), 3-6 min. CONTEXT.md says not to prune build cache, so expect the lower range.

**Recommended wait pattern:** poll `curl -sf http://localhost:8080/health` every 3-5s with a 180s timeout. If timeout, dump `docker compose ps` + `docker compose logs --tail=50` for triage and stop.

### Alembic migrations

Auto-run by the `migrate` service. The `api` container will not start until `migrate` exits with code 0. **No need to run `alembic upgrade head` manually.** Use `make migrate` only if a fresh migration is added mid-task (not the case here).

## Thematic demo seeder

### Discovery

`scripts/demo/seed-thematic-demo.py` is a FROZEN orchestrator (header comment: "Plans 218-02, 218-03, 218-04 must NOT modify this file"). It registers 3 themes (`theme1`, `theme2`, `theme3`) totaling 18 datasets across mixed source types:

| Source type | Theme 1 | Theme 2 | Theme 3 | What it does |
|-------------|---------|---------|---------|--------------|
| `vector` / `ne_cdn` | 5 | 9 | 4 | Downloads from `https://naciscdn.org/naturalearth/10m/...` at runtime, caches in `--cache-dir` |
| `vector` / `local` | 0 | 3 | 2 | **Reads from hard-coded `/data/demo/*.geojson` paths** |
| `raster` / `local` | 4 | 0 | 0 | **Reads from hard-coded `/data/demo/*.tif` paths** |

The orchestrator's `ingest_vector_local_with_summary` (line 215) and `ingest_raster_local` (line 251) both early-return `{"status": "failed", "error": "local file missing: <path> — Plan 05 Dockerfile must create it"}` when the file is absent on disk. **This means running the orchestrator from the api container or the host will fail on 9 of 18 datasets — but the 9 NE-CDN datasets will still succeed**, including the critical `ne_10m_admin_0_countries`, `ne_10m_ocean`, etc.

After ingest, the orchestrator applies 9 fixture maps from `scripts/demo/fixtures/maps/*.json`. Fixtures that reference failed-ingest stems will fail to apply (returning a non-zero exit code), but ingest of NE-CDN stems is fully decoupled.

### The three viable invocation paths

#### Path A (recommended): use the cached seeder image

A fully-bundled `geolens-seeder:latest` image already exists locally and has all `/data/demo/*` files present:

```bash
docker images | grep geolens-seeder
# geolens-seeder:latest   657d553fdecc   256MB

docker run --rm --entrypoint ls geolens-seeder:latest /data/demo
# gdp_per_capita_ppp_2023.geojson.gz
# gebco_2024_30arcmin.tif
# gebco_2024_viridis.tif
# life_expectancy_2021.geojson.gz
# manhattan_buildings.geojson.gz
# ne_10m_shaded_relief.tif
# refugees_by_origin_2023.geojson.gz
# srtm_himalayas.tif
# ucdp_ged_v25_1.csv.gz
```

Invocation against the running stack's compose network:

```bash
docker run --rm \
  --network geolens_default \
  -e GEOLENS_BASE_URL=http://api:8000 \
  -e GEOLENS_ADMIN_USERNAME=admin \
  -e GEOLENS_ADMIN_PASSWORD=admin \
  geolens-seeder:latest
```

The default network name with this compose project is `geolens_default` (compose project name = parent dir = `geolens`, default network suffix `_default`). Verify with `docker network ls | grep geolens` after `up`.

The image's ENTRYPOINT is `/scripts/demo/run-seeder.sh`, which:
1. Decompresses bundled `.gz` files in `/data/demo` (idempotent on re-run).
2. Polls `${GEOLENS_BASE_URL}/health` up to 30 retries × 5s = 150s — though if the compose stack is already healthy this returns immediately.
3. Logs in as admin, mints a `demo-seed` API key, runs the orchestrator with `--api-key <plaintext>`.
4. On exit, deletes the `demo-seed` API key (cleanup trap).

Expected duration on warm stack: 5-10 min total (downloads 9 NE-CDN zips of 10-50 MB each through to API ingest + commit + worker processing + fixture apply). Set timeout to 900s (15 min) for headroom.

Idempotency: the orchestrator calls `fetch_existing_datasets` and skips any stem whose `<stem>.zip` filename is already in the catalog. Re-running is safe and fast (skips all NE-CDN entries, re-applies fixtures).

#### Path B: build the seeder image fresh

If `geolens-seeder:latest` doesn't exist or is stale:

```bash
docker compose -f docker-compose.yml -f docker-compose.demo.yml build seeder
```

This builds Stage 1 (data-fetcher: downloads GEBCO, NE shaded relief, World Bank GDP, OWID life expectancy, NYC manhattan buildings, UCDP GED, UNHCR refugees, runs gdal_translate / csv_to_choropleth pre-joins) + Stage 2 (runtime: copies `/data/demo` + scripts/, sets ENTRYPOINT). **Cold build is 10-15 min on a fast connection** (GEBCO alone is a 6.7 GB download with BuildKit cache mount). With BuildKit cache mounts warm, ~2-3 min.

This invokes `docker compose build` only — does not start any service from the demo overlay. Then run via Path A.

#### Path C: skip local-source datasets, take the partial seed

If we don't want to deal with the seeder image at all, run the orchestrator from the api container. All 9 NE-CDN datasets ingest successfully; 9 local-source datasets fail with "local file missing"; 9 fixtures fail to apply. The smoke-check needs only "any dataset" + "any map", so this *might* pass — but builder.spec.ts' beforeAll creates a fresh test map referencing the first available dataset, which works as long as 1+ vector dataset exists. **Path C is risky** because:
- The orchestrator returns exit 1 (any fixture failed), which the wrapper script treats as a hard failure.
- Several smoke specs implicitly need a populated catalog beyond just one dataset.

**Decision:** prefer Path A. Fall back to Path B if Path A fails an image-presence check. Avoid Path C unless explicitly authorized mid-task.

### Logging strategy

Capture seeder stdout + stderr to `seed.log` for the SUMMARY.md. The seeder prints per-dataset status lines (`stem: succeeded|failed|skipped`) plus a per-theme summary block, so a tail of the last 30 lines is usually enough to summarize without dumping noise.

## Smoke-check

### Preconditions

`smoke-check.md` PHASE 0 requires `curl -sf http://localhost:8080/health` to return 200. After the up-and-seed sequence, this should always pass.

### Spec compatibility with seeded data (verified)

All specs in `npm run e2e:smoke` were inspected for state assumptions:

| Spec | Setup assumption | Compatibility with thematic seed |
|------|------------------|----------------------------------|
| `auth.spec.ts` | none — exercises login/logout | Compatible. |
| `admin.spec.ts` | admin user exists | Compatible — admin auto-created on first boot via `GEOLENS_ADMIN_USERNAME/PASSWORD`. |
| `search.spec.ts` | `getSearchSeed()` dynamically picks any dataset whose title yields a stable search match | Compatible — works as long as ≥1 dataset is searchable. NE-CDN seed always satisfies. |
| `dataset-detail.spec.ts` | `beforeAll` GETs `/api/datasets/?limit=10`, picks the first vector dataset (sorted by feature_count desc) | Compatible — needs ≥1 vector dataset. NE-CDN seed creates many. |
| `collections.spec.ts` | exercises CRUD on collections; creates/destroys its own | Compatible. May overlap with seeded collections by name but uses unique IDs; no count assertions. |
| `permissions.spec.ts` | admin auth + permissions matrix | Compatible. |
| `builder.spec.ts` | `beforeAll` GETs `/api/datasets/?limit=1`, creates a fresh test map, adds the dataset as a layer; `afterAll` deletes the map | Compatible — needs ≥1 dataset. Cleans up after itself. |
| `builder-styling.spec.ts` | piggybacks on builder fixtures | Compatible. |
| `upload.spec.ts` | uses `e2e/fixtures/sample.geojson`, uploads + commits | **Self-contained — does not depend on seed.** Creates a new dataset; doesn't clean up (intentional artifact for re-runs). |
| `non-spatial.spec.ts` | uses `e2e/fixtures/sample-nonspatial.csv`, uploads, then bulk-deletes via API in `afterAll` | **Self-contained — does not depend on seed.** Creates + cleans up. |

**No spec asserts an exact dataset/map count.** All count-related `toHaveCount(0)` calls are on UI elements (e.g., "Delete menu should not be visible after Escape"), not on catalog totals. **Seeded data does not break any smoke spec, and zero-data does not break the upload/non-spatial fixture specs.**

### Playwright environment

- `playwright.config.ts` declares `setup` project that runs `e2e/auth.setup.ts` first, logging in as `admin/admin` and writing storage state to `playwright/.auth/user.json`. All chromium specs depend on this. Don't need to manually create `playwright/.auth/`.
- `node` (v25 via Homebrew) is on PATH. `node_modules/@playwright`, `node_modules/@axe-core`, `node_modules/axe-core` exist — assume current. Do NOT run `npm install` unless the test runner errors with a missing module.
- Browsers: Playwright will use whatever chromium it last installed. If chromium is missing, Playwright errors with a clear "browser not found" message — handle reactively with `npx playwright install chromium` only if needed.
- Workers: 1 (config: `workers: 1`, `fullyParallel: false`). Tests run serially.
- Retries: 0 in non-CI. A flaky test will fail on first run.

### Smoke runtime estimate

`npm run e2e:smoke` runs 3 sub-suites sequentially: core (auth + admin + search + dataset-detail + collections + permissions ≈ 30-40 tests), builder (builder + builder-styling ≈ 10-15 tests), fixtures (upload + non-spatial ≈ 4-6 tests). Wall-clock: 6-12 min on a healthy stack. Set timeout to 1500s (25 min) for headroom (matches Playwright default per-test timeout × spec count).

### Failure capture

Per smoke-check.md PHASE 2: list failing test names + one-line reasons. The orchestrator already passes `reporter: 'html'` so `playwright-report/index.html` is generated automatically — reference it in SUMMARY.md but don't dump its raw contents. Also useful: tail of `docker compose logs --tail=80 api` if smoke fails after seed succeeded (to surface backend 500s vs frontend assertion failures).

## Pitfalls

### P1: Compose network name mismatch
- **What could happen:** `docker run --network geolens_default ...` fails with `network not found`.
- **How to detect:** `docker network ls | grep geolens` after `compose up` — confirm exact name.
- **Mitigation:** Read the actual network name first; the project name defaults to the parent directory (`geolens`). If the project was started with a different `-p`/`COMPOSE_PROJECT_NAME`, use that name + `_default`.

### P2: Seeder image absent or stale
- **What could happen:** `geolens-seeder:latest` doesn't exist (was pruned), or was built before the current `scripts/demo/` tree (orchestrator code drift).
- **How to detect:** `docker image inspect geolens-seeder:latest > /dev/null 2>&1` returns non-zero. Check image age vs `git log -1 --format=%ct scripts/demo/`.
- **Mitigation:** Path B — `docker compose -f docker-compose.yml -f docker-compose.demo.yml build seeder`. Note: image is currently 256 MB and was built recently (per `docker images` output it's present alongside `geolens-seeder-tmp:latest` from prior dev work).

### P3: Migrate service hangs
- **What could happen:** alembic migration fails (e.g., schema drift from prior manual edits), api never starts, frontend never reaches healthy.
- **How to detect:** After `up -d --build`, `docker compose ps migrate` shows `Exited (1)` instead of `Exited (0)`. `docker compose logs migrate --tail=80` shows the alembic error.
- **Mitigation:** Report the alembic error verbatim, stop. Source-code fixes are out of scope per CONTEXT.md.

### P4: Frontend slow-to-bundle on first hit
- **What could happen:** Vite dev server is up (`/health` returns 200 via api passthrough) but the first browser visit to `/login` takes 15-20s as Vite resolves the import graph. Playwright's `auth.setup.ts` has a 60s default timeout (config: `timeout: 60_000`) so this should not actually fail, but it can look like a hang.
- **How to detect:** `auth.setup.ts` taking >10s but eventually passing.
- **Mitigation:** Optionally pre-warm with `curl -s http://localhost:8080/login > /dev/null` after the stack is healthy and BEFORE running `npm run e2e:smoke`. Adds ~15s to the warm-up but eliminates the slow first-test risk. Discretion.

### P5: API trailing-slash 307s
- **What could happen:** Per CLAUDE.md memory, FastAPI routes defined with `"/"` cause 307 redirects when called without it. The seeder's `lib/create_api_key.py` uses paths like `/api/auth/login/` and `/api/auth/api-keys/` (with trailing slash) — verified correct. The smoke specs use `/api/datasets/?limit=10`, `/api/maps/`, etc. — also correct. **No mitigation needed; risk is zero for this task.** Mentioned only because it's the most common false-positive when hand-debugging.

### P6: Admin credentials must be set on FIRST boot
- **What could happen:** If `.env` is missing `GEOLENS_ADMIN_USERNAME` or `GEOLENS_ADMIN_PASSWORD`, the api container refuses to boot (Phase 273 SEC-15 validator).
- **How to detect:** `docker compose logs api` shows "GEOLENS_ADMIN_USERNAME is required". Verified from `.env` snapshot: both are set to `admin`.
- **Mitigation:** Pre-flight `grep -E '^(GEOLENS_ADMIN_USERNAME|GEOLENS_ADMIN_PASSWORD|JWT_SECRET_KEY)=' /Users/ishiland/Code/geolens/.env` before bringing the stack up. Current `.env` has all three set; no action needed unless missing.

### P7: Seeder upload size
- **What could happen:** The default `UPLOAD_MAX_SIZE_MB=500` (from .env) handles all bundled assets. The demo overlay raises it to 300 MB for a different reason (defending against public abuse), not because the dev default is too low. **No risk on the main stack.**
- **How to detect:** Seeder logs would show `413 Request Entity Too Large`.
- **Mitigation:** Already satisfied by main stack default.

### P8: Empty cache directory after volume reset
- **What could happen:** `docker compose down -v` destroys named volumes (`geolens_pgdata`, `geolens_tile_cache`, `geolens_upload_staging`, `geolens_backup_data`) — these are server-side. The host-side `cache/` directory (e2e Natural Earth fixtures) is bind-mounted nowhere and is preserved. Verified.
- **Mitigation:** None needed. The CONTEXT.md "preserve cache/" intent is automatically satisfied because no compose service mounts it.

### P9: Seeder local cache-dir collision
- **What could happen:** The orchestrator's `--cache-dir /data/demo/cache` writes downloaded NE-CDN zips into the seeder image's writable layer (the image is not read-only). On a one-shot `docker run --rm`, this cache evaporates with the container — fine for one-off runs but means re-running the seeder re-downloads. **Acceptable for this task.**
- **Mitigation:** None needed. If we later wanted persistent cache, add `-v $PWD/cache/seeder-cdn:/data/demo/cache`.

### P10: Worker readiness for fixture apply
- **What could happen:** The seeder commits ingest jobs and polls them. Jobs are processed by the Procrastinate worker. If the worker is somehow not healthy when the seeder sends the first commit, jobs stack up in pending and the seeder times out per-stem (300s for vectors, 600s for rasters).
- **How to detect:** `docker compose ps worker` shows `unhealthy` or `restarting`. Seeder logs show `poll_job timed out`.
- **Mitigation:** Pre-flight `docker compose ps --status running` check listing both `api` and `worker` as healthy before invoking the seeder. The wait-for-`/health` already gates on api healthy; explicitly add a worker check too.

## Recommended task sequence

```bash
# 0. Pre-flight
cd /Users/ishiland/Code/geolens
grep -E '^(GEOLENS_ADMIN_USERNAME|GEOLENS_ADMIN_PASSWORD|JWT_SECRET_KEY)=' .env
# Expect 3 non-empty lines. If any are missing/empty, stop and report.

docker image inspect geolens-seeder:latest > /dev/null 2>&1
# Exit 0 → Path A (use cached image). Exit 1 → Path B (build fresh).

# 1. Reset volumes
docker compose down -v

# 2. Cold start with rebuild
docker compose up -d --build

# 3. Wait for stack healthy (180s timeout)
for i in $(seq 1 60); do
  if curl -sf http://localhost:8080/health > /dev/null 2>&1; then
    echo "Stack healthy at attempt $i"
    break
  fi
  sleep 3
done
# Verify worker is healthy too
docker compose ps --format '{{.Service}} {{.Status}}' | grep -E '(worker|api).*healthy' \
  || { echo "ERROR: worker or api not healthy"; docker compose ps; docker compose logs --tail=60; exit 1; }

# 4. Determine compose network
NET=$(docker network ls --format '{{.Name}}' | grep -E '^geolens.*default$' | head -1)
echo "Using network: $NET"

# 5. Build seeder image if Path B (skip if Path A)
# docker compose -f docker-compose.yml -f docker-compose.demo.yml build seeder

# 6. Run thematic seeder via cached image (15 min timeout)
docker run --rm \
  --network "$NET" \
  -e GEOLENS_BASE_URL=http://api:8000 \
  -e GEOLENS_ADMIN_USERNAME=admin \
  -e GEOLENS_ADMIN_PASSWORD=admin \
  geolens-seeder:latest 2>&1 | tee /tmp/seed.log
SEED_EXIT=${PIPESTATUS[0]}
echo "Seeder exit: $SEED_EXIT"

# 7. Smoke-check preflight
curl -sf http://localhost:8080/health > /dev/null \
  || { echo "Stack went unhealthy after seed"; exit 1; }

# 8. Run full smoke suite (25 min timeout)
npm run e2e:smoke 2>&1 | tee /tmp/smoke.log
SMOKE_EXIT=${PIPESTATUS[0]}

# 9. Report (regardless of pass/fail)
echo "Smoke exit: $SMOKE_EXIT"
# If non-zero: extract failing test names from /tmp/smoke.log and write to SUMMARY.md
# If zero: write "Smoke check passed" to SUMMARY.md
```

**Notes for the executor:**
- Steps 2 and 3 can be combined behind `make reset-db` (which runs `docker compose down -v && docker compose up --build` in foreground), but the foreground form blocks — prefer the explicit two-step pattern shown.
- Step 6 produces ~30-50 lines of useful output (per-stem status + per-theme summary). Tail the last 40 lines into SUMMARY.md, not the full log.
- Step 8: `npm run e2e:smoke` chains 3 sub-suites with `&&`, so if `e2e:smoke:core` fails, `e2e:smoke:builder` and `e2e:smoke:fixtures` never run. To get a complete failure picture, optionally re-run each sub-script independently after the chained failure — discretion.
- Per CONTEXT.md "Report only, stop" — do not attempt to fix any failure. Capture names + one-line reasons + commit reference (`git rev-parse HEAD`) into SUMMARY.md and end.

---

**End of research.**
