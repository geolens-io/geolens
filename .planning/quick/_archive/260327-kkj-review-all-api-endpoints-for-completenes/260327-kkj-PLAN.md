---
phase: 260327-kkj
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - .planning/quick/260327-kkj-review-all-api-endpoints-for-completenes/API-AUDIT-REPORT.md
autonomous: true
requirements: [AUDIT-ALL]

must_haves:
  truths:
    - "Every router file in backend/app/*/router.py plus auth/oauth/router.py and embed_tokens/admin_router.py is covered in the report"
    - "Each finding has severity, affected file with line number, description, and a specific fix proposal"
    - "Findings from RESEARCH.md are verified against actual source code before inclusion"
    - "Report includes an endpoint inventory table with auth pattern per router"
  artifacts:
    - path: ".planning/quick/260327-kkj-review-all-api-endpoints-for-completenes/API-AUDIT-REPORT.md"
      provides: "Structured audit report covering all 23 routers"
      min_lines: 200
  key_links: []
---

<objective>
Produce a comprehensive API audit report covering all 23 routers (~163 endpoints) in the GeoLens backend.

Purpose: Identify correctness, security, completeness, performance, and cleanup issues with actionable fix proposals for each finding.
Output: `.planning/quick/260327-kkj-review-all-api-endpoints-for-completenes/API-AUDIT-REPORT.md`
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/quick/260327-kkj-review-all-api-endpoints-for-completenes/260327-kkj-CONTEXT.md
@.planning/quick/260327-kkj-review-all-api-endpoints-for-completenes/260327-kkj-RESEARCH.md
</context>

<tasks>

<task type="auto">
  <name>Task 1: Verify research findings and audit all routers</name>
  <files>
    backend/app/admin/router.py
    backend/app/ai/router.py
    backend/app/audit/router.py
    backend/app/auth/router.py
    backend/app/auth/oauth/router.py
    backend/app/collections/router.py
    backend/app/config_ops/router.py
    backend/app/datasets/router.py
    backend/app/embed_tokens/router.py
    backend/app/embed_tokens/admin_router.py
    backend/app/export/router.py
    backend/app/features/router.py
    backend/app/ingest/router.py
    backend/app/jobs/router.py
    backend/app/layers/router.py
    backend/app/maps/router.py
    backend/app/ogc/router.py
    backend/app/records/router.py
    backend/app/search/router.py
    backend/app/services/router.py
    backend/app/settings/router.py
    backend/app/stac/router.py
    backend/app/tiles/router.py
    backend/app/main.py
    backend/app/auth/dependencies.py
  </files>
  <action>
Read every router file listed above. For each router, examine:

1. **Auth pattern**: Which dependency is used (get_optional_user, get_current_active_user, require_permission, require_role)? Is it appropriate for the endpoint's purpose?
2. **Input validation**: Are query params and body fields validated with Pydantic models or Query constraints?
3. **Response models**: Does the endpoint declare a response_model or return untyped dict?
4. **Error handling**: Are errors caught and returned as proper HTTPException with status codes?
5. **Trailing slashes**: Record which endpoints have trailing slashes and which do not.
6. **N+1 queries**: Look for loops that make individual DB calls per item.
7. **Code duplication**: Note functions duplicated across routers.
8. **Dead code**: Functions defined but unused or superseded by shared utilities.

Verify each of the 22 findings from RESEARCH.md (C1-C5, H1-H7, M1-M5, L1-L7) against the actual source code:
- Confirm the issue exists at the cited line numbers (they may have shifted).
- Extract the actual code snippet showing the problem.
- Confirm the proposed fix is correct for the current code.
- If a finding is wrong or already fixed, note that.

Additionally, look for issues the research may have missed:
- Endpoints with no error handling for service-layer exceptions.
- Missing audit logging on mutation endpoints.
- Inconsistent pagination patterns (some use skip/limit, some use page/per_page, some have none).
- Any endpoint that accepts user input and passes it unsanitized to SQL or shell commands.
- Endpoints returning 200 on creation (should be 201).

