# Phase 1083: Close Gate - Context

**Gathered:** 2026-05-21
**Status:** Ready for planning
**Mode:** Auto-generated (discuss skipped via workflow.skip_discuss)

<domain>
## Phase Boundary

Final close gate for v1018. Capture post-fix pytest baseline showing 0 TD-01..07-attributable failures; run full close-gate protocol (backend pytest sequential + `e2e:smoke:builder` + live Playwright MCP smoke); write `CHANGELOG.md [1.5.3] - 2026-05-21` entry covering all 8 TD items; cut local tag `v1018` + public tag `v1.5.3`. Honest disposition of any residual failures (deferred to v1019 with rationale).

Closes TD-08 from the v1017 milestone audit.

</domain>

<decisions>
## Implementation Decisions

### Required deliverables (from ROADMAP success criteria)
1. `.planning/audits/PYTEST-BASELINE-v1018.md` exists; documents total tests / passes / failures attributable to TD-01..07 (must be 0); honest disposition of residual unexpected failures.
2. Full sequential `uv run pytest backend/` passes all 7 named TD test invocations (TD-01..07) AND the TD-07 unit test, with no skip-mark additions.
3. `npm run e2e:smoke:builder` exits green (no new failures beyond pre-existing documented skips).
4. Live Playwright MCP smoke covers 5 surfaces on `localhost:8080` (catalog list, dataset detail, map builder, map viewer, login/auth surface) — all pass.
5. `CHANGELOG.md` carries `[1.5.3] - 2026-05-21` entry covering TD-01..TD-08.
6. Local tag `v1018` + public tag `v1.5.3` cut at the post-baseline commit.

### Outstanding REQUIREMENTS.md reconciliation
- REQUIREMENTS.md names TD-02/TD-03 test targets as `test_register_password_too_short` / `test_register_password_diversity`. Actual failing tests were `test_register_emits_user_register_audit` / `test_register_disabled_does_not_emit_audit`. Plan 1081-01 closed them; PYTEST-BASELINE-v1018.md should reconcile the naming in its NEW-DISCOVERY table.
- Plan 1080 WR-01 finding (broad-except at `tasks_common.py:1030` + macOS `git grep -E` `\s` portability bug in `test_layering.py`) was fixed inline during code review. This was outside the original 8-TD scope but landed in v1018. CHANGELOG should mention it as a v1018 inline-fix bonus.
- WR-02 finding (test_verify_full_returns_ssl_context_with_verify never actually called database_connect_args) was a pre-existing defect in TD-07-touched code; fixed inline during code review. Same: mention in CHANGELOG as v1018 inline-fix bonus.

### Live MCP surfaces to verify
The v1017 close gate verified these 5 surfaces:
1. Catalog list page
2. Dataset detail page
3. Map builder page
4. Map viewer page
5. Login/auth surface
Mirror for v1018.

</decisions>

<code_context>
## Existing Code Insights

- **Baseline doc precedent**: `.planning/audits/PYTEST-BASELINE-2026-05-21.md` (v1017's TI-03 baseline). Use same shape: total / passed / failed / skipped + NEW-DISCOVERY table for any unexpected failures.
- **CHANGELOG precedent**: Read existing `CHANGELOG.md` `[1.5.2]`, `[1.5.1]`, `[1.5.0]` entries for shape/voice.
- **Stack for live MCP smoke**: needs `docker compose up -d` (db + api + worker + frontend). MCP-driven Playwright requires the orchestrator to invoke browser tools — this is NOT delegable to a subagent (per `project_v1010_e2e_pre_existing_failures` memory + v1017 close gate precedent: live MCP smoke is orchestrator-scoped). Plan should defer the live MCP smoke task to the orchestrator (mark as `autonomous: false` OR leave to the verifier/orchestrator post-execute).
- **Tag cut convention**: from prior milestones — `git tag v1018` (local marker), `git tag v1.5.3` (public marker). Push both manually with `git push origin v1018 v1.5.3` when shipping (per memory: "Push manually with git push origin <tag> when shipping").

</code_context>

<specifics>
## Specific Ideas

- **Plan split**:
  - Plan 1083-01: Capture PYTEST-BASELINE-v1018.md + write CHANGELOG.md [1.5.3] entry (autonomous: true; pure docs work)
  - Plan 1083-02: Full close-gate gate-runs (sequential pytest + e2e:smoke:builder) + cut tags (autonomous: true, gates the tag-cut on green gates)
  - Plan 1083-03: Live Playwright MCP smoke on 5 surfaces (autonomous: false — orchestrator-scoped, cannot be delegated to a subagent)

  OR consolidate to 2 plans (combine 1083-01 and 1083-02 since they're sequential docs+verification work):
  - Plan 1083-01: Baseline capture + close-gate gates + CHANGELOG + tag cuts (autonomous: true)
  - Plan 1083-02: Live Playwright MCP smoke (autonomous: false, orchestrator runs the MCP tools)

</specifics>

<deferred>
## Deferred Ideas

None — Phase 1083 is the last phase of v1018.

</deferred>
