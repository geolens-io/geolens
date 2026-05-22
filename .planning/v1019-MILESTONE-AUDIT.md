---
milestone: v1019
milestone_name: Hygiene Tail — v1018 Frontend + xdist + Process
audited: 2026-05-22
status: tech_debt
scores:
  requirements: 6/6
  phases: 3/3
  integration: 4/6
  flows: n/a (hygiene milestone — no E2E user flows added)
gaps:
  requirements: []
  integration:
    - "REQUIREMENTS.md: TD-09, TD-11, TD-12 checkboxes still [ ] and traceability rows still
      Pending — Phase 1084 executor completed the work before the TD-13 rule was established and
      never circled back to flip them; Phase 1086-02 only flipped TD-14 (its own requirement)."
    - "ROADMAP.md: Phase 1084 and Phase 1086 phase-list entries still [ ] (unchecked) and all
      three Plan checkboxes for 1084 plus the 1086-02 Plan checkbox are [ ] — not marked complete
      after execution."
    - "ROADMAP.md: v1019 milestone status line still 🚧 (in progress) — not updated to ✅ after
      close-gate PASSED."
  flows: []
tech_debt:
  - phase: 1085
    items:
      - "192 fixture-scope failures exposed by pytest -n auto parallelism (not asyncpg cascade —
        that is closed). Code review REVIEW.md CR-01 classified this as must_have unmet; the
        orchestrator accepted the disposition as v1020-deferred known limitation. Documented in
        CHANGELOG [1.5.4] Known Limitations. Deferred to v1020 as fixture-isolation hygiene task.
        CR-02 (regression test not reaching NullPool branch directly) was addressed post-VERIFICATION
        via commit ea24168c (_make_test_async_engine helper + test). WR-01/WR-02/WR-03 also
        addressed post-VERIFICATION via commits 6488fdf3 and 37b86244."
  - phase: 1084
    items:
      - "WR-01 (missing lint:sec-fu-03-no-false-positive npm script) was addressed after
        Phase 1084 closed — confirmed present in package.json. No follow-up commit documented."
phases_audited:
  - "1084: Frontend Hygiene Tail (3 plans, TD-09/11/12; code review found 2 warnings; WR-01 addressed inline)"
  - "1085: pytest -n auto Stabilization (2 plans, TD-10 spike + fix; code review found 2 critical
    + 3 warnings; CR-01 deferred to v1020, CR-02/WR-01/WR-02/WR-03 addressed via post-verification
    commits ea24168c + 6488fdf3 + 37b86244)"
  - "1086: Process Tightening + Close Gate (2 plans, TD-13 + TD-14)"
tags:
  local: v1019
  public: v1.5.4
  sha: 02cb25db
audit_summary:
  close_gate_results:
    backend_pytest_sequential: "3036 passed / 0 failed / 38 skipped (532s)"
    frontend_typecheck: "exit 0 (TD-09 closed — 37 errors / 15 files cleared)"
    e2e_smoke_builder: "25 passed / 0 failed / 1 skipped (matches v1017/v1018 baseline)"
    live_mcp_smoke: "5/5 surfaces PASS on localhost:8080 (TD-11 + TD-12 regression checks confirmed)"
  integration_verdict: PARTIAL — code complete, traceability docs stale
  requirements_coverage: "6/6 satisfied in code and CHANGELOG; 3/6 not reflected in REQUIREMENTS.md
    checkboxes or traceability table (TD-09/11/12 Pending)"
  deferred_to_v1020:
    count: 1
    items:
      - "192 pytest -n auto fixture-scope failures (not cascade, not regression of TD-10 fix;
        needs fixture-isolation audit in next milestone)"
