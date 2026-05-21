# Requirements: v1018 Hygiene — v1017 Tech-Debt Tail

**Defined:** 2026-05-21
**Core Value:** Users can find any dataset in the catalog in seconds — search, see it on a map, understand what it is, and get it out in the format they need.

**Milestone framing:** Hygiene close of the 8 tech-debt items deferred from v1017 (7 NEW-DISCOVERY pytest failures from Plan 1075-05 + 1 production-code defect from Phase 1079-03 VG-01 fix-discovery). No new user-facing features, no migrations. Restore full-suite pytest signal so `backend/tests/` shows zero unexpected failures sequentially. Public tag target: `v1.5.3` (patch).

**Source of truth:** `.planning/v1017-MILESTONE-AUDIT.md` frontmatter `deferred_to_v1018.items` (count: 8).

## v1018 Requirements

Each requirement maps to exactly one phase.

### Production-Code Drift

- [x] **TD-01**: Resolve `test_layering.py::test_no_unjustified_broad_except_sites` — production-code drift. The two broad `except:` clauses at `backend/app/platform/jobs/tasks_common.py:231,237` must either be narrowed to a specific exception class OR carry an in-line justification comment that the layering test recognises. Pin behaviour by running `pytest backend/tests/test_layering.py::test_no_unjustified_broad_except_sites` and confirming it PASSES on a clean tree without skip.

### Test Fixture & Assertion Drift

These failures are pre-existing — the production code has moved (v1014 SEC-S16, v1016 IA-P0-02/03) but the tests were not updated at the time. Each must be fixed at root cause (no `pytest.mark.skip` without an explicit issue link).

- [x] **TD-02**: Fix `backend/tests/test_phase_279_user_lifecycle.py::test_register_password_too_short` — re-align test assertions to v1014 SEC-S16 password policy (12-char minimum, 3-of-4 class diversity, configurable via `PASSWORD_MIN_LENGTH`/`PASSWORD_REQUIRE_CLASSES`). Test must reproduce the post-SEC-S16 failure mode, not the pre-policy one.

- [x] **TD-03**: Fix `backend/tests/test_phase_279_user_lifecycle.py::test_register_password_diversity` — same SEC-S16 policy drift as TD-02 (companion test). Update test to use a password that fails diversity check under the 3-of-4 class rule with the configured `PASSWORD_REQUIRE_CLASSES` default.

- [ ] **TD-05**: Fix `backend/tests/test_reupload_service.py::TestServiceReuploadWorker::test_reupload_service_preserves_identity_and_increments_version` AND `…::test_reupload_service_without_token_returns_retry_guidance_on_auth_failure` — SSRF gate drift. Same root cause Plan 1075-03 closed in `test_ingest.py`: v1016 IA-P0-03 added `validate_url_for_ssrf` re-validation inside the reupload_service worker. Update mocks/fixtures to satisfy the new validation surface. Both companion tests share one root cause → one commit.

- [ ] **TD-06**: Fix `backend/tests/test_tasks_common_phase_brackets.py::test_job_phase_session_none_branch_rolls_back_on_exception` — async loop contamination, full-suite-only failure. Test passes in isolation but fails when other tests have already exhausted/dirtied the async loop. Fix by either: (a) isolating the loop fixture, (b) tightening the session-bracket teardown, or (c) refactoring the test to avoid relying on cross-test loop state.

### Test Environmental

- [ ] **TD-04**: Resolve `backend/tests/test_reupload_idor.py::test_owner_gets_non_404_on_service_preview` — environmental dependency on the `ogrinfo` CLI being on host PATH. Either: (a) gate the test on `which ogrinfo` via `pytest.importorskip` / `pytest.skip(reason=...)` with an explicit env-doc link, OR (b) replace the live `ogrinfo` call with a mock so the test does not depend on host tooling. Decision must be documented in the test docstring.

### Backend Config Hygiene

- [x] **TD-07**: Fix `backend/app/core/config.py:database_connect_args` SSL handling — when `database_ssl_mode == 'disable'`, `connect_args["ssl"]` must be set to `False` (currently the disable path silently lets asyncpg negotiate default TLS). Discovered during Phase 1079-03 VG-01 docker-smoke fix sweep. Low operational priority (production never sets `'disable'`) but the disable branch should be honoured for parity with the documented config surface. Add a unit test pinning the connect_args shape across the 3 ssl-mode branches (`disable`, `require`, default).

### Close Gate

- [ ] **TD-08**: Capture post-v1018 pytest baseline at `.planning/audits/PYTEST-BASELINE-v1018.md`. Full close-gate: backend pytest sequential (must show 0 failures attributable to TD-01..07), `e2e:smoke:builder`, live Playwright MCP smoke. Cut local tag `v1018` + public tag `v1.5.3`. Write `CHANGELOG.md [1.5.3] - 2026-05-21` entry. Honest disposition of any residual failures discovered during close-gate (deferred to v1019 with rationale).

## Future Requirements

Items mentioned in the v1017 audit `tech_debt` section but explicitly deferred beyond v1018:

- **Frontend TS hygiene**: 36 pre-existing TypeScript errors in 14 untouched frontend test files (`tsc -b` exit 0 for build but errors surface in test contexts). Candidate for a dedicated frontend hygiene milestone, not in v1018 scope per user confirmation.
- **Parallel-mode environmental cap**: `pytest -n auto` on 16 xdist workers triggers a Postgres recovery cascade (1363 `CannotConnectNowError`). Different exception class and root cause from TI-01; needs PG `max_connections` tuning OR `-n 4`/`-n 8` host cap OR per-worker pool sizing in conftest. Not a regression.

## Out of Scope

| Feature | Reason |
|---------|--------|
| New user-facing features | v1018 is a patch tag (`v1.5.3`); user-facing capability waits for the next minor/major. |
| Frontend TS error sweep | 36 errors in 14 untouched test files — explicitly deferred per user confirmation; needs its own focused milestone. |
| `pytest -n auto` xdist cap | Environmental cap, not a TI-01 regression; deferred to a separate test-infra milestone. |
| New audits (`/sec-audit`, `/ingest-audit`) at front | v1016 ran both clean on 2026-05-21; v1017 audit verdict PASSED; no new audit pass needed for hygiene-only milestone. |
| Backend API contract changes | None planned — all v1018 changes are test-side, single config-branch fix, baseline capture. OpenAPI snapshot stable. |
| Migrations | No schema changes; no Alembic migrations. |
| Map Builder / Frontend work | v1011.1 closed builder polish; v1018 touches backend test/config only. |
| Cross-repo docs/marketing | Lives in `~/Code/getgeolens.com/`. |

## Traceability

Populated by `gsd-roadmapper` 2026-05-21.

| Requirement | Phase | Status |
|-------------|-------|--------|
| TD-01 | Phase 1080 | Complete |
| TD-07 | Phase 1080 | Complete |
| TD-02 | Phase 1081 | Complete |
| TD-03 | Phase 1081 | Complete |
| TD-05 | Phase 1081 | Pending |
| TD-06 | Phase 1081 | Pending |
| TD-04 | Phase 1082 | Pending |
| TD-08 | Phase 1083 | Pending |

**Coverage:**
- v1018 requirements: 8 total
- Mapped to phases: 8 (100%)
- Unmapped: 0

---

*Requirements defined: 2026-05-21*
*Last updated: 2026-05-21 — traceability filled by gsd-roadmapper*
