---
milestone: v1018
milestone_name: Hygiene — v1017 Tech-Debt Tail
audited: 2026-05-21
status: passed
scores:
  requirements: 8/8
  phases: 4/4
  integration: 8/8
  flows: n/a (hygiene milestone — no E2E user flows added)
gaps:
  requirements: []
  integration: []
  flows: []
tech_debt:
  - phase: 1083
    items:
      - "Pre-existing /maps/new console-noise pattern (2 spurious 422s before Create dialog short-circuits) — v1008 catalog-first empty-state, low-priority frontend cleanup deferred to v1019 (already in REQUIREMENTS.md Future Requirements)"
      - "Pre-existing /api/api/ doubled prefix on legacy quicklook proxy URLs — cosmetic only (all return 200 OK); v13.x scope, not v1018"
      - "Pre-existing 36 TypeScript errors in 14 untouched frontend test files — already deferred per user decision in REQUIREMENTS.md Future Requirements"
      - "pytest -n auto Postgres recovery cascade on 16 xdist workers — environmental cap deferred per user decision"
phases_audited:
  - "1080: Production-Code Drift + Config Hygiene (2 plans, TD-01 + TD-07; 2 inline-fix bonuses WR-01 + WR-02)"
  - "1081: Test Fixture & Assertion Drift (3 plans, TD-02/03 + TD-05 + TD-06)"
  - "1082: Test Environmental (1 plan, TD-04)"
  - "1083: Close Gate (2 plans, TD-08)"
tags:
  local: v1018
  public: v1.5.3
  sha: d1b76061b5aa03299da87cab9da552e8f9e9754c
audit_summary:
  close_gate_results:
    backend_pytest_sequential: "3025 passed / 0 failed / 38 skipped / 0 InvalidCatalogNameError (539.01s)"
    backend_pytest_td_named_invocations: "12/12 passed (5.49s) — all 7 named TD test invocations + TD-07 unit tests green"
    frontend_typecheck: "exit 0 (36 pre-existing test-file errors match v1017 baseline — v1019 frontend hygiene candidate)"
    frontend_vitest: "2105/2105 passed (213 test files)"
    e2e_smoke_builder: "25 passed / 1 skipped (matches v1017 baseline exactly)"
    live_mcp_smoke: "5/5 surfaces PASS on localhost:8080 (0 console errors aggregated across all surfaces; 0 failed network requests)"
  integration_verdict: PASSED
  requirements_coverage: "8/8 satisfied via REQUIREMENTS.md ↔ VERIFICATION.md ↔ SUMMARY.md cross-check"
  inline_review_fixes:
    - "Phase 1080 WR-01: third broad-except at tasks_common.py:1030 + macOS git grep -E \\s portability bug in test_layering.py (commit 4f9160cf)"
    - "Phase 1080 WR-02: test_verify_full_returns_ssl_context_with_verify never actually called database_connect_args — pre-existing defect in TD-07-touched code, fixed inline (commit 200b829a)"
  documentation_reconciliation:
    - "Phase 1083: REQUIREMENTS.md TD-02/TD-03 test names (test_register_password_too_short / test_register_password_diversity) do not exist in code — actual targets are test_register_emits_user_register_audit / test_register_disabled_does_not_emit_audit. Reconciliation documented in PYTEST-BASELINE-v1018.md NEW-DISCOVERY table and CHANGELOG [1.5.3] TD-02/TD-03 entry."
    - "Phase 1080 path correction (caught by planner): tasks_common.py lives at backend/app/processing/ingest/, not backend/app/platform/jobs/ as v1017 audit cited; lines 232/238 not 231/237."
    - "Phase 1082 patch-target nuance (caught by executor via Rule 1 deviation): caller-namespace vs defining-module patch target depends on whether the production import is module-top from-import or lazy function-body from-import. v1018 surfaced this as a generalisable rule."
  deferred_to_v1019:
    count: 0
    items: []
  followup_observations:
    - "TD-05 REQUIREMENTS.md traceability row was stale at audit time (Plan 1081-02 SUMMARY commit did not flip [ ] → [x]); fixed inline mid-audit (commit 5bf63166). Documentation-only — code/test/CHANGELOG all already showed TD-05 complete."