nyquist: { compliant_phases: 0, partial_phases: 0, missing_phases: 3, overall: "n/a — research disabled,
  validation not applicable (hygiene milestone)" }
---

# v1019 Milestone Audit: Hygiene Tail — v1018 Frontend + xdist + Process

**Audited:** 2026-05-22
**Status:** tech_debt
**Phases:** 1084–1086 (3 phases, 7 plans)
**Tags:** `v1019` (local) + `v1.5.4` (public) both at SHA `02cb25db` — verified

---

## 1. Definition of Done — 6/6 Requirements

All six TD requirements are satisfied in code, tests, and CHANGELOG. Three have stale traceability
in REQUIREMENTS.md (documentation gap, not an implementation gap).

| Req   | Phase | Code Delivered | Verified | REQUIREMENTS.md Checkbox | Traceability Row |
|-------|-------|---------------|----------|--------------------------|-----------------|
| TD-09 | 1084  | 37 TS errors cleared, `typecheck` script added | PASS (MCP + typecheck exit 0) | **[ ] Pending** | **Pending** |
| TD-10 | 1085  | NullPool + 5s stagger; 2452→0 cascade errors | PASS (0 cascade errors, 3032/0/38 sequential) | [x] | Complete |
| TD-11 | 1084  | `<Route path="maps/new">` redirect in App.tsx | PASS (MCP: 0 422s on /maps/new) | **[ ] Pending** | **Pending** |
| TD-12 | 1084  | Dropped `/api` double-prefix in use-quicklook.ts | PASS (MCP: 0 /api/api/ patterns) | **[ ] Pending** | **Pending** |
| TD-13 | 1086  | Retro + 3 global GSD skill file additive edits | PASS (files verified, line counts confirmed) | [x] | Complete |
| TD-14 | 1086  | Docker rebuild; `ssl=False` probed at config.py:309 in both containers | PASS (exit 0 on both probes) | [x] | Complete |

**Verdict:** Implementation coverage is 6/6. Traceability coverage is 3/6 (TD-09/11/12 unchecked).
The gap is a documentation-only omission, not a missing fix. All three items' code is in HEAD
and confirmed by the per-phase VERIFICATION.md and CHANGELOG [1.5.4].

**Root cause of traceability gap:** Phase 1084 was executed and its VERIFICATION.md written before
the TD-13 `requirements_traceability_flip` rule was established by Phase 1086. The new rule was
correctly applied by Phase 1085 (self-applying it preemptively for TD-10) and by Phase 1086 Plan 01
(TD-13 flipped in the same SUMMARY commit). Phase 1086 Plan 02 flipped only its own TD-14 and did
not retroactively flip the three Phase 1084 requirements. No commit in the range 1084..HEAD flips
the TD-09/11/12 checkboxes.

---

## 2. Phase-by-Phase Outcomes

### Phase 1084: Frontend Hygiene Tail — PASSED

**VERIFICATION.md status:** passed

| Plan | Requirement | Deliverable | Gate |
|------|-------------|-------------|------|
| 1084-01 | TD-09 | 37 TS errors cleared across 15 test files; `typecheck` npm script added; 2105/2105 vitest preserved; zero suppression directives | `npm run typecheck` exit 0 |
| 1084-02 | TD-11 | 1-line `<Route path="maps/new">` redirect inserted before `<Route path="maps/:id">` in App.tsx | MCP: 0 422s, URL redirects to /maps |
| 1084-03 | TD-12 | Dropped `/api` prefix from use-quicklook.ts:58; TDD red→green; 8/8 tests pass | MCP: 0 /api/api/ patterns across 10 quicklook fetches |

Code review (1084-REVIEW.md, untracked per project .gitignore pattern) found 2 warnings:
- WR-01: Missing `lint:sec-fu-03-no-false-positive` npm script — addressed; script is present in
  frontend/package.json:23 at HEAD.
- WR-02: `<Route path="maps/new">` missing `errorElement` — confirmed to match the established
  codebase convention for Navigate-only routes (not a new defect); downgraded to info.

### Phase 1085: pytest -n auto Stabilization — PASSED

**VERIFICATION.md status:** passed

| Plan | Requirement | Deliverable | Gate |
|------|-------------|-------------|------|
| 1085-01 | TD-10 (spike) | `.planning/audits/PYTEST-XDIST-SPIKE-v1019.md` committed; all 4 required numbers present; shape (a) chosen with rationale | Spike doc at af902329 |
| 1085-02 | TD-10 (implement) | NullPool for xdist engines + 5s per-worker startup stagger; 2452→0 cascade errors; 7/7 regression tests; sequential 3032/0/38 preserved | `pytest -n auto`: 0 cascade errors |

Code review (1085-REVIEW.md, untracked) found 2 critical + 3 warnings. All addressed:
- CR-01 (192 fixture-scope failures under -n auto, non-zero parallel exit): Accepted as v1020-deferred
  known limitation per orchestrator decision. Documented in CHANGELOG [1.5.4] Known Limitations.
  The cascade goal (0 asyncpg connection-overflow errors) is achieved. The 192 failures are
  pre-existing fixture-isolation issues exposed by parallelism, not new regressions introduced by
  the TD-10 fix. Deferred explicitly to v1020.
- CR-02 (regression test not covering NullPool branch in client fixture): Addressed via commit
  `ea24168c` — `_make_test_async_engine()` helper extracted + test added that asserts NullPool class
  directly. NullPool branch is now directly tested.
- WR-01 (stale 1.5s stagger docstring): Addressed via commit `6488fdf3`.
- WR-02 (dead `_pool_size`/`_max_overflow` variables in xdist branch): Addressed via commit
  `6488fdf3` — docstring updated to document sentinel intent.
- WR-03 (malformed worker ID silently returns 0.0): Addressed via commit `37b86244` — warning
  emitted on malformed worker ID.

Note: CR-02, WR-01, WR-02, WR-03 fixes landed after the per-phase VERIFICATION.md was written but
before the 1086 close-gate. The VERIFICATION.md at HEAD reflects the pre-fix state and does not
mention the post-verification fixes. This is a documentation sequencing artifact, not a quality gap.

### Phase 1086: Process Tightening + Close Gate — PASSED

**VERIFICATION.md status:** passed

| Plan | Requirement | Deliverable | Gate |
|------|-------------|-------------|------|
| 1086-01 | TD-13 | `.planning/retros/v1019-process.md` (127 lines, 3 incidents); `gsd-planner.md` +18 lines (`<req_citation_pinning>`); `gsd-executor.md` +20 lines (`<requirements_traceability_flip>`); `templates/requirements.md` +14 lines (Code-Pinned Examples) | File line counts verified; mutual cross-references pass grep gate |
| 1086-02 | TD-14 | Docker rebuild (api sha256 ea8ca72d, worker sha256 fafca570); dual container probe returned line 309 `connect_args["ssl"] = False` exit 0; CHANGELOG [1.5.4] written; close-gate all gates green; MCP 5/5; STATE.md shipped | CLOSE-GATE.md: PASSED; 5/5 MCP surfaces |

---

## 3. Cross-Phase Integration Checks

| Check | Expected | Actual | Status |
|-------|----------|--------|--------|
| REQUIREMENTS.md TD-10 checkbox | [x] | [x] | PASS |
| REQUIREMENTS.md TD-13 checkbox | [x] | [x] | PASS |
| REQUIREMENTS.md TD-14 checkbox | [x] | [x] | PASS |
| REQUIREMENTS.md TD-09 checkbox | [x] | **[ ]** | **FAIL — documentation only** |
| REQUIREMENTS.md TD-11 checkbox | [x] | **[ ]** | **FAIL — documentation only** |
| REQUIREMENTS.md TD-12 checkbox | [x] | **[ ]** | **FAIL — documentation only** |
| REQUIREMENTS.md TD-10 traceability row | Complete | Complete | PASS |
| REQUIREMENTS.md TD-13 traceability row | Complete | Complete | PASS |
| REQUIREMENTS.md TD-14 traceability row | Complete | Complete | PASS |
| REQUIREMENTS.md TD-09 traceability row | Complete | **Pending** | **FAIL — documentation only** |
| REQUIREMENTS.md TD-11 traceability row | Complete | **Pending** | **FAIL — documentation only** |
| REQUIREMENTS.md TD-12 traceability row | Complete | **Pending** | **FAIL — documentation only** |
| ROADMAP.md Phase 1084 checkbox | [x] | **[ ]** | **FAIL — documentation only** |
| ROADMAP.md Phase 1084 Plan checkboxes (3) | [x] each | **[ ]** each | **FAIL — documentation only** |
| ROADMAP.md Phase 1086 checkbox | [x] | **[ ]** | **FAIL — documentation only** |
| ROADMAP.md Phase 1086 Plan 1086-02 checkbox | [x] | **[ ]** | **FAIL — documentation only** |
| ROADMAP.md v1019 milestone status line | ✅ (shipped) | **🚧 (in progress)** | **FAIL — documentation only** |
| CHANGELOG [1.5.4] entry exists | yes | yes | PASS |
| CHANGELOG covers TD-09..TD-14 | yes | yes | PASS |
| CHANGELOG Known Limitations: 192 failures | yes | yes | PASS |
| Tags v1019 + v1.5.4 at SHA 02cb25db | yes | yes | PASS |
| Spike doc PYTEST-XDIST-SPIKE-v1019.md | yes | yes | PASS |
| Retro .planning/retros/v1019-process.md | yes (127 lines) | yes (127 lines) | PASS |
| gsd-planner.md req_citation_pinning block | yes | yes | PASS |
| gsd-executor.md requirements_traceability_flip block | yes | yes | PASS |
| templates/requirements.md Code-Pinned Examples | yes | yes | PASS |
| ssl=False at config.py:309 in source | yes | yes | PASS |

**Integration score: 4/6 checks clean (REQUIREMENTS and ROADMAP traceability stale)**

All 6 documentation failures are of the same root cause: Phase 1084 was the first phase to execute
under v1019, before the TD-13 traceability-flip rule was established in Phase 1086, and no subsequent
plan retroactively updated the stale fields. The code implementing TD-09/11/12 is present and
verified. This is a process gap, not a delivery gap.

---

## 4. Tag Verification

```
git show v1019 --format="%H" -s  → 02cb25db5510ef103200baf05bb0290700248298
git show v1.5.4 --format="%H" -s → 02cb25db5510ef103200baf05bb0290700248298
```

Both tags point to the same commit as specified in the milestone metadata. Tag pair is clean.

---

## 5. Tech-Debt Followups for v1020

### Item 1 (Phase 1085): 192 pytest -n auto fixture-scope failures

**Status:** v1020-deferred, explicitly documented.
**Nature:** These failures are exposed by xdist parallelism but are not cascade errors (the cascade
is zero). They represent pre-existing fixture-isolation issues: tests that assume global singleton
state (Redis cache, storage provider, `app.dependency_overrides`) that gets written or cleared by
another worker's session-scoped fixtures concurrently. They do not appear in sequential mode because
sequential mode serializes all fixture setup/teardown.
**Evidence:** CHANGELOG [1.5.4] Known Limitations section; 1085-REVIEW.md CR-01 disposition.
**Action for v1020:** Fixture-isolation audit — identify the session-scoped fixtures whose side
effects leak across workers, convert or scope them appropriately.

### Item 2 (Integration): REQUIREMENTS.md + ROADMAP.md stale traceability fields

**Status:** Documentation-only correction needed.
**Nature:** TD-09/11/12 checkboxes still `[ ]`; traceability rows still `Pending`;
ROADMAP.md Phase 1084/1086 and their plan checkboxes still `[ ]`; v1019 milestone status line
still `🚧`. All implementation is complete. This is a mechanical update, not a code change.
**Action:** One commit to flip TD-09/11/12 in REQUIREMENTS.md, mark Phase 1084/1086 complete in
ROADMAP.md, and update the v1019 status line to `✅`. Can be bundled with v1020 roadmap creation
or done as a standalone documentation commit before archiving.

---

## 6. Patterns Established During v1019

**TD-13 bootstrap paradox (fixed-point):** Plan 1086-01 was the first executor to follow the
`requirements_traceability_flip` rule it was writing. It correctly self-applied the rule (TD-13
flipped in same commit as SUMMARY). Phase 1085 also self-applied it preemptively for TD-10 — this
was deliberate ("applied TD-13 lesson preemptively"). Phase 1084 could not apply it because the
rule did not exist when Phase 1084 ran. The resulting stale fields are a bootstrapping artifact,
not a rule violation.

**Spike-first evidence discipline:** Phase 1085's spike-first shape (commit spike doc before
implementing fix) correctly captured the measured numbers and drove the fix decision. The spike
document is comprehensive and reproducible.

