# v1019 Process Retro: REQ Authoring Node-IDs + Executor SUMMARY Checkbox Flip

**Milestone:** v1018 Hygiene — v1017 Tech-Debt Tail (→ v1019 Process Tightening)
**Phase:** 1086
**Requirement:** TD-13
**Date:** 2026-05-22

---

## Why This Retro Exists

The v1018 milestone audit PASSED (8/8 requirements satisfied, 4/4 phases closed, full close-gate green) but surfaced three sub-agent-caught drift incidents — two in REQ authoring and one in executor workflow — that slipped past human review and code review alike. This retro encodes the rules those incidents motivate, and serves as the canonical project-scoped narrative backing the additive edits made to three global GSD skill files at v1019 close.

---

## Incident 1: TD-02/TD-03 Paraphrased Test Names (REQ Authoring)

### What Happened

The v1018 REQUIREMENTS.md cited two test names for TD-02 and TD-03:
- `test_register_password_too_short`
- `test_register_password_diversity`

Neither of these test names exists anywhere in the codebase. The tests that actually close TD-02 and TD-03 are:
- `test_register_emits_user_register_audit`
- `test_register_disabled_does_not_emit_audit`

Both reside at `backend/tests/test_phase_279_user_lifecycle.py` (lines 131 and 187 respectively). The fix shape — updating password fixtures from `"securepass123"` to `"TestPass1234!"` (13 chars, 4/4 SEC-S16 character classes) — was identical regardless of name; the drift was naming-only. The planner caught the discrepancy during Phase 1081 plan creation, before any executor touched the file.

The verbatim audit quote from `v1018-MILESTONE-AUDIT.md`:

> "REQUIREMENTS.md TD-02/TD-03 test names (test_register_password_too_short / test_register_password_diversity) do not exist in code — actual targets are test_register_emits_user_register_audit / test_register_disabled_does_not_emit_audit. Reconciliation documented in PYTEST-BASELINE-v1018.md NEW-DISCOVERY table and CHANGELOG [1.5.3] TD-02/TD-03 entry."

### Cost

The planner had to cross-reference the test file to reconstruct intent, document the discrepancy in `PYTEST-BASELINE-v1018.md` as a NEW-DISCOVERY, and write an explicit CHANGELOG entry calling it out. Any executor that consumed the paraphrased names verbatim would have failed to find the tests via `git grep` and either silently passed the wrong tests or halted.

### Root Cause

The REQ author paraphrased the test's _purpose_ rather than copying the exact `def test_name` symbol. There was no git-grep validation gate to catch the mismatch at commit time.

### Rule Added

This incident motivated the `req_citation_pinning` rule added to `gsd-planner.md`: REQ-cited test names MUST use the exact `path::TestClass::test_name` node-ID form, and the planner MUST validate each cited test exists via `git grep -n "def <test_name>" <path>` before committing CONTEXT.md or REQUIREMENTS.md.

See also: `### Authentication — Code-Pinned Examples` added to `templates/requirements.md` showing AUTH-05 and AUTH-06 in node-ID form.

---

## Incident 2: tasks_common.py Path + Line Drift (REQ Authoring)

### What Happened

The v1017 audit (which fed v1018 CONTEXT.md) cited:
- Path: `backend/app/platform/jobs/tasks_common.py`
- Lines: 231 + 237 (the two `except Exception:` clauses in `_job_phase_session`)

The actual file lives at:
- Path: `backend/app/processing/ingest/tasks_common.py`
- Lines: 232 + 238

Both the module path (`platform/jobs` vs `processing/ingest`) and the line numbers (231/237 vs 232/238) had drifted between the time the v1017 audit was written and the time v1018 planning ran. The planner caught the path drift during Phase 1080 plan creation by running `find` on the repo — the cited path simply did not exist.

The verbatim audit quote from `v1018-MILESTONE-AUDIT.md`:

> "Planner caught (Phase 1080): tasks_common.py path drift in CONTEXT.md (platform/jobs -> processing/ingest); broad-except line numbers off-by-one (231/237 -> 232/238)."

### Cost

The path drift required the planner to locate the actual file before writing the Phase 1080 plan. An executor consuming the stale path verbatim would have opened a non-existent file (or the wrong one if a `platform/jobs/` directory happened to exist). The line drift was minor in isolation but compound with the path drift — an executor citing line 231 would be commenting the wrong source line.

