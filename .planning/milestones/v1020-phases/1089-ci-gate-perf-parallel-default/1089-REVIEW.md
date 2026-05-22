---
phase: 1089
phase_name: ci-gate-perf-parallel-default
reviewed: 2026-05-22
status: clean
files_reviewed: 2
findings:
  critical: 0
  warning: 0
  info: 0
files_under_review:
  - .github/workflows/ci.yml (+100 lines, new pytest-parallel-isolation job)
  - Makefile (+3 / -1, parallel-default + test-sequential opt-in)
---

# Phase 1089 Code Review — clean

## Files Under Review

- **`.github/workflows/ci.yml`** — new `pytest-parallel-isolation` job inserted at lines 493-595, after `alembic-clean-db`. Mirrors `backend-test` shape verbatim for Postgres/Python/uv setup; replaces `Run tests with coverage` step with `uv run pytest -n 4 -v --tb=short -m 'not perf and not lifecycle'`. Triggers `if: needs.changes.outputs.backend == 'true' || github.event_name == 'push'`. `timeout-minutes: 30`.

- **`Makefile`** — `test:` target switched to `docker compose exec api uv run pytest -n 4 -v --tb=short` (was sequential). New `test-sequential:` target added immediately after `test:` for the explicit sequential opt-in. `test-cov:` at line 30 untouched.

## Quality Verdict

- **YAML valid:** `python3 -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml'))"` exits 0.
- **Sequential baseline:** 3047/0/38 — unchanged from Phase 1088 close.
- **`-n 4` cross-source consistency:** audit Section 4 + Plan 1089-01 SUMMARY + ci.yml:590 + Makefile:27 all agree.
- **No unintended scope:** zero changes to `backend/tests/conftest.py`, `backend/app/*`, `frontend/*`, migrations, or any v1019/v1088 deliverable.
- **CI gate live-verification:** deferred to post-merge `gh run watch` (operator action), documented in Phase 1089 SUMMARY.

No findings. Phase 1089 is clean for verification.
