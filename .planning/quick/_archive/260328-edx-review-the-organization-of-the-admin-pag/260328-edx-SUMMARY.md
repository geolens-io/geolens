---
phase: 260328-edx
plan: 01
subsystem: admin
tags: [audit, config-ops, export, connectivity, frontend, backend]
dependency_graph:
  requires: []
  provides:
    - GET /admin/audit-logs/export/{format} (csv|json)
    - validateConnectivity() frontend API function
    - useValidateConnectivity mutation hook
    - ValidateSection component in AdminConfigOpsPage
  affects:
    - frontend/src/pages/admin/AdminConfigOpsPage.tsx
    - backend/app/audit/router.py
tech_stack:
  added: []
  patterns:
    - StreamingResponse with async generator for memory-efficient CSV/JSON export
    - useMutation with onError toast for connectivity validation
key_files:
  created: []
  modified:
    - backend/app/audit/router.py
    - backend/tests/test_audit.py
    - frontend/src/api/config-ops.ts
    - frontend/src/hooks/use-config-ops.ts
    - frontend/src/pages/admin/AdminConfigOpsPage.tsx
    - frontend/src/i18n/locales/en/common.json
decisions:
  - Streaming CSV uses io.StringIO buffer flushed per row to avoid holding full result set in memory
  - JSON export uses prefix comma pattern (no leading comma on first record) for valid array streaming
  - ValidateSection placed between ExportSection and ImportSection per plan specification
  - ServiceRow sub-component handles per-service rendering to keep ValidateSection readable
metrics:
  duration: 15 min
  completed_date: "2026-03-28"
  tasks_completed: 2
  files_modified: 6
---

# Phase 260328-edx Plan 01: Admin Page Fix — Audit Export + Config Validate Summary

**One-liner:** Audit log CSV/JSON streaming export endpoint and config-ops connectivity validation UI wired end-to-end.

## What Was Built

### Task 1: Audit Log Export Endpoint

Added `GET /admin/audit-logs/export/{format}` to `backend/app/audit/router.py`. The endpoint:

- Validates `format` is `csv` or `json`, returns 400 otherwise
- Uses the existing `stream_audit_logs()` async generator for memory-efficient, cursor-based export
- CSV: streams header + data rows using `io.StringIO` buffer flushed per-row; `Content-Type: text/csv`
- JSON: streams a valid JSON array using a prefix-comma pattern; `Content-Type: application/json`
- Both formats set `Content-Disposition: attachment; filename="audit-export-{timestamp}.{ext}"`
- Protected by `require_permission("manage_settings")` (same as list endpoint)

The `ExportSplitButton` component in `AuditLogViewer` (enterprise feature) no longer 404s.

Added two integration tests:
- `test_export_audit_logs_csv` — verifies 200, text/csv content-type, .csv in disposition, header row present
- `test_export_audit_logs_json` — verifies 200, application/json content-type, .json in disposition, body parses as list

All 10 audit tests pass.

### Task 2: Config-Ops Validate Frontend

Wired the existing `POST /config-ops/validate/` endpoint into the Config Operations admin page:

- `frontend/src/api/config-ops.ts`: Added `ServiceProbeResult`, `ConnectivityResult` interfaces and `validateConnectivity()` API function
- `frontend/src/hooks/use-config-ops.ts`: Added `useValidateConnectivity` mutation hook with error toast
- `frontend/src/pages/admin/AdminConfigOpsPage.tsx`: Added `ValidateSection` card with "Run Validation" button; on success renders a table with storage, cache, and OIDC provider rows — each showing name, CheckCircle2/XCircle status icon, latency in ms, and error message if any
- `frontend/src/i18n/locales/en/common.json`: Added `configOps.validate.*` keys and `configOps.validateFailed`

TypeScript compiles cleanly.

## Deviations from Plan

None — plan executed exactly as written.

## Commits

| Task | Commit | Description |
|------|--------|-------------|
| 1 | f70554b7 | feat(260328-edx-01): add audit log export endpoint (CSV + JSON) |
| 2 | 4c1cf83e | feat(260328-edx-01): wire config-ops validate endpoint into admin frontend |

## Self-Check: PASSED

- backend/app/audit/router.py: FOUND
- frontend/src/api/config-ops.ts: FOUND
- frontend/src/pages/admin/AdminConfigOpsPage.tsx: FOUND
- commit f70554b7: FOUND
- commit 4c1cf83e: FOUND
- export_audit_logs function: FOUND
- validateConnectivity function: FOUND
- ValidateSection component: FOUND
