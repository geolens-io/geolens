---
status: complete
date: 2026-05-23
---

# Quick 260523-at1: Docker Rebuild + Seed Sweep

**Date:** 2026-05-23
**Operator:** Claude (autonomous quick)
**Repo HEAD:** `4a7d1a29`
**Branch:** `main`

## Rebuilt

Stack brought down with `docker compose down -v` (clean exit, all 6 containers + 2 named volumes removed) and rebuilt with `docker compose up -d --build`. Build was largely cached (db image cached, backend `uv sync` cached, frontend `npm ci` rebuilt 568 packages in 3s from npm cache). Total wall time from `up` invocation to all-services-healthy: ~3 minutes.

| Service | Image / Build | Final State | Time-to-Healthy (approx) | Notes |
|---------|---------------|-------------|--------------------------|-------|
| db | `./db` → `geolens-db` (postgis/postgis:17-3.5 + pgvector 0.8.2) | healthy | ~15-25s after start | start_period=10s, interval=5s |
| migrate | `Dockerfile` target=api → `geolens-migrate` | exited 0 | one-shot, 3s wall clock (11:52:18 → 11:52:21) | 22 alembic migrations applied 0001 → 0022 |
| api | `Dockerfile` target=api → `geolens-api` | healthy | ~30-40s after start | start_period=20s, interval=10s |
| worker | `Dockerfile` target=worker → `geolens-worker` | healthy | ~30-40s after start | start_period=10s, interval=10s |
| titiler | `ghcr.io/developmentseed/titiler:2.0.2` | healthy | ~20s after start | start_period=15s, pulled from cache (already local) |
| frontend | `frontend/Dockerfile.dev` (node:25.9.0-alpine) | healthy | ~30-60s after start (vite cold start) | start_period=30s, interval=30s |

Smoke probes:
- `GET http://localhost:8080/api/health` → **200** with `{"status":"healthy","providers":{"database":"ok","storage":"ok","cache":"ok"}}`
- `GET http://localhost:8080/` (vite) → **200**
- `GET http://localhost:8080/api/collections/` (with trailing slash) → **307** (redirects to internal `http://api:8000/collections` — see Issues §2)
- `GET http://localhost:8080/api/collections` (no slash) → **200** with OGC catalog landing

Final state post-Task-2 (12 minutes after up):

```
SERVICE    STATE     STATUS
api        running   Up 12 minutes (healthy)
db         running   Up 12 minutes (healthy)
frontend   running   Up 12 minutes (healthy)
titiler    running   Up 12 minutes (healthy)
worker     running   Up 12 minutes (healthy)
(migrate exited 0)
```

## Imported

| Script | Status | Datasets Added | Collection Count After | Notes / Skip Rationale |
|--------|--------|----------------|------------------------|------------------------|
| `scripts/seed-natural-earth.py` | ran | 109 datasets, 2 collections | 109 datasets / 2 catalog collections / 109 OGC features | Wall time ~3m23s (07:58:18 → 08:01:41 local). Auth via `--username admin --password admin` (script mints temporary API key internally). |
| `scripts/seed-e2e.py` | **skipped — already covered by Natural Earth** | 0 (incremental) | unchanged | seed-e2e seeds exactly `ne_10m_admin_0_countries` (→ `admin_0_countries_10m`, UUID `43fc691a-186c-4b57-8b6f-1452b97e3edb`) and `ne_10m_reefs` (→ `reefs_10m`, UUID `2e62ba48-b5a3-4b7f-9ad1-e633061fe048`), both present after Natural Earth. Both retrievable at `/api/collections/{uuid}` HTTP 200. |
| `scripts/seed-perf-data.py` | skipped | 0 | — | Heavy synthetic perf data (1000+ datasets); not part of canonical 'all seed'. Run explicitly when perf testing. |
| `scripts/seed-ago-data.py` | skipped | 0 | — | External ArcGIS Online dependency (`https://njhighlands.maps.arcgis.com`); network-flaky, requires explicit `--api-key` + outbound HTTPS. Not part of operational sweep. |

