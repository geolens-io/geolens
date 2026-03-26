---
phase: quick-260326-e7u
verified: 2026-03-26T00:00:00Z
status: gaps_found
score: 3/4 must-haves verified
gaps:
  - truth: "Each of the 5 PersistentConfig boolean flags has a clear keep/remove/change recommendation with justification"
    status: failed
    reason: "FINDINGS.md incorrectly declares ai_send_sample_values non-existent. The flag IS declared in persistent_config.py:383-388 and IS used in ai/service.py (lines 153, 490, 577) and ai/chat_service.py:534. The document covers only 4 flags instead of 5, and the correction section is factually wrong."
    artifacts:
      - path: ".planning/quick/260326-e7u-review-the-feature-flags-are-they-necess/260326-e7u-FINDINGS.md"
        issue: "Section 'Research Correction: ai_send_sample_values' erroneously declares the flag doesn't exist. It does exist and is actively used. The missing piece is a frontend admin UI toggle, not the flag itself."
    missing:
      - "Analysis of ai_send_sample_values as a real 5th flag: declared in persistent_config.py:383, enforced via _should_send_sample_values() in ai/service.py:153, called at ai/service.py:490+577 and ai/chat_service.py:534, default=True (sends samples), tab=ai"
      - "Correct gap identification: the flag exists and has backend enforcement, but lacks an admin UI toggle in SettingsAITab.tsx — this is a real gap worth documenting"
      - "Updated summary table showing 5 flags with ai_send_sample_values verdict (likely KEEP, with UI gap noted)"
---

# Quick Task 260326-e7u: Feature Flag Review Verification Report

**Task Goal:** Review whether the 5 PersistentConfig boolean feature flags are necessary
**Verified:** 2026-03-26
**Status:** gaps_found
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Each of the 5 PersistentConfig boolean flags has a clear keep/remove/change recommendation with justification | FAILED | FINDINGS.md covers only 4 flags; ai_send_sample_values is declared non-existent but it IS in persistent_config.py:383 and used at ai/service.py:490,577 and ai/chat_service.py:534 |
| 2 | Usage tracing covers both backend and frontend for every flag | FAILED | ai_send_sample_values has no frontend tracing because it was wrongly excluded. The other 4 flags are traced correctly. |
| 3 | Repo-split alignment is assessed for each flag | PARTIAL | Assessed for 4 flags; ai_send_sample_values omitted |
| 4 | Gaps (missing UI toggle, missing tests) are identified | PARTIAL | The FINDINGS.md concludes "no gaps for the 4 existing flags" — but ai_send_sample_values lacks a frontend admin UI toggle, which is a real gap. The Optional Follow-Up section accidentally surfaces this but frames it as a future feature rather than a gap in an existing flag. |

**Score:** 0/4 truths fully verified (3 partially pass for flags 1-4 only)

---

## Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `.planning/quick/260326-e7u-review-the-feature-flags-are-they-necess/260326-e7u-FINDINGS.md` | Feature flag review recommendations document, min 80 lines | STUB (factual error) | File exists, 155 lines, well-structured — but contains a material factual error that invalidates the analysis of the 5th flag |

---

## Key Link Verification

No key_links defined in the plan (doc-only deliverable, no code wiring required).

---

## Data-Flow Trace (Level 4)

Not applicable — doc-only deliverable.

---

## Behavioral Spot-Checks

| Behavior | Check | Result | Status |
|----------|-------|--------|--------|
| ai_send_sample_values declared in persistent_config.py | `grep "ai_send_sample_values" backend/app/persistent_config.py` | Found at line 383-388: `AI_SEND_SAMPLE_VALUES = PersistentConfig[bool](key="ai_send_sample_values", env_default=True, tab="ai", label="Send Sample Values to LLM")` | FAIL — contradicts FINDINGS.md claim |
| _should_send_sample_values() exists in ai/service.py | `grep "_should_send_sample_values" backend/app/ai/service.py` | Found at lines 153, 490, 577 | FAIL — contradicts FINDINGS.md claim |
| ai_send_sample_values has no frontend admin UI toggle | `grep -r "ai_send_sample_values" frontend/src/` | Zero results | PASS — confirms gap exists (correctly identified in Optional Follow-Up but wrongly framed) |

---

## Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| FLAG-REVIEW | 260326-e7u-PLAN.md | Review of all boolean PersistentConfig flags with keep/remove/change recommendations | PARTIAL | 4 of 5 flags reviewed; 5th flag incorrectly excluded due to factual error |

---

## Anti-Patterns Found

| File | Issue | Severity | Impact |
|------|-------|----------|--------|
| 260326-e7u-FINDINGS.md | States "This flag does not exist" for ai_send_sample_values — factually wrong | BLOCKER | The primary deliverable contains a false claim that will mislead future readers and any decision-making based on this document |
| 260326-e7u-FINDINGS.md | "Research Correction" section cites zero grep results for ai_send_sample_values, but the flag was added after the research phase (likely added in the same session that produced the research correction) | BLOCKER | The verification grep in Task 1 apparently ran before the flag was in the codebase, or was scoped incorrectly |
| 260326-e7u-SUMMARY.md | Records "ai_send_sample_values does not exist as a PersistentConfig entry. The research fabricated this flag." — propagates the error | WARNING | Incorrect project memory |

---

## Human Verification Required

None — all issues are code-verifiable.

---

## Gaps Summary

The FINDINGS.md has one critical factual error: it declares `ai_send_sample_values` non-existent. The flag **does exist**:

- **Declared:** `backend/app/persistent_config.py:383-388` as `AI_SEND_SAMPLE_VALUES = PersistentConfig[bool](key="ai_send_sample_values", env_default=True, tab="ai", label="Send Sample Values to LLM")`
- **Backend enforcement:** `backend/app/ai/service.py:153` defines `_should_send_sample_values()` which reads it; called at lines 490, 577 (map generation) and `ai/chat_service.py:534` (chat context)
- **Frontend:** No admin UI toggle in SettingsAITab.tsx — this is a **real gap**

The FINDINGS.md accidentally surfaces the correct fix in the "Optional Follow-Up Ideas" section (item 1) but frames it as adding a future feature rather than documenting a gap in an existing flag. The flag already exists and is functional — it only lacks the UI toggle.

**What needs to be corrected in FINDINGS.md:**

1. Remove the "Research Correction" section (or retitle it as an error)
2. Add a proper Flag 5 analysis for `ai_send_sample_values`:
   - Declaration: `persistent_config.py:383`, default=`True`, tab=`ai`
   - Backend: `_should_send_sample_values()` in `ai/service.py`, called in map generation (x2) and chat (x1)
   - Frontend: No admin UI toggle (gap)
   - Verdict: KEEP — actively used privacy/cost control
   - Gap: Missing admin UI toggle in SettingsAITab.tsx
3. Update summary table to show 5 flags
4. Move the gap (missing UI toggle) from "Optional Follow-Up" to "Identified Gaps"

---

_Verified: 2026-03-26_
_Verifier: Claude (gsd-verifier)_
