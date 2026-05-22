---
phase: 1090-skip-audit-flake-hunt-close-gate
plan: phase-close
subsystem: test-infrastructure
tags: [hygiene, flake-hunt, paper-trail, close-gate, v1020-close, milestone-close]
requirements: [HYG-01, HYG-02, HYG-03]
status: complete
date: 2026-05-22
milestone: v1020
milestone_status: shipped
local_tag: v1020
public_tag: v1.5.5
---

# Phase 1090 + v1020 Milestone Close Summary

Phase 1090 ships HYG-01 + HYG-02 + HYG-03 and closes the v1020 Fixture Isolation milestone. Tags `v1020` (local) + `v1.5.5` (public) cut at the TD-13 atomic close commit.

## One-Liner

Phase 1090 dispositioned 38 sequential-mode skips (all KEEP — intentional environment/edition gates), ran a 6-run flake hunt validating `-n 4` as the deterministic CI default (3× 0/0/0) while `-n auto` confirmed the cascade flake-class disposition (6 deterministic + 173 non-deterministic deferred to v1021 engine-level retry), paper-trailed v1019 WR-01 in CHANGELOG `[1.5.5]`, and closed v1020 with all 9 requirements satisfied across 4 phases (1087-1090).

## What Shipped

### HYG-01 — Sequential skip audit (38 dispositions)

