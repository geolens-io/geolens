# Post-Implementation Audit — 2026-04-05 (Backend Admin)

## Scorecard

| Dimension | Grade | Findings | P0 | P1 | P2 | P3 |
|-----------|-------|----------|----|----|----|----|
| KISS & Simplification | B | 8 | 0 | 1 | 3 | 4 |
| Performance | A | 4 | 0 | 0 | 2 | 2 |
| Cleanup & Dead Code | A | 3 | 0 | 0 | 3 | 0 |
| Type Safety | B | 4 | 0 | 0 | 2 | 2 |
| Error Handling & Resilience | B | 5 | 0 | 1 | 2 | 2 |
| **Overall** | **B** | **24** | **0** | **2** | **12** | **10** |

## Executive Summary

Backend audit scoped to `backend/app/`, focused on recent admin audit remediation changes (14 files touched in last 14 days). No P0 issues found. Two P1 issues identified and fixed inline: (1) double-commit transaction pattern where audit logs were in a separate transaction from operations, risking data loss on crash — fixed by changing service layer to flush() instead of commit(); (2) registry dict rebuilt on every settings call — fixed with lazy-cached lookup. 12 P2 items remain as future work (config_ops refactoring, shared API key service). Overall code health is good — the admin audit hardening was well-implemented with correct permission gates and comprehensive audit logging.

## Scope

- **Scope:** `backend/app/` only
- **Focus:** Files changed in admin audit remediation (admin/router.py, admin/service.py, auth/router.py, auth/permissions.py, settings/router.py, settings/schemas.py, datasets/router_data.py, embed_tokens/admin_router.py)
- **Test baseline:** 670 passed, 7 fixture-failures (pre-existing DB setup), 984 collection errors (no test DB)
- **Lint baseline:** 2 unused imports (F401) — fixed to 0

## Fixes Applied During Audit

### P1: Transaction atomicity (RESILIENCE-1 through RESILIENCE-6)
Changed `AdminService` methods from `commit()` to `flush()` so the router controls the single transaction. Now audit logs and operations are atomic — if the server crashes, either both succeed or both roll back.

**Files:** `backend/app/admin/service.py` (6 methods), `backend/app/admin/router.py` (API key create), `backend/app/auth/router.py` (self-service API key create)

### P2: Registry map caching (KISS-6, PERF-1)
Added `_get_registry_map()` with lazy initialization to avoid rebuilding `{cfg.key: cfg}` dict on every settings operation call.

**File:** `backend/app/settings/router.py`

### P2: Unused imports (CLEANUP-1, CLEANUP-2)
Removed `get_current_active_user` from `admin/router.py` and `datasets/router_data.py`.

### P3: Inconsistent log_action call (CLEANUP-3)
Changed positional `db` to keyword `session=db` in share token revoke audit call for consistency.

## Remaining Items (Not Fixed)

| Priority | Finding | File | Fix | Effort |
|----------|---------|------|-----|--------|
| P2 | [KISS-4] Duplicate API key creation logic between admin and auth routers | admin/router.py, auth/router.py | Extract shared `create_api_key_for_user()` service | 30m |
| P2 | [KISS-7] config_ops import_config 155 lines, 6 levels nesting | config_ops/service.py | Extract `_apply_oauth_providers()` helper | 45m |
| P2 | [KISS-8] config_ops dry_run_import 87 lines, repetitive diff | config_ops/service.py | Extract `_diff_settings()` and `_diff_providers()` | 30m |
| P2 | [PERF-2] PersistentConfig.set() SELECT + UPSERT pattern | persistent_config.py | Use INSERT ON CONFLICT DO UPDATE | 30m |
| P2 | [PERF-3] /admin/users/names/ unbounded list | admin/router.py:131 | Add limit param or cap at 1000 | 10m |
| P2 | [TYPE-1] ChangePasswordRequest defined inline | auth/router.py:359 | Move to auth/schemas.py | 5m |
| P2 | [TYPE-2] Hardcoded status codes 201/204 in settings router | settings/router.py | Use status.HTTP_* constants | 5m |
| P3 | [KISS-1] IP extraction pattern repeated 16x | multiple routers | Extract `get_client_ip(request)` helper | 15m |
| P3 | [KISS-2] list_admin_jobs 58 lines with inline query building | admin/router.py:390 | Move to AdminService | 20m |
| P3 | [PERF-4] pgvector HNSW ef_search not set at query time | search/service.py | Add SET hnsw.ef_search before queries | 15m |
| P3 | [TYPE-3] Boolean input not rejected in int validators | settings/schemas.py | Add `isinstance(v, bool)` guard | 10m |
| P3 | [TYPE-4] Self-role-change uses 400 instead of 422 | admin/router.py:170 | Change to HTTP_422 | 2m |

## Static Analysis

| Check | Before | After |
|-------|--------|-------|
| Ruff F401 (unused imports) | 2 | 0 |
| Ruff F841 (unused variables) | 0 | 0 |

## Explicitly NOT Flagged

- Admin route handler length (35-45 lines) — acceptable for handlers with audit logging; the audit trail is more valuable than shorter handlers
- `get_catalog_stats()` in service.py still commits internally — it's a read-only operation, commit is harmless
- GDAL subprocess calls — documented pattern in CLAUDE.md
- PersistentConfig caching with 30s TTL — appropriate for settings that rarely change