nyquist: { compliant_phases: 0, partial_phases: 0, missing_phases: 4, overall: "n/a — research disabled, validation not applicable (hygiene milestone)" }
---

# v1018 Hygiene — v1017 Tech-Debt Tail — Milestone Audit

**Audited:** 2026-05-21
**Verdict:** PASSED
**Tags:** `v1018` (local) + `v1.5.3` (public) at commit `d1b76061`

## Definition of Done

v1018 shipped when:
- All 8 requirements satisfied (TD-01 through TD-08)
- All 4 phases (1080-1083) closed with passing VERIFICATION
- Full close-gate protocol green (pytest sequential + e2e:smoke:builder + live MCP smoke)
- CHANGELOG `[1.5.3] - 2026-05-21` entry written covering all 8 TD items
- Tags `v1018` + `v1.5.3` cut at the same commit

**All criteria met.**

## Phase-by-Phase Outcomes

| Phase | Goal | Requirements | Plans | Verdict |
|-------|------|--------------|-------|---------|
| 1080 | Production-code drift + config hygiene | TD-01, TD-07 | 2 | PASSED (3/3 SCs; 2 inline WR fixes during code review) |
| 1081 | Test fixture & assertion drift | TD-02, TD-03, TD-05, TD-06 | 3 | PASSED (5/5 SCs; all 3 plans clean) |
| 1082 | Test environmental | TD-04 | 1 | PASSED (3/3 SCs; executor Rule 1 deviation correctly adjusted patch target) |
| 1083 | Close gate | TD-08 | 2 | PASSED (5/5 SCs; 5/5 MCP surfaces; tags cut) |

## Headline Deliverables

### Production-code drift + config hygiene (Phase 1080)
- **TD-01:** Two `except Exception:` clauses in `_job_phase_session` at `backend/app/processing/ingest/tasks_common.py:232,238` justified with same-line `# broad: caller-yielded block may raise any exception; we must rollback the session before re-raising to avoid pool leak` comments. Pinned by `test_layering.py::test_no_unjustified_broad_except_sites` (exit 0).
- **TD-07:** `backend/app/core/config.py:database_connect_args` `if/elif` chain restructured to make the `disable` branch EXPLICIT with `connect_args["ssl"] = False`. 9-test pin in `TestDatabaseConnectArgs` + `TestExternalPooler` (4 + 5 tests, all PASS).
- **WR-01 (inline review fix):** Third broad-except at `tasks_common.py:1030` (`except Exception as first_exc:`) was invisible to the layering test on macOS due to `git grep -E` not expanding `\s` as whitespace. Added `# broad: catch any swap failure to inspect for lock-timeout before re-raising` AND fixed regex from `\s+` to `[ \t]+` (portable ERE) in `test_layering.py:1577`. Prevents latent CI failure on Linux.
- **WR-02 (inline review fix):** `test_verify_full_returns_ssl_context_with_verify` was a pre-existing dead test — it constructed a `verify-full` settings object but discarded it and asserted on a `require`-mode object. Restructured to actually call `.database_connect_args` on the verify-full settings, with `certifi.where()` for a valid cafile.

