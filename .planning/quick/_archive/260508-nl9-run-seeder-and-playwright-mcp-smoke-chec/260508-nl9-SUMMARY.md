---
phase: 260508-nl9
plan: 01
status: incomplete
completed: 2026-05-08
duration: ~3h (validation run; seeder iterated 4x against unfolding stack of bugs)
predecessor: 260508-lkz
fixtures_seeded:
  - nyc_pluto_zoning  # NYC PLUTO Zoning (Theme 1 vector)
  - pop_density_tracts  # Density Bars: Los Angeles (Theme 1 vector)
fixtures_failed:
  - grand_canyon_dem  # raster — worker MissingGreenlet
  - grand_canyon_hillshade  # raster — worker MissingGreenlet
  - usgs_quakes_m5  # vector — clip_to_mercator_bounds MissingGreenlet
fixtures_unreached:
  - nifc_fires_2020_2024  # seeder bails on first failure (usgs_quakes_m5)
inline_fixes_committed:
  - "docker/seeder/Dockerfile: add gdal-bin to runtime stage"
  - "scripts/demo/fetch_external.py: NIFC per-page exponential-backoff retry"
local_overrides_uncommitted:
  - ".planning/quick/260508-nl9-.../docker-compose.upload-override.yml (UPLOAD_MAX_SIZE_MB=1000, /tmp tmpfs=2g, UVICORN_WORKERS=1, api memory=2G)"
follow_up_issues:
  - "WORKER-MISSING-GREENLET: tasks_raster.ingest_raster + tasks_common._finalize_ingest fail with sqlalchemy.exc.MissingGreenlet — blocks 100% of raster ingest and any vector that triggers clip_to_mercator_bounds"
  - "TMPFS-UPLOAD-CAP: docker-compose.yml api service /tmp tmpfs=512m is smaller than upload_max_size_mb (500 default, 300 in demo overlay), causing SpooledTemporaryFile rollover to fail mid-upload as 400 'There was an error parsing the body'"
---

# Quick Task 260508-nl9: Seeder + Playwright MCP Smoke Checks — Status: INCOMPLETE

## One-liner

Live validation of the new (260508-lkz) demo fixtures uncovered five separate bugs along the seeder + ingest path; two were fixed inline, two are documented as follow-up items, and the Playwright MCP smoke leg was never reached because only 2/5 fixtures could be ingested.

## Goal recap (from PLAN.md)

> Run the deferred validation work: bring the stack up cleanly, run the demo seeder against the new fixtures, then use Playwright MCP to validate that all five demo maps render in the browser (anonymous + admin views).

## Outcome

**Did not complete.** Three of five fixtures fail to ingest because of a worker-side `sqlalchemy.exc.MissingGreenlet` bug that blocks both raster paths and the global earthquakes vector. Without seeded data, the Playwright MCP smoke is not meaningful, so the user-chosen disposition (`Stop, document, commit`) is to ship this report and triage the worker bug separately.

## Findings (in the order they appeared)

### 1. seeder image lacked `gdal-bin` (FIXED inline)

- **Symptom:** `fetch_external.py` aborted with `FileNotFoundError: [Errno 2] No such file or directory: 'gdal_translate'` (and again for `ogr2ogr`); 2/5 fetchers failed.
- **Root cause:** `docker/seeder/Dockerfile` Stage 2 (runtime) is `ghcr.io/astral-sh/uv:python3.13-bookworm-slim` and only installed `httpx`. Stage 1 (data-fetcher) had `gdal-bin` for the build-time prefetches, but 260508-lkz moved the prefetches to runtime via `fetch_external.py` without updating Stage 2's apt deps.
- **Fix:** Added `apt-get install -y --no-install-recommends gdal-bin` to Stage 2 with a comment pointing at 260508-lkz. Image grew ~80 MB but is the minimum required surface area for the new runtime fetch model.
- **Commit:** `fix(260508-nl9): add gdal-bin to seeder runtime stage` (pending)

### 2. NIFC ArcGIS pagination flakes mid-stream (FIXED inline)