**Root-cause discovery under iteration:** Plan 1085-02 required 90 min vs an estimated 30 min
because the spike's initial root-cause hypothesis (runtime pool fan-out) was incomplete — the
cascade also occurred during setup-phase concurrent connections. NullPool alone was insufficient;
the 5s startup stagger was required. The final fix is more robust than the plan anticipated.

**Code-review inline closure pattern:** 1085 CR-02 and WR-01/WR-02/WR-03 were fixed in separate
post-VERIFICATION commits (ea24168c, 6488fdf3, 37b86244) after the phase VERIFICATION was written.
This means the per-phase VERIFICATION.md reflects the pre-fix state. For future milestones, the
verification step should be run after code-review fixes are merged, not before.

**Deferred tech-debt transparency:** CR-01 (192 parallel failures) was not silenced or ignored —
it was explicitly surfaced in CHANGELOG as a Known Limitation with a v1020 attribution. This is
the correct disposition: the cascade goal of TD-10 is met (0 asyncpg errors); the 192 failures
are a separate concern deferred with a named owner.

---

## 7. Close-Gate Results Summary

| Gate | Result | Verdict |
|------|--------|---------|
| Sequential pytest backend | 3036 / 0 / 38 in 532s | PASSED (+11 over v1018 baseline 3025/0/38) |
| e2e:smoke:builder | 25 / 0 / 1 in 1.5 min | PASSED (matches v1017/v1018 baseline) |
| Frontend typecheck | exit 0 | PASSED (TD-09 regression clear) |
| Playwright MCP Surface 1 (`/`) | 0 console errors, 0 /api/api/ patterns | PASSED |
| Playwright MCP Surface 2 (`/maps`) | 0 console errors, 0 /api/api/ patterns | PASSED |
| Playwright MCP Surface 3 (`/datasets/<uuid>`) | 0 console errors | PASSED |
| Playwright MCP Surface 4 (`/maps/new`) | Redirected to /maps; 0 422s; 0 /api/maps/new requests | PASSED (TD-11 check) |
| Playwright MCP Surface 5 (`/maps/<uuid>`) | 0 console errors, 0 /api/api/ patterns; 247 successful requests | PASSED |
| TD-14 Container probe (api) | Line 309: `connect_args["ssl"] = False` exit 0 | PASSED |
| TD-14 Container probe (worker) | Line 309: `connect_args["ssl"] = False` exit 0 | PASSED |
| Tags v1019 + v1.5.4 | Both at SHA 02cb25db | PASSED |

