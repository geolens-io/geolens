# Phase 208: Audit Log Export - Context

**Gathered:** 2026-03-26
**Status:** Ready for planning

<domain>
## Phase Boundary

Admins can download audit log data as CSV or JSON files for compliance evidence. The existing audit log viewer (AuditLogViewer.tsx) gains an export capability. The backend adds streaming export endpoints. Enterprise gating applies to export only — the viewer remains available to all admins.

</domain>

<decisions>
## Implementation Decisions

### Export Trigger UX
- **D-01:** Split button in the AuditLogViewer toolbar header. Primary click exports CSV (most common for compliance). Small dropdown arrow reveals JSON as alternate format.
- **D-02:** Current filters (date range, action type, search query) auto-apply to the export — what you see is what you export.

### File Format Details
- **D-03:** CSV includes all AuditLog columns. The JSONB `details` column is serialized as a raw JSON string — no flattening of nested keys.
- **D-04:** JSON export uses standard `[{...}, {...}]` array format, not NDJSON.

### Enterprise Gating Scope
- **D-05:** Community edition admins retain full audit log viewing. Only the export button is enterprise-gated (hidden when not enterprise). Consistent with branding toggle pattern from Phase 207.
- **D-06:** Backend export endpoints use `require_enterprise` dependency. Frontend hides export button when `useEdition()` reports non-enterprise.

### Streaming & Limits
- **D-07:** No hard row limit on exports. StreamingResponse writes rows from a DB cursor. Date range filters naturally scope size.
- **D-08:** Direct browser download via StreamingResponse with Content-Disposition header. No async job queue or custom progress UI — browser native download progress is sufficient.

### Claude's Discretion
- Column ordering in CSV (sensible default: timestamp, username, action, resource_type, resource_id, ip_address, details)
- Filename format for downloads (e.g., `audit-export-2026-03-26.csv`)
- Whether to add a resource_type filter to the export (currently only action filter exists in viewer)

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Audit Infrastructure
- `backend/app/audit/models.py` — AuditLog SQLAlchemy model (schema: catalog.audit_logs)
- `backend/app/audit/router.py` — Existing GET /admin/audit-logs endpoint with filter params
- `backend/app/audit/service.py` — query_audit_logs service function
- `backend/app/audit/schemas.py` — AuditLogResponse, AuditLogListResponse Pydantic schemas

### Frontend Audit UI
- `frontend/src/components/admin/AuditLogViewer.tsx` — Full admin viewer with filters, pagination, expandable details
- `frontend/src/pages/admin/AdminAuditPage.tsx` — Admin audit page wrapper
- `frontend/src/hooks/use-admin.ts` — useAuditLogs hook
- `frontend/src/api/admin.ts` — Admin API client

### Enterprise Gating Pattern
- `backend/app/extensions/guards.py` — require_enterprise dependency (proven in Phase 207)
- `frontend/src/hooks/use-settings.ts` — useEdition() hook for frontend gating

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `AuditLogViewer.tsx` — Already has date range, action, and search filters. Export button goes in the CardHeader alongside search.
- `useEdition()` hook — Frontend enterprise detection for hiding export button in community.
- `require_enterprise` FastAPI dependency — Backend gating for export endpoints.
- `StreamingResponse` from FastAPI/Starlette — Standard streaming pattern for large downloads.

### Established Patterns
- AuditLog query uses SQLAlchemy async with `selectinload` for user relationship. Export query can reuse `query_audit_logs` service or build a streaming cursor variant.
- Enterprise gating: hidden UI + 404 backend (not 403) — established in Phase 207.
- Split button pattern: not yet in codebase, but Radix DropdownMenu + Button composition is standard.

### Integration Points
- New export endpoints added to `backend/app/audit/router.py` (GET /admin/audit-logs/export/csv, GET /admin/audit-logs/export/json)
- Export button added to `AuditLogViewer.tsx` CardHeader
- i18n keys in admin.json for export labels

</code_context>

<specifics>
## Specific Ideas

No specific requirements — open to standard approaches.

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 208-audit-log-export*
*Context gathered: 2026-03-26*