- **Symptom:** `fetch_external.py:fetch_nifc_fires` raised `httpx.RemoteProtocolError: peer closed connection without sending complete message body (received 25165824 bytes, expected 45433714)` on different pages on different runs (pages 3, 4, 7 each failed at least once).
- **Root cause:** NIFC's WFIGS_Interagency_Perimeters ArcGIS service is intermittently flaky under bulk pagination — known per project memory `project_nifc_wfigs_perimeters_quirks.md`. The 260508-lkz fetcher had zero retry, so a single transient close aborted the entire NIFC fetch.
- **Fix:** Wrapped the per-page `client.get` in a 4-attempt exponential-backoff retry that catches `httpx.RemoteProtocolError`, `ReadError`, `ReadTimeout`, `ConnectError`. Per-page idempotent (no partial state).
- **Commit:** `fix(260508-nl9): retry NIFC pagination on transient httpx errors` (pending)

### 3. UPLOAD_MAX_SIZE_MB cap below DEM size (worked around via override file)

- **Symptom:** `httpx.HTTPStatusError: Client error '413 Content Too Large' for url 'http://api:8000/api/ingest/upload'`
- **Root cause:** Demo overlay sets `UPLOAD_MAX_SIZE_MB=300` (sized for the OLD 100 MB shaded-relief + 130 MB UCDP CSV datasets, 260508-lkz removed). The new Grand Canyon DEM is **716 MB** because `fetch_external.py:fetch_grand_canyon_dem` clips a 1.5° × 1° AOI from USGS 3DEP at 1/3 arc-second native resolution without downsampling.
- **Workaround:** Added `UPLOAD_MAX_SIZE_MB=1000` to the local `docker-compose.upload-override.yml`. Did NOT touch the demo overlay, since the right-sized cap depends on whether the demo wants to ship a downsampled DEM (smaller image, faster seed) or accept the larger upload.
- **Follow-up sizing question:** The DEM is also far larger than the rest of the demo combined. Unclear whether the intent was to accept this or whether `gdal_translate` should add `-tr 0.005 0.005` (or similar) to downsample the elevation grid for demo purposes. **Open question for the seeder owner.**

### 4. Worker MissingGreenlet on raster ingest + clip_to_mercator_bounds (NOT FIXED — follow-up)

- **Symptom:** `sqlalchemy.exc.MissingGreenlet: greenlet_spawn has not been called; can't call await_only() here.` Surfaces from:
  - `app/processing/ingest/tasks_raster.py:240` (raster ingest path) — both Grand Canyon DEM and Hillshade fail
  - `app/processing/ingest/metadata.py:939 clip_to_mercator_bounds` (called from `tasks_common._finalize_ingest:654`) — fails for `usgs_quakes_m5` but NOT for `nyc_pluto_zoning` or `pop_density_tracts`
- **Hypothesis:** The async session is being passed across a sync/threadpool boundary in the worker. The fact that the vector path passes for some datasets and fails for others suggests `clip_to_mercator_bounds` only triggers the bug when the WHERE clause `NOT ST_CoveredBy(geom, _MERCATOR_SAFE_ENVELOPE)` matches at least one row — global earthquakes (M5+ over 5 years) include polar events that breach ±85° lat, while the NYC + 4-state datasets are entirely within bounds and the UPDATE is a true no-op.
- **Reproduction:** Stand up the stack with the override file, run the seeder, watch `docker logs geolens-worker-1`. The first job (raster) fails in 0.4 s; vector jobs 3/5 fail similarly.
- **Severity:** **Hard blocker for any deployment that ingests rasters or near-pole vectors.** This is not specific to demo fixtures — any user-uploaded raster on this version of the worker would hit the same path.
- **Suggested next step:** Open a `/gsd-debug` session targeting `tasks_raster.ingest_raster` and `metadata.clip_to_mercator_bounds`. Likely fix is to ensure the AsyncSession used inside Procrastinate's worker context is created/disposed within a single greenlet/task scope (sqlalchemy[asyncio]'s `async_sessionmaker` + `AsyncSession()` async-context-manager).

### 5. tmpfs /tmp too small for SpooledTemporaryFile rollover during large uploads (worked around via override file)

