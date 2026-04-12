---
phase: 224-post-impl-audit-remediation
plan: "03"
subsystem: backend-resilience
tags: [resilience, error-handling, security, advisory-lock, storage, oauth]
dependency_graph:
  requires: []
  provides:
    - 503-on-embedding-rebuild-failure
    - thumbnail-temp-key-upload
    - oauth-stable-error-codes
    - bulk-delete-per-item-commit
    - chunked-body-limit-enforcement
    - advisory-lock-job-recovery
  affects:
    - backend/app/settings/router.py
    - backend/app/maps/router.py
    - backend/app/auth/oauth/router.py
    - backend/app/datasets/router.py
    - backend/app/middleware/body_limit.py
    - backend/app/worker.py
    - backend/app/jobs/models.py
    - backend/alembic/versions/
tech_stack:
  added: []
  patterns:
    - temp-key upload with post-commit cleanup
    - pg_try_advisory_xact_lock for distributed coordination
    - raw ASGI middleware for stream byte counting
    - per-item commit with rollback in bulk operations
key_files:
  created:
    - backend/alembic/versions/2026_04_12_0001-add_last_heartbeat_at_to_ingest_jobs.py
  modified:
    - backend/app/settings/router.py
    - backend/app/maps/router.py
    - backend/app/auth/oauth/router.py
    - backend/app/datasets/router.py
    - backend/app/middleware/body_limit.py
    - backend/app/worker.py
    - backend/app/jobs/models.py
decisions:
  - "Raw ASGI middleware chosen over BaseHTTPMiddleware for body_limit to enable stream wrapping control"
  - "Per-item commit for bulk delete: partial success preferred over all-or-nothing to avoid storage orphaning"
  - "5-minute heartbeat threshold for stale job detection; pending jobs use 1-hour cutoff (unchanged)"
  - "Manual Alembic migration written (DB not available in local dev without Docker)"
metrics:
  duration: "19 minutes"
  completed: "2026-04-12T15:21:40Z"
  tasks_completed: 6
  files_changed: 8
---

# Phase 224 Plan 03: Backend Resilience Audit Remediation Summary

**One-liner:** Six atomic fixes closing P0-3 and P1-13 through P1-18: 503+rollback on embedding rebuild, temp-key thumbnail upload, stable OAuth error codes, per-item bulk delete commits, chunked encoding body limit, and advisory-lock job recovery.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | P0-3 — Embedding rebuild 503 + rollback | af1f0687 | backend/app/settings/router.py |
| 2 | P1-13 — Thumbnail temp-key upload | 7e9bb77e | backend/app/maps/router.py |
| 3 | P1-15 — OAuth stable error codes | c400ef15 | backend/app/auth/oauth/router.py |
| 4 | P1-16 — Bulk delete per-item commit | a4395afb | backend/app/datasets/router.py |
| 5 | P1-17 — Chunked body limit enforcement | b4ce6694 | backend/app/middleware/body_limit.py |
| 6 | P1-18 — Advisory lock + heartbeat job recovery | 8f30de55 | backend/app/worker.py, backend/app/jobs/models.py, backend/alembic/versions/ |

## What Was Built

### Task 1: P0-3 — Embedding Rebuild 503 + Rollback (settings/router.py)

The `except Exception: pass` that silently swallowed embedding column rebuild failures was replaced. The old `embedding_dims` value is now captured before any changes are committed. On rebuild failure:
- `EMBEDDING_DIMS.set()` restores the previous value
- `db.commit()` persists the rollback
- `logger.exception()` logs the full traceback
- `HTTPException(503)` is raised so the admin sees a clear error

Admin no longer receives a false "success" response when the embedding column rebuild fails.

### Task 2: P1-13 — Thumbnail Temp-Key Upload (maps/router.py)

Replaced the deterministic-key write pattern with a temp-key pattern:
- Write to `maps/thumbnails/{map_id}.{ext}.{uuid8}` (temp key)
- Set `map_obj.thumbnail_uri = temp_key` and commit
- On failure: delete temp key, rollback DB, raise 503
- On success: delete old key (best-effort, non-fatal)
- Collapsed `except (ValueError, Exception)` to `except Exception` (ValueError is a subclass — the union was redundant)

No destructive overwrite of the existing thumbnail occurs before the commit succeeds.

### Task 3: P1-15 — OAuth Stable Error Codes (auth/oauth/router.py)

The `#error={quote(str(e))}` URL fragment that leaked raw exception text to browser history was replaced:
- `logger.warning(error=str(e))` → `logger.exception(...)` (captures full traceback with exc_info)
- URL fragment now uses `#error=oauth_failed&correlation_id={12-char-hex}`
- Admin can find the full traceback in logs using the correlation_id without exposing internals
- Removed `from urllib.parse import quote` (no longer needed)

### Task 4: P1-16 — Bulk Delete Per-Item Commit (datasets/router.py)

