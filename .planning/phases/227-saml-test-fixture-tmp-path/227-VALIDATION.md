---
phase: 227
slug: saml-test-fixture-tmp-path
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-05-02
---

# Phase 227 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (Python 3.13, `pytest` + `pytest-asyncio` per `backend/pyproject.toml`) |
| **Config file** | `backend/pyproject.toml` (`[tool.pytest.ini_options]`), `backend/tests/conftest.py` |
| **Quick run command** | `cd backend && uv run pytest tests/test_saml_overlay.py -v --tb=short` |
| **Full suite command** | `cd backend && uv run pytest -v --tb=short -m 'not perf'` |
| **Cleanliness check** | `git diff --quiet -- backend/tests/fixtures/saml/ && echo CLEAN || echo DIRTY` (run AFTER pytest) |
| **Estimated runtime** | ~30s for `test_saml_overlay.py` only; ~120s for full backend suite (`-m 'not perf'`) |

---

## Sampling Rate

- **After every task commit:** Run `cd backend && uv run pytest tests/test_saml_overlay.py -v` + cleanliness check (`git diff --quiet -- backend/tests/fixtures/saml/`).
- **After every plan wave:** Run `cd backend && uv run pytest -v -m 'not perf' --no-cov` (skip coverage gate during fast-feedback waves).
- **Before `/gsd-verify-work`:** Full suite must be green AND `git status --porcelain backend/tests/fixtures/saml/` must be empty.
- **Max feedback latency:** ~30 seconds (SAML test subset only — fast loop for fixture-resolution changes).

---

## Per-Task Verification Map

> Populated by gsd-planner during PLAN.md generation. Each task gets a row mapping `task_id → requirement → automated command → status`. The map below is a placeholder skeleton; planner fills concrete task IDs once plans are written.

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 227-XX-YY | XX | N | TESTFIX-01 | — | tmp_path used; no writes to tracked dir | unit + integration | `uv run pytest tests/test_saml_overlay.py -v` + `git diff --quiet -- backend/tests/fixtures/saml/` | ✅ existing infra | ⬜ pending |
| 227-XX-YY | XX | N | TESTFIX-02 | — | git working tree clean post-pytest | shell-assert | `git diff --quiet -- backend/tests/fixtures/saml/; test $? -eq 0` | ✅ git CLI | ⬜ pending |
| 227-XX-YY | XX | N | TESTFIX-03 | — | template files renamed; fallback works | filesystem + unit | `ls backend/tests/fixtures/saml/idp_response_*.xml.b64.template \| wc -l` (must equal 5); `pytest tests/test_saml_overlay.py::test_load_fixture_b64_falls_back_to_template -v` | ❌ W0 (new test) | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `backend/tests/test_saml_overlay.py` — already exists; refactored in this phase (not a Wave 0 stub).
- [ ] `backend/tests/fixtures/saml/generate_fixtures.py` — already exists; refactored in this phase.
- [ ] **NEW unit test (Wave 0):** `test_load_fixture_b64_falls_back_to_template` in `backend/tests/test_saml_overlay.py` — covers the TESTFIX-03 fallback path explicitly (when `saml_response_dir/idp_response_X.xml.b64` is absent, `_load_fixture_b64` reads from `FIXTURE_DIR/idp_response_X.xml.b64.template`). Required because the fallback is the new behavior that distinguishes this phase from a "just regenerate" refactor.
- [ ] No framework install needed — pytest is already configured.
- [ ] No new shared `conftest.py` fixture needed — `saml_response_dir` is co-located in `test_saml_overlay.py` per CONTEXT.md D-06.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| CI guard step actually fires on the regression | TESTFIX-02 (CI side) | Hard to reproduce in unit test — requires a CI run with a deliberately-broken fixture-mutation regression to confirm the `git diff --quiet` step exits non-zero | (a) Make a temp branch reverting the autouse refactor (so pytest mutates the templates again); (b) push to a draft PR; (c) confirm the new "Verify SAML fixtures unchanged after pytest" step in the `backend-test` job fails with the documented error message; (d) discard the branch. |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies (planner fills per-task)
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references (the `test_load_fixture_b64_falls_back_to_template` unit test)
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s for SAML subset
- [ ] `nyquist_compliant: true` set in frontmatter (after planner fills the task table)

**Approval:** pending — planner to populate per-task map.
