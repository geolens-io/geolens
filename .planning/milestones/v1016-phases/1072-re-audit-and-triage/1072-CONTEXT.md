# Phase 1072: Re-audit & Triage - Context

**Gathered:** 2026-05-21
**Status:** Ready for planning
**Mode:** Auto-generated (discuss skipped via workflow.skip_discuss)

<domain>
## Phase Boundary

Fresh `/sec-audit` and `/ingest-audit` runs against the v1015 ship state produce captured audit reports AND a triage doc that maps every new finding to a severity tier (HIGH/MEDIUM/LOW/INFO) and assigns it to Phase 1073 (HIGH+MEDIUM) or Phase 1074 (LOW+INFO) — or defers to a pending-todo file if scope warrants.

**In scope (3 reqs):**
- **AUDIT-01:** `/sec-audit` runs against current main; report captured at `.planning/audits/SECURITY-AUDIT-2026-05-21.md`
- **AUDIT-02:** `/ingest-audit` runs against current main; report captured at `.planning/audits/INGEST-AUDIT-2026-05-21.md`
- **AUDIT-03:** Triage classification doc at `.planning/audits/TRIAGE-2026-05-21.md` mapping each finding to severity + target phase

**Out of scope:**
- Remediating any findings (Phase 1073 + 1074)
- Re-running audits after fixes (Phase 1074 close-gate verifies)

</domain>

<decisions>
## Implementation Decisions

### Locked Decisions

- **Run order:** `/sec-audit` first (broader surface), then `/ingest-audit` (narrower). Both run unconditionally.
- **Capture location:** All audit artifacts under `.planning/audits/` (NOT `.planning/phases/1072-*/`) so they're milestone-scoped and discoverable across phases.
- **Date suffix:** Filenames include `-2026-05-21` so a future re-audit doesn't clobber.
- **Triage doc shape:** Following v1014 pattern — table of findings with columns: ID, Severity, Source (sec-audit/ingest-audit), Brief Description, Target Phase, Notes.
- **Severity mapping to phases:** HIGH+MEDIUM → Phase 1073; LOW+INFO → Phase 1074 batch close OR deferred to pending-todo if scope > 30 min.

### Claude's Discretion

- Audit skill invocation parameters (depth, scope) — use skill defaults
- Triage finding-ID format — match audit skill's native finding IDs (e.g., `SEC-S01`, `IA-P0-01`, etc.)
- Whether to split Phase 1073 into sub-phases — decide at end of Phase 1072 based on total finding count

</decisions>

<code_context>
## Existing Code Insights

Audits inspect the current shipped state of:
- Backend modules (auth, catalog, datasets, export, ingest, raster, search, stac, ogc, oauth, saml)
- Frontend (less coverage from sec-audit; ingest-audit doesn't touch frontend)
- Infrastructure (docker, nginx, env handling)

Phase 1071 just landed 11 code/config changes. The audits will see the post-1071 state, which is the desired baseline.

</code_context>

<specifics>
## Specific Ideas

- Both audit skills are installed and listed in the system skill catalog
- v1014 ran `/sec-audit` 2026-05-19 and closed 27 findings. v1015 ran `/ingest-audit` 2026-05-19 and closed 9 findings. Two days of code changes since then — expect fewer net findings.
- v1071's KNOWN closures may have already addressed items the auditors would otherwise flag (e.g., KNOWN-10 closes an AST-level export bypass; KNOWN-13 closes a known CVE).

</specifics>

<deferred>
## Deferred Ideas

None — phase scope is tight (3 reqs, run + capture + classify).
</deferred>