---

## 8. Final Verdict

**Status: tech_debt**

All 6 requirements are implemented and verified. The milestone closes with clean gates (pytest
3036/0/38, e2e:smoke:builder 25/0/1, MCP 5/5, typecheck exit 0, dual container ssl=False probe
PASS). Both tags are cut at the correct SHA.

The `tech_debt` status reflects two items that are not blockers but require follow-up:

1. **REQUIREMENTS.md + ROADMAP.md stale traceability (3 requirements, 2 phases)** — pure
   documentation; all implementation is present and verified. A single follow-up commit corrects
   this before archiving.

2. **192 fixture-scope failures under `pytest -n auto`** — explicitly accepted as a v1020-deferred
   known limitation, documented in CHANGELOG. The TD-10 cascade goal is met. This represents
   unfinished fixture-isolation work that parallelism exposed but did not introduce.

**Recommendation:** Apply a documentation-only fix commit before archiving (flip TD-09/11/12
checkboxes in REQUIREMENTS.md; mark Phase 1084/1086 complete in ROADMAP.md; update v1019 milestone
status to ✅). Then proceed with complete-milestone archive. The v1020 scope should include a
fixture-isolation hygiene phase addressing the 192 parallel failures.

---

_Audited: 2026-05-22_
_Auditor: Claude (gsd-verifier)_
