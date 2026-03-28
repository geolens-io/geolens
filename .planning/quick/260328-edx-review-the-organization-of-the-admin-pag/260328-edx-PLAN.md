---
phase: 260328-edx
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - backend/app/audit/router.py
  - backend/tests/test_audit.py
  - frontend/src/api/config-ops.ts
  - frontend/src/hooks/use-config-ops.ts
  - frontend/src/pages/admin/AdminConfigOpsPage.tsx
  - frontend/src/i18n/locales/en/common.json
autonomous: true
requirements: [ADMIN-REVIEW-01, ADMIN-REVIEW-02]

must_haves:
  truths:
    - "Enterprise audit log export button downloads a CSV file with correct audit data"
    - "Enterprise audit log export button downloads a JSON file with correct audit data"
    - "Config Operations page has a Validate Connectivity section showing service health"
  artifacts:
    - path: "backend/app/audit/router.py"
      provides: "GET /admin/audit-logs/export/{format} endpoint"
      contains: "export_audit_logs"
    - path: "frontend/src/api/config-ops.ts"
      provides: "validateConnectivity() API function"
      contains: "validateConnectivity"
    - path: "frontend/src/pages/admin/AdminConfigOpsPage.tsx"
      provides: "ValidateSection component"
      contains: "ValidateSection"
  key_links:
    - from: "frontend/src/components/admin/ExportSplitButton.tsx"
      to: "/admin/audit-logs/export/{format}"
      via: "exportAuditLogs() in api/admin.ts"
      pattern: "audit-logs/export"
    - from: "frontend/src/pages/admin/AdminConfigOpsPage.tsx"
      to: "/config-ops/validate/"
      via: "validateConnectivity() in api/config-ops.ts"
      pattern: "config-ops/validate"
---

<objective>
Fix two issues found during admin page organization review: (1) implement the missing backend endpoint for audit log export that the frontend already calls, and (2) wire the existing config-ops validate endpoint into the frontend.

Purpose: The audit export button currently 404s at runtime for enterprise users. The validate endpoint exists unused.
Output: Working audit export (CSV + JSON) and config connectivity validation UI.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@frontend/src/api/admin.ts (exportAuditLogs function at line 199 — calls GET /admin/audit-logs/export/{format})
@frontend/src/components/admin/ExportSplitButton.tsx (renders export button, handles blob download)
@frontend/src/components/admin/AuditLogViewer.tsx (conditionally renders ExportSplitButton when isEnterprise)
@backend/app/audit/router.py (only has list endpoint, missing export)
@backend/app/audit/service.py (stream_audit_logs already exists — use it)
@backend/app/audit/models.py (AuditLog model with fields: id, user_id, action, resource_type, resource_id, details, ip_address, created_at, user relationship)
@backend/app/audit/schemas.py (AuditLogResponse schema)
@backend/app/config_ops/router.py (POST /config-ops/validate/ exists, returns ConnectivityResult)
@backend/app/config_ops/schemas.py (ConnectivityResult, ServiceProbeResult schemas)
@frontend/src/api/config-ops.ts (missing validateConnectivity function)
@frontend/src/hooks/use-config-ops.ts (missing useValidateConnectivity hook)
@frontend/src/pages/admin/AdminConfigOpsPage.tsx (missing ValidateSection)

<interfaces>
<!-- Backend service layer already provides streaming export -->
From backend/app/audit/service.py:
```python
async def stream_audit_logs(
    session: AsyncSession,
    *,
    action: str | None = None,
    resource_type: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    search: str | None = None,
) -> AsyncIterator[AuditLog]:
```

From backend/app/config_ops/schemas.py:
```python
class ServiceProbeResult(BaseModel):
    name: str
    status: Literal["ok", "error"]
    latency_ms: float
    error: str | None = None

class ConnectivityResult(BaseModel):
    storage: ServiceProbeResult
    cache: ServiceProbeResult
    oidc_providers: dict[str, ServiceProbeResult]
```

From frontend/src/api/admin.ts:
```typescript
export async function exportAuditLogs(
  format: 'csv' | 'json',
  filters: { action?: string; date_from?: string; date_to?: string; search?: string },
): Promise<Blob>
```
</interfaces>
</context>

<tasks>

<task type="auto">
  <name>Task 1: Add audit log export endpoint to backend</name>
  <files>backend/app/audit/router.py, backend/tests/test_audit.py</files>
  <action>
Add `GET /admin/audit-logs/export/{format}` endpoint to `backend/app/audit/router.py` that the frontend already calls.

The endpoint must:
- Accept `format` as a path parameter, validated to be `csv` or `json`
- Accept the same query filters as the list endpoint: `action`, `date_from`, `date_to`, `search` (all optional)
- Use the existing `stream_audit_logs()` from `app.audit.service` (it already yields AuditLog rows from a server-side cursor)
- Require `manage_settings` permission (same as list endpoint)
- Return a `StreamingResponse` (from `starlette.responses`)
- For CSV format: set `Content-Type: text/csv`, `Content-Disposition: attachment; filename="audit-export-{timestamp}.csv"`, write header row then data rows with fields: timestamp, username, action, resource_type, resource_id, ip_address, details (JSON-serialized)
- For JSON format: set `Content-Type: application/json`, `Content-Disposition: attachment; filename="audit-export-{timestamp}.json"`, stream a JSON array of objects with same fields
- For invalid format values, return 400