### Test fixture & assertion drift (Phase 1081)
- **TD-02 / TD-03:** Two register-audit test password fixtures (`"securepass123"` at lines 154 and 206) updated to `"TestPass1234!"` (13 chars, 4/4 SEC-S16 classes — passes with maximum margin). Tests actually closed: `test_register_emits_user_register_audit` and `test_register_disabled_does_not_emit_audit`. REQUIREMENTS.md naming drift documented in baseline + CHANGELOG.
- **TD-05:** `patch("app.modules.catalog.sources.security.validate_url_for_ssrf", new=AsyncMock())` added as the FIRST entry in each `with (...)` block at `test_reupload_service.py:211, 339`. Patched at defining-module path (correct for lazy body-level from-import in `tasks_reupload.py:347`). Both companion tests PASS.
- **TD-06:** Added `client` fixture arg to `test_job_phase_session_none_branch_rolls_back_on_exception` at `test_tasks_common_phase_brackets.py:121`. The fixture transitively triggers `conftest.py:369`'s `db_module.async_session = test_session_factory` monkey-patch, which makes the helper's lazy `from app.core.db import async_session` at `tasks_common.py:215` resolve to the per-function test factory. Full-suite reproducer (`pytest tests/test_ingest.py tests/test_tasks_common_phase_brackets.py -x`) now exits 0 (44 passed).

### Test environmental (Phase 1082)
- **TD-04:** `patch("app.modules.catalog.datasets.api.router_reupload.run_service_preview", new=AsyncMock(side_effect=IngestionError(...)))` wraps the `client.post(...)` call in `test_owner_gets_non_404_on_service_preview` at `test_reupload_idor.py:452`. Patched at caller-namespace path because `router_reupload.py:44` uses module-top `from ... import run_service_preview` — defining-module patch would be a silent no-op. Executor caught this nuance via Rule 1 deviation. `IngestionError` side_effect drives the existing `except IngestionError → HTTPException(502)` branch at `router_reupload.py:268-272`, preserving the test's existing `assert status_code in (400, 502)` assertion. Test passes on a macOS host without `ogrinfo` on PATH.

### Close gate (Phase 1083)
- **TD-08:** `.planning/audits/PYTEST-BASELINE-v1018.md` captured (3025 passed / 0 failed / 38 skipped sequentially; 0 `InvalidCatalogNameError`; TD-01..07 attributable failures = 0). Frontend gates: `tsc -b` exit 0, `vitest run` 2105/2105, `e2e:smoke:builder` 25/1 (matches v1017 baseline). CHANGELOG `[1.5.3] - 2026-05-21` covers TD-01..TD-08 + WR-01/02 bonuses. Tags `v1018` + `v1.5.3` both at SHA `d1b76061`. Live Playwright MCP smoke 5/5 surfaces PASS on `localhost:8080` (catalog list, dataset detail, map builder, maps list, login/auth round-trip).

## Cross-Phase Integration

Per integration checker (`gsd-integration-checker`):
- ✅ Phase 1080 production changes byte-identical at v1018 tag (7 `# broad:` sites + `connect_args["ssl"] = False`)
- ✅ Phase 1081 test-only changes — production code from Phase 1080 untouched
- ✅ Phase 1082 TD-04 mock does not collide with Phase 1081 TD-05 SSRF mock (distinct module paths)
- ✅ Phase 1083 baseline captured at v1018 tag state (post-fix delta: +7 passed, −7 failed)
- ✅ CHANGELOG [1.5.3] coverage complete (13 TD-0[1-8] references; WR-01 + WR-02 present)
- ✅ Tag invariant: `v1018` SHA == `v1.5.3` SHA == `d1b76061b5aa03299da87cab9da552e8f9e9754c`
- ✅ REQUIREMENTS.md naming reconciliation documented (TD-02/03 actual test names in NEW-DISCOVERY table + CHANGELOG)
- ✅ `tasks_common.py` at v1018 has 7 justified broad-except sites (lines 232, 238, 403, 419, 514, 652, 1030)

**8/8 requirements integrated; cross-phase invariants intact.**

## Close-Gate Protocol Results

