# Phase 208: Audit Log Export - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-03-26
**Phase:** 208-audit-log-export
**Areas discussed:** Export trigger UX, File format details, Enterprise gating scope, Streaming & limits

---

## Export Trigger UX

| Option | Description | Selected |
|--------|-------------|----------|
| Toolbar export button | Add Download/Export button to existing AuditLogViewer header bar. Current filters auto-apply. | |
| Export dropdown with format choice | Dropdown showing CSV and JSON as separate actions. | |
| Export dialog with preview | Modal dialog with filter summary, format picker, row count estimate. | |

**User's choice:** Toolbar export button
**Notes:** None

### Follow-up: Format selection UX

| Option | Description | Selected |
|--------|-------------|----------|
| Split button: CSV default + JSON option | Primary click exports CSV. Dropdown arrow reveals JSON alternate. | ✓ |
| Single button, format in dropdown | Button labeled 'Export' with dropdown for both formats. | |
| You decide | Claude picks best approach. | |

**User's choice:** Split button: CSV default + JSON option
**Notes:** None

---

## File Format Details

### Details column handling

| Option | Description | Selected |
|--------|-------------|----------|
| Raw JSON string column | CSV gets 'details' column with JSON stringified. JSON export keeps nested object. | ✓ |
| Flattened top-level keys | Extract common keys as separate columns. More spreadsheet-friendly but lossy. | |
| Both: flat common + raw fallback | Flatten known keys AND include raw details. Wider CSV. | |

**User's choice:** Raw JSON string column
**Notes:** None

### JSON export format

| Option | Description | Selected |
|--------|-------------|----------|
| JSON array | Standard [{...}, {...}] array format. | ✓ |
| NDJSON (newline-delimited) | One JSON object per line. True streaming-friendly. | |

**User's choice:** JSON array
**Notes:** None

---

## Enterprise Gating Scope

| Option | Description | Selected |
|--------|-------------|----------|
| View for all, export enterprise-only | Community admins keep viewer. Export button only in enterprise. | ✓ |
| Entire audit page enterprise-only | Both viewing and exporting gated. Community loses audit visibility. | |
| Export visible but disabled in community | Button shows but disabled with Enterprise tooltip. | |

**User's choice:** View for all, export enterprise-only
**Notes:** None

---

## Streaming & Limits

### Row limits

| Option | Description | Selected |
|--------|-------------|----------|
| No hard limit, streaming handles it | StreamingResponse writes from DB cursor. No memory ceiling. | ✓ |
| Soft limit with warning | Warning if >100K rows. Still allows export. | |
| Hard cap at 100K rows | Enforce max 100K. Simple but may frustrate compliance. | |

**User's choice:** No hard limit, streaming handles it
**Notes:** None

### Download experience

| Option | Description | Selected |
|--------|-------------|----------|
| Direct browser download | StreamingResponse with Content-Disposition. Native download progress. | ✓ |
| Async job with notification | Background job, notification when ready. More infrastructure. | |

**User's choice:** Direct browser download
**Notes:** None

---

## Claude's Discretion

- CSV column ordering
- Download filename format
- Whether to add resource_type filter to export

## Deferred Ideas

None
