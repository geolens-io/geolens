# Phase 1081: Test Fixture & Assertion Drift - Context

**Gathered:** 2026-05-21
**Status:** Ready for planning
**Mode:** Auto-generated (discuss skipped via workflow.skip_discuss)

<domain>
## Phase Boundary

Fix four pre-existing pytest failures whose tests have drifted from the production code they pin. None are regressions — the production code moved (v1014 SEC-S16 password policy + v1016 IA-P0-03 SSRF re-validation), and the tests were not updated at the time. Per Phase 1075-05 root-cause-fix protocol: no `pytest.mark.skip` without an explicit issue link.

Closes TD-02, TD-03, TD-05, TD-06 from the v1017 milestone audit.

</domain>

<decisions>
## Implementation Decisions

### Claude's Discretion
All implementation choices are at Claude's discretion — discuss phase skipped per `workflow.skip_discuss=true`. Use the ROADMAP phase goal, success criteria, and codebase conventions (Phase 1075-02/03/04 precedent for SEC-S16 + SSRF assertion drift fixes; existing fixture/teardown patterns for async loop issues).

### Required deliverables (from ROADMAP success criteria)
1. `pytest backend/tests/test_phase_279_user_lifecycle.py::test_register_password_too_short` PASSES — asserts the post-SEC-S16 12-char minimum failure mode (TD-02).
2. `pytest backend/tests/test_phase_279_user_lifecycle.py::test_register_password_diversity` PASSES — uses a password that fails the 3-of-4 class diversity rule under `PASSWORD_REQUIRE_CLASSES` default (TD-03).
3. Both `pytest backend/tests/test_reupload_service.py::TestServiceReuploadWorker::test_reupload_service_preserves_identity_and_increments_version` AND `…::test_reupload_service_without_token_returns_retry_guidance_on_auth_failure` PASS in one commit — mocks/fixtures satisfy the v1016 IA-P0-03 `validate_url_for_ssrf` re-validation surface (TD-05).
4. `pytest backend/tests/test_tasks_common_phase_brackets.py::test_job_phase_session_none_branch_rolls_back_on_exception` PASSES in **full-suite sequential mode** (not just isolation) — async loop contamination resolved at fixture/teardown level (TD-06).
5. All four target tests pass together in a single sequential `pytest` invocation, with ZERO `pytest.mark.skip` decorators added.

</decisions>

<code_context>
## Existing Code Insights

- **TD-02 / TD-03 — SEC-S16 password policy**: v1014 SEC-S16 introduced `validate_password_complexity` with a 12-char minimum and a 3-of-4 class diversity rule (configurable via `PASSWORD_MIN_LENGTH` / `PASSWORD_REQUIRE_CLASSES`). Source: `backend/app/modules/auth/password.py` (search for `validate_password_complexity`). The two `test_phase_279_user_lifecycle.py` tests still assert the pre-policy registration responses.

- **TD-05 — SSRF gate drift**: v1016 IA-P0-03 added a second `validate_url_for_ssrf` call inside the reupload_service worker (`backend/app/processing/ingest/reupload_service.py` or `tasks_reupload.py` — search both). The Plan 1075-03 precedent fixed the same shape in `test_ingest.py` — find that diff for the mock-fixture pattern to mirror.

- **TD-06 — async loop contamination**: `test_tasks_common_phase_brackets.py::test_job_phase_session_none_branch_rolls_back_on_exception` passes in isolation but fails in full-suite mode. Phase 1080's executor confirmed this is pre-existing (exit 1 on clean tree, before Plan 1080-01's edit). Three viable fix shapes per the requirement: (a) isolate the loop fixture, (b) tighten session-bracket teardown, (c) refactor the test to avoid cross-test loop state.

- **Phase 1075 precedent**: Plans 1075-02 (test_defer_orphan_guard), 1075-03 (test_ingest), 1075-04 (test_maps_style_json) — all root-cause fixes for the same shape of v1015/v1016 test drift. Read the SUMMARYs at `.planning/milestones/v1017-phases/1075-*/1075-0X-SUMMARY.md` for the patterns used.

</code_context>

<specifics>
## Specific Ideas

- **TD-02 / TD-03 single commit, single root cause**: both tests share the SEC-S16 policy drift. One commit titled `test(1081): TD-02/TD-03 align password policy tests to SEC-S16 (12-char + 3-of-4)` is cleaner than two.
- **TD-05 single commit, two sibling tests**: per REQUIREMENTS.md TD-05 — both companion tests share one root cause, so one commit. Title: `test(1081): TD-05 satisfy SSRF re-validation surface in reupload_service worker tests`.
- **TD-06 separate commit**: distinct fix shape (fixture/teardown vs assertion update). Title: `test(1081): TD-06 fix async loop contamination in test_job_phase_session_none_branch_rolls_back_on_exception`.
- **Plan structure**: 3 plans (or 2 plans grouping TD-02/03/05 + TD-06), each independent — all wave 1.

</specifics>

<deferred>
## Deferred Ideas

None — discuss phase skipped. The 4 environmental + close-gate items are in subsequent phases (1082, 1083).

</deferred>
