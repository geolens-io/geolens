---
phase: 1086-process-tightening-close-gate
plan: "01"
subsystem: process/documentation
tags: [process, retro, skill-update, td-13]
dependency_graph:
  requires: []
  provides: [v1019-process-retro, req-citation-pinning-rule, requirements-traceability-flip-rule, node-id-template-example]
  affects: [~/.claude/agents/gsd-planner.md, ~/.claude/agents/gsd-executor.md, ~/.claude/get-shit-done/templates/requirements.md]
tech_stack:
  added: []
  patterns: [additive-skill-edit, cross-reference-retro-pattern]
key_files:
  created:
    - .planning/retros/v1019-process.md
  modified:
    - /Users/ishiland/.claude/agents/gsd-planner.md
    - /Users/ishiland/.claude/agents/gsd-executor.md
    - /Users/ishiland/.claude/get-shit-done/templates/requirements.md
    - .planning/REQUIREMENTS.md
decisions:
  - "Additive edits only for all three global skill files — no rewrites of existing content"
  - "Retro uses verbatim test names, paths, and commit hashes from v1018 audit to prevent the paraphrasing anti-pattern it describes"
  - "TD-13 REQUIREMENTS.md flip is self-referential: this plan is the first to obey the new executor rule it establishes"
metrics:
  duration: "4 minutes"
  completed: "2026-05-22"
  tasks_completed: 5
  files_modified: 4
requirements:
  - TD-13
---

# Phase 1086 Plan 01: Process Tightening (TD-13) Summary

**One-liner:** Repo retro + three additive global GSD skill edits preventing REQ citation paraphrasing and executor SUMMARY checkbox-flip misses, motivated by three v1018 drift incidents.

## What Was Built

### Task 1: v1019 Process Retro
Created `.planning/retros/v1019-process.md` (127 lines) — the canonical project-scoped narrative covering three v1018 documentation-drift incidents: TD-02/03 paraphrased test names, `tasks_common.py` path+line drift, and Plan 1081-02 SUMMARY checkbox-flip miss. Each incident includes verbatim test names/paths/commit hashes and a named rule with a cross-reference table.

**Commit:** `f7a17538`

### Task 2: gsd-planner.md — req_citation_pinning Rule
Inserted `<req_citation_pinning>` block (20 lines) immediately after `</context_fidelity>` in `/Users/ishiland/.claude/agents/gsd-planner.md`. File grew from 1278 to 1296 lines.

**Exact rule text added:**
- Test name citations: `path::TestClass::test_name` form (e.g., `backend/tests/test_phase_279_user_lifecycle.py::TestRegisterAudit::test_register_emits_user_register_audit`)
- Production-code citations: `path:line` form (e.g., `backend/app/processing/ingest/tasks_common.py:232`)
- Validation gate: `git grep -n "def <test_name>" <path>` before committing CONTEXT.md or REQUIREMENTS.md; zero matches = drift, multiple matches = ambiguous
- Origin cross-reference: `.planning/retros/v1019-process.md`

### Task 3: gsd-executor.md — requirements_traceability_flip Rule
Inserted `<requirements_traceability_flip>` block (20 lines) immediately before `<completion_format>` in `/Users/ishiland/.claude/agents/gsd-executor.md`. File grew from 752 to 772 lines.

**Exact rule text added:**
1. Checkbox flip: `[ ]` → `[x]` in requirements body
2. Traceability row flip: `Pending` → `Complete` in the traceability table
- Both must land in the SAME commit as SUMMARY.md write
- Failure mode: surface mismatch to orchestrator if IDs not found, do not skip silently
- Origin: commit `5bf63166` (Plan 1081-02 TD-05 missed flip, caught by integration checker mid-audit)
- Origin cross-reference: `.planning/retros/v1019-process.md`

### Task 4: templates/requirements.md — Code-Pinned Examples
Inserted `### Authentication — Code-Pinned Examples` subsection (14 lines) inside the existing `<template>` block, after AUTH-04 and before `### [Category 2]`. File grew from 231 to 245 lines.

**Exact content added:**
- AUTH-05: `backend/tests/test_auth.py::TestAuthAudit::test_failed_login_emits_audit_event`
- AUTH-06: `backend/app/auth/validators.py:42` + `backend/tests/test_password_policy.py::TestSEC_S16::test_min_length_enforced`
- Cross-reference: `.planning/retros/v1019-process.md`

### Task 5: Cross-Reference Integrity Verification
All four files mutually reference each other. Every section marker in the retro's cross-reference table matches the actual marker in the corresponding skill file. Grep gate exited 0.

## REQUIREMENTS.md TD-13 Flip

Per the new `requirements_traceability_flip` rule (self-referential bootstrap: this is the first plan whose executor must obey the new rule):

- `- [ ] **TD-13**:` → `- [x] **TD-13**:`
- Traceability row: `Pending` → `Complete`

Both flips staged in this SUMMARY commit (same commit as SUMMARY.md write).

| Requirement | Phase | Status |
|-------------|-------|--------|
| TD-13 | Phase 1086 / Plan 1086-01 | Complete |

## Deviations from Plan

None — plan executed exactly as written. The `validated against` phrase gap in the initial Task 2 edit was caught immediately during verification and fixed inline before any commit (not a deviation — part of normal task execution).

## Skill File Diffs Summary (for Plan 02 verification)

### gsd-planner.md — Lines Added