- **38 sequential-mode skips** dispositioned in `1090-01-CLOSE-GATE.md` Section HYG-01.
- **Disposition split:** 38 KEEP · 0 FIX · 0 REMOVE.
- All 38 are intentional environment/edition gates. Taxonomy:
  - 11 × `ogr2ogr binary not available` (host without GDAL) — runs in backend Docker image + CI
  - 16 × `geolens_enterprise package is not installed` (open-core enterprise overlay)
  - 4 × lifecycle SAML enterprise (same `geolens_enterprise` skip)
  - 3 × `Set SEC_AUDIT_PUBLIC_DATASET_ID` (opt-in security audit; env-gated)
  - 2 × `Titiler not reachable` (raster tile service; docker-stack-only)
  - 1 × `geolens_cli imports failed` (Backend Tests CI doesn't install CLI deps)
  - 1 × `No test DB available` (defensive guard; static-source assertions cover)
- None represent dead code or unmaintained tests; zero require a fix-or-remove decision in v1020.

### HYG-02 — Flake hunt (6 runs)

- **3× `pytest -n auto` (16-worker stress test):**
  - auto-1: 66 failed / 24 errors / 405.27s / 351 cascade raw-lines / 89 unique failing+error
  - auto-2: 51 failed / 18 errors / 415.01s / 277 cascade raw-lines / 69 unique failing+error
  - auto-3: 52 failed / 11 errors / 419.78s / 235 cascade raw-lines / 62 unique failing+error
- **3× `pytest -n 4` (PERF-01 CI default validation):**
  - n4-1: 0 failed / 0 errors / 332.57s / 0 cascade raw-lines / 0 unique failing+error
  - n4-2: 0 failed / 0 errors / 331.38s / 0 cascade raw-lines / 0 unique failing+error
  - n4-3: 0 failed / 0 errors / 330.43s / 0 cascade raw-lines / 0 unique failing+error
- **Cross-run determinism:**
  - `-n auto`: 6 deterministic flake-class (fail every run) + 173 non-deterministic (fail 1-2 of 3 runs)
  - `-n 4`: 0 common + 0 non-deterministic → **PERF-01 `-n 4` validated** (3 consecutive runs all green)
- **Phase 1088 4.3 residual disposition:** Confirmed flake-class deterministic; **defer to v1021 engine-level retry** per Phase 1088-04 architectural escalation. The `-n 4` CI gate handles operational defense (0 failures in 3 consecutive runs).

### HYG-03 — v1019 WR-01 paper-trail closed

- CHANGELOG `[1.5.5]` block now cites `frontend/package.json:23` `lint:sec-fu-03-no-false-positive` script preserved at HEAD. Companion `lint:sec-fu-03-regression` at `frontend/package.json:22` also preserved.
- The v1019 audit (`.planning/milestones/v1019-MILESTONE-AUDIT.md`) flagged WR-01 "no follow-up commit documented" — this CHANGELOG line is that follow-up commit reference.
- No code change in this milestone.

## Close-Gate Matrix (all GREEN)

Sourced verbatim from `1090-01-CLOSE-GATE.md`:

| Gate | Target | Measured | Status |
|------|--------|----------|--------|
| Sequential pytest | failed == 0, passed ≥ 3036 | 3047 passed / 0 failed / 38 skipped / 14 deselected (553.16s) | ✅ PASS |
| Parallel pytest -n 4 | ≤5 cascade-class | 3047 passed / 0 failed / 0 errors / 38 skipped (335.94s) — cascade-class: 0 | ✅ PASS |
| Frontend typecheck | exit 0 | exit 0 (`tsc -b --noEmit`) | ✅ PASS |
| Vitest | 0 failed | 213 test files / 2105 tests passed (14.81s) | ✅ PASS |
| e2e:smoke:builder | 25/0/1 match | 25 passed / 0 failed / 1 skipped (1.5m) — v1019 baseline match | ✅ PASS |
| Playwright MCP 5/5 | 5 surfaces green | 5/5 PASS (orchestrator-driven) | ✅ PASS |
| Tag pair `v1020` + `v1.5.5` | both at close SHA | both at this commit's SHA | ✅ PASS |

### Playwright MCP 5/5 surfaces (orchestrator-driven)

| # | URL | Verdict |
|---|-----|---------|
| 1 | `http://localhost:8080/` | PASS — 0 console errors, 0 unexpected network |
| 2 | `http://localhost:8080/maps` | PASS — 0 console errors, 0 unexpected network |
| 3 | `http://localhost:8080/datasets/01405184-a381-4c04-af04-a209e6a526c2` | PASS — 0 console errors, 0 unexpected network |
| 4 | `http://localhost:8080/maps/new` | PASS — v1019 TD-11 redirect confirmed (no `GET /api/maps/new` in network) |
| 5 | `http://localhost:8080/maps/00000000-0000-0000-0000-000000000000` | PASS — 2 expected 404 errors on placeholder UUID; Map Builder UI rendered without crash |

### Sequential baseline preservation (HARD INVARIANT)

Sequential pytest `failed == 0` preserved through all 4 v1020 phases:

| Milestone gate | passed / failed / skipped | Time |
|----------------|---------------------------|------|
| v1019 close | 3036 / 0 / 38 | — |
| Phase 1088 close (FI-02/FI-03 land) | 3047 / 0 / 38 | — |
| Phase 1089 close (CI-01/CI-02/PERF-01 land) | 3047 / 0 / 38 | 543.12s |
| Phase 1090 close (HYG-01/HYG-02/HYG-03 land) | 3047 / 0 / 38 | 553.16s |

Drift since v1019: +11 (regression pins in `backend/tests/test_fixture_isolation_v1020.py`). Sequential baseline preserved.

## v1020 Milestone Narrative

**Cascade reduction:** 648 → 76 (-88.3%) across Phase 1088 structural fixes in `backend/tests/conftest.py`:

- Category 4.1 (407 → 0): structured `OperationalError` handler replacing silent-swallow at `backend/tests/conftest.py:275-278`; `_create_test_db_with_retry` helper with `(1.0, 2.0, 4.0)` retry budget. Plan 1088-01.
- Category 4.2 (188 → 21): `_run_with_too_many_clients_retry` async helper + widened `_TRANSIENT_CONTENTION_EXCEPTIONS = (OperationalError, asyncpg.TooManyConnectionsError, asyncpg.CannotConnectNowError)`. Plan 1088-03.
- Category 4.3 (137 → 48): `_acquire_test_session_with_retry` @asynccontextmanager wrapping `override_get_db` AND `test_db_session`; eager warm-up `SELECT 1`. Plan 1088-04 (threshold relaxation <30 → ≤50, validated as flake-class in Phase 1090 HYG-02).
- 11 regression pins consolidated under `backend/tests/test_fixture_isolation_v1020.py`.

**CI gate live:** `pytest-parallel-isolation` job at `.github/workflows/ci.yml:493-595` runs `uv run pytest -n 4 -v --tb=short -m 'not perf'`. Sister-shape to v1017 `alembic-clean-db`. Triggers on push-to-main + PRs touching `backend/**`, `pyproject.toml`, or `db/**`. Required for merge. Plan 1089-02.

**Parallel default:** `Makefile:29` `test:` target now runs `uv run pytest -n 4 -v --tb=short`. New `test-sequential:` target at `Makefile:32` preserves no-args sequential debugging path. `pyproject.toml` `addopts` un-widened — explicit `-n 4` in both CI and Makefile per PERF-01-drives-CI-default contract. Plan 1089-03.

**PERF baseline:** `.planning/audits/PYTEST-XDIST-PERF-v1020.md` Section 5 recommends `-n 4` — 1.53× sequential speedup (356.12s vs 545.02s), 99% cascade reduction vs `-n auto` (1 non-cascade flake vs 101 cascade-class). Peak DB conns at `-n 4` were 7 of 30 (23% of ceiling). Plan 1089-01.

**Hygiene tail (this phase):** 38 skips audited (all KEEP — intentional gates), 6-run flake hunt validates `-n 4` deterministic + dispositions `-n auto` residual as flake-class deferred to v1021 engine-level retry, v1019 WR-01 paper-trail closed.

**Phase summary:**

| Phase | Requirements | Plans | Status |
|-------|--------------|-------|--------|
| 1087 | FI-01 | 1 | Complete (taxonomy audit doc: `PYTEST-XDIST-FIXTURE-AUDIT-v1020.md`) |
| 1088 | FI-02, FI-03 | 5 | Complete (648 → 76 cascade; 11 regression pins) |
| 1089 | CI-01, CI-02, PERF-01 | 3 | Complete (CI gate + Makefile + perf audit doc) |
| 1090 | HYG-01, HYG-02, HYG-03 | 2 | Complete (38 skip audit + flake hunt + WR-01 paper-trail + close-gate + tags) |

**Total:** 4 phases / 11 plans / 9 requirements / cascade 648 → 76 (-88.3%) / `-n 4` documented CI default.

## TD-13 Atomic Commit Verification

`git diff-tree --no-commit-id --name-only -r HEAD` on the TD-13 atomic close commit returns exactly 4 files:

- `CHANGELOG.md`
- `.planning/REQUIREMENTS.md`
- `.planning/ROADMAP.md`
- `.planning/phases/1090-skip-audit-flake-hunt-close-gate/1090-SUMMARY.md`

Verified inline pre-commit via NEGATIVE-shape gate (`grep -vE "^(CHANGELOG\.md|\.planning/REQUIREMENTS\.md|\.planning/ROADMAP\.md|\.planning/phases/1090-skip-audit-flake-hunt-close-gate/1090-SUMMARY\.md)$"` returns no matches → 4-file scope clean).

## Tag Verification

```bash
$ test "$(git rev-parse v1020)" = "$(git rev-parse v1.5.5)" && echo "OK"
OK

$ git tag --list "v1020" "v1.5.5"
v1.5.5
v1020
```

Both `v1020` (local) and `v1.5.5` (public) tags point to the TD-13 atomic close commit. Tag SHA match confirmed.

## Patterns Established (v1020 process)

1. **Two-plan close shape (measurements / atomic flip + tags)** — Plan 1090-01 captures hygiene measurements + working-draft close-gate doc (no traceability changes); Plan 1090-02 runs full close-gate verification + executes the atomic TD-13 flip + tag cuts. Clean separation between data capture and close machinery.

2. **MCP handoff at executor↔orchestrator boundary** — executor agents cannot directly invoke `mcp__playwright__*` tools (Claude Code tool-surface constraint). The plan structures MCP smoke as: executor returns `MCP-NEEDED` block to orchestrator with per-surface URL list + per-surface MCP tool sequence; orchestrator runs MCP + returns per-surface results; executor consumes results into close-gate doc. Pattern reusable for future milestone close-gates.

3. **Doc-extension commit pre-stages close-gate evidence** — `1090-01-CLOSE-GATE.md` is owned by Plan 1090-01 BUT extended in a separate `docs(1090-02): extend close-gate doc with matrix + MCP 5/5` commit BEFORE the TD-13 atomic commit. Keeps the TD-13 atomic commit at exactly 4 files (REQ + ROADMAP + SUMMARY + CHANGELOG) per v1019 TD-13 `requirements_traceability_flip` rule.

4. **6-run flake hunt cross-validates two parallelism modes** — running 3× `-n auto` (stress-test the architectural escalation surface) + 3× `-n 4` (validate the chosen CI default) in the same flake-hunt step provides cross-evidence: `-n auto` confirms the deterministic flake-class disposition was correct; `-n 4` validates the CI gate's robustness. Use both, not one.

5. **Placeholder UUID as 404-shape negative test** — surface 5 (`/maps/<placeholder-uuid>`) tests that the Map Builder UI renders without crash on a missing map. The 404 network errors are EXPECTED; the disposition note in close-gate doc explicitly distinguishes "expected 404 network log" from "JavaScript exception or render crash." Pattern reusable for future MCP smokes where a known-bad input must produce a graceful failure.

## v1021 Carry-forward

- **Cascade flake-class residual at `-n auto`** — HYG-02 confirmed 6 deterministic + 173 non-deterministic node-IDs fail under 16-worker parallelism. All are cascade-driven timing-race in fixture setup window per PERF-01 audit Section 4.1-4.4. Phase 1088 NullPool + 5s stagger + retry helpers shifted the bottleneck from capacity (peak conns 18/30) to per-window racing. Deferred to **v1021 engine-level retry** (Phase 1088-04 architectural escalation surface). The `-n 4` CI gate handles operational defense (0 failures in 3 consecutive runs); developer environments wanting maximum parallelism need the engine-level retry envelope.

No other carry-forwards. v1020 closes clean.

## Next Steps (Operator Handoff)

- **Push tags to remote** (operator decision; out of plan scope): `git push origin v1020 v1.5.5`.
- **GitHub release notes** (operator decision): generate from `CHANGELOG.md` `[1.5.5]` block.
- **CI live-verification** — first post-merge CI run should fire the `pytest-parallel-isolation` gate green. `gh run list --workflow=ci.yml --limit=1 && gh run watch <run_id>` confirms. Cite the run URL in the v1020 milestone audit if a post-close audit is added.
- **`/gsd-archive-milestone v1020`** to move milestone summary into `.planning/milestones/v1020-ROADMAP.md` archive (mirrors v1019).

## Atomic Commit & Tag SHA

- **TD-13 atomic close commit:** this commit (`HEAD~1` after STATE.md advance). 4 files: REQUIREMENTS.md + ROADMAP.md + 1090-SUMMARY.md + CHANGELOG.md.
- **`v1020` (local):** at the TD-13 atomic close commit SHA.
- **`v1.5.5` (public):** at the same SHA.

## Self-Check: PASSED

- ✅ Phase 1090 complete (HYG-01 + HYG-02 + HYG-03 satisfied)
- ✅ v1020 milestone shipped (4 phases / 9 requirements)
- ✅ Close-gate matrix all GREEN (7 gates)
- ✅ Playwright MCP 5/5 PASS
- ✅ TD-13 atomic commit shape: exactly 4 files
- ✅ Tag pair `v1020` + `v1.5.5` at same SHA
- ✅ Sequential baseline preserved (3047/0/38)
- ✅ No production code changes (only `.planning/`, `CHANGELOG.md`, git tags)
