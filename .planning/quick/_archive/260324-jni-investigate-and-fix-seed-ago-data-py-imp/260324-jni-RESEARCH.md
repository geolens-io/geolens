# Quick Task: Investigate seed-ago-data.py Import Errors - Research

**Researched:** 2026-03-24
**Domain:** Backend resilience, nginx proxy config, seed script hardening, admin UI
**Confidence:** HIGH

## Summary

The 502 errors are caused by **missing nginx proxy timeouts** on the `/api/` location block. The default `proxy_read_timeout` is 60s, but the service preview endpoint runs `ogrinfo` against remote ArcGIS services (with a 60s subprocess timeout), and the commit+ingest pipeline runs `ogr2ogr` which can take minutes for large layers. When nginx times out waiting for the backend, it returns 502.

The backend runs as a **single uvicorn worker** (dev mode with `--reload`), so 3 concurrent requests that each spawn blocking `ogrinfo` subprocesses can exhaust the event loop's capacity to respond in time. The preview endpoint itself is async and spawns subprocesses, but the single-worker setup limits true parallelism.

The admin Jobs dashboard **already exists** at `/admin/jobs` with full filtering, search, pagination, expandable error details, and retry. No new dashboard is needed.

**Primary recommendation:** Add `proxy_read_timeout 600s` to nginx `/api/` block, reduce seed script default concurrency to 1, add retry with exponential backoff on 5xx, and raise default poll timeout to 1200s.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- Reduce default concurrency to 1-2 and add exponential backoff retry on 502/5xx errors
- Keep `--concurrency` CLI flag for user override
- Raise default poll timeout from 600s to 1200s
- Add `--timeout` CLI flag for user control
- Investigate AND fix the nginx/gunicorn configuration causing 502s under concurrent service preview load
- Harden the seed script with retry logic as defense-in-depth
- Add a job status dashboard: list all jobs with status, duration, error messages, filterable by status

### Deferred Ideas (OUT OF SCOPE)
None specified.
</user_constraints>

## Root Cause Analysis

### 502 Bad Gateway

**Cause:** nginx `/api/` location block has NO `proxy_read_timeout`, `proxy_connect_timeout`, or `proxy_send_timeout` directives. Nginx defaults are:
- `proxy_read_timeout`: 60s
- `proxy_send_timeout`: 60s
- `proxy_connect_timeout`: 60s

The service preview endpoint (`POST /services/preview/`) calls `run_service_preview()` which spawns `ogrinfo` with a 60s subprocess timeout. For ArcGIS layers, this involves an HTTP round-trip to the remote server. If the remote is slow, the ogrinfo call approaches or exceeds nginx's 60s timeout, producing a 502.

The commit endpoint triggers `ingest_service` as a background task via procrastinate (async job queue), so the commit itself returns quickly. But the preview step is synchronous within the request lifecycle.

**Confidence:** HIGH - verified by reading nginx.conf (no timeout directives), preview.py (60s subprocess timeout), and router.py (synchronous ogrinfo execution).

### Single Worker Bottleneck

The dev `docker-compose.yml` runs: `uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload --reload-dir /app/app`

This is a **single async worker**. While uvicorn can handle concurrent async requests, the `ogrinfo` subprocess calls in preview.py use `asyncio.create_subprocess_exec` which is properly async. However, 3 concurrent ogrinfo processes competing for CPU + network on a single container can cause slowdowns that push total request time past nginx's 60s timeout.

**Confidence:** HIGH - verified from docker-compose.yml line 99.

### Job Timeouts (600s)

The seed script polls `GET /api/jobs/{job_id}` with a hardcoded 600s timeout (line 255). Large ArcGIS layers with thousands of features take longer to download via ogr2ogr. The backend's own `JOB_TIMEOUT_SECONDS` is 3600s (1 hour), so jobs may still be running when the script gives up.

**Confidence:** HIGH - verified from seed script line 255 and jobs/router.py line 22.

## Fixes Required

### 1. nginx Proxy Timeouts (backend resilience)

Add to the `/api/` location block in `frontend/nginx.conf`:

```nginx
location /api/ {
    resolver 127.0.0.11 valid=10s;
    set $upstream_api http://api:8000;
    rewrite ^/api/(.*) /$1 break;
    proxy_pass $upstream_api;
    proxy_set_header Host $http_host;
    proxy_set_header X-Forwarded-Host $http_host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Accel-Buffering no;
    proxy_buffering off;
    proxy_cache off;
    client_max_body_size 500m;
    proxy_read_timeout 600s;
    proxy_send_timeout 600s;
    proxy_connect_timeout 30s;
}
```