```
<req_citation_pinning>
## CRITICAL: REQ-Cited Code Targets Must Use Validated Node-IDs

When CONTEXT.md or REQUIREMENTS.md cites a specific test name or a specific production-code line, the planner MUST encode the citation as a validated node-ID, NOT as a paraphrase.

**Test name citations:** Use `path::TestClass::test_name` form, e.g.,
`backend/tests/test_phase_279_user_lifecycle.py::TestRegisterAudit::test_register_emits_user_register_audit`.

**Production-code citations:** Use `path:line` form with the symbol context noted, e.g.,
`backend/app/processing/ingest/tasks_common.py:232` (the first `except Exception:` clause inside `_job_phase_session`).

**Validation before commit (validated against git grep):** Before committing CONTEXT.md or REQUIREMENTS.md, the planner MUST validate every cited target:
- For each test name: run `git grep -n "def <test_name>" <path>` and confirm a single match. Zero matches means the cited test does not exist (the v1018 TD-02/TD-03 drift pattern — the citation was a paraphrase, not a real symbol). Multiple matches means the citation is ambiguous and needs a fully-qualified class scope.
- For each production-code path:line: run `git grep -n "<expected symbol>" <path>` and confirm the cited line still contains the cited symbol. The v1018 `tasks_common.py` incident shows how 1-line drift between audit time and plan time can cascade into an executor citing a non-existent line.

**Origin:** v1018 surfaced three drift incidents that this rule prevents (see `.planning/retros/v1019-process.md` for the project-scoped narrative): TD-02/03 paraphrased test names, tasks_common.py path+line drift. The rule was added at v1019 close.
</req_citation_pinning>
```

**Insertion point:** Immediately after `</context_fidelity>` tag (after line 73 in pre-edit file).

### gsd-executor.md — Lines Added

```
<requirements_traceability_flip>
## CRITICAL: Flip REQUIREMENTS.md Before SUMMARY Commit

Before staging the SUMMARY.md commit at the end of a plan, the executor MUST update `.planning/REQUIREMENTS.md` for every requirement ID closed by this plan:

1. **Checkbox flip:** Change `- [ ] **REQ-ID**: ...` to `- [x] **REQ-ID**: ...` in the requirements body.
2. **Traceability row flip:** Change the matching row in the `## Traceability` table from `Pending` to `Complete`.

Both edits MUST land in the SAME commit as the SUMMARY.md write — NOT a follow-up commit. If you discover after a SUMMARY commit that you missed the flip, write a new commit immediately (do not amend).

**Failure mode:** If `.planning/REQUIREMENTS.md` doesn't exist, or if the requirement IDs the plan claims to close aren't found in the file, STOP and surface the mismatch to the orchestrator. Do not silently skip the flip — the stale row will mislead the integration checker and the milestone audit.

**Origin:** v1018 Plan 1081-02 closed TD-05 in code but skipped this flip; the integration checker caught the stale row mid-audit and the flip landed as a documentation-only follow-up commit (`5bf63166`). The rule was added at v1019 close to make the flip part of the executor's standard plan-close workflow. See `.planning/retros/v1019-process.md` in the closing project for the project-scoped narrative.

**What to check:**
- Open `.planning/REQUIREMENTS.md` before staging the SUMMARY commit.
- For each requirement ID in the plan's frontmatter `requirements:` list, confirm the checkbox is `[x]` and the traceability row says `Complete`.
- Stage both `.planning/REQUIREMENTS.md` and the SUMMARY together with `git add`.
</requirements_traceability_flip>
```

**Insertion point:** Immediately before `<completion_format>` tag (before line 722 in pre-edit file).

### templates/requirements.md — Lines Added

```
### Authentication — Code-Pinned Examples

When a requirement targets a specific test or specific production-code line, pin it in
node-ID form so the planner can validate the citation against `git grep` before commit
and the executor can run it directly. This prevents the "paraphrased test name" drift
pattern documented in v1019 (see `.planning/retros/v1019-process.md` in any project that
has run /gsd-complete-milestone v1019).

- [ ] **AUTH-05**: Failed login attempts emit a security audit event, pinned by
  `backend/tests/test_auth.py::TestAuthAudit::test_failed_login_emits_audit_event`
- [ ] **AUTH-06**: Password validation enforces a 12-char minimum + 3-of-4 character-class
  diversity, pinned by `backend/app/auth/validators.py:42` (the `MIN_PASSWORD_LENGTH`
  constant) and `backend/tests/test_password_policy.py::TestSEC_S16::test_min_length_enforced`
```

**Insertion point:** After `- [ ] **AUTH-04**: ...` line, before `### [Category 2]`.

## Threat Flags

None — this plan modifies only documentation files and global process/skill files. No network endpoints, auth paths, file access patterns, or schema changes introduced.

## Known Stubs

None — all four files are complete artifacts with no placeholder content.

## Self-Check: PASSED

- `.planning/retros/v1019-process.md` exists, 127 lines, all required strings present
- `/Users/ishiland/.claude/agents/gsd-planner.md` grew to 1296 lines (>1278), contains `req_citation_pinning`, `path::TestClass::test_name`, `validated against`, `v1019-process.md`
- `/Users/ishiland/.claude/agents/gsd-executor.md` grew to 772 lines (>752), contains `requirements_traceability_flip`, `Flip REQUIREMENTS.md Before SUMMARY Commit`, `5bf63166`, `Traceability row flip`, `v1019-process.md`
- `/Users/ishiland/.claude/get-shit-done/templates/requirements.md` grew to 245 lines (>231), contains `Code-Pinned Examples`, `test_failed_login_emits_audit_event`, `AUTH-05`, `AUTH-06`, `v1019-process.md`
- Cross-reference grep gate: all 9 checks PASSED (mutual references between retro and all 3 skill files)
- REQUIREMENTS.md TD-13: `[x]` checkbox + `Complete` traceability row — both verified
