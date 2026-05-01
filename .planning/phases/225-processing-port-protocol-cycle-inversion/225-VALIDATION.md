---
phase: 225
slug: processing-port-protocol-cycle-inversion
status: approved
nyquist_compliant: true
wave_0_complete: false
created: 2026-05-01
approved: 2026-05-01
---

# Phase 225 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.x (with pytest-asyncio) |
| **Config file** | `backend/pyproject.toml` (`[tool.pytest.ini_options]`) |
| **Quick run command** | `cd backend && uv run pytest tests/test_processing_port.py tests/test_layering.py -m architecture -x` |
| **Full suite command** | `cd backend && uv run pytest` |
| **Estimated runtime** | Quick: ~10s · Full suite: ~6–9 min (2036 tests) |

---

## Sampling Rate

- **After every task commit:** Run quick command (Port unit test + architecture-guard suite)
- **After every plan wave:** Run full suite command
- **Before `/gsd-verify-work`:** Full suite must be green (2036/2036 baseline) + ruff clean + alembic check clean
- **Max feedback latency:** 15s for quick run, 600s for full suite

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 225-01-* | 01 (additive scaffold) | 1 | PROCESS-01 | — | Protocol importable, default impl no-op via deferred imports | unit / smoke | `cd backend && uv run python -c "from app.core.processing_port import ProcessingPort, get_processing_port; from app.platform.extensions.defaults import DefaultProcessingPort; assert isinstance(DefaultProcessingPort(), ProcessingPort)"` | ❌ W0 (new file) | ⬜ pending |
| 225-02-* | 02 (top-level migration) | 2 | PROCESS-02, PROCESS-03 | — | 8 module-level catalog imports gone from processing/* | static / regression | `cd backend && uv run pytest -x` + `grep -REn "^(from\|import) app\.modules\.catalog" backend/app/processing/ \| grep -v function-scope` | ✅ existing | ⬜ pending |
| 225-03-* | 03 (function-scope migration) | 2 | PROCESS-02, PROCESS-03 | — | All ~24 deferred catalog imports rewritten via Port; behavior unchanged | regression | `cd backend && uv run pytest -x` + `grep -REn "from app\.modules\.catalog" backend/app/processing/` returns 0 hits | ✅ existing | ⬜ pending |
| 225-04-* | 04 (architecture guard + seam test) | 3 | PROCESS-04, PROCESS-05 | — | Guard fails CI on forbidden import; FakeProcessingPort seam test passes | architecture + unit | `cd backend && uv run pytest tests/test_layering.py::test_no_processing_imports_catalog tests/test_processing_port.py -x` | ❌ W0 (new test files) | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `backend/app/core/processing_port.py` — NEW file (PROCESS-01) — Protocol surface + companion structural Protocols + ProcessingPortExtension hook
- [ ] `backend/app/platform/extensions/defaults.py` — MODIFY — append `DefaultProcessingPort` class with deferred-import delegations
- [ ] `backend/app/platform/extensions/__init__.py` — MODIFY — append `get_processing_port()` typed accessor
- [ ] `backend/tests/test_processing_port.py` — NEW test file (PROCESS-03 / D-27) — `FakeProcessingPort` seam test
- [ ] `backend/tests/test_layering.py` — MODIFY — append `test_no_processing_imports_catalog` architecture-guard method + update module docstring

*All Wave 0 items land in commit 1 (additive scaffold) except the architecture-guard test method, which MUST land LAST per D-22 (the test fails until cross-domain catalog imports are gone — see migration sequencing in RESEARCH.md).*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Negative-control verification: architecture guard fails CI when a forbidden import is reintroduced | PROCESS-04 / D-26 | The guard's negative-control proof is a one-time human action — temporarily reintroduce a `from app.modules.catalog` import in (e.g.) `processing/embeddings/backfill.py`, run the test, confirm failure with offending line, revert | (1) Edit `backend/app/processing/embeddings/backfill.py` to re-add `from app.modules.catalog.datasets.domain.models import Record`. (2) `cd backend && uv run pytest tests/test_layering.py::test_no_processing_imports_catalog -x` — expected: FAIL with offending line shown. (3) Revert via `git checkout backend/app/processing/embeddings/backfill.py`. (4) Re-run test — expected: PASS. Document in PLAN 04 verification log. |
| `tasks_raster.py:143` Dataset side-effect F401 import — verify removal vs. keep | PROCESS-02 (D-23 strict zero-hit, no allowlist) | OQ-4 in RESEARCH.md flags as needs-attempt-removal-with-fallback | Attempt removal of `from app.modules.catalog.datasets.domain.models import Dataset  # noqa: F401` at `processing/ingest/tasks_raster.py:143`. Run worker test path — if worker fails to start because `Dataset` is unregistered in `Base.metadata`, restore the import as a documented allowlist exception (amend D-23) and add a Phase 225 `:!` pathspec exclusion in the architecture-guard test for that single line. |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references (Port file, Default impl, accessor, seam test, guard test)
- [ ] No watch-mode flags (pytest runs are one-shot, not `--looponfail`)
- [ ] Feedback latency <15s for quick run
- [ ] `nyquist_compliant: true` set in frontmatter (after planner authors plans + checker passes)

**Approval:** pending
