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
  - "All 4 boolean PersistentConfig flags are actively used -- KEEP all, no removals"
  - "Research-reported ai_send_sample_values flag does not exist in codebase (hallucination corrected)"
  - "docs/GTM/repo-split.md does not exist -- repo-split alignment assessed from general project context"
metrics:
  duration_minutes: 5
  completed: "2026-03-26"
---

# Quick Task 260326-e7u: Feature Flag Review Summary

Review of all boolean PersistentConfig feature flags -- 4 flags verified as actively used with full backend/frontend/admin-UI coverage, research error corrected (ai_send_sample_values does not exist)

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Verify research claims against source code | (read-only, no commit) | Verified 36 usage sites across backend/frontend |
| 2 | Write FINDINGS.md recommendation document | 4923e653 | 260326-e7u-FINDINGS.md |

## Key Findings

### Flags Reviewed (4 total, not 5 as research claimed)

1. **`registration_enabled`** -- KEEP. Core auth control, gates self-registration endpoint and UI.
2. **`ai_enabled`** -- KEEP. Kill switch for all AI features, distinct from missing API keys.
3. **`semantic_search_enabled`** -- KEEP. Independent of ai_enabled, requires pgvector infrastructure.
4. **`require_metadata_for_publish`** -- KEEP. Data governance gate on publish transitions.

### Research Corrections

- **`ai_send_sample_values` does not exist** as a PersistentConfig entry. The research fabricated this flag. `sample_values` is a JSONB data column on Dataset, not a feature flag.
- **`docs/GTM/repo-split.md` does not exist** in the current codebase. Referenced in research but not present.

### Gaps Identified

None for the 4 existing flags. All have backend enforcement, frontend consumption, admin UI toggle, and test coverage.

### Optional Follow-Up

Adding an actual `ai_send_sample_values` PersistentConfig flag would be a legitimate privacy feature -- currently sample data is always sent to LLMs when available.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Corrected flag count from 5 to 4**
- **Found during:** Task 1
- **Issue:** Research claimed 5 boolean feature flags exist, but `ai_send_sample_values` is not a PersistentConfig entry
- **Fix:** FINDINGS.md documents only the 4 real flags and includes a dedicated correction section
- **Files modified:** 260326-e7u-FINDINGS.md

## Verification

- FINDINGS.md covers all 4 actual flags with keep/remove/change recommendations: PASS
- No code changes were made (doc-only deliverable per user decision): PASS
- Research error (ai_send_sample_values) documented and corrected: PASS
- FINDINGS.md has 155 lines (>= 80 minimum): PASS

## Self-Check: PASSED

- FINDINGS.md: FOUND
- SUMMARY.md: FOUND
- Commit 4923e653: FOUND