### Root Cause

Production-code citations in REQUIREMENTS.md were written as memory artifacts from a prior audit session rather than validated live against the working tree. No git-grep gate ran at CONTEXT.md or REQUIREMENTS.md commit time.

### Rule Added

This incident motivated the production-code-citation half of the `req_citation_pinning` rule in `gsd-planner.md`: production-code citations MUST include path + line (e.g., `backend/app/processing/ingest/tasks_common.py:232`), and the planner MUST validate the cited line still contains the cited symbol via `git grep -n "<symbol>" <path>` before commit.

---

## Incident 3: Plan 1081-02 SUMMARY Checkbox-Flip Miss (Executor Workflow)

### What Happened

Plan 1081-02 closed TD-05 in code. The executor committed the test mock fix at commit `9eccc80b`. However, the SUMMARY commit at the end of Plan 1081-02 did NOT:
- Flip the REQUIREMENTS.md checkbox from `[ ]` to `[x]` for TD-05
- Flip the traceability-table row from `Pending` to `Complete`

The stale row sat undetected through the rest of Phase 1081 and into the Phase 1083 close-gate, where the integration checker caught it during the v1018 milestone audit. The fix was documentation-only and landed as a separate commit:

**Commit:** `5bf63166` — `docs(1081): mark TD-05 complete in REQUIREMENTS.md traceability`

The verbatim audit quote from `v1018-MILESTONE-AUDIT.md`:

> "TD-05 REQUIREMENTS.md traceability row was stale at audit time (Plan 1081-02 SUMMARY commit did not flip [ ] → [x]); fixed inline mid-audit (commit 5bf63166). Documentation-only — code/test/CHANGELOG all already showed TD-05 complete."

### Cost

The stale row was documentation-only — no code, no tests, no CHANGELOG were wrong. But if the integration checker had not caught it, the milestone audit would have reported `requirements: 7/8` (one row Pending out of eight), failing the pass criterion. The fix commit also breaks the clean commit history for Phase 1081 — the plan's story is now split across two sessions.

### Root Cause

The executor's SUMMARY-commit workflow did not include an explicit step to flip REQUIREMENTS.md before staging. The state-update commands (`gsd-sdk query requirements.mark-complete`) existed but were not enforced with a hard gate.

### Rule Added

This incident motivated the `requirements_traceability_flip` rule added to `gsd-executor.md`: before staging the SUMMARY commit, the executor MUST flip the REQUIREMENTS.md checkbox `[ ]` → `[x]` and the traceability row `Pending` → `Complete` for every requirement ID closed by the plan, and both edits MUST land in the SAME commit as the SUMMARY.md write.

Note: This retro itself is the first plan whose executor obeys the new rule — TD-13's REQUIREMENTS.md flip (checkbox + traceability row) must land in this plan's SUMMARY commit.

---

## Cross-Reference: Where the Rules Live

| Rule | Global Skill File | Section Marker |
|------|-------------------|----------------|
| `req_citation_pinning` — test-name node-ID form + git-grep validation | `/Users/ishiland/.claude/agents/gsd-planner.md` | `<req_citation_pinning>` |
| `req_citation_pinning` — production-code path+line validation | `/Users/ishiland/.claude/agents/gsd-planner.md` | `<req_citation_pinning>` |
| `requirements_traceability_flip` — checkbox + traceability row before SUMMARY commit | `/Users/ishiland/.claude/agents/gsd-executor.md` | `<requirements_traceability_flip>` |
| `Code-Pinned Examples` — AUTH-05/AUTH-06 node-ID example in template | `/Users/ishiland/.claude/get-shit-done/templates/requirements.md` | `### Authentication — Code-Pinned Examples` |

---

## Verification

Skill edits are gated by grep checks in Task 5: each skill file is grepped for its section marker (`req_citation_pinning`, `requirements_traceability_flip`, `Code-Pinned Examples`) and for cross-references to this retro at `.planning/retros/v1019-process.md`. This retro is the canonical project-scoped narrative — the skill files reference it so future maintainers can trace the rule back to the concrete v1018 incidents that motivated it.
