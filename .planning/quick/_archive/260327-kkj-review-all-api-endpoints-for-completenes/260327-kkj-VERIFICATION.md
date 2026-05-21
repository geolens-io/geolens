---
phase: 260327-kkj
verified: 2026-03-27T00:00:00Z
status: gaps_found
score: 3/4 must-haves verified
gaps:
  - truth: "Every router file in backend/app/*/router.py plus auth/oauth/router.py and embed_tokens/admin_router.py is covered in the report"
    status: failed
    reason: "backend/app/stac/router.py exists (545 lines, 6 endpoints, registered in main.py at line 390) and was audited in RESEARCH.md, but the report's Verification Notes falsely declare it absent ('STAC router findings are INVALID — backend/app/stac/ module does not exist'). Two valid STAC findings were dropped as false positives when they are real."
    artifacts:
      - path: "backend/app/stac/router.py"
        issue: "Exists with 6 endpoints (lines 181-410). GET /stac/collections and GET /stac/collections/{collection_id} have no response_model. N+1 extent queries in GET /stac/collections (raw SQL inside per-collection loop at lines 222-259). Neither finding is in the report."
      - path: ".planning/quick/260327-kkj-review-all-api-endpoints-for-completenes/API-AUDIT-REPORT.md"
        issue: "Line 4 states '22 routers (STAC router removed in current codebase)'. Line 599 states 'backend/app/stac/ module does not exist in the current codebase. No stac_router is registered in main.py.' Both claims are false."
    missing:
      - "Add stac/router.py as router #23 in the endpoint inventory table"
      - "Restore STAC H5 finding: GET /stac/collections and GET /stac/collections/{collection_id} return untyped dicts with no response_model"
      - "Restore STAC M2 finding: N+1 extent queries per collection in GET /stac/collections loop (lines 222-259)"
      - "Update executive summary counts: routers = 23, endpoint count += 6"
      - "Correct the false invalidation note in Verification Notes section"
---

# Quick Task 260327-kkj: API Endpoint Audit — Verification Report

**Task Goal:** Review all API endpoints for completeness, correctness and optimizations. Identify gaps, issues, concerns, suggested enhancements, and cleanup opportunities across all 22 routers. Produce a single structured audit report with findings grouped by severity, including specific fix proposals for each finding.
**Verified:** 2026-03-27
**Status:** gaps_found — one must-have fails due to the STAC router being missed
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|---------|
| 1 | Every router file covered in the report | FAILED | `stac/router.py` (545 lines, 6 endpoints, registered in main.py:390) is falsely declared absent. Two valid STAC findings dropped. |
| 2 | Each finding has severity, affected file with line number, description, and a specific fix proposal | VERIFIED | All 25 findings (C1-C2, H1-H7, M1-M4, L1-L6, 6 enhancements) include severity, file+line, description, current code snippet, and fix with code. |
| 3 | Findings from RESEARCH.md verified against actual source code before inclusion | VERIFIED (with caveat) | 22 of 26 RESEARCH.md findings verified; 4 correctly invalidated (jobs C1, double require_permission C4, httpx M5, STAC). However, the STAC invalidation is itself incorrect — those findings are real. The other 21 verifications are accurate. |
| 4 | Report includes an endpoint inventory table with auth pattern per router | VERIFIED | Table at lines 517-543 covers all 22 audited routers with prefix, endpoint count, line count, and auth pattern. Misses the 23rd (STAC) router. |

**Score:** 3/4 truths verified (the first truth fails; the fourth is partially correct)

---

## Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `API-AUDIT-REPORT.md` | Structured audit report covering all 23 routers, 200+ lines | PARTIAL | 599 lines. Well-structured with all required sections. Covers 22/23 routers. STAC router missed due to incorrect invalidation. |

---

## Spot-Check Results: Findings Validated Against Source

Five findings were manually verified against source code:

