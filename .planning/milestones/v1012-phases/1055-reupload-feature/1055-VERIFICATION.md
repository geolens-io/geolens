---
phase: 1055
status: passed
verified_at: 2026-05-19
must_haves_score: 1/1
must_haves_total: 1
human_verification:
  count: 0
  items: []
---

# Phase 1055 Verification — Reupload Feature

**Status:** PASSED (1/1 must-have verified)
**Verified:** 2026-05-19 via live Playwright MCP on rebuilt `localhost:8080` stack
**Evidence:** `1055-VERIFY.md` (full step-by-step trace)

## Must-Have

| # | Requirement | Plan | Status | Evidence |
|---|-------------|------|--------|----------|
| 1 | IMPORT-04: Reupload reachable + functional + identity-preserving | 01 + 02 + 03 | ✓ PASS | Live MCP: "More" trigger visible → Re-Upload menuitem → ReuploadDialog opens. Backend cross-record-type guard at `aa852239`. Discoverability hardening at `f4b7242a`. Full trace in `1055-VERIFY.md`. |

## Key Finding (Phase Discovery)

**The Reupload feature was already shipped before v1012 began.** The M001 audit missed it because the Playwright DOM snapshot only saw an unlabeled `MoreHorizontal` icon (the affordance was in the overflow kebab, not promoted to primary actions). Phase 1055 pivoted from "build the feature" to:

1. Close the real backend gap (cross-record-type validation guard) — `_assert_compatible_record_type` helper at both `reupload_dataset` and `request_presigned_reupload`, with 3 new pytest cases
2. Harden discoverability so future audits surface the affordance — visible "More" label + HTML title tooltips on overflow items + IMPORT-04 audit-replay e2e regression test
3. Live MCP verification confirming the audit-replay path now PASSES this surface

## Tag Implication for Phase 1056

**Recommend tagging v1012 as v1.2.1 (patch), NOT v1.3.0 (minor).** Phase 1055 did not deliver net-new feature work — it delivered a defect fix + UX polish. The only mild feature-shaped change in v1012 is EW-05 (STAC size-estimate confirmation step), which is also UX polish, not a new capability. Following the v1.2.0 precedent ("minor when features ship"), v1012 = patch.

## Smoke Gate Status (running tally)

| Gate | Status |
|------|--------|
| TypeScript (frontend) | ✓ 0 errors (Phase 1054 close) |
| Vitest (frontend) | ✓ 2028 tests green (Phase 1054 close) |
| Pytest (backend reupload tests) | ✓ 30+ cases green incl. 3 new Plan 1055-01 cross-record-type cases |
| i18n parity (en/de/es/fr) | ✓ Clean across all phases |
| Live MCP affordance check | ✓ Reupload trigger + dialog reachable; 0 console errors at /login; ROUTE-01/02/03/04 visible fixes confirmed |

## Findings Logged

1. **ROUTE-04 partial fix** — Browser-level network 404 log persists for invalid share tokens. JS-layer throw is silenced (Plan 1054-06 fix landed). The "Map not found" UI renders cleanly. The remaining single log line is browser-built-in behavior. Acceptable for the Low-severity finding.
2. **Backend rebuild required pre-MCP** — Project memory's "Stack-restart vs `down -v` decision tree" pattern confirmed; `docker compose up -d --build api worker` picks up backend changes without disturbing pgdata.
3. **Tag-bump reconsideration** — see "Tag Implication" section above.

## Next Action

Phase 1055 closed. Proceed to Phase 1056: Close Gate.
- Recommend tag: **v1.2.1** (patch)
- CHANGELOG `[Unreleased]` should be renamed to `[1.2.1]` per `89f37cca` pattern
