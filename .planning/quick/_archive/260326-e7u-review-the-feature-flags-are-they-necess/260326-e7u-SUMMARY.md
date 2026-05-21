---
phase: quick-260326-e7u
plan: 01
subsystem: settings/persistent-config
tags: [feature-flags, review, documentation]
dependency_graph:
  requires: []
  provides: [feature-flag-review-findings]
  affects: []
tech_stack:
  added: []
  patterns: []
key_files:
  created:
    - .planning/quick/260326-e7u-review-the-feature-flags-are-they-necess/260326-e7u-FINDINGS.md
  modified: []
decisions:
  - "All 5 boolean PersistentConfig flags are actively used -- KEEP all, no removals"
  - "ai_send_sample_values exists but has two gaps: missing admin UI toggle and missing test coverage"
  - "All flags align with enterprise extension seams per docs/GTM/repo-split.md"
metrics:
  duration_minutes: 5
  completed: "2026-03-26"
---

# Quick Task 260326-e7u: Feature Flag Review Summary

Review of all boolean PersistentConfig feature flags -- 5 flags verified as actively used with backend enforcement. 4 of 5 have full admin-UI coverage; `ai_send_sample_values` is missing a UI toggle and test coverage.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Verify research claims against source code | (read-only, no commit) | Verified usage sites across backend/frontend |
| 2 | Write FINDINGS.md recommendation document | 4923e653 | 260326-e7u-FINDINGS.md |

## Key Findings

### Flags Reviewed (5 total)

1. **`registration_enabled`** -- KEEP. Core auth control, gates self-registration endpoint and UI.
2. **`ai_enabled`** -- KEEP. Kill switch for all AI features, distinct from missing API keys.
3. **`semantic_search_enabled`** -- KEEP. Independent of ai_enabled, requires pgvector infrastructure.
4. **`require_metadata_for_publish`** -- KEEP. Data governance gate on publish transitions.
5. **`ai_send_sample_values`** -- KEEP. Privacy control for omitting sample data from LLM prompts. Backend-only (3 call sites in ai/service.py and ai/chat_service.py).

### Gaps Identified

4 of 5 flags are fully wired. `ai_send_sample_values` has two gaps:
1. **Missing admin UI toggle** -- not exposed in SettingsAITab.tsx, only changeable via direct API call.
2. **Missing test coverage** -- no tests verify the toggle behavior.

### Repo-Split Alignment

All 5 flags map to enterprise extension seams per `docs/GTM/repo-split.md`:
- `registration_enabled` -- auth seam
- `ai_enabled` -- AI policy seam
- `semantic_search_enabled` -- stays in core (adoption engine)
- `require_metadata_for_publish` -- governance seam
- `ai_send_sample_values` -- AI policy seam

### Optional Follow-Up

1. Add admin UI toggle for `ai_send_sample_values` in SettingsAITab.tsx.
2. Add test coverage for `ai_send_sample_values` toggle behavior.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Corrected ai_send_sample_values analysis**
- **Found during:** Verification step
- **Issue:** Executor incorrectly declared ai_send_sample_values as non-existent. Verifier caught the error.
- **Fix:** FINDINGS.md updated with proper 5th flag analysis including usage sites and gaps.
- **Files modified:** 260326-e7u-FINDINGS.md

## Verification

- FINDINGS.md covers all 5 actual flags with keep/remove/change recommendations: PASS
- No code changes were made (doc-only deliverable per user decision): PASS
- ai_send_sample_values gaps documented (missing UI toggle + tests): PASS
- FINDINGS.md has 160+ lines (>= 80 minimum): PASS

## Self-Check: PASSED

- FINDINGS.md: FOUND
- SUMMARY.md: FOUND
- Commit 4923e653: FOUND