| Finding | File + Line | Verified | Notes |
|---------|-------------|---------|-------|
| C1: Share token GET missing ownership check | `maps/router.py:479` | CONFIRMED | `get_map_share_token_endpoint` calls `get_active_share_token` with no prior `check_map_ownership`. All other share endpoints (POST/PATCH/DELETE) do call it. Real vulnerability. |
| C2: embed_tokens admin uses `require_role` | `embed_tokens/admin_router.py:40,65` | CONFIRMED | Both endpoints use `require_role("admin")`. Every other admin surface uses `require_permission(...)`. |
| H1: `_extent_to_bbox` duplicated 4x | `datasets/router.py:158`, `collections/router.py:50`, `ogc/router.py:39`, `maps/router.py:63` | CONFIRMED | Identical 10-line function in all four files. |
| M3: Missing cache invalidation after PATCH /datasets/{id} | `datasets/router.py:1141` | CONFIRMED | `db.commit()` at line 1141 with no subsequent `invalidate_catalog_cache()`. DELETE endpoint at line 1195 correctly calls it. |
| L2: Double-await pattern in config_ops | `config_ops/router.py:43-44` | CONFIRMED | `result = export_config(db)` then `data = await result` — should be `data = await export_config(db)`. |
| L6: Stale version string | `main.py:331` | CONFIRMED | `version="2.6.0"` (report says line 314 — minor line number shift, finding accurate). |
| STAC H5: Missing response_model | `stac/router.py:209,270` | CONFIRMED REAL — report says INVALID | `@stac_router.get("/collections")` and `@stac_router.get("/collections/{collection_id}")` have no `response_model`. Returns raw `dict`. |
| STAC M2: N+1 extent queries | `stac/router.py:222-259` | CONFIRMED REAL — report says INVALID | Per-collection raw SQL extent query inside a Python loop over all collections. |

---

## STAC Router: The Critical Gap

The report's Verification Notes state:

> "STAC router findings (M2, H5 STAC entries) are INVALID — `backend/app/stac/` module does not exist in the current codebase. STAC has been removed or not yet implemented. No `stac_router` is registered in `main.py`."

All three claims are false:

- `backend/app/stac/router.py` exists at 545 lines with 6 endpoints.
- `stac_router` is imported and registered in `main.py` at lines 51 and 390.
- The router has been substantively implemented (full landing page, conformance, collections, items, search).

The STAC router was in the PLAN's file list (`backend/app/stac/router.py` listed in Task 1 files). The RESEARCH.md had valid findings for it. The inventory table in the RESEARCH.md shows "23 | stac | /stac | 6 | none (public)" as the last row. Despite all this, the report dropped it entirely.

**Impact of the miss:**
- Inventory shows 22/23 routers — the summary line "Total routers reviewed: 22" is incorrect
- At least 2 real findings were discarded (H5: missing response_model on 2 STAC endpoints; M2: N+1 extent queries in STAC collections list)
- The endpoint count of ~152 is short by ~6

---

## Line Number Accuracy

The report cites specific line numbers for each finding. Spot-checks found minor shifts (H3 says line 446, actual is 463; L6 says line 314, actual is 331) but these are normal code drift, not substantive errors. The findings are accurate at the cited locations with shifted offsets.

---

## Finding Quality Assessment

For the 22 routers that were covered, the finding quality is high:

- **C1** and **C2**: Both are real, security-relevant issues with precise code context and correct fix proposals.
- **H1–H7**: All confirmed accurate. H4 (trailing slash inconsistency) and H6 (missing pagination) are well-documented with actionable fixes.
- **M1–M4**: All confirmed. M3 (missing cache invalidation) is particularly high-quality — the report identifies the exact pattern (DELETE has it, PATCH doesn't).
- **L1–L6**: All confirmed. L2 (double-await) and L3 (duplicate constant) are precise.
- **Enhancements**: All 6 are well-motivated with code examples.

The 4 actual invalidations (jobs C1, double require_permission C4, httpx M5) are all correct — no false positives among the actual invalidations.

---

## Requirements Coverage

| Requirement | Status | Notes |
|-------------|--------|-------|
| AUDIT-ALL (all routers reviewed) | PARTIAL | 22/23 routers reviewed. STAC router missed. |
| Findings grouped by severity | SATISFIED | CRITICAL / HIGH / MEDIUM / LOW / Enhancements sections present |
| Each finding includes file path, line number, code snippet, fix | SATISFIED | All 25 findings meet this bar |
| Research findings verified against source | PARTIAL | 21/22 source verifications correct; STAC invalidation is wrong |
| Report is actionable | SATISFIED | Developer can implement any finding without additional investigation |

---

## Anti-Patterns in Report

None found. The report does not contain placeholders or incomplete findings. The issue is a factual error (STAC claimed absent), not a format or completeness problem with the findings that are present.

---

## Human Verification Not Required

All verification was performed programmatically against source files. No UI, real-time, or external service behavior to assess.

---

## Gaps Summary

The report achieves its goal for 22 of 23 routers. The single gap is that `stac/router.py` — a 545-line, 6-endpoint router fully registered in main.py — was incorrectly declared non-existent in the Verification Notes. Two valid findings from RESEARCH.md were dropped as a result (missing response_model on 2 STAC endpoints; N+1 queries in STAC collections list). The fix is targeted: add the STAC router to the inventory table, restore the two STAC findings at their correct locations (H5 already exists for tiles, so STAC entries should be added there; M2 is a new finding), and correct the false invalidation note. All other content in the report is accurate and high-quality.

---

_Verified: 2026-03-27_
_Verifier: Claude (gsd-verifier)_