Collect all findings with: severity, finding ID, description, affected file(s) with line numbers, code snippet showing the issue, and specific fix proposal with code.
  </action>
  <verify>
    <automated>echo "Verify: all 23 router files read" && ls backend/app/admin/router.py backend/app/ai/router.py backend/app/audit/router.py backend/app/auth/router.py backend/app/auth/oauth/router.py backend/app/collections/router.py backend/app/config_ops/router.py backend/app/datasets/router.py backend/app/embed_tokens/router.py backend/app/embed_tokens/admin_router.py backend/app/export/router.py backend/app/features/router.py backend/app/ingest/router.py backend/app/jobs/router.py backend/app/layers/router.py backend/app/maps/router.py backend/app/ogc/router.py backend/app/records/router.py backend/app/search/router.py backend/app/services/router.py backend/app/settings/router.py backend/app/stac/router.py backend/app/tiles/router.py backend/app/main.py > /dev/null 2>&1 && echo "All router files exist"</automated>
  </verify>
  <done>All 23 routers reviewed. Every RESEARCH.md finding verified or corrected. Additional findings identified. All findings have file paths, line numbers, code snippets, and fix proposals.</done>
</task>

<task type="auto">
  <name>Task 2: Write the structured audit report</name>
  <files>.planning/quick/260327-kkj-review-all-api-endpoints-for-completenes/API-AUDIT-REPORT.md</files>
  <action>
Write the audit report to `.planning/quick/260327-kkj-review-all-api-endpoints-for-completenes/API-AUDIT-REPORT.md` using this structure:

```
# GeoLens API Endpoint Audit Report

**Date:** 2026-03-27
**Scope:** All 23 routers, ~163 endpoints
**Backend:** FastAPI (Python)

## Executive Summary

- Total routers reviewed: 23
- Total endpoints: ~163
- Critical findings: N
- High findings: N
- Medium findings: N
- Low findings: N
- Suggested enhancements: N

{2-3 sentence overall assessment}

## Findings

### CRITICAL: Security & Correctness

#### C1. {Title}
- **Severity:** CRITICAL
- **File:** `{path}:{line}`
- **Description:** {what's wrong and why it matters}
- **Current code:**
  ```python
  {actual code snippet}
  ```
- **Fix:**
  ```python
  {proposed fix}
  ```

{Repeat for each Critical finding}

### HIGH: Completeness & Consistency

{Same format for each High finding}

### MEDIUM: Performance & Optimization

{Same format for each Medium finding}

### LOW: Cleanup & Simplification

{Same format for each Low finding}

## Suggested Enhancements

{Numbered list of improvements that are not bugs -- rate limiting, bulk operations, etc.}

## Endpoint Inventory

| # | Router | Prefix | Endpoints | Lines | Auth Pattern | Notes |
|---|--------|--------|-----------|-------|--------------|-------|

## Cross-Cutting Patterns

### What's Working Well
{Bullet list of good patterns observed}

### Auth Dependency Usage
| Dependency | Purpose | Used By |
|------------|---------|---------|

## Methodology
{Brief note on what was checked and how}
```

Ensure every finding from Task 1 is included. Group by severity. Within each severity group, order by impact. Each finding MUST have: ID, title, severity, file with line number, description, current code snippet, and proposed fix with code.

For the endpoint inventory table, list every router with: prefix, endpoint count, line count, primary auth pattern, and any notable concerns.

Do NOT include findings that were determined to be false positives during verification in Task 1. Note any RESEARCH.md findings that turned out to be already fixed or incorrect in a "Verification Notes" section at the end.
  </action>
  <verify>
    <automated>test -f ".planning/quick/260327-kkj-review-all-api-endpoints-for-completenes/API-AUDIT-REPORT.md" && wc -l ".planning/quick/260327-kkj-review-all-api-endpoints-for-completenes/API-AUDIT-REPORT.md" | awk '{if ($1 >= 200) print "PASS: " $1 " lines"; else print "FAIL: only " $1 " lines"}'</automated>
  </verify>
  <done>API-AUDIT-REPORT.md exists with 200+ lines. All findings organized by severity with code snippets and fix proposals. Endpoint inventory covers all 23 routers. No false positives included.</done>
</task>

</tasks>

<verification>
- Report file exists at the expected path
- All 23 routers appear in the endpoint inventory table
- Every finding has severity, file path, line number, code snippet, and fix proposal
- CRITICAL findings are verified against actual source code (not just copied from research)
- No finding references a line number or code pattern that doesn't exist in the current codebase
</verification>

<success_criteria>
- Comprehensive audit report covering all 23 routers and ~163 endpoints
- Findings grouped by CRITICAL / HIGH / MEDIUM / LOW severity
- Each finding includes specific file paths, line numbers, current code, and proposed fix
- Endpoint inventory table with auth patterns per router
- Report is actionable: a developer can take any finding and implement the fix without further investigation
</success_criteria>

<output>
After completion, the report lives at:
`.planning/quick/260327-kkj-review-all-api-endpoints-for-completenes/API-AUDIT-REPORT.md`

No SUMMARY needed for quick tasks.
</output>