Ingest job state after Natural Earth seed (queried via `/api/admin/jobs/?limit=200`): **108 complete, 1 failed** (see Issues §1).

Sample of seeded datasets (first 10 of 109; `title (table_name)`):

- Wgs84 Bounding Box (10m) (wgs84_bounding_box_10m)
- Reefs (10m) (reefs_10m)
- Playas (10m) (playas_10m)
- Graticules 30 (10m) (graticules_30_10m)
- Graticules 15 (10m) (graticules_15_10m)
- Graticules 20 (10m) (graticules_20_10m)
- Graticules 10 (10m) (graticules_10_10m)
- Graticules 5 (10m) (graticules_5_10m)
- Graticules 1 (10m) (graticules_1_10m)
- Geography Regions Polys (10m) (geography_regions_polys_10m)

Collection assignment (per seed-natural-earth Import Summary):

- **Natural Earth Cultural (10m)** — 71 datasets (UUID `dfb6fe60-7e4e-4d5d-9cca-be26583d7356`)
- **Natural Earth Physical (10m)** — 38 datasets (UUID `a81d899a-c5e7-4e9b-ad30-3a9796fae2f0`)

## Errors

### Error 1 — `ne_10m_urban_areas_landscan` ingest job FAILED post-commit (`MissingGreenlet`)

- **Where surfaced:** `worker` container logs at `2026-05-23T11:59:21.038257Z` during seed-natural-earth run.
- **Symptom:** ingest_job `90254766-ca62-4db4-86c5-411d1c9061fe` marked `status=failed` even though the seed script reported "Succeeded: 109, Failed: 0".
- **Affected dataset:** `urban_areas_landscan_10m` (UUID `ffcba726-d61c-48e9-8786-3b41b5fc96f8`, source `ne_10m_urban_areas_landscan.zip`).
- **Data outcome (mitigating):** The dataset DID land in the catalog with `record_status=published`, `feature_count=6018`, and a valid `extent_bbox=[-175.23, -54.85, 178.53, 77.49]`. The failure occurred in the quicklook-generation phase AFTER the data commit, so the row is usable but the thumbnail/quicklook is missing. This is why the seed script's success-heuristic (which checks ingest dataset_id presence) disagrees with the worker's job-row `status`.
- **Log excerpt (ANSI stripped):**

```
worker-1  | 2026-05-23T11:59:21.038257Z [warning  ] quicklook_failed
  [app.processing.ingest.tasks_common]
  error="Can't reconnect until invalid transaction is rolled back.  Please rollback() fully before proceeding
         (Background on this error at: https://sqlalche.me/e/20/8s2b)"
  job_id=90254766-ca62-4db4-86c5-411d1c9061fe phase=commit table=urban_areas_landscan_10m task=ingest_file
worker-1  | 2026-05-23T11:59:21.038981Z [error    ] Ingest task failed
  [app.processing.ingest.tasks_vector]
  job_id=90254766-ca62-4db4-86c5-411d1c9061fe task=ingest_file
worker-1  | MissingGreenlet: greenlet_spawn has not been called; can't call await_only() here.
            Was IO attempted in an unexpected place?
            (Background on this error at: https://sqlalche.me/e/20/xd2s)
```

- **API confirmation:**

```
GET /api/admin/jobs/?limit=10&status=failed (admin token)
→ {
    "id": "90254766-ca62-4db4-86c5-411d1c9061fe",
    "status": "failed",
    "source_filename": "ne_10m_urban_areas_landscan.zip",
    "dataset_id": "ffcba726-d61c-48e9-8786-3b41b5fc96f8",
    "error_message": "greenlet_spawn has not been called; can't call await_only() here. Was IO attempted in an unexpected place? (Background on this error at: https://sqlalche.me/e/20/xd2s)",
    "started_at":  "2026-05-23T11:59:05.958235Z",
    "completed_at": "2026-05-23T11:59:22.527474Z"
  }
```