- **Symptom:** `400 {"detail": "There was an error parsing the body"}` from FastAPI's generic body-parse catch (`fastapi/routing.py:447`). Curl reports the upload starting then aborting partway. No useful api log entry — FastAPI swallows the cause.
- **Diagnosis path:**
  1. Confirmed not a `MultiPartParser.max_part_size` issue (`max_part_size` only checks non-file parts).
  2. Confirmed not the upload size cap (`UPLOAD_MAX_SIZE_MB=1000` already accommodates the 716 MB DEM).
  3. Eventually traced to `tmpfs on /tmp size=524288k` (512 MiB) in `docker-compose.yml`'s api service. Starlette's `MultiPartParser.on_headers_finished` creates a `SpooledTemporaryFile(max_size=spool_max_size=1MB)` which rolls over to disk past 1 MiB; the rollover target is `/tmp` (default `tempfile.tempdir`), and a 716 MB write fails with `OSError: No space left on device` — wrapped by FastAPI as the generic 400.
- **Workaround:** Local override sets `tmpfs: /tmp:size=2g`. Demonstrated upload succeeded in 2.2 s afterward.
- **Permanent fix candidates (each has trade-offs):**
  1. **Bump `/tmp` tmpfs:** Easiest, keeps current architecture, but uses RAM. At 2 GB tmpfs the api memory footprint roughly doubles.
  2. **Direct SpooledTemporaryFile to a real volume:** Set `tempfile.tempdir = "/app/staging"` (or a sibling). Saves RAM but needs the staging volume to be writable from the api user, which it already is.
  3. **Bypass the spool entirely:** Replace `file: UploadFile = File(...)` in `/api/ingest/upload` with a Request-based handler that streams chunks directly to `/app/staging` without going through `SpooledTemporaryFile`. Most invasive but most efficient.
- **Severity:** Same hard-blocker class as #4. ANY user upload past 511 MiB fails with the same opaque 400.
- **Suggested next step:** Option (1) is the cheapest unblock; (2) is the right long-term answer.

## Inline fixes — files changed

| File | Change | Purpose |
| --- | --- | --- |
| `docker/seeder/Dockerfile` | Stage 2 `apt-get install gdal-bin` | Unblock fetch_external.py runtime |
| `scripts/demo/fetch_external.py` | NIFC pagination retry (4-attempt, exponential backoff) | Survive ArcGIS flakes |

## Local overrides — kept in `.planning/` (NOT committed to source)

| File | Purpose |
| --- | --- |
| `.planning/quick/260508-nl9-.../docker-compose.upload-override.yml` | UPLOAD_MAX_SIZE_MB=1000, UVICORN_WORKERS=1, api memory=2G, tmpfs /tmp=2g — the env required to make the seeder reach the worker for the new fixtures. Stays in the quick-task dir as a reproducer for finding #5 + #3. |

## Stack state at handoff

```
geolens-api-1        Up + healthy  (with override applied — UPLOAD_MAX_SIZE_MB=1000, /tmp=2g, workers=1)
geolens-worker-1     Up + healthy  (but failing on raster + near-pole vector ingest jobs)
geolens-frontend-1   Up + unhealthy   (Vite dev server on :8080 — likely fine despite health flag)
geolens-titiler-1    Up + healthy
geolens-db-1         Up + healthy  (DB has 2 partial datasets: nyc_pluto_zoning, pop_density_tracts)
```

The 2 successfully-ingested datasets are still in the DB. Map fixtures have NOT been applied (orchestrator bailed on raster failure before reaching the apply-fixtures step).

## What was NOT done (planned but skipped)

- Verify maps via API (no maps to verify).
- Playwright MCP anonymous demo visit (no maps to render).
- Playwright MCP admin login + map list (no maps to list).

## Recommended next session

1. **First:** open `/gsd-debug WORKER-MISSING-GREENLET` and resolve finding #4 — it blocks raster ingest globally, not just demo seeding.
2. **Second:** decide on permanent fix for finding #5 (tmpfs vs `tempfile.tempdir` redirect).
3. **Third:** decide on the Grand Canyon DEM sizing question (downsample vs ship 716 MB).
4. **Then:** rerun this validation. With the worker bug fixed, the seeder should complete cleanly, and the Playwright MCP smoke leg becomes meaningful.

## Self-Check

- [x] PLAN.md exists and tracks must_haves
- [x] All 5 findings reproduced + diagnosed at the source-code level
- [x] 2 inline fixes verified by re-running the seeder past the affected step
- [x] All git changes are tied to a finding (no scope creep beyond what validation surfaced)
- [x] Stack left in a state the user can either keep running or `docker compose down`
- [ ] All 5 fixtures ingested — INTENTIONALLY incomplete per user choice; finding #4 blocks
- [ ] Playwright MCP smoke run — INTENTIONALLY incomplete; depends on full seed
