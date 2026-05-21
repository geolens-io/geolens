# Quick Task 260324-jni: Investigate and fix seed-ago-data.py import errors (502 Bad Gateway and job timeouts) - Context

**Gathered:** 2026-03-24
**Status:** Ready for planning

<domain>
## Task Boundary

Investigate and fix the two classes of errors seen when running `scripts/seed-ago-data.py` against localhost:
1. **502 Bad Gateway** — nginx returns 502 when multiple concurrent service preview requests hit the backend
2. **Job timeouts** — large ArcGIS layers exceed the 600s poll timeout

Also: investigate backend resilience and add an admin Jobs status dashboard.

</domain>

<decisions>
## Implementation Decisions

### Concurrency Handling
- Reduce default concurrency to 1-2 and add exponential backoff retry on 502/5xx errors
- Keep `--concurrency` CLI flag for user override

### Timeout Strategy
- Raise default poll timeout from 600s to 1200s
- Add `--timeout` CLI flag for user control

### Backend Resilience
- Investigate AND fix the nginx/gunicorn configuration causing 502s under concurrent service preview load
- Harden the seed script with retry logic as defense-in-depth

### Admin Jobs UI
- Add a job status dashboard: list all jobs with status, duration, error messages, filterable by status
- This gives visibility into import failures without requiring CLI log inspection

</decisions>

<specifics>
## Specific Ideas

- Error patterns from user's run: 502s on `/api/services/preview/` and timeouts after 600s on poll
- 78 total layers attempted, significant failure rate (~20+ failures)
- Concurrency was default 3 — even this modest parallelism causes 502s
- Some jobs start but never complete within 600s (large datasets)

</specifics>

<canonical_refs>
## Canonical References

- `scripts/seed-ago-data.py` — the seed script being fixed
- `backend/app/services/` — service connector backend code
- nginx config — proxy settings that may cause 502s
- `backend/app/jobs/` — job tracking system

</canonical_refs>