**Why 600s:** Matches the upload max scenario (large file uploads can take minutes). The backend's own timeouts (60s for ogrinfo preview, 3600s for job processing) are the real guards; nginx should not be the bottleneck.

### 2. Seed Script Hardening

Current issues in `scripts/seed-ago-data.py`:
- Default concurrency is 3 (line 693) -- too aggressive for single-worker backend
- No retry on HTTP errors (line 529 catches Exception but doesn't retry)
- Hardcoded 600s poll timeout (line 255)
- httpx client timeout is 300s (line 708) but this is for the HTTP call itself, not the job poll

Fixes needed:
- Change default concurrency from 3 to 1
- Add `--timeout` flag (default 1200s) passed to `poll_job()`
- Add retry with exponential backoff on 5xx errors in `process_one()` (3 retries, backoff: 5s, 15s, 45s)
- Log retry attempts clearly

### 3. Admin Jobs Dashboard

**Already exists.** The admin jobs page is fully implemented:
- **Backend:** `GET /admin/jobs` with status, user_id, search filters + pagination (`backend/app/admin/router.py:282`)
- **Frontend:** `AdminJobsPage` at `/admin/jobs` (`frontend/src/pages/admin/AdminJobsPage.tsx`)
- **Component:** `JobList` with status filter, user filter, search, expandable rows showing error_message + user_metadata, retry button (`frontend/src/components/admin/JobList.tsx`)

The dashboard already shows: created_at, username, source_filename, status badge, duration, error messages, and a retry button for failed jobs. No additional work is needed here.

## Existing Code Structure

| File | Purpose | Key Details |
|------|---------|-------------|
| `scripts/seed-ago-data.py` | Seed script | 805 lines, asyncio + httpx, semaphore concurrency |
| `frontend/nginx.conf` | Reverse proxy | No API timeout directives (root cause) |
| `backend/app/services/router.py` | Preview/probe endpoints | `POST /services/preview/` runs ogrinfo synchronously |
| `backend/app/services/preview.py` | ogrinfo subprocess | 60s timeout on subprocess, async subprocess exec |
| `backend/app/jobs/router.py` | Job status API | `GET /jobs/{job_id}`, 3600s auto-fail timeout |
| `backend/app/jobs/models.py` | IngestJob model | status, error_message, started_at, completed_at |
| `backend/app/admin/router.py` | Admin jobs list | `GET /admin/jobs` with filters |
| `frontend/src/pages/admin/AdminJobsPage.tsx` | Admin jobs UI | Already complete |
| `frontend/src/components/admin/JobList.tsx` | Job table component | Filters, search, expandable details, retry |

## Common Pitfalls

### Pitfall 1: Retry on Non-Idempotent Operations
**What goes wrong:** Retrying the preview+commit sequence could create duplicate IngestJobs.
**How to avoid:** Only retry the initial `POST /services/preview/` call (which is effectively idempotent -- creates a new pending job). Do NOT retry the commit step without checking if the first attempt succeeded.

### Pitfall 2: nginx Timeout vs Backend Timeout Mismatch
**What goes wrong:** If nginx timeout < backend processing time, nginx returns 502 while the backend continues processing, leading to ghost jobs.
**How to avoid:** nginx timeout should be >= the longest expected synchronous backend operation. The preview ogrinfo has a 60s timeout; add margin to 600s for the nginx proxy.

### Pitfall 3: Exponential Backoff Without Jitter
**What goes wrong:** Multiple concurrent tasks retry at the same time, creating thundering herd.
**How to avoid:** Add random jitter to backoff delays: `delay * (0.5 + random.random())`.

## Sources

### Primary (HIGH confidence)
- `frontend/nginx.conf` -- no proxy timeout directives in `/api/` block
- `backend/app/services/preview.py` -- 60s ogrinfo subprocess timeout
- `backend/app/services/router.py` -- synchronous ogrinfo in request handler
- `docker-compose.yml` -- single uvicorn worker, no gunicorn
- `scripts/seed-ago-data.py` -- concurrency=3, timeout=600s, no retry
- `backend/app/jobs/router.py` -- JOB_TIMEOUT_SECONDS=3600
- `frontend/src/components/admin/JobList.tsx` -- existing admin jobs dashboard
- `backend/app/admin/router.py` -- existing admin jobs API

## Metadata

**Confidence breakdown:**
- Root cause (502): HIGH -- nginx timeout absence is definitive
- Root cause (job timeout): HIGH -- hardcoded 600s vs backend 3600s
- Fix approach: HIGH -- standard nginx configuration + script hardening
- Admin dashboard scope: HIGH -- already exists, verified in code

**Research date:** 2026-03-24
**Valid until:** 2026-04-24
