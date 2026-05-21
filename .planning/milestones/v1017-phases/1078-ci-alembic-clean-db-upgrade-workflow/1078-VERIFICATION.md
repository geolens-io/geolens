---
status: passed
phase: 1078
verified: 2026-05-21
verifier: Plan 1078-02
---

# Phase 1078 — CI Alembic Clean-DB Upgrade Workflow: Verification

Single-requirement phase (CI-01) closed by wiring `backend/scripts/test_alembic_upgrade_clean_db.sh` into `.github/workflows/ci.yml` as a peer of the existing backend gates. Plan 1078-02 verifies the YAML is syntactically valid, the structural greps match the plan's acceptance criteria, and the SEC-OBSV-03 observational finding from v1016 Phase 1072 is documentably closed.

## Headline

| Gate | Expected | Actual | Status |
|------|----------|--------|--------|
| `python3 -c "import yaml; yaml.safe_load(...)"` exit code | 0 | 0 | PASS |
| `^      alembic:` in outputs block | one line | line 26 | PASS |
| `^            alembic:` in filters block | one line | line 48 | PASS |
| `^  alembic-clean-db:` (new job) | one line | line 462 | PASS |
| `test_alembic_upgrade_clean_db.sh` reference | one line in `run:` | line 486 | PASS |

## CI-01 Closure Evidence

CI-01 (v1017 requirement; closes SEC-OBSV-03 from v1016 Phase 1072 triage) — the v1016 Phase 1071 script that exercises `alembic upgrade head` against a freshly-built PostGIS+pgvector container is now wired into a CI job that fails the build on migration regressions.

| Acceptance grep | Expected | Actual | Status |
|---|---|---|---|
| `grep -nE "^      alembic:" .github/workflows/ci.yml` | one line | `26:      alembic: ${{ steps.filter.outputs.alembic }}` | PASS |
| `grep -nE "^            alembic:" .github/workflows/ci.yml` | one line | `48:            alembic:` | PASS |
| `grep -nE "^  alembic-clean-db:" .github/workflows/ci.yml` | one line | `462:  alembic-clean-db:` | PASS |
| `grep -n "test_alembic_upgrade_clean_db.sh" .github/workflows/ci.yml` | two lines (filter + run step) | `50: - 'backend/scripts/test_alembic_upgrade_clean_db.sh'` + `486:        run: ./backend/scripts/test_alembic_upgrade_clean_db.sh` | PASS |

Additional structural pins:

| Pin | Expected | Actual | Status |
|---|---|---|---|
| Uses `actions/checkout@v6` (matches `backend-lint`) | true | line 466 | PASS |
| Uses `astral-sh/setup-uv@v8.1.0` with `version: "0.10.2"` | true | lines 468-471 (same shape as `backend-lint:60-64`) | PASS |
| Uses `actions/setup-python@v6` with `python-version: "3.13"` | true | lines 473-475 | PASS |
| Trigger condition matches plan | `needs.changes.outputs.alembic == 'true' \|\| github.event_name == 'push'` | line 464 | PASS |
| Timeout set | `timeout-minutes: 15` | line 465 | PASS |

## YAML Lint Output

`python3 -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml'))" 2>&1 | tee /tmp/1078-02-yamllint.log` → **exit 0**.

```
$ cat /tmp/1078-02-yamllint.log
yaml_lint_exit=0
```

(No stdout from `yaml.safe_load` on success; the single line is the appended exit-code marker.)

## actionlint (Optional Gate)

`actionlint` is not installed on this host. Per Plan 02 Task 1 acceptance criteria ("If actionlint fails but yaml-lint succeeds, document as a warning but continue"), this is **documented as a non-blocking warning**. The structural greps + `yaml.safe_load` pass; first real validation lands when the PR opens against `main` and GitHub's own workflow parser exercises the file.

## SEC-OBSV-03 Closure

`SEC-OBSV-03` (the observational finding from v1016 Phase 1072 triage that flagged `test_alembic_upgrade_clean_db.sh` as built-but-not-wired-to-CI):

| Stage | Phase | Outcome |
|---|---|---|
| Built the script | v1016 Phase 1071 KNOWN-02 | ✅ shipped |
| Triaged the wiring gap as SEC-OBSV-03 | v1016 Phase 1072 | ✅ recorded |
| **Wired the script into `ci.yml`** | **v1017 Phase 1078 Plan 01** | **✅ shipped (commit `40fb9112`)** |

Structural correctness is now verifiable via the YAML lint + the four acceptance greps above. End-to-end validation (the job actually executing against migration-touching changes on a real PR) is **deferred to Phase 1079's close-gate**, which exercises the full `docker compose up -d --build` stack + invokes the script against the rebuilt containers (VG-01 in REQUIREMENTS.md). Phase 1079's first real PR run also lands the workflow's debut execution on `main`.

This split — structural closure now, end-to-end on the next phase — was explicitly forecasted in `1078-CONTEXT.md` "Specific Ideas" section: *"the new job's first PR will be Phase 1078's own commits — we don't get a clean 'did it run on a real PR?' signal until Phase 1079 close-gate. That's acceptable; the structural correctness is verifiable via `actionlint` or YAML parsing."*

## Cross-Plan Interactions

Phase 1078 has only one production-code plan (Plan 01 — `.github/workflows/ci.yml`); Plan 02 is this close-gate and only touches `.planning/` markdown + the 3 milestone tracking files (`STATE.md`, `ROADMAP.md`, `REQUIREMENTS.md`). No cross-plan file overlap.

## Deferred / Out of Scope

- **End-to-end live CI run** — deferred to Phase 1079 close-gate per `1078-CONTEXT.md`. Phase 1079's VG-01 task re-verifies the script against a live `docker compose up -d --build` stack, which doubles as proof that the CI job's container-build sequence is functionally equivalent.
- **`actionlint`** — not installed; non-blocking per Plan 02 Task 1 acceptance criteria.
- **Docker image build caching** — deferred per `1078-CONTEXT.md` "Deferred Ideas". First-run image build is ~2-3 min; revisit if v1017 close-gate (Phase 1079) flags the alembic-clean-db job as a CI bottleneck.
- **Matrix testing across multiple Postgres versions (17, 16)** — deferred per `1078-CONTEXT.md`; not needed until multi-version production support.
- **Wiring into `release.yml` for tag-push verification** — deferred per `1078-CONTEXT.md`; separate scope.

## Requirements Closure

| Requirement | Phase | Status |
|---|---|---|
| **CI-01** — Wire `test_alembic_upgrade_clean_db.sh` into GitHub Actions | Phase 1078 | **Complete** |
| **SEC-OBSV-03** (v1016 Phase 1072 observational) — alembic-clean-DB CI gate | Phase 1078 | **Closed** |

CI-01 is the only v1017 requirement assigned to this phase. See `1078-01-SUMMARY.md` for the per-plan delivery summary and `1078-SUMMARY.md` for the phase-level summary.

## Self-Check: PASSED

All gates green. All 4 acceptance greps from Plan 01 still match against the post-commit working tree. YAML lint exits 0. New job is structurally consistent with the existing `backend-lint` / `openapi-snapshot` / `backend-test` peer set (same `actions/checkout@v6` + `astral-sh/setup-uv@v8.1.0` + `actions/setup-python@v6` pinning).

---

*Phase: 1078-ci-alembic-clean-db-upgrade-workflow*
*Verified: 2026-05-21*