| Gate | Result |
|------|--------|
| `uv run pytest backend/tests/` (sequential) | 3025 passed / 0 failed / 38 skipped / **0 InvalidCatalogNameError** in 539.01s |
| `uv run pytest` (7 named TD targets + TD-07 unit tests) | 12/12 passed in 5.49s |
| `npx tsc -b` (frontend) | exit 0 (36 pre-existing test-file errors match v1017 baseline) |
| `npx vitest run` (frontend) | 2105/2105 pass |
| `npm run e2e:smoke:builder` | 25 passed / 1 skipped (matches v1017 baseline exactly) |
| Live Playwright MCP smoke | **5/5 surfaces green** on `localhost:8080` |
| `CHANGELOG.md [1.5.3]` | At CHANGELOG.md:14 |
| Tags `v1018` + `v1.5.3` | Both cut at `d1b76061` (unpushed) |

## Inline Review Discoveries (Hygiene Bonus)

During code review of Phase 1080:
- **WR-01:** A third broad-except site at `tasks_common.py:1030` was silently invisible to the layering test on macOS due to `git grep -E` BSD-vs-GNU regex behavior (`\s` not expanded as whitespace by Apple Git). The layering test would have flagged this site on Linux CI but never on a Mac dev machine. Fixed inline: added `# broad:` justification AND made the regex portable (`[ \t]+`).
- **WR-02:** A pre-existing dead test (`test_verify_full_returns_ssl_context_with_verify`) was constructing a `verify-full` Settings object then discarding it and asserting on a `require`-mode object — zero coverage for the verify-full branch. Fixed inline by restructuring to actually exercise `verify-full`.

Both fixes landed in the v1018 milestone tag despite being outside the named 8 TD scope. They directly strengthen the TD-01 (layering invariant) and TD-07 (3-branch shape pin) deliverables.

## Documentation Reconciliations (Caught by Sub-Agents)

- **Planner caught (Phase 1080):** `tasks_common.py` path drift in CONTEXT.md (`platform/jobs` → `processing/ingest`); broad-except line numbers off-by-one (`231/237` → `232/238`).
- **Planner caught (Phase 1081):** TD-02/TD-03 test names in REQUIREMENTS.md were paraphrases that don't match any actual function in the codebase. The real tests are `test_register_emits_user_register_audit` and `test_register_disabled_does_not_emit_audit` (line 131 and 187). Documented in PYTEST-BASELINE-v1018.md NEW-DISCOVERY table; CHANGELOG TD-02/TD-03 entry calls this out explicitly.
- **Executor caught (Phase 1082):** Mock-patch target nuance — caller-namespace vs defining-module — depends on whether the production import is module-top `from ... import` (caller-namespace required because the symbol is bound at module load) or lazy function-body `from ... import` (defining-module works because the symbol is re-bound per call). Surfaced this as a generalisable v1018 milestone pattern.
- **Integration checker caught (this audit):** TD-05 REQUIREMENTS.md traceability row was stale at audit time. Fixed inline mid-audit (commit `5bf63166`) — documentation-only, no functional impact.

## v1017 Carryover Status

All 8 v1017-deferred items closed in v1018:
- ✅ TD-1..3, TD-5..7 (6 pytest failures from Phase 1075 NEW-DISCOVERY) → fixed at root cause (Phases 1080 + 1081)
- ✅ TD-4 (ogrinfo environmental gap from Phase 1075) → mock-out (Phase 1082)
- ✅ TD-8 (config.py SSL handling defect from Phase 1079-03) → ssl=False on disable branch + 3-branch pin (Phase 1080)

## Verdict

**PASSED.** All 8 requirements satisfied within their named scope. All 4 phases complete. Full close-gate green (pytest 3025/0/38, frontend 2105/2105, e2e 25/1, live MCP 5/5). Integration verified cross-phase. Zero deferrals to v1019 — the hygiene tail has been fully closed.

Tags `v1018` + `v1.5.3` ready for `git push origin v1018 v1.5.3` when shipping. Run `/gsd-complete-milestone v1018` → `/gsd-cleanup` to archive.

---

*Audited: 2026-05-21*
*Auditor: orchestrator + gsd-integration-checker*
