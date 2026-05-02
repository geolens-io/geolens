---
phase: 227
slug: saml-test-fixture-tmp-path
status: ready
nyquist_compliant: true
wave_0_complete: true
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

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 227-01-T01 | 01 | 1 | TESTFIX-01 (prep) | T-227-01 | 5 dirty fixture files restored to HEAD baseline | shell-assert | `git status --porcelain backend/tests/fixtures/saml/idp_response_*.xml.b64 \| grep -c '^ M' \| tr -d ' '` returns `0` | ✅ git CLI | ⬜ pending |
| 227-01-T02 | 01 | 1 | TESTFIX-01 | T-227-02 | `generate_fixtures.main()` accepts `output_dir`; CLI mode unchanged | unit + integration | `cd backend && uv run python -c "from pathlib import Path; from tests.fixtures.saml.generate_fixtures import main; out=Path('/tmp/saml_smoke'); out.mkdir(exist_ok=True); main(output_dir=out); ..."` + `cd backend && uv run pytest tests/test_saml_overlay.py -v` | ✅ existing infra | ⬜ pending |
| 227-02-T01 | 02 | 2 | TESTFIX-03 | T-227-01 | 5 `.xml.b64` files renamed to `.xml.b64.template` via `git mv` | shell-assert | `git status --porcelain \| awk '$1=="R" && $2 ~ /idp_response.*\.xml\.b64$/' \| wc -l` returns `5`; `ls backend/tests/fixtures/saml/idp_response_*.xml.b64.template \| wc -l` returns `5` | ✅ git CLI | ⬜ pending |
| 227-02-T02 | 02 | 2 | TESTFIX-01, TESTFIX-02, TESTFIX-03 | T-227-01, T-227-02 | autouse swap, helper rewrite, 9 callsite migration, Wave 0 fallback test added; pytest exits 0; tracked dir untouched | unit + integration | `cd backend && uv run pytest tests/test_saml_overlay.py -v --tb=short`; `git status --porcelain backend/tests/fixtures/saml/ \| grep -v '^R ' \| wc -l` returns `0` | ❌ W0 (Wave 0 test added inline) | ⬜ pending |
| 227-02-T03 | 02 | 2 | TESTFIX-02 | T-227-01 | CI guard step asserts `git diff --quiet` post-pytest; pathspec relative to `backend/` | yaml-lint + shell-assert | `python3 -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml'))"`; `grep -q "Verify SAML fixtures unchanged after pytest" .github/workflows/ci.yml`; `grep -q "git diff --quiet -- tests/fixtures/saml/" .github/workflows/ci.yml`; `cd backend && uv run pytest tests/test_saml_overlay.py -v && cd .. && git diff --quiet -- backend/tests/fixtures/saml/ && echo OK` | ✅ existing infra | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

**Wave 0 note:** `test_load_fixture_b64_falls_back_to_template` is created inline within Plan 02 / Task 02 (Edit 6) — it ships in the same task as the helper rewrite it covers. Sampling continuity is preserved because the task's `<verify><automated>` exercises the new test plus all 9 migrated callsites in a single pytest invocation.

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

- [x] All tasks have `<automated>` verify or Wave 0 dependencies (verified — 5/5 tasks)
- [x] Sampling continuity: no 3 consecutive tasks without automated verify (Wave 1: 2/2; Wave 2: 3/3)
- [x] Wave 0 covers all MISSING references (the `test_load_fixture_b64_falls_back_to_template` unit test ships inline in Plan 02 / Task 02 Edit 6)
- [x] No watch-mode flags (no `--watch`, no `pytest-watch`, no `vitest --watch`)
- [x] Feedback latency < 30s for SAML subset (`pytest tests/test_saml_overlay.py` runtime ~30s)
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** approved 2026-05-02 — per-task map populated post-planning; all acceptance criteria mapped to verifiable commands.