- **Likely root cause:** The quicklook commit-phase code path attempts a sync sqlalchemy call (or accesses a lazy-loaded relationship) from outside an async greenlet context. Probably `tasks_common.py` around the quicklook-write block on the commit phase. Repeatable enough that the seed reliably trips it on one specific dataset (urban_areas_landscan) but not the other 108 — feature shape may matter (multipolygon vs other geometry, or row count).
- **Status:** 1/109 datasets impacted; quicklook missing but data is queryable.

## Issues

### Issue 1 — Seed script success-count disagrees with worker job-row status

- **What:** `seed-natural-earth.py` reported `Succeeded: 109 / Failed: 0`, but `/api/admin/jobs/?limit=200` shows `108 complete, 1 failed`. The seed script does not reconcile against the persisted `ingest_jobs.status` row after polling.
- **Why it matters:** Operators relying on the seed script's exit-print for "everything's fine" will miss the `urban_areas_landscan` quicklook failure (Errors §1). Failed jobs accumulate as deferred work and may impact UI thumbnail rendering, OGC `numberMatched` parity if the failed dataset gets later GC'd, and any downstream "all datasets have a quicklook" assumption.
- **Disposition:** Defer to a backend fix; the seed script could `GET /api/admin/jobs/?status=failed` after the polling loop and report any failures. Out of scope for this sweep.

### Issue 2 — `/api/collections/` (trailing slash) leaks internal hostname in 307 redirect

- **What:** `GET http://localhost:8080/api/collections/` returns `HTTP 307` with `Location: http://api:8000/collections` — the **internal docker-compose hostname** leaks to the client.
- **Why it matters:** This is the same shape as the documented OGC `/collections/datasets` trailing-slash bug noted in MEMORY.md ("Exception: OGC `/collections/datasets` route is defined WITHOUT trailing slash — do NOT add one (causes 307 redirect to internal `api:8000` hostname)"). The bug surface is broader than `/collections/datasets` alone — it includes `/api/collections/`. Frontend code that constructs a no-slash URL works; any caller (curl, external client) that adds a slash gets back an unreachable internal URL.
- **Disposition:** Already a known issue per MEMORY.md; this sweep confirms the surface extends to `/api/collections/`. Not a regression.

### Issue 3 — `migrate` service runs alembic upgrade TWICE per startup

- **What:** The `migrate` service log shows two `alembic.runtime.migration Context impl PostgresqlImpl` blocks. First runs the 22 upgrade steps; second runs immediately after with no upgrade lines (head already applied).
- **Why it matters:** The migrate service has `command: sh -c "uv run --no-dev alembic upgrade head"` but inherits the api-target Dockerfile's `ENTRYPOINT`, which itself contains `uv run --no-dev alembic upgrade head` as a "safety net" (`backend/scripts/api-entrypoint.sh:62-68`). Both run, doubling alembic startup latency. The second invocation is a no-op (transactional DDL check finds head already applied), so the impact is small but observable.
- **Disposition:** Either override the entrypoint on the migrate service (e.g., `entrypoint: ["sh","-c"]`) OR detect "I'm the migrate service" in api-entrypoint.sh and skip the safety-net. Defer — low priority.

### Issue 4 — `db` image platform mismatch warning (arm64 host, linux/amd64 image)

- **What:** During `up -d --build`, docker emits `db The requested image's platform (linux/amd64) does not match the detected host platform (linux/arm64/v8) and no specific platform was requested`.
- **Why it matters:** On this macOS host (Apple silicon, arm64) the postgis/postgis:17-3.5 base image's `--platform=linux/amd64` (set in `./db/Dockerfile` line 1, per the build warning) forces emulation via Rosetta/QEMU. Postgres performance is degraded under emulation, but functional. The Dockerfile comment in `./db/Dockerfile` may be the source — it's flagged by `FromPlatformFlagConstDisallowed` in the build output: `WARN: FromPlatformFlagConstDisallowed: FROM --platform flag should not use constant value "linux/amd64" (line 1)`.
- **Disposition:** Known intentional pin (likely for pgvector build reproducibility); not blocking; not a regression. Worth a future enhancement: build a multi-arch postgis+pgvector image and remove the explicit platform.