The single `await db.commit()` after the entire delete loop was moved inside the per-item loop:
- Each dataset deletion is now an atomic unit: delete storage + delete DB row + commit
- Failed items get `await db.rollback()` in `DependentVrtError`, `ValueError`, and catch-all `Exception` handlers
- Partial success: previously committed deletions remain; the failed item is rolled back independently
- No storage objects are orphaned when a DB commit fails partway through a batch

### Task 5: P1-17 — Chunked Body Limit (middleware/body_limit.py)

Converted `BaseHTTPMiddleware` subclass to raw ASGI middleware for stream wrapping control:
- Fast path unchanged: Content-Length header checked before reading body
- New stream path: `limited_receive()` wraps the ASGI `receive` callable, counting bytes as they arrive
- When `total_read > max_bytes`, returns an empty EOF chunk and overrides the response with 413
- Legitimate uploads within the limit pass through unaffected
- Both paths use the same `max_bytes` cap

### Task 6: P1-18 — Advisory Lock + Heartbeat Job Recovery (worker.py, jobs/models.py)

Added `last_heartbeat_at` column to `IngestJob` for tracking active jobs:
- `pg_try_advisory_xact_lock(224_001)` prevents concurrent recovery across worker instances; a worker that fails to acquire the lock skips recovery (another worker holds it)
- Stale detection now uses heartbeat age: jobs with `last_heartbeat_at < now - 5min` (or no heartbeat + `created_at < now - 5min`) are marked failed
- Running jobs with a recent heartbeat on another worker survive a rolling restart
- Orphaned pending job recovery (1-hour threshold) is unchanged
- Manual Alembic migration written: `2026_04_12_0001-add_last_heartbeat_at_to_ingest_jobs.py`

## Decisions Made

1. **Raw ASGI middleware for body_limit:** `BaseHTTPMiddleware` does not support wrapping the `receive` callable cleanly for chunked requests. Converting to raw ASGI (`async def __call__(self, scope, receive, send)`) allows wrapping `receive` with `limited_receive()`.

2. **Per-item commit for bulk delete:** All-or-nothing transactional bulk delete is simpler but risks orphaning storage objects (already deleted from S3) when the DB commit fails for any item. Per-item commit gives partial success semantics that match what storage operations already do.

3. **5-minute heartbeat stale threshold:** Chosen to give adequate buffer for slow but healthy jobs. The pending-job fallback (created_at-based) handles the transition period before the first heartbeat is written.

4. **Manual Alembic migration:** The local dev environment requires Docker (DB not available without it), so `alembic revision --autogenerate` could not connect. The migration was written manually following the existing convention and will be applied by `alembic upgrade head` at deploy time.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Functionality] Added catch-all Exception handler to bulk delete**
- **Found during:** Task 4
- **Issue:** The plan showed handlers for `DependentVrtError` and `ValueError`, but a DB commit failure would propagate uncaught out of the loop, leaving the session in a bad state for subsequent items
- **Fix:** Added `except Exception as exc` with `await db.rollback()` to catch commit-level failures
- **Files modified:** backend/app/datasets/router.py
- **Commit:** a4395afb

**2. [Rule 1 - Bug] logger variable name mismatch in settings/router.py**
- **Found during:** Task 1 implementation
- **Issue:** Plan pseudocode used `log` but the file defines `logger = structlog.stdlib.get_logger(__name__)`
- **Fix:** Used `logger.exception(...)` to match the module's actual logger variable
- **Files modified:** backend/app/settings/router.py
- **Commit:** af1f0687

## Known Stubs

None. All fixes are complete implementations, not stubs.

## Threat Flags

None. All changes address threats already in the plan's STRIDE register (T-224-08 through T-224-13).

## Self-Check: PASSED

Files verified:
- backend/app/settings/router.py — FOUND, contains `503` and `EMBEDDING_DIMS.set` twice
- backend/app/maps/router.py — FOUND, contains `uuid4`, `temp_key`, `old_thumbnail_uri`
- backend/app/auth/oauth/router.py — FOUND, contains `oauth_failed`, `correlation_id`, `logger.exception`
- backend/app/datasets/router.py — FOUND, contains `db.commit()` inside loop, `db.rollback()` in except blocks
- backend/app/middleware/body_limit.py — FOUND, contains `total_read`, `limited_receive`, two 413 paths
- backend/app/worker.py — FOUND, contains `pg_try_advisory_xact_lock`, `last_heartbeat_at`, `RECOVERY_LOCK_KEY`
- backend/app/jobs/models.py — FOUND, contains `last_heartbeat_at` column
- backend/alembic/versions/2026_04_12_0001-add_last_heartbeat_at_to_ingest_jobs.py — FOUND

Commits verified (all present in git log):
- af1f0687 — Task 1: embedding rebuild 503 + rollback
- 7e9bb77e — Task 2: thumbnail temp-key upload
- c400ef15 — Task 3: OAuth stable error codes
- a4395afb — Task 4: bulk delete per-item commit
- b4ce6694 — Task 5: chunked body limit
- 8f30de55 — Task 6: advisory lock + heartbeat job recovery
