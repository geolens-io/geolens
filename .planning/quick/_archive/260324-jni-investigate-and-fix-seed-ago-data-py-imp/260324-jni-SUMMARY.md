---
phase: quick-260324-jni
plan: 01
subsystem: infra
tags: [nginx, httpx, seed-script, retry, backoff]

requires:
  - phase: none
    provides: n/a
provides:
  - "nginx proxy timeouts for /api/ preventing 502 on long-running requests"
  - "Hardened seed script with retry, configurable timeout, lower concurrency"
affects: [seed-ago-data, nginx, service-ingest]

tech-stack:
  added: []
  patterns: ["exponential backoff with jitter for 5xx retry", "timeout threading through async call chain"]

key-files:
  created: []
  modified:
    - frontend/nginx.conf
    - scripts/seed-ago-data.py

key-decisions:
  - "nginx proxy_read_timeout 600s chosen to exceed backend ogrinfo 60s subprocess timeout with headroom"
  - "httpx client timeout 660s (10% above nginx 600s) so nginx is always the timeout bottleneck"
  - "Default concurrency reduced from 3 to 1 to prevent backend overload during seed runs"
  - "poll_job default timeout raised from 600s to 1200s to allow backend job processing time"

patterns-established:
  - "Retry pattern: exponential backoff with random jitter (50-150% of base delay) for 5xx errors only"

requirements-completed: [SEED-FIX-502, SEED-FIX-TIMEOUT, SEED-RETRY]

duration: 3min
completed: 2026-03-24
---

# Quick Task 260324-jni: Seed Script 502 Fix Summary

**nginx proxy timeouts (600s) plus seed script retry with exponential backoff, configurable 1200s poll timeout, and concurrency=1 default**

## Performance

- **Duration:** 3 min
- **Started:** 2026-03-24T18:21:02Z
- **Completed:** 2026-03-24T18:24:01Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments
- nginx /api/ block now has proxy_read_timeout 600s, proxy_send_timeout 600s, proxy_connect_timeout 30s -- eliminating 502 Bad Gateway on long service preview requests
- Seed script retries 5xx errors up to 3 times with exponential backoff (5s, 15s, 45s base) plus random jitter
- Default concurrency reduced from 3 to 1, preventing backend overload
- New --timeout CLI flag (default 1200s) threaded through the full call chain: main -> process_one -> ingest_via_service/update_via_service -> poll_job
- httpx client timeout raised from 300s to 660s, ensuring httpx never times out before nginx

## Task Commits

Each task was committed atomically:

1. **Task 1: Add nginx proxy timeouts for /api/ location block** - `23f8accb` (fix)
2. **Task 2: Harden seed script -- retry, concurrency, timeout, httpx timeout** - `9995d4c0` (fix)

## Files Created/Modified
- `frontend/nginx.conf` - Added proxy_read_timeout 600s, proxy_send_timeout 600s, proxy_connect_timeout 30s to /api/ location block
- `scripts/seed-ago-data.py` - Retry logic, --timeout flag, concurrency=1 default, httpx timeout 660s, timeout threading through call chain

## Decisions Made
- nginx proxy_read_timeout 600s: exceeds ogrinfo 60s timeout with headroom for large file operations
- httpx 660s timeout: 10% above nginx 600s so nginx is always the bottleneck, not the client
- Concurrency default 1: prevents backend overload; users can increase with --concurrency flag
- Retry only 5xx: 4xx errors and non-HTTP exceptions are not retried (client errors and non-transient failures)
- Jitter range 50-150% of base delay: prevents thundering herd when multiple retries align

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Preserved outer exception handler for non-retryable errors**
- **Found during:** Task 2
- **Issue:** The plan's retry structure had `raise` in except blocks that would propagate to the TaskGroup and crash the entire run for non-retryable errors (same as original code's `except Exception as exc` handler caught)
- **Fix:** Wrapped the retry for-loop in an outer try/except that catches all exceptions and appends them to results, matching original graceful error handling behavior
- **Files modified:** scripts/seed-ago-data.py
- **Verification:** AST parse passes, error handling structure preserves original graceful failure semantics
- **Committed in:** 9995d4c0

---

**Total deviations:** 1 auto-fixed (1 bug)
**Impact on plan:** Essential for correctness -- without this fix, a single 4xx error would crash the entire seed run instead of logging and continuing.

## Issues Encountered
None

## Known Stubs
None

## User Setup Required
None - no external service configuration required. After deploying, nginx will automatically use the new timeouts. The seed script changes take effect on next run.

## Next Phase Readiness
- Seed script is ready for production use with `--timeout` and `--concurrency` flags
- Admin Jobs dashboard already exists at /admin/jobs for monitoring job progress

---
*Phase: quick-260324-jni*
*Completed: 2026-03-24*