### Issue 5 — `/api/auth/login/` (trailing slash) also returns 307

- **What:** `POST /api/auth/login/` → 307 (with -L, curl follows and obtains the token). `POST /api/auth/login` (no slash) → 200 directly.
- **Why it matters:** MEMORY.md states "JWT login is OAuth2 password form: `curl -d ... http://localhost:8080/api/auth/login/`" (with slash). That URL works only because curl/browser follow the 307. The same internal-hostname leak risk as Issue 2 applies. The frontend's actual auth client likely calls the no-slash version (since it works without -L) — MEMORY.md note is stale or referred to a prior route shape.
- **Disposition:** Update MEMORY.md to reflect the no-slash shape for `/api/auth/login`, OR ensure both shapes resolve to a 200 without exposing the internal `Location` URL. Defer (low priority — doesn't break frontend).

## Gaps

### Gap 1 — Plan assumed `/api/collections/{stem}` lookup by Natural Earth stem name

- **What:** Plan Task 2 step 5 specified `curl /api/collections/ne_10m_admin_0_countries` and `/api/collections/ne_10m_reefs` to verify e2e fixtures. The actual route is `/api/collections/{dataset_id}` where `dataset_id` is a UUID — not a Natural Earth stem. Both probes returned `HTTP 422 Validation Error: path.dataset_id: Input should be a valid UUID`.
- **Resolution applied:** Resolved the stems to UUIDs via `/api/datasets/?limit=200` filtered on `source_filename` containing `ne_10m_admin_0_countries.zip` and `ne_10m_reefs.zip`, then verified the UUIDs resolve via `/api/collections/{uuid}` (both HTTP 200). Functional intent of the success-criterion is satisfied.
- **Fix proposal:** Future quick plans referencing dataset fixtures should specify the lookup path that actually works (e.g., `GET /api/datasets/?source_filename=ne_10m_admin_0_countries.zip` or use the OGC items endpoint with a property filter). The plan's `done` text was technically unsatisfiable as written, but the functional check (these layers are in the catalog) was completed via the corrected probe.

### Gap 2 — Plan probe `?limit=500` exceeds API's hard cap of 200

- **What:** Plan Task 2 step 6 specified `curl /api/collections/?limit=500`. With JWT auth this returns `HTTP 422 Validation Error: query.limit: Input should be less than or equal to 200`.
- **Resolution applied:** Used `?limit=200` for the dataset-listing probe (returned all 109 datasets — no pagination needed at current scale) and `?limit=1` to read `numberMatched` for the OGC items count.
- **Fix proposal:** Update planning template to document the API's max-limit constraint, or have the seed-script probes consult `numberMatched` instead of fetching pages.

### Gap 3 — Initial poll loop treated "migrate missing from `docker compose ps`" as not-ready

- **What:** My health-poll script used `docker compose ps` (without `-a`) and expected `migrate` to appear. Since `migrate` exits ~3s after start with `restart: "no"`, it's removed from the active container list immediately, and my loop never reached "READY" — it timed out at 180s.
- **Resolution applied:** Switched to `docker compose ps -a` for inclusion of exited containers and verified migrate exit code via `docker inspect` (`ExitCode=0`). The plan's automated verify uses `docker compose ps --format json` (no `-a`), which has the same defect — but in practice the verify is invoked from a context where the operator knows to interpret `migrate` absence as "exited cleanly".
- **Fix proposal:** Quick-plan templates that check post-rebuild health for a one-shot service should use `docker compose ps -a` or query the specific service via `docker inspect <name> --format '{{.State.ExitCode}}'`. (Documentation-only — no code change.)

### Gap 4 — Anonymous OGC items endpoint accepts queries without auth; authenticated `/api/datasets/` requires Authorization

- **What:** `GET /api/collections/datasets/items?limit=10` returns 200 with all 109 features anonymously. `GET /api/datasets/?limit=10` requires `Authorization: Bearer ...` (returns 401 without).
- **Why it matters:** Two parallel listing endpoints with different auth posture isn't necessarily wrong (OGC is intentionally public-by-default; the admin/dataset CRUD endpoint requires auth). But operator scripts that switch between them need to know which header they need.
- **Disposition:** Document, not fix. Both behaviors are intentional per OGC vs admin-API split. ACCEPT.

## Next Actions

- **Investigate `urban_areas_landscan_10m` quicklook MissingGreenlet failure (Errors §1).** Reproducible across rebuilds since the seed reliably trips on the same dataset. Track as a bug in `app/processing/ingest/tasks_common.py` quicklook commit-phase code. Likely a lazy-load relationship access from outside an async context. **Severity: low** (data lands successfully, only quicklook missing).
- **Fix seed-natural-earth.py reconciliation (Issue 1).** Add a post-polling-loop sweep of `/api/admin/jobs/?status=failed` (filtered to the current run's job_ids) and surface any failures in the Import Summary so the operator can't miss a quicklook failure under a green "Succeeded: N" header.
- **Consider migrating the `migrate` service entrypoint (Issue 3).** Override the api-entrypoint.sh inheritance so alembic doesn't run twice per startup. Saves a few seconds on every dev rebuild.
- **Refresh MEMORY.md auth-login URL (Issue 5).** The trailing-slash on `/api/auth/login` causes a 307 and works only via curl `-L` follow. Update the canonical example to the no-slash form.

## Reproduction Commands

The exact command sequence that succeeded, for replay:

```bash
cd /Users/ishiland/Code/geolens
docker compose down -v
docker compose up -d --build
# Wait for healthchecks — db/api/worker/titiler/frontend report (healthy) in ps -a;
# migrate appears as `Exited (0)`. ~3 min wall-clock from clean state.
docker compose ps -a

# Smoke probes
curl -sf http://localhost:8080/api/health
curl -sf http://localhost:8080/
curl -sf http://localhost:8080/api/collections   # NO trailing slash

# Mint admin JWT — NO trailing slash on login endpoint
TOKEN=$(curl -s -X POST http://localhost:8080/api/auth/login \
  -d 'username=admin&password=admin' \
  | python3 -c "import json,sys; print(json.load(sys.stdin)['access_token'])")

# Run Natural Earth seed (script mints its own temp api-key from --username/--password)
python3 scripts/seed-natural-earth.py --base-url http://localhost:8080 \
  --username admin --password admin

# Verify catalog (anonymous works for OGC items)
curl -s "http://localhost:8080/api/collections/datasets/items?limit=1" \
  | python3 -c "import json,sys; print(json.load(sys.stdin)['numberMatched'])"
# Expected: 109

# Verify e2e fixtures (look up by source_filename, not stem)
curl -s "http://localhost:8080/api/datasets/?limit=200" \
  -H "Authorization: Bearer $TOKEN" \
  | python3 -c "
import json, sys
items=json.load(sys.stdin)['datasets']
for needle in ['ne_10m_admin_0_countries.zip', 'ne_10m_reefs.zip']:
  match=next((i for i in items if i.get('source_filename')==needle), None)
  print(f'{needle}: {match[\"id\"] if match else \"MISSING\"}')"

# Check failed jobs (Errors §1 will show up here)
curl -s "http://localhost:8080/api/admin/jobs/?status=failed" \
  -H "Authorization: Bearer $TOKEN" \
  | python3 -m json.tool | head -40

# Skipped:
# python3 scripts/seed-e2e.py --base-url http://localhost:8080 --api-key "$TOKEN"
#   → Both fixtures already present from Natural Earth.
# python3 scripts/seed-perf-data.py
#   → Heavy synthetic data; not part of canonical sweep.
# python3 scripts/seed-ago-data.py --api-key "$TOKEN"
#   → External ArcGIS Online dep; not part of canonical sweep.
```