Import `StreamingResponse` from `starlette.responses` (already used in `datasets/router_export.py` as a pattern reference). Import `io`, `csv`, `json` from stdlib.

Add two integration tests to `backend/tests/test_audit.py`:
- `test_export_audit_logs_csv`: POST an audit-producing action first (e.g. view a dataset), then GET `/admin/audit-logs/export/csv` with admin auth, assert 200, assert Content-Type is text/csv, assert Content-Disposition contains .csv, assert response body contains CSV header row
- `test_export_audit_logs_json`: Same setup, GET with format=json, assert 200, Content-Type is application/json, response parses as a JSON list
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens && docker compose exec -T api python -m pytest backend/tests/test_audit.py -x -q --tb=short 2>&1 | tail -20</automated>
  </verify>
  <done>GET /admin/audit-logs/export/csv and /admin/audit-logs/export/json return streaming downloads with correct Content-Type and Content-Disposition headers. Frontend ExportSplitButton no longer 404s.</done>
</task>

<task type="auto">
  <name>Task 2: Wire config-ops validate endpoint into frontend</name>
  <files>frontend/src/api/config-ops.ts, frontend/src/hooks/use-config-ops.ts, frontend/src/pages/admin/AdminConfigOpsPage.tsx, frontend/src/i18n/locales/en/common.json</files>
  <action>
Wire the existing `POST /config-ops/validate/` backend endpoint into the Config Operations admin page.

1. **frontend/src/api/config-ops.ts** — Add types and API function:
   ```typescript
   export interface ServiceProbeResult {
     name: string;
     status: 'ok' | 'error';
     latency_ms: number;
     error: string | null;
   }

   export interface ConnectivityResult {
     storage: ServiceProbeResult;
     cache: ServiceProbeResult;
     oidc_providers: Record<string, ServiceProbeResult>;
   }

   export async function validateConnectivity(): Promise<ConnectivityResult> {
     return apiFetch<ConnectivityResult>('/config-ops/validate/', { method: 'POST' });
   }
   ```

2. **frontend/src/hooks/use-config-ops.ts** — Add mutation hook:
   ```typescript
   export function useValidateConnectivity() {
     return useMutation<ConnectivityResult, Error>({
       mutationFn: validateConnectivity,
       onError: (err: Error) => {
         toast.error(err.message || i18n.t('configOps.validateFailed'));
       },
     });
   }
   ```
   Import `validateConnectivity` and `ConnectivityResult` from the API module.

3. **frontend/src/pages/admin/AdminConfigOpsPage.tsx** — Add a `ValidateSection` component between ExportSection and ImportSection. It should:
   - Show a Card with a ShieldCheck icon (from lucide-react), title "Validate Connectivity", description "Test connectivity to storage, cache, and OIDC providers."
   - Have a "Run Validation" button that triggers the mutation
   - Show a Loader2 spinner while pending
   - On success, render results in a simple list/table: for each service (storage, cache, plus each OIDC provider), show the name, a CheckCircle2 (green) or XCircle (red) status icon, latency in ms, and error message if any
   - Use existing Card/Badge/Table components consistent with the ExportSection and ImportSection style
   - Import `useValidateConnectivity` from hooks, `ShieldCheck`, `XCircle` from lucide-react

4. **frontend/src/i18n/locales/en/common.json** — Add i18n keys under `configOps`:
   - `configOps.validate.title`: "Validate Connectivity"
   - `configOps.validate.description`: "Test connectivity to storage, cache, and OIDC providers."
   - `configOps.validate.button`: "Run Validation"
   - `configOps.validate.statusOk`: "Connected"
   - `configOps.validate.statusError`: "Failed"
   - `configOps.validate.latency`: "{{ms}}ms"
   - `configOps.validate.noOidc`: "No OIDC providers configured"
   - `configOps.validateFailed`: "Connectivity validation failed"
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens && npx tsc --noEmit --project frontend/tsconfig.json 2>&1 | tail -20</automated>
  </verify>
  <done>Config Operations page shows a Validate Connectivity section between Export and Import. Clicking "Run Validation" calls POST /config-ops/validate/ and displays per-service status with pass/fail icons and latency.</done>
</task>

</tasks>

<verification>
- `GET /admin/audit-logs/export/csv` returns 200 with text/csv content
- `GET /admin/audit-logs/export/json` returns 200 with application/json content
- Frontend TypeScript compiles cleanly
- Config Operations page renders ValidateSection with button
- ExportSplitButton in AuditLogViewer no longer produces 404
</verification>

<success_criteria>
- Audit log export: enterprise users can download CSV and JSON audit exports via the ExportSplitButton without errors
- Config validation: admins see a "Validate Connectivity" card on the Config Operations page that probes storage, cache, and OIDC provider health
- No TypeScript compilation errors
- Backend audit export tests pass
</success_criteria>

<output>
After completion, create `.planning/quick/260328-edx-review-the-organization-of-the-admin-pag/260328-edx-SUMMARY.md`
</output>
